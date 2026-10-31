"""Dostępne kontrolki adresu radia, importu playlist i niezależnego odsłuchu."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from shaq._radio_playlist import load_playlist, validate_stream_url
from shaq._radio_preview import RadioPreview
from shaq._radio_stream import RadioStream


class RadioPanel:
    """Zarządza jedną transmisją współdzieloną przez nasłuch i opcjonalny odsłuch."""

    def __init__(
        self,
        parent: Any,
        config: Any,
        *,
        changed: Callable[[], None],
        status: Callable[[str], None],
        announce: Callable[[str], Any],
    ) -> None:
        import wx

        self._wx = wx
        self._changed = changed
        self._status = status
        self._announce = announce
        self._connection_state = "idle"
        self._recognition_failed = False
        self._events: Queue[tuple[str, int, str]] = Queue()
        self._source: RadioStream | None = None
        self._preview: RadioPreview | None = None
        self._preview_stopping = False
        self._monitoring = False
        self._generation = 0
        self._closed = False
        config = config if isinstance(config, dict) else {}
        self.panel = wx.Panel(parent)
        url_label = wx.StaticText(self.panel, label="Adres strumienia radia:")
        saved_url = config.get("url", "")
        self.url = wx.TextCtrl(self.panel, value=saved_url if isinstance(saved_url, str) else "")
        self.url.SetName("Adres strumienia radia")
        self.url.SetToolTip("Bezpośredni adres HTTP lub HTTPS, np. strumień MP3, AAC albo HLS.")
        self.url.Bind(wx.EVT_KILL_FOCUS, self._on_url_leave)
        self.import_btn = wx.Button(self.panel, label="Importuj PLS / M3U…")
        self.import_btn.Bind(wx.EVT_BUTTON, self._on_import)
        self.preview_start = wx.Button(self.panel, label="Włącz odsłuch")
        self.preview_start.SetToolTip("Włącz słuchanie radia. Cichy nasłuch działa niezależnie.")
        self.preview_start.Bind(wx.EVT_BUTTON, self._on_preview_start)
        self.preview_stop = wx.Button(self.panel, label="Zatrzymaj odsłuch")
        self.preview_stop.SetToolTip("Wyłącz dźwięk radia, zachowując rozpoznawanie utworów.")
        self.preview_stop.Bind(wx.EVT_BUTTON, self._on_preview_stop)
        volume_label = wx.StaticText(self.panel, label="Głośność odsłuchu (%):")
        volume = config.get("preview_volume", 25)
        if type(volume) is not int or not 0 <= volume <= 100:
            volume = 25
        self.volume = wx.Slider(
            self.panel,
            value=volume,
            minValue=0,
            maxValue=100,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        self.volume.SetName("Głośność odsłuchu w procentach")
        self.volume.SetLineSize(1)
        self.volume.SetPageSize(5)
        self.volume.Bind(wx.EVT_SLIDER, self._on_volume)
        self.info = wx.StaticText(
            self.panel, label="Odsłuch wyłączony. Start uruchamia cichy nasłuch."
        )
        self.connection = wx.StaticText(self.panel, label="Strumień nie jest połączony.")
        address_row = wx.BoxSizer(wx.HORIZONTAL)
        address_row.Add(url_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        address_row.Add(self.url, 1, wx.EXPAND | wx.RIGHT, 8)
        address_row.Add(self.import_btn, 0)
        preview_row = wx.BoxSizer(wx.HORIZONTAL)
        preview_row.Add(self.preview_start, 0, wx.RIGHT, 8)
        preview_row.Add(self.preview_stop, 0, wx.RIGHT, 12)
        preview_row.Add(volume_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        preview_row.Add(self.volume, 1, wx.ALIGN_CENTER_VERTICAL)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(address_row, 0, wx.EXPAND | wx.BOTTOM, 8)
        layout.Add(preview_row, 0, wx.EXPAND | wx.BOTTOM, 8)
        layout.Add(self.info, 0, wx.EXPAND | wx.BOTTOM, 4)
        layout.Add(self.connection, 0, wx.EXPAND)
        self.panel.SetSizer(layout)
        self._sync_controls()

    def config(self) -> dict[str, Any]:
        """Zapisuje adres i głośność; odsłuch nigdy nie włącza się po restarcie sam."""
        return {"url": self.url.GetValue().strip(), "preview_volume": self.volume.GetValue()}

    def stream(self) -> RadioStream:
        """Sprawdza adres i przygotowuje sesję bez blokowania połączeniem sieciowym."""
        url = validate_stream_url(self.url.GetValue())
        if self._source is None:
            self._generation += 1
            self._connection_state = "idle"
            generation = self._generation
            self._source = RadioStream(
                url,
                on_status=lambda message: self._events.put(("status", generation, message)),
                on_audio=lambda pcm: self._feed_preview(pcm, generation),
            )
        elif self._source.url != url:
            raise ValueError("Zatrzymaj nasłuch i odsłuch przed zmianą adresu radia.")
        return self._source

    def set_monitoring(self, monitoring: bool) -> None:
        """Włącza cichy odbiór lub zwalnia sesję, jeżeli odsłuch również jest wyłączony."""
        was_monitoring = self._monitoring
        self._monitoring = monitoring
        if monitoring:
            self.stream().start()
            if not was_monitoring:
                self._recognition_failed = False
                if self._connection_state == "connected":
                    self._announce("Nasłuch strumienia rozpoczęty.")
                else:
                    self._announce(
                        "Łączenie z radiem. Nasłuch rozpocznie się po odebraniu dźwięku."
                    )
        else:
            self._release_if_idle()
            if was_monitoring and not self._closed:
                self._announce("Nasłuch strumienia zatrzymany.")
        self._sync_controls()

    def recognition_problem(self, message: str) -> None:
        """Odczytuje pierwszy błąd usługi rozpoznawania w danej serii prób."""
        if not self._recognition_failed:
            self._recognition_failed = True
            self._announce(message)

    def recognition_succeeded(self) -> None:
        """Pozwala zgłosić kolejną awarię po poprawnej odpowiedzi usługi."""
        self._recognition_failed = False

    def request_monitor_stop(self) -> None:
        """Przerywa dekodowanie, jeśli nie jest potrzebne do włączonego odsłuchu."""
        if self._preview is None and self._source is not None:
            self._source.stop()

    def deactivate(self) -> None:
        """Zamyka radio przy przejściu na inne źródło dźwięku."""
        self._monitoring = False
        self._generation += 1
        self._preview_stopping = False
        if self._preview is not None:
            self._preview.stop()
            self._preview = None
        if self._source is not None:
            self._source.stop()
            self._source = None
        self.connection.SetLabel("Strumień nie jest połączony.")
        self._sync_controls()

    def close(self) -> None:
        """Kończy odbiór i odsłuch przy zamykaniu aplikacji."""
        self._closed = True
        self.deactivate()

    def poll(self) -> None:
        """Obsługuje zdarzenia tła wyłącznie w wątku interfejsu."""
        while not self._closed:
            try:
                kind, generation, message = self._events.get_nowait()
            except Empty:
                break
            if generation != self._generation:
                continue
            if kind == "status":
                self.connection.SetLabel(message)
                self._status(message)
                if message.startswith("Połączono."):
                    if self._connection_state != "connected":
                        prefix = (
                            "Połączenie z radiem przywrócone. "
                            if self._connection_state == "failed"
                            else "Połączono ze strumieniem radia. "
                        )
                        suffix = "Nasłuch rozpoczęty." if self._monitoring else "Odsłuch włączony."
                        self._announce(prefix + suffix)
                    self._connection_state = "connected"
                elif message.startswith("Brak transmisji"):
                    if self._connection_state != "failed":
                        self._announce(
                            "Brak połączenia z radiem. Będę ponawiać połączenie automatycznie."
                        )
                    self._connection_state = "failed"
            elif kind == "preview_finished":
                self._preview = None
                self._preview_stopping = False
                self._release_if_idle()
                self._sync_controls()
                if message:
                    self._announce(message)
                    self._wx.MessageBox(
                        message, "Odsłuch radia", self._wx.OK | self._wx.ICON_ERROR, self.panel
                    )
                else:
                    self._announce(
                        "Odsłuch wyłączony. Nasłuch trwa dalej."
                        if self._monitoring
                        else "Odsłuch radia wyłączony."
                    )

    def _release_if_idle(self) -> None:
        if not self._monitoring and self._preview is None and self._source is not None:
            self._source.stop()
            self._source = None
            self._generation += 1
            self.connection.SetLabel("Strumień nie jest połączony.")

    def _sync_controls(self) -> None:
        busy = self._monitoring or self._preview is not None
        self.url.Enable(not busy)
        self.import_btn.Enable(not busy)
        enabled, disabled = (
            (self.preview_stop, self.preview_start)
            if self._preview is not None
            else (self.preview_start, self.preview_stop)
        )
        enabled.Enable()
        if not self._closed and self._wx.Window.FindFocus() == disabled:
            enabled.SetFocus()
        disabled.Disable()
        if self._preview is not None:
            text = "Odsłuch włączony. Jego głośność nie wpływa na rozpoznawanie."
        elif self._monitoring:
            text = "Cichy nasłuch włączony. Radio nie jest odtwarzane w głośnikach."
        else:
            text = "Odsłuch wyłączony. Start uruchamia cichy nasłuch."
        self.info.SetLabel(text)

    def _feed_preview(self, pcm: bytes, generation: int) -> None:
        preview = self._preview
        if generation == self._generation and preview is not None:
            preview.feed(pcm)

    def _on_url_leave(self, event: Any) -> None:
        if not self._closed:
            self._changed()
        event.Skip()

    def _on_volume(self, event: Any) -> None:
        if self._preview is not None:
            self._preview.set_volume(self.volume.GetValue())
        self._changed()
        event.Skip()

    def _on_import(self, _event: Any) -> None:
        wx = self._wx
        with wx.FileDialog(
            self.panel,
            message="Wybierz playlistę radia",
            wildcard=(
                "Playlisty radia (*.pls;*.m3u;*.m3u8)|*.pls;*.m3u;*.m3u8|Wszystkie pliki (*.*)|*.*"
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                stations = load_playlist(Path(dialog.GetPath()))
            except (OSError, ValueError) as exc:
                self._announce(str(exc))
                wx.MessageBox(str(exc), "Import radia", wx.OK | wx.ICON_ERROR, self.panel)
                return
        selection = 0
        if len(stations) > 1:
            with wx.SingleChoiceDialog(
                self.panel,
                "Wybierz stację do nasłuchu:",
                "Stacje z playlisty",
                [station.label for station in stations],
            ) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                selection = dialog.GetSelection()
        self.url.ChangeValue(stations[selection].url)
        self._changed()
        self._status("Wczytano adres radia. Naciśnij Start, aby rozpocząć cichy nasłuch.")

    def _on_preview_start(self, _event: Any) -> None:
        if self._preview is not None:
            return
        try:
            source = self.stream()
            generation = self._generation
            self._preview = RadioPreview(
                self.volume.GetValue(),
                finished=lambda message: self._events.put(
                    ("preview_finished", generation, message)
                ),
            )
            self._preview_stopping = False
            self._preview.start()
            source.start()
            self._announce("Włączono odsłuch radia.")
        except (OSError, RuntimeError, ValueError) as exc:
            if self._preview is not None:
                self._preview.stop()
                self._preview = None
            self._release_if_idle()
            wx = self._wx
            self._announce(str(exc))
            wx.MessageBox(str(exc), "Odsłuch radia", wx.OK | wx.ICON_ERROR, self.panel)
        self._sync_controls()
        self._changed()

    def _on_preview_stop(self, _event: Any) -> None:
        if self._preview is not None and not self._preview_stopping:
            self._preview_stopping = True
            self._preview.stop()
            self.info.SetLabel("Zatrzymywanie odsłuchu. Rozpoznawanie pozostaje niezależne.")
