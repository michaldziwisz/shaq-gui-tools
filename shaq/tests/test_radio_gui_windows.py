"""Sprawdza prawdziwe kontrolki wxPython bez wyświetlania okien i nagrywania dźwięku."""

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
    wx.Yield()


def _hidden_frame(module: Any, wx: Any, app: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    existing = {id(window) for window in wx.GetTopLevelWindows()}
    monkeypatch.setattr(wx, "App", lambda *_args, **_kwargs: app)
    monkeypatch.setattr(app, "MainLoop", lambda: None)
    module._main()
    return next(
        window
        for window in wx.GetTopLevelWindows()
        if id(window) not in existing and window.GetTitle() == module._APP_NAME
    )


@pytest.mark.parametrize("stop_monitor_first", [False, True])
def test_radio_is_silent_and_preview_is_independent(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stop_monitor_first: bool,
) -> None:
    from shaq import _gui, _radio_panel
    from shaq._radio_stream import RadioStatus

    wx, app, dialogs = gui_environment
    streams: list[Any] = []
    previews: list[Any] = []
    spoken: list[str] = []

    class Stream:
        def __init__(self, url: str, **callbacks: Any) -> None:
            self.url = url
            self.started = False
            self.stopped = False
            self.callbacks = callbacks
            streams.append(self)

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    class Preview:
        def __init__(self, volume: int, *, finished: Any, **_kwargs: Any) -> None:
            self.volume = volume
            self.finished = finished
            self.pcm = []
            previews.append(self)

        def start(self) -> None:
            pass

        def stop(self) -> None:
            self.finished("")

        def set_volume(self, volume: int) -> None:
            self.volume = volume

        def feed(self, pcm: bytes) -> None:
            self.pcm.append(pcm)

    monkeypatch.setattr(_radio_panel, "RadioStream", Stream)
    monkeypatch.setattr(_radio_panel, "RadioPreview", Preview)
    _gui._save_config(
        {"source": "radio", "radio": {"url": "http://radio.example/live", "preview_volume": 35}}
    )
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    assert isinstance(frame._radio.volume, wx.Slider)
    assert frame._radio.volume.GetValue() == 35
    assert frame._radio.panel.IsShown()
    assert not frame.device_choice.IsShown()
    assert not frame._advanced.announce_recognitions
    assert streams == previews == []
    frame._speakers = []
    frame._microphones = []
    frame.out_path.SetValue(str(tmp_path / "radio_history.txt"))
    work = []
    frame._worker_main = lambda *args: work.append(args)
    frame._on_start(wx.CommandEvent())
    frame._worker.join(2)
    assert wx.Window.FindFocus() == frame.log_list
    assert len(streams) == 1 and streams[0].started
    assert previews == []
    assert work[0][0] is streams[0]
    streams[0].callbacks["on_status"](RadioStatus("connected"))
    frame._on_timer(None)
    assert any("Nasłuch rozpoczęty" in text for text in spoken)
    frame._radio.preview_start.SetFocus()
    frame._radio._on_preview_start(None)
    assert wx.Window.FindFocus() == frame._radio.preview_stop
    assert len(streams) == len(previews) == 1
    frame._radio.volume.SetValue(0)
    frame._radio._on_volume(wx.CommandEvent())
    assert previews[0].volume == 0
    assert not streams[0].stopped
    streams[0].callbacks["on_audio"](b"audio")
    assert previews[0].pcm == [b"audio"]

    def stop_monitor() -> None:
        frame._on_stop(wx.CommandEvent())
        frame._events.put(("stopped", "Zatrzymano."))
        frame._on_timer(None)

    if stop_monitor_first:
        stop_monitor()
        assert not streams[0].stopped
        frame._radio._on_preview_stop(None)
        assert wx.Window.FindFocus() == frame._radio.preview_stop
        frame._on_timer(None)
    else:
        frame._radio._on_preview_stop(None)
        assert wx.Window.FindFocus() == frame._radio.preview_stop
        frame._on_timer(None)
        assert not streams[0].stopped
        assert not frame.start_btn.IsEnabled()
        stop_monitor()
    assert streams[0].stopped
    assert frame._radio.url.IsEnabled()
    assert frame._radio.preview_start.IsEnabled()
    assert wx.Window.FindFocus() == frame._radio.preview_start
    assert _gui._load_config()["radio"]["preview_volume"] == 0
    assert _gui._load_config()["source"] == "radio"
    assert not dialogs
    frame._on_close(wx.CloseEvent())
    frame.Destroy()
    wx.Yield()
    reopened = _hidden_frame(_gui, wx, app, monkeypatch)
    assert reopened.source_choice.GetSelection() == 3
    assert reopened._radio.volume.GetValue() == 0
    assert reopened._radio._source is None and reopened._radio._preview is None


@pytest.mark.parametrize("language", ["pl", "en"])
def test_radio_announces_connection_failures_once_and_recovers(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    language: str,
) -> None:
    from shaq import _gui
    from shaq._radio_stream import RadioStatus

    wx, app, _dialogs = gui_environment
    _gui._save_config({"source": "radio", "ui_language": language})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = []
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    panel = frame._radio
    panel._monitoring = True
    assert panel.preview_start.GetLabel() == (
        "Włącz odsłuch" if language == "pl" else "Start preview"
    )
    assert frame.source_choice.GetString(3) == (
        "Strumień radiowy (cichy nasłuch)"
        if language == "pl"
        else "Radio stream (silent monitoring)"
    )
    for status in (
        RadioStatus("connecting"),
        RadioStatus("failed", 2),
        RadioStatus("connecting"),
        RadioStatus("failed", 4),
        RadioStatus("connected"),
        RadioStatus("connected"),
        RadioStatus("failed", 2),
    ):
        panel._events.put(("status", panel._generation, status))
        panel.poll()
    assert len(spoken) == 3
    missing = "Brak połączenia" if language == "pl" else "connection is unavailable"
    restored = "przywrócone" if language == "pl" else "restored"
    monitoring = "Nasłuch" if language == "pl" else "Monitoring"
    assert missing in spoken[0]
    assert restored in spoken[1] and monitoring in spoken[1]
    assert missing in spoken[2]
    assert "2 s" in panel.connection.GetLabel()
    panel._events.put(("status", panel._generation - 1, RadioStatus("connected")))
    panel.poll()
    assert len(spoken) == 3
    panel.recognition_problem("Usługa niedostępna")
    panel.recognition_problem("Usługa niedostępna")
    assert spoken.count("Usługa niedostępna") == 1
    panel.recognition_succeeded()
    panel.recognition_problem("Usługa niedostępna")
    assert spoken.count("Usługa niedostępna") == 2


@pytest.mark.parametrize("move_to_results", [False, True])
def test_radio_delayed_preview_stop_preserves_keyboard_focus(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    move_to_results: bool,
) -> None:
    """Zatrzymanie nie przechodzi przez suwak ani nie odbiera później fokusu liście."""
    from shaq import _gui

    wx, app, _dialogs = gui_environment
    _gui._save_config({"source": "radio"})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    frame._announcer.speaker = SimpleNamespace(speak=lambda *_args: True)
    panel = frame._radio
    stopped = Mock()
    panel._preview = SimpleNamespace(stop=stopped)
    panel._sync_controls()
    panel.preview_stop.SetFocus()
    slider_focus = []

    def on_slider_focus(event: Any) -> None:
        slider_focus.append(True)
        event.Skip()

    panel.volume.Bind(wx.EVT_SET_FOCUS, on_slider_focus)
    panel._on_preview_stop(None)
    panel._on_preview_stop(None)
    stopped.assert_called_once()
    assert wx.Window.FindFocus() == panel.preview_stop
    if move_to_results:
        frame.log_list.SetFocus()
    panel._events.put(("preview_finished", panel._generation, ""))
    panel.poll()
    expected = frame.log_list if move_to_results else panel.preview_start
    assert wx.Window.FindFocus() == expected
    assert not slider_focus


@pytest.mark.parametrize("source", ["output", "input", "radio"])
def test_start_moves_focus_to_results_in_every_source(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    """Poprawny Start przechodzi na listę przed wyłączeniem przycisków ustawień."""
    from shaq import _gui

    wx, app, dialogs = gui_environment
    _gui._save_config({"source": source})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    frame._announcer.speaker = SimpleNamespace(speak=lambda *_args: True)
    monkeypatch.setattr(frame._radio, "stream", lambda: SimpleNamespace(start=lambda: None))
    frame._worker_main = lambda *_args: None
    frame.start_btn.SetFocus()
    frame._on_start(wx.CommandEvent())
    frame._worker.join(2)
    assert wx.Window.FindFocus() == frame.log_list
    assert frame.stop_btn.IsEnabled()
    assert not dialogs


@pytest.mark.parametrize("language", ["pl", "en"])
def test_radio_invalid_address_is_announced_without_starting_worker(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    language: str,
) -> None:
    from shaq import _gui

    wx, app, dialogs = gui_environment
    _gui._save_config({"source": "radio", "ui_language": language, "radio": {"url": "file:///bad"}})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = []
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    frame.start_btn.SetFocus()
    frame._on_start(wx.CommandEvent())
    assert frame._worker is None
    assert wx.Window.FindFocus() == frame.start_btn
    assert "HTTP" in dialogs[-1] and spoken[-1] == dialogs[-1]

    assert ("Podaj poprawny" if language == "pl" else "Enter a valid") in dialogs[-1]


def test_radio_import_selects_station_without_starting_audio(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from shaq import _gui

    wx, app, dialogs = gui_environment
    _gui._save_config({"source": "radio"})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = []
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    path = tmp_path / "stations.m3u"
    path.write_text(
        "#EXTM3U\n#EXTINF:-1,Pierwsza\nhttp://radio.example/1\n#EXTINF:-1,Druga\nhttp://radio.example/2\n",
        encoding="utf-8",
    )

    class Dialog:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> Dialog:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def ShowModal(self) -> int:
            return wx.ID_OK

        def GetPath(self) -> str:
            return str(path)

        def GetSelection(self) -> int:
            return 1

    monkeypatch.setattr(wx, "FileDialog", Dialog)
    monkeypatch.setattr(wx, "SingleChoiceDialog", Dialog)
    frame._radio._on_import(None)
    assert frame._radio.url.GetValue() == "http://radio.example/2"
    assert _gui._load_config()["radio"]["url"] == "http://radio.example/2"
    assert frame._radio._source is None and frame._radio._preview is None
    path.write_text("#EXTM3U\n", encoding="utf-8")
    frame._radio._on_import(None)
    assert frame._radio.url.GetValue() == "http://radio.example/2"
    assert "nie zawiera" in dialogs[-1]
    assert spoken[-1] == dialogs[-1]


@pytest.mark.parametrize(
    "saved,expected", [(None, False), (False, False), (True, True), ("true", False), (1, False)]
)
def test_announcement_option_defaults_to_off_and_requires_boolean(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    saved: Any,
    expected: bool,
) -> None:
    from shaq import _gui

    wx, app, _dialogs = gui_environment
    _gui._save_config({"advanced": {"announce_recognitions": saved}})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    assert frame._advanced.announce_recognitions is expected
    assert frame._collect_config()["advanced"]["announce_recognitions"] is expected


@pytest.mark.parametrize(
    "enabled,focused,active,expected",
    [
        (True, True, True, 1),
        (False, True, True, 0),
        (True, False, True, 0),
        (True, True, False, 0),
    ],
)
def test_recognition_speaks_only_on_active_list_and_keeps_selection(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    focused: bool,
    active: bool,
    expected: int,
) -> None:
    from shaq import _gui
    from shaq._announcements import RecognitionAnnouncer

    wx, app, _dialogs = gui_environment
    _gui._save_config({"advanced": {"announce_recognitions": enabled}})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    speaker = Mock()
    speaker.speak.return_value = True
    frame._announcer = RecognitionAnnouncer(speaker)
    monkeypatch.setattr(frame, "IsActive", lambda: active)
    monkeypatch.setattr(
        wx.Window, "FindFocus", lambda: frame.log_list if focused else frame.out_path
    )
    frame.log_list.Append("Starszy wynik")
    frame.log_list.SetSelection(0)
    frame._events.put(("track", "Wykonawca - Utwór"))
    for _repeat in range(3):
        frame._events.put(("recognition", "Wykonawca - Utwór"))
    frame._on_timer(None)
    assert frame.log_list.GetCount() == 2
    assert frame.log_list.GetSelection() == 0
    assert speaker.speak.call_count == expected
    if expected:
        assert speaker.speak.call_args.args == (
            "Wykonawca - Utwór",
            int(frame.log_list.GetHandle()),
        )


@pytest.mark.parametrize("accept", [False, True])
def test_advanced_dialog_tests_speech_and_saves_only_on_ok(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    accept: bool,
) -> None:
    from shaq import _gui

    wx, app, _dialogs = gui_environment
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    speaker = Mock()
    speaker.speak.return_value = True
    frame._announcer.speaker = speaker
    monkeypatch.setattr(wx, "CallLater", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(wx.Dialog, "EndModal", lambda *_args: None)

    def inspect_dialog(dialog: Any) -> int:
        assert dialog.GetClientSize().height >= dialog.GetSizer().GetMinSize().height
        controls: list[Any] = []
        pending = list(dialog.GetChildren())
        while pending:
            control = pending.pop()
            controls.append(control)
            pending.extend(control.GetChildren())
        checkbox = next(control for control in controls if isinstance(control, wx.CheckBox))
        assert not checkbox.GetValue()
        assert checkbox.GetName() == checkbox.GetLabel()
        checkbox.SetValue(True)
        test_button = next(
            control
            for control in controls
            if isinstance(control, wx.Button)
            and control.GetLabel() in ("Testuj odczyt", "Test announcement")
        )
        test_button.GetEventHandler().ProcessEvent(
            wx.CommandEvent(wx.EVT_BUTTON.typeId, test_button.GetId())
        )
        assert speaker.speak.call_count == 1
        assert not frame._advanced.announce_recognitions
        result = wx.ID_OK if accept else wx.ID_CANCEL
        button = next(
            control
            for control in controls
            if isinstance(control, wx.Button) and control.GetId() == result
        )
        button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId, result))
        return result

    monkeypatch.setattr(wx.Dialog, "ShowModal", inspect_dialog)
    frame._on_advanced(None)
    assert frame._advanced.announce_recognitions is accept
    restarted = _hidden_frame(_gui, wx, app, monkeypatch)
    assert restarted._advanced.announce_recognitions is accept


@pytest.mark.skipif(
    os.environ.get("SHAQ_TEST_UIA") != "1", reason="Wymaga jawnego włączenia powiadomień Windows."
)
def test_native_uia_notification_accepts_wx_list_and_rejects_dead_window(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shaq import _gui
    from shaq._uia_notifications import notify

    wx, app, _dialogs = gui_environment
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    assert notify(int(frame.log_list.GetHandle()), "Test powiadomienia: wykonawca, tytuł.")
    assert not notify(0x7FFFFFFF, "Test nieistniejącego okna")


def test_recognition_problem_uses_event_kind_instead_of_message_prefix(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dowolna treść komunikatu nie zmienia rodzaju zdarzenia rozpoznawania."""
    from shaq import _gui

    wx, app, _dialogs = gui_environment
    _gui._save_config({"source": "radio", "ui_language": "en"})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken: list[str] = []
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    frame._events.put(("status", "Rozpoznawanie nieudane"))
    frame._on_timer(None)
    assert spoken == []
    frame._events.put(("recognition_failed", "Dowolny komunikat A"))
    frame._events.put(("recognition_failed", "Dowolny komunikat B"))
    frame._on_timer(None)
    assert spoken == ["Dowolny komunikat A"]
    frame._events.put(("radio_recognition_ok", ""))
    frame._events.put(("recognition_failed", "Dowolny komunikat C"))
    frame._on_timer(None)
    assert spoken == ["Dowolny komunikat A", "Dowolny komunikat C"]


@pytest.mark.parametrize("language", ["pl", "en"])
@pytest.mark.parametrize("speaker_available", [False, True])
def test_history_warning_survives_status_updates_until_successful_save(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    speaker_available: bool,
) -> None:
    """Błąd jest dostępny mimo kolejnych statusów i ogłaszany raz na serię niepowodzeń."""
    from shaq import _gui

    wx, app, dialogs = gui_environment
    _gui._save_config({"ui_language": language, "advanced": {"announce_recognitions": False}})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = Mock(return_value=speaker_available)
    has_speaker = hasattr(frame, "_announcer")
    if has_speaker:
        frame._announcer.speaker = SimpleNamespace(speak=spoken)
    frame.log_list.Append("Starszy wynik")
    frame.log_list.SetSelection(0)
    frame.out_path.SetFocus()
    initial_focus = wx.Window.FindFocus()
    error = "Brak miejsca na dysku." if language == "pl" else "The disk is full."
    for kind, payload in (
        ("write_warning", error),
        ("status", "Nasłuchuję"),
        ("status", "Rozpoznaję"),
        ("write_warning", error),
    ):
        frame._events.put((kind, payload))
    frame._on_timer(None)
    assert error in frame.history_status.GetValue()
    assert frame.history_status.IsShown()
    assert frame.history_status.GetName() == (
        "Stan zapisu historii:" if language == "pl" else "History saving status:"
    )
    assert not frame.history_status.IsEditable()
    assert ("Nasłuch trwa" if language == "pl" else "Monitoring continues") in (
        frame.history_status.GetValue()
    )
    assert not frame._stop_event.is_set()
    assert frame.log_list.GetSelection() == 0
    assert wx.Window.FindFocus() == initial_focus
    assert spoken.call_count == int(has_speaker)
    assert len(dialogs) == int(not has_speaker or not speaker_available)
    if has_speaker:
        assert spoken.call_args.args[0] == frame.history_status.GetValue()

    for _ in range(3):
        frame._events.put(("status", "Zapisano rozpoznanie"))
        frame._events.put(("write_warning", error))
        frame._on_timer(None)
    frame.SetStatusText("Dowolny status urządzenia lub radia")
    assert error in frame.history_status.GetValue()
    assert spoken.call_count == int(has_speaker)
    assert len(dialogs) == int(not has_speaker or not speaker_available)

    frame._events.put(("track", "Nowy zapisany utwór"))
    frame._on_timer(None)
    assert not frame._history_write_error
    assert ("ponownie działa" if language == "pl" else "working again") in (
        frame.history_status.GetValue()
    )
    frame._events.put(("write_warning", error))
    frame._on_timer(None)
    assert error in frame.history_status.GetValue()
    assert spoken.call_count == 2 * int(has_speaker)
    assert len(dialogs) == 2 * int(not has_speaker or not speaker_available)


def test_history_warning_keeps_worker_running_and_duplicate_does_not_clear_it(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Po błędzie zapisu znany utwór nie kasuje alarmu, a kolejny udany zapis go usuwa."""
    import wave
    from io import BytesIO

    from shazamio import Serialize, Shazam

    from shaq import _gui

    wx, app, dialogs = gui_environment
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = Mock(return_value=True)
    if hasattr(frame, "_announcer"):
        frame._announcer.speaker = SimpleNamespace(speak=spoken)
    history = tmp_path / "historia-test.txt"
    history.write_text("Autor - Znany\n", encoding="utf-8")
    titles = ["Nowy", "Znany", "Nowy"]
    recognized: list[str] = []
    saved_states: list[str] = []
    with BytesIO() as buffer:
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x10" * 240000)
        audio = buffer.getvalue()

    def record(*_args: Any, **_kwargs: Any) -> bytes:
        frame._on_timer(None)
        saved_states.append(frame._history_write_error)
        if len(recognized) == len(titles):
            frame._stop_event.set()
        return audio

    async def recognize(_self: Any, _audio: bytes) -> dict[str, str]:
        title = titles[len(recognized)]
        recognized.append(title)
        return {"title": title}

    append = _gui._HistoryWriter.append_unique
    attempts = []

    def save(writer: Any, line: str) -> bool:
        attempts.append(line)
        if len(attempts) == 1:
            raise OSError("Brak miejsca na dysku")
        return append(writer, line)

    monkeypatch.setattr(_gui, "_record_wav", record)
    monkeypatch.setattr(_gui._HistoryWriter, "append_unique", save)
    monkeypatch.setattr(Shazam, "__init__", lambda self, **kwargs: None)
    monkeypatch.setattr(Shazam, "recognize", recognize)
    monkeypatch.setattr(
        Serialize,
        "full_track",
        lambda raw: SimpleNamespace(
            matches=[True],
            track=SimpleNamespace(subtitle="Autor", title=raw["title"]),
        ),
    )
    frame._worker_main(
        _gui._AudioDevice("Test", "test", "output"),
        history,
        "en-US",
        "US",
        _gui._default_advanced_settings(),
    )
    assert recognized == titles
    assert saved_states[0] == saved_states[-1] == ""
    assert saved_states[1] and saved_states[2] == saved_states[1]
    assert frame.log_list.GetStrings() == ["Autor - Nowy"]
    assert history.read_text(encoding="utf-8").splitlines() == ["Autor - Znany", "Autor - Nowy"]
    assert len(dialogs) + spoken.call_count == 1
