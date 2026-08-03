# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for VSSSIC Ground Station V3
#
# Produces a single-file executable at dist/VSSSIC_Ground_Station[.exe].
# On first launch it seeds an editable config/ next to itself and writes
# flight CSVs there — see application/core/config.py.

a = Analysis(
    ['run.py'],
    # Required: main/core.*/ui.* live under application/, so without this
    # PyInstaller cannot follow their imports and misses their dependencies.
    pathex=['application'],
    binaries=[],
    datas=[
        ('images/vsssic-logo-1.ico', 'images'),
        ('config', 'config'),
    ],
    hiddenimports=[
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtWebEngineWidgets',
        'pyqtgraph',
        'folium',
        'serial',
        'serial.tools.list_ports',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VSSSIC_Ground_Station',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Keep the console attached: a onefile GUI build that fails to start is
    # otherwise completely silent for the operator.
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='images/vsssic-logo-1.ico',
)
