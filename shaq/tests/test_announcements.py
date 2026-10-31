"""Sprawdza wybór czytnika, warunek fokusu i pomijanie powtórnych rozpoznań."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from shaq import _announcements
from shaq._announcements import RecognitionAnnouncer, ScreenReaderSpeaker
from shaq._uia_notifications import notify
from shaq._zdsr_output import ZdsrOutput


@pytest.mark.parametrize("enabled,focused", [(False, False), (False, True), (True, False)])
def test_disabled_or_unfocused_does_not_initialize_reader(enabled: bool, focused: bool) -> None:
    factory = Mock(side_effect=AssertionError("Czytnik nie powinien być inicjalizowany."))
    fallback = Mock()
    announcer = RecognitionAnnouncer(ScreenReaderSpeaker(output_classes=factory, notify=fallback))
    assert not announcer.announce(
        "Wykonawca - Utwór", enabled=enabled, list_focused=focused, hwnd=1
    )
    factory.assert_not_called()
    fallback.assert_not_called()


def test_announcer_handles_repeats_changed_track_and_new_session() -> None:
    speaker = Mock()
    speaker.speak.return_value = True
    announcer = RecognitionAnnouncer(speaker)
    for track in ("A", "A", "B", "B", "A"):
        announcer.announce(track, enabled=True, list_focused=True, hwnd=1)
    assert [call.args[0] for call in speaker.speak.call_args_list] == ["A", "B", "A"]
    announcer.reset()
    assert announcer.announce("A", enabled=True, list_focused=True, hwnd=1)


def test_announcer_can_deliver_after_returning_to_list_or_output_failure() -> None:
    speaker = Mock()
    speaker.speak.side_effect = [False, True]
    announcer = RecognitionAnnouncer(speaker)
    assert not announcer.announce("A", enabled=True, list_focused=False, hwnd=1)
    assert not announcer.announce("A", enabled=True, list_focused=True, hwnd=1)
    assert announcer.announce("A", enabled=True, list_focused=True, hwnd=1)
    assert not announcer.announce("A", enabled=True, list_focused=True, hwnd=1)
    assert speaker.speak.call_count == 2


@pytest.mark.parametrize("text", ["", " \t\n"])
def test_empty_result_is_silent(text: str) -> None:
    speaker = Mock()
    assert not RecognitionAnnouncer(speaker).announce(text, enabled=True, list_focused=True, hwnd=1)
    speaker.speak.assert_not_called()


@pytest.mark.parametrize("text", [None, 123, b"A"])
def test_invalid_result_is_rejected(text: Any) -> None:
    with pytest.raises(TypeError):
        RecognitionAnnouncer().announce(text, enabled=True, list_focused=True, hwnd=1)
    with pytest.raises(TypeError):
        ScreenReaderSpeaker().speak(text, 1)


@pytest.mark.parametrize("name", ["NVDA", "jaws", "ZDSR", "Dolphin", "PC Talker"])
def test_active_readers_receive_unicode_without_interrupting(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shaq import _zdsr_output

    output = SimpleNamespace(name=name, is_active=Mock(return_value=True), speak=Mock())
    output.speak.return_value = None
    output_class = Mock(return_value=output)
    output_class.name = name
    output_class.system_output = False
    monkeypatch.setattr(_zdsr_output, "create_output", lambda factory: factory())
    fallback = Mock()
    speaker = ScreenReaderSpeaker(output_classes=lambda: [output_class], notify=fallback)
    assert speaker.speak("Żółć — wykonawca, utwór", 17)
    output.speak.assert_called_once_with("Żółć — wykonawca, utwór", interrupt=False)
    assert speaker.last_backend == name
    fallback.assert_not_called()


def test_one_broken_output_does_not_block_other_reader() -> None:
    broken = Mock(side_effect=OSError("Brak biblioteki"))
    broken.system_output = False
    broken.name = "Uszkodzony"
    reader = SimpleNamespace(name="NVDA", is_active=lambda: True, speak=Mock(return_value=None))
    working = Mock(return_value=reader, system_output=False)
    speaker = ScreenReaderSpeaker(output_classes=lambda: [broken, working], notify=Mock())
    assert speaker.speak("Utwór", 17)
    assert speaker.last_backend == "NVDA"


def test_narrator_uses_uia_and_sapi_is_not_started() -> None:
    sapi = Mock(system_output=True)
    fallback = Mock(return_value=True)
    speaker = ScreenReaderSpeaker(output_classes=lambda: [sapi], notify=fallback)
    assert speaker.speak("Utwór", 17)
    assert speaker.last_backend == "UI Automation"
    sapi.assert_not_called()
    fallback.assert_called_once_with(17, "Utwór")


def test_missing_package_and_unavailable_uia_do_not_raise() -> None:
    speaker = ScreenReaderSpeaker(
        output_classes=Mock(side_effect=ImportError("Brak pakietu")),
        notify=Mock(side_effect=OSError("Brak UIA")),
    )
    assert not speaker.speak("Utwór", 17)
    assert speaker.last_error == "Brak UIA"


def test_reader_can_start_after_first_attempt() -> None:
    active = False
    output = SimpleNamespace(name="NVDA", is_active=lambda: active, speak=Mock(return_value=None))
    factory = Mock(return_value=output, system_output=False)
    fallback = Mock(return_value=False)
    speaker = ScreenReaderSpeaker(output_classes=lambda: [factory], notify=fallback)
    assert not speaker.speak("Utwór", 17)
    active = True
    assert speaker.speak("Utwór", 17)
    assert factory.call_count == 1


@pytest.mark.parametrize(
    "hwnd,error", [(0, ValueError), (-1, ValueError), (True, TypeError), ("1", TypeError)]
)
def test_uia_rejects_invalid_window_handle(hwnd: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        notify(hwnd, "Utwór")


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize(
    "state,active", [(1, False), (2, False), (3, True), (4, True), (8, False), (9, False)]
)
def test_zdsr_checks_real_status_and_initialization_signature(
    modern: bool, state: int, active: bool
) -> None:
    library = SimpleNamespace(
        InitTTS=Mock(return_value=0),
        GetSpeakState=Mock(return_value=state),
        Speak=Mock(return_value=0),
    )
    output = ZdsrOutput(library, modern=modern)
    assert output.is_active() is active
    library.InitTTS.assert_called_once_with(*((0, None, True) if modern else (0, "")))
    assert output.speak("Żółć", interrupt=False) is active
    if active:
        library.Speak.assert_called_once_with("Żółć", False)
    else:
        library.Speak.assert_not_called()


def test_zdsr_initialization_and_delivery_failures() -> None:
    library = SimpleNamespace(
        InitTTS=Mock(return_value=1), GetSpeakState=Mock(return_value=4), Speak=Mock(return_value=8)
    )
    output = ZdsrOutput(library, modern=True)
    assert not output.is_active()
    library.InitTTS.return_value = 0
    assert output.is_active()
    assert not output.speak("Utwór")
    assert not output.speak("")
    with pytest.raises(TypeError):
        output.speak(None)


@pytest.mark.parametrize("cdll", [False, True])
def test_bundled_dll_is_loaded_from_extraction_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cdll: bool,
) -> None:
    loader = Mock()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(ctypes, "CDLL" if cdll else "WinDLL", loader, raising=False)
    assert (
        _announcements._bundled_library("nvdaControllerClient64.dll", cdll) is loader.return_value
    )
    loader.assert_called_once_with(
        str(tmp_path / "accessible_output2/lib/nvdaControllerClient64.dll")
    )


@pytest.mark.parametrize(
    "name,error", [(None, TypeError), ("", ValueError), ("../other.dll", ValueError)]
)
def test_bundled_dll_rejects_invalid_name(name: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        _announcements._bundled_library(name)


def test_real_output_catalog_uses_bundled_dll_loader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("accessible_output2")
    from accessible_output2.outputs import base

    monkeypatch.setattr(base, "load_library", base.load_library)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    classes = list(_announcements._output_classes())
    assert base.load_library is _announcements._bundled_library
    assert {"NVDA", "jaws", "ZDSR"}.issubset({cls.name for cls in classes})
