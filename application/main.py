import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget
from PyQt5.QtGui import QIcon, QPalette, QColor

from ui.dashboard_tab import DashboardTab
from ui.map_tab import MapTab
from ui.packet_editor_tab import PacketEditorTab
from core.serial_manager import SerialManager
from core.packet_parser import PacketParser


class GroundStation(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("VSSSIC Ground Station V3")
        self.resize(1500, 950)
        self.setWindowIcon(QIcon("images/vsssic-logo-1.ico"))

        # Shared Core Instances
        self.serial = SerialManager()
        self.parser = PacketParser()

        # Tabs
        self.tabs = QTabWidget()

        # Map tab is passed to Dashboard to allow it to push GNSS updates
        self.map_tab = MapTab()
        self.dashboard = DashboardTab(self.serial, self.map_tab)
        self.packet_editor = PacketEditorTab(self.parser)

        self.tabs.addTab(self.dashboard, "Telemetry Dashboard")
        self.tabs.addTab(self.map_tab, "Map & Tracking")
        self.tabs.addTab(self.packet_editor, "Packet Format")

        self.setCentralWidget(self.tabs)

    def closeEvent(self, event):
        """Clean shutdown of threads and file handles before exit."""
        print("[SHUTDOWN] Closing connections and file handles...")
        try:
            self.dashboard.stop_recording()
        except Exception as e:
            print(f"[SHUTDOWN] Error stopping recording: {e}")
            
        try:
            self.serial.disconnect()
        except Exception as e:
            print(f"[SHUTDOWN] Error disconnecting serial: {e}")
            
        event.accept()
        print("[SHUTDOWN] Complete.")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Use a consistent cross-platform dark-friendly style
    app.setStyle("Fusion")
    
    # Custom dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(18, 18, 18))
    palette.setColor(QPalette.WindowText, QColor(224, 224, 224))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(44, 44, 44))
    palette.setColor(QPalette.ToolTipBase, QColor(224, 224, 224))
    palette.setColor(QPalette.ToolTipText, QColor(224, 224, 224))
    palette.setColor(QPalette.Text, QColor(224, 224, 224))
    palette.setColor(QPalette.Button, QColor(30, 30, 30))
    palette.setColor(QPalette.ButtonText, QColor(224, 224, 224))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)
    
    app.setStyleSheet("""
        QToolTip { color: #E0E0E0; background-color: #2C2C2C; border: 1px solid white; }
        QPushButton { background-color: #1E1E1E; border: 1px solid #333; border-radius: 6px; padding: 6px; color: #E0E0E0; }
        QPushButton:hover { background-color: #333; }
        QTableWidget { background-color: #1E1E1E; gridline-color: #444; color: #E0E0E0; }
        QHeaderView::section { background-color: #2C2C2C; color: #E0E0E0; padding: 4px; border: none; }
    """)

    window = GroundStation()
    window.show()

    sys.exit(app.exec_())