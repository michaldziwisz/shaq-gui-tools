# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, copy_metadata
from pathlib import Path

_SPEC_DIR = Path(globals().get("SPECPATH", ".")).resolve()
_FFMPEG = _SPEC_DIR / "vendor" / "ffmpeg" / "ffmpeg.exe"
if not _FFMPEG.is_file():
    raise SystemExit("Brak FFmpeg do obsługi radia. Uruchom python fetch_ffmpeg_windows.py.")


a = Analysis(
    ["shaq\\_gui.py"],
    pathex=[],
    binaries=collect_dynamic_libs("accessible_output2") + [(str(_FFMPEG), ".")],
    datas=copy_metadata("accessible-output2"),
    hiddenimports=[
        "shaq._sygnalista_gui",
        "shaq._announcements",
        "shaq._uia_notifications",
        "shaq._zdsr_output",
        "shaq._radio_playlist",
        "shaq._radio_stream",
        "shaq._radio_preview",
        "shaq._radio_panel",
        "sygnalista_reporter",
    ] + collect_submodules("accessible_output2.outputs"),
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
    name="shaqgui",
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
