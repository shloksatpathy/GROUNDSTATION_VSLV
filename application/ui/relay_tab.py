"""
Admin-side settings for the monitor relay (core/relay.py).

Sets the code monitors must enter, the UDP port and station name they see,
and lists the monitors currently receiving telemetry. Saved to config.json
so the relay comes back up the same way on the next launch.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QLabel, QLineEdit, QSpinBox, QCheckBox,
                             QPushButton, QListWidget)

from core.config import load_config, save_config_values
from core.relay import RelayServer, DEFAULT_RELAY_PORT

_MIN_CODE_LEN = 4


class RelayTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        cfg = load_config()
        self.relay = RelayServer(cfg.get("station_name", "VSLV Ground Station"),
                                 str(cfg.get("monitor_code", "VIEW")), self)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Monitors are view-only copies of this station. They receive every "
            "processed packet, the launch reference and the simulated trajectory, "
            "but cannot connect to the vehicle, send commands, record, or edit "
            "configuration. Run them with <b>monitor.py</b> on any machine on this LAN."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#BBB; font-size:12px;")
        layout.addWidget(intro)

        form = QFormLayout()

        self.enabled_chk = QCheckBox("Relay telemetry to monitors")
        self.enabled_chk.setChecked(bool(cfg.get("relay_enabled", True)))
        form.addRow(self.enabled_chk)

        self.name_edit = QLineEdit(self.relay.station_name)
        self.name_edit.setToolTip("Shown in each monitor's station list and title bar")
        form.addRow("Station name:", self.name_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(int(cfg.get("relay_port", DEFAULT_RELAY_PORT)))
        form.addRow("UDP port:", self.port_spin)

        code_row = QHBoxLayout()
        self.code_edit = QLineEdit(self.relay.code)
        self.code_edit.setEchoMode(QLineEdit.Password)
        self.code_edit.setMaxLength(16)
        self.code_edit.setToolTip(
            "Code monitors enter to join. Changing it disconnects every monitor\n"
            "still using the old code within a couple of seconds.")
        show_chk = QCheckBox("Show")
        show_chk.toggled.connect(lambda on: self.code_edit.setEchoMode(
            QLineEdit.Normal if on else QLineEdit.Password))
        code_row.addWidget(self.code_edit)
        code_row.addWidget(show_chk)
        form.addRow("Monitor code:", code_row)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply && Save")
        self.apply_btn.setStyleSheet("padding: 6px 12px; background-color: #0078D7; font-weight: bold;")
        self.apply_btn.clicked.connect(self.apply)
        btn_row.addWidget(self.apply_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#8FD3FF; font-size:12px;")
        layout.addWidget(self.status_lbl)

        layout.addWidget(QLabel("Connected monitors:"))
        self.monitor_list = QListWidget()
        layout.addWidget(self.monitor_list, stretch=1)

        self.relay.status_changed.connect(self.status_lbl.setText)
        self.relay.subscribers_changed.connect(self._show_monitors)

        if self.enabled_chk.isChecked():
            self.relay.start(self.port_spin.value())
        else:
            self.status_lbl.setText("Relay off")

    def apply(self):
        code = self.code_edit.text().strip()
        if len(code) < _MIN_CODE_LEN:
            self.status_lbl.setText(f"Monitor code must be at least {_MIN_CODE_LEN} characters.")
            return
        name = self.name_edit.text().strip() or "VSLV Ground Station"
        port = self.port_spin.value()
        enabled = self.enabled_chk.isChecked()

        self.relay.set_code(code)
        self.relay.station_name = name
        if not enabled:
            self.relay.stop()
            self.status_lbl.setText("Relay off")
        elif not self.relay.is_running() or self.relay.port != port:
            self.relay.start(port)

        try:
            save_config_values({"relay_enabled": enabled, "relay_port": port,
                                "monitor_code": code, "station_name": name})
        except OSError as e:
            self.status_lbl.setText(f"Applied, but could not save config.json: {e}")

    def _show_monitors(self, monitors):
        self.monitor_list.clear()
        self.monitor_list.addItems(monitors)
        if self.relay.is_running():
            self.status_lbl.setText(
                f"Relay listening on UDP {self.relay.port} — {len(monitors)} monitor(s)")

    def shutdown(self):
        self.relay.stop()
