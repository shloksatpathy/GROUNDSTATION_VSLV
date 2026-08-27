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
from PyQt5.QtGui import QVector3D
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
# launch site, just means the 3D view shows the trajectory over an
# empty background.
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

# Coverage before any simulation has run — re-fetched wider (see
# set_ideal_result) once the ideal trajectory's actual extent is known, and
# again on the fly as the camera pans/zooms (see _poll_camera_for_terrain).
_DEFAULT_HALF_EXTENT_M = 250.0

# Upper bound on what a single fetch will cover, regardless of how far a
# trajectory drifts or how far the camera zooms out -- keeps a runaway
# simulation result or an aggressive scroll-out from requesting an
# unbounded tile grid.
_MAX_HALF_EXTENT_M = 50000.0

# Shared by both tile sets below.
_TILE_SIZE = 256
_TILE_USER_AGENT = "VSSSIC-GroundStation-MapTab/1.0"
# Rotated through for a {s} placeholder in the optional drape URL — map
# imagery laid over the relief for context (water, roads, built-up areas),
# configured via config.json's "terrain_basemap_url". Off by default, since
# the obvious free sources now watermark keyless requests, which would stamp
# that watermark right across the terrain.
_TILE_SUBDOMAINS = "abcd"

# Elevation tiles — Terrarium-encoded PNGs from the AWS "Terrain Tiles" open
# data set (no API key, same slippy-map tile scheme as the basemap):
#     elevation_m = R * 256 + G + B / 256 - 32768
# These are what make the ground under the trajectory actual relief instead of
# a flat picture of relief. Zoom 15 is the deepest level the set publishes.
_TERRAIN_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
_TERRAIN_MAX_ZOOM = 15

# Vertices per side of the relief mesh. The tile zoom is picked to land near
# this resolution, so it sets both how fine the terrain is and how sharp the
# map imagery draped over it looks — 320x320 is ~100k vertices, which the
# GPU chews through in one indexed draw and stays smooth while orbiting.
_TERRAIN_GRID = 320

# Baked sun for the hillshade: azimuth in degrees clockwise from north (315 =
# from the NW, the cartographic convention that makes ridges read as ridges
# rather than valleys), altitude in degrees above the horizon.
_SUN_AZIMUTH_DEG = 315.0
_SUN_ALTITUDE_DEG = 40.0
# Floor on the shading so slopes facing away from the sun stay readable
# instead of going pure black.
_TERRAIN_AMBIENT = 0.20
# Relief ramp, shadow -> lit. Cold slate, so the warm live trace and the blue
# ideal trace both stay legible against it.
_SHADOW_RGB = np.array([0.043, 0.078, 0.090], dtype=np.float32)
_LIGHT_RGB = np.array([0.470, 0.560, 0.570], dtype=np.float32)
# Slight S-curve on the shading so ridges and gullies separate instead of
# sitting in a narrow band of mid-greys.
_SHADE_GAMMA = 1.25
# Hypsometric tint: low ground is darkened and high ground brightened by this
# much either side of 1.0. Carries the large-scale shape of the ground (river
# plains, ridge lines) even where the hillshade alone has nothing to bite on.
_ELEVATION_TINT = 0.22
# The hillshade scales slopes so the steep end of the window lands near ~30
# degrees of apparent slope. Shading strength is a legibility choice, not a
# measurement: real mountains need no help (the gain lands at 1.0 there), but
# gentle ground would otherwise render as a blank plate. The *geometry* stays
# at the configured exaggeration either way.
_SHADE_SLOPE_TARGET = 0.60
_SHADE_GAIN_LIMITS = (1.0, 12.0)
# Ground flatter than this much relief across the window is left unamplified.
# Elevation tiles carry several metres of vertical noise, and gaining that up
# would draw dunes across a plain that is genuinely flat — the height tint
# still shows what large-scale shape is there.
_SHADE_NOISE_FLOOR_M = 8.0
# How strongly a configured drape's tile colours modulate the relief. Kept as
# a modulation rather than a blend: mixing dark map tiles in directly would
# just flatten the shading toward black.
_BASEMAP_MODULATION = 1.6


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


def _meters_per_pixel(lat, zoom):
    """Ground resolution of one tile pixel at this latitude and zoom."""
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)


