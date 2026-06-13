# eps2svg-gui.spec — PyInstaller build for the Qt GUI.
# Build:  pyinstaller eps2svg-gui.spec   ->   dist/eps2svg-gui.exe
# Requires PyInstaller >= 6 and the gui extra (PySide6) installed.

a = Analysis(
    ['eps2svg_gui/__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['eps2svg', 'eps2svg_pure', 'eps2svg_split'],
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
    name='eps2svg-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
