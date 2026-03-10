import sys, datetime, io, os, json, csv, time
from collections import deque
import pandas as pd
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QTimer
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
    if not line:
        return None
    delim = fmt.get("delimiter", ",")
    parts = [p.strip() for p in line.split(delim)]
    fields = fmt.get("fields", [])

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
        return None

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
    if len(parts) > len(fields):
        for j in range(len(fields), len(parts)):
            row[f"EXTRA_{j - len(fields)}"] = parts[j]
    return row

class Groundstation(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ser = None
        self.buffer = deque(maxlen=2000)
        self.packet_fmt = load_packet_format()
        self.columns = ["TIMESTAMP"] + [f["name"] for f in self.packet_fmt.get("fields", [])]

        self.roles = self.packet_fmt.get("roles", {
            "time": "TIME_SINCE_S",
            "lat": "GNSS_LAT",
            "lon": "GNSS_LON"
        })

        self.recording = False
        self.packet_count = 0
        self.power_on_time = now()
        self.flight_state = "boot"

        self._csv_has_header = os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 0
        self._csv_fh = open(CSV_PATH, "a", newline="")
        self._csv_writer = csv.DictWriter(self._csv_fh, fieldnames=self.columns)
        if not self._csv_has_header:
            try:
                self._csv_writer.writeheader()
                self._csv_fh.flush()
                self._csv_has_header = True
            except Exception:
                pass

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
        self.setWindowTitle("Groundstation Dashboard — Minimal")
        self.resize(1000, 700)

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
        self.lbl_pkt = QtWidgets.QLabel("Packets: 0")
        self.lbl_state = QtWidgets.QLabel(f"State: {self.flight_state}")
        for lbl in (self.lbl_time, self.lbl_pkt, self.lbl_state):
            lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        stat_box = QtWidgets.QHBoxLayout()
        stat_box.addWidget(self.lbl_time); stat_box.addWidget(self.lbl_pkt); stat_box.addWidget(self.lbl_state)
        stat_wrap = QtWidgets.QWidget(); stat_wrap.setLayout(stat_box)
        grid.addWidget(stat_wrap, 3, 0, 1, 4)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(300)
        grid.addWidget(self.table, 4, 0, 1, 4)

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)

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
            self.ser = serial.Serial(port, BAUD_RATE, timeout=0.02)
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass
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

    def read_serial_lines(self):
        lines = []
        if not self.ser:
            return lines
        try:
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

    def _append_row_to_csv(self, parsed):
        parsed_keys = list(parsed.keys())
        new_keys = [k for k in parsed_keys if k not in self.columns]
        if new_keys:
            new_columns = list(self.columns) + new_keys
            self.columns = new_columns
            self.table.setColumnCount(len(self.columns))
            self.table.setHorizontalHeaderLabels(self.columns)
        row = {c: parsed.get(c, "") for c in self.columns}
        try:
            self._csv_writer.writerow(row)
            if self.packet_count % 10 == 0:
                self._csv_fh.flush()
        except Exception:
            pd.DataFrame([row], columns=self.columns).to_csv(CSV_PATH, mode='a', header=False, index=False)

    def tick(self):
        t0_total = time_block("tick_total")
        t_since = int((now() - self.power_on_time).total_seconds())
        self.lbl_time.setText(f"Time since power: {t_since} s")
        self.lbl_pkt.setText(f"Packets: {self.packet_count}")

        if not self.recording:
            time_block_end(t0_total)
            return

        raw_lines = self.read_serial_lines()
        if not raw_lines:
            time_block_end(t0_total)
            return

        for line in raw_lines:
            parsed = parse_packet(line, self.packet_fmt)
            if parsed is None:
                continue
            parsed["TIMESTAMP"] = iso_ts()
            self.packet_count += 1
            parsed.setdefault("PACKET_COUNT", self.packet_count)
            self.buffer.append(parsed)
            self._append_row_to_csv(parsed)

            self.table.insertRow(0)
            for j, col in enumerate(self.columns):
                self.table.setItem(0, j, QtWidgets.QTableWidgetItem(str(parsed.get(col, ""))))
            if self.table.rowCount() > 10:
                self.table.removeRow(self.table.rowCount() - 1)

        time_block_end(t0_total)

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

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = Groundstation()
    win.show()
    sys.exit(app.exec_())
