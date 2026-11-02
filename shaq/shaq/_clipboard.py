"""Kopiowanie tekstu bez zależności schowka Windows od inicjalizacji COM audio."""

from __future__ import annotations

import ctypes
from functools import lru_cache
from sys import platform as _platform
from time import sleep
from typing import Any


def copy_text(text: str, owner: int) -> bool:
    """Kopiuje niepusty tekst Unicode; niedostępny schowek zwraca False.

    owner jest uchwytem kontrolki wywołującej kopiowanie. Błędny typ powoduje
    TypeError, niepoprawna wartość — ValueError. Wywołanie wymaga wątku GUI.
    Na Windows używa Win32, aby nie kolidować z trybem COM modułu soundcard.
    """
    if not isinstance(text, str):
        raise TypeError("Tekst do skopiowania musi być napisem.")
    if not text.strip() or "\x00" in text:
        raise ValueError("Tekst nie może być pusty ani zawierać znaku NUL.")
    if not isinstance(owner, int) or isinstance(owner, bool):
        raise TypeError("Uchwyt kontrolki musi być liczbą całkowitą.")
    if not 0 < owner < (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)):
        raise ValueError("Uchwyt kontrolki musi być niezerowym uchwytem systemowym.")
    if _platform == "win32":
        return _copy_windows(text, owner)
    return _copy_wx(text)


@lru_cache(maxsize=1)
def _windows_api() -> tuple[Any, Any]:
    """Wiąże funkcje Win32 z typami zachowującymi pełną szerokość uchwytów."""
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _copy_windows(text: str, owner: int) -> bool:
    """Przekazuje Windows bufor UTF-16, zwalniając go samodzielnie tylko po błędzie."""
    data = text.encode("utf-16-le") + b"\x00\x00"
    user32, kernel32 = _windows_api()
    block = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    if not block:
        return False
    try:
        pointer = kernel32.GlobalLock(block)
        if not pointer:
            return False
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel32.GlobalUnlock(block)
        for attempt in range(6):
            if user32.OpenClipboard(owner):
                break
            if attempt == 5:
                return False
            sleep(0.02)
        try:
            if not user32.EmptyClipboard():
                return False
            if not user32.SetClipboardData(13, block):  # CF_UNICODETEXT
                return False
            block = None  # Od tej chwili pamięć należy do systemowego schowka.
            return True
        finally:
            user32.CloseClipboard()
    finally:
        if block:
            kernel32.GlobalFree(block)


def _copy_wx(text: str) -> bool:
    """Kopiuje tekst przez wxPython na pozostałych platformach."""
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
