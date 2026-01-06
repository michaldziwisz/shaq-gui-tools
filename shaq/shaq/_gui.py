# -*- coding: utf-8 -*-

import asyncio
import math
import os
import threading
import traceback
import wave
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from queue import Empty, Queue
from tempfile import NamedTemporaryFile
from typing import Any

from shaq._i18n import I18n, UI_LANGUAGE_CHOICES, ui_language_from_config
from shaq._file_scan import slice_wav_bytes
from shaq._shazam_regions import (
    SUPPORTED_ENDPOINT_COUNTRIES,
    SUPPORTED_LANGUAGES,
    country_choice_strings,
    country_codes,
    find_index_by_code,
    language_choice_strings,
    language_codes,
)

_APP_NAME = "shaqgui"

_SHAZAM_SEGMENT_DURATION_S = int(os.environ.get("SHAQGUI_SHAZAM_SEGMENT_SECONDS", "12"))
_SHAZAM_SEGMENT_DURATION_S = max(5, min(60, _SHAZAM_SEGMENT_DURATION_S))

_SAMPLE_DURATION_S = int(os.environ.get("SHAQGUI_SAMPLE_SECONDS", "15"))
_SAMPLE_DURATION_S = max(_SHAZAM_SEGMENT_DURATION_S, min(60, _SAMPLE_DURATION_S))

_MAX_WINDOWS_PER_SAMPLE = max(
    1, min(6, int(os.environ.get("SHAQGUI_MAX_WINDOWS_PER_SAMPLE", "2")))
)
_WINDOW_STEP_S = max(1, int(os.environ.get("SHAQGUI_WINDOW_STEP_S", "1")))
_SILENCE_DBFS_THRESHOLD = float(os.environ.get("SHAQGUI_SILENCE_DBFS_THRESHOLD", "-55.0"))

_DEFAULT_SHAZAM_LANGUAGE = os.environ.get("SHAQGUI_SHAZAM_LANGUAGE", "en-US").strip() or "en-US"
_DEFAULT_SHAZAM_COUNTRY = os.environ.get("SHAQGUI_SHAZAM_COUNTRY", "US").strip() or "US"

_CONFIG_VERSION = 1

