"""
Admin-side Monitor Settings (the controls for core/relay.py).

Two halves: who may watch (monitor code, host allowlist, monitor cap, and a
live list of connected monitors that can be removed) and what they see (which
packet fields, position, launch reference and simulated trajectory are sent,
how fast, and a pause switch). Everything is enforced by the relay on this
station, so a modified monitor build cannot ask for more. Saved to
config.json so the relay comes back up the same way on the next launch.
"""

import ipaddress

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QGroupBox, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
                             QCheckBox, QPushButton, QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt5.QtCore import QTimer

from core.config import load_config, save_config_values
from core.relay import RelayServer, DEFAULT_RELAY_PORT

_MIN_CODE_LEN = 4
# Keys TelemetryProcessor adds on top of the parsed packet schema.
_DERIVED_FIELDS = ["filtered_alt", "filtered_vspeed", "smoothed_vspeed",
                   "flight_state_str", "power_pct", "voltage"]


def _fmt_duration(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


class RelayTab(QWidget):

    def __init__(self, parser=None, parent=None):
        super().__init__(parent)
        self.parser = parser

        cfg = load_config()
        self.relay = RelayServer(cfg.get("station_name", "VSLV Ground Station"),
                                 str(cfg.get("monitor_code", "VIEW")), self)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Monitors are view-only copies of this station. They cannot connect to the "
            "vehicle, send commands, record, or edit configuration. Run them with "
            "<b>monitor.py</b> on any machine on this LAN. Changes apply when you press "
            "<b>Apply &amp; Save</b>."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#BBB; font-size:12px;")
        layout.addWidget(intro)

        top = QHBoxLayout()
        top.addWidget(self._build_access_group(cfg), 1)
        top.addWidget(self._build_display_group(cfg), 1)
        layout.addLayout(top)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply && Save")
        self.apply_btn.setStyleSheet("padding: 6px 12px; background-color: #0078D7; font-weight: bold;")
        self.apply_btn.clicked.connect(self.apply)
        btn_row.addWidget(self.apply_btn)

        # Takes effect immediately and is not saved: a station should not
        # come back up silently frozen.
        self.pause_btn = QPushButton("Pause feed to monitors")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setToolTip("Freeze every monitor on its last data. Not saved; "
                                  "cleared when this app restarts.")
        self.pause_btn.toggled.connect(self._toggle_pause)
        btn_row.addWidget(self.pause_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#8FD3FF; font-size:12px;")
        layout.addWidget(self.status_lbl)

        layout.addWidget(self._build_monitors_group(), stretch=1)

        self.relay.status_changed.connect(self.status_lbl.setText)
        self.relay.subscribers_changed.connect(self._on_subscribers_changed)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._refresh_monitors)
        self._clock.start(1000)

        self._push_policy()
        if self.enabled_chk.isChecked():
            self.relay.start(self.port_spin.value())
        else:
            self.status_lbl.setText("Relay off")

    # -----------------------------------
    # Layout
    # -----------------------------------
    def _build_access_group(self, cfg):
        box = QGroupBox("Authentication && access")
        form = QFormLayout(box)

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

        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 64)
        self.max_spin.setSpecialValueText("Unlimited")
        self.max_spin.setValue(int(cfg.get("relay_max_monitors", 0)))
        self.max_spin.setToolTip("Further monitors are refused once this many have joined")
        form.addRow("Max monitors:", self.max_spin)

        self.allow_edit = QLineEdit(", ".join(cfg.get("relay_allowed_hosts", [])))
        self.allow_edit.setPlaceholderText("blank = any host, or e.g. 192.168.1.30, 192.168.1.31")
        self.allow_edit.setToolTip("Comma-separated IP addresses allowed to join, even with the code")
        form.addRow("Allowed hosts:", self.allow_edit)
        return box

    def _build_display_group(self, cfg):
        box = QGroupBox("Data shown to monitors")
        v = QVBoxLayout(box)

        self.position_chk = QCheckBox("Vehicle position (GNSS lat/lon)")
        self.position_chk.setChecked(bool(cfg.get("relay_share_position", True)))
        self.reference_chk = QCheckBox("Launch reference point")
        self.reference_chk.setChecked(bool(cfg.get("relay_share_reference", True)))
        self.sim_chk = QCheckBox("Simulated (ideal) trajectory")
        self.sim_chk.setChecked(bool(cfg.get("relay_share_simulation", True)))
        for chk in (self.position_chk, self.reference_chk, self.sim_chk):
            v.addWidget(chk)

        rate_row = QFormLayout()
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0, 100)
        self.rate_spin.setDecimals(1)
        self.rate_spin.setSuffix(" pkt/s")
        self.rate_spin.setSpecialValueText("Every packet")
        self.rate_spin.setValue(float(cfg.get("relay_max_rate_hz", 0)))
        rate_row.addRow("Send rate:", self.rate_spin)
        v.addLayout(rate_row)

        v.addWidget(QLabel("Packet fields (uncheck to hide from monitors):"))
        self.field_list = QListWidget()
        self.field_list.setMinimumHeight(110)
        self._hidden_saved = set(cfg.get("relay_hidden_fields", []))
        self._refresh_fields()
        v.addWidget(self.field_list, stretch=1)
        return box

    def _build_monitors_group(self):
        box = QGroupBox("Connected monitors")
        v = QVBoxLayout(box)

        self.monitor_table = QTableWidget(0, 3)
        self.monitor_table.setHorizontalHeaderLabels(["Address", "Connected", ""])
        hdr = self.monitor_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.monitor_table.verticalHeader().setVisible(False)
        self.monitor_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.monitor_table.setSelectionMode(QTableWidget.NoSelection)
        v.addWidget(self.monitor_table, stretch=1)

        self.banned_row = QHBoxLayout()
        self.banned_lbl = QLabel("")
        self.banned_lbl.setStyleSheet("color:#BBB; font-size:12px;")
        self.unban_btn = QPushButton("Clear removed hosts")
        self.unban_btn.clicked.connect(self._clear_bans)
        self.banned_row.addWidget(self.banned_lbl, 1)
        self.banned_row.addWidget(self.unban_btn)
        v.addLayout(self.banned_row)
        self._show_bans()
        return box

    # -----------------------------------
    # Fields list
    # -----------------------------------
    def _known_fields(self):
        names = list(self.parser.field_names) if self.parser is not None else []
        names += [n for n in _DERIVED_FIELDS if n not in names]
        return names

    def _hidden_now(self):
        """Fields currently unchecked in the list."""
        return {self.field_list.item(i).text() for i in range(self.field_list.count())
                if self.field_list.item(i).checkState() == Qt.Unchecked}

    def _refresh_fields(self):
        """Rebuild from the packet schema, keeping the operator's choices —
        the Packet Format tab can change the field set at any time."""
        hidden = self._hidden_now() if self.field_list.count() else self._hidden_saved
        names = self._known_fields()
        names += sorted(h for h in hidden if h not in names)  # keep stale choices
        self.field_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if name in hidden else Qt.Checked)
            self.field_list.addItem(item)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_fields()

    # -----------------------------------
    # Applying
    # -----------------------------------
    def _parse_hosts(self):
        """Allowed-hosts text -> (set of IPs, error or None)."""
        hosts = set()
        for part in self.allow_edit.text().replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                hosts.add(str(ipaddress.ip_address(part)))
            except ValueError:
                return None, f"'{part}' is not a valid IP address."
        return hosts, None

    def _push_policy(self, hosts=None):
        if hosts is None:
            hosts, _ = self._parse_hosts()
            hosts = hosts or set()
        self.relay.set_policy(
            max_monitors=self.max_spin.value(),
            allowed_hosts=hosts,
            hidden_fields=self._hidden_now(),
            share_position=self.position_chk.isChecked(),
            share_reference=self.reference_chk.isChecked(),
            share_simulation=self.sim_chk.isChecked(),
            max_rate_hz=self.rate_spin.value())

    def apply(self):
        code = self.code_edit.text().strip()
        if len(code) < _MIN_CODE_LEN:
            self.status_lbl.setText(f"Monitor code must be at least {_MIN_CODE_LEN} characters.")
            return
        hosts, err = self._parse_hosts()
        if err:
            self.status_lbl.setText(err)
            return
        name = self.name_edit.text().strip() or "VSLV Ground Station"
        port = self.port_spin.value()
        enabled = self.enabled_chk.isChecked()

        self.relay.set_code(code)
        self.relay.station_name = name
        self._push_policy(hosts)
        if not enabled:
            self.relay.stop()
            self.status_lbl.setText("Relay off")
        elif not self.relay.is_running() or self.relay.port != port:
            self.relay.start(port)

        try:
            save_config_values({
                "relay_enabled": enabled, "relay_port": port,
                "monitor_code": code, "station_name": name,
                "relay_max_monitors": self.max_spin.value(),
                "relay_allowed_hosts": sorted(hosts),
                "relay_hidden_fields": sorted(self._hidden_now()),
                "relay_share_position": self.position_chk.isChecked(),
                "relay_share_reference": self.reference_chk.isChecked(),
                "relay_share_simulation": self.sim_chk.isChecked(),
                "relay_max_rate_hz": self.rate_spin.value(),
            })
        except OSError as e:
            self.status_lbl.setText(f"Applied, but could not save config.json: {e}")
            return
        if enabled and self.relay.is_running():
            self._show_status(len(self.relay.subscriber_info()))

    # -----------------------------------
    # Monitors
    # -----------------------------------
    def _toggle_pause(self, paused):
        self.relay.set_paused(paused)
        self.pause_btn.setText("Resume feed to monitors" if paused else "Pause feed to monitors")
        self.status_lbl.setText("Feed to monitors PAUSED" if paused else "Feed resumed")

    def _on_subscribers_changed(self, monitors):
        self._refresh_monitors()
        self._show_bans()
        if self.relay.is_running() and not self.pause_btn.isChecked():
            self._show_status(len(monitors))

    def _show_status(self, count):
        self.status_lbl.setText(f"Relay listening on UDP {self.relay.port} — {count} monitor(s)")

    def _refresh_monitors(self):
        info = self.relay.subscriber_info()
        self.monitor_table.setRowCount(len(info))
        for row, (key, addr, secs) in enumerate(info):
            self.monitor_table.setItem(row, 0, QTableWidgetItem(addr))
            self.monitor_table.setItem(row, 1, QTableWidgetItem(_fmt_duration(secs)))
            btn = self.monitor_table.cellWidget(row, 2)
            if btn is None:
                btn = QPushButton("Remove")
                btn.setToolTip("Disconnect this monitor and refuse its host until cleared")
                self.monitor_table.setCellWidget(row, 2, btn)
            # Rebound every tick: rows shift as monitors come and go.
            try:
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(lambda _=False, k=key: self.relay.kick(k))

    def _show_bans(self):
        banned = self.relay.banned_hosts()
        self.banned_lbl.setText("Removed hosts: " + ", ".join(banned) if banned
                                else "No removed hosts")
        self.unban_btn.setEnabled(bool(banned))

    def _clear_bans(self):
        for host in self.relay.banned_hosts():
            self.relay.unban(host)
        self._show_bans()

    def shutdown(self):
        self.relay.stop()
