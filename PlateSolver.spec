# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['platesolver.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtGui', 'PyQt5.QtCore', 'PyQt5.QtPrintSupport'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PlateSolver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/PsIcon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PlateSolver',
)
app = BUNDLE(
    coll,
    name='PlateSolver.app',
    icon='icons/PsIcon.icns',
    bundle_identifier=None,
)