def _pick_zoom(lat, half_extent_m):
    """Deepest zoom whose pixels are still no finer than the mesh can show.

    Fetching past that only costs bandwidth: the surface samples one vertex
    per _TERRAIN_GRID-th of the view either way, so extra pixels are thrown
    away in the downsample.
    """
    target_m_per_px = (2.0 * half_extent_m) / _TERRAIN_GRID
    zoom = math.log2(_meters_per_pixel(lat, 0) / target_m_per_px)
    return int(max(2, min(_TERRAIN_MAX_ZOOM, round(zoom))))


def _tiles_per_side_for(lat, zoom, half_extent_m):
    """Odd tile count covering 2*half_extent_m at this zoom.

    Odd so the requested centre lands in the middle tile; +1 so the window
    doesn't graze the edge of the grid; capped so a fully zoomed-out view
    can't fire off an unbounded number of requests (the zoom goes coarser
    instead).
    """
    tile_span_m = _meters_per_pixel(lat, zoom) * _TILE_SIZE
    needed = int(math.ceil((2.0 * half_extent_m) / tile_span_m)) + 1
    needed += (needed + 1) % 2
    return max(1, min(needed, 7))


def _enu_to_latlon(east_m, north_m, ref_lat, ref_lon):
    """Inverse of the East/North-meters-from-ref projection used throughout
    this module. Lets a terrain fetch be centered wherever the camera has
    panned to, not just the reference point."""
    R = 6371000.0
    lat0 = math.radians(ref_lat)
    lat = ref_lat + math.degrees(north_m / R)
    lon = ref_lon + math.degrees(east_m / (R * math.cos(lat0)))
    return lat, lon


def _fetch_tile_image(tile_url, z, x, y, timeout=5):
    """One drape tile as an RGB float array in 0..1, or None if it can't be
    had — a hole in the imagery shouldn't cost us the relief."""
    n = 2 ** z
    x %= n
    s = _TILE_SUBDOMAINS[(x + y) % len(_TILE_SUBDOMAINS)]
    url = tile_url.format(s=s, z=z, x=x, y=y)
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": _TILE_USER_AGENT})
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None
    return np.asarray(img, dtype=np.float32) / 255.0


def _fetch_terrain_tile(z, x, y, timeout=8):
    """One Terrarium tile decoded to meters above sea level, or None if the
    tile is missing — the set has gaps, and one hole shouldn't sink a fetch."""
    n = 2 ** z
    x %= n
    url = _TERRAIN_TILE_URL.format(z=z, x=x, y=y)
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": _TILE_USER_AGENT})
        resp.raise_for_status()
        rgb = np.asarray(Image.open(io.BytesIO(resp.content)).convert("RGB"), dtype=np.float32)
    except Exception:
        return None
    return rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0


def _smooth(grid):
    """One separable 1-2-1 pass. Elevation tiles carry per-pixel sensor noise
    and 1/256 m quantisation steps; on gentle ground the shading gain below
    would otherwise amplify those into a plaster-like texture that reads as
    terrain detail that isn't there."""
    out = grid.astype(np.float32, copy=True)
    for axis in (0, 1):
        lo = np.roll(out, 1, axis=axis)
        hi = np.roll(out, -1, axis=axis)
        # Edges have no neighbour on one side; repeat the edge row/column
        # instead of wrapping around to the far side of the window.
        edge = [slice(None), slice(None)]
        edge[axis] = 0
        lo[tuple(edge)] = out[tuple(edge)]
        edge[axis] = -1
        hi[tuple(edge)] = out[tuple(edge)]
        out = 0.25 * lo + 0.5 * out + 0.25 * hi
    return out


