from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QComboBox, QLabel, QLineEdit, QTableWidget, 
                               QTableWidgetItem)
from PyQt5.QtCore import QTimer

from ui.plots import PlotManager
from ui.map_tab import MapTab
from core.serial_manager import SerialManager
from core.packet_parser import PacketParser
from core.data_buffer import TelemetryBuffer
from core.data_recorder import DataRecorder
from core.telemetry_processor import TelemetryProcessor

class DashboardTab(QWidget):

    def __init__(self, serial_manager: SerialManager, map_tab: MapTab,
                 parser: PacketParser = None):
        super().__init__()

        # ----- Core Systems -----
        self.serial = serial_manager
        # Shared with PacketEditorTab so schema edits apply to the live pipeline
        self.parser = parser if parser is not None else PacketParser()
        self.buffer = TelemetryBuffer()
        self.recorder = DataRecorder()
        self.processor = TelemetryProcessor()
        self.map_tab = map_tab
        
        # Connect threaded serial signal
        self.serial.line_received.connect(self.on_serial_line)
        self.packet_count = 0
        # Full enriched packet — the buffer only keeps the plotted subset of keys
        self.latest_packet = None

        layout = QVBoxLayout()

        # ---- Top Controls: Serial + Recording + Command ----
        top_layout = QHBoxLayout()

        # Serial Connection
        self.port_combo = QComboBox()
        self.refresh_ports()
        
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "38400", "57600", "115200"])
        
        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")
        
        self.lbl_conn = QLabel("Disconnected")
        self.lbl_conn.setStyleSheet("color: orange; font-size: 12px; font-weight: bold;")

        top_layout.addWidget(QLabel("COM Port:"))
        top_layout.addWidget(self.port_combo)
        top_layout.addWidget(QLabel("Baud:"))
        top_layout.addWidget(self.baud_combo)
        top_layout.addWidget(self.connect_btn)
        top_layout.addWidget(self.disconnect_btn)
        top_layout.addWidget(self.lbl_conn)
        
        top_layout.addStretch()

        # Recording
        self.start_btn = QPushButton("Start Recording")
        self.start_btn.setStyleSheet("background-color: #2E7D32;")
        self.stop_btn = QPushButton("Stop Recording")
        self.stop_btn.setStyleSheet("background-color: #C62828;")
        top_layout.addWidget(self.start_btn)
        top_layout.addWidget(self.stop_btn)

        layout.addLayout(top_layout)

        # Command TX
        cmd_layout = QHBoxLayout()
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText("Enter command to send (e.g. START)...")
        self.send_btn = QPushButton("Send")
        self.last_sent_lbl = QLabel("Last sent: —")
        self.last_sent_lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        
        cmd_layout.addWidget(QLabel("Command:"))
        cmd_layout.addWidget(self.cmd_edit)
        cmd_layout.addWidget(self.send_btn)
        cmd_layout.addWidget(self.last_sent_lbl)
        cmd_layout.addStretch()
        
        layout.addLayout(cmd_layout)

        # ---- Connections ----
        self.connect_btn.clicked.connect(self.connect_serial)
        self.disconnect_btn.clicked.connect(self.disconnect_serial)
        self.start_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)
        self.send_btn.clicked.connect(self.send_command)
        self.cmd_edit.returnPressed.connect(self.send_command)

        # ---- Middle: Plots + Info Panel ----
        middle_layout = QHBoxLayout()
        
        # Plots Grid
        plots_vbox = QVBoxLayout()
        self.plots = PlotManager()
        widgets = self.plots.widgets()
        
        plots_row1 = QHBoxLayout()
        plots_row1.addWidget(widgets["alt"])
        plots_row1.addWidget(widgets["pres"])
        plots_row1.addWidget(widgets["temp"])
        plots_vbox.addLayout(plots_row1)
        
        plots_row2 = QHBoxLayout()
        plots_row2.addWidget(widgets["roll"])
        plots_row2.addWidget(widgets["pitch"])
        plots_row2.addWidget(widgets["yaw"])
        plots_vbox.addLayout(plots_row2)
        
        plots_vbox.addWidget(widgets["vspeed"])
        
        middle_layout.addLayout(plots_vbox, stretch=4)
        
        # Info Panel
        info_layout = QVBoxLayout()
        info_widget = QWidget()
        info_widget.setLayout(info_layout)
        info_widget.setStyleSheet("background:#1A1A1A; border:1px solid #333; border-radius:6px; padding:10px;")
        
        self.info_lbl_time = QLabel("Time since power: — s")
        self.info_lbl_state = QLabel("State: idle")
        self.info_lbl_power = QLabel("Power: — %")
        self.info_lbl_pkt = QLabel("Packets: 0")
        
        for lbl in (self.info_lbl_time, self.info_lbl_state, self.info_lbl_power, self.info_lbl_pkt):
            lbl.setStyleSheet("color:#E0E0E0; font-size:15px; font-weight: bold; margin-bottom: 8px;")
            info_layout.addWidget(lbl)
            
        info_layout.addStretch()
        middle_layout.addWidget(info_widget, stretch=1)
        
        layout.addLayout(middle_layout)

        # ---- Bottom: Data Table ----
        self.table = QTableWidget()
        self.table_columns = []
        self.table.setMinimumHeight(160)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.setLayout(layout)

        # ---- Timer for Plot Updates ----
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(50)  # ~20 FPS

    # -----------------------------------
    # Controls
    # -----------------------------------
    def refresh_ports(self):
        self.port_combo.clear()
        for p in self.serial.available_ports():
            self.port_combo.addItem(p)

    def connect_serial(self):
        port = self.port_combo.currentText()
        try:
            baud = int(self.baud_combo.currentText())
        except Exception:
            baud = 9600
            
        try:
            self.serial.connect(port, baud)
            self.lbl_conn.setText(f"Connected to {port}")
            self.lbl_conn.setStyleSheet("color: lightgreen; font-size: 12px; font-weight: bold;")
        except Exception as e:
            self.lbl_conn.setText(f"Connection error")
            self.lbl_conn.setStyleSheet("color: red; font-size: 12px; font-weight: bold;")
            print("Connection error:", e)

    def disconnect_serial(self):
        self.serial.disconnect()
        self.lbl_conn.setText("Disconnected")
        self.lbl_conn.setStyleSheet("color: orange; font-size: 12px; font-weight: bold;")

    def start_recording(self):
        self.processor.reset()
        self.buffer.clear()
        self.packet_count = 0
        self.table.setRowCount(0)
        try:
            self.recorder.start()
        except Exception as e:
            print(f"[RECORDER] Could not start recording: {e}")

    def stop_recording(self):
        self.recorder.stop()

    def shutdown(self):
        """Flush and release the CSV handle on application exit."""
        self.recorder.close()


    def send_command(self):
        cmd = self.cmd_edit.text() or ""
        if not cmd:
            return
            
        to_send = (cmd + "\n").encode("utf-8")
        try:
            self.serial.write(to_send)
            self.last_sent_lbl.setText(f"Last sent: {cmd}")
            self.last_sent_lbl.setStyleSheet("color: lightgreen; font-size: 13px;")
            self.cmd_edit.clear()
        except Exception:
            self.last_sent_lbl.setText("Last sent: FAILED")
            self.last_sent_lbl.setStyleSheet("color: red; font-size: 13px;")

    # -----------------------------------
    # Data Pipeline (Triggered by Thread Signal)
    # -----------------------------------
    def on_serial_line(self, line):
        try:
            packet = self.parser.parse(line)
            if packet:
                # Enqueue data processing and update logic
                # (1) Apply Kalman Filter, battery %, state parsing
                enriched = self.processor.process(packet)
                self.latest_packet = enriched

                # (2) Store in buffer for plotting
                self.buffer.add_packet(enriched)
                
                # (3) Save to CSV if recording
                self.recorder.record(enriched)
                self.packet_count += 1
                
                # (4) Update Map Tab (every 20 packets to prevent stuttering)
                if self.packet_count % 20 == 0:
                    lat_key = next((k for k in ["GNSS_LAT", "lat", "LAT", "latitude"] if k in enriched), None)
                    lon_key = next((k for k in ["GNSS_LON", "lon", "LON", "longitude"] if k in enriched), None)
                    
                    if lat_key and lon_key:
                        lat, lon = enriched.get(lat_key), enriched.get(lon_key)
                        if lat is not None and lon is not None:
                            self.map_tab.update_position(float(lat), float(lon))
                
                # (5) Update data table dynamically
                new_cols = [k for k in enriched.keys() if k not in self.table_columns]
                if new_cols:
                    self.table_columns += new_cols
                    self.table.setColumnCount(len(self.table_columns))
                    self.table.setHorizontalHeaderLabels(self.table_columns)
                    
                self.table.insertRow(0)
                for j, col in enumerate(self.table_columns):
                    val = enriched.get(col)
                    val_str = "" if val is None else str(val)
                    self.table.setItem(0, j, QTableWidgetItem(val_str))
                    
                if self.table.rowCount() > 10:
                    self.table.removeRow(self.table.rowCount() - 1)
                    
        except Exception as e:
            print("Processing error on serial line:", e)

    # -----------------------------------
    # GUI Plot/Label Updates
    # -----------------------------------
    def update_gui(self):
        try:
            # 1. Update Plot Widgets
            self.plots.update(self.buffer.get_data())
            
            # 2. Update Info Panel Labels
            latest = self.latest_packet
            if latest:
                t = next(
                    (latest[k] for k in ["TIME_SINCE_S", "time", "TIME"]
                     if latest.get(k) is not None),
                    None
                )
                if isinstance(t, (int, float)):
                    self.info_lbl_time.setText(f"Time since power: {t:.2f} s")
                else:
                    self.info_lbl_time.setText(f"Time since power: {t if t else '—'} s")

                state = latest.get("flight_state_str") or "—"
                self.info_lbl_state.setText(f"State: {state}")

                pwr = latest.get("power_pct")
                if pwr is not None:
                    self.info_lbl_power.setText(f"Power: {pwr:.1f} %")

                self.info_lbl_pkt.setText(f"Packets: {self.packet_count}")


        except Exception as e:
            print("GUI update error:", e)