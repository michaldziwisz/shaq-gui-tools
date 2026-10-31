"""Powiadomienia UI Automation dla Narratora i innych klientów dostępności Windows."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def _release(pointer: ctypes.c_void_p) -> None:
    if pointer.value:
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])
        release(pointer)


def notify(hwnd: int, text: str) -> bool:
    """Zgłasza wynik przez dostępny obiekt kontrolki, bez zmiany fokusu i zaznaczenia."""
    if isinstance(hwnd, bool) or not isinstance(hwnd, int):
        raise TypeError("Uchwyt kontrolki musi być liczbą całkowitą.")
    if hwnd <= 0:
        raise ValueError("Uchwyt kontrolki musi być dodatni.")
    if not isinstance(text, str):
        raise TypeError("Tekst powiadomienia musi być napisem.")
    if sys.platform != "win32" or not text.strip():
        return False

    try:
        ole32 = ctypes.WinDLL("ole32")
        oleaut32 = ctypes.WinDLL("oleaut32")
        uia = ctypes.WinDLL("UIAutomationCore")
        raise_event = uia.UiaRaiseNotificationEvent
    except (OSError, AttributeError):
        return False

    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    oleaut32.SysAllocString.argtypes = [ctypes.c_wchar_p]
    oleaut32.SysAllocString.restype = ctypes.c_void_p
    oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
    oleaut32.SysFreeString.restype = None
    uia.UiaHostProviderFromHwnd.argtypes = [wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)]
    uia.UiaHostProviderFromHwnd.restype = ctypes.c_long
    uia.UiaClientsAreListening.argtypes = []
    uia.UiaClientsAreListening.restype = wintypes.BOOL
    raise_event.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    raise_event.restype = ctypes.c_long

    provider = ctypes.c_void_p()
    message = activity = None
    initialized = ole32.CoInitializeEx(None, 2) >= 0
    try:
        if not uia.UiaClientsAreListening():
            return False
        result = uia.UiaHostProviderFromHwnd(hwnd, ctypes.byref(provider))
        if result < 0 or not provider.value:
            return False
        message = oleaut32.SysAllocString(text)
        activity = oleaut32.SysAllocString("shaqgui.recognition")
        if not message or not activity:
            return False
        # Zakończona czynność; odczyt ostatniego wyniku po bieżącej wypowiedzi.
        return raise_event(provider, 2, 4, message, activity) >= 0
    finally:
        if message:
            oleaut32.SysFreeString(message)
        if activity:
            oleaut32.SysFreeString(activity)
        _release(provider)
        if initialized:
            ole32.CoUninitialize()
