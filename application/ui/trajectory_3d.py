"""
3D trajectory view — plots the RocketPy-simulated "ideal" trajectory and the
live GNSS+altimeter trajectory in one local East/North/Up scene, origin at
the launch pad.

Degrades gracefully exactly like ui/attitude_3d.py: if OpenGL is unavailable
on the ground station laptop, it falls back to a numeric/text-only panel
instead of taking the app down.
"""

import io
import math
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QMatrix4x4, QVector3D
from PyQt5.QtWidgets import QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QWidget

from core.config import load_config
from core.rocket_sim import RocketSimThread, ROCKETPY_AVAILABLE, ROCKETPY_IMPORT_ERROR

# OpenGL is optional at runtime — same guard as ui/attitude_3d.py.
try:
    import pyqtgraph.opengl as gl
    _GL_IMPORT_ERROR = None
except Exception as e:                                       # pragma: no cover
    gl = None
    _GL_IMPORT_ERROR = e

# Basemap tiles are optional too — no requests/Pillow, or no network at the
# launch site, just means the 3D view falls back to the bare grid.
try:
    import requests
    from PIL import Image
    _BASEMAP_IMPORT_ERROR = None
except Exception as e:                                       # pragma: no cover
    requests = None
    Image = None
    _BASEMAP_IMPORT_ERROR = e


# Decimate the live trace beyond this many points so GLLinePlotItem stays
# cheap for a long flight — halves the buffer rather than dropping the tail.
_MAX_LIVE_POINTS = 2000

# Basemap tiles — CartoDB dark tiles, matching ui/map_tab.py's 2D map style.
_TILE_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
_TILE_SUBDOMAINS = "abcd"
_TILE_SIZE = 256
_TILE_USER_AGENT = "VSSSIC-GroundStation-MapTab/1.0"

# Coverage before any simulation has run — re-fetched wider (see
# set_ideal_result) once the ideal trajectory's actual extent is known, and
# again on the fly as the camera pans/zooms (see _poll_camera_for_basemap).
_DEFAULT_HALF_EXTENT_M = 250.0

# Upper bound on what a single fetch will cover, regardless of how far a
# trajectory drifts or how far the camera zooms out -- keeps a runaway
# simulation result or an aggressive scroll-out from requesting an
# unbounded tile grid.
_MAX_HALF_EXTENT_M = 50000.0


def _deg2tile(lat, lon, zoom):
    """Slippy-map tile containing lat/lon at the given zoom."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    xt = int((lon + 180.0) / 360.0 * n)
    yt = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return xt, yt


def _tile2deg(xt, yt, zoom):
    """Lat/lon of a slippy-map tile's NW corner."""
    n = 2 ** zoom
    lon = xt / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * yt / n)))
    return math.degrees(lat_rad), lon


def _pick_zoom(lat, half_extent_m, tiles_per_side):
    """Zoom level whose tiles_per_side^2 grid roughly covers 2*half_extent_m."""
    target_tile_span_m = (2.0 * half_extent_m) / tiles_per_side
    meters_per_pixel_at_zoom0 = 156543.03392 * math.cos(math.radians(lat))
    zoom = math.log2(meters_per_pixel_at_zoom0 * _TILE_SIZE / target_tile_span_m)
    return int(max(2, min(19, round(zoom))))


def _tiles_per_side_for_extent(half_extent_m):
    """More tiles for a wider requested area, capped so a fully panned-out
    view still fetches a bounded number of tiles -- resolution drops via
    _pick_zoom's coarser zoom instead of the tile count growing without end.
    """
    if half_extent_m <= 400:
        return 3
    if half_extent_m <= 3000:
        return 5
    return 7


def _enu_to_latlon(east_m, north_m, ref_lat, ref_lon):
    """Inverse of the East/North-meters-from-ref projection used throughout
    this module. Lets a basemap fetch be centered wherever the camera has
    panned to, not just the reference point."""
    R = 6371000.0
    lat0 = math.radians(ref_lat)
    lat = ref_lat + math.degrees(north_m / R)
    lon = ref_lon + math.degrees(east_m / (R * math.cos(lat0)))
    return lat, lon


