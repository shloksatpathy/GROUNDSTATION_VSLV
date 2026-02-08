import sys, datetime, io, os, json, csv, time
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
WINDOW_SEC = 10   # sliding window size (seconds)

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

def parse_packet(line, fmt):
    """Tolerant parse: accepts shorter (or longer) rows and fills/ignores extras.
       Returns dict or None only for header lines (which update fmt)."""
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
        with open(PACKET_FORMAT_PATH, "w") as f:
            json.dump(fmt, f, indent=2)
        return None  # header line

    row = {}
    for i, field in enumerate(fields):
        name = field.get("name", f"col{i}")
        ftype = field.get("type", "str")
        raw = parts[i] if i < len(parts) else ""
        try:
            if ftype == "float":
                row[name] = float(raw) if raw != "" else None
            elif ftype == "int":
                row[name] = int(float(raw)) if raw != "" else None
            else:
                row[name] = raw
        except Exception:
            row[name] = raw
    # extras beyond defined fields
    if len(parts) > len(fields):
        for j in range(len(fields), len(parts)):
            row[f"EXTRA_{j - len(fields)}"] = parts[j]
    return row

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

        # roles
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
        self.flight_state = "boot"

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
        self.resize(1500, 900)

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

        self.lbl_time = QtWidgets.QLabel(f"Time since power: 0 s")
        self.lbl_pkt = QtWidgets.QLabel("Packets: 0")
        self.lbl_state = QtWidgets.QLabel(f"State: {self.flight_state}")
        for lbl in (self.lbl_time, self.lbl_pkt, self.lbl_state):
            lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        stat_box = QtWidgets.QHBoxLayout()
        stat_box.addWidget(self.lbl_time); stat_box.addWidget(self.lbl_pkt); stat_box.addWidget(self.lbl_state)
        stat_wrap = QtWidgets.QWidget(); stat_wrap.setLayout(stat_box)
        grid.addWidget(stat_wrap, 3, 0, 1, 4)

        # plots
        pg.setConfigOption('background', 'k')
        pg.setConfigOption('foreground', 'w')
        self.plot_pressure = pg.PlotWidget(title="Pressure vs Time")
        self.plot_temp     = pg.PlotWidget(title="Temperature vs Time")
        self.plot_alt      = pg.PlotWidget(title="Altitude vs Time")
        self.plot_p_alt    = pg.PlotWidget(title="Pressure vs Altitude")
        self.plot_t_alt    = pg.PlotWidget(title="Temp vs Altitude")

        # combined and RPY plots (new)
        self.plot_combined = pg.PlotWidget(title="Combined: Altitude / Pressure / Temp vs Time")
        self.plot_rpy = pg.PlotWidget(title="Roll / Pitch / Yaw vs Time")

        for pw in (self.plot_pressure, self.plot_temp, self.plot_alt, self.plot_p_alt, self.plot_t_alt, self.plot_combined, self.plot_rpy):
            pw.setMinimumHeight(220); pw.getPlotItem().showGrid(x=True, y=True, alpha=0.2)
        grid.addWidget(self.plot_pressure, 4, 0)
        grid.addWidget(self.plot_temp,     4, 1)
        grid.addWidget(self.plot_alt,      4, 2)
        grid.addWidget(self.plot_p_alt,    5, 0)
        grid.addWidget(self.plot_t_alt,    5, 1)
        grid.addWidget(self.plot_roll, )
        grid.addWidget(self.plot_pitch, )
        grid.addWidget(self.plot_yaw, )
        self.map_view = QWebEngineView()

        grid.addWidget(self.map_view, 5, 2) # map occupies 5,2

        # place combined and rpy plots on a new row (above the table)
        grid.addWidget(self.plot_combined, 6, 0, 1, 2)
        grid.addWidget(self.plot_rpy,      6, 2)

        # curves
        self.cur_pressure = self.plot_pressure.plot()
        self.cur_temp     = self.plot_temp.plot()
        self.cur_alt      = self.plot_alt.plot()
        self.cur_p_alt    = self.plot_p_alt.plot(symbol='o',symbolSize=5)
        self.cur_t_alt    = self.plot_t_alt.plot(symbol='o',symbolSize=5)

        # combined plot curves with legend
        self.plot_combined.addLegend()
        self.cur_comb_alt = self.plot_combined.plot(name='Altitude', pen=pg.mkPen(width=2))
        self.cur_comb_pres = self.plot_combined.plot(name='Pressure', pen=pg.mkPen(width=2, style=Qt.SolidLine))
        self.cur_comb_temp = self.plot_combined.plot(name='Temp', pen=pg.mkPen(width=2, style=Qt.DashLine))

        # rpy curves + legend
        self.plot_rpy.addLegend()
        self.cur_rpy_roll  = self.plot_rpy.plot(name='Roll', pen=pg.mkPen(width=2))
        self.cur_rpy_pitch = self.plot_rpy.plot(name='Pitch', pen=pg.mkPen(width=2, style=Qt.DashLine))
        self.cur_rpy_yaw   = self.plot_rpy.plot(name='Yaw', pen=pg.mkPen(width=2, style=Qt.DotLine))

        for curve in (self.cur_pressure, self.cur_temp, self.cur_alt, self.cur_p_alt, self.cur_t_alt, self.cur_comb_alt, self.cur_comb_pres, self.cur_comb_temp, self.cur_rpy_roll, self.cur_rpy_pitch, self.cur_rpy_yaw):
            curve.setClipToView(True)

        # map
        self.map_view.setMinimumHeight(260)
        self.update_map(20.5900, 78.9600)

        # table (moved down to make room for new plots)
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(200)
        grid.addWidget(self.table, 7, 0, 1, 4)

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
        self.lbl_state.setText(f"State: {self.flight_state}")

    def stop_recording(self):
        self.recording = False
        self.flight_state = "idle"
        self.lbl_state.setText(f"State: {self.flight_state}")

    def update_map(self, lat, lon):
        m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB dark_matter")
        folium.CircleMarker([lat, lon], radius=6, popup="Current Position").add_to(m)
        data = io.BytesIO()
        m.save(data, close_file=False)
        self.map_view.setHtml(data.getvalue().decode())

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
        t_since = int((now() - self.power_on_time).total_seconds())
        self.lbl_time.setText(f"Time since power: {t_since} s")
        self.lbl_pkt.setText(f"Packets: {self.packet_count}")

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
            time_key = self.roles.get('time', 'TIME_SINCE_S')
            times = [r.get(time_key) for r in self.buffer if time_key in r and r.get(time_key) is not None]
            t_now = times[-1] if times else int((now() - self.power_on_time).total_seconds())
            t_min = max(0, t_now - WINDOW_SEC)
            window_data = [r for r in self.buffer if (r.get(time_key, t_now) is not None and r.get(time_key, t_now) >= t_min)]

            def extract(role_name):
                key = self.roles.get(role_name)
                if not key:
                    return []
                return [r.get(key) for r in window_data if key in r]

            times_w = [r.get(time_key) for r in window_data if time_key in r]
            alt = extract('alt'); pres = extract('pres'); temp = extract('temp')

            # individual plots (unchanged)
            if times_w and alt:
                self.cur_alt.setData(times_w, alt)
                self.plot_alt.setXRange(max(t_min, times_w[0]), t_now)
                alt_min, alt_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                self.plot_alt.setYRange(alt_min, alt_max)
            else:
                self.cur_alt.clear()

            if times_w and pres:
                self.cur_pressure.setData(times_w, pres)
                self.plot_pressure.setXRange(max(t_min, times_w[0]), t_now)
                pres_min, pres_max = self._nice_range(pres, min_pad=0.05, min_span=1.0)
                self.plot_pressure.setYRange(pres_min, pres_max)
            else:
                self.cur_pressure.clear()

            if times_w and temp:
                self.cur_temp.setData(times_w, temp)
                self.plot_temp.setXRange(max(t_min, times_w[0]), t_now)
                temp_min, temp_max = self._nice_range(temp, min_pad=0.1, min_span=1.0)
                self.plot_temp.setYRange(temp_min, temp_max)
            else:
                self.cur_temp.clear()

            if pres and alt and len(pres) == len(alt):
                self.cur_p_alt.setData(pres, alt)
                x_min, x_max = self._nice_range(pres, min_pad=0.05, min_span=1.0)
                y_min, y_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                self.plot_p_alt.setXRange(x_min, x_max); self.plot_p_alt.setYRange(y_min, y_max)
            else:
                self.cur_p_alt.clear()

            if temp and alt and len(temp) == len(alt):
                self.cur_t_alt.setData(temp, alt)
                x_min, x_max = self._nice_range(temp, min_pad=0.1, min_span=1.0)
                y_min, y_max = self._nice_range(alt, min_pad=0.15, min_span=2.0)
                self.plot_t_alt.setXRange(x_min, x_max); self.plot_t_alt.setYRange(y_min, y_max)
            else:
                self.cur_t_alt.clear()

            # --- combined plot update (new) ---
            try:
                if times_w and (alt or pres or temp):
                    # update combined curves; fall back to empty lists when missing
                    if alt:
                        self.cur_comb_alt.setData(times_w, alt)
                    else:
                        self.cur_comb_alt.clear()
                    if pres:
                        self.cur_comb_pres.setData(times_w, pres)
                    else:
                        self.cur_comb_pres.clear()
                    if temp:
                        self.cur_comb_temp.setData(times_w, temp)
                    else:
                        self.cur_comb_temp.clear()
                    # set x range according to the time window
                    self.plot_combined.setXRange(max(t_min, times_w[0]), t_now)
                else:
                    self.cur_comb_alt.clear(); self.cur_comb_pres.clear(); self.cur_comb_temp.clear()
            except Exception:
                pass

            # --- RPY plot update (new) ---
            try:
                roll = extract('roll')
                pitch = extract('pitch')
                # yaw field may not exist in incoming packets; extract will return [] if missing
                yaw = extract('yaw')
                if times_w and (roll or pitch or yaw):
                    if roll:
                        self.cur_rpy_roll.setData(times_w, roll)
                    else:
                        self.cur_rpy_roll.clear()
                    if pitch:
                        self.cur_rpy_pitch.setData(times_w, pitch)
                    else:
                        self.cur_rpy_pitch.clear()
                    if yaw:
                        self.cur_rpy_yaw.setData(times_w, yaw)
                    else:
                        self.cur_rpy_yaw.clear()
                    self.plot_rpy.setXRange(max(t_min, times_w[0]), t_now)
                    # enforce -180..180 y axis as requested
                    self.plot_rpy.setYRange(-180, 180)
                    self.plot_rpy.setLabel('left', 'Angle (deg)')
                else:
                    self.cur_rpy_roll.clear(); self.cur_rpy_pitch.clear(); self.cur_rpy_yaw.clear()
            except Exception:
                pass

            time_block_end(t_plot)

            # map update every 20 packets (kept unchanged)
            try:
                if self.packet_count % 20 == 0 and self.roles.get('lat') in parsed and self.roles.get('lon') in parsed:
                    lat = float(parsed[self.roles['lat']]); lon = float(parsed[self.roles['lon']])
                    # update map less frequently is intentional to avoid slowdown
                    self.update_map(lat, lon)
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
