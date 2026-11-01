"""Opcjonalny odsłuch radia z niezależną głośnością i krótką kolejką dźwięku."""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from queue import Empty, Full, Queue

from shaq._radio_messages import default_translate
from shaq._radio_stream import CHANNELS, SAMPLE_RATE


class RadioPreview:
    """Odtwarza kopię PCM; zatrzymanie odsłuchu nie zmienia próbki rozpoznawania."""

    def __init__(
        self,
        volume: int,
        *,
        finished: Callable[[str], None],
        translate: Callable[..., str] = default_translate,
    ) -> None:
        self._t = translate
        self._queue: Queue[bytes] = Queue(maxsize=3)
        self._stop = threading.Event()
        self._finished = finished
        self._thread: threading.Thread | None = None
        self.set_volume(volume)

    def set_volume(self, volume: int) -> None:
        """Ustawia głośność tylko odsłuchu, w zakresie 0–100."""
        if type(volume) is not int:
            raise TypeError(self._t("radio.volume_type"))
        if not 0 <= volume <= 100:
            raise ValueError(self._t("radio.volume_range"))
        self._gain = volume / 100.0

    def start(self) -> None:
        """Uruchamia odtwarzanie dopiero po jawnym włączeniu odsłuchu."""
        if self._thread is not None or self._stop.is_set():
            raise RuntimeError(self._t("radio.preview_restarted"))
        self._thread = threading.Thread(target=self._run, name="radio-odsluch", daemon=True)
        self._thread.start()

    def feed(self, pcm: bytes) -> None:
        """Dodaje kopię aktualnego dźwięku bez blokowania cichego nasłuchu."""
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait(pcm)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            try:
                self._queue.put_nowait(pcm)
            except Full:
                pass

    def stop(self) -> None:
        """Wyłącza odsłuch bez oczekiwania w interfejsie użytkownika."""
        self._stop.set()

    def join(self, timeout: float = 2.0) -> None:
        """Czeka na zamknięcie odtwarzacza podczas testowania lub sprzątania."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        error = ""
        ole = None
        com_initialized = False
        try:
            import numpy as np
            import soundcard as sc

            if sys.platform == "win32":
                ole = ctypes.OleDLL("ole32")
                ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                ole.CoInitializeEx.restype = ctypes.c_int32
                result = ole.CoInitializeEx(None, 0)
                if result < 0:
                    raise RuntimeError(self._t("radio.windows_audio"))
                com_initialized = True
            speaker = sc.default_speaker()
            if speaker is None:
                raise RuntimeError(self._t("radio.no_speaker"))
            with speaker.player(
                samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=4800
            ) as player:
                while not self._stop.is_set():
                    try:
                        pcm = self._queue.get(timeout=0.1)
                    except Empty:
                        continue
                    if not self._stop.is_set():
                        samples = np.frombuffer(pcm, dtype="<i2").reshape(-1, CHANNELS)
                        player.play(samples.astype(np.float32) * (self._gain / 32768.0))
        except Exception:
            error = self._t("radio.preview_error")
        finally:
            if com_initialized and ole is not None:
                ole.CoUninitialize()
            self._stop.set()
            self._finished(error)
