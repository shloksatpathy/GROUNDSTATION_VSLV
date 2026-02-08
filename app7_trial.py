#!/usr/bin/env python3
import sys, datetime, io, os, json, csv, time, re, math
from collections import deque
import pandas as pd
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWebEngineWidgets import QWebEngineView
import pyqtgraph as pg
import folium
import serial
import serial.tools.list_ports

# ---------------- Config ----------------
CSV_PATH = "Flight_2024ASI-CANSAT0032.csv"
PACKET_FORMAT_PATH = "packet_format.json"  # editable JSON describing incoming packet
TEAM_ID = "2024ASI-CANSAT0032"
BAUD_RATE = 9600
WINDOW_SEC = 10   # sliding window size (seconds)

# manual reference coordinates for second map — set these to your reference point
REF_LAT = 20.5900
REF_LON = 78.9600

# voltage divisor constant for power calculation: power_pct = (voltage / VOLT_DIVISOR) * 100
VOLT_DIVISOR = 7.0  # change to 9.0 if you want later

# flight state numeric mapping (editable)
# default: -1 -> idle (no incoming numeric code yet)
FLIGHT_STATE_MAP = {
    -1: "idle",
     0: "ascent",
     1: "coasting",
     2: "stage-2",   # edit to your desired label (user didn't specify 2's label)
     3: "descent"
}

# ------------ small timing helpers for instrumentation -------------
_latency_log = deque(maxlen=200)
def time_block(name):
    return (name, time.perf_counter())
def time_block_end(token):
    name, t0 = token
    dt = (time.perf_counter() - t0) * 1000.0
    _latency_log.append((name, dt))
    # occasional summary to console
    if len(_latency_log) % 50 == 0:
        s = {}
        for n, d in list(_latency_log)[-50:]:
            s.setdefault(n, []).append(d)
        summary = ", ".join(f"{k}:{sum(v)/len(v):.1f}ms" for k,v in s.items())
        print(f"[LATENCY] last50 avg -> {summary}")

# ---------------- Utilities ----------------
def now():
    return datetime.datetime.now()

def iso_ts(dt=None):
    if dt is None:
        dt = now()
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def load_packet_format(path=PACKET_FORMAT_PATH):
    if not os.path.exists(path):
        default = {
            "delimiter": ",",
            "fields": [
                {"name": "TEAM_ID", "type": "str"},
                {"name": "TIME_SINCE_S", "type": "float"},
                {"name": "PACKET_COUNT", "type": "int"},
                {"name": "ALTITUDE_M", "type": "float"},
                {"name": "PRESSURE_PA", "type": "float"},
                {"name": "TEMP_C", "type": "float"},
                {"name": "VOLTAGE_V", "type": "float"},
                {"name": "GNSS_TIME", "type": "str"},
                {"name": "GNSS_LAT", "type": "float"},
                {"name": "GNSS_LON", "type": "float"},
                {"name": "GNSS_ALT_M", "type": "float"},
                {"name": "GNSS_SATS", "type": "int"},
                {"name": "ACCEL_X_MPS2", "type": "float"},
                {"name": "ACCEL_Y_MPS2", "type": "float"},
                {"name": "ACCEL_Z_MPS2", "type": "float"},
                {"name": "ROLL_DEG", "type": "float"},
                {"name": "PITCH_DEG", "type": "float"},
                {"name": "GYRO_SPIN_RATE_DPS", "type": "float"},
                {"name": "FLIGHT_STATE", "type": "str"},
                {"name": "OPTIONAL_DATA", "type": "str"}
            ]
        }
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default
    with open(path, "r") as f:
        return json.load(f)

# ---------------- robust numeric extractor ----------------
_num_re = re.compile(r'[+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?')
def _clean_numeric(raw):
    """Return numeric substring of raw (e.g. '85.98W' -> '85.98'), or '' if none."""
    if raw is None:
        return ""
    s = str(raw).strip()
    m = _num_re.search(s)
    return m.group(0) if m else ""

# ---------------- tolerant parse_packet ----------------
def parse_packet(line, fmt):
    """Tolerant parse: accepts shorter (or longer) rows and fills/ignores extras.
       Detects a leading device timestamp and extracts numeric substrings for numeric fields."""
    if not line:
        return None
    delim = fmt.get("delimiter", ",")
    parts = [p.strip() for p in line.split(delim)]
    fields = fmt.get("fields", [])

    # header detection (if tokens match known fields)
    maybe_header = all(any(p.lower() == f["name"].lower() for f in fields) for p in parts) if parts else False
    if maybe_header:
        new_fields = []
        for token in parts:
            token_clean = token.strip()
            match = next((f for f in fields if f["name"].lower() == token_clean.lower()), None)
            if match:
                new_fields.append(match)
            else:
                new_fields.append({"name": token_clean, "type": "str"})
        fmt["fields"] = new_fields
        with open(PACKET_FORMAT_PATH, "w") as fh:
            json.dump(fmt, fh, indent=2)
        return None  # header line

    row = {}
    device_ts = None
    # detect leading ISO-like timestamp (e.g. "2025-10-25 00:49:05.754")
    if parts and re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', parts[0]):
        device_ts = parts.pop(0)  # remove it so field indices align

    for i, field in enumerate(fields):
        name = field.get("name", f"col{i}")
        ftype = field.get("type", "str")
        raw = parts[i] if i < len(parts) else ""
        try:
            if ftype == "float":
                raw_clean = _clean_numeric(raw)
                row[name] = float(raw_clean) if raw_clean != "" else None
            elif ftype == "int":
                raw_clean = _clean_numeric(raw)
                row[name] = int(float(raw_clean)) if raw_clean != "" else None
            else:
                row[name] = raw
        except Exception:
            row[name] = raw
    # extras beyond defined fields
    if len(parts) > len(fields):
        for j in range(len(fields), len(parts)):
            row[f"EXTRA_{j - len(fields)}"] = parts[j]
    if device_ts is not None:
        row["DEVICE_TIMESTAMP"] = device_ts
    return row

