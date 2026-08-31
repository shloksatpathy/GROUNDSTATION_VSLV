import json

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
                              QPushButton, QMessageBox, QLabel)

from core.config import get, resolve_path, load_rocket_config
from core.rocket_sim import ROCKETPY_AVAILABLE, ROCKETPY_IMPORT_ERROR


class SimulationTab(QWidget):
    """Editor for config/rocket_config.json — the RocketPy input that drives
    the "ideal" trajectory shown on the Map tab.

    Mirrors ui/packet_editor_tab.py's raw-JSON-editor pattern rather than a
    generated form: RocketPy's input surface (environment/motor/rocket/
    flight, with optional nested nose/fins/tail/rail_buttons) is large and
    already fully described by the JSON schema, so a hand-built form would
    just be a second, driftable copy of the same field names.
    """

    def __init__(self, trajectory_view=None):
        super().__init__()

        # Reference to ui/trajectory_3d.py's view — reused so there is a
        # single RocketSimThread owner instead of two independent ones.
        self.trajectory_view = trajectory_view
        self.config_file = resolve_path(get("rocket_config_path", "config/rocket_config.json"))

        layout = QVBoxLayout()

        info = QLabel(f"Editing RocketPy input: {self.config_file}")
        info.setStyleSheet("color: #aaa; font-style: italic;")
        layout.addWidget(info)

        if not ROCKETPY_AVAILABLE:
            warn = QLabel(f"rocketpy is not installed ({ROCKETPY_IMPORT_ERROR}) — simulation is disabled.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#FFB300; font-weight:bold;")
            layout.addWidget(warn)

        self.editor = QTextEdit()
        self.editor.setStyleSheet(
            "font-family: monospace; font-size: 13px; background: #1E1E1E; color: #E0E0E0;"
        )
        layout.addWidget(self.editor)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#E0E0E0; font-size:12px;")
        layout.addWidget(self.status_lbl)

        btn_layout = QHBoxLayout()
        self.load_button = QPushButton("Reload from File")
        self.save_button = QPushButton("Save")
        self.run_button = QPushButton("Save & Run Simulation")

        self.load_button.setStyleSheet("padding: 8px; background-color: #333;")
        self.save_button.setStyleSheet("padding: 8px; background-color: #333;")
        self.run_button.setStyleSheet("padding: 8px; background-color: #0078D7; font-weight: bold;")
        if not ROCKETPY_AVAILABLE or self.trajectory_view is None:
            self.run_button.setEnabled(False)

        btn_layout.addWidget(self.load_button)
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(self.run_button)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

        self.load_button.clicked.connect(lambda: self.load_params())
        self.save_button.clicked.connect(lambda: self.save_params())
        self.run_button.clicked.connect(self.save_and_run)

        # The solve is plotted on the Map tab; this tab only reports its
        # outcome, so "Running simulation..." doesn't sit there forever.
        if self.trajectory_view is not None:
            self.trajectory_view.simulation_complete.connect(self._on_sim_done)
            self.trajectory_view.simulation_failed.connect(self._on_sim_error)

        # Initial load — silent, a modal dialog here would block the window from showing
        self.load_params(show_errors=False)

    def _on_sim_done(self, result):
        self.status_lbl.setText(
            f"Simulation complete — ideal apogee: {result['apogee_agl']:.1f} m AGL   "
            f"Max speed: {result['max_speed']:.1f} m/s   (plotted on the Map tab)"
        )

    def _on_sim_error(self, message):
        self.status_lbl.setText(f"Simulation error: {message}")

    def load_params(self, show_errors=True):
        """Load the rocket_config.json content into the editor."""
        try:
            with open(self.config_file, "r") as f:
                content = f.read()
            self.editor.setText(content)
        except Exception as e:
            msg = f"Could not load rocket config: {e}"
            print(f"[SIM CONFIG] {msg}")
            self.editor.setText("")
            if show_errors:
                QMessageBox.warning(self, "Error", msg)

    def save_params(self):
        """Validate JSON and save to file, then invalidate the cached config
        so the next simulation run picks up the edit.

        Returns True on success, False otherwise — callers that chain a run
        afterwards use this to avoid simulating against a rejected edit.
        """
        content = self.editor.toPlainText()
        try:
            parsed = json.loads(content)

            with open(self.config_file, "w") as f:
                json.dump(parsed, f, indent=2)

            load_rocket_config(force_reload=True)
            self.status_lbl.setText("Saved.")
            return True

        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "JSON Error", f"Invalid JSON syntax:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save rocket config: {e}")
        return False

    def save_and_run(self):
        if not self.save_params():
            return
        if self.trajectory_view is None:
            return
        self.status_lbl.setText("Running simulation...")
        self.trajectory_view.run_simulation()
