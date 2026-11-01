"""Sprawdza pauzy rzeczywistej pętli ShaqCast bez nagrywania i wysyłania tytułów."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture(scope="module", autouse=True)
def release_soundcard_com() -> Iterator[None]:
    """Zwalnia testowy interfejs COM przed zamknięciem interpretera."""
    yield
    module = sys.modules.get("soundcard.mediafoundation")
    library = getattr(module, "_com", None)
    if library is not None and library.com_loaded:
        library.__del__()
        library.com_loaded = False


@pytest.mark.parametrize(
    "status,invalid_response,expected",
    [(429, False, 30), (200, True, 30), (503, False, 5)],
)
def test_streamer_uses_error_fields_for_pause(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    invalid_response: bool,
    expected: int,
) -> None:
    """Niepoprawna odpowiedź i limit podnoszą pauzę do 30 s niezależnie od tekstu."""
    pytest.importorskip("soundcard")
    pytest.importorskip("shazamio")
    from shaqcast._recognition import RecognitionError

    from shaqcast import streamer

    pauses = []
    session = streamer.StreamingSession(
        settings=streamer.StreamSettings(
            "example.invalid", 8000, "", [1], "output", "test"
        ),
        log=lambda _text: None,
    )

    def wait(seconds: float) -> bool:
        pauses.append(seconds)
        session._stop_event.set()
        return True

    async def recognize(_audio: bytes) -> Any:
        raise RecognitionError(
            "Poprzednio HTTP 429" if status == 503 else "Odpowiedź usługi",
            status=status,
            invalid_response=invalid_response,
        )

    monkeypatch.setattr(session._stop_event, "wait", wait)
    monkeypatch.setattr(
        streamer.sc, "get_speaker", lambda _id: SimpleNamespace(name="Test")
    )
    monkeypatch.setattr(streamer, "_capture_wav_bytes", lambda **_kwargs: b"test")
    monkeypatch.setattr(
        streamer, "_rank_window_starts_by_rms", lambda *_a, **_k: ([0], -10)
    )
    monkeypatch.setattr(streamer, "_slice_wav_bytes", lambda *_a, **_k: b"test")
    monkeypatch.setattr(
        streamer,
        "create_recognizer",
        lambda **_kwargs: SimpleNamespace(recognize=recognize),
    )
    session._run()
    assert pauses == [expected]
