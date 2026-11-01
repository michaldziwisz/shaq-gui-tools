from __future__ import annotations

import asyncio
import math
import os
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

import numpy as np
import soundcard as sc
from shazamio import Serialize

from ._process_audio import ProcessTarget, record_process_wav
from ._process_messages import _STRINGS as PROCESS_STRINGS
from ._recognition import (
    create_recognizer,
    recognition_backoff_seconds,
    run_interruptible,
    signature_seconds,
)
from ._recognition import _STRINGS as RECOGNITION_STRINGS
from ._soundcard_compat import patch_soundcard_numpy_fromstring
from .i18n import I18n
from .icecast import update_now_playing as update_icecast_now_playing
from .shoutcast import update_now_playing as update_shoutcast_now_playing


LogFn = Callable[[str], None]

_SHAZAM_SEGMENT_DURATION_S = int(os.environ.get("SHAQCAST_SHAZAM_SEGMENT_SECONDS", "12"))
_SHAZAM_SEGMENT_DURATION_S = signature_seconds(max(3, _SHAZAM_SEGMENT_DURATION_S))

_MAX_WINDOWS_PER_SAMPLE = max(
    1, min(6, int(os.environ.get("SHAQCAST_MAX_WINDOWS_PER_SAMPLE", "1")))
)
_WINDOW_STEP_S = max(1, int(os.environ.get("SHAQCAST_WINDOW_STEP_S", "1")))
_SILENCE_DBFS_THRESHOLD = float(os.environ.get("SHAQCAST_SILENCE_DBFS_THRESHOLD", "-55.0"))
_MIN_REQUEST_INTERVAL_S = float(os.environ.get("SHAQCAST_MIN_REQUEST_INTERVAL_S", "10.0"))
_MIN_REQUEST_INTERVAL_S = max(0.0, min(60.0, _MIN_REQUEST_INTERVAL_S))

StreamServerType = Literal["shoutcast", "icecast"]


def _compact_response_body(body: str, *, limit: int = 180) -> str:
    text = " ".join((body or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _update_failed_log(prefix: str, result: object) -> str:
    status = getattr(result, "status", None)
    status_text = status if status is not None else "n/a"
    method = getattr(result, "method", "unknown")
    message = f"{prefix} update failed ({method}, status={status_text})"
    body = _compact_response_body(str(getattr(result, "body", "") or ""))
    if body:
        message = f"{message}: {body}"
    return message


@dataclass(frozen=True, slots=True)
class StreamSettings:
    host: str
    port: int
    password: str
    sids: list[int]
    source: str  # "output", "input" albo izolowany nasłuch "process"
    device_id: str
    process_target: ProcessTarget | None = None
    ui_language: str = "pl"
    server_type: StreamServerType = "shoutcast"
    icecast_user: str = "source"
    icecast_mounts: list[str] = field(default_factory=list)
    language: str = "en-US"
    endpoint_country: str = "US"
    listen_seconds: int = 15
    no_match_text: str = ""
    shazam_segment_seconds: int = int(_SHAZAM_SEGMENT_DURATION_S)
    max_windows_per_sample: int = int(_MAX_WINDOWS_PER_SAMPLE)
    window_step_s: int = int(_WINDOW_STEP_S)
    silence_dbfs_threshold: float = float(_SILENCE_DBFS_THRESHOLD)
    min_request_interval_s: float = float(_MIN_REQUEST_INTERVAL_S)
    sample_rate_hz: int = 16000
    channels: int = 1
    chunk_frames: int = 1024


def _capture_wav_bytes(
    *,
    device_id: str,
    include_loopback: bool,
    duration_s: int,
    sample_rate_hz: int,
    channels: int,
    chunk_frames: int,
    stop_event: threading.Event | None = None,
) -> bytearray | None:
    microphone = sc.get_microphone(device_id, include_loopback=include_loopback)

    total_frames = sample_rate_hz * duration_s
    frames_recorded = 0

    with (
        BytesIO() as io,
        wave.open(io, "wb") as wav,
        microphone.recorder(samplerate=sample_rate_hz, channels=channels) as recorder,
    ):
        wav.setnchannels(channels)
        wav.setsampwidth(2)  # PCM16
        wav.setframerate(sample_rate_hz)

        while frames_recorded < total_frames:
            if stop_event is not None and stop_event.is_set():
                return None
            frames = min(chunk_frames, total_frames - frames_recorded)
            chunk = recorder.record(numframes=frames)
            pcm16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
            wav.writeframes(pcm16.tobytes())
            frames_recorded += frames

        return bytearray(io.getvalue())


def _slice_wav_bytes(
    wav_bytes: bytes,
    *,
    start_s: int,
    duration_s: int,
) -> bytes | None:
    if start_s < 0:
        start_s = 0
    if duration_s <= 0:
        return None

    try:
        with wave.open(BytesIO(wav_bytes), "rb") as wav_in:
            framerate = wav_in.getframerate()
            if framerate <= 0:
                return None

            start_frame = int(start_s * framerate)
            duration_frames = int(duration_s * framerate)
            if duration_frames <= 0:
                return None

            if start_frame >= wav_in.getnframes():
                return None

            wav_in.setpos(start_frame)
            frames = wav_in.readframes(duration_frames)
            if not frames:
                return None

            with BytesIO() as out_io:
                with wave.open(out_io, "wb") as wav_out:
                    wav_out.setnchannels(wav_in.getnchannels())
                    wav_out.setsampwidth(wav_in.getsampwidth())
                    wav_out.setframerate(framerate)
                    wav_out.writeframes(frames)
                return out_io.getvalue()
    except wave.Error:
        return None


def _rank_window_starts_by_rms(
    wav_bytes: bytes,
    *,
    window_duration_s: int,
    window_step_s: int,
    max_windows: int,
) -> tuple[list[int], float]:
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as wav_in:
            channels = wav_in.getnchannels()
            sampwidth = wav_in.getsampwidth()
            framerate = wav_in.getframerate()
            declared_nframes = wav_in.getnframes()
            frames = wav_in.readframes(declared_nframes)
    except wave.Error:
        return [0], float("-inf")

    if framerate <= 0 or sampwidth != 2:
        return [0], float("-inf")

    frame_size = channels * sampwidth
    if frame_size <= 0:
        return [0], float("-inf")

    actual_nframes = len(frames) // frame_size
    if actual_nframes <= 0:
        return [0], float("-inf")

    frames = frames[: actual_nframes * frame_size]
    pcm = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)

    window_frames = int(window_duration_s * framerate)
    if window_frames <= 0 or window_frames >= pcm.shape[0]:
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        dbfs = float("-inf") if rms <= 0 else 20.0 * math.log10(rms / 32767.0)
        return [0], dbfs

    step_frames = max(1, int(window_step_s * framerate))
    last_start = pcm.shape[0] - window_frames
    candidates: list[tuple[float, int]] = []
    for start_frame in range(0, last_start + 1, step_frames):
        window = pcm[start_frame : start_frame + window_frames]
        if window.size <= 0:
            continue
        rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2)))
        candidates.append((rms, start_frame))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    best_rms = candidates[0][0] if candidates else 0.0
    best_dbfs = float("-inf") if best_rms <= 0 else 20.0 * math.log10(best_rms / 32767.0)

    starts: list[int] = []
    seen: set[int] = set()
    for _rms, start_frame in candidates:
        start_s = int(start_frame / framerate)
        if start_s in seen:
            continue
        seen.add(start_s)
        starts.append(start_s)
        if len(starts) >= max_windows:
            break

    if not starts:
        starts = [0]

    return starts, best_dbfs


