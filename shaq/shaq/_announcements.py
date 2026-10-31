"""Odczyt nowych rozpoznań przez aktywny czytnik ekranu."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


def _bundled_library(name: str, cdll: bool = False) -> Any:
    if not isinstance(name, str):
        raise TypeError("Nazwa biblioteki musi być napisem.")
    if not name or Path(name).name != name:
        raise ValueError("Wymagana jest sama nazwa biblioteki czytnika.")
    path = Path(getattr(sys, "_MEIPASS")) / "accessible_output2" / "lib" / name
    loader = ctypes.CDLL if cdll else ctypes.WinDLL
    return loader(str(path))


def _output_classes() -> Iterable[type[Any]]:
    import accessible_output2

    if hasattr(sys, "_MEIPASS"):
        from accessible_output2.outputs import base

        # Jednoplikowy PyInstaller rozpakowuje DLL do _MEIPASS, nie obok EXE.
        base.load_library = _bundled_library
    return accessible_output2.get_output_classes()


def _uia_notify(hwnd: int, text: str) -> bool:
    from ._uia_notifications import notify

    return notify(hwnd, text)


class ScreenReaderSpeaker:
    """Wybiera aktywny czytnik z Accessible Output 2 albo powiadomienia UI Automation."""

    def __init__(
        self,
        *,
        output_classes: Callable[[], Iterable[type[Any]]] = _output_classes,
        notify: Callable[[int, str], bool] = _uia_notify,
    ) -> None:
        self._output_classes = output_classes
        self._notify = notify
        self._instances: dict[type[Any], Any] = {}
        self.last_backend = ""
        self.last_error = ""

    def speak(self, text: str, hwnd: int) -> bool:
        """Przekazuje tekst raz, bez przerywania mowy i bez uruchamiania syntezatora SAPI."""
        if not isinstance(text, str):
            raise TypeError("Tekst do odczytu musi być napisem.")
        if not text.strip():
            return False
        self.last_backend = ""
        self.last_error = ""
        try:
            classes = list(self._output_classes())
        except Exception as exc:
            classes = []
            self.last_error = str(exc)
        for output_class in classes:
            if getattr(output_class, "system_output", False):
                continue
            try:
                output = self._instances.get(output_class)
                if output is None:
                    if getattr(output_class, "name", "").casefold() == "zdsr":
                        from ._zdsr_output import create_output

                        output = create_output(output_class)
                    else:
                        output = output_class()
                    self._instances[output_class] = output
                if output.is_active() and output.speak(text, interrupt=False) is not False:
                    self.last_backend = str(output.name)
                    self.last_error = ""
                    return True
            except Exception as exc:
                self._instances.pop(output_class, None)
                self.last_error = str(exc)
        try:
            if self._notify(hwnd, text):
                self.last_backend = "UI Automation"
                self.last_error = ""
                return True
        except Exception as exc:
            self.last_error = str(exc)
        return False


class RecognitionAnnouncer:
    """Odczytuje nowy utwór na liście, pomijając kolejne dopasowania tego samego utworu."""

    def __init__(self, speaker: ScreenReaderSpeaker | None = None) -> None:
        self.speaker = speaker if speaker is not None else ScreenReaderSpeaker()
        self.reset()

    def reset(self) -> None:
        """Pozwala odczytać pierwszy wynik nowej sesji nasłuchu."""
        self._last_track: str | None = None
        self._delivered = False

    def announce(self, track: str, *, enabled: bool, list_focused: bool, hwnd: int) -> bool:
        """Odczytuje wynik tylko po włączeniu opcji i podczas pracy na liście."""
        if not isinstance(track, str):
            raise TypeError("Rozpoznany utwór musi być napisem.")
        track = track.strip()
        if not track:
            return False
        if track != self._last_track:
            self._last_track = track
            self._delivered = False
        if not enabled or not list_focused or self._delivered:
            return False
        self._delivered = self.speaker.speak(track, hwnd)
        return self._delivered
