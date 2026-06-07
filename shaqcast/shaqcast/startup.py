from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


_APP_SHORTCUT_NAME = "Shaqcast.lnk"


class AutostartError(RuntimeError):
    """Raised when Windows autostart cannot be changed."""


@dataclass(frozen=True)
class ShortcutSpec:
    target_path: Path
    arguments: str
    working_directory: Path


def is_autostart_supported() -> bool:
    return os.name == "nt"


def startup_shortcut_path(*, appdata: str | None = None) -> Path:
    appdata_dir = appdata or os.environ.get("APPDATA")
    if not appdata_dir:
        raise AutostartError("APPDATA is not set; cannot find Windows Startup folder.")
    return (
        Path(appdata_dir)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / _APP_SHORTCUT_NAME
    )


def runtime_shortcut_spec(
    *, executable: str | os.PathLike[str] | None = None, frozen: bool | None = None
) -> ShortcutSpec:
    exe = Path(executable or sys.executable)
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    if is_frozen:
        return ShortcutSpec(target_path=exe, arguments="", working_directory=exe.parent)

    # Source-tree fallback: useful for developers running Shaqcast without PyInstaller.
    return ShortcutSpec(
        target_path=exe,
        arguments="-m shaqcast",
        working_directory=Path.cwd(),
    )


def is_autostart_enabled(*, shortcut_path: Path | None = None) -> bool:
    if not is_autostart_supported():
        return False
    path = shortcut_path or startup_shortcut_path()
    return path.exists()


def set_autostart_enabled(enabled: bool) -> None:
    if not is_autostart_supported():
        raise AutostartError("Autostart is only supported on Windows.")

    shortcut_path = startup_shortcut_path()
    if enabled:
        _create_shortcut(shortcut_path, runtime_shortcut_spec())
        return

    try:
        shortcut_path.unlink()
    except FileNotFoundError:
        return


def _create_shortcut(shortcut_path: Path, spec: ShortcutSpec) -> None:
    try:
        import win32com.client  # type: ignore[import-not-found]

        shell = win32com.client.Dispatch("WScript.Shell")
    except Exception:
        try:
            import comtypes.client  # type: ignore[import-not-found]

            shell = comtypes.client.CreateObject("WScript.Shell")
        except Exception:
            shell = None

    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    if shell is None:
        _create_shortcut_via_wsh(shortcut_path, spec)
        return

    shortcut = shell.CreateShortcut(str(shortcut_path))
    shortcut.TargetPath = str(spec.target_path)
    shortcut.Arguments = spec.arguments
    shortcut.WorkingDirectory = str(spec.working_directory)
    shortcut.Description = "Start Shaqcast at Windows logon"
    shortcut.WindowStyle = 1
    shortcut.Save()


def _create_shortcut_via_wsh(shortcut_path: Path, spec: ShortcutSpec) -> None:
    import subprocess
    import tempfile

    script = f"""
Set shell = CreateObject("WScript.Shell")
Set shortcut = shell.CreateShortcut("{_vbs_quote(shortcut_path)}")
shortcut.TargetPath = "{_vbs_quote(spec.target_path)}"
shortcut.Arguments = "{_vbs_quote(spec.arguments)}"
shortcut.WorkingDirectory = "{_vbs_quote(spec.working_directory)}"
shortcut.Description = "Start Shaqcast at Windows logon"
shortcut.WindowStyle = 1
shortcut.Save
"""
    with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False, encoding="utf-8") as tmp:
        tmp.write(script)
        script_path = Path(tmp.name)

    try:
        result = subprocess.run(
            ["cscript.exe", "//NoLogo", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        try:
            script_path.unlink()
        except OSError:
            pass

    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise AutostartError(output or "Failed to create Startup shortcut.")


def _vbs_quote(value: str | os.PathLike[str]) -> str:
    return str(value).replace('"', '""')