def _fetch_tile_image(z, x, y, timeout=5):
    n = 2 ** z
    x %= n
    s = _TILE_SUBDOMAINS[(x + y) % len(_TILE_SUBDOMAINS)]
    url = _TILE_URL.format(s=s, z=z, x=x, y=y)
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _TILE_USER_AGENT})
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def _build_basemap(ref_lat, ref_lon, center_east_m, center_north_m, half_extent_m, tiles_per_side):
    """Fetch and stitch a tiles_per_side x tiles_per_side tile grid centered
    on (center_east_m, center_north_m) -- local ENU meters relative to
    ref_lat/ref_lon, e.g. wherever the camera has panned to -- wide enough
    to roughly cover 2*half_extent_m.

    Returns (rgba_array, west_m, south_m, span_east_m, span_north_m) — the
    array in the (x, y, RGBA) layout GLImageItem expects, and the stitched
    image's footprint in local East/North meters relative to the reference
    point (same ENU frame as the trajectory lines, regardless of what point
    the fetch itself was centered on).
    """
    center_lat, center_lon = _enu_to_latlon(center_east_m, center_north_m, ref_lat, ref_lon)

    zoom = _pick_zoom(center_lat, half_extent_m, tiles_per_side)
    cx, cy = _deg2tile(center_lat, center_lon, zoom)
    half = tiles_per_side // 2
    x0, y0 = cx - half, cy - half

    # Fetched in parallel -- at the largest grid (7x7 = 49 tiles) sequential
    # requests could take the better part of a minute on an ordinary
    # connection, which would make panning/zooming feel broken rather than
    # like a map. This already runs on BasemapFetchThread, off the GUI
    # thread, so blocking here on the pool is fine.
    composite = Image.new("RGBA", (_TILE_SIZE * tiles_per_side, _TILE_SIZE * tiles_per_side))
    coords = [(row, col) for row in range(tiles_per_side) for col in range(tiles_per_side)]
    with ThreadPoolExecutor(max_workers=min(16, len(coords))) as pool:
        tiles = pool.map(lambda rc: _fetch_tile_image(zoom, x0 + rc[1], y0 + rc[0]), coords)
        for (row, col), tile in zip(coords, tiles):
            composite.paste(tile, (col * _TILE_SIZE, row * _TILE_SIZE))

    # (x0, y0) is the NW-most tile's NW corner; the SE-most tile's SE corner
    # is tiles_per_side tiles further along in both directions.
    lat_n, lon_w = _tile2deg(x0, y0, zoom)
    lat_s, lon_e = _tile2deg(x0 + tiles_per_side, y0 + tiles_per_side, zoom)

    R = 6371000.0
    lat0 = math.radians(ref_lat)
    west_m = math.radians(lon_w - ref_lon) * R * math.cos(lat0)
    east_m = math.radians(lon_e - ref_lon) * R * math.cos(lat0)
    north_m = math.radians(lat_n - ref_lat) * R
    south_m = math.radians(lat_s - ref_lat) * R

    # PIL rows run north(top) to south(bottom); world North is +Y and
    # GLImageItem's local Y runs low-to-high, so flip vertically. Then
    # transpose to the (x, y, RGBA) layout GLImageItem expects.
    arr = np.array(composite)
    arr = np.flipud(arr)
    arr = np.ascontiguousarray(arr.transpose(1, 0, 2))

    return arr, west_m, south_m, (east_m - west_m), (north_m - south_m)


class BasemapFetchThread(QThread):
    """Fetches and stitches basemap tiles off the GUI thread — same
    rationale as RocketSimThread: network/decode work must not block the UI.
    """

    finished_ok = pyqtSignal(object)
    finished_err = pyqtSignal(str)

    def __init__(self, ref_lat, ref_lon, center_east_m, center_north_m, half_extent_m, tiles_per_side):
        super().__init__()
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon
        self.center_east_m = center_east_m
        self.center_north_m = center_north_m
        self.half_extent_m = half_extent_m
        self.tiles_per_side = tiles_per_side

    def run(self):
        try:
            result = _build_basemap(
                self.ref_lat, self.ref_lon,
                self.center_east_m, self.center_north_m,
                self.half_extent_m, self.tiles_per_side,
            )
            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_err.emit(str(e))


