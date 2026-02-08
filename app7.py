import sys, datetime, io, os, json
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


def parse_packet(line, fmt):
    """Parse a raw line according to the provided format dict.
    Returns a dict mapping field name -> value or None on parse failure.
    """
    if not line:
        return None
    delim = fmt.get("delimiter", ",")
    parts = [p.strip() for p in line.split(delim)]
    fields = fmt.get("fields", [])

    # If the line is a header (contains field names), auto-detect and update format
    # A header is considered when every token in parts matches a field name from format (case-insensitive)
    maybe_header = all(any(p.lower() == f["name"].lower() for f in fields) for p in parts) if parts else False
    if maybe_header:
        # Rebuild format to match header order but keep types if known
        new_fields = []
        for token in parts:
            token_clean = token.strip()
            # find existing field with same name (case-insensitive)
            match = next((f for f in fields if f["name"].lower() == token_clean.lower()), None)
            if match:
                new_fields.append(match)
            else:
                # unknown header -> assume string
                new_fields.append({"name": token_clean, "type": "str"})
        fmt["fields"] = new_fields
        # persist updated format so future packets use it
        with open(PACKET_FORMAT_PATH, "w") as f:
            json.dump(fmt, f, indent=2)
        return None  # header line; no telemetry row

    if len(parts) < len(fields):
        # not enough fields for current format - bail gracefully
        return None

    row = {}
    for i, field in enumerate(fields):
        name = field.get("name", f"col{i}")
        ftype = field.get("type", "str")
        raw = parts[i] if i < len(parts) else ""
        try:
            if ftype == "float":
                row[name] = float(raw)
            elif ftype == "int":
                row[name] = int(float(raw))
            else:
                row[name] = raw
        except Exception:
            # keep raw string on parse error
            row[name] = raw
    return row


