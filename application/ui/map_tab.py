import io
import math
import folium
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView

from core.config import load_config
from ui.trajectory_3d import Trajectory3DView


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

        layout = QVBoxLayout()

        panes_layout = QHBoxLayout()

        # Left pane: 3D trajectory view (ideal vs live, local ENU).
        self.trajectory_view = Trajectory3DView()

        # Right pane: reference + current position + geodesic line.
        self.map2_view = QWebEngineView()
        self.map2_view.setMinimumHeight(400)

        panes_layout.addWidget(self.trajectory_view)
        panes_layout.addWidget(self.map2_view)

        layout.addLayout(panes_layout)

        self.setLayout(layout)

        # Initialize with reference point
        self.update_ref_map(None, None)

    def update_position(self, lat, lon, alt=None):
        """Called by dashboard when new coordinates arrive.

        alt is optional (meters, same convention as telemetry altitude) —
        fixes without an altimeter reading still update the ref map and
        plot flat (up=0) on the 3D trajectory.

        Deliberately not named update() — that would shadow QWidget.update().
        """
        self.update_ref_map(lat, lon)
        east, north, up = latlon_to_enu(lat, lon, alt, self.ref_lat, self.ref_lon, self.ref_alt)
        self.trajectory_view.add_live_point(east, north, up)

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

            m2 = folium.Map(location=center, zoom_start=10, tiles="CartoDB dark_matter")

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
                dist_str = f"{dist_m/1000.0:.3f} km" if dist_m >= 1000 else f"{dist_m:.1f} m"
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