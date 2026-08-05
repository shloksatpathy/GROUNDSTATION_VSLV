"""
3D attitude view — shows vehicle orientation inferred from roll/pitch/yaw.

Renders a fixed reference triad (X=North, Y=West, Z=Up) plus the vehicle's
CAD model and its body triad, rotated by the latest attitude telemetry.

The widget degrades gracefully: if OpenGL is unavailable on the ground station
laptop, it falls back to a numeric-only panel instead of taking the app down.
"""

import os
import traceback

import numpy as np
from pyqtgraph import Transform3D
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QWidget

from core.config import get as cfg_get, resolve_path
from ui.mesh_loader import build_placeholder_mesh, load_mesh, normalize_mesh

# OpenGL is optional at runtime — a missing/blocked GL driver must not stop the
# ground station from showing telemetry.
try:
    import pyqtgraph.opengl as gl
    _GL_IMPORT_ERROR = None
except Exception as e:                                       # pragma: no cover
    gl = None
    _GL_IMPORT_ERROR = e


_SHADER = "attitude_shaded"


def _register_shader():
    """Register a two-light shader for the vehicle mesh.

    pyqtgraph's stock 'shaded' program drops unlit faces to 20% brightness,
    which leaves half of a dark-hulled model unreadable against the panel
    background. This adds a fill light and a rim term so the silhouette and
    the far side of the vehicle both stay legible.
    """
    from pyqtgraph.opengl.shaders import FragmentShader, ShaderProgram, VertexShader

    if _SHADER in ShaderProgram.names:
        return

    ShaderProgram(_SHADER, [
        VertexShader("""
            uniform mat4 u_mvp;
            uniform mat3 u_normal;
            attribute vec4 a_position;
            attribute vec3 a_normal;
            attribute vec4 a_color;
            varying vec4 v_color;
            varying vec3 v_normal;
            void main() {
                v_normal = normalize(u_normal * a_normal);
                v_color = a_color;
                gl_Position = u_mvp * a_position;
            }
        """),
        FragmentShader("""
            #ifdef GL_ES
            precision mediump float;
            #endif
            varying vec4 v_color;
            varying vec3 v_normal;
            void main() {
                vec3 n = normalize(v_normal);
                float key  = max(0.0, dot(n, normalize(vec3( 0.45,  0.55, 0.70))));
                float fill = max(0.0, dot(n, normalize(vec3(-0.60, -0.35, 0.35))));
                float rim  = pow(1.0 - abs(n.z), 3.0);
                vec3 rgb = v_color.rgb * (0.30 + 0.70 * key + 0.22 * fill)
                         + vec3(0.16, 0.20, 0.26) * rim;
                gl_FragColor = vec4(clamp(rgb, 0.0, 1.0), v_color.a);
            }
        """),
    ])


# Body frame used by this view: +X nose/forward, +Y left, +Z up.
# Attitude telemetry follows the aerospace convention (body X forward,
# Y right, Z down), so a 180 deg flip about X converts between the two.
_NED_TO_VIEW = np.diag([1.0, -1.0, -1.0])

_AXIS_COLORS = {
    "x": (1.0, 0.32, 0.32, 1.0),   # roll axis  — red
    "y": (0.30, 0.85, 0.35, 1.0),  # pitch axis — green
    "z": (0.30, 0.60, 1.00, 1.0),  # yaw axis   — blue
}


def attitude_matrix(roll_deg, pitch_deg, yaw_deg):
    """Body->world rotation matrix in the view frame, from Euler angles.

    Uses the standard aerospace intrinsic Z-Y-X sequence (yaw, then pitch,
    then roll) and converts the result into the view's +X/+Y/+Z frame.
    """
    r, p, y = np.radians([roll_deg, pitch_deg, yaw_deg])

    cr, sr = np.cos(r), np.sin(r)
    cp, sp = np.cos(p), np.sin(p)
    cy, sy = np.cos(y), np.sin(y)

    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])

    return _NED_TO_VIEW @ (rz @ ry @ rx) @ _NED_TO_VIEW.T


