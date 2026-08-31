#!/usr/bin/env python3
"""
VSSSIC Ground Station V3 - Entry Point
Launches the modular ground station application.
"""
import sys
import os

# Add application directory to path. Frozen builds resolve these modules from
# the bundle instead — see pathex in build.spec.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'application'))

from PyQt5.QtWidgets import QApplication

# Imported before QApplication is constructed — QtWebEngine requires this.
from main import GroundStation, apply_dark_theme, set_application_attributes


def main():
    # Shared with application/main.py's main() so the two entry points can't
    # drift — high-DPI scaling in particular has to be set before the
    # QApplication exists or it is silently ignored.
    set_application_attributes()
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = GroundStation()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
