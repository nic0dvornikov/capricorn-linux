# PyInstaller onedir bundle for Linux package formats.
from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets"), ("bundled", "bundled")]
binaries = []
hiddenimports = []
# Let PyInstaller's Qt hooks collect only the PySide6 modules and plugins
# imported by the app. collect_all("PySide6") would bundle every Qt module.
package_datas, package_binaries, package_hidden = collect_all("vosk")
datas += package_datas
binaries += package_binaries
hiddenimports += package_hidden

a = Analysis(
    ["linux_main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "piper", "onnxruntime", "piper_phonemize"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="capricorn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="capricorn",
)
