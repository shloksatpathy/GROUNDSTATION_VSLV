import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTabWidget,
                             QScrollArea, QFrame)
from PyQt5.QtGui import QIcon, QPalette, QColor

from ui.dashboard_tab import DashboardTab
from ui.map_tab import MapTab
from ui.packet_editor_tab import PacketEditorTab
from ui.simulation_tab import SimulationTab
from core.serial_manager import SerialManager
from core.packet_parser import PacketParser


# Window size on a screen with room to spare. Anything smaller is driven by
# the work area instead — see GroundStation.__init__.
_PREFERRED_SIZE = (1500, 950)


def set_application_attributes():
    """Qt attributes that must be set before the QApplication is constructed.

    Both entry points call this — application/main.py's main() and run.py —
    so the two stay in step.

    High-DPI scaling is the reason this matters beyond the OpenGL sharing
    flag: without it, every hardcoded pixel size in the UI is interpreted as
    a physical device pixel, so on a 4K panel at 150-200% the whole interface
    renders at a third of its intended size, and on a scaled display Qt
    reports a work area the window sizing can't reason about.
    """
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


class GroundStation(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("VSSSIC Ground Station V3")

        # Size from the screen's work area rather than a fixed 1500x950. That
        # constant overflowed anything shorter than ~1000 px, and the part that
        # fell off the bottom was the last row of every tab — which is where
        # the Run Simulation and Save buttons used to sit, so they looked like
        # they simply did not exist.
        #
        # 92% leaves the window visibly framed by the desktop on a large
        # display without wasting space on a small one; the cap keeps it from
        # sprawling across an ultrawide. showEvent does the final fit, once the
        # window manager has told us how big the title bar and borders are.
        self._geometry_fitted = False
        avail = self._available_geometry()
        if avail is not None:
            self.resize(min(_PREFERRED_SIZE[0], int(avail.width() * 0.92)),
                        min(_PREFERRED_SIZE[1], int(avail.height() * 0.92)))
        else:
            self.resize(*_PREFERRED_SIZE)

        # Load icon from project root
        import os
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "images",
            "vsssic-logo-1.ico"
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Shared Core Instances
        self.serial = SerialManager()
        self.parser = PacketParser()

        # Tabs
        self.tabs = QTabWidget()

        # Map tab is passed to Dashboard to allow it to push GNSS updates
        self.map_tab = MapTab()
        self.dashboard = DashboardTab(self.serial, self.map_tab, self.parser)
        self.packet_editor = PacketEditorTab(self.parser)
        # Shares self.map_tab.trajectory_view's RocketSimThread rather than
        # owning a second one — see ui/simulation_tab.py.
        self.simulation_tab = SimulationTab(self.map_tab.trajectory_view)

        # Each page goes in a scroll area so that a screen too small for the
        # page's minimum size scrolls rather than silently clipping whatever
        # sits at the edges. With widgetResizable(True) this is invisible
        # whenever the window has room: the page is stretched to the viewport
        # exactly as it would be if it were the tab's direct child, and the
        # scrollbars only appear once the viewport drops below its minimum.
        self.tabs.addTab(self._scrollable(self.dashboard), "Telemetry Dashboard")
        self.tabs.addTab(self._scrollable(self.map_tab), "Map & Tracking")
        self.tabs.addTab(self._scrollable(self.simulation_tab), "Simulation Setup")
        self.tabs.addTab(self._scrollable(self.packet_editor), "Packet Format")

        self.setCentralWidget(self.tabs)

    @staticmethod
    def _scrollable(page):
        """Wrap a tab page in a frameless, resizing scroll area."""
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        # The tab widget already draws the pane border; a second one around
        # the scroll area would double it up.
        area.setFrameShape(QFrame.NoFrame)
        return area

    def _available_geometry(self):
        """Work area of the screen the window is on — desktop minus taskbar/dock."""
        screen = self.screen() if hasattr(self, "screen") else None
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def showEvent(self, event):
        """Shrink and nudge the window into the work area, frame included.

        __init__'s clamp sizes the *client* area, which ignores the title bar
        and borders — enough of an overhang to push the bottom row of a tab
        off a short screen. frameGeometry is only meaningful once the window
        manager has framed the window, so the final fit happens here, once.
        """
        super().showEvent(event)
        if self._geometry_fitted:
            return
        self._geometry_fitted = True

        avail = self._available_geometry()
        if avail is None:
            return

        frame = self.frameGeometry()
        chrome_h = max(0, frame.height() - self.height())
        chrome_w = max(0, frame.width() - self.width())

        target_w = min(self.width(), avail.width() - chrome_w)
        target_h = min(self.height(), avail.height() - chrome_h)
        if target_w < self.width() or target_h < self.height():
            self.resize(max(target_w, 1), max(target_h, 1))

        # A window sized to fit can still hang off the bottom if it was placed
        # low; move it back inside rather than leaving the fit purely nominal.
        frame = self.frameGeometry()
        if not avail.contains(frame):
            frame.moveLeft(max(avail.left(), min(frame.left(), avail.right() - frame.width() + 1)))
            frame.moveTop(max(avail.top(), min(frame.top(), avail.bottom() - frame.height() + 1)))
            self.move(frame.topLeft())

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
    set_application_attributes()
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    window = GroundStation()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()