import io
import math
import folium
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QDoubleSpinBox, QPushButton, QCheckBox)
from PyQt5.QtWebEngineWidgets import QWebEngineView

from core.config import load_config
from ui.trajectory_3d import Trajectory3DView


_INPUT_STYLE = (
    "background:#1E1E1E; color:#E0E0E0; border:1px solid #444; padding:3px;"
)


def haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in meters between two lat/lon points (Haversine)."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def great_circle_points(lat1, lon1, lat2, lon2, n_points=100):
    """Return list of [lat, lon] along great-circle from point1 to point2 inclusive."""
    φ1 = math.radians(lat1); λ1 = math.radians(lon1)
    φ2 = math.radians(lat2); λ2 = math.radians(lon2)

    dφ = φ2 - φ1
    dλ = λ2 - λ1
    a = math.sin(dφ/2.0)**2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ/2.0)**2
    
    # Constrain domain for sqrt to avoid math domain errors
    if a < 0: a = 0.0
    if a > 1: a = 1.0
        
    δ = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    if δ == 0:
        return [[lat1, lon1] for _ in range(n_points)]

    points = []
    for i in range(n_points):
        f = i / (n_points - 1)
        A = math.sin((1 - f) * δ) / math.sin(δ)
        B = math.sin(f * δ) / math.sin(δ)
        x = A * math.cos(φ1) * math.cos(λ1) + B * math.cos(φ2) * math.cos(λ2)
        y = A * math.cos(φ1) * math.sin(λ1) + B * math.cos(φ2) * math.sin(λ2)
        z = A * math.sin(φ1) + B * math.sin(φ2)
        φi = math.atan2(z, math.sqrt(x * x + y * y))
        λi = math.atan2(y, x)
        points.append([math.degrees(φi), math.degrees(λi)])
    return points


def _format_distance(dist_m):
    """Metres under a kilometre, kilometres above it."""
    return f"{dist_m/1000.0:.3f} km" if dist_m >= 1000 else f"{dist_m:.1f} m"


def latlon_to_enu(lat, lon, alt, ref_lat, ref_lon, ref_alt):
    """Convert a lat/lon/alt fix to local East/North/Up meters relative to
    a reference point.

    Equirectangular flat-earth approximation — accurate enough at the
    range scale of a rocket flight (a few km), and matches the local frame
    RocketPy's Flight solution is already expressed in (see core/rocket_sim.py).
    """
    R = 6371000.0
    lat0 = math.radians(ref_lat)
    east = math.radians(lon - ref_lon) * R * math.cos(lat0)
    north = math.radians(lat - ref_lat) * R
    up = (alt - ref_alt) if alt is not None else 0.0
    return east, north, up


