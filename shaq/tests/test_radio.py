"""Sprawdza playlisty, ciągłość próbek, limity pamięci i niezależność odsłuchu."""

from __future__ import annotations

import sys
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from shaq import _radio_playlist as playlist
from shaq import _radio_stream as radio
from shaq._radio_preview import RadioPreview


@pytest.mark.parametrize(
    "address, expected",
    [
        (" http://radio.example/live ", "http://radio.example/live"),
        (
            "https://radio.example:8000/live?token=a%2Fb#opis",
            "https://radio.example:8000/live?token=a%2Fb",
        ),
        ("icy://radio.example", "http://radio.example/"),
        ("http://[::1]:8000/radio", "http://[::1]:8000/radio"),
    ],
)
def test_valid_stream_addresses(address: str, expected: str) -> None:
    assert playlist.validate_stream_url(address) == expected


@pytest.mark.parametrize(
    "address",
    [
        "",
        "file:///secret",
        "ftp://radio/a",
        "http:///missing",
        "http://radio:bad/",
        "http://radio:0/",
        "http://radio/\nheader",
        "http://bad host/a",
    ],
)
def test_invalid_stream_addresses(address: str) -> None:
    with pytest.raises(ValueError):
        playlist.validate_stream_url(address)


def test_invalid_address_type() -> None:
    with pytest.raises(TypeError):
        playlist.validate_stream_url(None)


def test_pls_sorted_titles_percent_signs_and_duplicates() -> None:
    stations = playlist.parse_playlist(
        b"[playlist]\nFile2=https://radio.example/2\nTitle2=Druga\nFile1=http://radio.example/1?q=20%25\nTitle1=Pierwsza\nFile3=https://radio.example/2\nNumberOfEntries=3\n"
    )
    assert [station.title for station in stations] == ["Pierwsza", "Druga"]
    assert stations[0].url.endswith("?q=20%25")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1250", "utf-16"])
def test_m3u_names_encoding_relative_and_local_files(encoding: str) -> None:
    data = (
        "#EXTM3U\n#EXTINF:-1,Łódź\nhttps://radio.example/live\n"
        "# komentarz\nrelative.mp3\nC:\\music.wav\n"
    )
    stations = playlist.parse_playlist(data.encode(encoding))
    assert len(stations) == 1
    assert stations[0].title == "Łódź"
    assert (
        playlist.parse_playlist(b"../live", base_url="http://radio.example/list/station.m3u")[0].url
        == "http://radio.example/live"
    )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"#EXTM3U\n",
        b"[playlist]\nNumberOfEntries=0",
        b"#EXTM3U\n#EXT-X-TARGETDURATION:6\nsegment.ts",
        b"[playlist]\nbroken",
    ],
)
def test_invalid_or_empty_playlists(data: bytes) -> None:
    with pytest.raises(ValueError):
        playlist.parse_playlist(data)


def test_playlist_limits_and_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "large.m3u"
    path.write_bytes(b"#" * (playlist.MAX_PLAYLIST_BYTES + 1))
    with pytest.raises(ValueError, match="duża"):
        playlist.load_playlist(path)
    with pytest.raises(FileNotFoundError):
        playlist.load_playlist(tmp_path / "missing.pls")
    data = "\n".join(f"http://radio.example/{index}" for index in range(501)).encode()
    with pytest.raises(ValueError, match="dużo"):
        playlist.parse_playlist(data)
    with pytest.raises(TypeError):
        playlist.parse_playlist("not bytes")


def test_station_label_hides_password_and_query() -> None:
    station = playlist.RadioStation("http://user:secret@radio.example/a?token=secret", " Radio\nA ")
    assert station.label == "Radio A — radio.example/a"
    with pytest.raises(TypeError):
        playlist.RadioStation("http://radio.example", 3)


def test_remote_playlist_resolution_and_hls(monkeypatch: pytest.MonkeyPatch) -> None:
    contents = {
        "http://radio.example/a.pls": b"[playlist]\nFile1=/b.m3u\n",
        "http://radio.example/b.m3u": b"#EXTM3U\n/live.mp3\n",
        "http://radio.example/hls.m3u8": b"#EXTM3U\n#EXT-X-TARGETDURATION:6\nsegment.ts\n",
    }

    def open_url(request: Any, timeout: float) -> BytesIO:
        assert timeout <= 5
        response = BytesIO(contents[request.full_url])
        response.geturl = lambda: request.full_url
        return response

    monkeypatch.setattr(playlist, "build_opener", lambda *_a: SimpleNamespace(open=open_url))
    stop = threading.Event()
    assert (
        playlist.resolve_stream_url("http://radio.example/a.pls", stop)
        == "http://radio.example/live.mp3"
    )
    assert playlist.resolve_stream_url("http://radio.example/hls.m3u8", stop).endswith("hls.m3u8")
    contents["http://radio.example/b.m3u"] = b"a.pls"
    with pytest.raises(ValueError, match="samej siebie"):
        playlist.resolve_stream_url("http://radio.example/a.pls", stop)
    stop.set()
    assert playlist.resolve_stream_url("http://radio.example/a.pls", stop) is None


