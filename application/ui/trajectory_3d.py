"""
3D trajectory view — plots the RocketPy-simulated "ideal" trajectory and the
live GNSS+altimeter trajectory in one local East/North/Up scene, origin at
the launch pad.

Degrades gracefully exactly like ui/attitude_3d.py: if OpenGL is unavailable
on the ground station laptop, it falls back to a numeric/text-only panel
instead of taking the app down.
"""

import traceback

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QWidget

from core.rocket_sim import RocketSimThread, ROCKETPY_AVAILABLE, ROCKETPY_IMPORT_ERROR

# OpenGL is optional at runtime — same guard as ui/attitude_3d.py.
try:
    import pyqtgraph.opengl as gl
    _GL_IMPORT_ERROR = None
except Exception as e:                                       # pragma: no cover
    gl = None
    _GL_IMPORT_ERROR = e


# Decimate the live trace beyond this many points so GLLinePlotItem stays
# cheap for a long flight — halves the buffer rather than dropping the tail.
_MAX_LIVE_POINTS = 2000


class Trajectory3DView(QWidget):
    """Panel with a 3D plot of the ideal (simulated) and live (telemetry) trajectories."""

    # Emitted after a RocketSimThread solve so other views (ui/map_tab.py's
    # ground-track overlay, ui/simulation_tab.py's status label) can react
    # without each owning a second RocketSimThread.
    simulation_complete = pyqtSignal(dict)
    simulation_failed = pyqtSignal(str)

    def __init__(self, parent=None, show_run_button=True):
        super().__init__(parent)

        self._live_points = []  # list of (east_m, north_m, up_m)
        self._sim_thread = None
        self.run_btn = None

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title = QLabel("TRAJECTORY — IDEAL vs LIVE")
        title.setStyleSheet("color:#E0E0E0; font-size:13px; font-weight:bold; letter-spacing:1px;")
        layout.addWidget(title)

        self.view = None
        self.ideal_line = None
        self.live_line = None

        if gl is None:
            layout.addWidget(self._unavailable_label(
                f"3D trajectory unavailable — OpenGL could not be loaded ({_GL_IMPORT_ERROR})."
            ))
        else:
            try:
                self._build_scene()
                layout.addWidget(self.view, stretch=1)
            except Exception as e:
                traceback.print_exc()
                self.view = None
                layout.addWidget(self._unavailable_label(f"3D trajectory unavailable — {e}"))

        self.status_lbl = QLabel("No simulation run yet.")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet(
            "color:#E0E0E0; font-size:13px; font-weight:bold; "
            "background:#141414; border:1px solid #333; border-radius:4px; padding:4px;"
        )
        layout.addWidget(self.status_lbl)

        legend = QLabel(
            '<span style="color:#4C99FF;">■ ideal (RocketPy)</span>&nbsp;&nbsp;'
            '<span style="color:#FF9E42;">■ live (telemetry)</span>'
        )
        legend.setAlignment(Qt.AlignCenter)
        legend.setStyleSheet("font-size:11px;")
        layout.addWidget(legend)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if show_run_button:
            self.run_btn = QPushButton("Run Simulation")
            if not ROCKETPY_AVAILABLE:
                self.run_btn.setEnabled(False)
                self.run_btn.setToolTip(f"rocketpy not installed ({ROCKETPY_IMPORT_ERROR})")
            self.run_btn.clicked.connect(self.run_simulation)
            btn_row.addWidget(self.run_btn)
        if self.view is not None:
            reset_view_btn = QPushButton("Reset View")
            reset_view_btn.setToolTip("Restore the default camera angle (drag to orbit, scroll to zoom)")
            reset_view_btn.clicked.connect(self.reset_view)
            btn_row.addWidget(reset_view_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self.setMinimumHeight(420)
        self.setStyleSheet("background:#1A1A1A; border:1px solid #333; border-radius:6px;")

    # -----------------------------------
    # Scene construction
    # -----------------------------------
    def _build_scene(self):
        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor("#0E0E0E")
        self.view.setMinimumHeight(340)
        # The panel stylesheet would otherwise paint a border over the GL canvas.
        self.view.setStyleSheet("border:none;")
        self.reset_view()

        grid = gl.GLGridItem()
        grid.setSize(x=200, y=200)
        grid.setSpacing(x=20, y=20)
        grid.setColor((90, 90, 90, 90))
        self.view.addItem(grid)

        # Launch pad marker at the local-frame origin.
        pad = gl.GLScatterPlotItem(pos=np.array([[0.0, 0.0, 0.0]]), color=(1, 1, 1, 1), size=12)
        self.view.addItem(pad)

        self.ideal_line = gl.GLLinePlotItem(
            pos=np.zeros((1, 3), dtype=np.float32),
            color=(0.30, 0.60, 1.00, 1.0),
            width=2,
            antialias=True,
        )
        self.view.addItem(self.ideal_line)

        self.live_line = gl.GLLinePlotItem(
            pos=np.zeros((1, 3), dtype=np.float32),
            color=(1.00, 0.62, 0.26, 1.0),
            width=3,
            antialias=True,
        )
        self.view.addItem(self.live_line)

    def reset_view(self):
        """Restore the default camera framing."""
        if self.view is not None:
            self.view.setCameraPosition(distance=300, elevation=20, azimuth=135)

    # -----------------------------------
    # Public API
    # -----------------------------------
    def add_live_point(self, east_m, north_m, up_m):
        """Append one live telemetry point (local ENU meters, origin = launch pad)."""
        self._live_points.append((east_m, north_m, up_m))

        if len(self._live_points) > _MAX_LIVE_POINTS:
            self._live_points = self._live_points[::2]

        if self.view is not None and self.live_line is not None:
            pts = np.array(self._live_points, dtype=np.float32)
            self.live_line.setData(pos=pts)

    def run_simulation(self):
        """Kick off a RocketPy solve on a background thread."""
        if not ROCKETPY_AVAILABLE:
            self.status_lbl.setText("rocketpy not installed — cannot simulate.")
            return
        if self._sim_thread is not None and self._sim_thread.isRunning():
            return

        self.run_btn.setEnabled(False)
        self.status_lbl.setText("Running simulation...")

        self._sim_thread = RocketSimThread()
        self._sim_thread.finished_ok.connect(self._on_sim_ok)
        self._sim_thread.finished_err.connect(self._on_sim_err)
        self._sim_thread.start()

    def reset(self):
        """Clear the live trajectory — used when recording restarts.

        The simulated "ideal" trajectory is left in place: it's a standing
        reference computed once before launch, not per-recording state.
        """
        self._live_points = []
        if self.live_line is not None:
            self.live_line.setData(pos=np.zeros((1, 3), dtype=np.float32))

    # -----------------------------------
    # Internals
    # -----------------------------------
    def _on_sim_ok(self, result):
        if self.run_btn is not None:
            self.run_btn.setEnabled(True)
        self.set_ideal_result(result)
        self.simulation_complete.emit(result)

    def _on_sim_err(self, message):
        if self.run_btn is not None:
            self.run_btn.setEnabled(True)
        self.set_error(message)
        self.simulation_failed.emit(message)

    def set_ideal_result(self, result):
        """Plot an already-solved result and update the status label.

        Public so a second, run-button-less view (ui/simulation_tab.py's
        embedded preview) can mirror a solve driven by this instance's
        RocketSimThread without owning a thread of its own.
        """
        if self.view is not None and self.ideal_line is not None:
            pts = np.column_stack([result["x"], result["y"], result["z"]]).astype(np.float32)
            self.ideal_line.setData(pos=pts)
        self.status_lbl.setText(
            f"Ideal apogee: {result['apogee_agl']:.1f} m AGL   "
            f"Max speed: {result['max_speed']:.1f} m/s"
        )

    def set_error(self, message):
        """Show a solve failure — see set_ideal_result's docstring."""
        self.status_lbl.setText(f"Simulation error: {message}")

    def _unavailable_label(self, message):
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#B0B0B0; font-size:12px; padding:12px;")
        return lbl
