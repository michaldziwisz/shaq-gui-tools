"""Sprawdza tekst Unicode, zajęty schowek i zwalnianie go po niepowodzeniu."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from shaq._clipboard import copy_text


@pytest.fixture
def clipboard(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Podstawia schowek bez odczytywania ani zmiany danych użytkownika."""
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
    assert copy_text(text)
    assert clipboard.SetData.call_args.args[0].text == text
    assert [call[0] for call in clipboard.mock_calls] == ["Open", "SetData", "Close", "Flush"]


@pytest.mark.parametrize("raises", [False, True])
def test_busy_clipboard_does_not_modify_or_close_it(clipboard: Mock, raises: bool) -> None:
    clipboard.Open.return_value = False
    if raises:
        clipboard.Open.side_effect = RuntimeError("Schowek jest zajęty")
    assert not copy_text("Utwór")
    clipboard.SetData.assert_not_called()
    clipboard.Close.assert_not_called()
    clipboard.Flush.assert_not_called()


@pytest.mark.parametrize("raises", [False, True])
def test_failed_write_still_releases_clipboard(clipboard: Mock, raises: bool) -> None:
    clipboard.SetData.return_value = False
    if raises:
        clipboard.SetData.side_effect = RuntimeError("Nie udało się zapisać")
    assert not copy_text("Utwór")
    clipboard.Close.assert_called_once_with()
    clipboard.Flush.assert_not_called()


def test_data_conversion_failure_releases_clipboard(clipboard: Mock) -> None:
    sys.modules["wx"].TextDataObject = Mock(side_effect=RuntimeError("Błąd systemu"))
    assert not copy_text("Utwór")
    clipboard.Close.assert_called_once_with()


def test_close_failure_is_reported(clipboard: Mock) -> None:
    clipboard.Close.side_effect = RuntimeError("Błąd zwalniania schowka")
    assert not copy_text("Utwór")


def test_native_assertion_is_reported_and_releases_clipboard(clipboard: Mock) -> None:
    clipboard.SetData.side_effect = AssertionError("Błąd natywnego interfejsu wx")
    assert not copy_text("Utwór")
    clipboard.Close.assert_called_once_with()


@pytest.mark.parametrize("raises", [False, True])
def test_failed_flush_keeps_successful_copy_result(clipboard: Mock, raises: bool) -> None:
    clipboard.Flush.return_value = False
    if raises:
        clipboard.Flush.side_effect = RuntimeError("Utrwalanie jest niedostępne")
    assert copy_text("Utwór")
    clipboard.Close.assert_called_once_with()


def test_missing_clipboard_is_reported(clipboard: Mock) -> None:
    sys.modules["wx"].TheClipboard = None
    assert not copy_text("Utwór")
    assert not clipboard.mock_calls


@pytest.mark.parametrize("value", [None, 1, [], b"Utwor"])
def test_copy_rejects_invalid_type(value: Any) -> None:
    with pytest.raises(TypeError):
        copy_text(value)


@pytest.mark.parametrize("value", ["", " \t\n", "\x00", "Tytuł\x00Dalsza część"])
def test_copy_rejects_empty_or_truncated_text(value: str) -> None:
    with pytest.raises(ValueError):
        copy_text(value)
