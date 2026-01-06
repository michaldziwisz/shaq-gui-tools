from __future__ import annotations

import asyncio
import math
import os
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO

import numpy as np
import soundcard as sc
from shazamio import Serialize, Shazam

from .shoutcast import update_now_playing


LogFn = Callable[[str], None]

_SHAZAM_SEGMENT_DURATION_S = int(os.environ.get("SHAQCAST_SHAZAM_SEGMENT_SECONDS", "12"))
_SHAZAM_SEGMENT_DURATION_S = max(3, min(60, _SHAZAM_SEGMENT_DURATION_S))

_MAX_WINDOWS_PER_SAMPLE = max(
    1, min(6, int(os.environ.get("SHAQCAST_MAX_WINDOWS_PER_SAMPLE", "1")))
)
_WINDOW_STEP_S = max(1, int(os.environ.get("SHAQCAST_WINDOW_STEP_S", "1")))
_SILENCE_DBFS_THRESHOLD = float(os.environ.get("SHAQCAST_SILENCE_DBFS_THRESHOLD", "-55.0"))
_MIN_REQUEST_INTERVAL_S = float(os.environ.get("SHAQCAST_MIN_REQUEST_INTERVAL_S", "10.0"))
_MIN_REQUEST_INTERVAL_S = max(0.0, min(60.0, _MIN_REQUEST_INTERVAL_S))


@dataclass(frozen=True, slots=True)
class StreamSettings:
    host: str
    port: int
    password: str
    sids: list[int]
    source: str  # "output" (loopback) or "input" (microphone)
    device_id: str
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
) -> bytearray:
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
        include_loopback = self._settings.source != "input"
        label = "loopback" if include_loopback else "microphone"

        try:
            if include_loopback:
                device_name = sc.get_speaker(self._settings.device_id).name
            else:
                device_name = sc.get_microphone(self._settings.device_id).name
        except Exception as exc:
            self._log(f"Audio init failed: {exc}")
            return

        self._log(f"Listening ({label}): {device_name}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        segment_duration_s = min(
            max(3, int(self._settings.listen_seconds)),
            max(3, min(60, int(self._settings.shazam_segment_seconds))),
        )
        shazam = Shazam(
            language=self._settings.language,
            endpoint_country=self._settings.endpoint_country,
            segment_duration_seconds=segment_duration_s,
        )
        last_request_at = 0.0
        consecutive_recognition_errors = 0

        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                audio = _capture_wav_bytes(
                    device_id=self._settings.device_id,
                    include_loopback=include_loopback,
                    duration_s=self._settings.listen_seconds,
                    sample_rate_hz=self._settings.sample_rate_hz,
                    channels=self._settings.channels,
                    chunk_frames=self._settings.chunk_frames,
                )
            except Exception as exc:
                self._log(f"Audio capture failed: {exc}")
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
                        raw = loop.run_until_complete(shazam.recognize(window_audio))
                        track = Serialize.full_track(raw)
                        if track.matches:
                            break
                        raw = None
                        track = None
            except Exception as exc:
                consecutive_recognition_errors += 1
                text = str(exc).strip()
                lowered = text.lower()
                is_rate_limit = (
                    "429" in lowered
                    or "too many requests" in lowered
                    or "failed to decode json" in lowered
                )

                backoff_s = min(
                    300.0,
                    5.0 * (2.0 ** max(0, consecutive_recognition_errors - 1)),
                )
                if is_rate_limit:
                    backoff_s = max(backoff_s, 30.0)

                detail = f": {text}" if text else ""
                self._log(f"Recognition failed, backing off {int(backoff_s)}s{detail}")
                self._stop_event.wait(backoff_s)
                continue

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
                for sid in self._settings.sids:
                    result = update_now_playing(
                        host=self._settings.host,
                        port=self._settings.port,
                        password=self._settings.password,
                        sid=sid,
                        song=fallback,
                    )
                    if result.ok:
                        self._log(f"[sid {sid}] updated ({result.method})")
                    else:
                        status = result.status if result.status is not None else "n/a"
                        self._log(f"[sid {sid}] update failed ({result.method}, status={status})")

                self._last_track_sent = fallback
                continue

            consecutive_recognition_errors = 0
            now_playing = f"{track.track.subtitle} - {track.track.title}"
            if now_playing == self._last_track_sent:
                self._log(f"Unchanged: {now_playing}")
                continue

            self._log(f"Recognized: {now_playing}")
            for sid in self._settings.sids:
                result = update_now_playing(
                    host=self._settings.host,
                    port=self._settings.port,
                    password=self._settings.password,
                    sid=sid,
                    song=now_playing,
                )
                if result.ok:
                    self._log(f"[sid {sid}] updated ({result.method})")
                else:
                    status = result.status if result.status is not None else "n/a"
                    self._log(f"[sid {sid}] update failed ({result.method}, status={status})")

            self._last_track_sent = now_playing
