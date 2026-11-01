"""Cichy odbiór strumienia do ograniczonego bufora, z ponownym łączeniem."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from shaq._file_scan import _bundled_tool
from shaq._radio_messages import default_translate
from shaq._radio_playlist import resolve_stream_url, validate_stream_url

SAMPLE_RATE = 48000
CHANNELS = 2
FRAME_BYTES = CHANNELS * 2
BYTES_PER_SECOND = SAMPLE_RATE * FRAME_BYTES
CHUNK_BYTES = BYTES_PER_SECOND // 10
MAX_BUFFER_SECONDS = 65
STALL_SECONDS = 20.0


def radio_ffmpeg(*, translate: Callable[..., str] = default_translate) -> str:
    """Preferuje FFmpeg z aplikacji; instalacja systemowa jest jedynie rezerwą."""
    candidates = [_bundled_tool("ffmpeg")]
    if not getattr(sys, "frozen", False):
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        candidates.append(str(Path(__file__).resolve().parents[1] / "vendor" / "ffmpeg" / name))
    candidates.extend([os.environ.get("SHAQ_FFMPEG"), shutil.which("ffmpeg")])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError(translate("radio.ffmpeg_missing"))


class StreamBuffer:
    """Przechowuje końcówkę transmisji i wydaje wyłącznie świeże, ciągłe próbki."""

    def __init__(self, *, translate: Callable[..., str] = default_translate) -> None:
        self._t = translate
        self._condition = threading.Condition()
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._total = 0
        self._generation = 0
        self._closed = False

    @property
    def buffered_bytes(self) -> int:
        """Zwraca rozmiar bufora przydatny do kontroli długiego nasłuchu."""
        with self._condition:
            return self._size

    def reset(self) -> None:
        """Rozpoczyna nowy, ciągły odcinek po ponownym połączeniu."""
        with self._condition:
            self._chunks.clear()
            self._size = self._total = 0
            self._generation += 1
            self._condition.notify_all()

    def feed(self, data: bytes) -> None:
        """Dodaje PCM16 stereo i usuwa najstarsze dane ponad limit pamięci."""
        if not isinstance(data, bytes):
            raise TypeError(self._t("radio.pcm_type"))
        if len(data) % FRAME_BYTES:
            raise ValueError(self._t("radio.pcm_frame"))
        if not data:
            return
        limit = MAX_BUFFER_SECONDS * BYTES_PER_SECOND
        with self._condition:
            if self._closed:
                return
            self._total += len(data)
            data = data[-limit:]
            self._chunks.append(data)
            self._size += len(data)
            while self._chunks and self._size - len(self._chunks[0]) >= limit:
                self._size -= len(self._chunks.popleft())
            if self._size > limit:
                extra = self._size - limit
                self._chunks[0] = self._chunks[0][extra:]
                self._size = limit
            self._condition.notify_all()

    def close(self) -> None:
        """Zatrzymuje oczekiwanie i zwalnia przechowywany dźwięk."""
        with self._condition:
            self._closed = True
            self._chunks.clear()
            self._size = 0
            self._condition.notify_all()

    def read_wav(self, duration_s: float, stop_event: threading.Event) -> bytes | None:
        """Zbiera nową próbkę; pomija zaległości i nie łączy dźwięku przez przerwę sieci."""
        if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
            raise TypeError(self._t("radio.duration_type"))
        if not math.isfinite(duration_s) or not 1 / SAMPLE_RATE <= duration_s <= 60:
            raise ValueError(self._t("radio.duration_range"))
        length = int(duration_s * SAMPLE_RATE) * FRAME_BYTES
        with self._condition:
            generation, start = self._generation, self._total
            while not self._closed and not stop_event.is_set():
                if generation != self._generation:
                    generation, start = self._generation, 0
                oldest = self._total - self._size
                start = max(start, oldest)
                if self._total >= start + length:
                    offset = start - oldest
                    pcm = b"".join(self._chunks)[offset : offset + length]
                    break
                self._condition.wait(0.1)
            else:
                return None
        with BytesIO() as output:
            with wave.open(output, "wb") as wav:
                wav.setnchannels(CHANNELS)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(pcm)
            return output.getvalue()


def decoder_command(
    ffmpeg: str,
    url: str,
    *,
    translate: Callable[..., str] = default_translate,
) -> list[str]:
    """Buduje polecenie dekodowania HTTP(S) do pamięci, bez urządzenia odtwarzającego."""
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-rw_timeout",
        "10000000",
        "-protocol_whitelist",
        "http,https,tcp,tls,crypto",
        "-user_agent",
        "ShaqGUI/Radio",
        "-re",
        "-i",
        validate_stream_url(url, translate=translate),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        str(CHANNELS),
        "-ar",
        str(SAMPLE_RATE),
        "-acodec",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    ]


@dataclass(frozen=True)
class RadioStatus:
    """Stan odbiornika niezależny od języka wyświetlanego komunikatu."""

    kind: Literal["connecting", "connected", "failed"]
    retry_delay_s: int = 0


class RadioStream:
    """Odbiera radio niezależnie od karty dźwiękowej i opcjonalnego odsłuchu."""

    def __init__(
        self,
        url: str,
        *,
        on_status: Callable[[RadioStatus], None],
        on_audio: Callable[[bytes], None] | None = None,
        translate: Callable[..., str] = default_translate,
    ) -> None:
        self._t = translate
        self.url = validate_stream_url(url, translate=translate)
        self._ffmpeg = radio_ffmpeg(translate=translate)
        self._status = on_status
        self._audio = on_audio
        self.buffer = StreamBuffer(translate=translate)
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._last_audio = 0.0
        self._thread: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None

    def start(self) -> None:
        """Uruchamia odbiór raz; po zamknięciu wymagany jest nowy obiekt sesji."""
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError(self._t("radio.session_closed"))
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="radio-dekoder", daemon=True)
            self._watchdog = threading.Thread(target=self._watch, name="radio-nadzor", daemon=True)
            self._thread.start()
            self._watchdog.start()

    def stop(self) -> None:
        """Natychmiast przerywa odbiór i oczekiwanie na próbkę."""
        self._stop.set()
        self.buffer.close()
        with self._lock:
            process = self._process
        self._terminate(process)

    def join(self, timeout: float = 5.0) -> None:
        """Pozwala poczekać na zwolnienie procesu poza wątkiem interfejsu."""
        if self._thread is not None:
            self._thread.join(timeout)
        if self._watchdog is not None:
            self._watchdog.join(0.5)

    def read_wav(self, *, duration_s: float, stop_event: threading.Event) -> bytes | None:
        """Zwraca świeżą próbkę radia albo None po zatrzymaniu nasłuchu."""
        return self.buffer.read_wav(duration_s, stop_event)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes] | None) -> None:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _watch(self) -> None:
        while not self._finished.wait(0.25) and not self._stop.is_set():
            with self._lock:
                process, last_audio = self._process, self._last_audio
            if process is not None and time.monotonic() - last_audio > STALL_SECONDS:
                self._terminate(process)

    def _run(self) -> None:
        failures = 0
        try:
            while not self._stop.is_set():
                self._status(RadioStatus("connecting"))
                process = None
                received = 0
                try:
                    url = resolve_stream_url(self.url, self._stop, translate=self._t)
                    if url is None or self._stop.is_set():
                        break
                    self.buffer.reset()
                    process = subprocess.Popen(
                        decoder_command(self._ffmpeg, url, translate=self._t),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    with self._lock:
                        self._process = process
                        self._last_audio = time.monotonic()
                    if self._stop.is_set():
                        self._terminate(process)
                        break
                    if process.stdout is None:
                        raise RuntimeError(self._t("radio.decoder_empty"))
                    while not self._stop.is_set():
                        chunk = process.stdout.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        chunk = chunk[: len(chunk) - len(chunk) % FRAME_BYTES]
                        if not chunk:
                            continue
                        with self._lock:
                            self._last_audio = time.monotonic()
                        if not received:
                            self._status(RadioStatus("connected"))
                        received += len(chunk)
                        self.buffer.feed(chunk)
                        if self._audio is not None and not self._stop.is_set():
                            self._audio(chunk)
                except Exception:
                    pass
                finally:
                    self._terminate(process)
                    if process is not None:
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            try:
                                process.kill()
                                process.wait(timeout=2)
                            except (OSError, subprocess.TimeoutExpired):
                                pass
                        if process.stdout is not None:
                            process.stdout.close()
                    with self._lock:
                        self._process = None
                if self._stop.is_set():
                    break
                failures = 0 if received >= 10 * BYTES_PER_SECOND else failures + 1
                delay = min(30, 2 ** min(failures, 5))
                self._status(RadioStatus("failed", delay))
                self._stop.wait(delay)
        finally:
            self.buffer.close()
            self._finished.set()