# ---------------- Groundstation App ----------------
class Groundstation(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ser = None
        self.buffer = []

        # load dynamic packet format
        self.packet_fmt = load_packet_format()
        self.columns = [f["name"] for f in self.packet_fmt.get("fields", [])]

        # mapping of roles -> field names. Users can edit this map in packet_format.json under "roles" key.
        # Common roles: time, alt, pres, temp, lat, lon
        self.roles = self.packet_fmt.get("roles", {
            "time": "TIME_SINCE_S",
            "alt": "ALTITUDE_M",
            "pres": "PRESSURE_PA",
            "temp": "TEMP_C",
            "lat": "GNSS_LAT",
            "lon": "GNSS_LON",
        })

        # --- COM Controls ---
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

        # Main layout
        grid = QtWidgets.QGridLayout()
        root = QtWidgets.QWidget(); root.setLayout(grid)
        self.setCentralWidget(root)

        # Title
        title = QtWidgets.QLabel(f"Team: {TEAM_ID} — Groundstation Console")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; font-size: 20px; font-weight: 600;")
        grid.addWidget(title, 0, 0, 1, 4)

        grid.addWidget(port_wrap, 1, 0, 1, 4)

        # Dark stylesheet
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

        # State
        self.recording = False
        self.packet_count = 0
        self.power_on_time = now()
        self.flight_state = "boot"

        # PyQtGraph setup
        pg.setConfigOption('background', 'k')
        pg.setConfigOption('foreground', 'w')

        # ---------- Controls ----------
        self.start_btn = QtWidgets.QPushButton("Start Recording")
        self.stop_btn = QtWidgets.QPushButton("Stop Recording")
        self.start_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)
        ctrl_box = QtWidgets.QHBoxLayout()
        ctrl_box.addWidget(self.start_btn); ctrl_box.addWidget(self.stop_btn)
        ctrl_wrap = QtWidgets.QWidget(); ctrl_wrap.setLayout(ctrl_box)
        grid.addWidget(ctrl_wrap, 2, 0, 1, 1)

        # Send controls
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
        self.lbl_pkt = QtWidgets.QLabel("Packets: 0")
        self.lbl_state = QtWidgets.QLabel(f"State: {self.flight_state}")
        for lbl in (self.lbl_time, self.lbl_pkt, self.lbl_state):
            lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        stat_box = QtWidgets.QHBoxLayout()
        stat_box.addWidget(self.lbl_time); stat_box.addWidget(self.lbl_pkt); stat_box.addWidget(self.lbl_state)
        stat_wrap = QtWidgets.QWidget(); stat_wrap.setLayout(stat_box)
        grid.addWidget(stat_wrap, 3, 0, 1, 4)

        # ---------- Plots (create base plots; data binding is dynamic) ----------
        self.plot_pressure = pg.PlotWidget(title="Pressure vs Time")
        self.plot_temp     = pg.PlotWidget(title="Temperature vs Time")
        self.plot_alt      = pg.PlotWidget(title="Altitude vs Time")
        self.plot_p_alt    = pg.PlotWidget(title="Pressure vs Altitude")
        self.plot_t_alt    = pg.PlotWidget(title="Temp vs Altitude")
        for pw in (self.plot_pressure, self.plot_temp, self.plot_alt, self.plot_p_alt, self.plot_t_alt):
            pw.setMinimumHeight(220); pw.getPlotItem().showGrid(x=True, y=True, alpha=0.2)

        grid.addWidget(self.plot_pressure, 4, 0)
        grid.addWidget(self.plot_temp,     4, 1)
        grid.addWidget(self.plot_alt,      4, 2)
        grid.addWidget(self.plot_p_alt,    5, 0)
        grid.addWidget(self.plot_t_alt,    5, 1)

        # Initialize curves (we'll update data-role mapping later)
        self.cur_pressure = self.plot_pressure.plot(pen='y')
        self.cur_temp     = self.plot_temp.plot(pen='r')
        self.cur_alt      = self.plot_alt.plot(pen='g')
        self.cur_p_alt    = self.plot_p_alt.plot(pen='c', symbol='o', symbolSize=5)
        self.cur_t_alt    = self.plot_t_alt.plot(pen='m', symbol='o', symbolSize=5)
        for curve in (self.cur_pressure, self.cur_temp, self.cur_alt, self.cur_p_alt, self.cur_t_alt):
            curve.setClipToView(True)

        # ---------- Map ----------
        self.map_view = QWebEngineView()
        self.map_view.setMinimumHeight(260)
        grid.addWidget(self.map_view, 5, 2)
        self.update_map(20.5900, 78.9600)

        # ---------- Table ----------
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(200)
        grid.addWidget(self.table, 6, 0, 1, 4)

        # Timer
        self.timer = pg.QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

        # CSV init
        if not os.path.exists(CSV_PATH):
            pd.DataFrame(columns=self.columns).to_csv(CSV_PATH, index=False)

    # ------------------ Helpers ------------------
    def refresh_ports(self):
        self.port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self.port_combo.addItem(p.device)

    def toggle_connection(self):
        if self.ser and self.ser.is_open:
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

    def read_serial_line(self):
        if not self.ser or not getattr(self.ser, "in_waiting", 0):
            return None
        try:
            line = self.ser.readline().decode("utf-8", errors='ignore').strip()
            return line
        except Exception:
            return None

    def send_data(self):
        """Send the command in cmd_edit to the serial port (adds newline)."""
        if not self.ser or not getattr(self.ser, "is_open", False):
            self.last_sent_lbl.setText("Last sent: (not connected)")
            self.last_sent_lbl.setStyleSheet("color: red; font-size: 13px;")
            return

        cmd = self.cmd_edit.text()
        if cmd is None:
            cmd = ""
        # default behavior: append newline so onboard MCU receives a line
        to_send = (cmd + "\n").encode("utf-8")
        try:
            self.ser.write(to_send)
            self.last_sent_lbl.setText(f"Last sent: {cmd}")
            self.last_sent_lbl.setStyleSheet("color: lightgreen; font-size: 13px;")
        except Exception as e:
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

    def tick(self):
        t_since = int((now() - self.power_on_time).total_seconds())
        self.lbl_time.setText(f"Time since power: {t_since} s")
        self.lbl_pkt.setText(f"Packets: {self.packet_count}")

        if not self.recording:
            return

        line = self.read_serial_line()
        if line is None:
            return

        parsed = parse_packet(line, self.packet_fmt)
        if parsed is None:
            return

        # assign packet count and keep track
        self.packet_count += 1
        parsed.setdefault("PACKET_COUNT", self.packet_count)
        self.buffer.append(parsed)

        # persist CSV (ensure columns exist)
        # if new fields introduced, expand CSV header
        current_cols = list(pd.read_csv(CSV_PATH).columns) if os.path.exists(CSV_PATH) else []
        for k in parsed.keys():
            if k not in current_cols:
                current_cols.append(k)
        pd.DataFrame([parsed], columns=current_cols).to_csv(CSV_PATH, mode='a', header=not os.path.exists(CSV_PATH), index=False)

        # ---- Sliding window ----
        times = [r.get(self.roles.get('time', ''), 0) for r in self.buffer if self.roles.get('time') in r]
        t_now = times[-1] if times else t_since
        t_min = max(0, t_now - WINDOW_SEC)
        window_data = [r for r in self.buffer if r.get(self.roles.get('time', ''), t_since) >= t_min]

        # dynamic extraction based on roles; fallback to column names if roles not present
        def extract(role_name):
            key = self.roles.get(role_name)
            if not key:
                return []
            return [r.get(key, None) for r in window_data if key in r]

        times_w = [r.get(self.roles.get('time', ''), None) for r in window_data if self.roles.get('time') in r]
        alt = extract('alt')
        pres = extract('pres')
        temp = extract('temp')

        # Update plots (if data exists)
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

        # scatter plots
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

        # Map update every 20 packets if lat/lon available
        try:
            if self.packet_count % 20 == 0 and self.roles.get('lat') in parsed and self.roles.get('lon') in parsed:
                lat = float(parsed[self.roles['lat']]); lon = float(parsed[self.roles['lon']])
                self.update_map(lat, lon)
        except Exception:
            pass

        # Table: use latest 10 rows and ensure table columns match current packet format
        latest = self.buffer[-10:]
        cols = list({k for r in latest for k in r.keys()})
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(latest))
        for i, r in enumerate(latest):
            for j, col in enumerate(cols):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(r.get(col, ""))))

    # ---------------- Entrypoint helpers ----------------

# ---------------- Entrypoint ----------------
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = Groundstation()
    win.show()
    sys.exit(app.exec_())