# ---------------- Great-circle interpolation (geodesic approx) ----------------
def great_circle_points(lat1, lon1, lat2, lon2, n_points=100):
    """Return list of [lat, lon] along great-circle from point1 to point2 inclusive.
       Uses spherical interpolation; returns n_points points including endpoints.
    """
    # convert to radians
    φ1 = math.radians(lat1); λ1 = math.radians(lon1)
    φ2 = math.radians(lat2); λ2 = math.radians(lon2)

    # angular distance
    dφ = φ2 - φ1
    dλ = λ2 - λ1
    a = math.sin(dφ/2.0)**2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ/2.0)**2
    δ = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))

    if δ == 0:
        return [[lat1, lon1] for _ in range(n_points)]

    points = []
    for i in range(n_points):
        f = i / (n_points - 1)  # fraction 0..1
        A = math.sin((1 - f) * δ) / math.sin(δ)
        B = math.sin(f * δ) / math.sin(δ)
        x = A * math.cos(φ1) * math.cos(λ1) + B * math.cos(φ2) * math.cos(λ2)
        y = A * math.cos(φ1) * math.sin(λ1) + B * math.cos(φ2) * math.sin(λ2)
        z = A * math.sin(φ1) + B * math.sin(φ2)
        φi = math.atan2(z, math.sqrt(x * x + y * y))
        λi = math.atan2(y, x)
        points.append([math.degrees(φi), math.degrees(λi)])
    return points

