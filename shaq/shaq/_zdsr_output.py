"""Obsługa ZDSR z preferencją dla aktualnego interfejsu zainstalowanego czytnika."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any


def _installed_library() -> Path | None:
    from ._process_audio import list_processes

    filename = "ZDSRAPI_x64.dll" if ctypes.sizeof(ctypes.c_void_p) == 8 else "ZDSRAPI.dll"
    directories: list[Path] = []
    for process in list_processes():
        executable = Path(process.executable)
        if executable.stem.casefold().startswith("zdsr"):
            directories.append(executable.parent)
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        directory = os.environ.get(variable)
        if directory:
            directories.append(Path(directory) / "zdsr" / "zdsr")
    return next(
        (folder / filename for folder in directories if (folder / filename).is_file()), None
    )


class ZdsrOutput:
    """Sprawdza status ZDSR i wynik wywołania, także przy niezgodności wersji API."""

    name = "ZDSR"

    def __init__(self, library: Any, *, modern: bool) -> None:
        self._library = library
        self._modern = modern
        self._initialized = False
        arguments = [ctypes.c_int, ctypes.c_wchar_p]
        if modern:
            arguments.append(ctypes.c_int)
        library.InitTTS.argtypes = arguments
        library.InitTTS.restype = ctypes.c_int
        library.GetSpeakState.argtypes = []
        library.GetSpeakState.restype = ctypes.c_int
        library.Speak.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
        library.Speak.restype = ctypes.c_int

    def is_active(self) -> bool:
        """Wersja niezgodna, brak autoryzacji i błąd połączenia nie oznaczają aktywnego czytnika."""
        if not self._initialized:
            arguments = (0, None, True) if self._modern else (0, "")
            if self._library.InitTTS(*arguments) != 0:
                return False
            self._initialized = True
        return self._library.GetSpeakState() in (3, 4)

    def speak(self, text: str, *, interrupt: bool = False) -> bool:
        """Przekazuje tekst do kolejki mowy ZDSR i potwierdza przyjęcie polecenia."""
        if not isinstance(text, str):
            raise TypeError("Tekst do odczytu musi być napisem.")
        return bool(text.strip()) and self.is_active() and self._library.Speak(text, interrupt) == 0


def create_output(output_class: type[Any]) -> ZdsrOutput:
    """Wybiera DLL bieżącego czytnika, a przy jej braku wersję z Accessible Output 2."""
    path = _installed_library()
    if path is not None:
        return ZdsrOutput(ctypes.WinDLL(str(path)), modern=True)
    return ZdsrOutput(output_class().lib, modern=False)
