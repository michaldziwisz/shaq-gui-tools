"""Rzeczywiste dekodowanie radia z lokalnego HTTP, bez odtwarzania dźwięku."""

from __future__ import annotations

import os
import subprocess
import threading
import time
import wave
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import Any

import pytest

from shaq import _radio_stream as radio

pytestmark = pytest.mark.skipif(
    os.environ.get("SHAQ_TEST_RADIO") != "1",
    reason="Test lokalnego HTTP wymaga FFmpeg i zmiennej SHAQ_TEST_RADIO=1.",
)


@pytest.fixture(scope="module")
def radio_server(tmp_path_factory: Any) -> Iterator[tuple[str, Any]]:
    root = tmp_path_factory.mktemp("radio")
    mp3 = root / "tone.mp3"
    aac = root / "tone.aac"
    ffmpeg = radio.radio_ffmpeg()
    for target in (mp3, aac):
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=750:sample_rate=48000",
                "-t",
                "15",
                "-ac",
                "2",
                str(target),
            ],
            check=True,
            capture_output=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    mp3_data = mp3.read_bytes()
    aac_data = aac.read_bytes()
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=750:sample_rate=48000",
            "-t",
            "6",
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            "-hls_segment_filename",
            str(root / "segment%d.ts"),
            str(root / "radio.m3u8"),
        ],
        check=True,
        capture_output=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    hls_files = {
        "/" + path.name: path.read_bytes()
        for path in root.iterdir()
        if path.suffix in {".m3u8", ".ts"}
    }
    stopping = threading.Event()
    counts: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            """Udostępnia próbki, playlisty, błędy i celowo zerwane połączenia."""
            counts[self.path] = counts.get(self.path, 0) + 1
            if self.path == "/missing":
                self.send_error(503)
                return
            if self.path == "/stall":
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.end_headers()
                stopping.wait(15)
                return
            if self.path == "/list.pls":
                content = b"[playlist]\nFile1=/list.m3u\nTitle1=Test\n"
            elif self.path in hls_files:
                content = hls_files[self.path]
            elif self.path == "/list.m3u":
                content = b"#EXTM3U\n/tone.mp3\n"
            elif self.path == "/tone.aac":
                content = aac_data
            elif self.path == "/retry.mp3" and counts[self.path] == 1:
                content = mp3_data[:16000]
            else:
                content = mp3_data
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, _format: str, *_args: Any) -> None:
            """Nie zapisuje rutynowego ruchu serwera testowego."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", counts
    finally:
        stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize(
    "suffix", ["/tone.mp3", "/tone.aac", "/list.pls", "/retry.mp3", "/radio.m3u8"]
)
def test_real_stream_decoding_playlists_and_reconnect(
    radio_server: tuple[str, Any],
    suffix: str,
) -> None:
    base, counts = radio_server
    statuses = []
    stream = radio.RadioStream(base + suffix, on_status=statuses.append)
    stop = threading.Event()
    deadline = threading.Timer(15, stop.set)
    stream.start()
    deadline.start()
    try:
        audio = stream.read_wav(duration_s=1.2, stop_event=stop)
        assert audio is not None, statuses
        with wave.open(BytesIO(audio), "rb") as wav:
            assert wav.getnframes() == 57600
            assert (wav.getframerate(), wav.getnchannels()) == (48000, 2)
            assert any(wav.readframes(wav.getnframes()))
        assert any("Połączono" in message for message in statuses)
        if suffix == "/retry.mp3":
            assert counts[suffix] >= 2
            assert any("Ponowna próba" in message for message in statuses)
    finally:
        deadline.cancel()
        stream.stop()
        stream.join()
    assert not stream._thread.is_alive()
    assert stream._process is None


@pytest.mark.parametrize("suffix", ["/stall", "/missing"])
def test_stop_interrupts_network_failure_without_orphan_decoder(
    radio_server: tuple[str, Any],
    suffix: str,
) -> None:
    base, _counts = radio_server
    entered = threading.Event()
    statuses = []

    def status(message: str) -> None:
        statuses.append(message)
        if "Brak transmisji" in message:
            entered.set()

    stream = radio.RadioStream(base + suffix, on_status=status)
    stream.start()
    try:
        if suffix == "/missing":
            assert entered.wait(5), statuses
        else:
            deadline = time.monotonic() + 3
            while stream._process is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert stream._process is not None
        started = time.monotonic()
        stream.stop()
        stream.join(2)
        assert time.monotonic() - started < 2
        assert not stream._thread.is_alive()
        assert stream._process is None
    finally:
        stream.stop()
        stream.join()


def test_watchdog_restarts_stream_that_stops_producing_audio(
    radio_server: tuple[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, counts = radio_server
    initial = counts.get("/stall", 0)
    monkeypatch.setattr(radio, "STALL_SECONDS", 0.3)
    stream = radio.RadioStream(base + "/stall", on_status=lambda _message: None)
    stream.start()
    try:
        deadline = time.monotonic() + 5
        while counts.get("/stall", 0) < initial + 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert counts.get("/stall", 0) >= initial + 2
    finally:
        stream.stop()
        stream.join()
