"""Startup authorization gate.

Blocks the ground station UI behind a fixed 4-character passphrase. Not a
security boundary — the string lives in this file in plaintext — just a
deliberate "are you supposed to be here" checkpoint before the window opens.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QMessageBox)

AUTH_CODE = "VSLV"


class AuthDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VSSSIC Ground Station V3 - Authorization")
        self.setFixedSize(360, 150)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        prompt = QLabel("Enter the 4-character authorization code to continue:")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        self.entry = QLineEdit()
        self.entry.setMaxLength(4)
        self.entry.setAlignment(Qt.AlignCenter)
        self.entry.returnPressed.connect(self._attempt)
        layout.addWidget(self.entry)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Exit")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Unlock")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._attempt)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)

        self.entry.setFocus()

    def _attempt(self):
        if self.entry.text().strip().upper() == AUTH_CODE:
            self.accept()
        else:
            QMessageBox.critical(self, "Access Denied", "Incorrect authorization code.")
            self.entry.clear()
            self.entry.setFocus()


def require_authorization(parent=None):
    """Show the authorization dialog and return True iff it was passed."""
    return AuthDialog(parent).exec_() == QDialog.Accepted