def _reader_ready(buffer: radio.StreamBuffer, monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    ready = threading.Event()
    original_wait = buffer._condition.wait

    def wait(timeout: float) -> bool:
        ready.set()
        return original_wait(timeout)

    monkeypatch.setattr(buffer._condition, "wait", wait)
    return ready


def _pcm(audio: bytes) -> bytes:
    with wave.open(BytesIO(audio), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 2, 2)
        return wav.readframes(wav.getnframes())


def test_buffer_uses_fresh_audio_after_recognition_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = radio.StreamBuffer()
    buffer.feed(b"\x01\x00" * 4800)
    ready = _reader_ready(buffer, monkeypatch)
    data = b"\x02\x00" * 4800
    with ThreadPoolExecutor() as pool:
        result = pool.submit(buffer.read_wav, 0.05, threading.Event())
        assert ready.wait(2)
        buffer.feed(data)
        assert _pcm(result.result(timeout=2)) == data


def test_buffer_reconnect_does_not_glue_fragments(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = radio.StreamBuffer()
    ready = _reader_ready(buffer, monkeypatch)
    with ThreadPoolExecutor() as pool:
        result = pool.submit(buffer.read_wav, 0.1, threading.Event())
        assert ready.wait(2)
        buffer.feed(b"\x01\x00" * 4800)
        buffer.reset()
        new_audio = b"\x02\x00" * 9600
        buffer.feed(new_audio)
        assert _pcm(result.result(timeout=2)) == new_audio


@pytest.mark.parametrize("operation", ["close", "stop"])
def test_buffer_wait_can_be_cancelled(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    buffer = radio.StreamBuffer()
    ready = _reader_ready(buffer, monkeypatch)
    stop = threading.Event()
    with ThreadPoolExecutor() as pool:
        result = pool.submit(buffer.read_wav, 60, stop)
        assert ready.wait(2)
        buffer.close() if operation == "close" else stop.set()
        assert result.result(timeout=1) is None


def test_buffer_is_bounded_and_ignores_data_after_close() -> None:
    buffer = radio.StreamBuffer()
    for _index in range(700):
        buffer.feed(b"\0" * radio.CHUNK_BYTES)
    assert buffer.buffered_bytes == radio.MAX_BUFFER_SECONDS * radio.BYTES_PER_SECOND
    buffer.close()
    buffer.feed(b"\0" * 4)
    assert buffer.buffered_bytes == 0
    assert buffer.read_wav(1, threading.Event()) is None
    with pytest.raises(ValueError):
        buffer.feed(b"x")
    with pytest.raises(TypeError):
        buffer.feed("xxxx")


@pytest.mark.parametrize("duration", [0, -1, 61, float("nan"), float("inf")])
def test_buffer_rejects_invalid_durations(duration: float) -> None:
    with pytest.raises(ValueError):
        radio.StreamBuffer().read_wav(duration, threading.Event())


@pytest.mark.parametrize("duration", [True, "12", None])
def test_buffer_rejects_invalid_duration_types(duration: Any) -> None:
    with pytest.raises(TypeError):
        radio.StreamBuffer().read_wav(duration, threading.Event())


def test_decoder_uses_only_pipe_for_output() -> None:
    command = radio.decoder_command("ffmpeg.exe", "http://radio.example/live?a=1&b=2")
    assert command[-1] == "pipe:1"
    assert command[command.index("-i") + 1].endswith("?a=1&b=2")
    assert command[command.index("-protocol_whitelist") + 1] == "http,https,tcp,tls,crypto"
    with pytest.raises(ValueError):
        radio.decoder_command("ffmpeg.exe", "-f bogus")


def test_packaged_decoder_without_path_and_invalid_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundled = tmp_path / "ffmpeg.exe"
    bundled.write_bytes(b"test")
    monkeypatch.setattr(radio, "_bundled_tool", lambda _name: str(bundled))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("SHAQ_FFMPEG", str(tmp_path / "missing.exe"))
    assert radio.radio_ffmpeg() == str(bundled.resolve())
    monkeypatch.setattr(radio, "_bundled_tool", lambda _name: None)
    monkeypatch.setattr(radio.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="pełną wersję"):
        radio.radio_ffmpeg()


def test_preview_does_not_change_recognition_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    np = pytest.importorskip("numpy")
    played = threading.Event()
    values = []
    finished = []

    class Player:
        def __enter__(self) -> Player:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def play(self, data: Any) -> None:
            values.append(data)
            played.set()

    speaker = SimpleNamespace(player=lambda **_kwargs: Player())
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(default_speaker=lambda: speaker))
    preview = RadioPreview(25, finished=finished.append)
    data = b"\x00\x40" * 9600
    preview.start()
    try:
        preview.feed(data)
        assert played.wait(3)
        assert np.all(values[0] == 0.125)
        assert data == b"\x00\x40" * 9600
        with pytest.raises(RuntimeError):
            preview.start()
    finally:
        preview.stop()
        preview.join()
    assert finished == [""]


def test_preview_queue_and_volume_edges() -> None:
    preview = RadioPreview(0, finished=lambda _message: None)
    for _index in range(100):
        preview.feed(b"\0" * radio.CHUNK_BYTES)
    assert preview._queue.qsize() == 3
    preview.set_volume(100)
    with pytest.raises(ValueError):
        preview.set_volume(101)
    with pytest.raises(TypeError):
        preview.set_volume(True)
    preview.stop()
    with pytest.raises(RuntimeError):
        preview.start()


def test_preview_failure_is_reported_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(default_speaker=lambda: None))
    finished = []
    preview = RadioPreview(10, finished=finished.append)
    preview.start()
    preview.join()
    assert len(finished) == 1 and "Nie można" in finished[0]