_STRINGS: dict[str, dict[str, str]] = {
    "crash.unable_start": {
        "pl": "Nie mogę uruchomić aplikacji.",
        "en": "Unable to start the app.",
    },
    "crash.details_saved": {
        "pl": "Szczegóły zapisano w:\n{path}",
        "en": "Details were saved to:\n{path}",
    },
    "crash.vc_redist": {
        "pl": "Jeśli to świeża maszyna, doinstaluj: Microsoft Visual C++ Redistributable 2015–2022 (x64).",
        "en": "If this is a fresh machine, install: Microsoft Visual C++ Redistributable 2015–2022 (x64).",
    },
    "error.load_soundcard": {
        "pl": "Nie mogę załadować audio (soundcard): {error}",
        "en": "Unable to load audio (soundcard): {error}",
    },
    "error.load_shazamio": {
        "pl": "Nie mogę załadować shazamio: {error}",
        "en": "Unable to load shazamio: {error}",
    },
    "status.ready": {"pl": "Gotowe.", "en": "Ready."},
    "status.starting": {"pl": "Start...", "en": "Starting..."},
    "status.stopping": {"pl": "Zatrzymywanie...", "en": "Stopping..."},
    "status.listening": {"pl": "Nasłuchuję...", "en": "Listening..."},
    "status.recognizing": {"pl": "Rozpoznaję...", "en": "Recognizing..."},
    "status.recognizing_multi": {
        "pl": "Rozpoznaję ({current}/{total})...",
        "en": "Recognizing ({current}/{total})...",
    },
    "status.recognition_failed_backoff": {
        "pl": "Rozpoznawanie nieudane, pauza {seconds}s{detail}",
        "en": "Recognition failed, pausing {seconds}s{detail}",
    },
    "status.saved": {"pl": "Zapisano rozpoznanie.", "en": "Saved recognition."},
    "status.stopped": {"pl": "Zatrzymano.", "en": "Stopped."},
    "status.error": {"pl": "Błąd.", "en": "Error."},
    "error.list_audio_devices": {
        "pl": "Nie mogę pobrać listy urządzeń audio: {error}",
        "en": "Couldn't get list of audio devices: {error}",
    },
    "error.no_input_devices": {
        "pl": "Nie znaleziono żadnych urządzeń wejściowych (mikrofonów).",
        "en": "No input devices (microphones) found.",
    },
    "error.no_output_devices": {
        "pl": "Nie znaleziono żadnych urządzeń wyjściowych.",
        "en": "No output devices found.",
    },
    "error.no_audio_devices": {
        "pl": "Nie znaleziono żadnych urządzeń audio (wejście/wyjście).",
        "en": "No audio devices found (input/output).",
    },
    "error.no_device_selected": {
        "pl": "Nie wybrano urządzenia audio.",
        "en": "No audio device selected.",
    },
    "error.choose_output_file": {"pl": "Wybierz plik zapisu.", "en": "Select an output file."},
    "error.write_file": {"pl": "Nie mogę zapisać do pliku: {error}", "en": "Can't write to file: {error}"},
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
    "label.audio_source": {"pl": "Źródło audio:", "en": "Audio source:"},
    "choice.audio_source.output": {"pl": "Wyjście (loopback)", "en": "Output (loopback)"},
    "choice.audio_source.input": {"pl": "Wejście (mikrofon)", "en": "Input (microphone)"},
    "name.audio_source": {"pl": "Źródło audio", "en": "Audio source"},
    "label.device": {"pl": "Urządzenie:", "en": "Device:"},
    "name.device": {"pl": "Urządzenie audio", "en": "Audio device"},
    "label.shazam_language": {"pl": "Język Shazam:", "en": "Shazam language:"},
    "name.shazam_language": {"pl": "Język Shazam", "en": "Shazam language"},
    "help.shazam_language": {
        "pl": "Wybierz język (locale) używany przez Shazam.",
        "en": "Select the language (locale) used by Shazam.",
    },
    "label.shazam_country": {"pl": "Kraj Shazam:", "en": "Shazam country:"},
    "name.shazam_country": {"pl": "Kraj Shazam", "en": "Shazam country"},
    "help.shazam_country": {
        "pl": "Wybierz kraj (endpoint_country) używany przez Shazam.",
        "en": "Select the country (endpoint_country) used by Shazam.",
    },
    "label.output_file": {"pl": "Plik zapisu:", "en": "Output file:"},
    "name.output_file": {"pl": "Plik zapisu", "en": "Output file"},
    "button.browse": {"pl": "Wybierz...", "en": "Browse..."},
    "tooltip.browse": {
        "pl": "Wybierz plik, do którego będą zapisywane rozpoznania.",
        "en": "Choose the file where recognitions will be written.",
    },
    "name.saved_recognitions": {"pl": "Zapisane rozpoznania", "en": "Saved recognitions"},
    "label.saved_unique": {
        "pl": "Zapisane rozpoznania (unikalne):",
        "en": "Saved recognitions (unique):",
    },
    "button.advanced": {"pl": "Ustawienia zaawansowane…", "en": "Advanced settings..."},
    "tooltip.advanced": {
        "pl": "Zmień parametry wpływające na dokładność/limity API.",
        "en": "Change parameters affecting accuracy / API limits.",
    },
    "button.start": {"pl": "Start", "en": "Start"},
    "tooltip.start": {"pl": "Rozpocznij rozpoznawanie (Start).", "en": "Start recognition."},
    "button.stop": {"pl": "Stop", "en": "Stop"},
    "tooltip.stop": {"pl": "Zatrzymaj rozpoznawanie (Stop).", "en": "Stop recognition."},
    "status.config_save_failed": {
        "pl": "Nie udało się zapisać config: {error}",
        "en": "Failed to save config: {error}",
    },
    "dialog.advanced.title": {"pl": "Ustawienia zaawansowane", "en": "Advanced settings"},
    "adv.sample_seconds": {"pl": "Długość próbki (sek):", "en": "Sample length (sec):"},
    "name.sample_seconds": {"pl": "Długość próbki (sekundy)", "en": "Sample length (seconds)"},
    "adv.segment_seconds": {"pl": "Długość podpisu (sek):", "en": "Signature length (sec):"},
    "name.segment_seconds": {"pl": "Długość podpisu (sekundy)", "en": "Signature length (seconds)"},
    "adv.max_windows": {"pl": "Okna w próbce (max):", "en": "Windows per sample (max):"},
    "name.max_windows": {"pl": "Okna w próbce", "en": "Windows per sample"},
    "tooltip.max_windows": {
        "pl": "Ile prób (okien) w ramach jednej próbki audio.",
        "en": "How many tries (windows) within a single audio sample.",
    },
    "adv.window_step": {"pl": "Krok okna (sek):", "en": "Window step (sec):"},
    "name.window_step": {"pl": "Krok okna (sekundy)", "en": "Window step (seconds)"},
    "adv.silence_dbfs": {"pl": "Próg ciszy (dBFS):", "en": "Silence threshold (dBFS):"},
    "name.silence_dbfs": {"pl": "Próg ciszy (dBFS)", "en": "Silence threshold (dBFS)"},
    "tooltip.silence_dbfs": {
        "pl": "Jeśli najlepsze okno ma RMS poniżej progu, próbka nie jest wysyłana.",
        "en": "If the best window RMS is below this threshold, the sample isn't sent.",
    },
    "adv.error.segment_gt_sample": {
        "pl": "Długość podpisu nie może być większa niż długość próbki.",
        "en": "Signature length can't be greater than sample length.",
    },
    "adv.error.invalid_silence": {
        "pl": "Nieprawidłowy próg ciszy (dBFS).",
        "en": "Invalid silence threshold (dBFS).",
    },
    "file_dialog.choose_output": {"pl": "Wybierz plik zapisu", "en": "Select output file"},
}


def _config_path() -> Path:
    if os.name == "nt" and (appdata := os.environ.get("APPDATA")):
        return Path(appdata) / _APP_NAME / "config.json"

    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / _APP_NAME / "config.json"


