"""Rozpoznawanie z kontrolowanym czasem oczekiwania i bez ukrytych ponowień HTTP."""

from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

_STRINGS: dict[str, dict[str, str]] = {
    "recognition.http": {
        "pl": "Shazam zwrócił HTTP {status}.",
        "en": "Shazam returned HTTP {status}.",
    },
    "recognition.json": {
        "pl": "Shazam zwrócił niepoprawną odpowiedź JSON.",
        "en": "Shazam returned an invalid JSON response.",
    },
    "recognition.missing": {
        "pl": "Shazam zwrócił odpowiedź bez wyników rozpoznawania.",
        "en": "Shazam returned a response without recognition results.",
    },
    "recognition.timeout": {
        "pl": "Shazam nie odpowiedział w ciągu {seconds:g} sekund.",
        "en": "Shazam did not respond within {seconds:g} seconds.",
    },
    "recognition.connection": {
        "pl": "Nie udało się połączyć z Shazamem: {error}",
        "en": "Could not connect to Shazam: {error}",
    },
    "recognition.cancelled": {"pl": "Zatrzymano rozpoznawanie.", "en": "Recognition stopped."},
    "recognition.deadline": {
        "pl": "Przekroczono limit {seconds:g} sekund na rozpoznanie próbki.",
        "en": "The sample recognition exceeded the {seconds:g} second limit.",
    },
    "recognition.stopped_error": {
        "pl": "Zatrzymano nasłuch z powodu błędu: {error}",
        "en": "Monitoring stopped because of an error: {error}",
    },
}


def default_translate(key: str, **values: Any) -> str:
    """Zachowuje język polski dla wywołań bez interfejsu aplikacji."""
    return _STRINGS[key]["pl"].format(**values)


MAX_SIGNATURE_SECONDS = 12
REQUEST_TIMEOUT_SECONDS = 15.0
RECOGNITION_TIMEOUT_SECONDS = 20.0
_Result = TypeVar("_Result")


class RecognitionError(RuntimeError):
    """Błąd usługi, którego nie należy traktować jako braku pasującego utworu."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after_s: float | None = None,
        invalid_response: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s
        self.invalid_response = invalid_response


class RecognitionCancelled(RuntimeError):
    """Użytkownik zatrzymał rozpoznawanie."""


def recognition_backoff_seconds(error: Exception, failures: int) -> float:
    """Wyznacza pauzę z pól błędu, niezależnie od języka i treści komunikatu."""
    if not isinstance(error, Exception) or type(failures) is not int:
        raise TypeError("Wymagany jest wyjątek i całkowita liczba niepowodzeń.")
    if failures < 1:
        raise ValueError("Liczba niepowodzeń musi być dodatnia.")
    delay = min(300.0, 5.0 * 2 ** min(6, failures - 1))
    if isinstance(error, RecognitionError):
        if error.status == 429 or error.invalid_response:
            delay = max(delay, 30.0)
        retry_after = error.retry_after_s
        if isinstance(retry_after, (int, float)) and math.isfinite(retry_after):
            delay = max(delay, retry_after)
    return delay


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

    def __init__(
        self,
        timeout_s: float = REQUEST_TIMEOUT_SECONDS,
        *,
        translate: Callable[..., str] = default_translate,
    ) -> None:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise TypeError("Limit czasu zapytania musi być liczbą.")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("Limit czasu zapytania musi być dodatni i skończony.")
        self._t = translate
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
                            self._t("recognition.http", status=response.status),
                            status=response.status,
                            retry_after_s=retry_after_seconds(response.headers.get("Retry-After")),
                        )
                    try:
                        result = await response.json(content_type=None)
                    except (ValueError, UnicodeError) as exc:
                        raise RecognitionError(
                            self._t("recognition.json"),
                            status=response.status,
                            invalid_response=True,
                            retry_after_s=retry_after_seconds(response.headers.get("Retry-After")),
                        ) from exc
                    if not isinstance(result, dict) or not isinstance(result.get("matches"), list):
                        raise RecognitionError(
                            self._t("recognition.missing"),
                            status=response.status,
                            invalid_response=True,
                            retry_after_s=retry_after_seconds(response.headers.get("Retry-After")),
                        )
                    return result
        except asyncio.TimeoutError as exc:
            raise RecognitionError(self._t("recognition.timeout", seconds=self.timeout_s)) from exc
        except aiohttp.ClientError as exc:
            raise RecognitionError(self._t("recognition.connection", error=str(exc))) from exc


def create_recognizer(
    *,
    language: str,
    endpoint_country: str,
    segment_duration_seconds: int,
    translate: Callable[..., str] = default_translate,
) -> Any:
    """Tworzy klienta z krótką sygnaturą i jawnym limitem czasu połączenia."""
    from shazamio import Shazam

    return Shazam(
        language=language,
        endpoint_country=endpoint_country,
        segment_duration_seconds=signature_seconds(segment_duration_seconds),
        http_client=RecognitionHTTPClient(translate=translate),
    )


def run_interruptible(
    loop: asyncio.AbstractEventLoop,
    operation: Awaitable[_Result],
    *,
    stop_event: threading.Event,
    timeout_s: float = RECOGNITION_TIMEOUT_SECONDS,
    translate: Callable[..., str] = default_translate,
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
                    raise RecognitionCancelled(translate("recognition.cancelled"))
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise RecognitionError(translate("recognition.deadline", seconds=timeout_s))
                await asyncio.wait((task,), timeout=min(0.05, remaining))
            if stop_event.is_set():
                raise RecognitionCancelled(translate("recognition.cancelled"))
            return task.result()
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return loop.run_until_complete(run())
