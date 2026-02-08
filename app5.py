import sys, datetime, io, os
import pandas as pd
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWebEngineWidgets import QWebEngineView
import pyqtgraph as pg
import folium
import serial
import serial.tools.list_ports

CSV_PATH = "Flight_2024ASI-CANSAT0032.csv"
TEAM_ID = "2024ASI-CANSAT0032"
BAUD_RATE = 9600
WINDOW_SEC = 10   # <-- sliding window size (10s)




def now():
    return datetime.datetime.now()

class Groundstation(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ser = None
        self.buffer = []

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
        self.setWindowTitle("Groundstation Dashboard — PyQtGraph + Folium (Dark)")
        self.resize(1500, 900)

        # Data columns
        self.columns = [
            "TEAM_ID","TIME_SINCE_S","PACKET_COUNT","ALTITUDE_M","PRESSURE_PA","TEMP_C",
            "VOLTAGE_V","GNSS_TIME","GNSS_LAT","GNSS_LON","GNSS_ALT_M","GNSS_SATS",
            "ACCEL_X_MPS2","ACCEL_Y_MPS2","ACCEL_Z_MPS2","ROLL_DEG","PITCH_DEG",
            "GYRO_SPIN_RATE_DPS","FLIGHT_STATE","OPTIONAL_DATA",
        ]

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

        self.lbl_time = QtWidgets.QLabel("Time since power: 0 s")
        self.lbl_pkt = QtWidgets.QLabel("Packets: 0")
        self.lbl_state = QtWidgets.QLabel(f"State: {self.flight_state}")
        for lbl in (self.lbl_time, self.lbl_pkt, self.lbl_state):
            lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        stat_box = QtWidgets.QHBoxLayout()
        stat_box.addWidget(self.lbl_time); stat_box.addWidget(self.lbl_pkt); stat_box.addWidget(self.lbl_state)
        stat_wrap = QtWidgets.QWidget(); stat_wrap.setLayout(stat_box)
        grid.addWidget(stat_wrap, 2, 1, 1, 3)

        # ---------- Plots ----------
        self.plot_pressure = pg.PlotWidget(title="Pressure vs Time (Pa)")
        self.plot_temp     = pg.PlotWidget(title="Temperature vs Time (°C)")
        self.plot_alt      = pg.PlotWidget(title="Altitude vs Time (m)")
        self.plot_p_alt    = pg.PlotWidget(title="Pressure vs Altitude")
        self.plot_t_alt    = pg.PlotWidget(title="Temp vs Altitude")
        for pw in (self.plot_pressure, self.plot_temp, self.plot_alt, self.plot_p_alt, self.plot_t_alt):
            pw.setMinimumHeight(220); pw.getPlotItem().showGrid(x=True, y=True, alpha=0.2)

        grid.addWidget(self.plot_pressure, 3, 0)
        grid.addWidget(self.plot_temp,     3, 1)
        grid.addWidget(self.plot_alt,      3, 2)
        grid.addWidget(self.plot_p_alt,    4, 0)
        grid.addWidget(self.plot_t_alt,    4, 1)

        # Initialize curves
        self.cur_pressure = self.plot_pressure.plot(pen='y')
        self.cur_temp     = self.plot_temp.plot(pen='r')
        self.cur_alt      = self.plot_alt.plot(pen='g')
        self.cur_p_alt    = self.plot_p_alt.plot(pen='c', symbol='o', symbolSize=3)
        self.cur_t_alt    = self.plot_t_alt.plot(pen='m', symbol='o', symbolSize=3)

        # ---------- Map ----------
        self.map_view = QWebEngineView()
        self.map_view.setMinimumHeight(260)
        grid.addWidget(self.map_view, 4, 2)
        self.update_map(20.5900, 78.9600)

        # ---------- Table ----------
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(200)
        grid.addWidget(self.table, 5, 0, 1, 4)

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
            self.ser.close()
            self.ser = None
            self.lbl_conn.setText("Disconnected")
            self.lbl_conn.setStyleSheet("color: orange; font-size: 12px;")
            self.connect_btn.setText("Connect")
            return
        port = self.port_combo.currentText()
        try:
            self.ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
            self.lbl_conn.setText(f"Connected to {port}")
            self.lbl_conn.setStyleSheet("color: lightgreen; font-size: 12px;")
            self.connect_btn.setText("Disconnect")
        except:
            self.ser = None
            self.lbl_conn.setText("Connection Failed")
            self.lbl_conn.setStyleSheet("color: red; font-size: 12px;")

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

    def read_serial_row(self):
        if not self.ser or not self.ser.in_waiting:
            return None
        try:
            line = self.ser.readline().decode("utf-8").strip()
            if not line:
                return None
            parts = line.split(",")
            if len(parts) < len(self.columns):
                return None
            row = {}
            for i, col in enumerate(self.columns):
                try:
                    row[col] = float(parts[i]) if i not in (0,7,18,19) else parts[i]
                except:
                    row[col] = parts[i]
            return row
        except:
            return None

    def tick(self):
        t_since = int((now() - self.power_on_time).total_seconds())
        self.lbl_time.setText(f"Time since power: {t_since} s")
        self.lbl_pkt.setText(f"Packets: {self.packet_count}")

        if not self.recording:
            return

        row = self.read_serial_row()
        if row is None:
            return

        self.packet_count += 1
        row["PACKET_COUNT"] = self.packet_count
        self.buffer.append(row)

        # Save to CSV
        pd.DataFrame([row]).to_csv(CSV_PATH, mode='a', header=False, index=False)

        # ---- Sliding window (last 10s) ----
        times = [r.get("TIME_SINCE_S", 0) for r in self.buffer]
        t_now = times[-1] if times else 0
        t_min = max(0, t_now - WINDOW_SEC)

        # keep only last 10 sec for plotting
        window_data = [r for r in self.buffer if r.get("TIME_SINCE_S", 0) >= t_min]

        times = [r.get("TIME_SINCE_S", 0) for r in window_data]
        alt   = [r.get("ALTITUDE_M", 0) for r in window_data]
        pres  = [r.get("PRESSURE_PA", 0) for r in window_data]
        temp  = [r.get("TEMP_C", 0) for r in window_data]

        # Update plots
        self.cur_alt.setData(times, alt)
        self.cur_pressure.setData(times, pres)
        self.cur_temp.setData(times, temp)
        self.cur_p_alt.setData(pres, alt)
        self.cur_t_alt.setData(temp, alt)

        # Fix x-axis to [t_now-10, t_now]
        for pw in (self.plot_alt, self.plot_pressure, self.plot_temp):
            pw.setXRange(t_min, t_now)

        # Map update every 20 packets
        if self.packet_count % 20 == 0:
            try:
                lat = float(row["GNSS_LAT"]); lon = float(row["GNSS_LON"])
                self.update_map(lat, lon)
            except:
                pass 

        # Table
        latest = self.buffer[-10:]
        self.table.setRowCount(len(latest))
        for i, r in enumerate(latest):
            for j, col in enumerate(self.columns):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(r[col])))
        #input tab
        

# ---------------- Entrypoint ----------------
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = Groundstation()
    win.show()
    sys.exit(app.exec_())
