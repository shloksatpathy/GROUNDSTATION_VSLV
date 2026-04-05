from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLabel
from PyQt5.QtCore import QTimer

from ui.plots import PlotManager
from core.serial_manager import SerialManager
from core.packet_parser import PacketParser
from core.data_buffer import TelemetryBuffer


class DashboardTab(QWidget):

    def __init__(self):

        super().__init__()

        # ----- Core Systems -----
        self.serial = SerialManager()
        self.parser = PacketParser()
        self.buffer = TelemetryBuffer()

        layout = QVBoxLayout()

        # ---- Serial Control Panel ----
        control_layout = QHBoxLayout()

        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()

        self.baud_combo.addItems(["9600", "57600", "115200"])

        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")

        control_layout.addWidget(QLabel("COM Port"))
        control_layout.addWidget(self.port_combo)

        control_layout.addWidget(QLabel("Baud"))
        control_layout.addWidget(self.baud_combo)

        control_layout.addWidget(self.connect_btn)
        control_layout.addWidget(self.disconnect_btn)

        layout.addLayout(control_layout)

        # ---- Populate COM Ports ----
        self.refresh_ports()

        # ---- Button Connections ----
        self.connect_btn.clicked.connect(self.connect_serial)
        self.disconnect_btn.clicked.connect(self.disconnect_serial)

        # ---- Plots ----
        self.plots = PlotManager()

        widgets = self.plots.widgets()

        plots_layout = QHBoxLayout()
        plots_layout.addWidget(widgets["alt"])
        plots_layout.addWidget(widgets["pres"])
        plots_layout.addWidget(widgets["temp"])

        layout.addLayout(plots_layout)

        plots_layout2 = QHBoxLayout()
        plots_layout2.addWidget(widgets["roll"])
        plots_layout2.addWidget(widgets["pitch"])
        plots_layout2.addWidget(widgets["yaw"])

        layout.addLayout(plots_layout2)

        layout.addWidget(widgets["vspeed"])

        self.setLayout(layout)

        # ---- Timer for real-time update ----
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(50)  # ~20 FPS

    # -----------------------------------
    # Serial Controls
    # -----------------------------------
    def refresh_ports(self):

        self.port_combo.clear()

        ports = self.serial.get_available_ports()

        for p in ports:
            self.port_combo.addItem(p)

    def connect_serial(self):

        port = self.port_combo.currentText()
        baud = int(self.baud_combo.currentText())

        try:
            self.serial.ser = self.serial.connect_serial(port, baud)
            print("Connected:", port)
        except Exception as e:
            print("Connection error:", e)

    def disconnect_serial(self):

        self.serial.disconnect()
        print("Disconnected")

    # -----------------------------------
    # Main Update Loop
    # -----------------------------------
    def update_loop(self):

        try:
            line = self.serial.read_line()

            if line:
                print("RX:", line)

                packet = self.parser.parse(line)

                if packet:
                    self.buffer.add_packet(packet)

            # Update plots continuously
            self.plots.update(self.buffer.get_data())

        except Exception as e:
            print("Update error:", e)