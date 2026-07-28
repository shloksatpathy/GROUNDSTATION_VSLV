# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for VSSSIC Ground Station V3

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('images/vsssic-logo-1.ico', 'images'),
        ('application', 'application'),
    ],
    hiddenimports=[
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtWebEngineWidgets',
        'pyqtgraph',
        'folium',
        'serial',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='VSSSIC_Ground_Station',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='images/vsssic-logo-1.ico',
)
