#!/usr/bin/env python3
"""
VSSSIC Ground Station V3 - Entry Point
Launches the modular ground station application.
"""
import sys
import os

# Add application directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'application'))

from PyQt5.QtWidgets import QApplication
from main import GroundStation


def main():
    app = QApplication(sys.argv)
    window = GroundStation()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
