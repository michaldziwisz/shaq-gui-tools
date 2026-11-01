"""Komunikaty nasłuchu procesu używane przez tłumaczenia obu aplikacji."""

from typing import Any

_STRINGS: dict[str, dict[str, str]] = {
    "process.choice": {"pl": "Program (wybrany proces)", "en": "Program (selected process)"},
    "process.label": {"pl": "Program:", "en": "Program:"},
    "process.name": {"pl": "Program do nasłuchu", "en": "Program to monitor"},
    "process.refresh": {"pl": "Odśwież programy", "en": "Refresh programs"},
    "process.browse": {"pl": "Wskaż plik EXE…", "en": "Browse for EXE…"},
    "process.prompt": {
        "pl": "Wybierz program lub wskaż jego plik EXE…",
        "en": "Select a program or browse for its EXE file…",
    },
    "process.closed_suffix": {"pl": " — nieuruchomiony", "en": " — not running"},
    "process.browse_title": {
        "pl": "Wskaż program, którego dźwięk ma być rozpoznawany",
        "en": "Select the program whose audio should be recognized",
    },
    "process.files": {"pl": "Programy (*.exe)|*.exe", "en": "Programs (*.exe)|*.exe"},
    "process.selection_title": {"pl": "Wybór programu", "en": "Select program"},
    "process.title": {"pl": "Nasłuch programu", "en": "Program monitoring"},
    "process.choose": {
        "pl": "Wybierz program z listy lub wskaż jego plik EXE.",
        "en": "Select a program from the list or browse for its EXE file.",
    },
    "process.path": {
        "pl": "Wskaż pełną ścieżkę do pliku programu .exe.",
        "en": "Select the full path to a program .exe file.",
    },
    "process.unsupported": {
        "pl": "Nasłuch programu wymaga Windows 11 lub Windows w kompilacji co najmniej 20348.",
        "en": "Program monitoring requires Windows 11 or Windows build 20348 or later.",
    },
    "process.multiple": {
        "pl": "Działa kilka instancji {name}. Pozostaw jedną instancję odtwarzacza.",
        "en": "Several instances of {name} are running. Leave one player instance running.",
    },
    "process.unavailable": {
        "pl": (
            "Program {name} nie jest uruchomiony. Uruchom go i włącz odtwarzanie. "
            "Wybór pozostaje zapamiętany. Po naciśnięciu Start nasłuch zaczeka na ten program."
        ),
        "en": (
            "Program {name} is not running. Launch it and start playback. "
            "Your selection is saved. After you press Start, monitoring will wait for this program."
        ),
    },
    "process.listening": {"pl": "Nasłuch programu: {name}.", "en": "Monitoring program: {name}."},
    "process.capture_error": {
        "pl": "Nie można nagrać programu {name}: {error}",
        "en": "Cannot capture program {name}: {error}",
    },
    "process.exited_wait": {
        "pl": "Odtwarzacz został zamknięty. Czekam na ponowne uruchomienie.",
        "en": "The player was closed. Waiting for it to restart.",
    },
    "process.enumeration_error": {
        "pl": "Nie można odczytać listy uruchomionych programów.",
        "en": "Cannot read the list of running programs.",
    },
    "process.interface_error": {
        "pl": "Windows nie udostępnił interfejsu dźwięku.",
        "en": "Windows did not provide an audio interface.",
    },
    "process.windows_error": {
        "pl": "{operation}: błąd Windows 0x{code:08X}.",
        "en": "{operation}: Windows error 0x{code:08X}.",
    },
    "process.activation_stopped": {
        "pl": "Przerwano oczekiwanie na uruchomienie nasłuchu programu.",
        "en": "Waiting for program capture to start was interrupted.",
    },
    "process.activation_error": {
        "pl": "Nie można uruchomić nasłuchu programu: {error}",
        "en": "Cannot start program capture: {error}",
    },
    "process.interface_missing": {
        "pl": "Windows nie zwrócił interfejsu dźwięku programu.",
        "en": "Windows did not return the program audio interface.",
    },
    "process.empty_buffer": {
        "pl": "Windows zwrócił pusty bufor dźwięku.",
        "en": "Windows returned an empty audio buffer.",
    },
    "process.exited": {
        "pl": "Wybrany program został zamknięty.",
        "en": "The selected program was closed.",
    },
    "process.open_error": {
        "pl": "Windows nie pozwala otworzyć wybranego programu (błąd {error}).",
        "en": "Windows cannot open the selected program (error {error}).",
    },
    "process.restarted": {
        "pl": "Odtwarzacz zmienił instancję; odnajduję go ponownie.",
        "en": "The player instance changed; locating it again.",
    },
    "process.no_selection": {
        "pl": "Nie wybrano programu do nasłuchu.",
        "en": "No program selected for monitoring.",
    },
    "process.audio_error": {
        "pl": "Przechwytywanie dźwięku nieudane: {error}",
        "en": "Audio capture failed: {error}",
    },
    "process.operation.0": {"pl": "Aktywacja nasłuchu", "en": "Activate audio capture"},
    "process.operation.1": {"pl": "Aktywacja nasłuchu programu", "en": "Activate program capture"},
    "process.operation.2": {"pl": "Interfejs dźwięku", "en": "Audio interface"},
    "process.operation.3": {"pl": "Uruchamianie nasłuchu programu", "en": "Start program capture"},
    "process.operation.9": {"pl": "Ustawienie formatu dźwięku", "en": "Set audio format"},
    "process.operation.10": {"pl": "Otwarcie przechwytywania", "en": "Open audio capture"},
    "process.operation.11": {
        "pl": "Ustawienie powiadomień dźwięku",
        "en": "Set audio notifications",
    },
    "process.operation.12": {
        "pl": "Rozpoczęcie nagrywania programu",
        "en": "Start recording program",
    },
}

_STRINGS.update(
    {
        "process.operation.extra0": {"pl": "Odczyt rozmiaru próbki", "en": "Read packet size"},
        "process.operation.extra1": {
            "pl": "Odczyt próbki programu",
            "en": "Read program audio packet",
        },
        "process.operation.extra2": {"pl": "Zwolnienie próbki", "en": "Release audio packet"},
        "process.operation.extra3": {
            "pl": "Inicjalizacja obsługi dźwięku",
            "en": "Initialize audio support",
        },
    }
)


def default_translate(key: str, **values: Any) -> str:
    """Zachowuje polski komunikat dla bezpośrednich wywołań modułu."""
    return _STRINGS[key]["pl"].format(**values) if key in _STRINGS else key
