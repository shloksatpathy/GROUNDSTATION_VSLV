import io
import math
import folium
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView

from core.config import load_config


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


class MapTab(QWidget):

    def __init__(self):
        super().__init__()

        cfg = load_config()
        self.ref_lat = cfg.get("ref_lat", 26.712196)
        self.ref_lon = cfg.get("ref_lon", 84.305725)

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
        self.setLayout(layout)
        
        # Initialize with reference point
        self.update_map(self.ref_lat, self.ref_lon)
        self.update_ref_map(None, None)

    def update(self, lat, lon):
        """Called by dashboard when new coordinates arrive."""
        self.update_map(lat, lon)
        self.update_ref_map(lat, lon)

    def update_map(self, lat, lon):
        """Primary single-point map (re-centered on GNSS or REF)."""
        try:
            m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB dark_matter")
            folium.CircleMarker([lat, lon], radius=6, popup="Current Position").add_to(m)
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