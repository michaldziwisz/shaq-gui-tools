"""Regresje uwag recenzji: tłumaczenia radia i niezależne wykrywanie ZDSR."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from string import Formatter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shaq import _radio_playlist, _radio_stream, _zdsr_output
from shaq._i18n import I18n
from shaq._radio_messages import _STRINGS, default_translate
from shaq._radio_preview import RadioPreview


def test_radio_catalog_translates_every_message_and_preserves_parameters() -> None:
    formatter = Formatter()
    for key, entry in _STRINGS.items():
        assert set(entry) == {"pl", "en"}, key
        assert entry["pl"] and entry["en"], key
        fields = [
            {name for _, name, _, _ in formatter.parse(entry[lang]) if name}
            for lang in ("pl", "en")
        ]
        assert fields[0] == fields[1], key
    assert "4 s" in default_translate("radio.failed", seconds=4)
    assert default_translate("nieznany {klucz}") == "nieznany {klucz}"


@pytest.mark.parametrize(
    "data,fragment",
    [
        (b"", "no valid"),
        (b"#EXTM3U\n#EXT-X-VERSION:3", "HLS"),
        (b"[playlist]\nbroken", "Unable to read"),
        (b"x" * (_radio_playlist.MAX_PLAYLIST_BYTES + 1), "too large"),
    ],
)
def test_playlist_errors_use_selected_language(data: bytes, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        _radio_playlist.parse_playlist(data, translate=I18n("en", _STRINGS).t)


def test_missing_decoder_and_preview_errors_use_selected_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = I18n("en", _STRINGS).t
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(_radio_stream, "_bundled_tool", lambda _name: None)
    monkeypatch.setattr(_radio_stream.shutil, "which", lambda _name: None)
    monkeypatch.delenv("SHAQ_FFMPEG", raising=False)
    with pytest.raises(RuntimeError, match="bundled FFmpeg decoder is missing"):
        _radio_stream.RadioStream(
            "http://radio.example/live", on_status=lambda _: None, translate=t
        )
    preview = RadioPreview(25, finished=lambda _: None, translate=t)
    with pytest.raises(ValueError, match="between 0 and 100"):
        preview.set_volume(101)
    with pytest.raises(TypeError, match="integer"):
        preview.set_volume(True)
    with pytest.raises(ValueError, match="Enter a valid"):
        _radio_playlist.validate_stream_url("file:///bad", translate=t)


def test_reader_discovery_skips_denied_processes_and_closes_handles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ordinary = SimpleNamespace(Close=Mock(), path=tmp_path / "player.exe")
    reader = SimpleNamespace(Close=Mock(), path=tmp_path / "reader" / "ZDSR.exe")
    opener = Mock(side_effect=[OSError("Brak dostępu"), ordinary, reader])
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=OSError))
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(OpenProcess=opener))
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(
            EnumProcesses=lambda: [1, 2, 3],
            GetModuleFileNameEx=lambda handle, _module: str(handle.path),
        ),
    )
    assert _zdsr_output._running_reader_directories() == [reader.path.parent]
    ordinary.Close.assert_called_once()
    reader.Close.assert_called_once()


def test_reader_discovery_tolerates_missing_library_and_enumeration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "win32api", None)
    assert _zdsr_output._running_reader_directories() == []
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=OSError))
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(
            EnumProcesses=Mock(side_effect=OSError("Brak dostępu")),
        ),
    )
    assert _zdsr_output._running_reader_directories() == []


def test_installed_reader_library_prefers_running_reader_then_install_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    filename = "ZDSRAPI_x64.dll" if ctypes.sizeof(ctypes.c_void_p) == 8 else "ZDSRAPI.dll"
    active = tmp_path / "portable"
    installed = tmp_path / "programs" / "zdsr" / "zdsr"
    active.mkdir()
    installed.mkdir(parents=True)
    (active / filename).write_bytes(b"test")
    (installed / filename).write_bytes(b"test")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "programs"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(_zdsr_output, "_running_reader_directories", lambda: [active])
    assert _zdsr_output._installed_library() == active / filename
    monkeypatch.setattr(_zdsr_output, "_running_reader_directories", lambda: [])
    assert _zdsr_output._installed_library() == installed / filename
    monkeypatch.delenv("ProgramFiles")
    assert _zdsr_output._installed_library() is None