def _relief_colors(elev_m, tile_rgb, dx_m, dy_m, exaggeration):
    """Bake a hillshade of the elevation grid into per-vertex colours.

    Shading is baked rather than left to an OpenGL light because the mesh is
    rebuilt on every pan/zoom: per-vertex normals for 100k vertices cost more
    than this does, and a baked shade also lets the map imagery modulate it.

    elev_m is (nx, ny) with x running east and y running north, matching
    GLSurfacePlotItem's vertex layout.
    """
    shading_elev = _smooth(elev_m) * exaggeration
    dz_dx = np.gradient(shading_elev, dx_m, axis=0)
    dz_dy = np.gradient(shading_elev, dy_m, axis=1)

    # Normalise the shading to the relief actually in this window -- see
    # _SHADE_SLOPE_TARGET. The gain applies to the shading only; it never
    # touches the vertex heights the trajectory is compared against.
    slope = np.hypot(dz_dx, dz_dy)
    reference_slope = float(np.percentile(slope, 90.0))
    gain = float(np.clip(_SHADE_SLOPE_TARGET / max(reference_slope, 1e-6), *_SHADE_GAIN_LIMITS))
    relief_m = float(np.subtract(*np.percentile(elev_m, [98.0, 2.0])))
    damping = float(np.clip(
        (relief_m - _SHADE_NOISE_FLOOR_M) / (3.0 * _SHADE_NOISE_FLOOR_M), 0.0, 1.0))
    gain = 1.0 + (gain - 1.0) * damping
    dz_dx, dz_dy = dz_dx * gain, dz_dy * gain

    inv_len = 1.0 / np.sqrt(dz_dx * dz_dx + dz_dy * dz_dy + 1.0)

    az = math.radians(_SUN_AZIMUTH_DEG)
    alt = math.radians(_SUN_ALTITUDE_DEG)
    # Azimuth is clockwise from north, so it maps to (east, north) as
    # (sin, cos) rather than the usual (cos, sin).
    lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)

    shade = np.clip((-dz_dx * lx - dz_dy * ly + lz) * inv_len, 0.0, 1.0) ** _SHADE_GAMMA
    shade = _TERRAIN_AMBIENT + (1.0 - _TERRAIN_AMBIENT) * shade

    relief = _SHADOW_RGB + (_LIGHT_RGB - _SHADOW_RGB) * shade[..., None]

    # Height tint, stretched across the window's own 2nd..98th percentile so
    # it adapts to whatever range of ground is on screen rather than to some
    # fixed sea-level-to-summit scale.
    lo, hi = np.percentile(elev_m, [2.0, 98.0])
    if hi - lo > 1e-3:
        height = np.clip((elev_m - lo) / (hi - lo), 0.0, 1.0)
        relief = relief * (1.0 + _ELEVATION_TINT * (2.0 * height - 1.0))[..., None]

    if tile_rgb is not None:
        # Map features as a gain on the relief: how much brighter or darker
        # this pixel is than the map's own background, which keeps water and
        # roads visible without washing the shading out.
        luma = tile_rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        gain = 1.0 + (luma - float(np.median(luma))) * _BASEMAP_MODULATION
        relief = relief * np.clip(gain, 0.55, 2.2)[..., None]

    colors = np.ones(relief.shape[:2] + (4,), dtype=np.float32)
    colors[..., :3] = np.clip(relief, 0.0, 1.0)
    return colors


