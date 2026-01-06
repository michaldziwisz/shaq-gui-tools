from __future__ import annotations

import os
import threading
import sys
from dataclasses import dataclass
from typing import Any

import wx

from .audio import default_microphone_id, default_speaker_id, list_microphones, list_speakers
from .config_store import config_version, decrypt_secret, encrypt_secret, load_config, save_config
from .i18n import I18n, UI_LANGUAGE_CHOICES, ui_language_from_config
from .shazam_regions import (
    SUPPORTED_ENDPOINT_COUNTRIES,
    SUPPORTED_LANGUAGES,
    country_choice_strings,
    country_codes,
    find_index_by_code,
    language_choice_strings,
    language_codes,
)
from .streamer import StreamSettings, StreamingSession


_APP_NAME = "shaqcast"

_STRINGS: dict[str, dict[str, str]] = {
    "label.ui_language": {"pl": "Język interfejsu:", "en": "Interface language:"},
    "name.ui_language": {"pl": "Język interfejsu", "en": "Interface language"},
    "tooltip.ui_language": {
        "pl": "Zmień język interfejsu (wymaga restartu aplikacji).",
        "en": "Change the interface language (requires app restart).",
    },
    "info.restart_required": {
        "pl": "Zapisano język. Uruchom ponownie aplikację, aby zastosować zmianę.",
        "en": "Language saved. Restart the app to apply the change.",
    },
    "label.preset": {"pl": "Preset:", "en": "Preset:"},
    "button.preset_save": {"pl": "Zapisz preset…", "en": "Save preset..."},
    "name.preset_save": {"pl": "Zapisz preset", "en": "Save preset"},
    "button.preset_delete": {"pl": "Usuń preset", "en": "Delete preset"},
    "name.preset_delete": {"pl": "Usuń preset", "en": "Delete preset"},
    "label.host": {"pl": "Host:", "en": "Host:"},
    "label.port": {"pl": "Port:", "en": "Port:"},
    "label.password": {"pl": "Hasło / authhash:", "en": "Password / authhash:"},
    "label.sids": {"pl": "SIDy (np. 1,2,3):", "en": "SIDs (e.g. 1,2,3):"},
    "label.listen_seconds": {"pl": "Nasłuch (sekundy):", "en": "Listen (seconds):"},
    "label.no_match_text": {
        "pl": "Tekst przy braku dopasowania (opcjonalnie):",
        "en": "Text when no match (optional):",
    },
    "label.shazam_language": {"pl": "Język Shazam:", "en": "Shazam language:"},
    "label.shazam_country": {"pl": "Kraj Shazam:", "en": "Shazam country:"},
    "label.audio_source": {"pl": "Źródło audio:", "en": "Audio source:"},
    "choice.audio_source.output": {"pl": "Wyjście (loopback)", "en": "Output (loopback)"},
    "choice.audio_source.input": {"pl": "Wejście (mikrofon)", "en": "Input (microphone)"},
    "label.device": {"pl": "Urządzenie:", "en": "Device:"},
    "button.refresh_devices": {"pl": "Odśwież urządzenia", "en": "Refresh devices"},
    "name.refresh_devices": {"pl": "Odśwież urządzenia", "en": "Refresh devices"},
    "button.advanced": {"pl": "Ustawienia zaawansowane…", "en": "Advanced settings..."},
    "name.advanced": {"pl": "Ustawienia zaawansowane", "en": "Advanced settings"},
    "button.start": {"pl": "Start", "en": "Start"},
    "button.stop": {"pl": "Stop", "en": "Stop"},
    "label.log": {"pl": "Log:", "en": "Log:"},
    "dialog.preset_name": {"pl": "Nazwa presetu:", "en": "Preset name:"},
    "error.preset_name_required": {"pl": "Podaj nazwę presetu.", "en": "Enter a preset name."},
    "prompt.delete_preset": {
        "pl": "Usunąć preset '{name}'?",
        "en": "Delete preset '{name}'?",
    },
    "dialog.advanced.title": {"pl": "Ustawienia zaawansowane", "en": "Advanced settings"},
    "adv.segment_seconds": {"pl": "Długość podpisu Shazam (sek):", "en": "Shazam signature length (sec):"},
    "adv.segment_seconds_name": {"pl": "Długość podpisu Shazam", "en": "Shazam signature length"},
    "adv.max_windows": {"pl": "Okna w próbce (max):", "en": "Windows per sample (max):"},
    "adv.window_step": {"pl": "Krok okna (sek):", "en": "Window step (sec):"},
    "adv.window_step_name": {"pl": "Krok okna", "en": "Window step"},
    "adv.silence_dbfs": {"pl": "Próg ciszy (dBFS):", "en": "Silence threshold (dBFS):"},
    "adv.min_api_interval": {"pl": "Min odstęp API (sek):", "en": "Min API interval (sec):"},
    "adv.sample_rate": {"pl": "Sample rate (Hz):", "en": "Sample rate (Hz):"},
    "adv.channels": {"pl": "Kanały:", "en": "Channels:"},
    "adv.chunk_frames": {"pl": "Chunk frames:", "en": "Chunk frames:"},
    "error.enter_int": {"pl": "{label}: wpisz liczbę całkowitą.", "en": "{label}: enter an integer."},
    "error.enter_float": {"pl": "{label}: wpisz liczbę.", "en": "{label}: enter a number."},
    "error.range": {"pl": "{label}: zakres {minimum}–{maximum}.", "en": "{label}: range {minimum}–{maximum}."},
    "error.port_range": {"pl": "Port musi być w zakresie 1–65535", "en": "Port must be in the range 1–65535"},
    "error.listen_range": {
        "pl": "Nasłuch musi być w zakresie 3–30 sekund",
        "en": "Listen time must be in the range 3–30 seconds",
    },
    "error.choose_shazam_language": {"pl": "Wybierz język Shazam", "en": "Select a Shazam language"},
    "error.choose_shazam_country": {"pl": "Wybierz kraj Shazam", "en": "Select a Shazam country"},
    "error.no_device_selected": {"pl": "Nie wybrano urządzenia audio", "en": "No audio device selected"},
    "error.sid_min": {"pl": "SID musi być >= 1", "en": "SID must be >= 1"},
    "error.no_sids": {"pl": "Nie podano SIDów", "en": "No SIDs provided"},
    "title.error": {"pl": "Błąd", "en": "Error"},
    "log.device_enum_failed": {
        "pl": "Nie udało się pobrać listy urządzeń audio: {error}",
        "en": "Failed to enumerate audio devices: {error}",
    },
    "log.config_save_failed": {
        "pl": "Nie udało się zapisać config: {error}",
        "en": "Failed to save config: {error}",
    },
    "log.listening_started": {"pl": "Nasłuch uruchomiony.", "en": "Listening started."},
    "log.listening_stopped": {"pl": "Nasłuch zatrzymany.", "en": "Listening stopped."},
}

