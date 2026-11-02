"""Regresja kopiowania w prawdziwym GUI po inicjalizacji dźwięku w trybie COM MTA."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("SHAQ_TEST_CLIPBOARD") != "1",
    reason="Test rzeczywistego schowka Windows wymaga SHAQ_TEST_CLIPBOARD=1.",
)


def test_shortcuts_with_audio_and_real_clipboard_in_fresh_process(tmp_path: Path) -> None:
    """Sprawdza oba skróty i trwałość danych; wcześniejszy tekst zostaje przywrócony."""
    for module in ("wx", "soundcard", "shazamio", "win32clipboard"):
        pytest.importorskip(module)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        env=dict(
            os.environ,
            APPDATA=str(tmp_path),
            XDG_CONFIG_HOME=str(tmp_path),
            PYTHONIOENCODING="utf-8",
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode == 77:
        pytest.skip("Schowek zawiera dane inne niż tekst; test pozostawia je nietknięte.")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "tryb_com": "MTA",
        "skroty": 2,
        "bledy_wx": [],
        "dane_po_zamknieciu": True,
    }


def _probe() -> int:
    """Wykonuje próbę w osobnym procesie z kolejnością inicjalizacji właściwej aplikacji."""
    import atexit
    import ctypes
    import time
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    import pywintypes
    import soundcard
    import win32clipboard
    import wx

    def release_audio_com() -> None:
        """Zwalnia inicjalizację audio również po pominięciu lub niepowodzeniu próby."""
        library = soundcard.mediafoundation._com
        if library.com_loaded:
            library.__del__()
            library.com_loaded = False

    atexit.register(release_audio_com)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from shaq import _gui

    apartment, qualifier = ctypes.c_int(), ctypes.c_int()
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoGetApartmentType.argtypes = [ctypes.POINTER(ctypes.c_int)] * 2
    ole32.CoGetApartmentType.restype = ctypes.c_long
    assert ole32.CoGetApartmentType(ctypes.byref(apartment), ctypes.byref(qualifier)) == 0
    assert apartment.value == 1, "Moduł audio powinien uruchomić COM w trybie MTA."

    def open_clipboard() -> None:
        """Czeka krótko na zwolnienie schowka przez systemową historię lub czytnik."""
        deadline = time.monotonic() + 2
        while True:
            try:
                win32clipboard.OpenClipboard()
                return
            except pywintypes.error:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)

    open_clipboard()
    try:
        formats = []
        current = win32clipboard.EnumClipboardFormats(0)
        while current:
            formats.append(current)
            current = win32clipboard.EnumClipboardFormats(current)
        if set(formats) - {1, 7, 13, 16}:
            return 77
        original = win32clipboard.GetClipboardData(13) if formats else None
    finally:
        win32clipboard.CloseClipboard()

    def read_text() -> str:
        """Odczytuje tekst skopiowany w bieżącej próbie."""
        open_clipboard()
        try:
            return win32clipboard.GetClipboardData(13)
        finally:
            win32clipboard.CloseClipboard()

    errors: list[str] = []

    class Log(wx.Log):
        """Przechwytuje dodatkowe okna błędów generowane przez sam wxPython."""

        def DoLogText(self, text: str) -> None:
            errors.append(text)

    app = wx.App(False)
    logger = Log()
    previous_log = wx.Log.SetActiveTarget(logger)
    frame = None
    last_sequence = None
    _gui._save_config({"ui_language": "pl"})
    try:
        with (
            patch.object(wx, "App", return_value=app),
            patch.object(app, "MainLoop"),
            patch.object(wx.Frame, "Show", return_value=False),
            patch.object(wx, "CallAfter"),
            patch.object(wx, "MessageBox", side_effect=AssertionError("Nieoczekiwany dialog")),
        ):
            _gui._main()
        frame = next(item for item in wx.GetTopLevelWindows() if isinstance(item, wx.Frame))
        frame._timer.Stop()
        spoken = Mock(return_value=True)
        frame._announcer.speaker = SimpleNamespace(speak=spoken)
        title = "Tytuł - część druga 🎵"
        full = f"Żółć feat. 東京 - {title}"
        frame._events.put(("track", (full, title)))
        frame._on_timer(None)
        frame.log_list.SetSelection(0)
        for shift, expected, key in (
            (False, title, "clipboard.title_copied"),
            (True, full, "clipboard.full_copied"),
        ):
            event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            event.SetKeyCode(ord("C"))
            event.SetControlDown(True)
            event.SetShiftDown(shift)
            event.SetEventObject(frame.log_list)
            frame.log_list.GetEventHandler().ProcessEvent(event)
            last_sequence = win32clipboard.GetClipboardSequenceNumber()
            assert frame.GetStatusBar().GetStatusText() == _gui._STRINGS[key]["pl"]
            assert read_text() == expected, {
                "status": frame.GetStatusBar().GetStatusText(),
                "zdarzenie_pominiete": event.GetSkipped(),
                "bledy_wx": errors,
            }
            assert spoken.call_args.args[0] == _gui._STRINGS[key]["pl"]
            assert frame.log_list.GetSelection() == 0
        wx.Log.FlushActive()
        assert not errors, errors
    finally:
        if frame is not None:
            frame.Destroy()
        app.ProcessPendingEvents()
        wx.Log.SetActiveTarget(previous_log)
        app.Destroy()
        persisted = False
        try:
            if last_sequence is not None:
                persisted = read_text() == full
        finally:
            if last_sequence is not None:
                open_clipboard()
                try:
                    if win32clipboard.GetClipboardData(13) in (title, full):
                        win32clipboard.EmptyClipboard()
                        if original is not None:
                            win32clipboard.SetClipboardData(13, original)
                finally:
                    win32clipboard.CloseClipboard()
            release_audio_com()
    assert persisted
    print(
        json.dumps(
            {
                "tryb_com": "MTA",
                "skroty": 2,
                "bledy_wx": errors,
                "dane_po_zamknieciu": persisted,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_probe())
