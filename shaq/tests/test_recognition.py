"""Regresje czasu oczekiwania, anulowania i długości sygnatur Shazama."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from typing import Any

import pytest

from shaq._recognition import (
    RecognitionCancelled,
    RecognitionError,
    RecognitionHTTPClient,
    create_recognizer,
    retry_after_seconds,
    run_interruptible,
    signature_seconds,
)


@pytest.mark.parametrize("value,expected", [(1, 1), (8, 8), (12, 12), (15, 12), (60, 12)])
def test_signature_limit_preserves_short_and_repairs_old_settings(
    value: int, expected: int
) -> None:
    assert signature_seconds(value) == expected


@pytest.mark.parametrize(
    "value,error", [(0, ValueError), (-1, ValueError), (True, TypeError), ("12", TypeError)]
)
def test_signature_rejects_invalid_length(value: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        signature_seconds(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("7.5", 7.5),
        ("-1", 0),
        ("NaN", None),
        ("inf", None),
        ("błąd", None),
    ],
)
def test_retry_after_seconds(value: str | None, expected: float | None) -> None:
    assert retry_after_seconds(value) == expected


def test_retry_after_http_date() -> None:
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    result = retry_after_seconds(format_datetime(future, usegmt=True))
    assert result is not None and 57 <= result <= 60
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[Any]]:
    aiohttp = pytest.importorskip("aiohttp")

    def configure(
        *, status: int = 200, payload: Any = None, error: Exception | None = None
    ) -> list[Any]:
        calls: list[Any] = []

        class Response:
            url = "https://example.invalid/rozpoznaj"
            headers = {"Retry-After": "45", "Content-Type": "application/json"}

            async def __aenter__(self) -> Response:
                return self

            async def __aexit__(self, *_args: Any) -> None:
                return None

            async def json(self, **_kwargs: Any) -> Any:
                if error is not None:
                    raise error
                return payload

        response = Response()
        response.status = status

        class Session:
            def __init__(self, *, timeout: Any) -> None:
                assert timeout.total == 15
                assert timeout.connect == 5

            async def __aenter__(self) -> Session:
                return self

            async def __aexit__(self, *_args: Any) -> None:
                return None

            def request(self, method: str, url: str, **kwargs: Any) -> Response:
                calls.append((method, url, kwargs))
                return response

        monkeypatch.setattr(aiohttp, "ClientSession", Session)
        return calls

    return configure


@pytest.mark.parametrize(
    "payload", [{"matches": []}, {"matches": [{"id": "test"}], "track": {"title": "Test"}}]
)
def test_http_returns_valid_response_without_retry(
    fake_http: Callable[..., list[Any]], payload: dict[str, Any]
) -> None:
    calls = fake_http(payload=payload)
    client = RecognitionHTTPClient()
    assert asyncio.run(client.request("POST", "https://example.invalid", json={})) == payload
    assert len(calls) == 1
    assert client.attempts == [(1, 200)]
    client.reset()
    assert client.attempts == [] and client.last_status is None


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_http_errors_are_not_empty_matches_or_hidden_retries(
    fake_http: Callable[..., list[Any]], status: int
) -> None:
    calls = fake_http(status=status, payload={"matches": []})
    client = RecognitionHTTPClient()
    with pytest.raises(RecognitionError) as caught:
        asyncio.run(client.request("POST", "https://example.invalid"))
    assert caught.value.status == status
    assert caught.value.retry_after_s == 45
    assert client.last_status == status
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [None, [], {}, {"matches": None}, {"matches": "błąd"}])
def test_malformed_success_is_an_error(fake_http: Callable[..., list[Any]], payload: Any) -> None:
    fake_http(payload=payload)
    with pytest.raises(RecognitionError, match="bez wyników"):
        asyncio.run(RecognitionHTTPClient().request("POST", "https://example.invalid"))


@pytest.mark.parametrize(
    "error,text", [(ValueError("JSON"), "JSON"), (asyncio.TimeoutError(), "15 sekund")]
)
def test_http_timeout_and_invalid_json(
    fake_http: Callable[..., list[Any]], error: Exception, text: str
) -> None:
    calls = fake_http(error=error)
    with pytest.raises(RecognitionError, match=text):
        asyncio.run(RecognitionHTTPClient().request("POST", "https://example.invalid"))
    assert len(calls) == 1


def test_connection_error_is_reported(fake_http: Callable[..., list[Any]]) -> None:
    aiohttp = pytest.importorskip("aiohttp")
    fake_http(error=aiohttp.ClientConnectionError("przerwane połączenie"))
    with pytest.raises(RecognitionError, match="połączyć"):
        asyncio.run(RecognitionHTTPClient().request("POST", "https://example.invalid"))


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_http_timeout(timeout: float) -> None:
    with pytest.raises(ValueError):
        RecognitionHTTPClient(timeout)


def test_factory_passes_bounded_client_and_repairs_old_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "shazamio", SimpleNamespace(Shazam=lambda **kwargs: kwargs))
    settings = create_recognizer(
        language="pl-PL", endpoint_country="PL", segment_duration_seconds=60
    )
    assert settings["segment_duration_seconds"] == 12
    assert isinstance(settings["http_client"], RecognitionHTTPClient)


@pytest.fixture
def loop() -> Iterator[asyncio.AbstractEventLoop]:
    event_loop = asyncio.new_event_loop()
    yield event_loop
    assert not asyncio.all_tasks(event_loop)
    event_loop.close()


def test_interruptible_success_and_original_exception(loop: asyncio.AbstractEventLoop) -> None:
    async def value() -> int:
        return 42

    async def failure() -> None:
        raise RecognitionError("Błąd usługi")

    stop = threading.Event()
    assert run_interruptible(loop, value(), stop_event=stop) == 42
    with pytest.raises(RecognitionError, match="Błąd usługi"):
        run_interruptible(loop, failure(), stop_event=stop)


@pytest.mark.parametrize("cancel_with_stop", [False, True])
def test_interruptible_cancels_pending_network_and_releases_task(
    loop: asyncio.AbstractEventLoop, cancel_with_stop: bool
) -> None:
    stop = threading.Event()
    released = threading.Event()

    async def pending() -> None:
        try:
            await asyncio.sleep(60)
        finally:
            released.set()

    timer = threading.Timer(0.1, stop.set)
    if cancel_with_stop:
        timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(RecognitionCancelled if cancel_with_stop else RecognitionError):
            run_interruptible(
                loop, pending(), stop_event=stop, timeout_s=10 if cancel_with_stop else 0.1
            )
        assert time.monotonic() - started < 2
        assert released.is_set()
    finally:
        timer.cancel()


def test_already_stopped_never_starts_request(loop: asyncio.AbstractEventLoop) -> None:
    stop = threading.Event()
    stop.set()
    started: list[bool] = []

    async def operation() -> None:
        started.append(True)

    with pytest.raises(RecognitionCancelled):
        run_interruptible(loop, operation(), stop_event=stop)
    assert started == []


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_interruptible_invalid_timeout_closes_coroutine(
    loop: asyncio.AbstractEventLoop, timeout: float
) -> None:
    with pytest.raises(ValueError):
        run_interruptible(loop, asyncio.sleep(60), stop_event=threading.Event(), timeout_s=timeout)