class MapTab(QWidget):

    def __init__(self):
        super().__init__()

        cfg = load_config()
        self.ref_lat = cfg.get("ref_lat", 26.712196)
        self.ref_lon = cfg.get("ref_lon", 84.305725)
        self.ref_alt = cfg.get("ref_alt", 0.0)

        # Tile source for the folium map below. Read from config so a keyed
        # provider can be swapped in without touching this file; see
        # core/config.py for why the default is Esri rather than CARTO.
        self.tile_url = cfg.get("map_tile_url")
        self.tile_attribution = cfg.get("map_tile_attribution")

        layout = QVBoxLayout()

        layout.addLayout(self._build_manual_fix_row())

        panes_layout = QHBoxLayout()

        # Left pane: 3D trajectory view (ideal vs live, local ENU).
        self.trajectory_view = Trajectory3DView()

        # Right pane: reference + current position + geodesic line.
        self.map2_view = QWebEngineView()
        self.map2_view.setMinimumHeight(220)

        panes_layout.addWidget(self.trajectory_view)
        panes_layout.addWidget(self.map2_view)

        layout.addLayout(panes_layout)

        self.setLayout(layout)

        # Initialize with reference point
        self.update_ref_map(None, None)

    # -----------------------------------
    # Manual lat/lon entry
    # -----------------------------------
    def _build_manual_fix_row(self):
        """Row of lat/lon/alt inputs that render the maps at a position typed
        in at runtime, without waiting for (or having) a GNSS fix.

        Two destinations for the same numbers: "Plot Position" treats them as
        a fix — exactly what a telemetry packet would do — while "Set as
        Reference" moves the origin both maps are drawn around, which is what
        you want when the launch site differs from the one in config.json.
        """
        row = QHBoxLayout()
        row.setSpacing(6)

        label = QLabel("MANUAL FIX")
        label.setStyleSheet("color:#E0E0E0; font-size:12px; font-weight:bold; letter-spacing:1px;")
        row.addWidget(label)

        self.lat_input = self._coord_input(-90.0, 90.0, self.ref_lat, "Latitude, decimal degrees")
        self.lon_input = self._coord_input(-180.0, 180.0, self.ref_lon, "Longitude, decimal degrees")

        # Altitude is metres above the same datum as telemetry altitude, so a
        # plotted point rises off the ground plane the way a live fix does.
        self.alt_input = QDoubleSpinBox()
        self.alt_input.setDecimals(1)
        self.alt_input.setRange(-1000.0, 100000.0)
        self.alt_input.setSingleStep(10.0)
        self.alt_input.setValue(self.ref_alt)
        self.alt_input.setToolTip("Altitude in meters (same datum as telemetry altitude)")
        self.alt_input.setStyleSheet(_INPUT_STYLE)
        self.alt_input.setFixedWidth(100)

        row.addWidget(QLabel("Lat"))
        row.addWidget(self.lat_input)
        row.addWidget(QLabel("Lon"))
        row.addWidget(self.lon_input)
        row.addWidget(QLabel("Alt (m)"))
        row.addWidget(self.alt_input)

        self.plot_btn = QPushButton("Plot Position")
        self.plot_btn.setStyleSheet("padding: 6px 12px; background-color: #0078D7; font-weight: bold;")
        self.plot_btn.clicked.connect(self.plot_manual_position)
        row.addWidget(self.plot_btn)

        self.set_ref_btn = QPushButton("Set as Reference")
        self.set_ref_btn.setStyleSheet("padding: 6px 12px; background-color: #333;")
        self.set_ref_btn.clicked.connect(self.set_manual_reference)
        row.addWidget(self.set_ref_btn)

        self.manual_chk = QCheckBox("Ignore telemetry")
        self.manual_chk.setToolTip(
            "While checked, incoming GNSS fixes do not move the maps — "
            "otherwise the next packet overwrites a manually plotted position."
        )
        self.manual_chk.setStyleSheet("color:#E0E0E0; font-size:12px;")
        row.addWidget(self.manual_chk)

        row.addStretch(1)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#8FD3FF; font-size:12px;")
        row.addWidget(self.status_lbl)

        return row

    def _coord_input(self, minimum, maximum, value, tooltip):
        box = QDoubleSpinBox()
        # Six decimals is ~0.1 m of latitude — finer than any GNSS fix the
        # telemetry link carries, so typed coordinates are never truncated.
        box.setDecimals(6)
        box.setRange(minimum, maximum)
        box.setSingleStep(0.0001)
        box.setValue(value)
        box.setToolTip(tooltip)
        box.setStyleSheet(_INPUT_STYLE)
        box.setFixedWidth(130)
        return box

    def plot_manual_position(self):
        """Treat the typed coordinates as a position fix."""
        lat = self.lat_input.value()
        lon = self.lon_input.value()
        alt = self.alt_input.value()

        # Without this a live link would erase the manual point on its very
        # next packet. Checking the box (rather than only telling the user to)
        # keeps the plotted position on screen; unchecking it hands the maps
        # straight back to telemetry.
        self.manual_chk.setChecked(True)

        self._apply_position(lat, lon, alt)
        dist_m = haversine_m(self.ref_lat, self.ref_lon, lat, lon)
        self.status_lbl.setText(
            f"Plotted {lat:.6f}, {lon:.6f} — {_format_distance(dist_m)} from reference "
            f"(telemetry ignored)"
        )

    def set_manual_reference(self):
        """Move the reference point — the origin of the 3D local frame and the
        flag on the 2D map — to the typed coordinates."""
        self.ref_lat = self.lat_input.value()
        self.ref_lon = self.lon_input.value()
        self.ref_alt = self.alt_input.value()

        # Clears the live trace and reloads terrain around the new origin:
        # points already plotted are ENU meters from the old one.
        self.trajectory_view.set_reference(self.ref_lat, self.ref_lon)
        self.update_ref_map(None, None)
        self.status_lbl.setText(
            f"Reference moved to {self.ref_lat:.6f}, {self.ref_lon:.6f} "
            f"(alt {self.ref_alt:.1f} m) — live trace cleared"
        )

    def update_position(self, lat, lon, alt=None):
        """Called by dashboard when new coordinates arrive.

        alt is optional (meters, same convention as telemetry altitude) —
        fixes without an altimeter reading still update the ref map and
        plot flat (up=0) on the 3D trajectory.

        Deliberately not named update() — that would shadow QWidget.update().
        """
        if self.manual_chk.isChecked():
            return

        # Keeps the inputs showing the latest fix, so editing one field is a
        # nudge from where the vehicle actually is rather than a fresh guess.
        self._show_in_inputs(lat, lon, alt)
        self._apply_position(lat, lon, alt)

    def _apply_position(self, lat, lon, alt):
        self.update_ref_map(lat, lon)
        east, north, up = latlon_to_enu(lat, lon, alt, self.ref_lat, self.ref_lon, self.ref_alt)
        self.trajectory_view.add_live_point(east, north, up)

    def _show_in_inputs(self, lat, lon, alt):
        """Write values into the spin boxes without stepping on an edit in
        progress: a field is left alone only while it is focused *and* has
        been typed into, so merely tabbing into the row (or the focus the
        first field gets when the tab opens) doesn't freeze the readout."""
        for box, value in ((self.lat_input, lat), (self.lon_input, lon), (self.alt_input, alt)):
            if value is None or (box.hasFocus() and box.lineEdit().isModified()):
                continue
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def reset(self):
        """Clear the live trajectory trace — called when recording restarts.

        The ideal (simulated) ground track is left in place, same as
        ui/trajectory_3d.py's reset() — it's a standing pre-launch
        reference, not per-recording state.
        """
        self.trajectory_view.reset()

    def update_ref_map(self, gnss_lat, gnss_lon):
        """Second map: reference marker, GNSS marker, geodesic polyline, distance label."""
        try:
            # center map halfway between points (or ref if GNSS missing)
            if gnss_lat is None or gnss_lon is None:
                center = [self.ref_lat, self.ref_lon]
            else:
                center = [(self.ref_lat + gnss_lat)/2.0, (self.ref_lon + gnss_lon)/2.0]

            m2 = folium.Map(
                location=center,
                zoom_start=10,
                tiles=self.tile_url,
                attr=self.tile_attribution,
            )

            # reference marker (distinct)
            folium.Marker(
                [self.ref_lat, self.ref_lon],
                popup=f"Reference\n{self.ref_lat:.6f}, {self.ref_lon:.6f}",
                tooltip="Reference Point",
                icon=folium.Icon(color="blue", icon="flag")
            ).add_to(m2)

            # if GNSS available add marker, geodesic polyline and midpoint distance label
            if gnss_lat is not None and gnss_lon is not None:
                folium.Marker(
                    [gnss_lat, gnss_lon],
                    popup=f"GNSS\n{gnss_lat:.6f}, {gnss_lon:.6f}",
                    tooltip="GNSS Position",
                    icon=folium.Icon(color="lightgreen", icon="glyphicon-screenshot")
                ).add_to(m2)

                # compute geodesic sampled points for a smooth curved line
                line = great_circle_points(self.ref_lat, self.ref_lon, gnss_lat, gnss_lon, n_points=120)
                folium.PolyLine(line, weight=3, opacity=0.9).add_to(m2)

                # compute distance and add label at midpoint
                dist_m = haversine_m(self.ref_lat, self.ref_lon, gnss_lat, gnss_lon)
                dist_str = _format_distance(dist_m)
                mid = line[len(line)//2]

                folium.Marker(
                    [mid[0], mid[1]],
                    icon=folium.DivIcon(html=f"""<div style="font-size:12px;color:#fff;background:rgba(0,0,0,0.6);padding:3px 8px;border-radius:6px;">{dist_str}</div>""")
                ).add_to(m2)

            data = io.BytesIO()
            m2.save(data, close_file=False)
            self.map2_view.setHtml(data.getvalue().decode())
        except Exception as e:
            print(f"[MAP] update_ref_map error: {e}")