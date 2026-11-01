"""Sprawdza prawdziwe kontrolki wxPython bez wyświetlania okien i nagrywania dźwięku."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SHAQ_TEST_GUI") != "1",
    reason="Test interfejsu wymaga wxPython i jawnego włączenia SHAQ_TEST_GUI=1.",
)


@pytest.fixture(scope="module", autouse=True)
def finish_soundcard_com() -> Iterator[None]:
    """Zwalnia COM biblioteki testowej przed usunięciem jej modułów przy zamykaniu Pythona."""
    yield
    module = sys.modules.get("soundcard.mediafoundation")
    library = getattr(module, "_com", None)
    if library is not None and library.com_loaded:
        library.__del__()
        library.com_loaded = False


@pytest.fixture
def gui_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, Any, list[str]]:
    wx = pytest.importorskip("wx")
    soundcard = pytest.importorskip("soundcard")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    speaker = SimpleNamespace(id="output", name="Wyjście testowe", channels=2)
    microphone = SimpleNamespace(id="input", name="Wejście testowe", channels=1)
    monkeypatch.setattr(soundcard, "all_speakers", lambda: [speaker])
    monkeypatch.setattr(soundcard, "all_microphones", lambda: [microphone])
    monkeypatch.setattr(soundcard, "default_speaker", lambda: speaker)
    monkeypatch.setattr(soundcard, "default_microphone", lambda: microphone)
    app = wx.GetApp() or wx.App(False)
    dialogs: list[str] = []
    monkeypatch.setattr(wx, "MessageBox", lambda message, *_a, **_k: dialogs.append(message))
    monkeypatch.setattr(wx, "CallAfter", lambda *_a, **_k: None)
    monkeypatch.setattr(wx.Frame, "Show", lambda *_a, **_k: False)
    yield wx, app, dialogs
    for window in wx.GetTopLevelWindows():
        window.Destroy()
    app.ProcessPendingEvents()
    wx.Yield()


@pytest.mark.parametrize("language", ["pl", "en"])
def test_live_gui_preserves_program_across_source_switches_and_restart(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    language: str,
) -> None:
    from shaq import _gui, _process_picker
    from shaq._process_audio import ProcessTarget

    wx, app, dialogs = gui_environment
    target = ProcessTarget(r"C:\Programy\winamp.exe")
    _gui._save_config(
        {"source": "process", "process_target": target.to_config(), "ui_language": language}
    )
    monkeypatch.setattr(_process_picker, "list_processes", lambda: [])
    monkeypatch.setattr(_process_picker, "require_process_capture", lambda: None)
    monkeypatch.setattr(wx, "App", lambda *_a, **_k: app)

    def inspect_frame() -> None:
        frame = next(window for window in wx.GetTopLevelWindows() if window.GetTitle() == "shaqgui")
        assert frame.source_choice.GetCount() == 4
        assert frame.source_choice.GetSelection() == 2
        assert (
            "nieuruchomiony" if language == "pl" else "not running"
        ) in frame.device_choice.GetStringSelection()
        assert frame.source_choice.GetString(2) == (
            "Program (wybrany proces)" if language == "pl" else "Program (selected process)"
        )
        frame._process_picker.startup_notice()
        assert ("Uruchom go" if language == "pl" else "Launch it") in dialogs[-1]
        for mode, expected in ((0, "Wyjście testowe"), (1, "Wejście testowe"), (2, "winamp.exe")):
            frame.source_choice.SetSelection(mode)
            frame._on_source_changed(wx.CommandEvent())
            assert expected in frame.device_choice.GetStringSelection()
            assert frame._process_picker.target == target
        frame.out_path.SetValue(str(tmp_path / "history.txt"))
        work: list[tuple[Any, ...]] = []
        frame._worker_main = lambda *args: work.append(args)
        frame._on_start(wx.CommandEvent())
        frame._worker.join(timeout=2)
        assert work[0][0] == target
        assert _gui._load_config()["process_target"] == target.to_config()
        assert _gui._load_config()["source"] == "process"
        frame._on_close(wx.CloseEvent())
        frame.Destroy()
        wx.Yield()

    monkeypatch.setattr(app, "MainLoop", inspect_frame)
    _gui._main()
    # Drugie otwarcie korzysta wyłącznie z konfiguracji zapisanej przez pierwsze okno.
    _gui._main()


@pytest.mark.parametrize("language", ["pl", "en"])
def test_cast_gui_passes_saved_program_to_session(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    language: str,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "shaqcast"))
    from shaqcast import _process_picker, config_store, gui
    from shaqcast._process_audio import ProcessTarget

    wx, _app, dialogs = gui_environment
    target = ProcessTarget(r"C:\Programy\winamp.exe")
    config_store.save_config(
        {"source": "process", "process_target": target.to_config(), "ui_language": language}
    )
    monkeypatch.setattr(_process_picker, "list_processes", lambda: [])
    monkeypatch.setattr(_process_picker, "require_process_capture", lambda: None)
    monkeypatch.setattr(gui, "is_autostart_supported", lambda: False)
    sessions: list[Any] = []

    class Session:
        def __init__(self, *, settings: Any, log: Any) -> None:
            sessions.append(settings)

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr(gui, "StreamingSession", Session)
    frame = gui.MainFrame()
    assert frame._source.GetSelection() == 2
    assert (
        "nieuruchomiony" if language == "pl" else "not running"
    ) in frame._device.GetStringSelection()
    frame._process_picker.startup_notice()
    assert ("Uruchom go" if language == "pl" else "Launch it") in dialogs[-1]
    for mode in (0, 1, 2):
        frame._source.SetSelection(mode)
        frame._on_source_changed(wx.CommandEvent())
        assert frame._process_picker.target == target
    frame._on_start(wx.CommandEvent())
    assert sessions[0].source == "process"
    assert sessions[0].process_target == target
    assert sessions[0].device_id == ""
    assert sessions[0].ui_language == language
    assert not frame._source.IsEnabled()
    frame._on_stop(wx.CommandEvent())
    assert frame._source.IsEnabled()
    frame._on_close(wx.CloseEvent())
    assert config_store.load_config()["process_target"] == target.to_config()
    assert config_store.load_config()["source"] == "process"