def _build_terrain(ref_lat, ref_lon, center_east_m, center_north_m, half_extent_m,
                   exaggeration, tile_url=None):
    """Fetch elevation (and optionally map imagery) around (center_east_m, center_north_m)
    -- local ENU meters relative to ref_lat/ref_lon, e.g. wherever the camera
    has panned to -- and turn them into a shaded relief surface.

    Returns a dict of
        x, y          1D ENU meter coordinates (east, north) of the grid
        elev          (len(x), len(y)) elevation in meters above sea level
        colors        (len(x)*len(y), 4) baked hillshade, flattened the way
                      GLSurfacePlotItem indexes its vertices
        origin_elev   elevation at the launch pad, or None if this window
                      doesn't contain it
        flat          True if no elevation tile came back and the surface is
                      a bare plane
    """
    center_lat, center_lon = _enu_to_latlon(center_east_m, center_north_m, ref_lat, ref_lon)

    zoom = _pick_zoom(center_lat, half_extent_m)
    tiles_per_side = _tiles_per_side_for(center_lat, zoom, half_extent_m)
    cx, cy = _deg2tile(center_lat, center_lon, zoom)
    half = tiles_per_side // 2
    x0, y0 = cx - half, cy - half

    size = _TILE_SIZE * tiles_per_side
    elev = np.zeros((size, size), dtype=np.float32)
    rgb = np.zeros((size, size, 3), dtype=np.float32)
    coords = [(row, col) for row in range(tiles_per_side) for col in range(tiles_per_side)]

    # Tiles are fetched in parallel -- at the largest grid that's 49 of them
    # (98 with a drape configured), and doing them in series would make
    # panning feel broken rather than like a map. This already runs on
    # TerrainFetchThread, off the GUI thread, so blocking on the pool is fine.
    with ThreadPoolExecutor(max_workers=min(24, 2 * len(coords))) as pool:
        elev_futures = {
            rc: pool.submit(_fetch_terrain_tile, zoom, x0 + rc[1], y0 + rc[0]) for rc in coords
        }
        img_futures = {} if tile_url is None else {
            rc: pool.submit(_fetch_tile_image, tile_url, zoom, x0 + rc[1], y0 + rc[0])
            for rc in coords
        }
        got_elev = False
        got_rgb = False
        for row, col in coords:
            r0, c0 = row * _TILE_SIZE, col * _TILE_SIZE
            tile_elev = elev_futures[(row, col)].result()
            if tile_elev is not None:
                elev[r0:r0 + _TILE_SIZE, c0:c0 + _TILE_SIZE] = tile_elev
                got_elev = True
            if img_futures:
                tile_rgb = img_futures[(row, col)].result()
                if tile_rgb is not None:
                    rgb[r0:r0 + _TILE_SIZE, c0:c0 + _TILE_SIZE] = tile_rgb
                    got_rgb = True

    if not got_elev and not got_rgb:
        raise RuntimeError("no tiles could be fetched")

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

    px_e = (east_m - west_m) / size
    px_n = (north_m - south_m) / size

    # Crop to what the camera is actually looking at. Without this a zoomed-in
    # view (where the zoom cap means one tile already covers far more than the
    # window) would spread the mesh's fixed vertex budget over kilometres of
    # off-screen ground and leave the visible part coarse.
    want = half_extent_m * 1.15
    col_lo = int(np.clip((center_east_m - want - west_m) / px_e, 0, size - 2))
    col_hi = int(np.clip(math.ceil((center_east_m + want - west_m) / px_e), col_lo + 2, size))
    row_lo = int(np.clip((north_m - (center_north_m + want)) / px_n, 0, size - 2))
    row_hi = int(np.clip(
        math.ceil((north_m - (center_north_m - want)) / px_n), row_lo + 2, size))

    stride = max(1, int(math.ceil(max(col_hi - col_lo, row_hi - row_lo) / _TERRAIN_GRID)))
    rows = np.arange(row_lo, row_hi, stride)
    cols = np.arange(col_lo, col_hi, stride)

    # Rows run north -> south in tile space; flip so y ascends northward, then
    # transpose into the (x=east, y=north) layout GLSurfacePlotItem expects.
    elev_grid = np.ascontiguousarray(elev[np.ix_(rows, cols)][::-1].T)
    rgb_grid = np.ascontiguousarray(rgb[np.ix_(rows, cols)][::-1].transpose(1, 0, 2))

    x_coords = (west_m + (cols + 0.5) * px_e).astype(np.float32)
    y_coords = (north_m - (rows + 0.5) * px_n).astype(np.float32)[::-1].copy()

    origin_elev = None
    if got_elev and x_coords[0] <= 0.0 <= x_coords[-1] and y_coords[0] <= 0.0 <= y_coords[-1]:
        origin_elev = float(
            elev_grid[int(np.abs(x_coords).argmin()), int(np.abs(y_coords).argmin())]
        )

    colors = _relief_colors(
        elev_grid, rgb_grid if got_rgb else None,
        px_e * stride, px_n * stride, exaggeration,
    )

    return {
        "x": x_coords,
        "y": y_coords,
        "elev": elev_grid,
        "colors": colors.reshape(-1, 4),
        "origin_elev": origin_elev,
        "flat": not got_elev,
    }