# ---------------- Haversine distance ----------------
def haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in meters between two lat/lon points (Haversine)."""
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# ---------------- Groundstation App ----------------
class Groundstation(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ser = None

        # bounded in-memory buffer
        self.buffer = deque(maxlen=2000)

        # load dynamic packet format
        self.packet_fmt = load_packet_format()
        self.columns = ["TIMESTAMP"] + [f["name"] for f in self.packet_fmt.get("fields", [])]

        # roles (default)
        self.roles = self.packet_fmt.get("roles", {
            "time": "TIME_SINCE_S",
            "alt": "ALTITUDE_M",
            "pres": "PRESSURE_PA",
            "temp": "TEMP_C",
            "lat": "GNSS_LAT",
            "lon": "GNSS_LON",
            # attitude roles (yaw may be missing in incoming format)
            "roll": "ROLL_DEG",
            "pitch": "PITCH_DEG",
            "yaw": "YAW_DEG"
        })

        # diagnostics
        self.recording = False
        self.packet_count = 0
        self.power_on_time = now()
        self.flight_state = "idle"

        self._diag_raw_lines = 0
        self._diag_parsed = 0
        self._diag_dropped = 0
        self._diag_last_tx_seen = None
        self._diag_start_time = now()
        self._diag_last_report = now()

        # persistent CSV handle + header flag
        self._csv_has_header = os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 0
        self._csv_fh = open(CSV_PATH, "a", newline="")  # keep open for fast append
        self._csv_writer = csv.DictWriter(self._csv_fh, fieldnames=self.columns)
        if not self._csv_has_header:
            try:
                self._csv_writer.writeheader()
                self._csv_fh.flush()
                self._csv_has_header = True
            except Exception:
                pass

        # --- UI Controls ---
        self.port_combo = QtWidgets.QComboBox()
        self.refresh_ports()
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.lbl_conn = QtWidgets.QLabel("Not Connected")
        self.lbl_conn.setStyleSheet("color: orange; font-size: 12px;")
        port_box = QtWidgets.QHBoxLayout()
        port_box.addWidget(QtWidgets.QLabel("Serial Port:"))
        port_box.addWidget(self.port_combo)
        port_box.addWidget(self.connect_btn)
        port_box.addWidget(self.lbl_conn)
        port_wrap = QtWidgets.QWidget(); port_wrap.setLayout(port_box)

        grid = QtWidgets.QGridLayout()
        root = QtWidgets.QWidget(); root.setLayout(grid)
        self.setCentralWidget(root)

        title = QtWidgets.QLabel(f"Team: {TEAM_ID} — Groundstation Console")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; font-size: 20px; font-weight: 600;")
        grid.addWidget(title, 0, 0, 1, 4)

        grid.addWidget(port_wrap, 1, 0, 1, 4)

        self.setStyleSheet("""
        QMainWindow { background-color: #121212; color: #E0E0E0; }
        QWidget { background-color: #121212; color: #E0E0E0; font-size: 14px; }
        QPushButton {
            background-color: #1E1E1E; border: 1px solid #333; border-radius: 6px; padding: 6px; color: #E0E0E0;
        }
        QPushButton:hover { background-color: #333; }
        QTableWidget { background-color: #1E1E1E; gridline-color: #444; color: #E0E0E0; }
        QHeaderView::section { background-color: #2C2C2C; color: #E0E0E0; padding: 4px; border: none; }
        """)
        self.setWindowTitle("Groundstation Dashboard — PyQtGraph + Folium (Dynamic Format)")
        self.resize(1500, 950)

        # controls
        self.start_btn = QtWidgets.QPushButton("Start Recording")
        self.stop_btn = QtWidgets.QPushButton("Stop Recording")
        self.start_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)
        ctrl_box = QtWidgets.QHBoxLayout()
        ctrl_box.addWidget(self.start_btn); ctrl_box.addWidget(self.stop_btn)
        ctrl_wrap = QtWidgets.QWidget(); ctrl_wrap.setLayout(ctrl_box)
        grid.addWidget(ctrl_wrap, 2, 0, 1, 1)

        self.cmd_edit = QtWidgets.QLineEdit()
        self.cmd_edit.setPlaceholderText("Enter command to send (e.g. START)")
        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.clicked.connect(self.send_data)
        self.send_btn.setEnabled(False)
        self.last_sent_lbl = QtWidgets.QLabel("Last sent: —")
        self.last_sent_lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        send_box = QtWidgets.QHBoxLayout()
        send_box.addWidget(QtWidgets.QLabel("Command:"))
        send_box.addWidget(self.cmd_edit)
        send_box.addWidget(self.send_btn)
        send_box.addWidget(self.last_sent_lbl)
        send_wrap = QtWidgets.QWidget(); send_wrap.setLayout(send_box)
        grid.addWidget(send_wrap, 2, 1, 1, 3)

        # ---------------- top-left: device time + IST ----------------
        self.lbl_time = QtWidgets.QLabel("Device Time: — | IST: —")
        self.lbl_time.setStyleSheet("color: #ccc; font-size: 13px;")
        grid.addWidget(self.lbl_time, 3, 0, 1, 4)

        # plots: separated into individual time-series
        pg.setConfigOption('background', 'k')
        pg.setConfigOption('foreground', 'w')

        # Individual time-based plots
        self.plot_alt = pg.PlotWidget(title="Altitude vs Time")
        self.plot_pres = pg.PlotWidget(title="Pressure vs Time")
        self.plot_temp = pg.PlotWidget(title="Temperature vs Time")

        # R, P, Y separate plots
        self.plot_roll = pg.PlotWidget(title="Roll vs Time")
        self.plot_pitch = pg.PlotWidget(title="Pitch vs Time")
        self.plot_yaw = pg.PlotWidget(title="Yaw vs Time")

        # keep pressure/temp vs altitude on the left (existing scatter plots)
        self.plot_p_alt = pg.PlotWidget(title="Pressure vs Altitude")
        self.plot_t_alt = pg.PlotWidget(title="Temp vs Altitude")

        for pw in (self.plot_p_alt, self.plot_t_alt, self.plot_alt, self.plot_pres, self.plot_temp, self.plot_roll, self.plot_pitch, self.plot_yaw):
            pw.setMinimumHeight(160); pw.getPlotItem().showGrid(x=True, y=True, alpha=0.2)

        # place altitude/pressure/temp at top row (cols 0..2) and main map at col 3
        grid.addWidget(self.plot_alt, 4, 0)
        grid.addWidget(self.plot_pres, 4, 1)
        grid.addWidget(self.plot_temp, 4, 2)

        # main map (right)
        self.map_view = QWebEngineView()
        grid.addWidget(self.map_view, 4, 3)
        self.map_view.setMinimumHeight(220)
        self.update_map(REF_LAT, REF_LON)

        # place RPY separated in the next row (columns 0-2)
        grid.addWidget(self.plot_roll, 5, 0)
        grid.addWidget(self.plot_pitch, 5, 1)
        grid.addWidget(self.plot_yaw, 5, 2)

        # second map (reference + GNSS + geodesic) on right, below main map
        self.ref_lat = REF_LAT
        self.ref_lon = REF_LON
        self.map2_view = QWebEngineView()
        grid.addWidget(self.map2_view, 5, 3)
        self.map2_view.setMinimumHeight(220)
        # initialize with both markers at the reference point
        self.update_ref_map(self.ref_lat, self.ref_lon, None, None)

        # keep pressure vs altitude and temp vs altitude lower-left
        grid.addWidget(self.plot_p_alt, 6, 0)
        grid.addWidget(self.plot_t_alt, 6, 1)

        # ---------------- Info Block (below maps) ----------------
        # This block contains: Time since power (device TIME_SINCE_S), State, Power (%), Packet Count
        info_layout = QtWidgets.QVBoxLayout()
        info_widget = QtWidgets.QWidget(); info_widget.setLayout(info_layout)
        info_widget.setStyleSheet("background:#1A1A1A; border:1px solid #333; border-radius:6px; padding:8px;")

        # labels
        self.info_lbl_time = QtWidgets.QLabel("Time since power: — s")
        self.info_lbl_state = QtWidgets.QLabel("State: idle")
        self.info_lbl_power = QtWidgets.QLabel("Power: — %")
        self.info_lbl_pkt = QtWidgets.QLabel("Packets: —")

        for lbl in (self.info_lbl_time, self.info_lbl_state, self.info_lbl_power, self.info_lbl_pkt):
            lbl.setStyleSheet("color:#E0E0E0; font-size:14px;")
            info_layout.addWidget(lbl)

        # place info block (below maps, right side)
        grid.addWidget(info_widget, 6, 2, 1, 2)

        # table (moved down)
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(160)
        grid.addWidget(self.table, 7, 0, 1, 4)

        # curves for p_alt/t_alt
        self.cur_p_alt    = self.plot_p_alt.plot(symbol='o',symbolSize=5)
        self.cur_t_alt    = self.plot_t_alt.plot(symbol='o',symbolSize=5)

        # individual time-series curves (no combined plot)
        self.cur_alt = self.plot_alt.plot(pen=pg.mkPen(color=QColor(0,120,215), width=2))
        self.cur_pres = self.plot_pres.plot(pen=pg.mkPen(color=QColor(255,165,0), width=2))
        self.cur_temp = self.plot_temp.plot(pen=pg.mkPen(color=QColor(0,200,0), width=2))

        # RPY individual curves
        self.cur_roll  = self.plot_roll.plot(pen=pg.mkPen(color=QColor(220,20,60), width=2))
        self.cur_pitch = self.plot_pitch.plot(pen=pg.mkPen(color=QColor(199,21,133), width=2))
        self.cur_yaw   = self.plot_yaw.plot(pen=pg.mkPen(color=QColor(0,206,209), width=2))

        for curve in (self.cur_p_alt, self.cur_t_alt, self.cur_alt, self.cur_pres, self.cur_temp, self.cur_roll, self.cur_pitch, self.cur_yaw):
            curve.setClipToView(True)

        # label x-axis as seconds
        for pw in (self.plot_alt, self.plot_pres, self.plot_temp, self.plot_roll, self.plot_pitch, self.plot_yaw):
            pw.setLabel('bottom', 'Time (s)')

        # timer: faster polling for responsiveness
        self.timer = pg.QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)   # 50 ms

    # ------------------ Helpers ------------------
    def refresh_ports(self):
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(p.device)

    def toggle_connection(self):
        if self.ser and getattr(self.ser, "is_open", False):
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            self.lbl_conn.setText("Disconnected")
            self.lbl_conn.setStyleSheet("color: orange; font-size: 12px;")
            self.connect_btn.setText("Connect")
            self.send_btn.setEnabled(False)
            return

        port = self.port_combo.currentText()
        try:
            # reduced timeout to be more responsive
            self.ser = serial.Serial(port, BAUD_RATE, timeout=0.02)
            # clear any backlog on connect
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass
            self.lbl_conn.setText(f"Connected to {port}")
            self.lbl_conn.setStyleSheet("color: lightgreen; font-size: 12px;")
            self.connect_btn.setText("Disconnect")
            self.send_btn.setEnabled(True)
        except Exception as e:
            self.ser = None
            self.lbl_conn.setText("Connection Failed")
            self.lbl_conn.setStyleSheet("color: red; font-size: 12px;")
            self.send_btn.setEnabled(False)

    def start_recording(self):
        self.recording = True
        self.flight_state = "idle"
        # will be updated from packet parsing
        # self.lbl_state.setText(f"State: {self.flight_state}")

    def stop_recording(self):
        self.recording = False
        # keep flight_state as is

    def update_map(self, lat, lon):
        """Primary single-point map (re-centered on GNSS or REF)."""
        try:
            m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB dark_matter")
            folium.CircleMarker([lat, lon], radius=6, popup="Current Position").add_to(m)
            data = io.BytesIO()
            m.save(data, close_file=False)
            self.map_view.setHtml(data.getvalue().decode())
        except Exception:
            pass

    def update_ref_map(self, ref_lat, ref_lon, gnss_lat, gnss_lon):
        """Second map: reference marker, GNSS marker (if present), geodesic polyline, and distance label."""
        try:
            # center map halfway between points (or ref if GNSS missing)
            if gnss_lat is None or gnss_lon is None:
                center = [ref_lat, ref_lon]
            else:
                center = [ (ref_lat + gnss_lat)/2.0, (ref_lon + gnss_lon)/2.0 ]

            m2 = folium.Map(location=center, zoom_start=10, tiles="CartoDB dark_matter")

            # reference marker (distinct)
            folium.Marker(
                [ref_lat, ref_lon],
                popup=f"Reference\n{ref_lat:.6f}, {ref_lon:.6f}",
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

                # compute geodesic (great-circle) sampled points for a smooth curved line
                line = great_circle_points(ref_lat, ref_lon, gnss_lat, gnss_lon, n_points=120)
                folium.PolyLine(line, weight=3, opacity=0.9).add_to(m2)

                # compute distance and add label at midpoint
                dist_m = haversine_m(ref_lat, ref_lon, gnss_lat, gnss_lon)
                if dist_m >= 1000:
                    dist_str = f"{dist_m/1000.0:.3f} km"
                else:
                    dist_str = f"{dist_m:.1f} m"
                mid = line[len(line)//2]
                mid_lat, mid_lon = mid[0], mid[1]

                folium.Marker(
                    [mid_lat, mid_lon],
                    icon=folium.DivIcon(html=f"""<div style="font-size:12px;color:#fff;background:rgba(0,0,0,0.6);padding:3px 8px;border-radius:6px;">{dist_str}</div>""")
                ).add_to(m2)

            data = io.BytesIO()
            m2.save(data, close_file=False)
            self.map2_view.setHtml(data.getvalue().decode())
        except Exception:
            pass

    def _get_latest_device_time(self):
        """Return latest device 'time' value (in seconds) from buffer or None.
        Heuristic: if numeric value > 10000 assume it's milliseconds and divide by 1000.
        """
        time_key = self.roles.get('time', 'TIME_SINCE_S')
        for r in reversed(self.buffer):
            if time_key not in r:
                continue
            v = r.get(time_key)
            if v is None or v == "":
                continue
            try:
                val = float(v)
            except Exception:
                m = _num_re.search(str(v))
                if not m:
                    continue
                try:
                    val = float(m.group(0))
                except Exception:
                    continue
            # heuristic: treat large numbers as ms
            if val > 10000:
                val = val / 1000.0
            return val
        return None

    def _derive_flight_state_str(self, parsed):
        """Look for a numeric flight state in parsed data and map to string using FLIGHT_STATE_MAP."""
        # Candidate keys (commonly present)
        candidates = ["FLIGHT_STATE", "FLIGHT_STATE_CODE", "STATE", "MODE"]
        for k in candidates:
            if k in parsed:
                v = parsed.get(k)
                if v is None or v == "":
                    continue
                # try integer extraction
                try:
                    code = int(float(v))
                    return FLIGHT_STATE_MAP.get(code, f"code:{code}")
                except Exception:
                    # if string label already provided
                    sval = str(v).strip().lower()
                    # try to find matching map value
                    for code, label in FLIGHT_STATE_MAP.items():
                        if label.lower() == sval:
                            return label
                    return sval
        # fallback: no numeric state in parsed
        return FLIGHT_STATE_MAP.get(-1, "idle")

    def _get_voltage_from_parsed(self, parsed):
        # common field name VOLTAGE_V
        cand = ["VOLTAGE_V", "VOLTAGE", "VBAT", "V"]
        for k in cand:
            if k in parsed:
                v = parsed.get(k)
                if v is None or v == "":
                    continue
                try:
                    return float(_num_re.search(str(v)).group(0))
                except Exception:
                    try:
                        return float(v)
                    except Exception:
                        pass
        return None

    def read_serial_lines(self):
        """Drain the serial buffer and return all available non-empty lines."""
        lines = []
        if not self.ser:
            return lines
        try:
            # read until empty (non-blocking behavior thanks to small timeout and in_waiting)
            while getattr(self.ser, "in_waiting", 0):
                raw = self.ser.readline().decode("utf-8", errors='ignore').strip()
                if raw:
                    lines.append(raw)
            return lines
        except Exception:
            return lines

    def send_data(self):
        if not self.ser or not getattr(self.ser, "is_open", False):
            self.last_sent_lbl.setText("Last sent: (not connected)")
            self.last_sent_lbl.setStyleSheet("color: red; font-size: 13px;")
            return
        cmd = self.cmd_edit.text() or ""
        to_send = (cmd + "\n").encode("utf-8")
        try:
            self.ser.write(to_send)
            self.last_sent_lbl.setText(f"Last sent: {cmd}")
            self.last_sent_lbl.setStyleSheet("color: lightgreen; font-size: 13px;")
        except Exception:
            self.last_sent_lbl.setText(f"Last sent: FAILED")
            self.last_sent_lbl.setStyleSheet("color: red; font-size: 13px;")
            self.lbl_conn.setText(f"Write Failed")
            self.lbl_conn.setStyleSheet("color: red; font-size: 12px;")

    def _nice_range(self, values, min_pad=0.1, min_span=1.0):
        if not values:
            return 0.0, min_span
        vmin = min(values)
        vmax = max(values)
        if vmin == vmax:
            return vmin - min_span/2.0, vmax + min_span/2.0
        span = vmax - vmin
        pad = max(min_span * 0.1, span * min_pad)
        return vmin - pad, vmax + pad

    # ---------- CSV helpers ----------
    def _rewrite_csv_with_new_columns(self, new_columns):
        """Rare: rewrite CSV header/data to include new columns."""
        ordered = ["TIMESTAMP"]
        for f in self.packet_fmt.get("fields", []):
            name = f["name"]
            if name in new_columns and name not in ordered:
                ordered.append(name)
        for c in new_columns:
            if c not in ordered:
                ordered.append(c)

        # read existing and reindex
        try:
            if os.path.exists(CSV_PATH):
                df = pd.read_csv(CSV_PATH)
            else:
                df = pd.DataFrame(columns=self.columns)
            for c in ordered:
                if c not in df.columns:
                    df[c] = ""
            df = df.reindex(columns=ordered)
            df.to_csv(CSV_PATH, index=False)
        except Exception:
            # fallback: write header only
            with open(CSV_PATH, "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=ordered)
                writer.writeheader()
        # reopen writer with new header
        try:
            self._csv_fh.close()
        except Exception:
            pass
        self.columns = ordered
        self._csv_fh = open(CSV_PATH, "a", newline="")
        self._csv_writer = csv.DictWriter(self._csv_fh, fieldnames=self.columns)
        self._csv_has_header = True

    def _append_row_to_csv(self, parsed):
        parsed_keys = list(parsed.keys())
        new_keys = [k for k in parsed_keys if k not in self.columns]
        if new_keys:
            # expand header rarely
            new_columns = list(self.columns) + new_keys
            self._rewrite_csv_with_new_columns(new_columns)
        row = {c: parsed.get(c, "") for c in self.columns}
        try:
            self._csv_writer.writerow(row)
            # flush occasionally to avoid losing data on crash; keep cheap
            if self.packet_count % 10 == 0:
                self._csv_fh.flush()
        except Exception:
            # fallback: pandas append (rare)
            pd.DataFrame([row], columns=self.columns).to_csv(CSV_PATH, mode='a', header=False, index=False)

    # ---------------- main tick (optimized) ----------------
    def tick(self):
        t0_total = time_block("tick_total")

        # update top-left label: device TIME_SINCE_S (from incoming data) + IST
        latest_dev_time = self._get_latest_device_time()
        if latest_dev_time is not None:
            dev_str = f"{latest_dev_time:.3f} s"
        else:
            dev_str = "—"
        # IST now (UTC+5:30)
        ist_offset = datetime.timedelta(hours=5, minutes=30)
        ist_now = datetime.datetime.now(datetime.timezone(ist_offset))
        ist_str = ist_now.strftime("%Y-%m-%d %H:%M:%S")
        self.lbl_time.setText(f"Device Time: {dev_str} | IST: {ist_str}")

        if not self.recording:
            time_block_end(t0_total)
            return

        # Drain all available lines and process each immediately
        t_read = time_block("read_serial")
        raw_lines = self.read_serial_lines()
        time_block_end(t_read)

        if not raw_lines:
            # periodic diagnostics print every 5 seconds
            if (now() - self._diag_last_report).total_seconds() > 5:
                elapsed = (now() - self._diag_start_time).total_seconds()
                print(f"[DIAG] elapsed={elapsed:.0f}s raw={self._diag_raw_lines} parsed={self._diag_parsed} dropped={self._diag_dropped} buffer_len={len(self.buffer)} pkt_count_local={self.packet_count} last_tx_seen={self._diag_last_tx_seen}")
                self._diag_last_report = now()
            time_block_end(t0_total)
            return

        for line in raw_lines:
            self._diag_raw_lines += 1
            t_parse = time_block("parse_packet")
            parsed = parse_packet(line, self.packet_fmt)
            time_block_end(t_parse)
            if parsed is None:
                self._diag_dropped += 1
                continue

            # success path
            self._diag_parsed += 1
            # if incoming has PACKET_COUNT, use it for diag only (we still increment our local pack count)
            if "PACKET_COUNT" in parsed:
                try:
                    tx = int(parsed["PACKET_COUNT"]) if parsed["PACKET_COUNT"] is not None else None
                    self._diag_last_tx_seen = tx
                except Exception:
                    pass

            # add timestamp and ensure PACKET_COUNT exists
            parsed["TIMESTAMP"] = iso_ts()
            self.packet_count += 1
            parsed.setdefault("PACKET_COUNT", self.packet_count)

            # buffer append (fast)
            t_buf = time_block("buffer_append")
            self.buffer.append(parsed)
            time_block_end(t_buf)

            # CSV append (fast)
            t_csv = time_block("csv_append")
            # optionally, you can temporarily comment this while debugging
            self._append_row_to_csv(parsed)
            time_block_end(t_csv)

            # plotting (use window from buffer)
            t_plot = time_block("plot_update")

            # ---------------- time normalization (handles ms vs s and aligns to t0) ----------------
            time_key = self.roles.get('time', 'TIME_SINCE_S')

            # collect raw time values and attempt numeric extraction
            raw_times = []
            for r in self.buffer:
                v = r.get(time_key)
                if v is None:
                    continue
                try:
                    raw_times.append(float(v))
                except Exception:
                    m = _num_re.search(str(v))
                    if m:
                        try:
                            raw_times.append(float(m.group(0)))
                        except Exception:
                            pass

            # if no times available, fallback to system time window
            if not raw_times:
                t_now = int((now() - self.power_on_time).total_seconds())
                t_min = max(0, t_now - WINDOW_SEC)
                window_data = [r for r in self.buffer]
                times_w = []
            else:
                max_raw = max(raw_times)
                # heuristic: if values are large (>10k) treat as ms -> seconds
                is_ms = (max_raw > 10000)

                # build paired list of (record, time_in_seconds)
                paired = []
                for r in self.buffer:
                    v = r.get(time_key)
                    if v is None:
                        continue
                    try:
                        tv = float(v)
                    except Exception:
                        m = _num_re.search(str(v))
                        if m:
                            try:
                                tv = float(m.group(0))
                            except Exception:
                                continue
                        else:
                            continue
                    if is_ms:
                        tv = tv / 1000.0
                    paired.append((r, tv))

                if not paired:
                    t_now = int((now() - self.power_on_time).total_seconds())
                    t_min = max(0, t_now - WINDOW_SEC)
                    window_data = [r for r in self.buffer]
                    times_w = []
                else:
                    # normalize to zero based on first seen packet in paired list
                    t0 = paired[0][1]
                    paired_norm = [(r, tv - t0) for (r, tv) in paired]
                    t_now = paired_norm[-1][1]
                    t_min = max(0, t_now - WINDOW_SEC)
                    window_data = [r for (r, tv) in paired_norm if tv >= t_min]
                    times_w = [tv for (r, tv) in paired_norm if tv >= t_min]

            # small helper to extract numeric lists robustly from window_data
            def extract_numeric_list(key):
                out = []
                if not key:
                    return out
                for r in window_data:
                    if key not in r:
                        continue
                    v = r.get(key)
                    if v is None or v == "":
                        continue
                    try:
                        out.append(float(v))
                    except Exception:
                        m = _num_re.search(str(v))
                        if m:
                            try:
                                out.append(float(m.group(0)))
                            except Exception:
                                continue
                return out

            alt = extract_numeric_list(self.roles.get('alt'))
            pres = extract_numeric_list(self.roles.get('pres'))
            temp = extract_numeric_list(self.roles.get('temp'))

            # --- pressure vs altitude (existing scatter) ---
            try:
                if pres and alt and len(pres) == len(alt):
                    self.cur_p_alt.setData(pres, alt)
                    x_min, x_max = self._nice_range(pres, min_pad=0.05, min_span=1.0)
                    y_min, y_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                    self.plot_p_alt.setXRange(x_min, x_max); self.plot_p_alt.setYRange(y_min, y_max)
                else:
                    self.cur_p_alt.clear()
            except Exception as e:
                print("p_alt plot error:", e)
                self.cur_p_alt.clear()

            # --- temp vs altitude (existing scatter) ---
            try:
                if temp and alt and len(temp) == len(alt):
                    self.cur_t_alt.setData(temp, alt)
                    x_min, x_max = self._nice_range(temp, min_pad=0.1, min_span=1.0)
                    y_min, y_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                    self.plot_t_alt.setXRange(x_min, x_max); self.plot_t_alt.setYRange(y_min, y_max)
                else:
                    self.cur_t_alt.clear()
            except Exception as e:
                print("t_alt plot error:", e)
                self.cur_t_alt.clear()

            # --- Individual time-series updates (Altitude / Pressure / Temp) ---
            try:
                if times_w and (alt or pres or temp):
                    # Build aligned lists for each series from window_data
                    alt_vals = []
                    pres_vals = []
                    temp_vals = []
                    for r in window_data:
                        a = None; p = None; t = None
                        if self.roles.get('alt') in r:
                            try: a = float(_num_re.search(str(r[self.roles.get('alt')])).group(0))
                            except Exception: pass
                        if self.roles.get('pres') in r:
                            try: p = float(_num_re.search(str(r[self.roles.get('pres')])).group(0))
                            except Exception: pass
                        if self.roles.get('temp') in r:
                            try: t = float(_num_re.search(str(r[self.roles.get('temp')])).group(0))
                            except Exception: pass
                        alt_vals.append(a); pres_vals.append(p); temp_vals.append(t)

                    # Altitude plot
                    if any(a is not None for a in alt_vals):
                        x_a = [times_w[i] for i, a in enumerate(alt_vals) if a is not None]
                        y_a = [a for a in alt_vals if a is not None]
                        self.cur_alt.setData(x_a, y_a)
                        x_min, x_max = (max(t_min, x_a[0]), t_now) if x_a else (0, WINDOW_SEC)
                        y_min, y_max = self._nice_range(y_a, min_pad=0.15, min_span=2.0)
                        try:
                            self.plot_alt.setXRange(x_min, x_max)
                        except Exception:
                            pass
                        try:
                            self.plot_alt.setYRange(y_min, y_max)
                        except Exception:
                            pass
                    else:
                        self.cur_alt.clear()

                    # Pressure plot
                    if any(p is not None for p in pres_vals):
                        x_p = [times_w[i] for i, p in enumerate(pres_vals) if p is not None]
                        y_p = [p for p in pres_vals if p is not None]
                        self.cur_pres.setData(x_p, y_p)
                        y_min, y_max = self._nice_range(y_p, min_pad=0.05, min_span=1.0)
                        try:
                            self.plot_pres.setXRange(max(t_min, x_p[0]), t_now)
                        except Exception:
                            pass
                        try:
                            self.plot_pres.setYRange(y_min, y_max)
                        except Exception:
                            pass
                    else:
                        self.cur_pres.clear()

                    # Temp plot
                    if any(t is not None for t in temp_vals):
                        x_t = [times_w[i] for i, t in enumerate(temp_vals) if t is not None]
                        y_t = [t for t in temp_vals if t is not None]
                        self.cur_temp.setData(x_t, y_t)
                        y_min, y_max = self._nice_range(y_t, min_pad=0.1, min_span=1.0)
                        try:
                            self.plot_temp.setXRange(max(t_min, x_t[0]), t_now)
                        except Exception:
                            pass
                        try:
                            self.plot_temp.setYRange(y_min, y_max)
                        except Exception:
                            pass
                    else:
                        self.cur_temp.clear()
                else:
                    self.cur_alt.clear(); self.cur_pres.clear(); self.cur_temp.clear()
            except Exception as e:
                print("individual time-series plot error:", e)

            # --- Roll / Pitch / Yaw plot updates (separate plots) ---
            try:
                # extract rpy lists aligned to times_w
                roll = []
                pitch = []
                yaw = []
                for r in window_data:
                    for name, dest in ((self.roles.get('roll'), roll), (self.roles.get('pitch'), pitch), (self.roles.get('yaw'), yaw)):
                        if not name or name not in r:
                            dest.append(None)
                        else:
                            try:
                                dest.append(float(_num_re.search(str(r[name])).group(0)))
                            except Exception:
                                dest.append(None)

                # helper to set per-plot data
                def set_single_plot(curve, arr, plot_widget, y_range=None):
                    if any(v is not None for v in arr) and times_w:
                        x = [times_w[i] for i, v in enumerate(arr) if v is not None]
                        y = [v for v in arr if v is not None]
                        curve.setData(x, y)
                        try:
                            plot_widget.setXRange(max(t_min, x[0]), t_now)
                        except Exception:
                            pass
                        if y_range is not None:
                            try:
                                plot_widget.setYRange(y_range[0], y_range[1])
                            except Exception:
                                pass
                        else:
                            try:
                                y_min, y_max = self._nice_range(y, min_pad=0.1, min_span=1.0)
                                plot_widget.setYRange(y_min, y_max)
                            except Exception:
                                pass
                    else:
                        curve.clear()

                set_single_plot(self.cur_roll, roll, self.plot_roll, y_range=(-180, 180))
                set_single_plot(self.cur_pitch, pitch, self.plot_pitch, y_range=(-180, 180))
                set_single_plot(self.cur_yaw, yaw, self.plot_yaw, y_range=(-180, 180))
            except Exception as e:
                print("rpy individual plot error:", e)

            time_block_end(t_plot)

            # map updates every 20 packets: primary map and geodesic secondary map
            try:
                if self.packet_count % 20 == 0 and self.roles.get('lat') in parsed and self.roles.get('lon') in parsed:
                    lat_raw = parsed[self.roles['lat']]
                    lon_raw = parsed[self.roles['lon']]
                    lat_s = _clean_numeric(lat_raw)
                    lon_s = _clean_numeric(lon_raw)
                    if lat_s and lon_s:
                        lat = float(lat_s); lon = float(lon_s)
                        # update primary single-point map
                        self.update_map(lat, lon)
                        # update second map with reference + GNSS and geodesic connecting line
                        self.update_ref_map(self.ref_lat, self.ref_lon, lat, lon)
            except Exception:
                pass

            # ----- Update Info Block (Time since power from device, State, Power%, Packet count) -----
            try:
                # device time (latest)
                latest_dev_time = self._get_latest_device_time()
                if latest_dev_time is not None:
                    self.info_lbl_time.setText(f"Time since power: {latest_dev_time:.3f} s")
                else:
                    self.info_lbl_time.setText("Time since power: —")

                # flight state
                state_str = self._derive_flight_state_str(parsed)
                self.info_lbl_state.setText(f"State: {state_str}")

                # power calculation
                voltage = self._get_voltage_from_parsed(parsed)
                if voltage is not None and VOLT_DIVISOR and VOLT_DIVISOR != 0:
                    power_pct = (voltage / float(VOLT_DIVISOR)) * 100.0
                    self.info_lbl_power.setText(f"Power: {power_pct:.1f} % (V={voltage:.2f}V / DIV={VOLT_DIVISOR})")
                else:
                    self.info_lbl_power.setText("Power: —")

                # packet count from incoming data (prefer PACKET_COUNT field if present)
                pkt_val = None
                if "PACKET_COUNT" in parsed and parsed.get("PACKET_COUNT") is not None:
                    try:
                        pkt_val = int(parsed.get("PACKET_COUNT"))
                    except Exception:
                        pkt_val = parsed.get("PACKET_COUNT")
                else:
                    # fallback to local incremental counter
                    pkt_val = self.packet_count
                self.info_lbl_pkt.setText(f"Packets: {pkt_val}")
            except Exception:
                pass

            # table update incremental (insert newest at top; keep max 10 rows)
            t_table = time_block("table_update")
            new_cols = [k for k in parsed.keys() if k not in self.columns]
            if new_cols:
                self.columns += new_cols
                old_count = self.table.columnCount()
                new_count = len(self.columns)
                self.table.setColumnCount(new_count)
                self.table.setHorizontalHeaderLabels(self.columns)
            self.table.insertRow(0)
            max_rows = 10
            for j, col in enumerate(self.columns):
                self.table.setItem(0, j, QtWidgets.QTableWidgetItem(str(parsed.get(col, ""))))
            if self.table.rowCount() > max_rows:
                self.table.removeRow(self.table.rowCount() - 1)
            time_block_end(t_table)

        time_block_end(t0_total)

    # ---------------- Entrypoint helpers ----------------

    def closeEvent(self, event):
        try:
            self._csv_fh.flush()
            self._csv_fh.close()
        except Exception:
            pass
        try:
            if self.ser and getattr(self.ser, "is_open", False):
                self.ser.close()
        except Exception:
            pass
        event.accept()

# ---------------- Entrypoint ----------------
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = Groundstation()
    win.show()
    sys.exit(app.exec_())
