from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from shaqcast import _process_picker as picker_module
from shaqcast._process_audio import ProcessInfo, ProcessTarget


class Choice:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.selection = -1

    def SetItems(self, values: list[str]) -> None:
        self.items = values

    def SetSelection(self, value: int) -> None:
        self.selection = value

    def GetSelection(self) -> int:
        return self.selection


def test_closed_selection_survives_refresh_and_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    target = ProcessTarget(r"C:\Programy\winamp.exe")
    choice = Choice()
    changed: list[bool] = []
    picker = picker_module.ProcessPicker(
        None,
        choice,
        target.to_config(),
        changed=lambda: changed.append(True),
        status=lambda _: None,
    )
    monkeypatch.setattr(picker_module, "list_processes", lambda: [])
    picker.refresh(force=True)
    assert picker.target == target
    assert choice.selection == 1
    assert "nieuruchomiony" in choice.items[1]
    monkeypatch.setattr(
        picker_module, "list_processes", lambda: [ProcessInfo(99, 1, target.executable, 1)]
    )
    picker.refresh(force=True)
    assert picker.target == target
    assert choice.selection == 1
    assert "nieuruchomiony" not in choice.items[1]
    assert changed == []


def test_refresh_does_not_select_unrelated_program(monkeypatch: pytest.MonkeyPatch) -> None:
    choice = Choice()
    monkeypatch.setattr(
        picker_module, "list_processes", lambda: [ProcessInfo(99, 1, r"C:\nvda.exe", 1)]
    )
    picker = picker_module.ProcessPicker(
        None, choice, None, changed=lambda: None, status=lambda _: None
    )
    picker.refresh(force=True)
    assert choice.selection == 0
    assert picker.target is None


def test_user_selection_is_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    choice = Choice()
    saved: list[dict[str, str]] = []
    monkeypatch.setattr(
        picker_module, "list_processes", lambda: [ProcessInfo(99, 1, r"C:\winamp.exe", 1)]
    )
    picker = picker_module.ProcessPicker(
        None,
        choice,
        None,
        changed=lambda: saved.append(picker.target.to_config()),
        status=lambda _: None,
    )
    picker.refresh(force=True)
    choice.SetSelection(1)
    picker.select_current()
    assert saved == [{"executable": r"C:\winamp.exe"}]


def test_start_without_selection_has_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker_module, "require_process_capture", lambda: None)
    picker = picker_module.ProcessPicker(
        None, Choice(), {}, changed=lambda: None, status=lambda _: None
    )
    with pytest.raises(ValueError, match="Wybierz program"):
        picker.selected()


def test_startup_prompts_for_missing_saved_program(monkeypatch: pytest.MonkeyPatch) -> None:
    dialogs: list[str] = []
    wx = SimpleNamespace(
        OK=1, ICON_INFORMATION=2, MessageBox=lambda message, *_args: dialogs.append(message)
    )
    monkeypatch.setitem(sys.modules, "wx", wx)
    monkeypatch.setattr(picker_module, "require_process_capture", lambda: None)
    monkeypatch.setattr(picker_module, "list_processes", lambda: [])
    picker = picker_module.ProcessPicker(
        None,
        Choice(),
        {"executable": r"C:\winamp.exe"},
        changed=lambda: None,
        status=lambda _: None,
    )
    picker.startup_notice()
    assert len(dialogs) == 1
    assert "Uruchom go" in dialogs[0]
    assert picker.target.executable == r"C:\winamp.exe"


def test_running_player_does_not_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "wx", SimpleNamespace())
    monkeypatch.setattr(picker_module, "require_process_capture", lambda: None)
    monkeypatch.setattr(
        picker_module, "list_processes", lambda: [ProcessInfo(99, 1, r"C:\winamp.exe", 1)]
    )
    picker = picker_module.ProcessPicker(
        None,
        Choice(),
        {"executable": r"C:\winamp.exe"},
        changed=lambda: None,
        status=lambda _: None,
    )
    picker.startup_notice()


def test_explicit_empty_selection_clears_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker_module, "list_processes", lambda: [])
    monkeypatch.setattr(picker_module, "require_process_capture", lambda: None)
    choice = Choice()
    picker = picker_module.ProcessPicker(
        None,
        choice,
        {"executable": r"C:\winamp.exe"},
        changed=lambda: None,
        status=lambda _: None,
    )
    picker.refresh(force=True)
    choice.SetSelection(0)
    picker.select_current()
    assert picker.target is None
    with pytest.raises(ValueError):
        picker.selected()


def test_enumeration_error_does_not_leave_device_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> list[ProcessInfo]:
        raise OSError("Nie można odczytać listy procesów.")

    monkeypatch.setattr(picker_module, "list_processes", fail)
    choice = Choice()
    choice.SetItems(["Głośniki"])
    picker = picker_module.ProcessPicker(
        None,
        choice,
        {"executable": r"C:\winamp.exe"},
        changed=lambda: None,
        status=lambda _: None,
    )
    picker.refresh(force=True)
    assert "winamp.exe" in choice.items[choice.selection]
    assert "Głośniki" not in choice.items
