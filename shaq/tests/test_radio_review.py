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


@pytest.mark.parametrize("pointer_size", [4, 8])
@pytest.mark.parametrize("variable", ["ProgramFiles", "ProgramFiles(x86)"])
def test_zdsr_uses_only_installed_library_for_process_architecture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pointer_size: int,
    variable: str,
) -> None:
    """Obcy proces o nazwie ZDSR i katalog roboczy nie wskazują biblioteki czytnika."""
    installed = tmp_path / "programs" / "zdsr" / "zdsr"
    installed.mkdir(parents=True)
    for name in ("ZDSRAPI.dll", "ZDSRAPI_x64.dll"):
        (installed / name).write_bytes(b"instalacja")
        (tmp_path / name).write_bytes(b"obcy plik")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(
            EnumProcesses=Mock(side_effect=AssertionError("Nie należy przeglądać procesów.")),
        ),
    )
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, str(tmp_path / "programs"))
    monkeypatch.setattr(ctypes, "sizeof", lambda _: pointer_size)
    filename = "ZDSRAPI_x64.dll" if pointer_size == 8 else "ZDSRAPI.dll"
    assert _zdsr_output._installed_library() == installed / filename


@pytest.mark.parametrize("directory", [None, "relative/path", "missing"])
def test_missing_or_invalid_zdsr_installation_uses_bundled_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    directory: str | None,
) -> None:
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    if directory is not None:
        monkeypatch.setenv(
            "ProgramFiles", str(tmp_path / directory) if directory == "missing" else directory
        )
    library = SimpleNamespace(InitTTS=Mock(), GetSpeakState=Mock(), Speak=Mock())
    factory = Mock(return_value=SimpleNamespace(lib=library))
    loader = Mock(side_effect=AssertionError("Nie wolno ładować obcej biblioteki."))
    monkeypatch.setattr(ctypes, "WinDLL", loader, raising=False)
    output = _zdsr_output.create_output(factory)
    assert output._library is library and not output._modern
    factory.assert_called_once()
    loader.assert_not_called()


def test_zdsr_rejects_installation_link_outside_program_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Rozwiązany cel dowiązania musi pozostawać wewnątrz Program Files."""
    root = tmp_path / "programs"
    root.mkdir()
    outside = tmp_path / "outside.dll"
    outside.write_bytes(b"obcy plik")
    original = Path.resolve
    monkeypatch.setenv("ProgramFiles", str(root))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, **kwargs: outside if path.suffix == ".dll" else original(path, **kwargs),
    )
    assert _zdsr_output._installed_library() is None
