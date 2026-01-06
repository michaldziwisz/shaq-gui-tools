from __future__ import annotations

import wave
from io import BytesIO
from pathlib import Path

from shaq._file_scan import (
    _candidate_input_formats,
    _ffmpeg_timeout_seconds,
    _should_try_big_probe,
    _should_try_post_seek,
    format_hms,
    slice_wav_bytes,
)


def _make_wav_bytes(*, sample_rate: int, channels: int, seconds: int) -> bytes:
    frames = b"\x00\x00" * (sample_rate * channels * seconds)
    with BytesIO() as io:
        with wave.open(io, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(frames)
        return io.getvalue()


def test_candidate_input_formats_aac() -> None:
    assert _candidate_input_formats(Path("x.aac")) == [None, "aac", "loas", "latm"]


def test_candidate_input_formats_latm() -> None:
    assert _candidate_input_formats(Path("x.latm")) == ["latm", "loas", None]


def test_candidate_input_formats_loas() -> None:
    assert _candidate_input_formats(Path("x.loas")) == ["loas", None]


def test_candidate_input_formats_ts() -> None:
    assert _candidate_input_formats(Path("x.ts")) == [None, "mpegts"]


def test_probe_seek_strategy() -> None:
    assert _should_try_big_probe(Path("x.ts")) is True
    assert _should_try_big_probe(Path("x.mp3")) is False

    assert _should_try_post_seek(Path("x.aac")) is True
    assert _should_try_post_seek(Path("x.latm")) is True
    assert _should_try_post_seek(Path("x.loas")) is True
    assert _should_try_post_seek(Path("x.wav")) is False


def test_ffmpeg_timeout_seconds_caps() -> None:
    assert _ffmpeg_timeout_seconds(duration_s=1) == 70.0
    assert _ffmpeg_timeout_seconds(duration_s=100) == 900.0


def test_slice_wav_bytes_basic() -> None:
    original = _make_wav_bytes(sample_rate=10, channels=1, seconds=2)
    sliced = slice_wav_bytes(original, start_s=1, duration_s=1)
    assert sliced is not None

    with wave.open(BytesIO(sliced), "rb") as wav:
        assert wav.getframerate() == 10
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 10


def test_slice_wav_bytes_out_of_range() -> None:
    original = _make_wav_bytes(sample_rate=10, channels=1, seconds=2)
    assert slice_wav_bytes(original, start_s=10, duration_s=1) is None


def test_slice_wav_bytes_invalid_returns_none() -> None:
    assert slice_wav_bytes(b"not a wav", start_s=0, duration_s=1) is None


def test_format_hms() -> None:
    assert format_hms(0) == "00:00:00"
    assert format_hms(3661) == "01:01:01"
    assert format_hms(-5) == "00:00:00"
