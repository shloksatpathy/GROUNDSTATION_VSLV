"""
Read-only monitor: mirrors an admin ground station over the LAN.

Shows the same dashboard and map as the admin GCS (main.py), fed by the
admin's relay (core/relay.py) instead of a radio. There is no serial link,
command line, recorder, simulation runner or config editor here — those
stay with the admin station.
"""
import sys

from PyQt5.QtWidgets import QApplication, QMessageBox

from main import StationWindow, apply_dark_theme, set_application_attributes
from ui.dashboard_tab import DashboardTab
from ui.map_tab import MapTab
from ui.monitor_join_dialog import join_relay
from core.relay import RelayClient, sim_result_from_wire

_TITLE = "VSSSIC Ground Station V3 — Monitor"


class MonitorStation(StationWindow):

    def __init__(self, client):
        super().__init__(_TITLE)
        self.client = client

        self.map_tab = MapTab()
        # The ideal trajectory arrives from the admin; running a solve here
        # would only show a different one.
        self.map_tab.trajectory_view.run_btn.hide()
        self.dashboard = DashboardTab(None, self.map_tab)

        self.tabs.addTab(self._scrollable(self.dashboard), "Telemetry Dashboard")
        self.tabs.addTab(self._scrollable(self.map_tab), "Map & Tracking")

        client.packet_received.connect(self.dashboard.ingest)
        client.reference_received.connect(self.map_tab.set_reference)
        client.simulation_received.connect(self._show_simulation)
        client.reset_received.connect(self.dashboard.reset_views)
        client.link_changed.connect(self._show_link)
        client.joined.connect(self._show_joined)
        client.denied.connect(self._on_revoked)

        self._show_joined(client.station)
        # Delivered in the welcome, before this window existed.
        if client.reference is not None:
            self.map_tab.set_reference(*client.reference)
        if client.simulation is not None:
            self._show_simulation(client.simulation)

    def _show_joined(self, station):
        self.setWindowTitle(f"{_TITLE} — {station}")
        self._set_status(f"Joined {station} ({self.client.host}:{self.client.port})", "lightgreen")

    def _show_link(self, up):
        if up:
            self._set_status(f"Receiving from {self.client.station}", "lightgreen")
        else:
            self._set_status(f"No data from {self.client.station} — link lost", "orange")

    def _show_simulation(self, wire):
        try:
            self.map_tab.trajectory_view.set_ideal_result(sim_result_from_wire(wire))
        except (KeyError, TypeError, ValueError) as e:
            print(f"[MONITOR] Bad simulation from relay: {e}")

    def _on_revoked(self, reason):
        """The admin changed the monitor code under us."""
        self._set_status(f"Access revoked: {reason}", "red")
        QMessageBox.warning(self, "Monitor access revoked",
                            f"{reason}\n\nAsk the admin station for the new monitor code.")
        # Rejoined: the welcome replays ref/sim, so only live data was missed.
        join_relay(self.client, self)

    def _set_status(self, text, color):
        self.dashboard.lbl_conn.setText(text)
        self.dashboard.lbl_conn.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")

    def closeEvent(self, event):
        self.client.leave()
        event.accept()


def main():
    """Monitor entry point. Kept in sync with monitor.py."""
    set_application_attributes()
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    client = RelayClient()
    if not join_relay(client):
        sys.exit(0)

    window = MonitorStation(client)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
