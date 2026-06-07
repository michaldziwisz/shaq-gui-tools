from __future__ import annotations

import os
from pathlib import Path

import pytest

from shaqcast.startup import (
    AutostartError,
    runtime_shortcut_spec,
    set_autostart_enabled,
    startup_shortcut_path,
)


def test_startup_shortcut_path_uses_windows_startup_folder() -> None:
    appdata = Path("C:/Users/user/AppData/Roaming")
    path = startup_shortcut_path(appdata=str(appdata))

    assert path == (
        appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "Shaqcast.lnk"
    )


def test_runtime_shortcut_spec_for_frozen_exe() -> None:
    exe = Path("C:/program portable/shaqcast.exe")
    spec = runtime_shortcut_spec(executable=exe, frozen=True)

    assert spec.target_path == exe
    assert spec.arguments == ""
    assert spec.working_directory == exe.parent


def test_runtime_shortcut_spec_for_source_tree() -> None:
    spec = runtime_shortcut_spec(executable="/usr/bin/python", frozen=False)

    assert spec.target_path == Path("/usr/bin/python")
    assert spec.arguments == "-m shaqcast"


def test_set_autostart_enabled_rejects_non_windows() -> None:
    if os.name == "nt":
        pytest.skip("This test must not create a real Startup shortcut on Windows.")

    with pytest.raises(AutostartError):
        set_autostart_enabled(True)
