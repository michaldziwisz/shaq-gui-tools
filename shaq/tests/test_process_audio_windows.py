"""Rzeczywisty test WASAPI, włączany zmienną SHAQ_TEST_PROCESS_AUDIO=1."""

from __future__ import annotations

import array
import math
import os
import subprocess
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest

from shaq._process_audio import (
    ProcessExitedError,
    ProcessInfo,
    list_processes,
    process_capture_supported,
)
from shaq._win_process_audio import capture_wav

pytestmark = pytest.mark.skipif(
    os.environ.get("SHAQ_TEST_PROCESS_AUDIO") != "1" or not process_capture_supported(),
    reason="Test odtwarza krótkie sygnały; wymaga jawnego włączenia na Windows.",
)


def _tone(path: Path, frequency: int) -> None:
    samples = array.array(
        "h",
        (int(1500 * math.sin(2 * math.pi * frequency * index / 16000)) for index in range(16000)),
    )
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(samples.tobytes())


def _play(path: Path, ready: Path) -> subprocess.Popen:
    code = (
        "import sys, time, winsound; from pathlib import Path; "
        "winsound.PlaySound(sys.argv[1], "
        "winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP); "
        "Path(sys.argv[2]).touch(); time.sleep(30)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(path), str(ready)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5
    while not ready.exists():
        if child.poll() is not None or time.monotonic() >= deadline:
            child.terminate()
            _, error = child.communicate(timeout=5)
            pytest.fail(f"Nie uruchomiono sygnału testowego: {error!r}")
        time.sleep(0.02)
    return child


def _info(child: subprocess.Popen) -> ProcessInfo:
    return next(item for item in list_processes() if item.pid == child.pid)


def _amplitude(samples: array.array, frequency: int) -> float:
    sine = sum(
        value * math.sin(2 * math.pi * frequency * index / 16000)
        for index, value in enumerate(samples)
    )
    cosine = sum(
        value * math.cos(2 * math.pi * frequency * index / 16000)
        for index, value in enumerate(samples)
    )
    return math.hypot(sine, cosine) / len(samples)


def test_real_wasapi_isolates_program_and_releases_after_stop(tmp_path: Path) -> None:
    target_file, other_file = tmp_path / "target.wav", tmp_path / "other.wav"
    _tone(target_file, 750)
    _tone(other_file, 1300)
    children: list[subprocess.Popen] = []
    try:
        target = _play(target_file, tmp_path / "target.ready")
        children.append(target)
        other = _play(other_file, tmp_path / "other.ready")
        children.append(other)
        time.sleep(0.2)
        info = _info(target)
        with ThreadPoolExecutor(max_workers=1) as pool:
            data = pool.submit(
                capture_wav,
                info,
                duration_s=0.8,
                sample_rate=16000,
                channels=1,
                stop_event=threading.Event(),
            ).result(timeout=15)
            with wave.open(BytesIO(data), "rb") as wav:
                assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
                assert wav.getnframes() == 12800
                samples = array.array("h", wav.readframes(wav.getnframes()))
            wanted, unrelated = _amplitude(samples, 750), _amplitude(samples, 1300)
            assert wanted > 10, f"Brak sygnału odtwarzacza: {wanted:.3f}"
            assert unrelated < wanted * 0.02, (
                f"Przesłuch innej aplikacji: {wanted:.3f}, {unrelated:.3f}"
            )
            event = threading.Event()
            timer = threading.Timer(0.1, event.set)
            timer.start()
            try:
                assert (
                    pool.submit(
                        capture_wav,
                        info,
                        duration_s=5,
                        sample_rate=16000,
                        channels=1,
                        stop_event=event,
                    ).result(timeout=3)
                    is None
                )
            finally:
                timer.cancel()
            target.terminate()
            target.wait(timeout=5)
            with pytest.raises(ProcessExitedError):
                pool.submit(
                    capture_wav,
                    info,
                    duration_s=0.5,
                    sample_rate=16000,
                    channels=1,
                    stop_event=threading.Event(),
                ).result(timeout=5)
            restarted = _play(target_file, tmp_path / "restarted.ready")
            children.append(restarted)
            new_info = _info(restarted)
            assert new_info.pid != info.pid
            assert pool.submit(
                capture_wav,
                new_info,
                duration_s=0.5,
                sample_rate=16000,
                channels=1,
                stop_event=threading.Event(),
            ).result(timeout=10)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=5)
