from __future__ import annotations

import os
import shutil
import subprocess
import sys
import wave
from io import BytesIO
from pathlib import Path
from typing import Any


class FfmpegNotFoundError(RuntimeError):
    pass


def _candidate_input_formats(input_path: Path) -> list[str | None]:
    suffix = input_path.suffix.lower()
    if suffix == ".loas":
        candidates: list[str | None] = ["loas", None]
    elif suffix == ".latm":
        candidates = ["latm", "loas", None]
    elif suffix == ".aac":
        candidates = [None, "aac", "loas", "latm"]
    elif suffix == ".ts":
        candidates = [None, "mpegts"]
    else:
        candidates = [None]

    seen: set[str | None] = set()
    ordered: list[str | None] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _should_try_big_probe(input_path: Path) -> bool:
    return input_path.suffix.lower() == ".ts"


def _should_try_post_seek(input_path: Path) -> bool:
    return input_path.suffix.lower() in {".aac", ".loas", ".latm"}


def _windows_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _ffmpeg_timeout_seconds(*, duration_s: int) -> float:
    # Allow overhead for probing/seeking, but avoid hanging forever.
    base = max(60.0, (float(duration_s) * 10.0) + 60.0)
    return min(base, 15.0 * 60.0)


def _bundled_tool(name: str) -> str | None:
    if not getattr(sys, "frozen", False):
        return None

    candidates: list[Path] = []
    ext = ".exe" if os.name == "nt" else ""

    if meipass := getattr(sys, "_MEIPASS", None):
        candidates.append(Path(meipass) / f"{name}{ext}")
        candidates.append(Path(meipass) / name)

    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / f"{name}{ext}")
    candidates.append(exe_dir / name)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def require_ffmpeg() -> tuple[str, str | None]:
    ffmpeg = os.environ.get("SHAQ_FFMPEG") or _bundled_tool("ffmpeg") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise FfmpegNotFoundError("ffmpeg not found (bundled or on $PATH)")

    ffprobe = os.environ.get("SHAQ_FFPROBE") or _bundled_tool("ffprobe") or shutil.which("ffprobe")
    return ffmpeg, ffprobe


def probe_duration_seconds(input_path: Path) -> float | None:
    _, ffprobe = require_ffmpeg()
    if not ffprobe:
        return None

    for input_format in _candidate_input_formats(input_path):
        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
        ]
        if input_format:
            cmd.extend(["-f", input_format])
        cmd.append(str(input_path))

        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=30.0,
                **_windows_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired:
            continue
        if proc.returncode != 0:
            continue

        raw = proc.stdout.strip()
        try:
            duration_s = float(raw)
        except ValueError:
            continue

        if duration_s <= 0:
            continue
        return duration_s

    return None


def extract_wav_segment(
    input_path: Path,
    *,
    start_s: int,
    duration_s: int,
    sample_rate: int = 16000,
    channels: int = 1,
) -> bytes | None:
    ffmpeg, _ = require_ffmpeg()

    last_error: str | None = None
    attempts: list[str] = []

    probe_options: list[tuple[str, str] | None] = [None]
    if _should_try_big_probe(input_path):
        probe_options.append(("20M", "20M"))

    seek_modes: list[str] = ["pre"]
    if _should_try_post_seek(input_path):
        seek_modes.append("post")

    for input_format in _candidate_input_formats(input_path):
        for probe in probe_options:
            for seek_mode in seek_modes:
                cmd = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-fflags",
                    "+discardcorrupt",
                    "-err_detect",
                    "ignore_err",
                ]

                label = input_format or "auto"
                if probe is not None:
                    analyzeduration, probesize = probe
                    cmd.extend(["-analyzeduration", analyzeduration, "-probesize", probesize])
                    label = f"{label}+probe{probesize}"
                label = f"{label}+seek{seek_mode}"
                attempts.append(label)

                if seek_mode == "pre":
                    cmd.extend(["-ss", str(start_s), "-t", str(duration_s)])
                if input_format:
                    cmd.extend(["-f", input_format])
                cmd.extend(["-i", str(input_path)])
                if seek_mode == "post":
                    cmd.extend(["-ss", str(start_s), "-t", str(duration_s)])

                cmd.extend(
                    [
                        "-vn",
                        "-sn",
                        "-dn",
                        "-map",
                        "0:a:0",
                        "-ac",
                        str(channels),
                        "-ar",
                        str(sample_rate),
                        "-c:a",
                        "pcm_s16le",
                        "-f",
                        "s16le",
                        "pipe:1",
                    ]
                )

                try:
                    proc = subprocess.run(
                        cmd,
                        check=False,
                        capture_output=True,
                        timeout=_ffmpeg_timeout_seconds(duration_s=duration_s),
                        **_windows_subprocess_kwargs(),
                    )
                except subprocess.TimeoutExpired:
                    last_error = "ffmpeg timeout"
                    continue

                if proc.returncode != 0:
                    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                    last_error = stderr or "ffmpeg failed"
                    continue

                pcm_bytes = proc.stdout
                if not isinstance(pcm_bytes, (bytes, bytearray)):
                    raise RuntimeError("ffmpeg returned unexpected output")
                pcm_bytes = bytes(pcm_bytes)
                if not pcm_bytes:
                    return None

                frame_size = channels * 2
                if frame_size <= 0:
                    raise RuntimeError("invalid audio frame size")
                pcm_bytes = pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % frame_size)]
                if not pcm_bytes:
                    return None

                with BytesIO() as out_io:
                    with wave.open(out_io, "wb") as wav_out:
                        wav_out.setnchannels(channels)
                        wav_out.setsampwidth(2)
                        wav_out.setframerate(sample_rate)
                        wav_out.writeframes(pcm_bytes)
                    wav_bytes = out_io.getvalue()
                try:
                    with wave.open(BytesIO(wav_bytes), "rb") as wav:
                        if wav.getnframes() <= 0:
                            return None
                except wave.Error:
                    return None

                return wav_bytes

    detail = f" (próbowałem: {', '.join(attempts)})" if len(attempts) > 1 else ""
    raise RuntimeError(f"{last_error or 'ffmpeg failed'}{detail}")


def slice_wav_bytes(
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


def format_hms(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
