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
    wx.Yield()


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


@pytest.mark.parametrize("source", ["output", "input"])
@pytest.mark.parametrize("language", ["pl", "en"])
def test_live_recognition_reports_existing_history_in_every_source(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    language: str,
) -> None:
    from shazamio import Serialize

    from shaq import _gui

    wx, app, _dialogs = gui_environment
    _gui._save_config({"advanced": {"segment_seconds": 60}, "ui_language": language})
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
    monkeypatch.setattr(
        Serialize,
        "full_track",
        lambda _raw: SimpleNamespace(
            matches=[True], track=SimpleNamespace(subtitle="Wykonawca", title="Utwór")
        ),
    )
    device = _gui._AudioDevice("Test", "test", source)
    advanced = _gui._AdvancedSettings(15, 60, 2, 1, -55)
    frame._worker_main(device, history, "en-US", "US", advanced)
    events = list(frame._events.queue)
    assert [payload for kind, payload in events if kind == "track"] == []
    label = "Ostatnie rozpoznanie" if language == "pl" else "Last recognition"
    assert any(label in payload for kind, payload in events if kind == "status")
    assert not any(kind == "error" for kind, _payload in events)
    frame._on_timer(None)
    assert frame.log_list.GetCount() == 0
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


def test_write_failure_keeps_monitoring_and_list_contains_only_saved_unique_tracks(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Awaria zapisu nie kończy nasłuchu ani nie dodaje fałszywie zapisanego wyniku."""
    from shazamio import Serialize

    from shaq import _gui

    wx, app, dialogs = gui_environment
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    titles = ["Pierwszy", "Drugi", "Pierwszy", "Drugi"]
    frame._announcer.speaker = SimpleNamespace(speak=Mock(return_value=False))
    recognized = []
    writes = []
    original = _gui._HistoryWriter.append_unique

    def record(*_args: Any, **_kwargs: Any) -> bytes:
        if len(recognized) == len(titles):
            frame._stop_event.set()
        return _test_wav()

    async def recognize(_audio: bytes) -> dict[str, Any]:
        title = titles[len(recognized)]
        recognized.append(title)
        return {"title": title}

    def append(writer: Any, line: str) -> bool:
        writes.append(line)
        if len(writes) == 1:
            raise OSError("Brak miejsca")
        return original(writer, line)

    monkeypatch.setattr(_gui, "_record_wav", record)
    monkeypatch.setattr(
        _gui, "create_recognizer", lambda **_kwargs: SimpleNamespace(recognize=recognize)
    )
    monkeypatch.setattr(_gui._HistoryWriter, "append_unique", append)
    monkeypatch.setattr(
        Serialize,
        "full_track",
        lambda raw: SimpleNamespace(
            matches=[True], track=SimpleNamespace(subtitle="Wykonawca", title=raw["title"])
        ),
    )
    history = tmp_path / "history.txt"
    frame._worker_main(
        _gui._AudioDevice("Test", "test", "output"),
        history,
        "en-US",
        "US",
        _gui._default_advanced_settings(),
    )
    events = list(frame._events.queue)
    assert recognized == titles
    assert sum(kind == "write_warning" for kind, _payload in events) == 1
    assert not any(kind == "error" for kind, _payload in events)
    frame._on_timer(None)
    assert frame.log_list.GetStrings() == ["Wykonawca - Drugi", "Wykonawca - Pierwszy"]
    assert history.read_text(encoding="utf-8").splitlines() == frame.log_list.GetStrings()
    assert len(dialogs) == 1
    assert frame.history_status.GetValue() in _gui._STRINGS["history.restored"].values()


@pytest.mark.parametrize("known_duration", [True, False])
@pytest.mark.parametrize("first_window_misses", [False, True])
@pytest.mark.parametrize("request_timeout", [10, 60, 600])
@pytest.mark.parametrize(
    "statuses", [(429, 200), (429, 429, 200), (503, 503, 503, 503, 503, 200), (503,) * 6, (400,)]
)
def test_file_scan_retries_exact_window_without_skipping_or_duplicate_progress(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    known_duration: bool,
    first_window_misses: bool,
    request_timeout: int,
    statuses: tuple[int, ...],
) -> None:
    """Wznawia te same bajty po limicie, także gdy długość pliku jest nieznana."""
    from shazamio import Serialize, Shazam

    from shaq import _file_gui
    from shaq._recognition import RecognitionError

    wx, app, _dialogs = gui_environment
    _file_gui._save_config({"ui_language": "en"})
    frame = _hidden_frame(_file_gui, wx, app, monkeypatch)
    requests = []
    decoded_offsets = []
    clock = [100.0]
    sliced_windows = []
    operation_timeouts = []
    responses = (200, *statuses) if first_window_misses else statuses
    run_interruptible = _file_gui.run_interruptible

    def run_with_timeout(*args: Any, **kwargs: Any) -> Any:
        operation_timeouts.append(kwargs["timeout_s"])
        return run_interruptible(*args, **kwargs)

    monkeypatch.setattr(_file_gui, "run_interruptible", run_with_timeout)
    assert _file_gui._AdvancedSettings().recognize_timeout_s == 60

    class ControlledStop:
        """Przyspiesza wyłącznie pauzy skanera, bez zmiany zegara asyncio."""

        def is_set(self) -> bool:
            return False

        def wait(self, seconds: float = 0) -> bool:
            clock[0] += seconds + 0.001
            return False

    frame._stop_event = ControlledStop()
    monkeypatch.setattr(_file_gui, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(
        _file_gui, "probe_duration_seconds", lambda _path: 1 if known_duration else None
    )

    def extract(_path: Path, *, start_s: int, duration_s: int) -> bytes | None:
        decoded_offsets.append(start_s)
        return _test_wav() if start_s == 0 else None

    async def signature(*, value: bytes) -> Any:
        return SimpleNamespace(
            signature=SimpleNamespace(uri=value.hex(), samples=192000), timestamp=1
        )

    def init_shazam(self: Any, **kwargs: Any) -> None:
        self.language = kwargs["language"]
        self.endpoint_country = kwargs["endpoint_country"]
        self.http_client = kwargs["http_client"]
        self.core_recognizer = SimpleNamespace(recognize_bytes=signature)

    async def request(client: Any, *_args: Any, **kwargs: Any) -> dict[str, Any]:
        assert client.timeout_s == request_timeout
        status = responses[len(requests)]
        requests.append((kwargs["json"], clock[0]))
        client.last_status = status
        client.last_headers = {"Retry-After": "12"} if status == 429 else {}
        client.attempts = [(1, status)]
        if status != 200:
            message = "Limit usługi" if status == 429 else "Wcześniejszy błąd HTTP 429"
            raise RecognitionError(message, status=status)
        return {"miss": first_window_misses and len(requests) == 1}

    def window(_audio: bytes, *, start_s: int, duration_s: int) -> bytes:
        sliced_windows.append(start_s)
        return str(start_s).encode("ascii")

    monkeypatch.setattr(_file_gui, "extract_wav_segment", extract)
    monkeypatch.setattr(_file_gui, "slice_wav_bytes", window)
    monkeypatch.setattr(Shazam, "__init__", init_shazam)
    monkeypatch.setattr(_file_gui.RecognitionHTTPClient, "request", request)
    monkeypatch.setattr(
        Serialize,
        "full_track",
        lambda raw: SimpleNamespace(
            track=None if raw["miss"] else SimpleNamespace(subtitle="Wykonawca", title="Utwór")
        ),
    )
    output = tmp_path / "wyniki.txt"
    frame._scan_one_file(
        input_path=tmp_path / "test.wav",
        output_file=output,
        interval_s=30,
        language="en-US",
        endpoint_country="US",
        file_index=1,
        file_total=1,
        advanced=_file_gui._AdvancedSettings(
            workers=1,
            sig_duration_s=12,
            min_api_interval_s=0,
            max_windows_per_sample=2 if first_window_misses else 1,
            recognize_timeout_s=request_timeout,
        ),
    )
    assert operation_timeouts and set(operation_timeouts) == {request_timeout}
    assert len(requests) == len(responses)
    signatures = [payload["signature"] for payload, _timestamp in requests]
    if first_window_misses:
        assert signatures.pop(0) != signatures[0]
    assert all(signature == signatures[0] for signature in signatures)
    assert len(sliced_windows) == (2 if first_window_misses else 1)
    for index, status in enumerate(responses[:-1]):
        if status == 429:
            assert requests[index + 1][1] - requests[index][1] >= 12
        elif status == 503:
            attempt = index + 1 - int(first_window_misses)
            assert requests[index + 1][1] - requests[index][1] >= min(2**attempt, 60)
    assert decoded_offsets.count(0) == 1
    progress = [
        payload for kind, payload in frame._events.queue if kind == "progress" and "done" in payload
    ]
    assert [item["done"] for item in progress] == [1]
    assert progress[-1]["rate_limits"] == statuses.count(429)
    assert progress[-1]["errors"] == int(statuses[-1] != 200)
    assert progress[-1]["nomatch"] == 0
    assert ("Wykonawca - Utwór" in output.read_text(encoding="utf-8")) == (statuses[-1] == 200)


@pytest.mark.parametrize("known_duration", [True, False])
def test_file_scan_stop_interrupts_rate_limit_without_counting_sample_done(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    known_duration: bool,
) -> None:
    """Stop podczas Retry-After kończy pracę i nie oznacza odłożonego okna jako gotowego."""
    from shazamio import Shazam

    from shaq import _file_gui
    from shaq._recognition import RecognitionError

    wx, app, _dialogs = gui_environment
    frame = _hidden_frame(_file_gui, wx, app, monkeypatch)
    monkeypatch.setattr(
        _file_gui, "probe_duration_seconds", lambda _path: 1 if known_duration else None
    )
    monkeypatch.setattr(_file_gui, "extract_wav_segment", lambda *_args, **_kwargs: _test_wav())
    calls = []
    timers = []

    async def signature(*, value: bytes) -> Any:
        return SimpleNamespace(signature=SimpleNamespace(uri="test", samples=192000), timestamp=1)

    def init_shazam(self: Any, **kwargs: Any) -> None:
        self.language = kwargs["language"]
        self.endpoint_country = kwargs["endpoint_country"]
        self.http_client = kwargs["http_client"]
        self.core_recognizer = SimpleNamespace(recognize_bytes=signature)

    async def request(client: Any, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(True)
        client.last_status = 429
        client.last_headers = {"Retry-After": "300"}
        client.attempts = [(1, 429)]
        timer = threading.Timer(0.1, frame._stop_event.set)
        timers.append(timer)
        timer.start()
        raise RecognitionError("HTTP 429", status=429)

    monkeypatch.setattr(Shazam, "__init__", init_shazam)
    monkeypatch.setattr(_file_gui.RecognitionHTTPClient, "request", request)
    started = time.monotonic()
    try:
        frame._scan_one_file(
            input_path=tmp_path / "test.wav",
            output_file=tmp_path / "wyniki.txt",
            interval_s=30,
            language="en-US",
            endpoint_country="US",
            file_index=1,
            file_total=1,
            advanced=_file_gui._AdvancedSettings(workers=1, min_api_interval_s=0),
        )
        assert time.monotonic() - started < 2
        assert len(calls) == 1
        assert frame._stop_event.is_set()
        assert not any(
            payload.get("done", 0) for kind, payload in frame._events.queue if kind == "progress"
        )
    finally:
        for timer in timers:
            timer.cancel()


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


@pytest.mark.parametrize("timeout", [10, 600])
def test_file_stop_cancels_pending_http_with_configured_timeout(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    timeout: int,
) -> None:
    """Stop anuluje trwające zapytanie, także przy maksymalnym limicie ustawień."""
    from shazamio import Shazam

    from shaq import _file_gui

    wx, app, dialogs = gui_environment
    frame = _hidden_frame(_file_gui, wx, app, monkeypatch)
    released = threading.Event()
    monkeypatch.setattr(_file_gui, "probe_duration_seconds", lambda _path: 1)
    monkeypatch.setattr(_file_gui, "extract_wav_segment", lambda *_a, **_k: _test_wav())

    async def signature(*, value: bytes) -> Any:
        return SimpleNamespace(signature=SimpleNamespace(uri="test", samples=192000), timestamp=1)

    def init_shazam(self: Any, **kwargs: Any) -> None:
        self.language = kwargs["language"]
        self.endpoint_country = kwargs["endpoint_country"]
        self.http_client = kwargs["http_client"]
        self.core_recognizer = SimpleNamespace(recognize_bytes=signature)

    async def request(client: Any, *_args: Any, **_kwargs: Any) -> None:
        assert client.timeout_s == timeout
        try:
            asyncio.get_running_loop().call_later(0.1, frame._stop_event.set)
            await asyncio.sleep(600)
        finally:
            released.set()

    monkeypatch.setattr(Shazam, "__init__", init_shazam)
    monkeypatch.setattr(_file_gui.RecognitionHTTPClient, "request", request)
    started = time.monotonic()
    frame._scan_one_file(
        input_path=tmp_path / "test.wav",
        output_file=tmp_path / "wyniki.txt",
        interval_s=30,
        language="en-US",
        endpoint_country="US",
        file_index=1,
        file_total=1,
        advanced=_file_gui._AdvancedSettings(
            workers=1, min_api_interval_s=0, recognize_timeout_s=timeout
        ),
    )
    assert time.monotonic() - started < 2
    assert released.is_set()
    assert not dialogs


@pytest.mark.parametrize(
    "status,invalid_response,expected", [(429, False, 30), (200, True, 30), (503, False, 5)]
)
def test_live_worker_uses_error_fields_for_pause(
    gui_environment: tuple[Any, Any, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: int,
    invalid_response: bool,
    expected: int,
) -> None:
    """Prawdziwa pętla nasłuchu wybiera pauzę z pól błędu, także przy mylącym tekście."""
    from shaq import _gui
    from shaq._recognition import RecognitionError

    wx, app, _dialogs = gui_environment
    frame = _hidden_frame(_gui, wx, app, monkeypatch)
    pauses = []

    def wait(seconds: float) -> bool:
        pauses.append(seconds)
        frame._stop_event.set()
        return True

    async def recognize(_audio: bytes) -> None:
        raise RecognitionError(
            "Poprzednio HTTP 429" if status == 503 else "Odpowiedź usługi",
            status=status,
            invalid_response=invalid_response,
        )

    monkeypatch.setattr(frame._stop_event, "wait", wait)
    monkeypatch.setattr(_gui, "_record_wav", lambda *_a, **_k: _test_wav())
    monkeypatch.setattr(
        _gui, "create_recognizer", lambda **_k: SimpleNamespace(recognize=recognize)
    )
    frame._worker_main(
        _gui._AudioDevice("Test", "test", "output"),
        tmp_path / "history.txt",
        "en-US",
        "US",
        _gui._default_advanced_settings(),
    )
    assert pauses == [expected]
