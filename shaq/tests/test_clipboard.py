"""Sprawdza tekst Unicode, zajęty schowek i zwalnianie go po niepowodzeniu."""

from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from shaq import _clipboard
from shaq._clipboard import copy_text


@pytest.fixture
def clipboard(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Podstawia schowek bez odczytywania ani zmiany danych użytkownika."""
    monkeypatch.setattr(_clipboard, "_platform", "linux")
    clipboard = Mock()
    clipboard.Open.return_value = True
    clipboard.SetData.return_value = True
    clipboard.Flush.return_value = True
    monkeypatch.setitem(
        sys.modules,
        "wx",
        SimpleNamespace(
            TheClipboard=clipboard,
            TextDataObject=lambda text: SimpleNamespace(text=text),
        ),
    )
    return clipboard


@pytest.mark.parametrize(
    "text", ["Tytuł", "Artysta - Gość - Tytuł - wersja koncertowa", "Żółć / 東京 🎵", "  Utwór  "]
)
def test_copy_preserves_text_and_releases_clipboard(clipboard: Mock, text: str) -> None:
    assert copy_text(text, 123)
    assert clipboard.SetData.call_args.args[0].text == text
    assert [call[0] for call in clipboard.mock_calls] == ["Open", "SetData", "Close", "Flush"]


@pytest.mark.parametrize("raises", [False, True])
def test_busy_clipboard_does_not_modify_or_close_it(clipboard: Mock, raises: bool) -> None:
    clipboard.Open.return_value = False
    if raises:
        clipboard.Open.side_effect = RuntimeError("Schowek jest zajęty")
    assert not copy_text("Utwór", 123)
    clipboard.SetData.assert_not_called()
    clipboard.Close.assert_not_called()
    clipboard.Flush.assert_not_called()


@pytest.mark.parametrize("raises", [False, True])
def test_failed_write_still_releases_clipboard(clipboard: Mock, raises: bool) -> None:
    clipboard.SetData.return_value = False
    if raises:
        clipboard.SetData.side_effect = RuntimeError("Nie udało się zapisać")
    assert not copy_text("Utwór", 123)
    clipboard.Close.assert_called_once_with()
    clipboard.Flush.assert_not_called()


def test_data_conversion_failure_releases_clipboard(clipboard: Mock) -> None:
    sys.modules["wx"].TextDataObject = Mock(side_effect=RuntimeError("Błąd systemu"))
    assert not copy_text("Utwór", 123)
    clipboard.Close.assert_called_once_with()


def test_close_failure_is_reported(clipboard: Mock) -> None:
    clipboard.Close.side_effect = RuntimeError("Błąd zwalniania schowka")
    assert not copy_text("Utwór", 123)


def test_native_assertion_is_reported_and_releases_clipboard(clipboard: Mock) -> None:
    clipboard.SetData.side_effect = AssertionError("Błąd natywnego interfejsu wx")
    assert not copy_text("Utwór", 123)
    clipboard.Close.assert_called_once_with()


@pytest.mark.parametrize("raises", [False, True])
def test_failed_flush_keeps_successful_copy_result(clipboard: Mock, raises: bool) -> None:
    clipboard.Flush.return_value = False
    if raises:
        clipboard.Flush.side_effect = RuntimeError("Utrwalanie jest niedostępne")
    assert copy_text("Utwór", 123)
    clipboard.Close.assert_called_once_with()


def test_missing_clipboard_is_reported(clipboard: Mock) -> None:
    sys.modules["wx"].TheClipboard = None
    assert not copy_text("Utwór", 123)
    assert not clipboard.mock_calls


@pytest.mark.parametrize("value", [None, 1, [], b"Utwor"])
def test_copy_rejects_invalid_type(value: Any) -> None:
    with pytest.raises(TypeError):
        copy_text(value, 123)


@pytest.mark.parametrize("value", ["", " \t\n", "\x00", "Tytuł\x00Dalsza część"])
def test_copy_rejects_empty_or_truncated_text(value: str) -> None:
    with pytest.raises(ValueError):
        copy_text(value, 123)


@pytest.fixture
def windows_api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Udostępnia bufor UTF-16 bez zapisu do systemowego schowka."""
    buffer = ctypes.create_string_buffer(512)
    user32, kernel32 = Mock(), Mock()
    user32.OpenClipboard.return_value = True
    user32.EmptyClipboard.return_value = True
    user32.SetClipboardData.return_value = 1234
    kernel32.GlobalAlloc.return_value = 1234
    kernel32.GlobalLock.return_value = ctypes.addressof(buffer)
    monkeypatch.setattr(_clipboard, "_platform", "win32")
    monkeypatch.setattr(_clipboard, "sleep", Mock())
    monkeypatch.setattr(_clipboard, "_windows_api", lambda: (user32, kernel32))
    return SimpleNamespace(buffer=buffer, user32=user32, kernel32=kernel32)


def test_windows_retries_a_temporarily_busy_clipboard(windows_api: SimpleNamespace) -> None:
    windows_api.user32.OpenClipboard.side_effect = [False, False, True]
    assert copy_text("Utwór", 456)
    windows_api.user32.SetClipboardData.assert_called_once_with(13, 1234)
    windows_api.kernel32.GlobalFree.assert_not_called()


@pytest.mark.parametrize("text", ["Tytuł", "Żółć feat. 東京 - Tytuł 🎵", "  Utwór - remix  "])
def test_windows_copies_unicode_and_transfers_ownership(
    windows_api: SimpleNamespace, text: str
) -> None:
    assert copy_text(text, 456)
    data = text.encode("utf-16-le") + b"\x00\x00"
    assert windows_api.buffer.raw[: len(data)] == data
    windows_api.user32.OpenClipboard.assert_called_once_with(456)
    windows_api.user32.SetClipboardData.assert_called_once_with(13, 1234)
    windows_api.user32.CloseClipboard.assert_called_once_with()
    windows_api.kernel32.GlobalFree.assert_not_called()


@pytest.mark.parametrize("operation", ["GlobalAlloc", "GlobalLock"])
def test_windows_allocation_failure_keeps_clipboard_unchanged(
    windows_api: SimpleNamespace, operation: str
) -> None:
    getattr(windows_api.kernel32, operation).return_value = 0
    assert not copy_text("Utwór", 456)
    windows_api.user32.OpenClipboard.assert_not_called()
    if operation == "GlobalLock":
        windows_api.kernel32.GlobalFree.assert_called_once_with(1234)
    else:
        windows_api.kernel32.GlobalFree.assert_not_called()


@pytest.mark.parametrize("operation", ["OpenClipboard", "EmptyClipboard", "SetClipboardData"])
def test_windows_failure_releases_memory_and_only_closes_owned_clipboard(
    windows_api: SimpleNamespace, operation: str
) -> None:
    getattr(windows_api.user32, operation).return_value = 0
    assert not copy_text("Utwór", 456)
    windows_api.kernel32.GlobalFree.assert_called_once_with(1234)
    if operation == "OpenClipboard":
        windows_api.user32.CloseClipboard.assert_not_called()
        windows_api.user32.EmptyClipboard.assert_not_called()
    else:
        windows_api.user32.CloseClipboard.assert_called_once_with()


def test_windows_rejects_invalid_unicode_before_opening_clipboard(
    windows_api: SimpleNamespace,
) -> None:
    with pytest.raises(ValueError):
        copy_text("\ud800", 456)
    windows_api.user32.OpenClipboard.assert_not_called()
    windows_api.kernel32.GlobalAlloc.assert_not_called()


@pytest.mark.parametrize("owner", [None, "123", True])
def test_copy_rejects_invalid_owner_type(owner: Any) -> None:
    with pytest.raises(TypeError):
        copy_text("Tytuł", owner)


@pytest.mark.parametrize("owner", [0, -1, 1 << 100])
def test_copy_rejects_invalid_owner_value(owner: int) -> None:
    with pytest.raises(ValueError):
        copy_text("Tytuł", owner)
