from __future__ import annotations

import os

import shaq._file_gui as file_gui
import shaq._gui as live_gui


def _set_test_config_dir(monkeypatch, tmp_path) -> None:
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("APPDATA", raising=False)


def test_save_and_load_config_roundtrip(monkeypatch, tmp_path) -> None:
    _set_test_config_dir(monkeypatch, tmp_path)

    file_gui._save_config({"hello": "world"})
    assert file_gui._load_config() == {"hello": "world"}


def test_load_config_invalid_json_returns_empty(monkeypatch, tmp_path) -> None:
    _set_test_config_dir(monkeypatch, tmp_path)

    path = file_gui._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert file_gui._load_config() == {}


def test_history_writer_dedupes(monkeypatch, tmp_path) -> None:
    history_path = tmp_path / "history.txt"
    history_path.write_text("a\n", encoding="utf-8")

    writer = live_gui._HistoryWriter(history_path)
    assert writer.append_unique("a") is False
    assert writer.append_unique("b") is True

    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["a", "b"]
