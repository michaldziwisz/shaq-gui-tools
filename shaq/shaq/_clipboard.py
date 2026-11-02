"""Bezpieczne kopiowanie tekstu do systemowego schowka przez wxPython."""

from __future__ import annotations


def copy_text(text: str) -> bool:
    """Kopiuje niepusty tekst Unicode; niedostępny schowek zwraca False.

    Nieprawidłowy typ powoduje TypeError, pusty tekst lub znak NUL — ValueError.
    Wywołanie wymaga uruchomionej aplikacji wxPython i jej wątku interfejsu.
    """
    if not isinstance(text, str):
        raise TypeError("Tekst do skopiowania musi być napisem.")
    if not text.strip() or "\x00" in text:
        raise ValueError("Tekst nie może być pusty ani zawierać znaku NUL.")

    import wx

    clipboard = wx.TheClipboard
    if clipboard is None:
        return False
    try:
        if not clipboard.Open():
            return False
        try:
            copied = bool(clipboard.SetData(wx.TextDataObject(text)))
        finally:
            clipboard.Close()
    except (RuntimeError, AssertionError):
        return False

    if copied:
        try:
            clipboard.Flush()
        except (RuntimeError, AssertionError):
            # Błąd utrwalania nie cofa udanego kopiowania w bieżącej sesji.
            pass
    return copied
