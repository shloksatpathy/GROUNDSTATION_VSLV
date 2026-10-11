"""
Startup mode chooser: run this machine as the host station or as a monitor.

One build serves both roles, so the choice is made at launch. Host is the
station that owns the radio link and goes through ui/auth_dialog.py; a
monitor is a view-only copy that joins a host over the LAN
(ui/monitor_join_dialog.py).
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QCheckBox)

HOST = "host"
MONITOR = "monitor"


class ModeDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VSSSIC Ground Station V3")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.mode = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("How should this computer run the ground station?"))

        choices = QHBoxLayout()
        choices.addWidget(self._choice(
            "Host station",
            "Connects to the vehicle's radio, records, sends commands and shares "
            "telemetry with monitors. Needs the authorization code.", HOST))
        choices.addWidget(self._choice(
            "Monitor",
            "View-only copy of a host station on this network. Needs the "
            "host's monitor code.", MONITOR))
        layout.addLayout(choices)

        self.remember = QCheckBox("Remember my choice on this computer")
        layout.addWidget(self.remember)

        exit_btn = QPushButton("Exit")
        exit_btn.clicked.connect(self.reject)
        layout.addWidget(exit_btn, alignment=Qt.AlignRight)

    def _choice(self, title, blurb, mode):
        btn = QPushButton()
        btn.setMinimumHeight(130)
        # Button text won't wrap, so the text lives in labels inside the button.
        inner = QVBoxLayout(btn)
        head = QLabel(f"<b>{title}</b>")
        head.setAlignment(Qt.AlignCenter)
        body = QLabel(blurb)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        for lbl in (head, body):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            inner.addWidget(lbl)
        btn.clicked.connect(lambda: self._pick(mode))
        return btn

    def _pick(self, mode):
        self.mode = mode
        self.accept()


def choose_mode(parent=None):
    """Return (mode, remember), or (None, False) if the user exited."""
    dlg = ModeDialog(parent)
    if dlg.exec_() != QDialog.Accepted:
        return None, False
    return dlg.mode, dlg.remember.isChecked()
