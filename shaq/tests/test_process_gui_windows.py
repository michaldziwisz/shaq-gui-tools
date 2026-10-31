"""Sprawdza prawdziwe kontrolki wxPython bez wyświetlania okien i nagrywania dźwięku."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import wave
from collections.abc import Iterator
from io import BytesIO
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
    app.ProcessPendingEvents()


def test_live_gui_preserves_program_across_source_switches_and_restart(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from shaq import _gui, _process_picker
    from shaq._process_audio import ProcessTarget

    wx, app, dialogs = gui_environment
    target = ProcessTarget(r"C:\Programy\winamp.exe")
    _gui._save_config({"source": "process", "process_target": target.to_config()})
    monkeypatch.setattr(_process_picker, "list_processes", lambda: [])
    monkeypatch.setattr(_process_picker, "require_process_capture", lambda: None)
    monkeypatch.setattr(wx, "App", lambda *_a, **_k: app)

    def inspect_frame() -> None:
        frame = next(window for window in wx.GetTopLevelWindows() if window.GetTitle() == "shaqgui")
        assert frame.source_choice.GetCount() == 4
        assert frame.source_choice.GetSelection() == 2
        assert "nieuruchomiony" in frame.device_choice.GetStringSelection()
        frame._process_picker.startup_notice()
        assert "Uruchom go" in dialogs[-1]
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

    monkeypatch.setattr(app, "MainLoop", inspect_frame)
    _gui._main()
    # Drugie otwarcie korzysta wyłącznie z konfiguracji zapisanej przez pierwsze okno.
    _gui._main()


def test_cast_gui_passes_saved_program_to_session(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "shaqcast"))
    from shaqcast import _process_picker, config_store, gui
    from shaqcast._process_audio import ProcessTarget

    wx, _app, dialogs = gui_environment
    target = ProcessTarget(r"C:\Programy\winamp.exe")
    config_store.save_config({"source": "process", "process_target": target.to_config()})
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
    assert "nieuruchomiony" in frame._device.GetStringSelection()
    frame._process_picker.startup_notice()
    assert "Uruchom go" in dialogs[-1]
    for mode in (0, 1, 2):
        frame._source.SetSelection(mode)
        frame._on_source_changed(wx.CommandEvent())
        assert frame._process_picker.target == target
    frame._on_start(wx.CommandEvent())
    assert sessions[0].source == "process"
    assert sessions[0].process_target == target
    assert sessions[0].device_id == ""
    assert not frame._source.IsEnabled()
    frame._on_stop(wx.CommandEvent())
    assert frame._source.IsEnabled()
    frame._on_close(wx.CloseEvent())
    assert config_store.load_config()["process_target"] == target.to_config()
    assert config_store.load_config()["source"] == "process"


def _test_wav(seconds: int = 15) -> bytes:
    """Tworzy próbkę PCM do sprawdzania podziału nagrania bez sprzętu audio."""
    with BytesIO() as buffer:
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x10" * (16000 * seconds))
        return buffer.getvalue()


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
    gui_environment: tuple[Any, Any, list[str]], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, stop_monitor_first: bool,
) -> None:
    from shaq import _gui, _radio_panel

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
        def __init__(self, volume: int, *, finished: Any) -> None:
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
    _gui._save_config({"source": "radio", "radio": {"url": "http://radio.example/live", "preview_volume": 35}})
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
    streams[0].callbacks["on_status"]("Połączono. Odbieram dźwięk radia.")
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
    reopened = _hidden_frame(_gui, wx, app, monkeypatch)
    assert reopened.source_choice.GetSelection() == 3
    assert reopened._radio.volume.GetValue() == 0
    assert reopened._radio._source is None and reopened._radio._preview is None


def test_radio_announces_connection_failures_once_and_recovers(
    gui_environment: tuple[Any, Any, list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shaq import _gui

    wx, app, _dialogs = gui_environment
    _gui._save_config({"source": "radio"})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = []
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    panel = frame._radio
    panel._monitoring = True
    for message in (
        "Łączenie ze strumieniem radia…", "Brak transmisji radia. Próba za 2 s.",
        "Łączenie ze strumieniem radia…", "Brak transmisji radia. Próba za 4 s.",
        "Połączono. Odbieram dźwięk radia.", "Połączono. Odbieram dźwięk radia.",
        "Brak transmisji radia. Próba za 2 s.",
    ):
        panel._events.put(("status", panel._generation, message))
        panel.poll()
    assert len(spoken) == 3
    assert "Brak połączenia" in spoken[0]
    assert "przywrócone" in spoken[1] and "Nasłuch" in spoken[1]
    assert "Brak połączenia" in spoken[2]
    panel._events.put(("status", panel._generation - 1, "Połączono."))
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


@pytest.mark.parametrize("source", ["output", "input", "process", "radio"])
def test_start_moves_focus_to_results_in_every_source(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    """Poprawny Start przechodzi na listę przed wyłączeniem przycisków ustawień."""
    from shaq import _gui
    from shaq._process_audio import ProcessTarget

    wx, app, dialogs = gui_environment
    _gui._save_config({"source": source})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    frame._announcer.speaker = SimpleNamespace(speak=lambda *_args: True)
    monkeypatch.setattr(
        frame._process_picker, "selected", lambda: ProcessTarget(r"C:\Programy\winamp.exe")
    )
    monkeypatch.setattr(frame._radio, "stream", lambda: SimpleNamespace(start=lambda: None))
    frame._worker_main = lambda *_args: None
    frame.start_btn.SetFocus()
    frame._on_start(wx.CommandEvent())
    frame._worker.join(2)
    assert wx.Window.FindFocus() == frame.log_list
    assert frame.stop_btn.IsEnabled()
    assert not dialogs


def test_radio_invalid_address_is_announced_without_starting_worker(
    gui_environment: tuple[Any, Any, list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shaq import _gui

    wx, app, dialogs = gui_environment
    _gui._save_config({"source": "radio", "radio": {"url": "file:///bad"}})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = []
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    frame.start_btn.SetFocus()
    frame._on_start(wx.CommandEvent())
    assert frame._worker is None
    assert wx.Window.FindFocus() == frame.start_btn
    assert "HTTP" in dialogs[-1] and spoken[-1] == dialogs[-1]


def test_radio_recognition_keeps_existing_history_and_uses_normal_signature(
    gui_environment: tuple[Any, Any, list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from shazamio import Serialize
    from shaq import _gui, _radio_stream

    wx, app, _dialogs = gui_environment
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    monkeypatch.setattr(_radio_stream, "radio_ffmpeg", lambda: "test.exe")
    stream = _radio_stream.RadioStream("http://radio.example/live", on_status=lambda _m: None)
    recognized = []

    def read(**_kwargs: Any) -> bytes | None:
        if recognized:
            frame._stop_event.set()
            return None
        return _test_wav()

    async def recognize(audio: bytes) -> dict[str, Any]:
        with wave.open(BytesIO(audio), "rb") as sample:
            assert sample.getnframes() / sample.getframerate() == 12
        recognized.append(audio)
        return {"matches": [{}]}

    stream.read_wav = read
    monkeypatch.setattr(_gui, "create_recognizer", lambda **_kwargs: SimpleNamespace(recognize=recognize))
    monkeypatch.setattr(Serialize, "full_track", lambda _raw: SimpleNamespace(matches=[True], track=SimpleNamespace(subtitle="Radio", title="Utwór")))
    history = tmp_path / "radio.txt"
    frame._worker_main(stream, history, "en-US", "US", _gui._default_advanced_settings())
    assert history.read_text(encoding="utf-8") == "Radio - Utwór\n"
    assert ("track", "Radio - Utwór") in list(frame._events.queue)


def test_radio_import_selects_station_without_starting_audio(
    gui_environment: tuple[Any, Any, list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from shaq import _gui

    wx, app, dialogs = gui_environment
    _gui._save_config({"source": "radio"})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    spoken = []
    frame._announcer.speaker = SimpleNamespace(speak=lambda text, _hwnd: spoken.append(text))
    path = tmp_path / "stations.m3u"
    path.write_text("#EXTM3U\n#EXTINF:-1,Pierwsza\nhttp://radio.example/1\n#EXTINF:-1,Druga\nhttp://radio.example/2\n", encoding="utf-8")

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


@pytest.mark.parametrize("source", ["output", "input", "process"])
def test_live_recognition_reports_existing_history_in_every_source(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
) -> None:
    from shazamio import Serialize

    from shaq import _gui
    from shaq._process_audio import ProcessTarget

    wx, app, _dialogs = gui_environment
    _gui._save_config({"advanced": {"segment_seconds": 60}})
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    assert frame._advanced.segment_seconds == 12
    line = "Wykonawca - Utwór"
    history = tmp_path / "history.txt"
    history.write_text(line + "\n", encoding="utf-8")
    recognized: list[bytes] = []

    def record(*_args: Any, **_kwargs: Any) -> bytes | None:
        if len(recognized) == 2:
            frame._stop_event.set()
            return None
        return _test_wav()

    async def recognize(audio: bytes) -> dict[str, Any]:
        recognized.append(audio)
        with wave.open(BytesIO(audio), "rb") as sample:
            assert sample.getnframes() == 12 * 16000
        return {"matches": [{}]}

    def factory(**kwargs: Any) -> Any:
        assert kwargs["segment_duration_seconds"] == 12
        return SimpleNamespace(recognize=recognize)

    monkeypatch.setattr(_gui, "create_recognizer", factory)
    monkeypatch.setattr(_gui, "_record_wav", record)
    monkeypatch.setattr(_gui, "record_process_wav", record)
    monkeypatch.setattr(
        Serialize,
        "full_track",
        lambda _raw: SimpleNamespace(
            matches=[True], track=SimpleNamespace(subtitle="Wykonawca", title="Utwór")
        ),
    )
    device = (
        ProcessTarget(r"C:\Programy\winamp.exe")
        if source == "process"
        else _gui._AudioDevice("Test", "test", source)
    )
    advanced = _gui._AdvancedSettings(15, 60, 2, 1, -55)
    frame._worker_main(device, history, "en-US", "US", advanced)
    events = list(frame._events.queue)
    assert [payload for kind, payload in events if kind == "track"] == [line, line]
    assert any("Ostatnie rozpoznanie" in payload for kind, payload in events if kind == "status")
    assert not any(kind == "error" for kind, _payload in events)
    frame._on_timer(None)
    assert frame.log_list.GetCount() == 1
    assert frame.log_list.GetString(0) == line
    assert history.read_text(encoding="utf-8") == line + "\n"


def test_live_stop_cancels_recognition_without_error_dialog(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from shaq import _gui

    wx, app, dialogs = gui_environment
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    released = threading.Event()

    async def recognize(_audio: bytes) -> None:
        try:
            asyncio.get_running_loop().call_later(0.1, frame._stop_event.set)
            await asyncio.sleep(60)
        finally:
            released.set()

    monkeypatch.setattr(
        _gui, "create_recognizer", lambda **_kwargs: SimpleNamespace(recognize=recognize)
    )
    monkeypatch.setattr(_gui, "_record_wav", lambda *_args, **_kwargs: _test_wav())
    started = time.monotonic()
    frame._worker_main(
        _gui._AudioDevice("Test", "test", "output"),
        tmp_path / "history.txt",
        "en-US",
        "US",
        _gui._default_advanced_settings(),
    )
    assert time.monotonic() - started < 2
    assert released.is_set()
    frame._on_timer(None)
    assert not dialogs


@pytest.mark.parametrize("stop_during_pause", [False, True])
def test_file_scan_rate_limit_is_finite_and_pause_can_be_stopped(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stop_during_pause: bool,
) -> None:
    from shazamio import Shazam

    from shaq import _file_gui
    from shaq._recognition import RecognitionError

    wx, app, _dialogs = gui_environment
    frame = _hidden_frame(_file_gui, wx, app, monkeypatch)
    calls: list[int] = []
    timers: list[threading.Timer] = []
    duration = 60 if stop_during_pause else 1
    monkeypatch.setattr(_file_gui, "probe_duration_seconds", lambda _path: duration)
    monkeypatch.setattr(_file_gui, "extract_wav_segment", lambda *_args, **_kwargs: _test_wav())

    async def signature(*, value: bytes) -> Any:
        with wave.open(BytesIO(value), "rb") as sample:
            assert sample.getnframes() == 12 * 16000
        return SimpleNamespace(
            signature=SimpleNamespace(uri="data:audio/vnd.shazam.sig;base64,AAAA", samples=192000),
            timestamp=1,
        )

    def init_shazam(self: Any, **kwargs: Any) -> None:
        assert kwargs["segment_duration_seconds"] == 12
        self.language = kwargs["language"]
        self.endpoint_country = kwargs["endpoint_country"]
        self.http_client = kwargs["http_client"]
        self.core_recognizer = SimpleNamespace(recognize_bytes=signature)

    async def request(client: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(1)
        if stop_during_pause:
            timer = threading.Timer(0.1, frame._stop_event.set)
            timers.append(timer)
            timer.start()
            return {"matches": []}
        client.last_status = 429
        client.last_headers = {"Retry-After": "300"}
        client.attempts = [(1, 429)]
        raise RecognitionError("Shazam zwrócił HTTP 429.", status=429, retry_after_s=300)

    monkeypatch.setattr(Shazam, "__init__", init_shazam)
    monkeypatch.setattr(_file_gui.RecognitionHTTPClient, "request", request)
    advanced = _file_gui._AdvancedSettings(
        workers=1, sig_duration_s=60, min_api_interval_s=30, max_windows_per_sample=1
    )
    output = tmp_path / "wyniki.txt"
    started = time.monotonic()
    try:
        frame._scan_one_file(
            input_path=tmp_path / "test.wav",
            output_file=output,
            interval_s=30,
            language="en-US",
            endpoint_country="US",
            advanced=advanced,
            file_index=1,
            file_total=1,
        )
        assert time.monotonic() - started < 2
        assert len(calls) == 1
        assert output.read_text(encoding="utf-8") == ""
        events = list(frame._events.queue)
        if stop_during_pause:
            assert frame._stop_event.is_set()
        else:
            progress = [payload for kind, payload in events if kind == "progress"][-1]
            assert progress["errors"] == 1
            assert progress["rate_limits"] == 1
            assert progress["nomatch"] == 0
    finally:
        for timer in timers:
            timer.cancel()


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
    for _repeat in range(3):
        frame._events.put(("track", "Wykonawca - Utwór"))
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
