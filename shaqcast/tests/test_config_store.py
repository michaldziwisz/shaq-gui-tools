from __future__ import annotations

import os

from shaqcast.config_store import config_path, decrypt_secret, encrypt_secret, load_config, save_config


def _set_test_config_dir(monkeypatch, tmp_path) -> None:
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("APPDATA", raising=False)


def test_config_roundtrip(monkeypatch, tmp_path) -> None:
    _set_test_config_dir(monkeypatch, tmp_path)

    save_config({"x": 1})
    assert load_config() == {"x": 1}
    assert config_path().name == "config.json"


def test_encrypt_decrypt_secret_roundtrip() -> None:
    secret = "p@ssw0rd!"
    token = encrypt_secret(secret)
    assert token.startswith(("dpapi:", "b64:"))
    assert decrypt_secret(token) == secret


def test_decrypt_secret_fallbacks() -> None:
    assert decrypt_secret("") == ""
    assert decrypt_secret("plain") == "plain"
    assert decrypt_secret("b64:not-base64") == ""