def _load_config() -> dict[str, Any]:
    path = _config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_config(data: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent)) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _win32_force_redraw(hwnd: int) -> None:
    if os.name != "nt" or not hwnd:
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


@dataclass(frozen=True)
class _AdvancedSettings:
    sample_seconds: int
    segment_seconds: int
    max_windows_per_sample: int
    window_step_seconds: int
    silence_dbfs_threshold: float


def _default_advanced_settings() -> _AdvancedSettings:
    return _AdvancedSettings(
        sample_seconds=int(_SAMPLE_DURATION_S),
        segment_seconds=int(_SHAZAM_SEGMENT_DURATION_S),
        max_windows_per_sample=int(_MAX_WINDOWS_PER_SAMPLE),
        window_step_seconds=int(_WINDOW_STEP_S),
        silence_dbfs_threshold=float(_SILENCE_DBFS_THRESHOLD),
    )


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


@dataclass(frozen=True)
class _AudioDevice:
    name: str
    id: str
    kind: str  # "output" (loopback) or "input" (microphone)


class _HistoryWriter:
    def __init__(self, path: Path) -> None:
        self._path = path.expanduser()
        self._seen: set[str] = set()
        self._lock = threading.Lock()

        if self._path.exists():
            try:
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        self._seen.add(line)
            except OSError:
                # Best-effort only: if we can't read the file, dedupe will be session-only.
                pass

    def append_unique(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return False

        with self._lock:
            if line in self._seen:
                return False

            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as io:
                io.write(f"{line}\n")
            self._seen.add(line)
            return True


def _record_wav(
    sc: Any,
    device_id: str,
    *,
    include_loopback: bool,
    duration_s: int,
    sample_rate: int,
    channels: int,
    chunk_size: int,
    stop_event: threading.Event,
) -> bytearray:
    import wave
    from io import BytesIO

    import numpy as np

    microphone = sc.get_microphone(device_id, include_loopback=include_loopback)
    total_frames = sample_rate * duration_s
    frames_recorded = 0

    with (
        BytesIO() as io,
        wave.open(io, "wb") as wav,
        microphone.recorder(samplerate=sample_rate, channels=channels) as recorder,
    ):
        wav.setnchannels(channels)
        wav.setsampwidth(2)  # PCM16
        wav.setframerate(sample_rate)

        while frames_recorded < total_frames and not stop_event.is_set():
            frames = min(chunk_size, total_frames - frames_recorded)
            chunk = recorder.record(numframes=frames)

            pcm16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
            wav.writeframes(pcm16.tobytes())
            frames_recorded += frames

        return bytearray(io.getvalue())


def _rank_window_starts_by_rms(
    wav_bytes: bytes,
    *,
    window_duration_s: int,
    window_step_s: int,
    max_windows: int,
) -> tuple[list[int], float]:
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as wav_in:
            channels = wav_in.getnchannels()
            sampwidth = wav_in.getsampwidth()
            framerate = wav_in.getframerate()
            declared_nframes = wav_in.getnframes()
            frames = wav_in.readframes(declared_nframes)
    except wave.Error:
        return [0], float("-inf")

    if framerate <= 0 or sampwidth != 2:
        return [0], float("-inf")

    frame_size = channels * sampwidth
    if frame_size <= 0:
        return [0], float("-inf")

    actual_nframes = len(frames) // frame_size
    if actual_nframes <= 0:
        return [0], float("-inf")

    frames = frames[: actual_nframes * frame_size]

    import numpy as np

    pcm = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)

    window_frames = int(window_duration_s * framerate)
    if window_frames <= 0 or window_frames >= pcm.shape[0]:
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        dbfs = float("-inf") if rms <= 0 else 20.0 * math.log10(rms / 32767.0)
        return [0], dbfs

    step_frames = max(1, int(window_step_s * framerate))
    last_start = pcm.shape[0] - window_frames
    candidates: list[tuple[float, int]] = []
    for start_frame in range(0, last_start + 1, step_frames):
        window = pcm[start_frame : start_frame + window_frames]
        if window.size <= 0:
            continue
        rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2)))
        candidates.append((rms, start_frame))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    best_rms = candidates[0][0] if candidates else 0.0
    best_dbfs = float("-inf") if best_rms <= 0 else 20.0 * math.log10(best_rms / 32767.0)

    starts: list[int] = []
    seen: set[int] = set()
    for _rms, start_frame in candidates:
        start_s = int(start_frame / framerate)
        if start_s in seen:
            continue
        seen.add(start_s)
        starts.append(start_s)
        if len(starts) >= max_windows:
            break

    if not starts:
        starts = [0]

    return starts, best_dbfs


def _win_error_dialog(message: str) -> None:
    if os.name != "nt":
        return

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, _APP_NAME, 0x10)
    except Exception:
        pass


def _write_crash_log(text: str) -> Path | None:
    try:
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        log_dir = base / _APP_NAME
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "crash.log"
        log_path.write_text(text, encoding="utf-8")
        return log_path
    except Exception:
        return None


