"""Sprawdza skróty listy wyników i komunikaty czytnika na prawdziwych kontrolkach wx."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SHAQ_TEST_GUI") != "1",
    reason="Test interfejsu wymaga wxPython i SHAQ_TEST_GUI=1.",
)


@pytest.fixture(scope="module", autouse=True)
def release_soundcard_com() -> Iterator[None]:
    """Zwalnia testowy interfejs COM przed zamknięciem interpretera."""
    yield
    module = sys.modules.get("soundcard.mediafoundation")
    library = getattr(module, "_com", None)
    if library is not None and library.com_loaded:
        library.__del__()
        library.com_loaded = False


@pytest.fixture(params=["pl", "en"])
def window(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Any]:
    """Tworzy ukryte okno z osobną konfiguracją i bez używania schowka użytkownika."""
    wx = pytest.importorskip("wx")
    soundcard = pytest.importorskip("soundcard")
    from shaq import _gui

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    device = SimpleNamespace(id="test", name="Test", channels=1)
    for name in ("all_speakers", "all_microphones"):
        monkeypatch.setattr(soundcard, name, lambda: [device])
    for name in ("default_speaker", "default_microphone"):
        monkeypatch.setattr(soundcard, name, lambda: device)
    _gui._save_config({"ui_language": request.param})
    app = wx.GetApp() or wx.App(False)
    existing = set(wx.GetTopLevelWindows())
    dialogs = Mock()
    copied = Mock(return_value=True)
    monkeypatch.setattr(wx, "MessageBox", dialogs)
    monkeypatch.setattr(wx, "CallAfter", lambda *_a, **_k: None)
    monkeypatch.setattr(wx.Frame, "Show", lambda *_a, **_k: False)
    monkeypatch.setattr(wx, "App", lambda *_a, **_k: app)
    monkeypatch.setattr(app, "MainLoop", lambda: None)
    monkeypatch.setattr(_gui, "copy_text", copied)
    _gui._main()
    frame = next(item for item in wx.GetTopLevelWindows() if item not in existing)
    frame._timer.Stop()
    spoken = Mock(return_value=True)
    frame._announcer.speaker = SimpleNamespace(speak=spoken)
    yield SimpleNamespace(
        frame=frame,
        wx=wx,
        copied=copied,
        spoken=spoken,
        dialogs=dialogs,
        language=request.param,
        module=_gui,
    )
    frame.Destroy()
    app.ProcessPendingEvents()
    wx.Yield()


def press(
    window: Any,
    key: int,
    *,
    control: bool = True,
    shift: bool = False,
    alt: bool = False,
    meta: bool = False,
    target: Any = None,
) -> Any:
    """Wysyła zdarzenie klawiatury do wskazanej kontrolki, bez klawiszy systemowych."""
    event = window.wx.KeyEvent(window.wx.wxEVT_KEY_DOWN)
    event.SetKeyCode(key)
    event.SetControlDown(control)
    event.SetShiftDown(shift)
    event.SetAltDown(alt)
    event.SetMetaDown(meta)
    target = window.frame.log_list if target is None else target
    event.SetEventObject(target)
    target.GetEventHandler().ProcessEvent(event)
    return event


@pytest.mark.parametrize("full", [False, True])
def test_copy_uses_metadata_preserves_selection_and_announces(window: Any, full: bool) -> None:
    frame = window.frame
    artist = "Artysta - Gość feat. Żółć & 東京"
    title = "Tytuł - część druga — na żywo 🎵"
    display = f"{artist} - {title}"
    frame._events.put(("track", (display, title)))
    frame._on_timer(None)
    frame.log_list.SetSelection(0)
    frame.log_list.SetFocus()
    initial_focus = window.wx.Window.FindFocus()
    frame._events.put(("track", ("Ktoś - Nowszy utwór", "Nowszy utwór")))
    frame._on_timer(None)
    assert not frame._advanced.announce_recognitions

    event = press(window, ord("C"), shift=full)
    window.copied.assert_called_once_with(display if full else title)
    key = "clipboard.full_copied" if full else "clipboard.title_copied"
    expected = window.module._STRINGS[key][window.language]
    window.spoken.assert_called_once_with(expected, int(frame.log_list.GetHandle()))
    assert frame.GetStatusBar().GetStatusText() == expected
    assert frame.log_list.GetSelection() == 0
    assert window.wx.Window.FindFocus() == initial_focus
    assert not event.GetSkipped()
    window.dialogs.assert_not_called()


@pytest.mark.parametrize("populated", [False, True])
def test_no_selection_does_not_touch_clipboard(window: Any, populated: bool) -> None:
    if populated:
        window.frame.log_list.Append("Autor - Tytuł", "Tytuł")
        window.frame.log_list.SetSelection(window.wx.NOT_FOUND)
    press(window, ord("C"))
    window.copied.assert_not_called()
    assert (
        window.spoken.call_args.args[0]
        == (window.module._STRINGS["clipboard.no_selection"][window.language])
    )


@pytest.mark.parametrize("failure", [False, TypeError("Błędny typ"), ValueError("Pusty tekst")])
def test_copy_failure_is_announced_without_success(window: Any, failure: Any) -> None:
    window.frame.log_list.Append("Autor - Tytuł", "Tytuł")
    window.frame.log_list.SetSelection(0)
    window.copied.return_value = False
    if isinstance(failure, Exception):
        window.copied.side_effect = failure
    press(window, ord("C"))
    expected = window.module._STRINGS["clipboard.failed"][window.language]
    assert window.spoken.call_args.args[0] == expected
    assert window.frame.GetStatusBar().GetStatusText() == expected
    assert window.frame.log_list.GetSelection() == 0


@pytest.mark.parametrize("success", [False, True])
def test_unavailable_speech_has_accessible_dialog_fallback(window: Any, success: bool) -> None:
    window.frame.log_list.Append("Autor - Tytuł", "Tytuł")
    window.frame.log_list.SetSelection(0)
    window.copied.return_value = success
    window.spoken.return_value = False
    press(window, ord("C"))
    window.dialogs.assert_called_once()
    assert window.dialogs.call_args.args[0] == window.spoken.call_args.args[0]


@pytest.mark.parametrize(
    "key,modifiers",
    [
        (ord("C"), {"control": False}),
        (ord("C"), {"alt": True}),
        (ord("C"), {"meta": True}),
        (ord("X"), {}),
        (317, {}),
    ],
)
def test_other_keys_are_passed_to_list(window: Any, key: int, modifiers: dict[str, bool]) -> None:
    event = press(window, key, **modifiers)
    assert event.GetSkipped()
    window.copied.assert_not_called()
    window.spoken.assert_not_called()


@pytest.mark.parametrize("shift", [False, True])
def test_shortcuts_in_other_controls_are_not_intercepted(window: Any, shift: bool) -> None:
    window.frame.log_list.Append("Autor - Tytuł", "Tytuł")
    window.frame.log_list.SetSelection(0)
    press(window, ord("C"), shift=shift, target=window.frame.out_path)
    window.copied.assert_not_called()
    window.spoken.assert_not_called()
