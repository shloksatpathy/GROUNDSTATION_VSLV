"""
Single startup path for the packaged app: pick host or monitor, then launch.

The mode comes from, in order: an explicit argument (monitor.py), a
--host / --monitor command-line flag, the saved "launch_mode" config key, and
finally the chooser dialog. run.py, main.py and monitor.py all end up here so
they cannot drift.
"""
import sys

from PyQt5.QtWidgets import QApplication

from main import (GroundStation, apply_dark_theme, set_application_attributes)
from monitor_main import MonitorStation
from ui.auth_dialog import require_authorization
from ui.mode_dialog import choose_mode, HOST, MONITOR
from ui.monitor_join_dialog import join_relay
from core.config import load_config, save_config_values
from core.relay import RelayClient


def _resolve_mode(argv):
    if "--monitor" in argv:
        return MONITOR, False
    if "--host" in argv:
        return HOST, False
    saved = load_config().get("launch_mode")
    if saved in (HOST, MONITOR):
        return saved, False
    return choose_mode()


def main(mode=None):
    # Must precede QApplication: high-DPI scaling is ignored otherwise.
    set_application_attributes()
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    remember = False
    if mode is None:
        mode, remember = _resolve_mode(sys.argv[1:])
    if mode is None:
        sys.exit(0)

    if mode == MONITOR:
        client = RelayClient()
        if not join_relay(client):
            sys.exit(0)
        window = MonitorStation(client)
    else:
        if not require_authorization():
            sys.exit(0)
        window = GroundStation()

    if remember:
        try:
            save_config_values({"launch_mode": mode})
        except OSError as e:
            print(f"[LAUNCH] Could not remember launch mode: {e}")

    window.show()
    sys.exit(app.exec_())
