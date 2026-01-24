from __future__ import annotations

from shaqcast.icecast import _looks_successful


def test_looks_successful_basic() -> None:
    assert _looks_successful(200, "OK") is True
    assert _looks_successful(204, "") is True


def test_looks_successful_rejects_errors() -> None:
    assert _looks_successful(None, "OK") is False
    assert _looks_successful(401, "OK") is False
    assert _looks_successful(200, "Invalid password") is False
    assert _looks_successful(200, "ERROR something") is False