class TerrainFetchThread(QThread):
    """Fetches, stitches and shades terrain off the GUI thread — same
    rationale as RocketSimThread: network/decode work must not block the UI.
    """

    finished_ok = pyqtSignal(object)
    finished_err = pyqtSignal(str)

    def __init__(self, ref_lat, ref_lon, center_east_m, center_north_m,
                 half_extent_m, exaggeration, tile_url=None):
        super().__init__()
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon
        self.center_east_m = center_east_m
        self.center_north_m = center_north_m
        self.half_extent_m = half_extent_m
        self.exaggeration = exaggeration
        self.tile_url = tile_url

    def run(self):
        try:
            result = _build_terrain(
                self.ref_lat, self.ref_lon,
                self.center_east_m, self.center_north_m,
                self.half_extent_m, self.exaggeration, self.tile_url,
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
        # Vertical exaggeration of the relief — 1.0 keeps the ground to the
        # same scale as the trajectory drawn against it. Legibility on gentle
        # terrain is handled in the shading instead (see _relief_colors), so
        # this only needs raising to deliberately dramatise the landscape.
        self.terrain_exaggeration = float(cfg.get("terrain_exaggeration", 1.0))
        # Optional imagery draped over the relief — see _fetch_tile_image.
        self.terrain_basemap_url = cfg.get("terrain_basemap_url") or None

        self._live_points = []  # list of (east_m, north_m, up_m)
        self._sim_thread = None
        self._terrain_item = None
        self._terrain_thread = None
        self._terrain_fetch_pending = False
        self._terrain_center = None        # (east_m, north_m) of the last requested fetch
        self._terrain_half_extent = None   # half-extent (m) of the last requested fetch
        # Sea-level elevation under the pad, learned from the first fetch that
        # covers the origin. Terrain is drawn relative to it so the ground sits
        # at z=0 under the pad, matching the AGL frame the trajectories use.
        self._pad_elev_m = None
        self._terrain_flat_warned = False
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
                self._request_terrain(0.0, 0.0, initial_half_extent)

                # Polls the camera each tick to reload terrain as the user
                # pans/zooms — see _poll_camera_for_terrain's docstring.
                self._camera_timer = QTimer(self)
                self._camera_timer.setInterval(500)
                self._camera_timer.timeout.connect(self._poll_camera_for_terrain)
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

            credit = "Terrain: AWS Terrain Tiles (SRTM, ASTER, NED)"
            if self.terrain_basemap_url:
                # Whatever source the operator pointed terrain_basemap_url at
                # comes with its own attribution terms; name it so the credit
                # line doesn't quietly claim the imagery is ours.
                credit += " · Map imagery: configured tile source"
            attribution = QLabel(f'<span style="color:#666;">{credit}</span>')
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

        # Launch pad marker at the local-frame origin.
        #
        # glOptions='translucent' is deliberate on every item below: pyqtgraph's
        # GLLinePlotItem/GLScatterPlotItem default to glOptions='additive',
        # which disables GL_DEPTH_TEST. That's invisible as long as nothing
        # opaque is drawn after them — but the terrain surface is, and
        # without depth testing the line has no way to win against it, so it
        # renders as barely-visible fragments wherever terrain happens to be
        # drawn behind them. 'translucent' keeps depth testing on so the
        # trajectory and pad marker correctly render in front of the terrain
        # instead of being swallowed by it.
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
        """Restore the default camera framing and pan position.

        The 30-degree elevation is a terrain concession: from much lower the
        camera can end up inside a hillside at a launch site with any relief,
        and near-ground geometry hides the first part of the climb.
        """
        if self.view is not None:
            self.view.setCameraPosition(
                pos=QVector3D(0.0, 0.0, 0.0), distance=300, elevation=30, azimuth=135,
            )

    # -----------------------------------
    # Terrain
    # -----------------------------------
    def _poll_camera_for_terrain(self):
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
        self._maybe_refresh_terrain(center.x(), center.y(), target_half_extent)

    def _extent_for_camera(self, distance, fov):
        """Roughly how much ground (half-extent, meters) is visible at the
        current zoom. 2*distance*tan(fov/2) is the span at the focal plane;
        the 1.5x pad means panning to the edge of the current view doesn't
        immediately run past the edge of what's loaded."""
        visible_span_m = 2.0 * distance * math.tan(math.radians(fov / 2.0)) * 1.5
        return max(_DEFAULT_HALF_EXTENT_M, min(visible_span_m, _MAX_HALF_EXTENT_M))

    def _maybe_refresh_terrain(self, center_east_m, center_north_m, target_half_extent):
        """Only re-fetch once the loaded terrain is actually stale for the
        current view -- otherwise every settle of the camera (including a
        tiny nudge) would re-download tiles."""
        if self._terrain_half_extent is None:
            self._request_terrain(center_east_m, center_north_m, target_half_extent)
            return

        moved_m = math.hypot(
            center_east_m - self._terrain_center[0],
            center_north_m - self._terrain_center[1],
        )
        stale = (
            target_half_extent > self._terrain_half_extent * 1.15  # zoomed out past coverage
            or target_half_extent < self._terrain_half_extent * 0.4  # zoomed in, resolution too coarse
            or moved_m > self._terrain_half_extent * 0.5  # panned toward the edge
        )
        if stale:
            self._request_terrain(center_east_m, center_north_m, target_half_extent)

    def _request_terrain(self, center_east_m, center_north_m, half_extent_m):
        """Fetch elevation + map tiles centered on (center_east_m,
        center_north_m) -- local ENU meters relative to the reference point --
        covering roughly +/-half_extent_m, on a background thread. No-op if
        tiles/network aren't available — the trajectory lines alone are still
        a fully usable view without them."""
        if self.view is None or requests is None or Image is None:
            return
        # A plain flag rather than self._terrain_thread.isRunning(): the
        # flag flips the instant we decide to fetch, with no dependency on
        # exactly when Qt marks the new QThread as started.
        if self._terrain_fetch_pending:
            return

        self._terrain_fetch_pending = True
        self._terrain_center = (center_east_m, center_north_m)
        self._terrain_half_extent = half_extent_m

        self._terrain_thread = TerrainFetchThread(
            self.ref_lat, self.ref_lon, center_east_m, center_north_m,
            half_extent_m, self.terrain_exaggeration, self.terrain_basemap_url,
        )
        self._terrain_thread.finished_ok.connect(self._on_terrain_ok)
        self._terrain_thread.finished_err.connect(self._on_terrain_err)
        self._terrain_thread.start()

    def _on_terrain_ok(self, result):
        self._terrain_fetch_pending = False

        if result["origin_elev"] is not None and self._pad_elev_m is None:
            self._pad_elev_m = result["origin_elev"]
        # Until a window containing the pad has been seen, level the surface
        # on its own median rather than leaving it at absolute sea level --
        # otherwise the first fetch of a plateau launch site would put the
        # ground hundreds of meters above a trajectory measured from the pad.
        datum = self._pad_elev_m
        if datum is None:
            datum = float(np.median(result["elev"]))

        z = ((result["elev"] - datum) * self.terrain_exaggeration).astype(np.float32)

        if self._terrain_item is None:
            self._terrain_item = gl.GLSurfacePlotItem(
                x=result["x"], y=result["y"], z=z, colors=result["colors"],
                # Normals are never used: the hillshade is already baked into
                # the vertex colours (see _relief_colors), so computing them
                # for 100k vertices on every pan would be pure cost.
                computeNormals=False, smooth=True, shader=None, glOptions='opaque',
            )
            self.view.addItem(self._terrain_item)
        else:
            self._terrain_item.setData(
                x=result["x"], y=result["y"], z=z, colors=result["colors"],
            )

        if result["flat"] and not self._terrain_flat_warned:
            self._terrain_flat_warned = True
            print("[TRAJECTORY] elevation tiles unavailable — terrain is flat")

    def _on_terrain_err(self, message):
        self._terrain_fetch_pending = False
        print(f"[TRAJECTORY] terrain unavailable — {message}")

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
            # panned to), and _poll_camera_for_terrain (next tick) would see
            # terrain that disagrees with what that camera implies and
            # immediately reload to match it back, fighting this call
            # instead of showing the new trajectory's terrain.
            # Inverse of _extent_for_camera's visible_span_m = 2*distance*
            # tan(fov/2)*1.5, solved for distance.
            fov = self.view.opts.get('fov', 60.0)
            target_distance = half_extent_m / (3.0 * math.tan(math.radians(fov / 2.0)))

            # A tall, narrow flight is framed by its altitude, not its ground
            # track: a 3 km climb over a 500 m footprint would otherwise run
            # straight off the top of the view. Lifting the look-at point off
            # the ground also keeps the camera clear of the terrain in front
            # of the pad, which used to be a bare plane and is now a hillside.
            apogee_m = float(np.max(pts[:, 2])) if len(pts) else 0.0
            target_distance = max(target_distance, apogee_m * 0.9)
            self.view.setCameraPosition(
                pos=QVector3D(0.0, 0.0, apogee_m * 0.35),
                distance=max(target_distance, 100.0),
            )

            self._request_terrain(0.0, 0.0, half_extent_m)
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