class StreamingSession:
    def __init__(self, *, settings: StreamSettings, log: LogFn) -> None:
        self._settings = settings
        self._log = log
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._last_track_sent: str | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10.0)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self._run_with_loop(loop)
        except Exception as exc:
            self._log(I18n(self._settings.ui_language, RECOGNITION_STRINGS).t("recognition.stopped_error", error=str(exc)))
        finally:
            loop.close()

    def _run_with_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        patch_soundcard_numpy_fromstring()

        t = I18n(self._settings.ui_language, {**PROCESS_STRINGS, **RECOGNITION_STRINGS}).t
        is_process = self._settings.source == "process"
        include_loopback = self._settings.source == "output"
        label = "loopback" if include_loopback else "microphone"

        try:
            if is_process:
                if self._settings.process_target is None:
                    self._log(t("process.no_selection"))
                    return
                device_name = self._settings.process_target.name
                label = "program"
            elif include_loopback:
                device_name = sc.get_speaker(self._settings.device_id).name
            else:
                device_name = sc.get_microphone(self._settings.device_id).name
        except Exception as exc:
            self._log(f"Audio init failed: {exc}")
            return

        self._log(f"Listening ({label}): {device_name}")

        segment_duration_s = min(
            max(3, int(self._settings.listen_seconds)),
            max(3, min(60, int(self._settings.shazam_segment_seconds))),
        )
        segment_duration_s = signature_seconds(segment_duration_s)
        shazam = create_recognizer(
            language=self._settings.language,
            endpoint_country=self._settings.endpoint_country,
            segment_duration_seconds=segment_duration_s, translate=t,
        )
        last_request_at = 0.0
        consecutive_recognition_errors = 0

        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                if is_process:
                    audio = record_process_wav(
                        self._settings.process_target,
                        duration_s=self._settings.listen_seconds,
                        sample_rate=self._settings.sample_rate_hz,
                        channels=self._settings.channels,
                        stop_event=self._stop_event,
                        on_status=self._log, translate=t,
                    )
                else:
                    audio = _capture_wav_bytes(
                        device_id=self._settings.device_id,
                        include_loopback=include_loopback,
                        duration_s=self._settings.listen_seconds,
                        sample_rate_hz=self._settings.sample_rate_hz,
                        channels=self._settings.channels,
                        chunk_frames=self._settings.chunk_frames,
                        stop_event=self._stop_event,
                    )
                if audio is None or self._stop_event.is_set():
                    break
            except Exception as exc:
                self._log(t("process.audio_error", error=str(exc)))
                self._stop_event.wait(2.0)
                continue

            try:
                window_starts, best_dbfs = _rank_window_starts_by_rms(
                    audio,
                    window_duration_s=segment_duration_s,
                    window_step_s=max(1, int(self._settings.window_step_s)),
                    max_windows=max(1, min(6, int(self._settings.max_windows_per_sample))),
                )
                raw = None
                track = None

                if best_dbfs >= float(self._settings.silence_dbfs_threshold):
                    for rel_start_s in window_starts:
                        window_audio = _slice_wav_bytes(
                            audio, start_s=int(rel_start_s), duration_s=segment_duration_s
                        )
                        if window_audio is None:
                            continue
                        min_interval_s = max(
                            0.0, min(60.0, float(self._settings.min_request_interval_s))
                        )
                        if min_interval_s > 0:
                            now = time.monotonic()
                            since_last = now - last_request_at
                            if since_last < min_interval_s:
                                self._stop_event.wait(min_interval_s - since_last)
                            last_request_at = time.monotonic()
                        if self._stop_event.is_set():
                            break
                        raw = run_interruptible(
                            loop, shazam.recognize(window_audio), stop_event=self._stop_event, translate=t
                        )
                        track = Serialize.full_track(raw)
                        if track.matches:
                            break
                        raw = None
                        track = None
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                consecutive_recognition_errors += 1
                text = str(exc).strip()
                backoff_s = recognition_backoff_seconds(exc, consecutive_recognition_errors)

                detail = f": {text}" if text else ""
                self._log(f"Recognition failed, backing off {int(backoff_s)}s{detail}")
                self._stop_event.wait(backoff_s)
                continue

            if self._stop_event.is_set():
                break
            if track is None or not track.matches:
                consecutive_recognition_errors = 0
                elapsed = time.monotonic() - started
                fallback = self._settings.no_match_text.strip()
                if not fallback:
                    self._log(f"No match ({elapsed:.1f}s).")
                    continue

                if fallback == self._last_track_sent:
                    self._log(f"No match ({elapsed:.1f}s), unchanged fallback.")
                    continue

                self._log(f"No match ({elapsed:.1f}s), sending fallback: {fallback}")
                if self._settings.server_type == "icecast":
                    for mount in self._settings.icecast_mounts:
                        result = update_icecast_now_playing(
                            host=self._settings.host,
                            port=self._settings.port,
                            username=self._settings.icecast_user,
                            password=self._settings.password,
                            mount=mount,
                            song=fallback,
                        )
                        if result.ok:
                            self._log(f"[mount {mount}] updated ({result.method})")
                        else:
                            self._log(_update_failed_log(f"[mount {mount}]", result))
                else:
                    for sid in self._settings.sids:
                        result = update_shoutcast_now_playing(
                            host=self._settings.host,
                            port=self._settings.port,
                            password=self._settings.password,
                            sid=sid,
                            song=fallback,
                        )
                        if result.ok:
                            self._log(f"[sid {sid}] updated ({result.method})")
                        else:
                            self._log(_update_failed_log(f"[sid {sid}]", result))

                self._last_track_sent = fallback
                continue

            consecutive_recognition_errors = 0
            now_playing = f"{track.track.subtitle} - {track.track.title}"
            if now_playing == self._last_track_sent:
                self._log(f"Unchanged: {now_playing}")
                continue

            self._log(f"Recognized: {now_playing}")
            if self._settings.server_type == "icecast":
                for mount in self._settings.icecast_mounts:
                    result = update_icecast_now_playing(
                        host=self._settings.host,
                        port=self._settings.port,
                        username=self._settings.icecast_user,
                        password=self._settings.password,
                        mount=mount,
                        song=now_playing,
                    )
                    if result.ok:
                        self._log(f"[mount {mount}] updated ({result.method})")
                    else:
                        self._log(_update_failed_log(f"[mount {mount}]", result))
            else:
                for sid in self._settings.sids:
                    result = update_shoutcast_now_playing(
                        host=self._settings.host,
                        port=self._settings.port,
                        password=self._settings.password,
                        sid=sid,
                        song=now_playing,
                    )
                    if result.ok:
                        self._log(f"[sid {sid}] updated ({result.method})")
                    else:
                        self._log(_update_failed_log(f"[sid {sid}]", result))

            self._last_track_sent = now_playing
