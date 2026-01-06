# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

_SPEC_DIR = Path(globals().get("SPECPATH", ".")).resolve()
_FFMPEG_DIR = _SPEC_DIR / "vendor" / "ffmpeg"
_EXT = ".exe" if os.name == "nt" else ""

_binaries = []
for tool in ("ffmpeg", "ffprobe"):
    path = _FFMPEG_DIR / f"{tool}{_EXT}"
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Run: python fetch_ffmpeg_windows.py (from the shaq/ folder) "
            "or place ffmpeg.exe/ffprobe.exe into vendor/ffmpeg/."
        )
    _binaries.append((str(path), "."))

a = Analysis(
    [str(_SPEC_DIR / "shaq" / "_file_gui.py")],
    pathex=[],
    binaries=_binaries,
    datas=[],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name="shaqfilegui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
