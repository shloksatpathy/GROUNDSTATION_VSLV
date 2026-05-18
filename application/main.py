import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget
from ui.dashboard_tab import DashboardTab
from ui.map_tab import MapTab
from ui.packet_editor_tab import PacketEditorTab
from core.serial_manager import SerialManager
from core.packet_parser import PacketParser


class GroundStation(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("VSSSIC Ground Station V3")
        self.resize(1400, 900)

        # Tabs
        self.tabs = QTabWidget()

        self.dashboard = DashboardTab()
        self.map_tab = MapTab()
        self.packet_editor = PacketEditorTab()

        self.tabs.addTab(self.dashboard, "Telemetry Dashboard")
        self.tabs.addTab(self.map_tab, "Map & Tracking")
        self.tabs.addTab(self.packet_editor, "Packet Format")

        self.setCentralWidget(self.tabs)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Dark theme
    app.setStyle("Fusion")
    
    # Custom dark palette can be added here if desired

    window = GroundStation()
    window.show()

    sys.exit(app.exec_())