from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


_APP_NAME = "shaqcast"
_CONFIG_VERSION = 1
_DPAPI_ENTROPY = b"shaqcast"


def config_version() -> int:
    return _CONFIG_VERSION


def config_path() -> Path:
    if os.name == "nt" and (appdata := os.environ.get("APPDATA")):
        return Path(appdata) / _APP_NAME / "config.json"

    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / _APP_NAME / "config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent)) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def encrypt_secret(secret: str) -> str:
    secret = secret or ""
    if not secret:
        return ""
    raw = secret.encode("utf-8")

    if os.name != "nt":
        return "b64:" + base64.b64encode(raw).decode("ascii")

    try:
        encrypted = _dpapi_encrypt(raw, entropy=_DPAPI_ENTROPY)
    except Exception:
        return "b64:" + base64.b64encode(raw).decode("ascii")

    return "dpapi:" + base64.b64encode(encrypted).decode("ascii")


def decrypt_secret(token: str) -> str:
    token = token or ""
    if not token:
        return ""

    if token.startswith("dpapi:"):
        payload = token.removeprefix("dpapi:")
        try:
            encrypted = base64.b64decode(payload.encode("ascii"))
        except Exception:
            return ""
        try:
            raw = _dpapi_decrypt(encrypted, entropy=_DPAPI_ENTROPY)
        except Exception:
            return ""
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""

    if token.startswith("b64:"):
        payload = token.removeprefix("b64:")
        try:
            raw = base64.b64decode(payload.encode("ascii"))
        except Exception:
            return ""
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""

    return token


def _dpapi_encrypt(data: bytes, *, entropy: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    def blob_from_bytes(value: bytes) -> tuple[DATA_BLOB, Any]:
        buf = ctypes.create_string_buffer(value)
        blob = DATA_BLOB(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        return blob, buf

    in_blob, _in_buf = blob_from_bytes(data)
    entropy_blob, _entropy_buf = blob_from_bytes(entropy)
    out_blob = DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_decrypt(data: bytes, *, entropy: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    def blob_from_bytes(value: bytes) -> tuple[DATA_BLOB, Any]:
        buf = ctypes.create_string_buffer(value)
        blob = DATA_BLOB(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        return blob, buf

    in_blob, _in_buf = blob_from_bytes(data)
    entropy_blob, _entropy_buf = blob_from_bytes(entropy)
    out_blob = DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)