try:
    class _NamedAccessible(wx.Accessible):
        def __init__(self, window: wx.Window, name: str, description: str | None = None) -> None:
            super().__init__()
            self._window = window
            self._name = name
            self._description = description or ""

        def GetName(self, childId: int):  # noqa: N802 - wx API name
            return (wx.ACC_OK, self._name)

        def GetDescription(self, childId: int):  # noqa: N802 - wx API name
            if self._description:
                return (wx.ACC_OK, self._description)
            return (wx.ACC_NOT_SUPPORTED, "")

        def GetRole(self, childId: int):  # noqa: N802 - wx API name
            if isinstance(self._window, wx.TextCtrl):
                return (wx.ACC_OK, wx.ROLE_SYSTEM_TEXT)
            return (wx.ACC_OK, wx.ROLE_SYSTEM_CLIENT)

        def GetState(self, childId: int):  # noqa: N802 - wx API name
            state = 0
            if not self._window.IsEnabled():
                state |= wx.ACC_STATE_SYSTEM_UNAVAILABLE
            if not self._window.IsShownOnScreen():
                state |= wx.ACC_STATE_SYSTEM_INVISIBLE
            if self._window.HasFocus():
                state |= wx.ACC_STATE_SYSTEM_FOCUSED
            if self._window.CanAcceptFocus():
                state |= wx.ACC_STATE_SYSTEM_FOCUSABLE

            if isinstance(self._window, wx.TextCtrl):
                if not self._window.IsEditable():
                    state |= wx.ACC_STATE_SYSTEM_READONLY
                if self._window.GetWindowStyleFlag() & wx.TE_PASSWORD:
                    state |= wx.ACC_STATE_SYSTEM_PROTECTED

            return (wx.ACC_OK, state)

        def GetValue(self, childId: int):  # noqa: N802 - wx API name
            if isinstance(self._window, wx.TextCtrl):
                if self._window.GetWindowStyleFlag() & wx.TE_PASSWORD:
                    return (wx.ACC_OK, "")
                return (wx.ACC_OK, self._window.GetValue())
            return (wx.ACC_NOT_SUPPORTED, "")

except Exception:  # pragma: no cover - fallback when accessibility is unavailable
    _NamedAccessible = None  # type: ignore[assignment]


def _a11y(control: wx.Window, name: str) -> None:
    control.SetName(name)
    control.SetHelpText(name)
    if _NamedAccessible is None:
        return
    if not isinstance(control, wx.TextCtrl):
        return
    try:
        acc = _NamedAccessible(control, name, name)
        control.SetAccessible(acc)
        setattr(control, "_shaq_accessible", acc)
    except Exception:
        pass


