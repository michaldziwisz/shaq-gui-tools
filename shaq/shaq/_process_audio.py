"""Wybór programu i przechwytywanie jego dźwięku bez dźwięków innych aplikacji."""

from __future__ import annotations

import math
import ntpath
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


class ProcessAudioError(RuntimeError):
    """Błąd przechwytywania dźwięku wybranego programu."""


class ProcessExitedError(ProcessAudioError):
    """Wybrana instancja programu została zamknięta."""


class MultipleProcessesError(ProcessAudioError):
    """Kilka niezależnych instancji pasuje do zapamiętanego programu."""


def _path_key(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))


@dataclass(frozen=True)
class ProcessTarget:
    """Trwały wybór programu według pełnej ścieżki, niezależny od numeru PID."""

    executable: str

    def __post_init__(self) -> None:
        if not isinstance(self.executable, str):
            raise TypeError("Ścieżka programu musi być tekstem.")
        if (
            not self.executable.strip()
            or "\x00" in self.executable
            or not ntpath.isabs(self.executable)
            or not ntpath.splitdrive(self.executable)[0]
            or not self.executable.lower().endswith(".exe")
        ):
            raise ValueError("Wskaż pełną ścieżkę do pliku programu .exe.")

    @property
    def name(self) -> str:
        """Zwraca nazwę pliku wykonywalnego do wyświetlenia."""
        return ntpath.basename(self.executable)

    @property
    def key(self) -> str:
        """Zwraca identyfikator odporny na wielkość liter w ścieżce Windows."""
        return _path_key(self.executable)

    def to_config(self) -> dict[str, str]:
        """Zapisuje trwałe dane programu, bez chwilowego identyfikatora PID."""
        return {"executable": self.executable}

    @classmethod
    def from_config(cls, value: Any) -> ProcessTarget | None:
        """Odczytuje wybór; niepoprawny lub nieistniejący wpis zwraca jako brak wyboru."""
        if not isinstance(value, dict):
            return None
        try:
            return cls(value.get("executable"))
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class ProcessInfo:
    """Bieżąca instancja programu wraz z czasem utworzenia chroniącym przed użyciem PID ponownie."""

    pid: int
    parent_pid: int
    executable: str
    creation_time: int

    @property
    def target(self) -> ProcessTarget:
        """Zwraca trwały wybór odpowiadający instancji."""
        return ProcessTarget(self.executable)


def process_capture_supported() -> bool:
    """Sprawdza dostępność przechwytywania procesów w bieżącej wersji Windows."""
    return sys.platform == "win32" and sys.getwindowsversion().build >= 20348


def require_process_capture() -> None:
    """Zgłasza czytelny błąd, jeżeli system nie obsługuje izolowanego nasłuchu."""
    if not process_capture_supported():
        raise ProcessAudioError(
            "Nasłuch programu wymaga Windows 11 lub Windows w kompilacji co najmniej 20348."
        )


def list_processes() -> list[ProcessInfo]:
    """Zwraca procesy z dostępną pełną ścieżką; nie otwiera ani nie nagrywa dźwięku."""
    if sys.platform != "win32":
        return []
    from ._win_process_audio import enumerate_processes

    return enumerate_processes()


def process_choices(
    processes: Iterable[ProcessInfo], saved: ProcessTarget | None
) -> list[tuple[ProcessTarget, bool]]:
    """Buduje listę programów, zachowując także zapamiętany, zamknięty odtwarzacz."""
    targets: dict[str, ProcessTarget] = {}
    for process in processes:
        target = process.target
        targets[target.key] = target
    running = set(targets)
    if saved is not None:
        targets[saved.key] = saved
    return [
        (target, target.key in running)
        for target in sorted(targets.values(), key=lambda item: (item.name.casefold(), item.key))
    ]


def resolve_process(target: ProcessTarget, processes: Iterable[ProcessInfo]) -> ProcessInfo | None:
    """Odnajduje główny proces programu; odrzuca wybór spośród kilku osobnych instancji."""
    matches = [process for process in processes if _path_key(process.executable) == target.key]
    if not matches:
        return None
    pids = {process.pid for process in matches}
    roots = [process for process in matches if process.parent_pid not in pids]
    if len(roots) != 1:
        raise MultipleProcessesError(
            f"Działa kilka instancji {target.name}. Pozostaw jedną instancję odtwarzacza."
        )
    return roots[0]


def process_unavailable_message(target: ProcessTarget) -> str:
    """Zwraca komunikat o zachowanym wyborze zamkniętego odtwarzacza."""
    return (
        f"Program {target.name} nie jest uruchomiony. Uruchom go i włącz odtwarzanie. "
        "Wybór pozostaje zapamiętany. Po naciśnięciu Start nasłuch zaczeka na ten program."
    )


def record_process_wav(
    target: ProcessTarget,
    *,
    duration_s: float,
    sample_rate: int = 16000,
    channels: int = 1,
    stop_event: threading.Event,
    on_status: Callable[[str], None],
) -> bytes | None:
    """Nagrywa wyłącznie wskazany program, czekając na niego po zamknięciu lub restarcie.

    Zatrzymanie zwraca None. Błędy systemowe zgłasza jako ProcessAudioError;
    brak programu i zmiana PID nie kasują zapamiętanego wyboru.
    """
    if not isinstance(target, ProcessTarget):
        raise TypeError("Wymagany jest wybór programu ProcessTarget.")
    if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
        raise TypeError("Długość nagrania musi być liczbą.")
    if not math.isfinite(duration_s) or not 0 < duration_s <= 60:
        raise ValueError("Długość nagrania musi wynosić więcej niż 0 i nie więcej niż 60 sekund.")
    if type(sample_rate) is not int or type(channels) is not int:
        raise TypeError("Częstotliwość i liczba kanałów muszą być liczbami całkowitymi.")
    if not 8000 <= sample_rate <= 48000 or channels not in (1, 2):
        raise ValueError("Obsługiwane jest 8000–48000 Hz oraz jeden lub dwa kanały.")
    require_process_capture()
    from ._win_process_audio import capture_wav

    last_status = ""
    while not stop_event.is_set():
        try:
            process = resolve_process(target, list_processes())
        except MultipleProcessesError as exc:
            process = None
            status = str(exc)
        else:
            status = (
                f"Nasłuch programu: {target.name}."
                if process is not None
                else process_unavailable_message(target)
            )
        if status != last_status:
            on_status(status)
            last_status = status
        if process is None:
            stop_event.wait(1.0)
            continue
        try:
            return capture_wav(
                process,
                duration_s=float(duration_s),
                sample_rate=sample_rate,
                channels=channels,
                stop_event=stop_event,
            )
        except ProcessExitedError:
            stop_event.wait(0.1)
            continue
        except OSError as exc:
            raise ProcessAudioError(f"Nie można nagrać programu {target.name}: {exc}") from exc
    return None
