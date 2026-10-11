#!/usr/bin/env python3
"""
VSSSIC Ground Station V3 - Monitor Entry Point
Launches the read-only monitor, which mirrors an admin ground station
(run.py) over the LAN.
"""
import sys
import os

# Add application directory to path. Frozen builds resolve these modules from
# the bundle instead — see pathex in build.spec.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'application'))

# Imported before QApplication is constructed — QtWebEngine requires this.
from monitor_main import main


if __name__ == "__main__":
    main()
