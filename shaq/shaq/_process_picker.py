"""Dostępny wybór programu wspólny dla okien nasłuchu."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ._process_audio import (
    ProcessAudioError,
    ProcessTarget,
    list_processes,
    process_choices,
    process_unavailable_message,
    require_process_capture,
    resolve_process,
)
from ._process_messages import default_translate


class ProcessPicker:
    """Zachowuje wybór zamkniętego programu podczas odświeżania listy procesów."""

    def __init__(
        self,
        parent: Any,
        choice: Any,
        config: Any,
        *,
        changed: Callable[[], None],
        status: Callable[[str], None],
        translate: Callable[..., str] = default_translate,
    ) -> None:
        self._t = translate
        self.parent = parent
        self.choice = choice
        self.target = ProcessTarget.from_config(config)
        self._changed = changed
        self._status = status
        self._choices: list[tuple[ProcessTarget, bool]] = []
        self._signature: tuple[Any, ...] | None = None
        self._last_refresh = 0.0

    def refresh(self, *, force: bool = False) -> None:
        """Odświeża listę najwyżej co dwie sekundy, nie zmieniając zapamiętanego wyboru."""
        if not force and getattr(self.choice, "HasFocus", lambda: False)():
            return
        now = time.monotonic()
        if not force and now - self._last_refresh < 2.0:
            return
        self._last_refresh = now
        try:
            processes = list_processes()
        except (OSError, ProcessAudioError) as exc:
            self._status(exc.localized(self._t) if isinstance(exc, ProcessAudioError) else str(exc))
            processes = []
        choices = process_choices(processes, self.target)
        signature = tuple((target.key, running) for target, running in choices)
        if not force and signature == self._signature:
            return
        self._signature = signature
        self._choices = choices
        labels = [self._t("process.prompt")]
        selection = 0
        for index, (target, running) in enumerate(choices, start=1):
            state = "" if running else self._t("process.closed_suffix")
            labels.append(f"{target.name}{state} ({target.executable})")
            if self.target is not None and target.key == self.target.key:
                selection = index
        self.choice.SetItems(labels)
        self.choice.SetSelection(selection)

    def select_current(self) -> None:
        """Zapamiętuje wyłącznie świadomy wybór pozycji z listy."""
        index = self.choice.GetSelection() - 1
        if 0 <= index < len(self._choices):
            self.target = self._choices[index][0]
            self._changed()
        elif self.choice.GetSelection() == 0:
            self.target = None
            self._changed()

    def browse(self) -> None:
        """Pozwala wskazać plik EXE również dla nieuruchomionego programu."""
        import wx

        with wx.FileDialog(
            self.parent,
            message=self._t("process.browse_title"),
            wildcard=self._t("process.files"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                self.target = ProcessTarget(dialog.GetPath())
            except (TypeError, ValueError):
                wx.MessageBox(
                    self._t("process.path"),
                    self._t("process.selection_title"),
                    wx.OK | wx.ICON_ERROR,
                    self.parent,
                )
                return
        self.refresh(force=True)
        self._changed()

    def selected(self) -> ProcessTarget:
        """Sprawdza wymagania systemu i zwraca trwały wybór do uruchomienia nasłuchu."""
        try:
            require_process_capture()
        except ProcessAudioError as exc:
            raise ValueError(exc.localized(self._t)) from exc
        if self.target is None:
            raise ValueError(self._t("process.choose"))
        return self.target

    def startup_notice(self) -> None:
        """Informuje po uruchomieniu aplikacji o zamkniętym, zapamiętanym odtwarzaczu."""
        import wx

        if self.target is None:
            return
        try:
            require_process_capture()
            process = resolve_process(self.target, list_processes())
        except (OSError, ProcessAudioError) as exc:
            message = exc.localized(self._t) if isinstance(exc, ProcessAudioError) else str(exc)
        else:
            if process is not None:
                return
            message = process_unavailable_message(self.target, translate=self._t)
        self._status(message)
        wx.MessageBox(message, self._t("process.title"), wx.OK | wx.ICON_INFORMATION, self.parent)
