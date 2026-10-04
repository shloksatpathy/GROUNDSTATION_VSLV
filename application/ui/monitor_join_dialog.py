"""
Monitor startup: pick an admin ground station and enter the monitor code.

Takes the place of ui/auth_dialog.py for the monitor. The code is checked by
the admin's relay, not here, so the admin can change it without anyone
redistributing the monitor build.
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QLabel, QLineEdit, QSpinBox, QPushButton,
                             QListWidget, QListWidgetItem)

from core.relay import BeaconListener, DEFAULT_RELAY_PORT

# How long to wait for the admin to answer a join before giving up.
_JOIN_TIMEOUT_MS = 4000


class MonitorJoinDialog(QDialog):

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("VSSSIC Ground Station V3 - Monitor")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Ground stations found on this network:"))
        self.station_list = QListWidget()
        self.station_list.setMaximumHeight(110)
        self.station_list.currentItemChanged.connect(self._pick_station)
        layout.addWidget(self.station_list)

        form = QFormLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("Admin station IP, e.g. 192.168.1.20")
        form.addRow("Host:", self.host_edit)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(DEFAULT_RELAY_PORT)
        form.addRow("Port:", self.port_spin)
        self.code_edit = QLineEdit()
        self.code_edit.setEchoMode(QLineEdit.Password)
        self.code_edit.setMaxLength(16)
        self.code_edit.returnPressed.connect(self._attempt)
        form.addRow("Monitor code:", self.code_edit)
        layout.addLayout(form)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        buttons = QHBoxLayout()
        exit_btn = QPushButton("Exit")
        exit_btn.clicked.connect(self.reject)
        self.join_btn = QPushButton("Join")
        self.join_btn.setDefault(True)
        self.join_btn.clicked.connect(self._attempt)
        buttons.addWidget(exit_btn)
        buttons.addWidget(self.join_btn)
        layout.addLayout(buttons)

        self._stations = set()
        self.beacons = BeaconListener(self)
        self.beacons.station_found.connect(self._add_station)

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)

        self.client.joined.connect(self._on_joined)
        self.client.denied.connect(self._on_denied)

        if client.host:
            # Re-opened after the admin revoked access: keep the old target.
            self.host_edit.setText(client.host)
            self.port_spin.setValue(client.port)
        self.code_edit.setFocus()

    def _add_station(self, name, host, port):
        if (host, port) in self._stations:
            return
        self._stations.add((host, port))
        item = QListWidgetItem(f"{name}  —  {host}:{port}")
        item.setData(Qt.UserRole, (host, port))
        self.station_list.addItem(item)
        if not self.host_edit.text():
            self.station_list.setCurrentItem(item)

    def _pick_station(self, item, _previous=None):
        if item is None:
            return
        host, port = item.data(Qt.UserRole)
        self.host_edit.setText(host)
        self.port_spin.setValue(port)

    def _attempt(self):
        host = self.host_edit.text().strip()
        code = self.code_edit.text().strip()
        if not host or not code:
            self._show("Enter the station's host and the monitor code.", error=True)
            return
        self.join_btn.setEnabled(False)
        self._show(f"Joining {host}:{self.port_spin.value()}...")
        self.client.join(host, self.port_spin.value(), code)
        self._timeout.start(_JOIN_TIMEOUT_MS)

    def _on_joined(self, _station):
        if self.isVisible():
            self._timeout.stop()
            self.accept()

    def _on_denied(self, reason):
        if self.isVisible():
            self._timeout.stop()
            self.join_btn.setEnabled(True)
            self._show(reason, error=True)
            self.code_edit.clear()
            self.code_edit.setFocus()

    def _on_timeout(self):
        self.client.leave()
        self.join_btn.setEnabled(True)
        self._show(f"No answer from {self.client.host}:{self.client.port}. Is the admin "
                   "station running with its relay on, and is the port open?", error=True)

    def _show(self, text, error=False):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {'#FF6B6B' if error else '#8FD3FF'};")

    def done(self, result):
        # Signals stay connected on a long-lived client; detach so a later
        # revoke doesn't poke a closed dialog.
        self._timeout.stop()
        for signal, slot in ((self.client.joined, self._on_joined),
                             (self.client.denied, self._on_denied)):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass
        super().done(result)


def join_relay(client, parent=None):
    """Show the join dialog; True once the admin has accepted the code."""
    return MonitorJoinDialog(client, parent).exec_() == QDialog.Accepted
