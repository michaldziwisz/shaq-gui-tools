"""Rozpoznawanie z kontrolowanym czasem oczekiwania i bez ukrytych ponowień HTTP."""

from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import Awaitable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

MAX_SIGNATURE_SECONDS = 12
REQUEST_TIMEOUT_SECONDS = 15.0
RECOGNITION_TIMEOUT_SECONDS = 20.0
_Result = TypeVar("_Result")


class RecognitionError(RuntimeError):
    """Błąd usługi, którego nie należy traktować jako braku pasującego utworu."""

    def __init__(
        self, message: str, *, status: int | None = None, retry_after_s: float | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s


class RecognitionCancelled(RuntimeError):
    """Użytkownik zatrzymał rozpoznawanie."""


def signature_seconds(value: int) -> int:
    """Ogranicza długość sygnatury do sprawdzonych 12 sekund, także dla starszej konfiguracji."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Długość sygnatury musi być liczbą całkowitą.")
    if value < 1:
        raise ValueError("Długość sygnatury musi być dodatnia.")
    return min(value, MAX_SIGNATURE_SECONDS)


def retry_after_seconds(value: str | None) -> float | None:
    """Odczytuje Retry-After jako liczbę sekund albo datę HTTP."""
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


class RecognitionHTTPClient:
    """Wykonuje jedno zapytanie z limitem czasu; zapisuje status do diagnostyki aplikacji."""

    def __init__(self, timeout_s: float = REQUEST_TIMEOUT_SECONDS) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("Limit czasu zapytania musi być dodatni i skończony.")
        self.timeout_s = timeout_s
        self.reset()

    def reset(self) -> None:
        """Czyści dane poprzedniego zapytania."""
        self.last_status: int | None = None
        self.last_url: str | None = None
        self.last_headers: dict[str, str] = {}
        self.attempts: list[tuple[int, int]] = []

    async def request(self, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
        """Zwraca JSON lub czytelny błąd; nie ponawia zapytania wewnątrz biblioteki."""
        import aiohttp

        self.reset()
        timeout = aiohttp.ClientTimeout(total=self.timeout_s, connect=min(5.0, self.timeout_s))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(method, url, **kwargs) as response:
                    self.last_status = response.status
                    self.last_url = str(response.url)
                    self.last_headers = dict(response.headers)
                    self.attempts.append((1, response.status))
                    if response.status != 200:
                        raise RecognitionError(
                            f"Shazam zwrócił HTTP {response.status}.",
                            status=response.status,
                            retry_after_s=retry_after_seconds(response.headers.get("Retry-After")),
                        )
                    try:
                        result = await response.json(content_type=None)
                    except (ValueError, UnicodeError) as exc:
                        raise RecognitionError(
                            "Shazam zwrócił niepoprawną odpowiedź JSON."
                        ) from exc
                    if not isinstance(result, dict) or not isinstance(result.get("matches"), list):
                        raise RecognitionError(
                            "Shazam zwrócił odpowiedź bez wyników rozpoznawania."
                        )
                    return result
        except asyncio.TimeoutError as exc:
            raise RecognitionError(
                f"Shazam nie odpowiedział w ciągu {self.timeout_s:g} sekund."
            ) from exc
        except aiohttp.ClientError as exc:
            raise RecognitionError(f"Nie udało się połączyć z Shazamem: {exc}") from exc


def create_recognizer(
    *, language: str, endpoint_country: str, segment_duration_seconds: int
) -> Any:
    """Tworzy klienta z krótką sygnaturą i jawnym limitem czasu połączenia."""
    from shazamio import Shazam

    return Shazam(
        language=language,
        endpoint_country=endpoint_country,
        segment_duration_seconds=signature_seconds(segment_duration_seconds),
        http_client=RecognitionHTTPClient(),
    )


def run_interruptible(
    loop: asyncio.AbstractEventLoop,
    operation: Awaitable[_Result],
    *,
    stop_event: threading.Event,
    timeout_s: float = RECOGNITION_TIMEOUT_SECONDS,
) -> _Result:
    """Uruchamia operację, reagując na Stop i przerywając oczekiwanie po ustalonym czasie."""

    async def run() -> _Result:
        task = asyncio.ensure_future(operation)
        try:
            if not math.isfinite(timeout_s) or timeout_s <= 0:
                raise ValueError("Limit czasu rozpoznawania musi być dodatni i skończony.")
            deadline = loop.time() + timeout_s
            while not task.done():
                if stop_event.is_set():
                    raise RecognitionCancelled("Zatrzymano rozpoznawanie.")
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise RecognitionError(
                        f"Przekroczono limit {timeout_s:g} sekund na rozpoznanie próbki."
                    )
                await asyncio.wait((task,), timeout=min(0.05, remaining))
            if stop_event.is_set():
                raise RecognitionCancelled("Zatrzymano rozpoznawanie.")
            return task.result()
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return loop.run_until_complete(run())