def _default_output_file() -> Path:
    if output := os.environ.get("SHAQGUI_OUTPUT"):
        return Path(output)

    if os.name == "nt" and (appdata := os.environ.get("APPDATA")):
        return Path(appdata) / _APP_NAME / "history.txt"

    return Path.home() / "shaqgui.txt"


def main() -> None:
    t = I18n(ui_language_from_config(_load_config().get("ui_language")), _STRINGS).t
    try:
        _main()
    except Exception:
        trace = traceback.format_exc()
        log_path = _write_crash_log(trace)

        msg = t("crash.unable_start")
        if log_path is not None:
            msg += "\n\n" + t("crash.details_saved", path=str(log_path))
        msg += "\n\n" + t("crash.vc_redist")

        _win_error_dialog(msg)


def _main() -> None:
    import wx

    try:
        import soundcard as sc  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Nie mogę załadować audio (soundcard): {exc}") from exc

    from shaq._soundcard_compat import patch_soundcard_numpy_fromstring

    patch_soundcard_numpy_fromstring()

    try:
        from shazamio import Serialize, Shazam  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Nie mogę załadować shazamio: {exc}") from exc

    app = wx.App(False)
    config = _load_config()
    ui_language = ui_language_from_config(config.get("ui_language"))
    i18n = I18n(ui_language, _STRINGS)
    t = i18n.t

    class MainFrame(wx.Frame):
        def __init__(self) -> None:
            super().__init__(None, title=_APP_NAME)
            self.SetMinClientSize((620, 360))

            panel = wx.Panel(self)
            self.CreateStatusBar()
            self.SetStatusText(t("status.ready"))

            try:
                self._speakers = [_AudioDevice(s.name, s.id, "output") for s in sc.all_speakers()]
                self._microphones = [
                    _AudioDevice(m.name, m.id, "input") for m in sc.all_microphones()
                ]
            except Exception as exc:
                wx.MessageBox(
                    t("error.list_audio_devices", error=str(exc)),
                    _APP_NAME,
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                self._speakers = []
                self._microphones = []

            self._events: Queue[tuple[str, str]] = Queue()
            self._stop_event = threading.Event()
            self._worker: threading.Thread | None = None

            self._device_id_output = str(config.get("device_id_output") or "").strip() or None
            self._device_id_input = str(config.get("device_id_input") or "").strip() or None

            adv_cfg = config.get("advanced") if isinstance(config.get("advanced"), dict) else {}
            defaults = _default_advanced_settings()
            segment_seconds = _clamp_int(
                adv_cfg.get("segment_seconds", defaults.segment_seconds), minimum=5, maximum=60
            )
            sample_seconds = _clamp_int(
                adv_cfg.get("sample_seconds", defaults.sample_seconds), minimum=5, maximum=60
            )
            sample_seconds = max(sample_seconds, segment_seconds)
            max_windows = _clamp_int(
                adv_cfg.get("max_windows_per_sample", defaults.max_windows_per_sample),
                minimum=1,
                maximum=6,
            )
            window_step = _clamp_int(
                adv_cfg.get("window_step_seconds", defaults.window_step_seconds),
                minimum=1,
                maximum=60,
            )
            silence_dbfs = _clamp_float(
                adv_cfg.get("silence_dbfs_threshold", defaults.silence_dbfs_threshold),
                minimum=-100.0,
                maximum=0.0,
            )
            if not adv_cfg:
                segment_seconds = defaults.segment_seconds
                sample_seconds = defaults.sample_seconds
                max_windows = defaults.max_windows_per_sample
                window_step = defaults.window_step_seconds
                silence_dbfs = defaults.silence_dbfs_threshold

            self._advanced = _AdvancedSettings(
                sample_seconds=sample_seconds,
                segment_seconds=segment_seconds,
                max_windows_per_sample=max_windows,
                window_step_seconds=window_step,
                silence_dbfs_threshold=silence_dbfs,
            )

            self._ui_language_codes = [code for code, _label in UI_LANGUAGE_CHOICES]
            self.ui_language_choice = wx.Choice(
                panel, choices=[label for _code, label in UI_LANGUAGE_CHOICES]
            )
            self.ui_language_choice.SetName(t("name.ui_language"))
            self.ui_language_choice.SetToolTip(t("tooltip.ui_language"))
            self.ui_language_choice.SetSelection(0 if ui_language == "pl" else 1)
            self.ui_language_choice.Bind(wx.EVT_CHOICE, self._on_ui_language_changed)

            ui_lang_label = wx.StaticText(panel, label=t("label.ui_language"))

            source_label = wx.StaticText(panel, label=t("label.audio_source"))
            self.source_choice = wx.Choice(
                panel,
                choices=[
                    t("choice.audio_source.output"),
                    t("choice.audio_source.input"),
                ],
            )
            self.source_choice.SetName(t("name.audio_source"))
            self.source_choice.Bind(wx.EVT_CHOICE, self._on_source_changed)
            source_cfg = str(config.get("source") or "").strip().lower()
            if source_cfg in {"input", "mic", "microphone"}:
                self.source_choice.SetSelection(1)
            else:
                self.source_choice.SetSelection(0)

            device_label = wx.StaticText(panel, label=t("label.device"))
            self.device_choice = wx.Choice(panel, choices=[])
            self.device_choice.SetName(t("name.device"))
            self.device_choice.Bind(wx.EVT_CHOICE, self._on_device_changed)
            self._devices: list[_AudioDevice] = []
            self._populate_devices()

            language_label = wx.StaticText(panel, label=t("label.shazam_language"))
            self._language_codes = language_codes()
            self.language_choice = wx.Choice(panel, choices=language_choice_strings())
            self.language_choice.SetName(t("name.shazam_language"))
            self.language_choice.SetHelpText(t("help.shazam_language"))
            cfg_language = str(config.get("language") or "").strip() or _DEFAULT_SHAZAM_LANGUAGE
            language_idx = find_index_by_code(SUPPORTED_LANGUAGES, cfg_language)
            self.language_choice.SetSelection(language_idx if language_idx is not None else 0)

            country_label = wx.StaticText(panel, label=t("label.shazam_country"))
            self._country_codes = country_codes()
            self.country_choice = wx.Choice(panel, choices=country_choice_strings())
            self.country_choice.SetName(t("name.shazam_country"))
            self.country_choice.SetHelpText(t("help.shazam_country"))
            cfg_country = str(config.get("endpoint_country") or "").strip() or _DEFAULT_SHAZAM_COUNTRY
            country_idx = find_index_by_code(SUPPORTED_ENDPOINT_COUNTRIES, cfg_country)
            self.country_choice.SetSelection(country_idx if country_idx is not None else 0)

            out_label = wx.StaticText(panel, label=t("label.output_file"))
            cfg_out = str(config.get("output_path") or "").strip()
            self.out_path = wx.TextCtrl(panel, value=cfg_out or str(_default_output_file()))
            self.out_path.SetName(t("name.output_file"))
            self.browse_btn = wx.Button(panel, label=t("button.browse"))
            self.browse_btn.SetToolTip(t("tooltip.browse"))
            self.browse_btn.Bind(wx.EVT_BUTTON, self._on_browse)

            self.log_list = wx.ListBox(panel)
            self.log_list.SetName(t("name.saved_recognitions"))

            self.advanced_btn = wx.Button(panel, label=t("button.advanced"))
            self.advanced_btn.SetToolTip(t("tooltip.advanced"))
            self.advanced_btn.Bind(wx.EVT_BUTTON, self._on_advanced)

            self.start_btn = wx.Button(panel, label=t("button.start"))
            self.start_btn.SetToolTip(t("tooltip.start"))
            self.start_btn.Bind(wx.EVT_BUTTON, self._on_start)
            self.stop_btn = wx.Button(panel, label=t("button.stop"))
            self.stop_btn.SetToolTip(t("tooltip.stop"))
            self.stop_btn.Bind(wx.EVT_BUTTON, self._on_stop)
            self.stop_btn.Disable()

            grid = wx.FlexGridSizer(rows=6, cols=3, vgap=8, hgap=8)
            grid.AddGrowableCol(1, 1)
            grid.Add(ui_lang_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.ui_language_choice, 0)
            grid.Add((1, 1))
            grid.Add(source_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.source_choice, 1, wx.EXPAND)
            grid.Add((1, 1))
            grid.Add(device_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.device_choice, 1, wx.EXPAND)
            grid.Add((1, 1))
            grid.Add(language_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.language_choice, 1, wx.EXPAND)
            grid.Add((1, 1))
            grid.Add(country_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.country_choice, 1, wx.EXPAND)
            grid.Add((1, 1))
            grid.Add(out_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.out_path, 1, wx.EXPAND)
            grid.Add(self.browse_btn, 0)

            buttons = wx.BoxSizer(wx.HORIZONTAL)
            buttons.Add(self.advanced_btn, 0, wx.RIGHT, 8)
            buttons.AddStretchSpacer(1)
            buttons.Add(self.start_btn, 0, wx.RIGHT, 8)
            buttons.Add(self.stop_btn, 0)

            layout = wx.BoxSizer(wx.VERTICAL)
            layout.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
            layout.Add(
                wx.StaticText(panel, label=t("label.saved_unique")),
                0,
                wx.LEFT | wx.RIGHT,
                12,
            )
            layout.Add(self.log_list, 1, wx.EXPAND | wx.ALL, 12)
            layout.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            panel.SetSizer(layout)

            self._timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
            self._timer.Start(150)

            self.Bind(wx.EVT_CLOSE, self._on_close)

        def _set_running(self, running: bool) -> None:
            self.start_btn.Enable(not running)
            self.stop_btn.Enable(running)
            self.ui_language_choice.Enable(not running)
            self.source_choice.Enable(not running)
            self.device_choice.Enable(not running)
            self.language_choice.Enable(not running)
            self.country_choice.Enable(not running)
            self.out_path.Enable(not running)
            self.browse_btn.Enable(not running)
            self.advanced_btn.Enable(not running)

        def _populate_devices(self) -> None:
            self.device_choice.Clear()
            self._devices.clear()

            source_idx = self.source_choice.GetSelection()
            if source_idx == wx.NOT_FOUND:
                source_idx = 0
                if self.source_choice.GetCount() > 0:
                    self.source_choice.SetSelection(source_idx)

            if source_idx == 1:
                candidates = list(self._microphones)
                empty_message = t("error.no_input_devices")
            else:
                candidates = list(self._speakers)
                empty_message = t("error.no_output_devices")

            self._devices.extend(candidates)
            preferred_id = self._device_id_input if source_idx == 1 else self._device_id_output
            preferred_index = 0
            for dev in candidates:
                self.device_choice.Append(dev.name)
            if preferred_id:
                for idx, dev in enumerate(candidates):
                    if dev.id == preferred_id:
                        preferred_index = idx
                        break

            if candidates:
                self.device_choice.SetSelection(preferred_index)
            else:
                wx.MessageBox(empty_message, _APP_NAME, wx.OK | wx.ICON_ERROR, self)

        def _selected_device(self) -> _AudioDevice:
            idx = self.device_choice.GetSelection()
            if idx == wx.NOT_FOUND or idx >= len(self._devices):
                raise RuntimeError(t("error.no_device_selected"))
            return self._devices[idx]

        def _on_ui_language_changed(self, _event: wx.CommandEvent) -> None:
            self._persist_config()
            wx.MessageBox(t("info.restart_required"), _APP_NAME, wx.OK | wx.ICON_INFORMATION, self)

        def _on_source_changed(self, _event: wx.CommandEvent) -> None:
            self._populate_devices()

        def _on_device_changed(self, _event: wx.CommandEvent) -> None:
            try:
                device = self._selected_device()
            except Exception:
                return
            if self.source_choice.GetSelection() == 1:
                self._device_id_input = device.id
            else:
                self._device_id_output = device.id

        def _collect_config(self) -> dict[str, Any]:
            ui_language_value = ui_language
            ui_idx = self.ui_language_choice.GetSelection()
            if ui_idx != wx.NOT_FOUND and ui_idx < len(self._ui_language_codes):
                ui_language_value = self._ui_language_codes[ui_idx]

            language = _DEFAULT_SHAZAM_LANGUAGE
            lang_idx = self.language_choice.GetSelection()
            if lang_idx != wx.NOT_FOUND and lang_idx < len(self._language_codes):
                language = self._language_codes[lang_idx]

            endpoint_country = _DEFAULT_SHAZAM_COUNTRY
            country_idx = self.country_choice.GetSelection()
            if country_idx != wx.NOT_FOUND and country_idx < len(self._country_codes):
                endpoint_country = self._country_codes[country_idx]

            source = "input" if self.source_choice.GetSelection() == 1 else "output"
            try:
                device = self._selected_device()
                if source == "input":
                    self._device_id_input = device.id
                else:
                    self._device_id_output = device.id
            except Exception:
                pass

            return {
                "version": _CONFIG_VERSION,
                "ui_language": ui_language_value,
                "output_path": self.out_path.GetValue(),
                "source": source,
                "device_id_output": self._device_id_output,
                "device_id_input": self._device_id_input,
                "language": language,
                "endpoint_country": endpoint_country,
                "advanced": {
                    "sample_seconds": self._advanced.sample_seconds,
                    "segment_seconds": self._advanced.segment_seconds,
                    "max_windows_per_sample": self._advanced.max_windows_per_sample,
                    "window_step_seconds": self._advanced.window_step_seconds,
                    "silence_dbfs_threshold": self._advanced.silence_dbfs_threshold,
                },
            }

        def _persist_config(self) -> None:
            try:
                _save_config(self._collect_config())
            except Exception as exc:
                self.SetStatusText(t("status.config_save_failed", error=str(exc)))

        def _on_advanced(self, _event: wx.CommandEvent) -> None:
            focus_before = wx.Window.FindFocus()
            if focus_before is not None and self.IsDescendant(focus_before):
                focus_target = focus_before
            else:
                focus_target = self.advanced_btn

            def _restore_focus() -> None:
                target = focus_target
                try:
                    if not target.IsEnabled() or not target.IsShownOnScreen():
                        target = self.advanced_btn
                except Exception:
                    target = self.advanced_btn
                try:
                    target.SetFocus()
                except Exception:
                    pass

            def _after_modal() -> None:
                try:
                    self.Raise()
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
                _restore_focus()

            dialog = wx.Dialog(
                self,
                title=t("dialog.advanced.title"),
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            )
            dialog.SetMinClientSize((560, 320))

            panel = wx.Panel(dialog)

            sample_label = wx.StaticText(panel, label=t("adv.sample_seconds"))
            sample = wx.SpinCtrl(panel, min=5, max=60, initial=int(self._advanced.sample_seconds))
            sample.SetName(t("name.sample_seconds"))

            segment_label = wx.StaticText(panel, label=t("adv.segment_seconds"))
            segment = wx.SpinCtrl(panel, min=5, max=60, initial=int(self._advanced.segment_seconds))
            segment.SetName(t("name.segment_seconds"))

            windows_label = wx.StaticText(panel, label=t("adv.max_windows"))
            windows = wx.SpinCtrl(
                panel, min=1, max=6, initial=int(self._advanced.max_windows_per_sample)
            )
            windows.SetName(t("name.max_windows"))
            windows.SetToolTip(t("tooltip.max_windows"))

            step_label = wx.StaticText(panel, label=t("adv.window_step"))
            step = wx.SpinCtrl(panel, min=1, max=60, initial=int(self._advanced.window_step_seconds))
            step.SetName(t("name.window_step"))

            silence_label = wx.StaticText(panel, label=t("adv.silence_dbfs"))
            silence = wx.TextCtrl(panel, value=str(self._advanced.silence_dbfs_threshold))
            silence.SetName(t("name.silence_dbfs"))
            silence.SetToolTip(t("tooltip.silence_dbfs"))

            grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
            grid.AddGrowableCol(1, 1)
            grid.Add(sample_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(sample, 0, wx.EXPAND)
            grid.Add(segment_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(segment, 0, wx.EXPAND)
            grid.Add(windows_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(windows, 0, wx.EXPAND)
            grid.Add(step_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(step, 0, wx.EXPAND)
            grid.Add(silence_label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(silence, 0, wx.EXPAND)

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
            root.Add(grid, 0, wx.ALL | wx.EXPAND, 12)
            root.Add(buttons, 0, wx.ALL | wx.EXPAND, 12)
            panel.SetSizer(root)

            dialog_sizer = wx.BoxSizer(wx.VERTICAL)
            dialog_sizer.Add(panel, 1, wx.EXPAND)
            dialog.SetSizer(dialog_sizer)
            dialog.Layout()
            dialog.CentreOnParent()

            def on_ok(_evt: wx.CommandEvent) -> None:
                sample_seconds = int(sample.GetValue())
                segment_seconds = int(segment.GetValue())
                if segment_seconds > sample_seconds:
                    wx.MessageBox(
                        t("adv.error.segment_gt_sample"),
                        _APP_NAME,
                        wx.OK | wx.ICON_ERROR,
                        dialog,
                    )
                    return

                try:
                    silence_dbfs = float(silence.GetValue().strip().replace(",", "."))
                except ValueError:
                    wx.MessageBox(
                        t("adv.error.invalid_silence"),
                        _APP_NAME,
                        wx.OK | wx.ICON_ERROR,
                        dialog,
                    )
                    return

                self._advanced = _AdvancedSettings(
                    sample_seconds=sample_seconds,
                    segment_seconds=segment_seconds,
                    max_windows_per_sample=int(windows.GetValue()),
                    window_step_seconds=int(step.GetValue()),
                    silence_dbfs_threshold=silence_dbfs,
                )
                self._persist_config()
                dialog.EndModal(wx.ID_OK)

            ok_btn.Bind(wx.EVT_BUTTON, on_ok)
            cancel_btn.Bind(wx.EVT_BUTTON, lambda _e: dialog.EndModal(wx.ID_CANCEL))
            dialog.Bind(wx.EVT_CLOSE, lambda _e: dialog.EndModal(wx.ID_CANCEL))

            dialog.ShowModal()
            dialog.Destroy()
            wx.CallAfter(_after_modal)
            wx.CallLater(50, _after_modal)

        def _on_browse(self, _event: wx.CommandEvent) -> None:
            with wx.FileDialog(
                self,
                message=t("file_dialog.choose_output"),
                defaultDir=str(Path(self.out_path.GetValue()).expanduser().parent),
                defaultFile=str(Path(self.out_path.GetValue()).name),
                wildcard="Text files (*.txt)|*.txt|All files (*.*)|*.*",
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            ) as dialog:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return
                self.out_path.SetValue(dialog.GetPath())

        def _on_start(self, _event: wx.CommandEvent) -> None:
            if self._worker and self._worker.is_alive():
                return

            if not self._speakers:
                if not self._microphones:
                    wx.MessageBox(
                        t("error.no_audio_devices"),
                        _APP_NAME,
                        wx.OK | wx.ICON_ERROR,
                        self,
                    )
                    return

            out_path = Path(self.out_path.GetValue()).expanduser()
            if not str(out_path).strip():
                wx.MessageBox(t("error.choose_output_file"), _APP_NAME, wx.OK | wx.ICON_ERROR, self)
                return

            try:
                device = self._selected_device()
            except Exception as exc:
                wx.MessageBox(str(exc), _APP_NAME, wx.OK | wx.ICON_ERROR, self)
                return

            if self.source_choice.GetSelection() == 1:
                self._device_id_input = device.id
            else:
                self._device_id_output = device.id

            language = "en-US"
            lang_idx = self.language_choice.GetSelection()
            if lang_idx != wx.NOT_FOUND and lang_idx < len(self._language_codes):
                language = self._language_codes[lang_idx]

            endpoint_country = "US"
            country_idx = self.country_choice.GetSelection()
            if country_idx != wx.NOT_FOUND and country_idx < len(self._country_codes):
                endpoint_country = self._country_codes[country_idx]

            self._stop_event.clear()
            self._set_running(True)
            self.SetStatusText(t("status.starting"))

            self._persist_config()

            self._worker = threading.Thread(
                target=self._worker_main,
                args=(device, out_path, language, endpoint_country, self._advanced),
                daemon=True,
            )
            self._worker.start()

        def _on_stop(self, _event: wx.CommandEvent) -> None:
            self._stop_event.set()
            self.SetStatusText(t("status.stopping"))

        def _worker_main(
            self,
            device: _AudioDevice,
            out_path: Path,
            language: str,
            endpoint_country: str,
            advanced: _AdvancedSettings,
        ) -> None:
            writer = _HistoryWriter(out_path)
            shazam = Shazam(
                language=language,
                endpoint_country=endpoint_country,
                segment_duration_seconds=advanced.segment_seconds,
            )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            consecutive_recognition_errors = 0

            try:
                while not self._stop_event.is_set():
                    self._events.put(("status", t("status.listening")))
                    audio = _record_wav(
                        sc,
                        device.id,
                        include_loopback=(device.kind == "output"),
                        duration_s=advanced.sample_seconds,
                        sample_rate=16000,
                        channels=1,
                        chunk_size=1024,
                        stop_event=self._stop_event,
                    )
                    if self._stop_event.is_set():
                        break

                    window_starts, best_dbfs = _rank_window_starts_by_rms(
                        audio,
                        window_duration_s=advanced.segment_seconds,
                        window_step_s=advanced.window_step_seconds,
                        max_windows=advanced.max_windows_per_sample,
                    )
                    if best_dbfs < advanced.silence_dbfs_threshold:
                        consecutive_recognition_errors = 0
                        continue

                    raw: Any | None = None
                    recognition_exc: Exception | None = None
                    for idx, rel_start_s in enumerate(window_starts, start=1):
                        if self._stop_event.is_set():
                            break
                        window_audio = slice_wav_bytes(
                            audio,
                            start_s=int(rel_start_s),
                            duration_s=advanced.segment_seconds,
                        )
                        if window_audio is None:
                            continue

                        if len(window_starts) > 1:
                            self._events.put(
                                (
                                    "status",
                                    t(
                                        "status.recognizing_multi",
                                        current=idx,
                                        total=len(window_starts),
                                    ),
                                )
                            )
                        else:
                            self._events.put(("status", t("status.recognizing")))

                        try:
                            raw = loop.run_until_complete(shazam.recognize(window_audio))  # type: ignore[arg-type]
                        except Exception as exc:
                            recognition_exc = exc
                            raw = None
                            break

                        track = Serialize.full_track(raw)
                        if track.matches:
                            recognition_exc = None
                            break
                        raw = None

                    if recognition_exc is not None:
                        consecutive_recognition_errors += 1
                        text = str(recognition_exc).strip()
                        lowered = text.lower()
                        is_rate_limit = (
                            "429" in lowered
                            or "too many requests" in lowered
                            or "failed to decode json" in lowered
                        )

                        backoff_s = min(
                            300.0,
                            5.0 * (2.0 ** max(0, consecutive_recognition_errors - 1)),
                        )
                        if is_rate_limit:
                            backoff_s = max(backoff_s, 30.0)

                        detail = f": {text}" if text else ""
                        self._events.put(
                            (
                                "status",
                                t(
                                    "status.recognition_failed_backoff",
                                    seconds=int(backoff_s),
                                    detail=detail,
                                ),
                            )
                        )
                        self._stop_event.wait(backoff_s)
                        continue

                    if raw is None:
                        consecutive_recognition_errors = 0
                        continue

                    track = Serialize.full_track(raw)
                    if not track.matches:
                        consecutive_recognition_errors = 0
                        continue

                    consecutive_recognition_errors = 0
                    line = f"{track.track.subtitle} - {track.track.title}"
                    try:
                        if writer.append_unique(line):
                            self._events.put(("track", line))
                            self._events.put(("status", t("status.saved")))
                    except OSError as exc:
                        self._events.put(("error", t("error.write_file", error=str(exc))))
            except Exception as exc:
                self._events.put(("error", str(exc)))
            finally:
                self._events.put(("stopped", t("status.stopped")))

        def _on_timer(self, _event: wx.TimerEvent) -> None:
            while True:
                try:
                    kind, payload = self._events.get_nowait()
                except Empty:
                    break

                if kind == "status":
                    self.SetStatusText(payload)
                elif kind == "track":
                    self.log_list.Append(payload)
                elif kind == "error":
                    self.SetStatusText(t("status.error"))
                    wx.MessageBox(payload, _APP_NAME, wx.OK | wx.ICON_ERROR, self)
                    self._stop_event.set()
                elif kind == "stopped":
                    self.SetStatusText(payload)
                    self._set_running(False)

        def _on_close(self, event: wx.CloseEvent) -> None:
            self._timer.Stop()
            self._stop_event.set()
            if self._worker and self._worker.is_alive():
                self._worker.join(timeout=2.0)
            event.Skip()

    frame = MainFrame()
    frame.Show(True)
    app.MainLoop()


if __name__ == "__main__":
    main()
