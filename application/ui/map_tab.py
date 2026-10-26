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

    LABEL_STYLE = "font-size:12px;color:#fff;background:rgba(0,0,0,0.6);padding:3px 8px;border-radius:6px;"

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
        
        self.build_maps()

    def build_maps(self):
        """Load both maps once. Fixes then move their layers via JavaScript,
        so the pages never reload (no flicker, no tile refetch)."""
        ref = [self.ref_lat, self.ref_lon]

        # Primary single-point map
        m = folium.Map(location=ref, zoom_start=15, tiles="CartoDB dark_matter")
        pos = folium.CircleMarker(ref, radius=6, popup="Current Position").add_to(m)
        self.map_js, self.pos_js = m.get_name(), pos.get_name()
        self.map_view.setHtml(self._html(m))

        # Second map: reference marker, GNSS marker, geodesic polyline, distance label.
        # GNSS layers start invisible at the reference until the first fix.
        m2 = folium.Map(location=ref, zoom_start=10, tiles="CartoDB dark_matter")
        folium.Marker(
            ref,
            popup=f"Reference\n{self.ref_lat:.6f}, {self.ref_lon:.6f}",
            tooltip="Reference Point",
            icon=folium.Icon(color="blue", icon="flag")
        ).add_to(m2)
        gnss = folium.Marker(
            ref,
            popup="GNSS",
            tooltip="GNSS Position",
            icon=folium.Icon(color="lightgreen", icon="glyphicon-screenshot"),
            opacity=0
        ).add_to(m2)
        line = folium.PolyLine([ref, ref], weight=3, opacity=0.9).add_to(m2)
        label = folium.Marker(ref, icon=folium.DivIcon(html="")).add_to(m2)
        self.map2_js, self.gnss_js = m2.get_name(), gnss.get_name()
        self.line_js, self.label_js = line.get_name(), label.get_name()
        self.map2_view.setHtml(self._html(m2))

    @staticmethod
    def _html(m):
        data = io.BytesIO()
        m.save(data, close_file=False)
        return data.getvalue().decode()

    def update_position(self, lat, lon):
        """Called by dashboard when new coordinates arrive.

        Deliberately not named update() — that would shadow QWidget.update().
        """
        self.map_view.page().runJavaScript(
            f"{self.pos_js}.setLatLng([{lat}, {lon}]); {self.map_js}.panTo([{lat}, {lon}]);"
        )

        line = great_circle_points(self.ref_lat, self.ref_lon, lat, lon, n_points=120)
        dist_m = haversine_m(self.ref_lat, self.ref_lon, lat, lon)
        dist_str = f"{dist_m/1000.0:.3f} km" if dist_m >= 1000 else f"{dist_m:.1f} m"
        mid = line[len(line)//2]
        center = [(self.ref_lat + lat)/2.0, (self.ref_lon + lon)/2.0]

        self.map2_view.page().runJavaScript(f"""
            {self.gnss_js}.setLatLng([{lat}, {lon}]).setOpacity(1)
                .setPopupContent("GNSS<br>{lat:.6f}, {lon:.6f}");
            {self.line_js}.setLatLngs({line});
            {self.label_js}.setLatLng({mid}).setIcon(L.divIcon({{
                className: "empty",
                html: '<div style="{self.LABEL_STYLE}">{dist_str}</div>'
            }}));
            {self.map2_js}.panTo({center});
        """)