def _win32_force_redraw(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes
        from ctypes import wintypes

        RDW_INVALIDATE = 0x0001
        RDW_ERASE = 0x0004
        RDW_ALLCHILDREN = 0x0080
        RDW_UPDATENOW = 0x0100

        user32 = ctypes.windll.user32
        user32.RedrawWindow(
            wintypes.HWND(hwnd),
            None,
            None,
            RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW,
        )
        try:
            desktop = user32.GetDesktopWindow()
            if desktop:
                user32.RedrawWindow(
                    wintypes.HWND(desktop),
                    None,
                    None,
                    RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW,
                )
        except Exception:
            pass
        try:
            ctypes.windll.gdi32.GdiFlush()
        except Exception:
            pass
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            pass
    except Exception:
        pass


@dataclass(frozen=True, slots=True)
class _DeviceChoice:
    label: str
    id: str


def _clamp_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        n = int(value)
    except Exception:
        return minimum
    return max(minimum, min(maximum, n))


def _clamp_float(value: Any, *, minimum: float, maximum: float) -> float:
    try:
        n = float(value)
    except Exception:
        return minimum
    return max(minimum, min(maximum, n))


@dataclass
class _AdvancedSettings:
    shazam_segment_seconds: int
    max_windows_per_sample: int
    window_step_s: int
    silence_dbfs_threshold: float
    min_request_interval_s: float
    sample_rate_hz: int
    channels: int
    chunk_frames: int


def _default_advanced() -> _AdvancedSettings:
    seg = _clamp_int(os.environ.get("SHAQCAST_SHAZAM_SEGMENT_SECONDS", "12"), minimum=3, maximum=60)
    max_windows = _clamp_int(
        os.environ.get("SHAQCAST_MAX_WINDOWS_PER_SAMPLE", "1"), minimum=1, maximum=6
    )
    step_s = _clamp_int(os.environ.get("SHAQCAST_WINDOW_STEP_S", "1"), minimum=1, maximum=60)
    silence = _clamp_float(
        os.environ.get("SHAQCAST_SILENCE_DBFS_THRESHOLD", "-55.0"), minimum=-100.0, maximum=0.0
    )
    min_interval = _clamp_float(
        os.environ.get("SHAQCAST_MIN_REQUEST_INTERVAL_S", "10.0"), minimum=0.0, maximum=60.0
    )
    return _AdvancedSettings(
        shazam_segment_seconds=seg,
        max_windows_per_sample=max_windows,
        window_step_s=step_s,
        silence_dbfs_threshold=silence,
        min_request_interval_s=min_interval,
        sample_rate_hz=16000,
        channels=1,
        chunk_frames=1024,
    )

class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(parent=None, title="shaqcast", size=(760, 520))

        panel = wx.Panel(self)

        config = load_config()
        ui_language = ui_language_from_config(config.get("ui_language"))
        i18n = I18n(ui_language, _STRINGS)
        self._t = i18n.t
        self._ui_language_code = ui_language

        self._device_id_output = str(config.get("device_id_output") or "").strip() or None
        self._device_id_input = str(config.get("device_id_input") or "").strip() or None

        defaults = _default_advanced()
        adv_cfg = config.get("advanced") if isinstance(config.get("advanced"), dict) else {}
        self._advanced = _AdvancedSettings(
            shazam_segment_seconds=_clamp_int(
                adv_cfg.get("shazam_segment_seconds", defaults.shazam_segment_seconds),
                minimum=3,
                maximum=60,
            ),
            max_windows_per_sample=_clamp_int(
                adv_cfg.get("max_windows_per_sample", defaults.max_windows_per_sample),
                minimum=1,
                maximum=6,
            ),
            window_step_s=_clamp_int(
                adv_cfg.get("window_step_s", defaults.window_step_s), minimum=1, maximum=60
            ),
            silence_dbfs_threshold=_clamp_float(
                adv_cfg.get("silence_dbfs_threshold", defaults.silence_dbfs_threshold),
                minimum=-100.0,
                maximum=0.0,
            ),
            min_request_interval_s=_clamp_float(
                adv_cfg.get("min_request_interval_s", defaults.min_request_interval_s),
                minimum=0.0,
                maximum=60.0,
            ),
            sample_rate_hz=_clamp_int(
                adv_cfg.get("sample_rate_hz", defaults.sample_rate_hz), minimum=8000, maximum=48000
            ),
            channels=_clamp_int(adv_cfg.get("channels", defaults.channels), minimum=1, maximum=2),
            chunk_frames=_clamp_int(
                adv_cfg.get("chunk_frames", defaults.chunk_frames), minimum=128, maximum=16384
            ),
        )

        default_language = (
            str(config.get("language") or os.environ.get("SHAQCAST_SHAZAM_LANGUAGE", "en-US"))
            .strip()
            .replace("_", "-")
            or "en-US"
        )
        default_country = (
            str(
                config.get("endpoint_country")
                or os.environ.get("SHAQCAST_SHAZAM_COUNTRY", "US")
            )
            .strip()
            .upper()
            or "US"
        )

        self._presets: list[dict[str, Any]] = []
        raw_presets = config.get("presets")
        if isinstance(raw_presets, list):
            for item in raw_presets:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                self._presets.append(item)
        self._presets.sort(key=lambda p: str(p.get("name") or "").lower())
        self._selected_preset_name = str(config.get("selected_preset") or "").strip()

        t = self._t
        self._ui_language_codes = [code for code, _label in UI_LANGUAGE_CHOICES]
        ui_lang_label = wx.StaticText(panel, label=t("label.ui_language"))
        self._ui_language_choice = wx.Choice(
            panel, choices=[label for _code, label in UI_LANGUAGE_CHOICES]
        )
        _a11y(self._ui_language_choice, t("name.ui_language"))
        self._ui_language_choice.SetToolTip(t("tooltip.ui_language"))
        self._ui_language_choice.SetSelection(0 if ui_language == "pl" else 1)
        self._ui_language_choice.Bind(wx.EVT_CHOICE, self._on_ui_language_changed)

        preset_label = wx.StaticText(panel, label=t("label.preset"))
        self._preset = wx.Choice(panel)
        _a11y(self._preset, t("label.preset").rstrip(":"))
        self._preset_save = wx.Button(panel, label=t("button.preset_save"))
        _a11y(self._preset_save, t("name.preset_save"))
        self._preset_delete = wx.Button(panel, label=t("button.preset_delete"))
        _a11y(self._preset_delete, t("name.preset_delete"))

        host_label = wx.StaticText(panel, label=t("label.host"))
        self._host = wx.TextCtrl(panel, value=str(config.get("host") or "127.0.0.1"))
        _a11y(self._host, t("label.host").rstrip(":"))

        port_label = wx.StaticText(panel, label=t("label.port"))
        self._port = wx.TextCtrl(panel, value=str(config.get("port") or "8000"))
        _a11y(self._port, t("label.port").rstrip(":"))

        password_label = wx.StaticText(panel, label=t("label.password"))
        self._password = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        _a11y(self._password, t("label.password").rstrip(":"))
        self._password.SetValue(decrypt_secret(str(config.get("password") or "")))

        sids_label = wx.StaticText(panel, label=t("label.sids"))
        self._sids = wx.TextCtrl(panel, value=str(config.get("sids") or "1"))
        _a11y(self._sids, t("label.sids").rstrip(":"))

        listen_label = wx.StaticText(panel, label=t("label.listen_seconds"))
        self._listen_seconds = wx.TextCtrl(panel, value=str(config.get("listen_seconds") or "15"))
        _a11y(self._listen_seconds, t("label.listen_seconds").rstrip(":"))

        no_match_label = wx.StaticText(
            panel, label=t("label.no_match_text")
        )
        self._no_match_text = wx.TextCtrl(panel, value=str(config.get("no_match_text") or ""))
        _a11y(self._no_match_text, t("label.no_match_text").rstrip(":"))

        self._language_codes = language_codes()
        language_label = wx.StaticText(panel, label=t("label.shazam_language"))
        self._language = wx.Choice(panel, choices=language_choice_strings())
        _a11y(self._language, t("label.shazam_language").rstrip(":"))
        lang_idx = find_index_by_code(SUPPORTED_LANGUAGES, default_language)
        self._language.SetSelection(lang_idx if lang_idx is not None else 0)

        self._country_codes = country_codes()
        country_label = wx.StaticText(panel, label=t("label.shazam_country"))
        self._country = wx.Choice(panel, choices=country_choice_strings())
        _a11y(self._country, t("label.shazam_country").rstrip(":"))
        country_idx = find_index_by_code(SUPPORTED_ENDPOINT_COUNTRIES, default_country)
        self._country.SetSelection(country_idx if country_idx is not None else 0)

        source_label = wx.StaticText(panel, label=t("label.audio_source"))
        self._source = wx.Choice(
            panel,
            choices=[t("choice.audio_source.output"), t("choice.audio_source.input")],
        )
        _a11y(self._source, t("label.audio_source").rstrip(":"))
        source_cfg = str(config.get("source") or "").strip().lower()
        self._source.SetSelection(1 if source_cfg in {"input", "mic", "microphone"} else 0)

        device_label = wx.StaticText(panel, label=t("label.device"))
        self._device = wx.Choice(panel)
        _a11y(self._device, t("label.device").rstrip(":"))
        self._device.Bind(wx.EVT_CHOICE, self._on_device_changed)
        self._refresh = wx.Button(panel, label=t("button.refresh_devices"))
        _a11y(self._refresh, t("name.refresh_devices"))

        self._advanced_btn = wx.Button(panel, label=t("button.advanced"))
        _a11y(self._advanced_btn, t("name.advanced"))
        self._start = wx.Button(panel, label=t("button.start"))
        _a11y(self._start, t("button.start"))
        self._stop = wx.Button(panel, label=t("button.stop"))
        _a11y(self._stop, t("button.stop"))
        self._stop.Disable()

        log_label = wx.StaticText(panel, label=t("label.log"))
        self._log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        _a11y(self._log, t("label.log").rstrip(":"))

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        preset_row.Add(self._preset, 1, wx.EXPAND)
        preset_row.Add(self._preset_save, 0, wx.LEFT, 8)
        preset_row.Add(self._preset_delete, 0, wx.LEFT, 8)

        grid.Add(preset_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(preset_row, 1, wx.EXPAND)

        grid.Add(ui_lang_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._ui_language_choice, 1, wx.EXPAND)

        grid.Add(host_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._host, 1, wx.EXPAND)

        grid.Add(port_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._port, 1, wx.EXPAND)

        grid.Add(password_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._password, 1, wx.EXPAND)

        grid.Add(sids_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._sids, 1, wx.EXPAND)

        grid.Add(listen_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._listen_seconds, 1, wx.EXPAND)

        grid.Add(no_match_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._no_match_text, 1, wx.EXPAND)

        grid.Add(language_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._language, 1, wx.EXPAND)

        grid.Add(country_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._country, 1, wx.EXPAND)

        grid.Add(source_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._source, 1, wx.EXPAND)

        grid.Add(device_label, 0, wx.ALIGN_CENTER_VERTICAL)
        device_row = wx.BoxSizer(wx.HORIZONTAL)
        device_row.Add(self._device, 1, wx.EXPAND)
        device_row.Add(self._refresh, 0, wx.LEFT, 8)
        grid.Add(device_row, 1, wx.EXPAND)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self._advanced_btn, 0, wx.RIGHT, 8)
        buttons.AddStretchSpacer(1)
        buttons.Add(self._start, 0, wx.RIGHT, 8)
        buttons.Add(self._stop, 0)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 0, wx.ALL | wx.EXPAND, 12)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        root.Add(log_label, 0, wx.LEFT | wx.RIGHT, 12)
        root.Add(self._log, 1, wx.ALL | wx.EXPAND, 12)

        panel.SetSizer(root)

        self._device_choices: list[_DeviceChoice] = []
        self._session: StreamingSession | None = None
        self._session_lock = threading.Lock()

        self._refresh.Bind(wx.EVT_BUTTON, self._on_refresh)
        self._advanced_btn.Bind(wx.EVT_BUTTON, self._on_advanced)
        self._start.Bind(wx.EVT_BUTTON, self._on_start)
        self._stop.Bind(wx.EVT_BUTTON, self._on_stop)
        self._source.Bind(wx.EVT_CHOICE, self._on_source_changed)
        self._preset.Bind(wx.EVT_CHOICE, self._on_preset_changed)
        self._preset_save.Bind(wx.EVT_BUTTON, self._on_preset_save)
        self._preset_delete.Bind(wx.EVT_BUTTON, self._on_preset_delete)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._populate_devices()
        self._refresh_presets(select_name=self._selected_preset_name)
        if self._selected_preset_name:
            self._apply_preset(self._selected_preset_name)

    def log(self, message: str) -> None:
        self._log.AppendText(message + "\n")

    def _populate_devices(self) -> None:
        self._device.Clear()
        self._device_choices.clear()

        try:
            source_is_input = self._source.GetSelection() == 1
            if source_is_input:
                devices = list_microphones()
                default_id = default_microphone_id()
            else:
                devices = list_speakers()
                default_id = default_speaker_id()
        except Exception as exc:
            self.log(self._t("log.device_enum_failed", error=str(exc)))
            return

        default_index = 0
        preferred_id = self._device_id_input if source_is_input else self._device_id_output
        for idx, device in enumerate(devices):
            label = f"{device.name} ({device.channels}ch)"
            self._device_choices.append(_DeviceChoice(label=label, id=device.id))
            self._device.Append(label)
            if preferred_id and device.id == preferred_id:
                default_index = idx
            elif not preferred_id and device.id == default_id:
                default_index = idx

        if self._device_choices:
            self._device.SetSelection(default_index)

    def _parse_sids(self) -> list[int]:
        raw = self._sids.GetValue().strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        sids: list[int] = []
        for part in parts:
            sid = int(part)
            if sid <= 0:
                raise ValueError(self._t("error.sid_min"))
            sids.append(sid)
        if not sids:
            raise ValueError(self._t("error.no_sids"))
        return sids

    def _selected_device_id(self) -> str:
        idx = self._device.GetSelection()
        if idx < 0 or idx >= len(self._device_choices):
            raise RuntimeError(self._t("error.no_device_selected"))
        return self._device_choices[idx].id

    def _refresh_presets(self, *, select_name: str = "") -> None:
        self._preset.Clear()
        self._preset_names: list[str] = [str(p.get("name") or "") for p in self._presets]
        for name in self._preset_names:
            self._preset.Append(name)

        selected = wx.NOT_FOUND
        if select_name:
            try:
                selected = self._preset_names.index(select_name)
            except ValueError:
                selected = wx.NOT_FOUND

        if selected != wx.NOT_FOUND:
            self._preset.SetSelection(selected)
            self._selected_preset_name = select_name
        elif self._preset_names:
            self._preset.SetSelection(0)

        self._preset_delete.Enable(bool(self._preset_names))

    def _find_preset(self, name: str) -> dict[str, Any] | None:
        name = name.strip()
        if not name:
            return None
        for preset in self._presets:
            if str(preset.get("name") or "").strip() == name:
                return preset
        return None

    def _apply_preset(self, name: str) -> None:
        preset = self._find_preset(name)
        if preset is None:
            return

        self._host.SetValue(str(preset.get("host") or "127.0.0.1"))
        self._port.SetValue(str(preset.get("port") or "8000"))
        self._sids.SetValue(str(preset.get("sids") or "1"))
        self._no_match_text.SetValue(str(preset.get("no_match_text") or ""))
        self._password.SetValue(decrypt_secret(str(preset.get("password") or "")))
        self._selected_preset_name = name
        self._persist_config()

    def _collect_config(self) -> dict[str, Any]:
        ui_language = self._ui_language_code
        ui_idx = self._ui_language_choice.GetSelection()
        if ui_idx != wx.NOT_FOUND and ui_idx < len(self._ui_language_codes):
            ui_language = self._ui_language_codes[ui_idx]

        language = "en-US"
        lang_idx = self._language.GetSelection()
        if lang_idx != wx.NOT_FOUND and lang_idx < len(self._language_codes):
            language = self._language_codes[lang_idx]

        endpoint_country = "US"
        country_idx = self._country.GetSelection()
        if country_idx != wx.NOT_FOUND and country_idx < len(self._country_codes):
            endpoint_country = self._country_codes[country_idx]

        source = "input" if self._source.GetSelection() == 1 else "output"
        try:
            device_id = self._selected_device_id()
            if source == "input":
                self._device_id_input = device_id
            else:
                self._device_id_output = device_id
        except Exception:
            pass

        port_val: int | str
        try:
            port_val = int(self._port.GetValue().strip())
        except Exception:
            port_val = self._port.GetValue().strip()

        listen_val: int | str
        try:
            listen_val = int(self._listen_seconds.GetValue().strip())
        except Exception:
            listen_val = self._listen_seconds.GetValue().strip()

        sanitized_presets: list[dict[str, Any]] = []
        for preset in self._presets:
            if not isinstance(preset, dict):
                continue
            name = str(preset.get("name") or "").strip()
            if not name:
                continue
            item = dict(preset)
            password = str(item.get("password") or "")
            if password and not (password.startswith("dpapi:") or password.startswith("b64:")):
                item["password"] = encrypt_secret(password)
            sanitized_presets.append(item)

        sanitized_presets.sort(key=lambda p: str(p.get("name") or "").lower())
        self._presets = sanitized_presets

        return {
            "version": config_version(),
            "ui_language": ui_language,
            "host": self._host.GetValue().strip(),
            "port": port_val,
            "password": encrypt_secret(self._password.GetValue()),
            "sids": self._sids.GetValue().strip(),
            "listen_seconds": listen_val,
            "no_match_text": self._no_match_text.GetValue(),
            "language": language,
            "endpoint_country": endpoint_country,
            "source": source,
            "device_id_output": self._device_id_output,
            "device_id_input": self._device_id_input,
            "selected_preset": self._selected_preset_name,
            "presets": sanitized_presets,
            "advanced": {
                "shazam_segment_seconds": int(self._advanced.shazam_segment_seconds),
                "max_windows_per_sample": int(self._advanced.max_windows_per_sample),
                "window_step_s": int(self._advanced.window_step_s),
                "silence_dbfs_threshold": float(self._advanced.silence_dbfs_threshold),
                "min_request_interval_s": float(self._advanced.min_request_interval_s),
                "sample_rate_hz": int(self._advanced.sample_rate_hz),
                "channels": int(self._advanced.channels),
                "chunk_frames": int(self._advanced.chunk_frames),
            },
        }

    def _persist_config(self) -> None:
        try:
            save_config(self._collect_config())
        except Exception as exc:
            try:
                self.log(self._t("log.config_save_failed", error=str(exc)))
            except Exception:
                pass

    def _on_ui_language_changed(self, _evt: wx.CommandEvent) -> None:
        self._persist_config()
        wx.MessageBox(
            self._t("info.restart_required"),
            _APP_NAME,
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def _on_device_changed(self, _evt: wx.CommandEvent) -> None:
        source = "input" if self._source.GetSelection() == 1 else "output"
        try:
            device_id = self._selected_device_id()
        except Exception:
            return
        if source == "input":
            self._device_id_input = device_id
        else:
            self._device_id_output = device_id
        self._persist_config()

    def _on_preset_changed(self, _evt: wx.CommandEvent) -> None:
        idx = self._preset.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(getattr(self, "_preset_names", [])):
            return
        name = self._preset_names[idx]
        if name:
            self._apply_preset(name)

    def _on_preset_save(self, _evt: wx.CommandEvent) -> None:
        current_name = self._selected_preset_name
        if not current_name:
            current_name = f"{self._host.GetValue().strip()}:{self._port.GetValue().strip()}".strip(":")

        with wx.TextEntryDialog(
            self, self._t("dialog.preset_name"), _APP_NAME, value=current_name
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()

        if not name:
            wx.MessageBox(
                self._t("error.preset_name_required"), _APP_NAME, wx.OK | wx.ICON_ERROR, self
            )
            return

        preset = {
            "name": name,
            "host": self._host.GetValue().strip(),
            "port": self._port.GetValue().strip(),
            "password": encrypt_secret(self._password.GetValue()),
            "sids": self._sids.GetValue().strip(),
            "no_match_text": self._no_match_text.GetValue(),
        }

        existing = self._find_preset(name)
        if existing is None:
            self._presets.append(preset)
        else:
            existing.clear()
            existing.update(preset)

        self._presets.sort(key=lambda p: str(p.get("name") or "").lower())
        self._selected_preset_name = name
        self._refresh_presets(select_name=name)
        self._persist_config()

    def _on_preset_delete(self, _evt: wx.CommandEvent) -> None:
        idx = self._preset.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(getattr(self, "_preset_names", [])):
            return
        name = self._preset_names[idx]
        if not name:
            return

        res = wx.MessageBox(
            self._t("prompt.delete_preset", name=name),
            _APP_NAME,
            wx.YES_NO | wx.ICON_WARNING,
            self,
        )
        if res != wx.YES:
            return

        self._presets = [p for p in self._presets if str(p.get("name") or "").strip() != name]
        if self._selected_preset_name == name:
            self._selected_preset_name = ""
        self._refresh_presets(select_name=self._selected_preset_name)
        self._persist_config()

    def _on_advanced(self, _evt: wx.CommandEvent) -> None:
        focus_before = wx.Window.FindFocus()
        focus_target: wx.Window
        if focus_before is not None and self.IsDescendant(focus_before):
            focus_target = focus_before
        else:
            focus_target = self._advanced_btn

        dialog = wx.Dialog(
            self,
            title=self._t("dialog.advanced.title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        dialog.SetMinClientSize((640, 460))

        panel = wx.Panel(dialog)

        seg_label = wx.StaticText(panel, label=self._t("adv.segment_seconds"))
        seg = wx.TextCtrl(panel, value=str(self._advanced.shazam_segment_seconds))
        _a11y(seg, self._t("adv.segment_seconds").rstrip(":"))

        win_label = wx.StaticText(panel, label=self._t("adv.max_windows"))
        win = wx.TextCtrl(panel, value=str(self._advanced.max_windows_per_sample))
        _a11y(win, self._t("adv.max_windows").rstrip(":"))

        step_label = wx.StaticText(panel, label=self._t("adv.window_step"))
        step = wx.TextCtrl(panel, value=str(self._advanced.window_step_s))
        _a11y(step, self._t("adv.window_step").rstrip(":"))

        silence_label = wx.StaticText(panel, label=self._t("adv.silence_dbfs"))
        silence = wx.TextCtrl(panel, value=str(self._advanced.silence_dbfs_threshold))
        _a11y(silence, self._t("adv.silence_dbfs").rstrip(":"))

        interval_label = wx.StaticText(panel, label=self._t("adv.min_api_interval"))
        interval = wx.TextCtrl(panel, value=str(self._advanced.min_request_interval_s))
        _a11y(interval, self._t("adv.min_api_interval").rstrip(":"))

        rate_label = wx.StaticText(panel, label=self._t("adv.sample_rate"))
        rate = wx.TextCtrl(panel, value=str(self._advanced.sample_rate_hz))
        _a11y(rate, self._t("adv.sample_rate").rstrip(":"))

        channels_label = wx.StaticText(panel, label=self._t("adv.channels"))
        channels = wx.TextCtrl(panel, value=str(self._advanced.channels))
        _a11y(channels, self._t("adv.channels").rstrip(":"))

        chunk_label = wx.StaticText(panel, label=self._t("adv.chunk_frames"))
        chunk = wx.TextCtrl(panel, value=str(self._advanced.chunk_frames))
        _a11y(chunk, self._t("adv.chunk_frames").rstrip(":"))

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)
        for label, ctrl in [
            (seg_label, seg),
            (win_label, win),
            (step_label, step),
            (silence_label, silence),
            (interval_label, interval),
            (rate_label, rate),
            (channels_label, channels),
            (chunk_label, chunk),
        ]:
            grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 0, wx.EXPAND)

        buttons = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        buttons.AddButton(ok_btn)
        buttons.AddButton(cancel_btn)
        buttons.Realize()
        dialog.SetAffirmativeId(wx.ID_OK)
        dialog.SetEscapeId(wx.ID_CANCEL)
        ok_btn.SetDefault()

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 1, wx.ALL | wx.EXPAND, 12)
        root.Add(buttons, 0, wx.ALL | wx.EXPAND, 12)
        panel.SetSizer(root)

        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog_sizer.Add(panel, 1, wx.EXPAND)
        dialog.SetSizer(dialog_sizer)
        dialog.Layout()
        dialog.CentreOnParent()

        def parse_int(value: str, *, minimum: int, maximum: int, label: str) -> int:
            try:
                n = int(value.strip())
            except ValueError as exc:
                raise ValueError(self._t("error.enter_int", label=label)) from exc
            if n < minimum or n > maximum:
                raise ValueError(self._t("error.range", label=label, minimum=minimum, maximum=maximum))
            return n

        def parse_float(value: str, *, minimum: float, maximum: float, label: str) -> float:
            try:
                n = float(value.strip().replace(",", "."))
            except ValueError as exc:
                raise ValueError(self._t("error.enter_float", label=label)) from exc
            if n < minimum or n > maximum:
                raise ValueError(self._t("error.range", label=label, minimum=minimum, maximum=maximum))
            return n

        def repaint_parent() -> None:
            try:
                self.Raise()
                self.SetFocus()
                self.Refresh()
                self.Update()
                self.SendSizeEvent()
            except Exception:
                pass
            try:
                _win32_force_redraw(int(self.GetHandle()))
            except Exception:
                pass
            try:
                wx.YieldIfNeeded()
            except Exception:
                pass
            try:
                focus_target.SetFocus()
            except Exception:
                pass

        def on_ok(_event: wx.CommandEvent) -> None:
            try:
                seg_s = parse_int(
                    seg.GetValue(),
                    minimum=3,
                    maximum=60,
                    label=self._t("adv.segment_seconds_name"),
                )
                win_n = parse_int(
                    win.GetValue(),
                    minimum=1,
                    maximum=6,
                    label=self._t("adv.max_windows").rstrip(":"),
                )
                step_s = parse_int(
                    step.GetValue(),
                    minimum=1,
                    maximum=60,
                    label=self._t("adv.window_step_name"),
                )
                silence_dbfs = parse_float(
                    silence.GetValue(),
                    minimum=-100.0,
                    maximum=0.0,
                    label=self._t("adv.silence_dbfs").rstrip(":"),
                )
                min_interval_s = parse_float(
                    interval.GetValue(),
                    minimum=0.0,
                    maximum=60.0,
                    label=self._t("adv.min_api_interval").rstrip(":"),
                )
                rate_hz = parse_int(
                    rate.GetValue(),
                    minimum=8000,
                    maximum=48000,
                    label=self._t("adv.sample_rate").rstrip(":"),
                )
                ch = parse_int(
                    channels.GetValue(),
                    minimum=1,
                    maximum=2,
                    label=self._t("adv.channels").rstrip(":"),
                )
                chunk_frames = parse_int(
                    chunk.GetValue(),
                    minimum=128,
                    maximum=16384,
                    label=self._t("adv.chunk_frames").rstrip(":"),
                )
            except ValueError as exc:
                wx.MessageBox(str(exc), _APP_NAME, wx.OK | wx.ICON_ERROR, dialog)
                return

            self._advanced.shazam_segment_seconds = seg_s
            self._advanced.max_windows_per_sample = win_n
            self._advanced.window_step_s = step_s
            self._advanced.silence_dbfs_threshold = silence_dbfs
            self._advanced.min_request_interval_s = min_interval_s
            self._advanced.sample_rate_hz = rate_hz
            self._advanced.channels = ch
            self._advanced.chunk_frames = chunk_frames
            self._persist_config()
            dialog.EndModal(wx.ID_OK)

        def on_cancel(_event: wx.CommandEvent) -> None:
            dialog.EndModal(wx.ID_CANCEL)

        ok_btn.Bind(wx.EVT_BUTTON, on_ok)
        cancel_btn.Bind(wx.EVT_BUTTON, on_cancel)
        dialog.Bind(wx.EVT_CLOSE, lambda _e: dialog.EndModal(wx.ID_CANCEL))

        dialog.ShowModal()
        dialog.Destroy()
        repaint_parent()
        wx.CallLater(50, repaint_parent)

    def _on_refresh(self, _evt: wx.CommandEvent) -> None:
        self._populate_devices()

    def _on_source_changed(self, _evt: wx.CommandEvent) -> None:
        self._populate_devices()
        self._persist_config()

    def _on_start(self, _evt: wx.CommandEvent) -> None:
        try:
            source = "input" if self._source.GetSelection() == 1 else "output"
            port_raw = self._port.GetValue().strip()
            port = int(port_raw)
            if port < 1 or port > 65535:
                raise ValueError(self._t("error.port_range"))

            listen_raw = self._listen_seconds.GetValue().strip()
            listen_seconds = int(listen_raw)
            if listen_seconds < 3 or listen_seconds > 30:
                raise ValueError(self._t("error.listen_range"))

            lang_idx = self._language.GetSelection()
            if lang_idx == wx.NOT_FOUND or lang_idx >= len(self._language_codes):
                raise ValueError(self._t("error.choose_shazam_language"))
            language = self._language_codes[lang_idx]

            country_idx = self._country.GetSelection()
            if country_idx == wx.NOT_FOUND or country_idx >= len(self._country_codes):
                raise ValueError(self._t("error.choose_shazam_country"))
            endpoint_country = self._country_codes[country_idx]

            settings = StreamSettings(
                host=self._host.GetValue().strip(),
                port=port,
                password=self._password.GetValue(),
                sids=self._parse_sids(),
                source=source,
                device_id=self._selected_device_id(),
                language=language,
                endpoint_country=endpoint_country,
                listen_seconds=listen_seconds,
                no_match_text=self._no_match_text.GetValue(),
                shazam_segment_seconds=int(self._advanced.shazam_segment_seconds),
                max_windows_per_sample=int(self._advanced.max_windows_per_sample),
                window_step_s=int(self._advanced.window_step_s),
                silence_dbfs_threshold=float(self._advanced.silence_dbfs_threshold),
                min_request_interval_s=float(self._advanced.min_request_interval_s),
                sample_rate_hz=int(self._advanced.sample_rate_hz),
                channels=int(self._advanced.channels),
                chunk_frames=int(self._advanced.chunk_frames),
            )
        except Exception as exc:
            wx.MessageBox(str(exc), self._t("title.error"), wx.OK | wx.ICON_ERROR)
            return

        self._persist_config()

        with self._session_lock:
            if self._session is not None:
                return
            self._session = StreamingSession(settings=settings, log=lambda m: wx.CallAfter(self.log, m))
            self._session.start()

        self._start.Disable()
        self._stop.Enable()
        self.log(self._t("log.listening_started"))

    def _on_stop(self, _evt: wx.CommandEvent) -> None:
        with self._session_lock:
            session = self._session
            self._session = None

        if session is not None:
            session.stop()
            self.log(self._t("log.listening_stopped"))

        self._stop.Disable()
        self._start.Enable()

    def _on_close(self, evt: wx.CloseEvent) -> None:
        self._on_stop(wx.CommandEvent())
        self._persist_config()
        evt.Skip()


def main() -> None:
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
