"""Wybór programu i przechwytywanie jego dźwięku bez dźwięków innych aplikacji."""

from __future__ import annotations

import math
import ntpath
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ._process_messages import default_translate


class ProcessAudioError(RuntimeError):
    """Błąd z kluczem tłumaczenia, renderowany dopiero w języku interfejsu."""

    def __init__(self, key: str, **values: Any) -> None:
        self.key = key
        self.values = values
        super().__init__(self.localized(default_translate))

    def localized(self, translate: Callable[..., str]) -> str:
        """Formatuje błąd, zachowując kody systemowe i parametry."""
        values = dict(self.values)
        if "operation" in values:
            values["operation"] = translate(values["operation"])
        return translate(self.key, **values)


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
        raise ProcessAudioError("process.unsupported")


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
    """Sprawdza całe drzewo przodków w czasie O(n), także przez procesy pomocnicze."""
    by_pid = {process.pid: process for process in processes}
    matches = [
        process for process in by_pid.values() if _path_key(process.executable) == target.key
    ]
    if not matches:
        return None
    pids = {process.pid for process in matches}
    ancestors: dict[int, int | None] = {}
    for process in matches:
        trail: list[ProcessInfo] = []
        visited: set[int] = set()
        current = process
        root_pid = None
        while current.pid not in ancestors:
            if current.pid in visited:
                raise MultipleProcessesError("process.multiple", name=target.name)
            visited.add(current.pid)
            trail.append(current)
            parent = by_pid.get(current.parent_pid)
            if parent is None or (
                current.creation_time > 0 and parent.creation_time > current.creation_time
            ):
                # Brak rodzica lub ponowne użycie jego PID nie dowodzi pokrewieństwa.
                break
            current = parent
        else:
            root_pid = ancestors[current.pid]
        for ancestor in reversed(trail):
            if root_pid is None and ancestor.pid in pids:
                root_pid = ancestor.pid
            ancestors[ancestor.pid] = root_pid
    roots = {ancestors[process.pid] for process in matches}
    if len(roots) != 1 or None in roots:
        raise MultipleProcessesError("process.multiple", name=target.name)
    root_pid = roots.pop()
    assert root_pid is not None
    return by_pid[root_pid]


def process_unavailable_message(
    target: ProcessTarget, *, translate: Callable[..., str] = default_translate
) -> str:
    """Zwraca przetłumaczony komunikat o zachowanym wyborze odtwarzacza."""
    return translate("process.unavailable", name=target.name)


def record_process_wav(
    target: ProcessTarget,
    *,
    duration_s: float,
    sample_rate: int = 16000,
    channels: int = 1,
    stop_event: threading.Event,
    on_status: Callable[[str], None],
    translate: Callable[..., str] = default_translate,
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
    try:
        require_process_capture()
    except ProcessAudioError as exc:
        raise ProcessAudioError(exc.localized(translate)) from exc
    from ._win_process_audio import capture_wav

    last_status = ""
    while not stop_event.is_set():
        try:
            process = resolve_process(target, list_processes())
        except MultipleProcessesError as exc:
            process = None
            status = exc.localized(translate)
        else:
            status = (
                translate("process.listening", name=target.name)
                if process is not None
                else process_unavailable_message(target, translate=translate)
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
        except ProcessAudioError as exc:
            raise ProcessAudioError(exc.localized(translate)) from exc
        except OSError as exc:
            raise ProcessAudioError(
                translate("process.capture_error", name=target.name, error=str(exc))
            ) from exc
    return None
