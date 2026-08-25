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


def enu_to_latlon(east, north, ref_lat, ref_lon):
    """Inverse of latlon_to_enu's horizontal projection — East/North meters
    relative to the reference point back to lat/lon.

    Used to project the RocketPy "ideal" trajectory (local ENU, origin at
    the pad) onto the 2D map as a ground-track polyline.
    """
    R = 6371000.0
    lat0 = math.radians(ref_lat)
    lat = ref_lat + math.degrees(north / R)
    lon = ref_lon + math.degrees(east / (R * math.cos(lat0)))
    return lat, lon


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


# Decimate the live ground track beyond this many points — mirrors
# ui/trajectory_3d.py's _MAX_LIVE_POINTS so a long flight stays cheap to
# redraw as a folium PolyLine.
_MAX_LIVE_TRACK_POINTS = 2000


class MapTab(QWidget):

    def __init__(self):
        super().__init__()

        cfg = load_config()
        self.ref_lat = cfg.get("ref_lat", 26.712196)
        self.ref_lon = cfg.get("ref_lon", 84.305725)
        self.ref_alt = cfg.get("ref_alt", 0.0)

        # Ground-track overlay state — the ideal (RocketPy) track is set once
        # per simulation run; the live track accumulates GNSS fixes.
        self._ideal_track = None  # list of [lat, lon], or None before a sim run
        self._live_track = []     # list of [lat, lon]

        layout = QVBoxLayout()

        map_layout = QHBoxLayout()

        # Primary Map (centered on current position)
        self.map_view = QWebEngineView()
        self.map_view.setMinimumHeight(400)

        # Secondary Map (Reference + current + line)
        self.map2_view = QWebEngineView()
        self.map2_view.setMinimumHeight(400)

        map_layout.addWidget(self.map_view)
        map_layout.addWidget(self.map2_view)

        layout.addLayout(map_layout)

        # 3D trajectory: ideal (RocketPy) vs live (telemetry) — full width
        # below the two 2D maps, since it needs its own room to be legible.
        self.trajectory_view = Trajectory3DView()
        layout.addWidget(self.trajectory_view)

        self.trajectory_view.simulation_complete.connect(self._on_sim_result)

        self.setLayout(layout)

        # Initialize with reference point
        self.update_map(self.ref_lat, self.ref_lon)
        self.update_ref_map(None, None)

    def update_position(self, lat, lon, alt=None):
        """Called by dashboard when new coordinates arrive.

        alt is optional (meters, same convention as telemetry altitude) —
        fixes without an altimeter reading still update the 2D maps and
        plot flat (up=0) on the 3D trajectory.

        Deliberately not named update() — that would shadow QWidget.update().
        """
        self._live_track.append([lat, lon])
        if len(self._live_track) > _MAX_LIVE_TRACK_POINTS:
            self._live_track = self._live_track[::2]

        self.update_map(lat, lon)
        self.update_ref_map(lat, lon)
        east, north, up = latlon_to_enu(lat, lon, alt, self.ref_lat, self.ref_lon, self.ref_alt)
        self.trajectory_view.add_live_point(east, north, up)

    def reset(self):
        """Clear the live trajectory trace — called when recording restarts.

        The ideal (simulated) ground track is left in place, same as
        ui/trajectory_3d.py's reset() — it's a standing pre-launch
        reference, not per-recording state.
        """
        self._live_track = []
        self.trajectory_view.reset()

    def _on_sim_result(self, result):
        """Project the RocketPy solve's local ENU trajectory to lat/lon and
        redraw the map with the new ideal ground track."""
        self._ideal_track = [
            list(enu_to_latlon(east, north, self.ref_lat, self.ref_lon))
            for east, north in zip(result["x"], result["y"])
        ]
        last = self._live_track[-1] if self._live_track else [self.ref_lat, self.ref_lon]
        self.update_map(last[0], last[1])

    def update_map(self, lat, lon):
        """Primary map — re-centered on GNSS or REF, with the ideal
        (RocketPy) and live ground tracks drawn as overlaid polylines."""
        try:
            m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB dark_matter")

            if self._ideal_track:
                folium.PolyLine(
                    self._ideal_track, color="#4C99FF", weight=3, opacity=0.85,
                    tooltip="Ideal trajectory (RocketPy)",
                ).add_to(m)

            if len(self._live_track) > 1:
                folium.PolyLine(
                    self._live_track, color="#FF9E42", weight=3, opacity=0.9,
                    tooltip="Live trajectory (GNSS)",
                ).add_to(m)

            folium.CircleMarker([lat, lon], radius=6, color="#FF9E42",
                                 fill=True, fill_opacity=1.0, popup="Current Position").add_to(m)

            if self._ideal_track or self._live_track:
                legend_html = """
                <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                            background: rgba(0,0,0,0.65); color: #fff; font-size: 12px;
                            padding: 6px 10px; border-radius: 6px;">
                  <span style="color:#4C99FF;">&#9632;</span> ideal (RocketPy)&nbsp;&nbsp;
                  <span style="color:#FF9E42;">&#9632;</span> live (GNSS)
                </div>
                """
                m.get_root().html.add_child(folium.Element(legend_html))

            data = io.BytesIO()
            m.save(data, close_file=False)
            self.map_view.setHtml(data.getvalue().decode())
        except Exception as e:
            print(f"[MAP] update_map error: {e}")

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