class Attitude3DView(QWidget):
    """Panel with a 3-axis 3D plot of the vehicle's current orientation."""

    def __init__(self, model_path=None, parent=None):
        super().__init__(parent)

        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self._last_applied = None

        # Sign flips for IMUs that report the opposite handedness.
        invert = cfg_get("attitude_invert", [False, False, False]) or [False, False, False]
        self._sign = np.array([-1.0 if bool(v) else 1.0 for v in invert[:3]])

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title = QLabel("ATTITUDE")
        title.setStyleSheet("color:#E0E0E0; font-size:13px; font-weight:bold; letter-spacing:1px;")
        layout.addWidget(title)

        self.view = None
        self.model_item = None
        self.body_axes = []

        if gl is None:
            layout.addWidget(self._unavailable_label(
                f"3D view unavailable — OpenGL could not be loaded ({_GL_IMPORT_ERROR})."
            ))
        else:
            try:
                self._build_scene(model_path)
                layout.addWidget(self.view, stretch=1)
            except Exception as e:
                # Printed as well as shown: the panel has room for one line,
                # and the packaged build keeps a console open for exactly this.
                traceback.print_exc()
                self.view = None
                layout.addWidget(self._unavailable_label(f"3D view unavailable — {e}"))

        # ---- Numeric readout (always shown, GL or not) ----
        self.readout = QLabel("R —°   P —°   Y —°")
        self.readout.setAlignment(Qt.AlignCenter)
        self.readout.setStyleSheet(
            "color:#E0E0E0; font-size:14px; font-weight:bold; "
            "background:#141414; border:1px solid #333; border-radius:4px; padding:4px;"
        )
        layout.addWidget(self.readout)

        legend = QLabel(
            '<span style="color:#FF5252;">■ roll/X</span>&nbsp;&nbsp;'
            '<span style="color:#4CD964;">■ pitch/Y</span>&nbsp;&nbsp;'
            '<span style="color:#4C99FF;">■ yaw/Z</span>'
        )
        legend.setAlignment(Qt.AlignCenter)
        legend.setStyleSheet("font-size:11px;")
        layout.addWidget(legend)

        if self.view is not None:
            btn_row = QHBoxLayout()
            reset_btn = QPushButton("Reset View")
            reset_btn.setToolTip("Restore the default camera angle (drag to orbit, scroll to zoom)")
            reset_btn.clicked.connect(self.reset_view)
            btn_row.addStretch()
            btn_row.addWidget(reset_btn)
            btn_row.addStretch()
            layout.addLayout(btn_row)

        self.setLayout(layout)
        self.setMinimumHeight(340)
        self.setStyleSheet("background:#1A1A1A; border:1px solid #333; border-radius:6px;")

    # -----------------------------------
    # Scene construction
    # -----------------------------------
    def _build_scene(self, model_path):
        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor("#0E0E0E")
        self.view.setMinimumHeight(240)
        # The panel stylesheet would otherwise paint a border over the GL canvas.
        self.view.setStyleSheet("border:none;")
        self.reset_view()

        grid = gl.GLGridItem()
        grid.setSize(x=4, y=4)
        grid.setSpacing(x=0.5, y=0.5)
        grid.setColor((90, 90, 90, 90))
        self.view.addItem(grid)

        self._add_reference_axes()

        verts, faces = self._load_model(model_path)
        mesh = gl.MeshData(vertexes=verts, faces=faces)

        try:
            _register_shader()
            shader = _SHADER
        except Exception as e:
            print(f"[ATTITUDE] Custom shader unavailable ({e}); using default.")
            shader = "shaded"

        self.model_item = gl.GLMeshItem(
            meshdata=mesh,
            smooth=True,
            shader=shader,
            color=(0.72, 0.78, 0.88, 1.0),
            glOptions="opaque",
        )
        self.view.addItem(self.model_item)

        self._add_body_axes()
        self._apply_transform()

    def _add_reference_axes(self):
        """Dim fixed world triad the vehicle is oriented against."""
        length = 1.6
        specs = [
            ((length, 0, 0), _AXIS_COLORS["x"], "X (N)"),
            ((0, length, 0), _AXIS_COLORS["y"], "Y (W)"),
            ((0, 0, length), _AXIS_COLORS["z"], "Z (U)"),
        ]

        for end, color, label in specs:
            dim = (color[0] * 0.55, color[1] * 0.55, color[2] * 0.55, 0.9)
            line = gl.GLLinePlotItem(
                pos=np.array([[0, 0, 0], end], dtype=np.float32),
                color=dim,
                width=2,
                antialias=True,
            )
            self.view.addItem(line)

            text = gl.GLTextItem(
                pos=np.array(end, dtype=np.float32) * 1.08,
                text=label,
                color=tuple(int(c * 255) for c in dim[:3]),
                font=QFont("Helvetica", 9),
            )
            self.view.addItem(text)

    def _add_body_axes(self):
        """Bright triad rigidly attached to the model, rotated with it."""
        length = 1.4
        self.body_axes = []

        for axis, end in (("x", (length, 0, 0)), ("y", (0, length, 0)), ("z", (0, 0, length))):
            line = gl.GLLinePlotItem(
                pos=np.array([[0, 0, 0], end], dtype=np.float32),
                color=_AXIS_COLORS[axis],
                width=3,
                antialias=True,
            )
            self.view.addItem(line)
            self.body_axes.append(line)

    def _load_model(self, model_path):
        """Load the configured CAD model, falling back to the placeholder."""
        path = model_path or cfg_get("attitude_model_path", "")

        if path:
            resolved = resolve_path(path)
            if os.path.exists(resolved):
                try:
                    verts, faces = load_mesh(resolved)
                    verts = normalize_mesh(
                        verts,
                        target_size=float(cfg_get("attitude_model_size", 2.0)),
                        align_rotation=cfg_get("attitude_model_rotation", None),
                        scale=cfg_get("attitude_model_scale", None),
                    )
                    print(f"[ATTITUDE] Loaded {os.path.basename(resolved)} "
                          f"({len(verts)} verts, {len(faces)} faces)")
                    if len(faces) > 200000:
                        print("[ATTITUDE] Model is very dense — decimate it in CAD "
                              "if the dashboard feels sluggish.")
                    return verts, faces
                except Exception as e:
                    print(f"[ATTITUDE] Could not load {resolved}: {e}. Using placeholder.")
            else:
                print(f"[ATTITUDE] Model not found at {resolved}. Using placeholder.")

        verts, faces = build_placeholder_mesh()
        verts = normalize_mesh(verts, target_size=float(cfg_get("attitude_model_size", 2.0)))
        return verts, faces

    # -----------------------------------
    # Public API
    # -----------------------------------
    def set_attitude(self, roll, pitch, yaw):
        """Push the latest orientation, in degrees. None keeps the last value."""
        if roll is not None:
            self.roll = float(roll)
        if pitch is not None:
            self.pitch = float(pitch)
        if yaw is not None:
            self.yaw = float(yaw)

        self.readout.setText(
            f"R {self.roll:+6.1f}°   P {self.pitch:+6.1f}°   Y {self.yaw:+6.1f}°"
        )
        self._apply_transform()

    def reset(self):
        """Return to level attitude — used when recording restarts."""
        self.roll = self.pitch = self.yaw = 0.0
        self._last_applied = None
        self.readout.setText("R —°   P —°   Y —°")
        self._apply_transform()

    def reset_view(self):
        """Restore the default camera framing."""
        if self.view is not None:
            self.view.setCameraPosition(distance=4.6, elevation=24, azimuth=135)

    # -----------------------------------
    # Internals
    # -----------------------------------
    def _apply_transform(self):
        if self.view is None or self.model_item is None:
            return

        roll, pitch, yaw = self._sign * np.array([self.roll, self.pitch, self.yaw])

        # Skip the GL redraw when nothing moved — update_gui runs at ~20 FPS.
        current = (round(roll, 2), round(pitch, 2), round(yaw, 2))
        if current == self._last_applied:
            return
        self._last_applied = current

        matrix = np.eye(4)
        matrix[:3, :3] = attitude_matrix(roll, pitch, yaw)
        transform = Transform3D(matrix)

        self.model_item.setTransform(transform)
        for line in self.body_axes:
            line.setTransform(transform)

    def _unavailable_label(self, message):
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#B0B0B0; font-size:12px; padding:12px;")
        return lbl