class Trajectory3DView(QWidget):
    """Panel with a 3D plot of the ideal (simulated) and live (telemetry) trajectories."""

    # Emitted after a RocketSimThread solve so other views (ui/map_tab.py's
    # ground-track overlay, ui/simulation_tab.py's status label) can react
    # without each owning a second RocketSimThread.
    simulation_complete = pyqtSignal(dict)
    simulation_failed = pyqtSignal(str)

    def __init__(self, parent=None, show_run_button=True):
        super().__init__(parent)

        cfg = load_config()
        self.ref_lat = cfg.get("ref_lat", 26.712196)
        self.ref_lon = cfg.get("ref_lon", 84.305725)

        self._live_points = []  # list of (east_m, north_m, up_m)
        self._sim_thread = None
        self._basemap_item = None
        self._basemap_thread = None
        self._basemap_fetch_pending = False
        self._basemap_center = None        # (east_m, north_m) of the last requested fetch
        self._basemap_half_extent = None   # half-extent (m) of the last requested fetch
        self._camera_poll_snapshot = None
        self._camera_timer = None
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

                # Size the very first fetch to what the default camera framing
                # (set by reset_view() inside _build_scene) actually shows,
                # rather than a flat constant — otherwise the camera-poll
                # timer below immediately judges the flat default "stale"
                # and re-fetches within its first tick.
                initial_half_extent = self._extent_for_camera(
                    self.view.opts.get('distance', 300.0), self.view.opts.get('fov', 60.0)
                )
                self._request_basemap(0.0, 0.0, initial_half_extent)

                # Polls the camera each tick to reload terrain as the user
                # pans/zooms — see _poll_camera_for_basemap's docstring.
                self._camera_timer = QTimer(self)
                self._camera_timer.setInterval(500)
                self._camera_timer.timeout.connect(self._poll_camera_for_basemap)
                self._camera_timer.start()
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

        if self.view is not None:
            controls_hint = QLabel(
                "Drag to orbit · scroll to zoom · Ctrl+drag (or middle-drag) to pan"
                " — terrain reloads as you move"
            )
            controls_hint.setAlignment(Qt.AlignCenter)
            controls_hint.setStyleSheet("color:#888; font-size:9px;")
            layout.addWidget(controls_hint)

            attribution = QLabel(
                '<span style="color:#666;">Basemap © CARTO, © OpenStreetMap contributors</span>'
            )
            attribution.setAlignment(Qt.AlignCenter)
            attribution.setStyleSheet("font-size:9px;")
            layout.addWidget(attribution)

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
            reset_view_btn.setToolTip(
                "Restore the default camera angle\n"
                "Drag to orbit, scroll to zoom, Ctrl+drag (or middle-drag) to pan the map"
            )
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
        #
        # glOptions='translucent' is deliberate on every item below: pyqtgraph's
        # GLLinePlotItem/GLScatterPlotItem default to glOptions='additive',
        # which disables GL_DEPTH_TEST. That's invisible as long as nothing
        # opaque is drawn after them — but the basemap image is, and without
        # depth testing the line has no way to win against it, so it renders
        # as barely-visible fragments (only where the grid's own depth-tested
        # pixels happen to coincide). 'translucent' keeps depth testing on so
        # the trajectory and pad marker correctly render in front of the
        # basemap instead of being swallowed by it.
        pad = gl.GLScatterPlotItem(
            pos=np.array([[0.0, 0.0, 0.0]]), color=(1, 1, 1, 1), size=12,
            glOptions='translucent',
        )
        self.view.addItem(pad)

        self.ideal_line = gl.GLLinePlotItem(
            pos=np.zeros((1, 3), dtype=np.float32),
            color=(0.30, 0.60, 1.00, 1.0),
            width=2,
            antialias=True,
            glOptions='translucent',
        )
        self.view.addItem(self.ideal_line)

        self.live_line = gl.GLLinePlotItem(
            pos=np.zeros((1, 3), dtype=np.float32),
            color=(1.00, 0.62, 0.26, 1.0),
            width=3,
            antialias=True,
            glOptions='translucent',
        )
        self.view.addItem(self.live_line)

    def reset_view(self):
        """Restore the default camera framing and pan position."""
        if self.view is not None:
            self.view.setCameraPosition(
                pos=QVector3D(0.0, 0.0, 0.0), distance=300, elevation=20, azimuth=135,
            )

    # -----------------------------------
    # Basemap
    # -----------------------------------
    def _poll_camera_for_basemap(self):
        """Runs on a timer while the view is visible: reloads terrain as the
        camera pans or zooms, the way a 2D web map loads new tiles as you
        navigate. Debounced by only acting once two consecutive polls see
        the same camera reading, so a drag gesture doesn't trigger a fetch
        on every intermediate frame — only once it settles."""
        if self.view is None:
            return
        center = self.view.opts.get('center')
        if center is None:
            return
        distance = self.view.opts.get('distance', 300.0)
        fov = self.view.opts.get('fov', 60.0)

        snapshot = (round(center.x(), 1), round(center.y(), 1), round(distance, 1), round(fov, 2))
        if snapshot != self._camera_poll_snapshot:
            self._camera_poll_snapshot = snapshot
            return  # camera is still moving -- wait for it to settle

        target_half_extent = self._extent_for_camera(distance, fov)
        self._maybe_refresh_basemap(center.x(), center.y(), target_half_extent)

    def _extent_for_camera(self, distance, fov):
        """Roughly how much ground (half-extent, meters) is visible at the
        current zoom. 2*distance*tan(fov/2) is the span at the focal plane;
        the 1.5x pad means panning to the edge of the current view doesn't
        immediately run past the edge of what's loaded."""
        visible_span_m = 2.0 * distance * math.tan(math.radians(fov / 2.0)) * 1.5
        return max(_DEFAULT_HALF_EXTENT_M, min(visible_span_m, _MAX_HALF_EXTENT_M))

    def _maybe_refresh_basemap(self, center_east_m, center_north_m, target_half_extent):
        """Only re-fetch once the loaded terrain is actually stale for the
        current view -- otherwise every settle of the camera (including a
        tiny nudge) would re-download tiles."""
        if self._basemap_half_extent is None:
            self._request_basemap(center_east_m, center_north_m, target_half_extent)
            return

        moved_m = math.hypot(
            center_east_m - self._basemap_center[0],
            center_north_m - self._basemap_center[1],
        )
        stale = (
            target_half_extent > self._basemap_half_extent * 1.15  # zoomed out past coverage
            or target_half_extent < self._basemap_half_extent * 0.4  # zoomed in, resolution too coarse
            or moved_m > self._basemap_half_extent * 0.5  # panned toward the edge
        )
        if stale:
            self._request_basemap(center_east_m, center_north_m, target_half_extent)

    def _request_basemap(self, center_east_m, center_north_m, half_extent_m):
        """Fetch map tiles centered on (center_east_m, center_north_m) --
        local ENU meters relative to the reference point -- covering
        roughly +/-half_extent_m, on a background thread. No-op if tiles/
        network aren't available — the bare grid is still a fully usable
        trajectory view without it."""
        if self.view is None or requests is None or Image is None:
            return
        # A plain flag rather than self._basemap_thread.isRunning(): the
        # flag flips the instant we decide to fetch, with no dependency on
        # exactly when Qt marks the new QThread as started.
        if self._basemap_fetch_pending:
            return

        self._basemap_fetch_pending = True
        self._basemap_center = (center_east_m, center_north_m)
        self._basemap_half_extent = half_extent_m

        tiles_per_side = _tiles_per_side_for_extent(half_extent_m)
        self._basemap_thread = BasemapFetchThread(
            self.ref_lat, self.ref_lon, center_east_m, center_north_m,
            half_extent_m, tiles_per_side,
        )
        self._basemap_thread.finished_ok.connect(self._on_basemap_ok)
        self._basemap_thread.finished_err.connect(self._on_basemap_err)
        self._basemap_thread.start()

    def _on_basemap_ok(self, result):
        self._basemap_fetch_pending = False
        arr, west_m, south_m, span_e_m, span_n_m = result
        w, h = arr.shape[0], arr.shape[1]

        if self._basemap_item is None:
            self._basemap_item = gl.GLImageItem(arr, smooth=True, glOptions='opaque')
            # Slightly below the grid/trajectory plane to avoid z-fighting.
            self.view.addItem(self._basemap_item)
        else:
            self._basemap_item.setData(arr)

        transform = QMatrix4x4()
        transform.translate(west_m, south_m, -0.5)
        transform.scale(span_e_m / w, span_n_m / h, 1.0)
        self._basemap_item.setTransform(transform)

    def _on_basemap_err(self, message):
        self._basemap_fetch_pending = False
        print(f"[TRAJECTORY] basemap unavailable — {message}")

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
            xy_extent = max(np.abs(pts[:, 0]).max(), np.abs(pts[:, 1]).max(), 1.0)
            half_extent_m = max(_DEFAULT_HALF_EXTENT_M, min(xy_extent * 1.2, _MAX_HALF_EXTENT_M))

            # Re-center and zoom the camera out to actually frame the
            # trajectory -- without this, the camera stays wherever it was
            # (its unrelated default distance, or wherever the user had
            # panned to), and _poll_camera_for_basemap (next tick) would see
            # a basemap that disagrees with what that camera implies and
            # immediately reload to match it back, fighting this call
            # instead of showing the new trajectory's terrain.
            # Inverse of _extent_for_camera's visible_span_m = 2*distance*
            # tan(fov/2)*1.5, solved for distance.
            fov = self.view.opts.get('fov', 60.0)
            target_distance = half_extent_m / (3.0 * math.tan(math.radians(fov / 2.0)))
            self.view.setCameraPosition(
                pos=QVector3D(0.0, 0.0, 0.0), distance=max(target_distance, 100.0),
            )

            self._request_basemap(0.0, 0.0, half_extent_m)
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
