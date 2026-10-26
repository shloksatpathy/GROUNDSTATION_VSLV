import os
import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QShortcut, QFileDialog
from PyQt5.QtGui import QIcon, QPalette, QColor, QKeySequence, QSurfaceFormat

from ui.dashboard_tab import DashboardTab
from ui.map_tab import MapTab
from ui.packet_editor_tab import PacketEditorTab
from core.serial_manager import SerialManager
from core.packet_parser import PacketParser
from core.replay_source import ReplaySource
from core.config import DATA_ROOT


class GroundStation(QMainWindow):

    def __init__(self, replay_path=None):
        super().__init__()

        self.setWindowTitle("VSSSIC Ground Station V3")
        self.resize(1500, 950)

        # Load icon from project root
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "images",
            "vsssic-logo-1.ico"
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Shared Core Instances
        self.parser = PacketParser()
        if replay_path:
            self.serial = ReplaySource(replay_path, self.parser)
        else:
            self.serial = SerialManager()

        # Tabs
        self.tabs = QTabWidget()

        # Map tab is passed to Dashboard to allow it to push GNSS updates
        self.map_tab = MapTab()
        self.dashboard = DashboardTab(self.serial, self.map_tab, self.parser)
        self.packet_editor = PacketEditorTab(self.parser)

        self.tabs.addTab(self.dashboard, "Telemetry Dashboard")
        self.tabs.addTab(self.map_tab, "Map & Tracking")
        self.tabs.addTab(self.packet_editor, "Packet Format")

        self.setCentralWidget(self.tabs)

        # Replay: Ctrl+Alt+H opens a replica of this window fed from a CSV
        self.replay_window = None
        if not replay_path:
            QShortcut(QKeySequence("Ctrl+Alt+H"), self, activated=self.open_replay)

    def open_replay(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Replay telemetry CSV", DATA_ROOT, "CSV files (*.csv)")
        if not path:
            return
        if self.replay_window:
            self.replay_window.close()
        self.replay_window = GroundStation(replay_path=path)
        self.replay_window.show()

    def closeEvent(self, event):
        """Clean shutdown of threads and file handles before exit."""
        print("[SHUTDOWN] Closing connections and file handles...")
        try:
            self.dashboard.shutdown()
        except Exception as e:
            print(f"[SHUTDOWN] Error stopping recording: {e}")


        try:
            self.serial.disconnect()
        except Exception as e:
            print(f"[SHUTDOWN] Error disconnecting serial: {e}")
            
        event.accept()
        print("[SHUTDOWN] Complete.")


def apply_dark_theme(app):
    """Apply the Fusion style + dark palette. Must run for any entry point —
    the widget stylesheets assume a dark background."""
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


def main():
    """Console/GUI entry point. Kept in sync with run.py."""
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    # No vsync: with the 3D view on screen every repaint is GL-composited, and
    # waiting on vblank each time throttles the whole event loop (~6 FPS).
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    window = GroundStation()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()