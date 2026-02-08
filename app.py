#!/usr/bin/env python3
"""
gui.py

Groundstation GUI (UDP mode)

- UI/design matches provided layout.
- Does NOT open the serial port.
- Listens for telemetry JSON on UDP 127.0.0.1:5005 (reader -> GUI).
- Sends command JSON to UDP 127.0.0.1:5010 (GUI -> reader).
- When recording is enabled, GUI appends rows to CSV_PATH (note: reader.py may already log to CSV).
"""
import sys, datetime, io, os, json, socket
import pandas as pd
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView
import pyqtgraph as pg
import folium

# Config
CSV_PATH = "Flight_2024ASI-CANSAT0032.csv"
TEAM_ID = "2024ASI-CANSAT0032"
WINDOW_SEC = 10   # sliding window seconds
TELEMETRY_UDP_HOST = "127.0.0.1"
TELEMETRY_UDP_PORT = 5005
COMMAND_UDP_HOST = "127.0.0.1"
COMMAND_UDP_PORT = 5010

def now():
    return datetime.datetime.now()

# UDP listener thread emits parsed JSON dicts
class UDPListener(QThread):
    row_received = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, host='127.0.0.1', port=5005, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = int(port)
        self._sock = None
        self._running = False

    def run(self):
        self._running = True
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # bind to localhost port
            try:
                self._sock.bind((self.host, self.port))
            except Exception as e:
                self.error.emit(f"Bind failed: {e}")
                return
            self._sock.settimeout(0.5)
            while self._running:
                try:
                    data, addr = self._sock.recvfrom(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    continue
                try:
                    payload = data.decode('utf-8', errors='ignore').strip()
                    obj = json.loads(payload)
                except Exception:
                    # fallback: try CSV parsing into dict with TEAM_ID only
                    try:
                        text = data.decode('utf-8', errors='ignore').strip()
                        obj = {"RAW": text}
                    except:
                        obj = {"RAW": None}
                # emit dict
                self.row_received.emit(obj)
        finally:
            try:
                if self._sock:
                    self._sock.close()
            except:
                pass

    def stop(self):
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except:
            pass
        # wait until thread exits
        self.wait(500)

class Groundstation(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Groundstation Dashboard — PyQtGraph + Folium (Dark)")
        self.resize(1500, 900)

        # state
        self.buffer = []
        self.columns = [
            "TEAM_ID","TIME_SINCE_S","PACKET_COUNT","ALTITUDE_M","PRESSURE_PA","TEMP_C",
            "VOLTAGE_V","GNSS_TIME","GNSS_LAT","GNSS_LON","GNSS_ALT_M","GNSS_SATS",
            "ACCEL_X_MPS2","ACCEL_Y_MPS2","ACCEL_Z_MPS2","ROLL_DEG","PITCH_DEG",
            "GYRO_SPIN_RATE_DPS","FLIGHT_STATE","OPTIONAL_DATA",
        ]
        self.recording = False
        self.packet_count = 0
        self.power_on_time = now()
        self.flight_state = "boot"

        # UDP listener ref
        self.udp_listener = None

        # build UI (layout matches original)
        self._build_ui()

        # start timer for plotting & UI updates
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

        # ensure CSV exists (GUI will append if recording)
        if not os.path.exists(CSV_PATH):
            pd.DataFrame(columns=self.columns).to_csv(CSV_PATH, index=False)

    def _build_ui(self):
        # style
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

        grid = QtWidgets.QGridLayout()
        root = QtWidgets.QWidget(); root.setLayout(grid)
        self.setCentralWidget(root)

        # --- Top controls: (kept port combo visually but used for appearance only) ---
        self.port_combo = QtWidgets.QComboBox()
        self.refresh_ports()
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.lbl_conn = QtWidgets.QLabel("Not connected")
        self.lbl_conn.setStyleSheet("color: orange;")
        top_h = QtWidgets.QHBoxLayout()
        top_h.addWidget(QtWidgets.QLabel("Port:"))         # purely cosmetic in UDP mode
        top_h.addWidget(self.port_combo)
        top_h.addWidget(self.connect_btn)
        top_h.addWidget(self.lbl_conn)
        top_wrap = QtWidgets.QWidget(); top_wrap.setLayout(top_h)
        grid.addWidget(top_wrap, 0, 0, 1, 4)

        # Title centered
        title = QtWidgets.QLabel(f"Team: {TEAM_ID} — Groundstation Console")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        grid.addWidget(title, 1, 0, 1, 4)

        # --- Command buttons area ---
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("SEND START")
        self.btn_stop  = QtWidgets.QPushButton("SEND STOP")
        self.btn_reset = QtWidgets.QPushButton("SEND RESET")
        for b in (self.btn_start, self.btn_stop, self.btn_reset):
            b.setEnabled(False)
            btn_layout.addWidget(b)

        self.btn_start.clicked.connect(lambda: self.send_command("START"))
        self.btn_stop.clicked.connect(lambda: self.send_command("STOP"))
        self.btn_reset.clicked.connect(lambda: self.send_command("RESET"))

        # line ending selector kept for similarity (but commands are sent as JSON)
        self.line_ending = QtWidgets.QComboBox()
        self.line_ending.addItems(["No line ending","\\n (LF)","\\r (CR)","\\r\\n (CRLF)"])
        self.line_ending.setCurrentIndex(1)

        self.last_sent_lbl = QtWidgets.QLabel("Last sent: —")
        cmd_wrap = QtWidgets.QWidget(); cmd_h = QtWidgets.QHBoxLayout()
        cmd_h.addLayout(btn_layout)
        cmd_h.addWidget(QtWidgets.QLabel("Line ending:")); cmd_h.addWidget(self.line_ending)
        cmd_h.addWidget(self.last_sent_lbl)
        cmd_wrap.setLayout(cmd_h)
        grid.addWidget(cmd_wrap, 2, 0, 1, 4)

        # Recording controls, time, packets
        self.record_start_btn = QtWidgets.QPushButton("Start Recording")
        self.record_stop_btn  = QtWidgets.QPushButton("Stop Recording")
        self.record_start_btn.clicked.connect(self.start_recording)
        self.record_stop_btn.clicked.connect(self.stop_recording)
        self.lbl_time = QtWidgets.QLabel("Time: 0s")
        self.lbl_pkt  = QtWidgets.QLabel("Packets: 0")
        stats_h = QtWidgets.QHBoxLayout()
        stats_h.addWidget(self.record_start_btn); stats_h.addWidget(self.record_stop_btn)
        stats_h.addStretch(); stats_h.addWidget(self.lbl_time); stats_h.addWidget(self.lbl_pkt)
        stats_w = QtWidgets.QWidget(); stats_w.setLayout(stats_h)
        grid.addWidget(stats_w, 3, 0, 1, 4)

        # Plots
        pg.setConfigOption('background', 'k'); pg.setConfigOption('foreground', 'w')
        self.plot_pressure = pg.PlotWidget(title="Pressure vs Time (Pa)")
        self.plot_temp     = pg.PlotWidget(title="Temp vs Time (°C)")
        self.plot_alt      = pg.PlotWidget(title="Altitude vs Time (m)")
        for pw in (self.plot_pressure, self.plot_temp, self.plot_alt):
            pw.setMinimumHeight(180); pw.getPlotItem().showGrid(x=True, y=True, alpha=0.2)
        self.cur_pressure = self.plot_pressure.plot()
        self.cur_temp     = self.plot_temp.plot()
        self.cur_alt      = self.plot_alt.plot()
        grid.addWidget(self.plot_pressure, 4, 0)
        grid.addWidget(self.plot_temp,     4, 1)
        grid.addWidget(self.plot_alt,      4, 2)

        self.plot_p_alt = pg.PlotWidget(title="Pressure vs Altitude")
        self.plot_t_alt = pg.PlotWidget(title="Temp vs Altitude")
        self.cur_p_alt = self.plot_p_alt.plot(symbol='o', symbolSize=3)
        self.cur_t_alt = self.plot_t_alt.plot(symbol='o', symbolSize=3)
        grid.addWidget(self.plot_p_alt, 5, 0)
        grid.addWidget(self.plot_t_alt, 5, 1)

        # Map
        self.map_view = QWebEngineView()
        self.map_view.setMinimumHeight(240)
        grid.addWidget(self.map_view, 4, 3, 2, 1)

        # Table
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(200)
        grid.addWidget(self.table, 6, 0, 1, 4)

        # Send text controls (separate from quick buttons)
        self.cmd_edit = QtWidgets.QLineEdit()
        self.cmd_edit.setPlaceholderText("Enter command to send (e.g. START)")
        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.clicked.connect(self._send_from_input)
        self.send_btn.setEnabled(False)
        send_small_h = QtWidgets.QHBoxLayout()
        send_small_h.addWidget(QtWidgets.QLabel("Command:")); send_small_h.addWidget(self.cmd_edit); send_small_h.addWidget(self.send_btn)
        send_small_wrap = QtWidgets.QWidget(); send_small_wrap.setLayout(send_small_h)
        grid.addWidget(send_small_wrap, 7, 0, 1, 4)

    # ------------------ Helpers ------------------
    def refresh_ports(self):
        self.port_combo.clear()
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                self.port_combo.addItem(p.device)
        except Exception:
            # if listing fails just show common placeholders
            for x in ("COM1","COM3","/dev/ttyUSB0"):
                if self.port_combo.findText(x) < 0:
                    self.port_combo.addItem(x)

    def toggle_connection(self):
        """
        In UDP mode: toggle the UDP listener to "connect" to reader's telemetry feed.
        This preserves the UI flow (Connect button) while avoiding opening the serial port.
        """
        if self.udp_listener and self.udp_listener.isRunning():
            try:
                self.udp_listener.stop()
            except Exception:
                pass
            self.udp_listener = None
            self.lbl_conn.setText("Disconnected")
            self.lbl_conn.setStyleSheet("color: orange;")
            self.connect_btn.setText("Connect")
            # disable send controls
            self.send_btn.setEnabled(False)
            for b in (self.btn_start, self.btn_stop, self.btn_reset):
                b.setEnabled(False)
            return

        # Start UDP listener
        try:
            self.udp_listener = UDPListener(host=TELEMETRY_UDP_HOST, port=TELEMETRY_UDP_PORT)
            self.udp_listener.row_received.connect(self._on_udp_row)
            self.udp_listener.error.connect(lambda m: self._show_error(m))
            self.udp_listener.start()
            self.lbl_conn.setText(f"Connected (UDP {TELEMETRY_UDP_PORT})")
            self.lbl_conn.setStyleSheet("color: lightgreen;")
            self.connect_btn.setText("Disconnect")
            self.send_btn.setEnabled(True)
            for b in (self.btn_start, self.btn_stop, self.btn_reset):
                b.setEnabled(True)
        except Exception as e:
            self.lbl_conn.setText(f"Connect failed: {e}")
            self.lbl_conn.setStyleSheet("color: red;")

    def _show_error(self, msg):
        self.lbl_conn.setText(f"Error: {msg}")
        self.lbl_conn.setStyleSheet("color: red;")

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
        except Exception as e:
            print("update_map error:", e)

    # ---------------- UDP telemetry handler ----------------
    def _on_udp_row(self, obj):
        """
        Normalize incoming JSON object into the expected row dict and append to buffer.
        The reader.py should send JSON matching the GUI columns. This function is tolerant.
        """
        try:
            # Build a normalized row dict
            row = {c: "" for c in self.columns}
            # If obj already contains keys, copy them
            for k, v in obj.items():
                # check for case-insensitive matches
                up = k.upper()
                if up in row:
                    row[up] = v
                else:
                    # allow direct key if matches exactly
                    if k in row:
                        row[k] = v
            # fallback for RAW payloads: put entire raw string in OPTIONAL_DATA
            if "RAW" in obj and not any(obj.get(c) for c in ("TEAM_ID","GNSS_LAT")):
                row["OPTIONAL_DATA"] = obj.get("RAW")

            # TIME_SINCE_S: if missing, derive from GUI power_on_time
            try:
                if not row.get("TIME_SINCE_S"):
                    row["TIME_SINCE_S"] = int((now() - self.power_on_time).total_seconds())
            except Exception:
                row["TIME_SINCE_S"] = 0

            # PACKET_COUNT bookkeeping
            try:
                incoming_count = int(float(row.get("PACKET_COUNT") or 0))
            except Exception:
                incoming_count = 0
            if incoming_count and incoming_count > self.packet_count:
                self.packet_count = incoming_count
            else:
                self.packet_count += 1
                row["PACKET_COUNT"] = self.packet_count

            # append to buffer
            self.buffer.append(row)

            # if recording, also append to CSV (reader may already log; this duplicates if both enabled)
            if self.recording:
                try:
                    pd.DataFrame([row])[self.columns].to_csv(CSV_PATH, mode='a', header=False, index=False)
                except Exception:
                    try:
                        pd.DataFrame([row]).to_csv(CSV_PATH, mode='a', header=False, index=False)
                    except Exception:
                        pass

        except Exception as e:
            print("Error processing UDP row:", e)

    # ---------------- send commands (via UDP to reader) ----------------
    def _format_with_line_ending(self, base_text):
        mode = self.line_ending.currentText()
        if mode == "\\n (LF)": return base_text + "\n"
        if mode == "\\r (CR)": return base_text + "\r"
        if mode == "\\r\\n (CRLF)": return base_text + "\r\n"
        return base_text

    def _send_from_input(self):
        cmd = self.cmd_edit.text().strip()
        if cmd:
            self.send_command(cmd)

    def send_command(self, cmd_text):
        """
        Send a command to the reader via UDP.
        The reader listens on COMMAND_UDP_PORT and will forward to serial.
        """
        try:
            to_send = self._format_with_line_ending(cmd_text)
            payload = json.dumps({"cmd": to_send})
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.0)
            sock.sendto(payload.encode('utf-8'), (COMMAND_UDP_HOST, COMMAND_UDP_PORT))
            sock.close()
            # update label
            self.last_sent_lbl.setText(f"Last sent: {cmd_text}")
            self.last_sent_lbl.setStyleSheet("color: lightgreen; font-size: 13px;")
        except Exception as e:
            self.last_sent_lbl.setText("Last sent: FAILED")
            self.last_sent_lbl.setStyleSheet("color: red; font-size: 13px;")
            self.lbl_conn.setText(f"Send failed: {e}")
            self.lbl_conn.setStyleSheet("color: red; font-size: 12px;")

    # ---------------- tick for plots & time ----------------
    def tick(self):
        t_since = int((now() - self.power_on_time).total_seconds())
        try:
            self.lbl_time.setText(f"Time: {t_since}s")
            self.lbl_pkt.setText(f"Packets: {self.packet_count}")
        except Exception:
            pass

        # update plots using sliding window
        if not self.buffer:
            return
        times = [float(r.get("TIME_SINCE_S", 0) or 0) for r in self.buffer]
        t_now = times[-1]
        t_min = max(0, t_now - WINDOW_SEC)
        window_data = [r for r in self.buffer if float(r.get("TIME_SINCE_S", 0) or 0) >= t_min]
        times_w = [float(r.get("TIME_SINCE_S", 0) or 0) for r in window_data]
        alt = [float(r.get("ALTITUDE_M", 0) or 0) for r in window_data]
        pres = [float(r.get("PRESSURE_PA", 0) or 0) for r in window_data]
        temp = [float(r.get("TEMP_C", 0) or 0) for r in window_data]
        try:
            self.cur_alt.setData(times_w, alt)
            self.cur_pressure.setData(times_w, pres)
            self.cur_temp.setData(times_w, temp)
            self.cur_p_alt.setData(pres, alt)
            self.cur_t_alt.setData(temp, alt)
        except Exception:
            pass
        for pw in (self.plot_alt, self.plot_pressure, self.plot_temp):
            try: pw.setXRange(t_min, t_now)
            except: pass

        # Map update every 20 packets
        if self.packet_count % 20 == 0 and self.buffer:
            try:
                lat = float(self.buffer[-1].get("GNSS_LAT", 0) or 0)
                lon = float(self.buffer[-1].get("GNSS_LON", 0) or 0)
                self.update_map(lat, lon)
            except Exception:
                pass

        # Table (last 10)
        latest = self.buffer[-10:]
        self.table.setRowCount(len(latest))
        for i, r in enumerate(latest):
            for j, col in enumerate(self.columns):
                val = r.get(col, "")
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(str(val)))

    # ---------------- shutdown ----------------
    def closeEvent(self, event):
        try:
            if self.udp_listener:
                self.udp_listener.stop()
        except Exception:
            pass
        try:
            # clear web resources
            if hasattr(self, 'map_view') and self.map_view:
                try: self.map_view.page().profile().clearHttpCache()
                except: pass
                try: self.map_view.deleteLater()
                except: pass
        except Exception:
            pass
        event.accept()

# Entrypoint
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = Groundstation()
    win.show()
    sys.exit(app.exec_())
