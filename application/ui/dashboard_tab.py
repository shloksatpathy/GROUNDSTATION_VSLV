from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLabel
from ui.plots import PlotManager
from core.serial_manager import SerialManager

class DashboardTab(QWidget):

    def __init__(self):

        super().__init__()

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

        # ---- Plots ----
        self.plots = PlotManager()

        plots_layout = QHBoxLayout()

        widgets = self.plots.widgets()

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