#!/usr/bin/env python3
import sys, datetime, io, os, json, csv, time, re
from collections import deque
import pandas as pd
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWebEngineWidgets import QWebEngineView
import pyqtgraph as pg
import folium
import serial
import serial.tools.list_ports

CSV_PATH = "Flight_2024ASI-CANSAT0032.csv"
PACKET_FORMAT_PATH = "packet_format.json"  # editable JSON describing incoming packet
TEAM_ID = "2024ASI-CANSAT0032"
BAUD_RATE = 9600
WINDOW_SEC = 10   # <-- sliding window size (10s)

# ---------------- Utilities ----------------

def now():
    return datetime.datetime.now()

def iso_ts(dt=None):
    """Human-readable timestamp with milliseconds: YYYY-MM-DD HH:MM:SS.sss"""
    if dt is None:
        dt = now()
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def ist_ts(dt=None):
    """Return IST timestamp string (Asia/Kolkata, UTC+5:30)"""
    if dt is None:
        dt = datetime.datetime.utcnow()
    ist = dt + datetime.timedelta(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%d %H:%M:%S")

def load_packet_format(path=PACKET_FORMAT_PATH):
    """Load packet description from JSON. If file missing, return a sensible default."""
    if not os.path.exists(path):
        # default format compatible with previous hardcoded columns
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


def parse_packet(line, fmt):
    """Parse a raw line according to the provided format dict.
    Detect and drop a leading device timestamp (ISO-like) so fields align.
    Returns dict mapping field name -> value, or None for header/insufficient fields.
    """
    if not line:
        return None
    delim = fmt.get("delimiter", ",")
    parts = [p.strip() for p in line.split(delim)]
    fields = fmt.get("fields", [])

    # Header detection: if every token matches one of known field names (case-insensitive)
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
        # persist
        try:
            with open(PACKET_FORMAT_PATH, "w") as fh:
                json.dump(fmt, fh, indent=2)
        except Exception:
            pass
        return None

    # If line too short, bail (we require at least as many tokens as fields)
    if len(parts) < len(fields):
        # but allow if the first token is a leading device timestamp -> try popping it and recheck
        if parts and re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', parts[0]):
            parts.pop(0)
        if len(parts) < len(fields):
            return None

    # If first token looks like an ISO timestamp, drop it so indices align with fields
    device_ts = None
    if parts and re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', parts[0]):
        device_ts = parts.pop(0)

    row = {}
    for i, field in enumerate(fields):
        name = field.get("name", f"col{i}")
        ftype = field.get("type", "str")
        raw = parts[i] if i < len(parts) else ""
        try:
            if ftype == "float":
                # tolerant: extract numeric substring
                raw_clean = _clean_numeric(raw)
                row[name] = float(raw_clean) if raw_clean != "" else None
            elif ftype == "int":
                raw_clean = _clean_numeric(raw)
                row[name] = int(float(raw_clean)) if raw_clean != "" else None
            else:
                row[name] = raw
        except Exception:
            row[name] = raw

    # extras
    if len(parts) > len(fields):
        for j in range(len(fields), len(parts)):
            row[f"EXTRA_{j - len(fields)}"] = parts[j]

    if device_ts is not None:
        row["DEVICE_TIMESTAMP"] = device_ts

    return row


# ---------------- Groundstation App ----------------
class Groundstation(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ser = None
        # keep a deque buffer for efficient pops; store parsed dicts
        self.buffer = deque(maxlen=2000)

        # load dynamic packet format
        self.packet_fmt = load_packet_format()
        # TIMESTAMP will be the first column in CSV and table
        self.columns = ["TIMESTAMP"] + [f["name"] for f in self.packet_fmt.get("fields", [])] + ["TIME_SINCE_S_NORM"]

        # roles mapping
        self.roles = self.packet_fmt.get("roles", {
            "time": "TIME_SINCE_S",
            "alt": "ALTITUDE_M",
            "pres": "PRESSURE_PA",
            "temp": "TEMP_C",
            "lat": "GNSS_LAT",
            "lon": "GNSS_LON",
            "roll": "ROLL_DEG",
            "pitch": "PITCH_DEG",
            "yaw": "GYRO_SPIN_RATE_DPS",
        })

        # state
        self.recording = False
        self.packet_count = 0
        self.power_on_time = now()
        self.flight_state = "boot"

        # time normalization state
        self._time_offset_set = False
        self._time_offset = 0.0
        self._detected_ms = False

        # UI / Comms
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
        self.resize(1200, 800)

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

        self.lbl_time = QtWidgets.QLabel("Time since power: 0 s")
        self.lbl_ist = QtWidgets.QLabel(f"IST: {ist_ts()}")
        self.lbl_pkt = QtWidgets.QLabel("Packets: 0")
        self.lbl_state = QtWidgets.QLabel(f"State: {self.flight_state}")
        for lbl in (self.lbl_time, self.lbl_ist, self.lbl_pkt, self.lbl_state):
            lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        stat_box = QtWidgets.QHBoxLayout()
        stat_box.addWidget(self.lbl_time); stat_box.addWidget(self.lbl_ist); stat_box.addWidget(self.lbl_pkt); stat_box.addWidget(self.lbl_state)
        stat_wrap = QtWidgets.QWidget(); stat_wrap.setLayout(stat_box)
        grid.addWidget(stat_wrap, 3, 0, 1, 4)

        # ---------- Plots ----------
        pg.setConfigOption('background', 'k')
        pg.setConfigOption('foreground', 'w')

        self.plot_pressure = pg.PlotWidget(title="Pressure vs Time")
        self.plot_temp     = pg.PlotWidget(title="Temperature vs Time")
        self.plot_alt      = pg.PlotWidget(title="Altitude vs Time")
        self.plot_p_alt    = pg.PlotWidget(title="Pressure vs Altitude")
        self.plot_t_alt    = pg.PlotWidget(title="Temp vs Altitude")
        for pw in (self.plot_pressure, self.plot_temp, self.plot_alt, self.plot_p_alt, self.plot_t_alt):
            pw.setMinimumHeight(200); pw.getPlotItem().showGrid(x=True, y=True, alpha=0.2)

        grid.addWidget(self.plot_pressure, 4, 0)
        grid.addWidget(self.plot_temp,     4, 1)
        grid.addWidget(self.plot_alt,      4, 2)
        grid.addWidget(self.plot_p_alt,    5, 0)
        grid.addWidget(self.plot_t_alt,    5, 1)

        # Initialize curves
        self.cur_pressure = self.plot_pressure.plot(pen='y')
        self.cur_temp     = self.plot_temp.plot(pen='r')
        self.cur_alt      = self.plot_alt.plot(pen='g')
        self.cur_p_alt    = self.plot_p_alt.plot(pen='c', symbol='o', symbolSize=5)
        self.cur_t_alt    = self.plot_t_alt.plot(pen='m', symbol='o', symbolSize=5)
        for curve in (self.cur_pressure, self.cur_temp, self.cur_alt, self.cur_p_alt, self.cur_t_alt):
            curve.setClipToView(True)

        # map
        self.map_view = QWebEngineView()
        self.map_view.setMinimumHeight(260)
        grid.addWidget(self.map_view, 5, 2)
        self.update_map(20.5900, 78.9600)

        # attitude plots
        self.plot_roll = pg.PlotWidget(title="Roll (deg) vs Time")
        self.plot_pitch = pg.PlotWidget(title="Pitch (deg) vs Time")
        self.plot_yaw = pg.PlotWidget(title="Yaw (deg) vs Time")
        for pw in (self.plot_roll, self.plot_pitch, self.plot_yaw):
            pw.setMinimumHeight(180); pw.getPlotItem().showGrid(x=True, y=True, alpha=0.2)

        grid.addWidget(self.plot_roll, 6, 0)
        grid.addWidget(self.plot_pitch, 6, 1)
        grid.addWidget(self.plot_yaw, 6, 2)

        self.cur_roll = self.plot_roll.plot(pen='w')
        self.cur_pitch = self.plot_pitch.plot(pen='c')
        self.cur_yaw = self.plot_yaw.plot(pen='y')
        for curve in (self.cur_roll, self.cur_pitch, self.cur_yaw):
            curve.setClipToView(True)

        # table
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(200)
        grid.addWidget(self.table, 7, 0, 1, 4)

        # timer
        self.timer = pg.QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

        # ensure CSV exists with header
        if not os.path.exists(CSV_PATH):
            pd.DataFrame(columns=self.columns).to_csv(CSV_PATH, index=False)

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
            self.ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
            self.lbl_conn.setText(f"Connected to {port}")
            self.lbl_conn.setStyleSheet("color: lightgreen; font-size: 12px;")
            self.connect_btn.setText("Disconnect")
            self.send_btn.setEnabled(True)
        except Exception:
            self.ser = None
            self.lbl_conn.setText("Connection Failed")
            self.lbl_conn.setStyleSheet("color: red; font-size: 12px;")
            self.send_btn.setEnabled(False)

    def start_recording(self):
        self.recording = True
        self.flight_state = "idle"
        self.lbl_state.setText(f"State: {self.flight_state}")

    def stop_recording(self):
        self.recording = False
        self.flight_state = "idle"
        self.lbl_state.setText(f"State: {self.flight_state}")

    def update_map(self, lat, lon):
        try:
            m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB dark_matter")
            folium.CircleMarker([lat, lon], radius=6, popup="Current Position").add_to(m)
            data = io.BytesIO()
            m.save(data, close_file=False)
            self.map_view.setHtml(data.getvalue().decode())
        except Exception:
            pass

    def read_serial_line(self):
        if not self.ser or not getattr(self.ser, "in_waiting", 0):
            return None
        try:
            line = self.ser.readline().decode("utf-8", errors='ignore').strip()
            return line
        except Exception:
            return None

    def send_data(self):
        if not self.ser or not getattr(self.ser, "is_open", False):
            return
        cmd = self.cmd_edit.text() or ""
        try:
            self.ser.write((cmd + "\n").encode("utf-8"))
            self.last_sent_lbl.setText(f"Last sent: {cmd}")
            self.last_sent_lbl.setStyleSheet("color: lightgreen; font-size: 13px;")
        except Exception:
            self.last_sent_lbl.setText("Last sent: FAILED"); self.last_sent_lbl.setStyleSheet("color: red;")

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

    def append_csv(self, parsed):
        # Append a parsed row to CSV, adding missing columns if needed.
        if not os.path.exists(CSV_PATH):
            pd.DataFrame([parsed], columns=self.columns).to_csv(CSV_PATH, index=False)
            return
        try:
            df = pd.read_csv(CSV_PATH)
        except Exception:
            pd.DataFrame([parsed], columns=self.columns).to_csv(CSV_PATH, index=False)
            return
        # ensure columns
        existing = list(df.columns)
        for k in parsed.keys():
            if k not in existing:
                existing.append(k)
                df[k] = ""
        # write with TIMESTAMP first and TIME_SINCE_S_NORM appended at end
        ordered = ["TIMESTAMP"]
        for f in self.packet_fmt.get("fields", []):
            if f["name"] in existing and f["name"] not in ordered:
                ordered.append(f["name"])
        if "TIME_SINCE_S_NORM" not in ordered:
            ordered.append("TIME_SINCE_S_NORM")
        for c in existing:
            if c not in ordered:
                ordered.append(c)
        new_row = {c: parsed.get(c, "") for c in ordered}
        df = df.reindex(columns=ordered)
        df = pd.concat([df, pd.DataFrame([new_row], columns=ordered)], ignore_index=True)
        df.to_csv(CSV_PATH, index=False)

    def tick(self):
        t_since = int((now() - self.power_on_time).total_seconds())
        self.lbl_time.setText(f"Time since power: {t_since} s")
        self.lbl_ist.setText(f"IST: {ist_ts()}")
        self.lbl_pkt.setText(f"Packets: {self.packet_count}")

        if not self.recording:
            return

        line = self.read_serial_line()
        if line is None:
            return

        parsed = parse_packet(line, self.packet_fmt)
        if parsed is None:
            return

        # add system timestamp and packet_count
        parsed["TIMESTAMP"] = iso_ts()
        self.packet_count += 1
        parsed.setdefault("PACKET_COUNT", self.packet_count)

        # append to buffer
        self.buffer.append(parsed)

        # --- Time normalization logic (handles ms vs s) ---
        time_key = self.roles.get('time', 'TIME_SINCE_S')

        # gather raw times from buffer with numeric-cleaning
        raw_times = []
        for r in list(self.buffer):
            if time_key in r:
                v = r.get(time_key)
                if v is None:
                    continue
                try:
                    raw_times.append(float(v))
                except Exception:
                    s = _clean_numeric(v)
                    if s != "":
                        try:
                            raw_times.append(float(s))
                        except Exception:
                            pass

        # detect ms heuristic (if max_raw > 10000 treat as ms)
        if raw_times:
            max_raw = max(raw_times)
            detected_ms = max_raw > 10000  # tune threshold if needed
        else:
            detected_ms = False

        # set offset once (based on first buffer entry)
        if raw_times and not self._time_offset_set:
            first_raw = raw_times[0]
            if detected_ms:
                self._time_offset = first_raw / 1000.0
                self._detected_ms = True
            else:
                self._time_offset = first_raw
                self._detected_ms = False
            self._time_offset_set = True

        # compute normalized times and attach TIME_SINCE_S_NORM to each record (for CSV and plotting)
        paired = []  # list of (record, t_norm)
        for r in list(self.buffer):
            if time_key not in r:
                continue
            v = r.get(time_key)
            if v is None or v == "":
                continue
            try:
                tv = float(v)
            except Exception:
                s = _clean_numeric(v)
                if s == "":
                    continue
                try:
                    tv = float(s)
                except Exception:
                    continue
            if self._detected_ms:
                tv = tv / 1000.0
            # t_norm subtract offset (if set)
            if self._time_offset_set:
                t_norm = tv - self._time_offset
            else:
                t_norm = tv
            # attach normalized time to record copy (but keep original in CSV row)
            # we set TIME_SINCE_S_NORM in the parsed dict used for CSV
            r["TIME_SINCE_S_NORM"] = t_norm
            paired.append((r, t_norm))

        # decide window
        if paired:
            t_now = paired[-1][1]
            t_min = max(0.0, t_now - WINDOW_SEC)
            window_data = [r for (r, tv) in paired if tv >= t_min]
            times_w = [tv for (r, tv) in paired if tv >= t_min]
        else:
            t_now = t_since
            t_min = max(0, t_now - WINDOW_SEC)
            window_data = list(self.buffer)
            times_w = []

        # append to CSV asynchronously (kept simple here)
        try:
            self.append_csv(parsed)
        except Exception:
            pass

        # helper: robust numeric extractor over window_data
        def extract_numeric(role_name):
            key = self.roles.get(role_name)
            if not key:
                return []
            out = []
            for r in window_data:
                if key not in r:
                    continue
                v = r.get(key)
                if v is None or v == "":
                    continue
                try:
                    out.append(float(v))
                except Exception:
                    s = _clean_numeric(v)
                    if s != "":
                        try:
                            out.append(float(s))
                        except Exception:
                            continue
            return out

        alt = extract_numeric('alt')
        pres = extract_numeric('pres')
        temp = extract_numeric('temp')
        roll = extract_numeric('roll')
        pitch = extract_numeric('pitch')
        yaw = extract_numeric('yaw')

        # Update plots with checks
        try:
            if times_w and alt:
                self.cur_alt.setData(times_w, alt)
                self.plot_alt.setXRange(max(t_min, times_w[0]), t_now)
                alt_min, alt_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                self.plot_alt.setYRange(alt_min, alt_max)
            else:
                self.cur_alt.clear()
        except Exception:
            self.cur_alt.clear()

        try:
            if times_w and pres:
                self.cur_pressure.setData(times_w, pres)
                self.plot_pressure.setXRange(max(t_min, times_w[0]), t_now)
                pres_min, pres_max = self._nice_range(pres, min_pad=0.05, min_span=1.0)
                self.plot_pressure.setYRange(pres_min, pres_max)
            else:
                self.cur_pressure.clear()
        except Exception:
            self.cur_pressure.clear()

        try:
            if times_w and temp:
                self.cur_temp.setData(times_w, temp)
                self.plot_temp.setXRange(max(t_min, times_w[0]), t_now)
                temp_min, temp_max = self._nice_range(temp, min_pad=0.1, min_span=1.0)
                self.plot_temp.setYRange(temp_min, temp_max)
            else:
                self.cur_temp.clear()
        except Exception:
            self.cur_temp.clear()

        # attitude
        try:
            if times_w and roll:
                self.cur_roll.setData(times_w, roll)
                self.plot_roll.setXRange(max(t_min, times_w[0]), t_now)
                rmin, rmax = self._nice_range(roll, min_pad=0.05, min_span=1.0)
                self.plot_roll.setYRange(rmin, rmax)
            else:
                self.cur_roll.clear()
        except Exception:
            self.cur_roll.clear()

        try:
            if times_w and pitch:
                self.cur_pitch.setData(times_w, pitch)
                self.plot_pitch.setXRange(max(t_min, times_w[0]), t_now)
                pmin, pmax = self._nice_range(pitch, min_pad=0.05, min_span=1.0)
                self.plot_pitch.setYRange(pmin, pmax)
            else:
                self.cur_pitch.clear()
        except Exception:
            self.cur_pitch.clear()

        try:
            if times_w and yaw:
                self.cur_yaw.setData(times_w, yaw)
                self.plot_yaw.setXRange(max(t_min, times_w[0]), t_now)
                ymin, ymax = self._nice_range(yaw, min_pad=0.05, min_span=1.0)
                self.plot_yaw.setYRange(ymin, ymax)
            else:
                self.cur_yaw.clear()
        except Exception:
            self.cur_yaw.clear()

        # scatter plots
        try:
            if pres and alt and len(pres) == len(alt):
                self.cur_p_alt.setData(pres, alt)
                x_min, x_max = self._nice_range(pres, min_pad=0.05, min_span=1.0)
                y_min, y_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                self.plot_p_alt.setXRange(x_min, x_max); self.plot_p_alt.setYRange(y_min, y_max)
            else:
                self.cur_p_alt.clear()
        except Exception:
            self.cur_p_alt.clear()

        try:
            if temp and alt and len(temp) == len(alt):
                self.cur_t_alt.setData(temp, alt)
                x_min, x_max = self._nice_range(temp, min_pad=0.1, min_span=1.0)
                y_min, y_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                self.plot_t_alt.setXRange(x_min, x_max); self.plot_t_alt.setYRange(y_min, y_max)
            else:
                self.cur_t_alt.clear()
        except Exception:
            self.cur_t_alt.clear()

        # map update every 20 packets
        try:
            if self.packet_count % 20 == 0 and self.roles.get('lat') in parsed and self.roles.get('lon') in parsed:
                lat_s = _clean_numeric(parsed[self.roles['lat']])
                lon_s = _clean_numeric(parsed[self.roles['lon']])
                if lat_s and lon_s:
                    self.update_map(float(lat_s), float(lon_s))
        except Exception:
            pass

        # update table with latest 10 rows
        latest = list(self.buffer)[-10:]
        cols_set = {k for r in latest for k in r.keys()}
        cols_ordered = ["TIMESTAMP"]
        for f in self.packet_fmt.get("fields", []):
            name = f["name"]
            if name in cols_set and name not in cols_ordered:
                cols_ordered.append(name)
        if "TIME_SINCE_S_NORM" in cols_set and "TIME_SINCE_S_NORM" not in cols_ordered:
            cols_ordered.append("TIME_SINCE_S_NORM")
        for k in sorted(cols_set):
            if k not in cols_ordered:
                cols_ordered.append(k)
        self.table.setColumnCount(len(cols_ordered))
        self.table.setHorizontalHeaderLabels(cols_ordered)
        self.table.setRowCount(len(latest))
        for i, r in enumerate(reversed(latest)):  # show newest at top
            for j, col in enumerate(cols_ordered):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(r.get(col, ""))))

# ---------------- Entrypoint ----------------
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = Groundstation()
    win.show()
    sys.exit(app.exec_())
