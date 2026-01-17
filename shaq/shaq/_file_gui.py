from __future__ import annotations

import asyncio
import math
import os
import json
import threading
import time
import traceback
import uuid
import warnings
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait as wait_futures
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from queue import Empty, Queue
from tempfile import NamedTemporaryFile
from typing import Any
import wave

warnings.filterwarnings("ignore", category=DeprecationWarning, message=r".*audioop.*deprecated.*")
import audioop

from shaq._i18n import I18n, UI_LANGUAGE_CHOICES, ui_language_from_config
from shaq._file_scan import (
    FfmpegNotFoundError,
    extract_wav_segment,
    format_hms,
    probe_duration_seconds,
    slice_wav_bytes,
)
from shaq._shazam_regions import (
    SUPPORTED_ENDPOINT_COUNTRIES,
    SUPPORTED_LANGUAGES,
    country_choice_strings,
    country_codes,
    find_index_by_code,
    language_choice_strings,
    language_codes,
)

_APP_NAME = "shaqfilegui"
_CONFIG_VERSION = 1
_SHAZAM_SEGMENT_DURATION_S = int(os.environ.get("SHAQ_SHAZAM_SEGMENT_SECONDS", "12"))
_SHAZAM_SEGMENT_DURATION_S = max(5, min(60, _SHAZAM_SEGMENT_DURATION_S))

_SAMPLE_DURATION_S = int(os.environ.get("SHAQ_SAMPLE_SECONDS", "15"))
_SAMPLE_DURATION_S = max(_SHAZAM_SEGMENT_DURATION_S, min(60, _SAMPLE_DURATION_S))
_BASE_MIN_REQUEST_INTERVAL_S = float(os.environ.get("SHAQ_MIN_REQUEST_INTERVAL_S", "10.0"))
_BASE_MIN_REQUEST_INTERVAL_S = max(0.0, min(60.0, _BASE_MIN_REQUEST_INTERVAL_S))
_DEFAULT_WORKERS = max(1, min(4, (os.cpu_count() or 4)))
_RECOGNIZE_TIMEOUT_S = int(os.environ.get("SHAQ_RECOGNIZE_TIMEOUT_S", "60"))
_RECOGNIZE_TIMEOUT_S = max(10, min(600, _RECOGNIZE_TIMEOUT_S))
_MAX_WINDOWS_PER_SAMPLE = max(1, min(6, int(os.environ.get("SHAQ_MAX_WINDOWS_PER_SAMPLE", "3"))))
_WINDOW_STEP_S = max(1, int(os.environ.get("SHAQ_WINDOW_STEP_S", "1")))
_SILENCE_DBFS_THRESHOLD = float(os.environ.get("SHAQ_SILENCE_DBFS_THRESHOLD", "-55.0"))
_DEBUG_AUDIO = os.environ.get("SHAQ_DEBUG_AUDIO", "").strip() not in {"", "0", "false", "False"}

_SHAZAM_URL_LANGUAGE = os.environ.get("SHAQ_SHAZAM_URL_LANGUAGE", "en-US")
_SHAZAM_ENDPOINT_COUNTRY = os.environ.get("SHAQ_SHAZAM_ENDPOINT_COUNTRY", "US")
_SHAZAM_DEVICE = os.environ.get("SHAQ_SHAZAM_DEVICE", "android")
_SHAZAM_ACCEPT_LANGUAGE = os.environ.get("SHAQ_SHAZAM_ACCEPT_LANGUAGE", "pl-PL")
_SHAZAM_USER_AGENT = os.environ.get(
    "SHAQ_SHAZAM_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
)
_SHAZAM_PLATFORM = os.environ.get("SHAQ_SHAZAM_PLATFORM", "IPHONE")
_SHAZAM_APP_VERSION = os.environ.get("SHAQ_SHAZAM_APP_VERSION", "14.1.0")
_SHAZAM_TIME_ZONE = os.environ.get("SHAQ_SHAZAM_TIME_ZONE", "Europe/Warsaw")

_SUPPORTED_SUFFIXES = {
    ".aac",
    ".flac",
    ".latm",
    ".loas",
    ".mp2",
    ".mp3",
    ".mp4",
    ".m4a",
    ".ogg",
    ".opus",
    ".ts",
    ".wav",
}

_STRINGS: dict[str, dict[str, str]] = {
    "crash.unable_start": {"pl": "Nie mogę uruchomić aplikacji.", "en": "Unable to start the app."},
    "crash.details_saved": {
        "pl": "Szczegóły zapisano w:\n{path}",
        "en": "Details were saved to:\n{path}",
    },
    "crash.vc_redist": {
        "pl": "Jeśli to świeża maszyna, doinstaluj: Microsoft Visual C++ Redistributable 2015–2022 (x64).",
        "en": "If this is a fresh machine, install: Microsoft Visual C++ Redistributable 2015–2022 (x64).",
    },
    "error.load_shazamio": {
        "pl": "Nie mogę załadować shazamio: {error}",
        "en": "Unable to load shazamio: {error}",
    },
    "status.ready": {"pl": "Gotowe.", "en": "Ready."},
    "status.starting": {"pl": "Start...", "en": "Starting..."},
    "status.stopping": {"pl": "Zatrzymywanie...", "en": "Stopping..."},
    "status.stopped": {"pl": "Zatrzymano.", "en": "Stopped."},
    "status.done": {"pl": "Zakończono.", "en": "Done."},
    "status.error": {"pl": "Błąd.", "en": "Error."},
    "status.config_save_failed": {
        "pl": "Nie udało się zapisać config: {error}",
        "en": "Failed to save config: {error}",
    },
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
    "label.files_to_scan": {"pl": "Pliki do skanowania:", "en": "Files to scan:"},
    "name.files_to_scan": {"pl": "Pliki do skanowania", "en": "Files to scan"},
    "button.add_files": {"pl": "Dodaj pliki...", "en": "Add files..."},
    "tooltip.add_files": {"pl": "Dodaj jeden lub wiele plików audio.", "en": "Add one or more audio files."},
    "button.add_folder": {"pl": "Dodaj folder...", "en": "Add folder..."},
    "tooltip.add_folder": {
        "pl": "Dodaj wszystkie wspierane pliki z folderu.",
        "en": "Add all supported files from a folder.",
    },
    "button.remove_selected": {"pl": "Usuń zaznaczone", "en": "Remove selected"},
    "tooltip.remove_selected": {
        "pl": "Usuń zaznaczone pliki z listy.",
        "en": "Remove selected files from the list.",
    },
    "button.clear_list": {"pl": "Wyczyść listę", "en": "Clear list"},
    "tooltip.clear_list": {"pl": "Usuń wszystkie pliki z listy.", "en": "Remove all files from the list."},
    "label.remember_file_list": {
        "pl": "Pamiętaj listę plików między sesjami",
        "en": "Remember file list between sessions",
    },
    "name.remember_file_list": {
        "pl": "Pamiętaj listę plików",
        "en": "Remember file list",
    },
    "tooltip.remember_file_list": {
        "pl": "Jeżeli zaznaczone, lista plików zostanie przywrócona przy następnym uruchomieniu.",
        "en": "If checked, the file list will be restored on next startup.",
    },
    "label.output_folder_optional": {
        "pl": "Folder zapisu (opcjonalnie):",
        "en": "Output folder (optional):",
    },
    "name.output_folder": {"pl": "Folder zapisu", "en": "Output folder"},
    "button.browse": {"pl": "Wybierz...", "en": "Browse..."},
    "tooltip.output_folder_browse": {
        "pl": "Wybierz folder, w którym powstanie plik .txt; jeśli puste, zapis obok źródła.",
        "en": "Choose the folder where the .txt file will be created; if empty, it is written next to the source.",
    },
    "label.interval_seconds": {"pl": "Próbka co (sek):", "en": "Sample every (sec):"},
    "name.interval_seconds": {"pl": "Próbka co (sekundy)", "en": "Sample every (seconds)"},
    "label.shazam_language": {"pl": "Język Shazam:", "en": "Shazam language:"},
    "name.shazam_language": {"pl": "Język Shazam", "en": "Shazam language"},
    "tooltip.shazam_language": {
        "pl": "Język (locale) używany przez Shazam API.",
        "en": "Language (locale) used by the Shazam API.",
    },
    "label.shazam_country": {"pl": "Kraj Shazam:", "en": "Shazam country:"},
    "name.shazam_country": {"pl": "Kraj Shazam", "en": "Shazam country"},
    "tooltip.shazam_country": {
        "pl": "Kraj (endpoint_country) używany przez Shazam API.",
        "en": "Country (endpoint_country) used by the Shazam API.",
    },
    "name.progress": {"pl": "Postęp", "en": "Progress"},
    "label.progress_initial": {"pl": "Postęp: 0%", "en": "Progress: 0%"},
    "name.progress_text": {"pl": "Postęp (tekst)", "en": "Progress (text)"},
    "name.scan_results": {"pl": "Wyniki skanowania", "en": "Scan results"},
    "button.scan": {"pl": "Skanuj", "en": "Scan"},
    "tooltip.scan": {"pl": "Rozpocznij skanowanie wybranych plików.", "en": "Start scanning the selected files."},
    "button.stop": {"pl": "Stop", "en": "Stop"},
    "tooltip.stop": {"pl": "Zatrzymaj skanowanie.", "en": "Stop scanning."},
    "button.advanced": {"pl": "Ustawienia zaawansowane…", "en": "Advanced settings..."},
    "tooltip.advanced": {
        "pl": "Parametry wpływające na dokładność/limity API.",
        "en": "Parameters affecting accuracy / API limits.",
    },
    "label.results": {"pl": "Wyniki:", "en": "Results:"},
    "status.files_selected": {"pl": "Wybrano plików: {count}", "en": "Files selected: {count}"},
    "file_dialog.add_files": {"pl": "Dodaj pliki audio", "en": "Add audio files"},
    "file_dialog.all_files": {"pl": "Wszystkie pliki (*.*)|*.*", "en": "All files (*.*)|*.*"},
    "file_dialog.add_folder": {"pl": "Dodaj folder z plikami audio", "en": "Add folder with audio files"},
    "file_dialog.output_folder": {"pl": "Wybierz folder zapisu", "en": "Select output folder"},
    "prompt.include_subfolders": {
        "pl": "Dodać też pliki z podfolderów?",
        "en": "Also add files from subfolders?",
    },
    "info.no_supported_files": {
        "pl": "Nie znaleziono żadnych wspieranych plików w tym folderze.",
        "en": "No supported files found in this folder.",
    },
    "warn.skipped_unsupported_ext": {
        "pl": "Pominięto {count} plików o niewspieranych rozszerzeniach.",
        "en": "Skipped {count} files with unsupported extensions.",
    },
    "dialog.advanced.title": {"pl": "Ustawienia zaawansowane", "en": "Advanced settings"},
    "dialog.advanced.group_recognition": {"pl": "Rozpoznawanie", "en": "Recognition"},
    "dialog.advanced.group_http": {"pl": "HTTP / Shazam", "en": "HTTP / Shazam"},
    "adv.sample_seconds": {"pl": "Długość próbki (sek):", "en": "Sample length (sec):"},
    "name.sample_seconds": {"pl": "Długość próbki (sekundy)", "en": "Sample length (seconds)"},
    "adv.signature_seconds": {"pl": "Długość podpisu (sek):", "en": "Signature length (sec):"},
    "name.signature_seconds": {"pl": "Długość podpisu (sekundy)", "en": "Signature length (seconds)"},
    "adv.workers": {"pl": "Wątki:", "en": "Threads:"},
    "name.workers": {"pl": "Wątki", "en": "Threads"},
    "adv.min_api_interval": {"pl": "Min odstęp API (sek):", "en": "Min API interval (sec):"},
    "name.min_api_interval": {"pl": "Min odstęp API (sekundy)", "en": "Min API interval (seconds)"},
    "adv.recognize_timeout": {"pl": "Timeout rozpoznawania (sek):", "en": "Recognition timeout (sec):"},
    "name.recognize_timeout": {"pl": "Timeout rozpoznawania (sekundy)", "en": "Recognition timeout (seconds)"},
    "adv.max_windows": {"pl": "Okna w próbce (max):", "en": "Windows per sample (max):"},
    "name.max_windows": {"pl": "Okna w próbce", "en": "Windows per sample"},
    "adv.window_step": {"pl": "Krok okna (sek):", "en": "Window step (sec):"},
    "name.window_step": {"pl": "Krok okna (sekundy)", "en": "Window step (seconds)"},
    "adv.silence_dbfs": {"pl": "Próg ciszy (dBFS):", "en": "Silence threshold (dBFS):"},
    "name.silence_dbfs": {"pl": "Próg ciszy (dBFS)", "en": "Silence threshold (dBFS)"},
    "adv.debug_audio": {
        "pl": "Debug audio (loguj parametry/RMS)",
        "en": "Debug audio (log parameters/RMS)",
    },
    "name.debug_audio": {"pl": "Debug audio", "en": "Debug audio"},
    "adv.accept_language": {
        "pl": "Accept-Language (nagłówek):",
        "en": "Accept-Language (header):",
    },
    "tooltip.accept_language": {
        "pl": "Jeśli puste, używany będzie wybrany język Shazam.",
        "en": "If empty, the selected Shazam language will be used.",
    },
    "adv.error.sig_gt_sample": {
        "pl": "Długość podpisu nie może być większa niż długość próbki.",
        "en": "Signature length can't be greater than sample length.",
    },
    "adv.error.invalid_silence": {
        "pl": "Nieprawidłowy próg ciszy (dBFS).",
        "en": "Invalid silence threshold (dBFS).",
    },
    "error.add_file_first": {
        "pl": "Dodaj przynajmniej jeden plik do skanowania.",
        "en": "Add at least one file to scan.",
    },
    "error.interval_positive": {
        "pl": "Interwał próbkowania musi być dodatni.",
        "en": "Sampling interval must be positive.",
    },
    "error.no_existing_files": {
        "pl": "Lista nie zawiera żadnych istniejących plików.",
        "en": "The list doesn't contain any existing files.",
    },
    "prompt.unknown_ext": {
        "pl": "Niektóre pliki mają nietypowe rozszerzenia ({preview}). Spróbować mimo to?",
        "en": "Some files have unusual extensions ({preview}). Try anyway?",
    },
    "error.create_folder": {"pl": "Nie mogę utworzyć folderu: {error}", "en": "Can't create folder: {error}"},
    "prompt.overwrite_outputs": {
        "pl": "Istnieje {count} plików wynikowych. Nadpisać wszystkie?",
        "en": "{count} output files already exist. Overwrite all?",
    },
    "error.ffmpeg_missing": {
        "pl": "Brak ffmpeg (wbudowanego lub na $PATH). W wersji źródłowej doinstaluj ffmpeg (razem z ffprobe) albo uruchom gotowy plik .exe z wbudowanym ffmpeg.",
        "en": "ffmpeg is missing (bundled or on $PATH). In the source version, install ffmpeg (with ffprobe) or run the packaged .exe that bundles ffmpeg.",
    },
    "status.scanning_file": {
        "pl": "[{file_index}/{file_total}] Skanuję: {filename}",
        "en": "[{file_index}/{file_total}] Scanning: {filename}",
    },
    "status.api_limit_pause": {"pl": "Limit API: pauza {seconds}s...", "en": "API limit: pause {seconds}s..."},
    "warn.http_429_pause": {
        "pl": "{timestamp}\tHTTP 429{chain} (limit). Pauza {seconds}s...{extra}",
        "en": "{timestamp}\tHTTP 429{chain} (limit). Pause {seconds}s...{extra}",
    },
    "warn.http_retry": {"pl": "{timestamp}\tHTTP retry{chain}", "en": "{timestamp}\tHTTP retry{chain}"},
    "warn.silence_skip": {
        "pl": "{timestamp}\tCisza (RMS {dbfs:.1f} dBFS) — pomijam.",
        "en": "{timestamp}\tSilence (RMS {dbfs:.1f} dBFS) — skipping.",
    },
    "status.sample": {"pl": "Próbka {timestamp}...", "en": "Sample {timestamp}..."},
    "error.recognize_failed": {"pl": "rozpoznawanie nieudane", "en": "recognize failed"},
    "info.file_stopped": {
        "pl": "[{file_index}/{file_total}] Zatrzymano. Wynik: {output_file}",
        "en": "[{file_index}/{file_total}] Stopped. Output: {output_file}",
    },
    "info.file_done": {
        "pl": "[{file_index}/{file_total}] Zakończono. Wynik: {output_file}",
        "en": "[{file_index}/{file_total}] Done. Output: {output_file}",
    },
    "log.warn_prefix": {"pl": "UWAGA: ", "en": "WARNING: "},
    "progress.stats": {
        "pl": ", rozpozn.: {matches}, brak: {nomatch}, błędy: {errors}",
        "en": ", matches: {matches}, no match: {nomatch}, errors: {errors}",
    },
    "progress.stats_rate_limits": {"pl": ", limity: {rate_limits}", "en": ", rate limits: {rate_limits}"},
    "progress.initial_known_total": {
        "pl": "{file_prefix}Postęp: 0% (0/{total}), czas: 00:00:00 / {duration}, wątki: {workers}",
        "en": "{file_prefix}Progress: 0% (0/{total}), time: 00:00:00 / {duration}, threads: {workers}",
    },
    "progress.initial_unknown_total": {
        "pl": "{file_prefix}Postęp: ... , wątki: {workers}",
        "en": "{file_prefix}Progress: ... , threads: {workers}",
    },
    "progress.update_with_eta": {
        "pl": "{file_prefix}Postęp: {percent}% ({done}/{total}), czas: {elapsed}, ETA: {eta}, pozycja: {offset} / {duration}{stats}",
        "en": "{file_prefix}Progress: {percent}% ({done}/{total}), time: {elapsed}, ETA: {eta}, position: {offset} / {duration}{stats}",
    },
    "progress.update_no_eta": {
        "pl": "{file_prefix}Postęp: {percent}% ({done}/{total}), pozycja: {offset} / {duration}{stats}",
        "en": "{file_prefix}Progress: {percent}% ({done}/{total}), position: {offset} / {duration}{stats}",
    },
    "progress.update_unknown_total_done": {
        "pl": "{file_prefix}Postęp: {done} próbek (bez czasu całkowitego){stats}",
        "en": "{file_prefix}Progress: {done} samples (unknown total){stats}",
    },
    "progress.update_unknown_total": {"pl": "{file_prefix}Postęp: ...", "en": "{file_prefix}Progress: ..."},
    "progress.done": {
        "pl": "{file_prefix}Postęp: 100% ({total}/{total}), czas: {elapsed} / {duration}, rozpozn.: {matches}, brak: {nomatch}, błędy: {errors}",
        "en": "{file_prefix}Progress: 100% ({total}/{total}), time: {elapsed} / {duration}, matches: {matches}, no match: {nomatch}, errors: {errors}",
    },
    "progress.stopped": {"pl": "{file_prefix}Zatrzymano.", "en": "{file_prefix}Stopped."},
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


def _clamp_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        return minimum
    return max(minimum, min(maximum, number))


def _clamp_float(value: Any, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except Exception:
        return minimum
    return max(minimum, min(maximum, number))


@dataclass
class _AdvancedSettings:
    sample_duration_s: int = int(_SAMPLE_DURATION_S)
    sig_duration_s: int = int(_SHAZAM_SEGMENT_DURATION_S)
    workers: int = int(_DEFAULT_WORKERS)
    min_api_interval_s: int = int(round(_BASE_MIN_REQUEST_INTERVAL_S))
    recognize_timeout_s: int = int(_RECOGNIZE_TIMEOUT_S)
    max_windows_per_sample: int = int(_MAX_WINDOWS_PER_SAMPLE)
    window_step_s: int = int(_WINDOW_STEP_S)
    silence_dbfs_threshold: float = float(_SILENCE_DBFS_THRESHOLD)
    debug_audio: bool = bool(_DEBUG_AUDIO)

    shazam_device: str = str(_SHAZAM_DEVICE)
    shazam_accept_language: str = str(_SHAZAM_ACCEPT_LANGUAGE)
    shazam_user_agent: str = str(_SHAZAM_USER_AGENT)
    shazam_platform: str = str(_SHAZAM_PLATFORM)
    shazam_app_version: str = str(_SHAZAM_APP_VERSION)
    shazam_time_zone: str = str(_SHAZAM_TIME_ZONE)


def _win_error_dialog(message: str) -> None:
    if os.name != "nt":
        return

    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return
        windll.user32.MessageBoxW(0, message, _APP_NAME, 0x10)
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
        from shazamio import Serialize, Shazam
    except Exception as exc:
        raise RuntimeError(f"Nie mogę załadować shazamio: {exc}") from exc

    from aiohttp_retry import ExponentialRetry
    from shazamio.client import HTTPClient
    from shazamio.converter import Converter
    from shazamio.misc import ShazamUrl

    class _InstrumentedHTTPClient(HTTPClient):
        def __init__(self) -> None:
            super().__init__(
                retry_options=ExponentialRetry(
                    attempts=4,
                    start_timeout=1.0,
                    max_timeout=30.0,
                    statuses={500, 502, 503, 504},
                )
            )
            self.last_status: int | None = None
            self.last_url: str | None = None
            self.last_headers: dict[str, str] = {}
            self.attempts: list[tuple[int, int]] = []

            self.trace_config.on_request_end.append(self.on_request_end)
            self.trace_config.on_request_exception.append(self.on_request_exception)

        def reset(self) -> None:
            self.last_status = None
            self.last_url = None
            self.last_headers = {}
            self.attempts = []

        async def request(self, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
            self.reset()
            return await super().request(method, url, *args, **kwargs)

        async def on_request_end(self, _session: Any, trace_config_ctx: Any, params: Any) -> None:
            attempt = trace_config_ctx.trace_request_ctx.get("current_attempt", 0)
            status = params.response.status

            try:
                attempt_n = int(attempt)
            except Exception:
                attempt_n = 0

            self.attempts.append((attempt_n, int(status)))
            self.last_status = int(status)
            self.last_url = str(params.url)
            self.last_headers = {k: v for k, v in params.response.headers.items()}

        async def on_request_exception(
            self, _session: Any, _trace_config_ctx: Any, _params: Any
        ) -> None:
            return

    class _PinnedShazam(Shazam):
        def __init__(
            self,
            *,
            language: str,
            endpoint_country: str,
            device: str,
            platform: str,
            app_version: str,
            user_agent: str,
            time_zone: str,
            accept_language: str,
            segment_duration_seconds: int,
        ) -> None:
            self._device = device
            self._platform = platform
            self._app_version = app_version
            self._user_agent = user_agent
            self._time_zone = time_zone
            self._accept_language = accept_language
            super().__init__(
                language=language,
                endpoint_country=endpoint_country,
                http_client=_InstrumentedHTTPClient(),
                segment_duration_seconds=segment_duration_seconds,
            )

        def headers(self) -> dict[str, str]:
            return {
                "X-Shazam-Platform": self._platform,
                "X-Shazam-AppVersion": self._app_version,
                "Accept": "*/*",
                "Accept-Language": self._accept_language,
                "Accept-Encoding": "gzip, deflate",
                "Content-Type": "application/json",
                "User-Agent": self._user_agent,
            }

        async def send_recognize_request_v2(
            self,
            sig: Any,
            proxy: str | None = None,
        ) -> dict[str, Any]:
            data = Converter.data_search(
                self._time_zone,
                sig.signature.uri,
                sig.signature.samples,
                sig.timestamp,
            )
            return await self.http_client.request(
                "POST",
                ShazamUrl.SEARCH_FROM_FILE.format(
                    language=self.language,
                    device=self._device,
                    endpoint_country=self.endpoint_country,
                    uuid_1=str(uuid.uuid4()).upper(),
                    uuid_2=str(uuid.uuid4()).upper(),
                ),
                headers=self.headers(),
                proxy=proxy,
                json=data,
            )

    app = wx.App(False)
    config = _load_config()
    ui_language = ui_language_from_config(config.get("ui_language"))
    i18n = I18n(ui_language, _STRINGS)
    t = i18n.t

    class MainFrame(wx.Frame):
        def __init__(self) -> None:
            super().__init__(None, title=_APP_NAME)
            self.SetMinClientSize((760, 520))

            panel = wx.Panel(self)
            self.CreateStatusBar()
            self.SetStatusText(t("status.ready"))

            self._events: Queue[tuple[str, Any]] = Queue()
            self._stop_event = threading.Event()
            self._worker: threading.Thread | None = None
            self._scan_duration_s: int | None = None
            self._scan_total_samples: int | None = None
            self._scan_elapsed_s: int = 0
            self._scan_matches: int = 0
            self._scan_nomatch: int = 0
            self._scan_errors: int = 0
            self._scan_rate_limits: int = 0
            self._scan_file_index: int | None = None
            self._scan_file_total: int | None = None
            self._scan_file_name: str | None = None

            self._input_paths: list[Path] = []
            self._remember_file_list: bool = bool(config.get("remember_file_list", True))

            adv_cfg = config.get("advanced") if isinstance(config.get("advanced"), dict) else {}
            defaults = _AdvancedSettings()
            sample_duration_s = _clamp_int(
                adv_cfg.get("sample_duration_s", defaults.sample_duration_s),
                minimum=5,
                maximum=60,
            )
            sig_duration_s = _clamp_int(
                adv_cfg.get("sig_duration_s", defaults.sig_duration_s), minimum=5, maximum=60
            )
            sample_duration_s = max(sample_duration_s, sig_duration_s)
            self._advanced = _AdvancedSettings(
                sample_duration_s=sample_duration_s,
                sig_duration_s=min(sig_duration_s, sample_duration_s),
                workers=_clamp_int(adv_cfg.get("workers", defaults.workers), minimum=1, maximum=32),
                min_api_interval_s=_clamp_int(
                    adv_cfg.get("min_api_interval_s", defaults.min_api_interval_s),
                    minimum=0,
                    maximum=60,
                ),
                recognize_timeout_s=_clamp_int(
                    adv_cfg.get("recognize_timeout_s", defaults.recognize_timeout_s),
                    minimum=10,
                    maximum=600,
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
                debug_audio=bool(adv_cfg.get("debug_audio", defaults.debug_audio)),
                shazam_device=str(adv_cfg.get("shazam_device", defaults.shazam_device) or "").strip()
                or defaults.shazam_device,
                shazam_accept_language=str(
                    adv_cfg.get("shazam_accept_language", defaults.shazam_accept_language) or ""
                ).strip(),
                shazam_user_agent=str(
                    adv_cfg.get("shazam_user_agent", defaults.shazam_user_agent) or ""
                ).strip()
                or defaults.shazam_user_agent,
                shazam_platform=str(adv_cfg.get("shazam_platform", defaults.shazam_platform) or "").strip()
                or defaults.shazam_platform,
                shazam_app_version=str(
                    adv_cfg.get("shazam_app_version", defaults.shazam_app_version) or ""
                ).strip()
                or defaults.shazam_app_version,
                shazam_time_zone=str(
                    adv_cfg.get("shazam_time_zone", defaults.shazam_time_zone) or ""
                ).strip()
                or defaults.shazam_time_zone,
            )

            self._ui_language_codes = [code for code, _label in UI_LANGUAGE_CHOICES]
            ui_lang_label = wx.StaticText(panel, label=t("label.ui_language"))
            self.ui_language_choice = wx.Choice(
                panel, choices=[label for _code, label in UI_LANGUAGE_CHOICES]
            )
            self.ui_language_choice.SetName(t("name.ui_language"))
            self.ui_language_choice.SetToolTip(t("tooltip.ui_language"))
            self.ui_language_choice.SetSelection(0 if ui_language == "pl" else 1)
            self.ui_language_choice.Bind(wx.EVT_CHOICE, self._on_ui_language_changed)

            files_label = wx.StaticText(panel, label=t("label.files_to_scan"))
            self.files_list = wx.ListBox(panel, style=wx.LB_EXTENDED)
            self.files_list.SetName(t("name.files_to_scan"))

            self.add_files_btn = wx.Button(panel, label=t("button.add_files"))
            self.add_files_btn.SetToolTip(t("tooltip.add_files"))
            self.add_files_btn.Bind(wx.EVT_BUTTON, self._on_add_files)

            self.add_folder_btn = wx.Button(panel, label=t("button.add_folder"))
            self.add_folder_btn.SetToolTip(t("tooltip.add_folder"))
            self.add_folder_btn.Bind(wx.EVT_BUTTON, self._on_add_folder)

            self.remove_files_btn = wx.Button(panel, label=t("button.remove_selected"))
            self.remove_files_btn.SetToolTip(t("tooltip.remove_selected"))
            self.remove_files_btn.Bind(wx.EVT_BUTTON, self._on_remove_files)

            self.clear_files_btn = wx.Button(panel, label=t("button.clear_list"))
            self.clear_files_btn.SetToolTip(t("tooltip.clear_list"))
            self.clear_files_btn.Bind(wx.EVT_BUTTON, self._on_clear_files)

            self.remember_files_cb = wx.CheckBox(panel, label=t("label.remember_file_list"))
            self.remember_files_cb.SetName(t("name.remember_file_list"))
            self.remember_files_cb.SetToolTip(t("tooltip.remember_file_list"))
            self.remember_files_cb.SetValue(self._remember_file_list)
            self.remember_files_cb.Bind(wx.EVT_CHECKBOX, self._on_remember_files_changed)

            out_dir_label = wx.StaticText(panel, label=t("label.output_folder_optional"))
            self.out_dir = wx.TextCtrl(panel, value=str(config.get("output_dir") or ""))
            self.out_dir.SetName(t("name.output_folder"))
            self.out_dir_browse_btn = wx.Button(panel, label=t("button.browse"))
            self.out_dir_browse_btn.SetToolTip(t("tooltip.output_folder_browse"))
            self.out_dir_browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_output_dir)

            interval_label = wx.StaticText(panel, label=t("label.interval_seconds"))
            self.interval = wx.SpinCtrl(
                panel,
                min=1,
                max=24 * 60 * 60,
                initial=_clamp_int(config.get("interval_s", 30), minimum=1, maximum=24 * 60 * 60),
            )
            self.interval.SetName(t("name.interval_seconds"))

            language_label = wx.StaticText(panel, label=t("label.shazam_language"))
            self._language_codes = language_codes()
            self.language_choice = wx.Choice(panel, choices=language_choice_strings())
            self.language_choice.SetName(t("name.shazam_language"))
            self.language_choice.SetToolTip(t("tooltip.shazam_language"))
            cfg_language = str(config.get("language") or "").strip() or _SHAZAM_URL_LANGUAGE
            lang_idx = find_index_by_code(SUPPORTED_LANGUAGES, cfg_language)
            self.language_choice.SetSelection(lang_idx if lang_idx is not None else 0)

            country_label = wx.StaticText(panel, label=t("label.shazam_country"))
            self._country_codes = country_codes()
            self.country_choice = wx.Choice(panel, choices=country_choice_strings())
            self.country_choice.SetName(t("name.shazam_country"))
            self.country_choice.SetToolTip(t("tooltip.shazam_country"))
            cfg_country = str(config.get("endpoint_country") or "").strip() or _SHAZAM_ENDPOINT_COUNTRY
            country_idx = find_index_by_code(SUPPORTED_ENDPOINT_COUNTRIES, cfg_country)
            self.country_choice.SetSelection(country_idx if country_idx is not None else 0)

            self.progress = wx.Gauge(panel, range=100)
            self.progress.SetName(t("name.progress"))
            self.progress.SetValue(0)
            self.progress_text = wx.StaticText(panel, label=t("label.progress_initial"))
            self.progress_text.SetName(t("name.progress_text"))

            self.log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.log.SetName(t("name.scan_results"))

            self.scan_btn = wx.Button(panel, label=t("button.scan"))
            self.scan_btn.SetToolTip(t("tooltip.scan"))
            self.scan_btn.Bind(wx.EVT_BUTTON, self._on_scan)
            self.stop_btn = wx.Button(panel, label=t("button.stop"))
            self.stop_btn.SetToolTip(t("tooltip.stop"))
            self.stop_btn.Bind(wx.EVT_BUTTON, self._on_stop)
            self.stop_btn.Disable()

            self.advanced_btn = wx.Button(panel, label=t("button.advanced"))
            self.advanced_btn.SetToolTip(t("tooltip.advanced"))
            self.advanced_btn.Bind(wx.EVT_BUTTON, self._on_advanced)

            file_buttons = wx.BoxSizer(wx.HORIZONTAL)
            file_buttons.Add(self.add_files_btn, 0, wx.RIGHT, 8)
            file_buttons.Add(self.add_folder_btn, 0, wx.RIGHT, 8)
            file_buttons.Add(self.remove_files_btn, 0, wx.RIGHT, 8)
            file_buttons.Add(self.clear_files_btn, 0)

            opts = wx.FlexGridSizer(rows=5, cols=3, vgap=8, hgap=8)
            opts.AddGrowableCol(1, 1)
            opts.Add(ui_lang_label, 0, wx.ALIGN_CENTER_VERTICAL)
            opts.Add(self.ui_language_choice, 0)
            opts.Add((1, 1))
            opts.Add(out_dir_label, 0, wx.ALIGN_CENTER_VERTICAL)
            opts.Add(self.out_dir, 1, wx.EXPAND)
            opts.Add(self.out_dir_browse_btn, 0)
            opts.Add(interval_label, 0, wx.ALIGN_CENTER_VERTICAL)
            opts.Add(self.interval, 0)
            opts.Add((1, 1))
            opts.Add(language_label, 0, wx.ALIGN_CENTER_VERTICAL)
            opts.Add(self.language_choice, 0)
            opts.Add((1, 1))
            opts.Add(country_label, 0, wx.ALIGN_CENTER_VERTICAL)
            opts.Add(self.country_choice, 0)
            opts.Add((1, 1))

            buttons = wx.BoxSizer(wx.HORIZONTAL)
            buttons.AddStretchSpacer(1)
            buttons.Add(self.advanced_btn, 0, wx.RIGHT, 8)
            buttons.Add(self.scan_btn, 0, wx.RIGHT, 8)
            buttons.Add(self.stop_btn, 0)

            progress_row = wx.BoxSizer(wx.HORIZONTAL)
            progress_row.Add(self.progress, 1, wx.EXPAND)
            progress_row.Add(self.progress_text, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 10)

            root = wx.BoxSizer(wx.VERTICAL)
            root.Add(files_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
            root.Add(self.files_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
            root.Add(file_buttons, 0, wx.EXPAND | wx.ALL, 12)
            root.Add(self.remember_files_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            root.Add(opts, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
            root.Add(progress_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            root.Add(wx.StaticText(panel, label=t("label.results")), 0, wx.LEFT | wx.RIGHT, 12)
            root.Add(self.log, 1, wx.EXPAND | wx.ALL, 12)
            root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            panel.SetSizer(root)

            self._load_input_paths_from_config()

            self._timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
            self._timer.Start(150)

            self.Bind(wx.EVT_CLOSE, self._on_close)

        def _set_running(self, running: bool) -> None:
            self.scan_btn.Enable(not running)
            self.stop_btn.Enable(running)
            self.files_list.Enable(not running)
            self.add_files_btn.Enable(not running)
            self.add_folder_btn.Enable(not running)
            self.remove_files_btn.Enable(not running)
            self.clear_files_btn.Enable(not running)
            self.ui_language_choice.Enable(not running)
            self.out_dir.Enable(not running)
            self.out_dir_browse_btn.Enable(not running)
            self.interval.Enable(not running)
            self.language_choice.Enable(not running)
            self.country_choice.Enable(not running)
            self.advanced_btn.Enable(not running)
            self.remember_files_cb.Enable(not running)

        def _collect_config(self) -> dict[str, Any]:
            ui_language_value = ui_language
            ui_idx = self.ui_language_choice.GetSelection()
            if ui_idx != wx.NOT_FOUND and ui_idx < len(self._ui_language_codes):
                ui_language_value = self._ui_language_codes[ui_idx]

            language = _SHAZAM_URL_LANGUAGE
            lang_idx = self.language_choice.GetSelection()
            if lang_idx != wx.NOT_FOUND and lang_idx < len(self._language_codes):
                language = self._language_codes[lang_idx]

            endpoint_country = _SHAZAM_ENDPOINT_COUNTRY
            country_idx = self.country_choice.GetSelection()
            if country_idx != wx.NOT_FOUND and country_idx < len(self._country_codes):
                endpoint_country = self._country_codes[country_idx]

            return {
                "version": _CONFIG_VERSION,
                "ui_language": ui_language_value,
                "input_paths": [str(p) for p in self._input_paths[:200]] if self._remember_file_list else [],
                "remember_file_list": self._remember_file_list,
                "output_dir": self.out_dir.GetValue(),
                "interval_s": int(self.interval.GetValue()),
                "language": language,
                "endpoint_country": endpoint_country,
                "advanced": {
                    "sample_duration_s": int(self._advanced.sample_duration_s),
                    "sig_duration_s": int(self._advanced.sig_duration_s),
                    "workers": int(self._advanced.workers),
                    "min_api_interval_s": int(self._advanced.min_api_interval_s),
                    "recognize_timeout_s": int(self._advanced.recognize_timeout_s),
                    "max_windows_per_sample": int(self._advanced.max_windows_per_sample),
                    "window_step_s": int(self._advanced.window_step_s),
                    "silence_dbfs_threshold": float(self._advanced.silence_dbfs_threshold),
                    "debug_audio": bool(self._advanced.debug_audio),
                    "shazam_device": self._advanced.shazam_device,
                    "shazam_accept_language": self._advanced.shazam_accept_language,
                    "shazam_user_agent": self._advanced.shazam_user_agent,
                    "shazam_platform": self._advanced.shazam_platform,
                    "shazam_app_version": self._advanced.shazam_app_version,
                    "shazam_time_zone": self._advanced.shazam_time_zone,
                },
            }

        def _persist_config(self) -> None:
            try:
                _save_config(self._collect_config())
            except Exception as exc:
                self.SetStatusText(t("status.config_save_failed", error=str(exc)))

        def _load_input_paths_from_config(self) -> None:
            if not self._remember_file_list:
                return
            raw_list = config.get("input_paths")
            if not isinstance(raw_list, list):
                return
            for item in raw_list[:200]:
                try:
                    path = Path(str(item)).expanduser()
                except Exception:
                    continue
                if path.exists() and path.is_file():
                    self._add_input_path(path)

        def _add_input_path(self, path: Path) -> None:
            path = path.expanduser()
            key = str(path)
            if any(str(existing) == key for existing in self._input_paths):
                return
            self._input_paths.append(path)
            self.files_list.Append(str(path))
            self.SetStatusText(t("status.files_selected", count=len(self._input_paths)))

        def _on_ui_language_changed(self, _event: wx.CommandEvent) -> None:
            self._persist_config()
            wx.MessageBox(t("info.restart_required"), _APP_NAME, wx.OK | wx.ICON_INFORMATION, self)

        def _on_remember_files_changed(self, _event: wx.CommandEvent) -> None:
            self._remember_file_list = self.remember_files_cb.GetValue()
            self._persist_config()

        def _on_add_files(self, _event: wx.CommandEvent) -> None:
            wildcard = (
                "Audio/video (*.mp3;*.mp2;*.aac;*.flac;*.wav;*.ogg;*.opus;"
                "*.mp4;*.m4a;*.ts;*.loas;*.latm)|"
                "*.mp3;*.mp2;*.aac;*.flac;*.wav;*.ogg;*.opus;"
                "*.mp4;*.m4a;*.ts;*.loas;*.latm|"
                + t("file_dialog.all_files")
            )

            start_dir = ""
            if self._input_paths:
                start_dir = str(self._input_paths[-1].parent)

            with wx.FileDialog(
                self,
                message=t("file_dialog.add_files"),
                defaultDir=start_dir,
                wildcard=wildcard,
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
            ) as dialog:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return

                paths = [Path(p).expanduser() for p in dialog.GetPaths()]
                added = 0
                for path in paths:
                    if path.exists() and path.is_file():
                        self._add_input_path(path)
                        added += 1
                if added:
                    self._persist_config()

        def _on_add_folder(self, _event: wx.CommandEvent) -> None:
            start_dir = ""
            if self._input_paths:
                start_dir = str(self._input_paths[-1].parent)

            with wx.DirDialog(
                self, message=t("file_dialog.add_folder"), defaultPath=start_dir
            ) as dialog:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return
                folder = Path(dialog.GetPath()).expanduser()

            include_sub = wx.MessageBox(
                t("prompt.include_subfolders"),
                _APP_NAME,
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            recursive = include_sub == wx.YES

            candidates = folder.rglob("*") if recursive else folder.glob("*")
            added = 0
            skipped = 0
            for path in sorted(candidates):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                    skipped += 1
                    continue
                self._add_input_path(path)
                added += 1

            if not added:
                wx.MessageBox(
                    t("info.no_supported_files"),
                    _APP_NAME,
                    wx.OK | wx.ICON_INFORMATION,
                    self,
                )
                return

            if skipped:
                self.log.AppendText(
                    f"{t('log.warn_prefix')}{t('warn.skipped_unsupported_ext', count=skipped)}\n"
                )
            self._persist_config()

        def _on_remove_files(self, _event: wx.CommandEvent) -> None:
            selections = list(self.files_list.GetSelections())
            if not selections:
                return
            for idx in sorted(selections, reverse=True):
                if 0 <= idx < len(self._input_paths):
                    self._input_paths.pop(idx)
                self.files_list.Delete(idx)
            self.SetStatusText(t("status.files_selected", count=len(self._input_paths)))
            self._persist_config()

        def _on_clear_files(self, _event: wx.CommandEvent) -> None:
            self._input_paths.clear()
            self.files_list.Clear()
            self.SetStatusText(t("status.ready"))
            self._persist_config()

        def _on_browse_output_dir(self, _event: wx.CommandEvent) -> None:
            start_dir = ""
            if value := self.out_dir.GetValue().strip():
                start_dir = str(Path(value).expanduser())

            with wx.DirDialog(
                self, message=t("file_dialog.output_folder"), defaultPath=start_dir
            ) as dialog:
                if dialog.ShowModal() == wx.ID_CANCEL:
                    return
                self.out_dir.SetValue(dialog.GetPath())
                self._persist_config()

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
            dialog.SetMinClientSize((740, 600))
            panel = wx.Panel(dialog)

            recog_box = wx.StaticBoxSizer(
                wx.StaticBox(panel, label=t("dialog.advanced.group_recognition")),
                wx.VERTICAL,
            )
            recog_grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
            recog_grid.AddGrowableCol(1, 1)

            sample_label = wx.StaticText(panel, label=t("adv.sample_seconds"))
            sample = wx.SpinCtrl(
                panel, min=5, max=60, initial=int(self._advanced.sample_duration_s)
            )
            sample.SetName(t("name.sample_seconds"))

            sig_label = wx.StaticText(panel, label=t("adv.signature_seconds"))
            sig = wx.SpinCtrl(panel, min=5, max=60, initial=int(self._advanced.sig_duration_s))
            sig.SetName(t("name.signature_seconds"))

            workers_label = wx.StaticText(panel, label=t("adv.workers"))
            workers = wx.SpinCtrl(panel, min=1, max=32, initial=int(self._advanced.workers))
            workers.SetName(t("name.workers"))

            api_interval_label = wx.StaticText(panel, label=t("adv.min_api_interval"))
            api_interval = wx.SpinCtrl(
                panel, min=0, max=60, initial=int(self._advanced.min_api_interval_s)
            )
            api_interval.SetName(t("name.min_api_interval"))

            timeout_label = wx.StaticText(panel, label=t("adv.recognize_timeout"))
            timeout = wx.SpinCtrl(
                panel, min=10, max=600, initial=int(self._advanced.recognize_timeout_s)
            )
            timeout.SetName(t("name.recognize_timeout"))

            windows_label = wx.StaticText(panel, label=t("adv.max_windows"))
            windows = wx.SpinCtrl(
                panel, min=1, max=6, initial=int(self._advanced.max_windows_per_sample)
            )
            windows.SetName(t("name.max_windows"))

            step_label = wx.StaticText(panel, label=t("adv.window_step"))
            step = wx.SpinCtrl(panel, min=1, max=60, initial=int(self._advanced.window_step_s))
            step.SetName(t("name.window_step"))

            silence_label = wx.StaticText(panel, label=t("adv.silence_dbfs"))
            silence = wx.TextCtrl(panel, value=str(self._advanced.silence_dbfs_threshold))
            silence.SetName(t("name.silence_dbfs"))

            debug = wx.CheckBox(panel, label=t("adv.debug_audio"))
            debug.SetName(t("name.debug_audio"))
            debug.SetValue(bool(self._advanced.debug_audio))

            for label, ctrl in [
                (sample_label, sample),
                (sig_label, sig),
                (workers_label, workers),
                (api_interval_label, api_interval),
                (timeout_label, timeout),
                (windows_label, windows),
                (step_label, step),
                (silence_label, silence),
            ]:
                recog_grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                recog_grid.Add(ctrl, 0, wx.EXPAND)

            recog_box.Add(recog_grid, 0, wx.ALL | wx.EXPAND, 8)
            recog_box.Add(debug, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            http_box = wx.StaticBoxSizer(
                wx.StaticBox(panel, label=t("dialog.advanced.group_http")),
                wx.VERTICAL,
            )
            http_grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
            http_grid.AddGrowableCol(1, 1)

            device_label = wx.StaticText(panel, label="Device (URL):")
            device = wx.TextCtrl(panel, value=self._advanced.shazam_device)
            device.SetName("Device (URL)")

            accept_label = wx.StaticText(panel, label=t("adv.accept_language"))
            accept = wx.TextCtrl(panel, value=self._advanced.shazam_accept_language)
            accept.SetName("Accept-Language")
            accept.SetToolTip(t("tooltip.accept_language"))

            ua_label = wx.StaticText(panel, label="User-Agent:")
            ua = wx.TextCtrl(panel, value=self._advanced.shazam_user_agent)
            ua.SetName("User-Agent")

            platform_label = wx.StaticText(panel, label="X-Shazam-Platform:")
            platform = wx.TextCtrl(panel, value=self._advanced.shazam_platform)
            platform.SetName("X-Shazam-Platform")

            appver_label = wx.StaticText(panel, label="X-Shazam-AppVersion:")
            appver = wx.TextCtrl(panel, value=self._advanced.shazam_app_version)
            appver.SetName("X-Shazam-AppVersion")

            tz_label = wx.StaticText(panel, label="Time zone:")
            tz = wx.TextCtrl(panel, value=self._advanced.shazam_time_zone)
            tz.SetName("Time zone")

            for label, ctrl in [
                (device_label, device),
                (accept_label, accept),
                (ua_label, ua),
                (platform_label, platform),
                (appver_label, appver),
                (tz_label, tz),
            ]:
                http_grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                http_grid.Add(ctrl, 0, wx.EXPAND)

            http_box.Add(http_grid, 0, wx.ALL | wx.EXPAND, 8)

            root = wx.BoxSizer(wx.VERTICAL)
            root.Add(recog_box, 0, wx.ALL | wx.EXPAND, 12)
            root.Add(http_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

            buttons = wx.StdDialogButtonSizer()
            ok_btn = wx.Button(panel, wx.ID_OK)
            cancel_btn = wx.Button(panel, wx.ID_CANCEL)
            buttons.AddButton(ok_btn)
            buttons.AddButton(cancel_btn)
            buttons.Realize()
            dialog.SetAffirmativeId(wx.ID_OK)
            dialog.SetEscapeId(wx.ID_CANCEL)
            ok_btn.SetDefault()

            root.Add(buttons, 0, wx.ALL | wx.EXPAND, 12)
            panel.SetSizer(root)

            dialog_sizer = wx.BoxSizer(wx.VERTICAL)
            dialog_sizer.Add(panel, 1, wx.EXPAND)
            dialog.SetSizer(dialog_sizer)
            dialog.Layout()
            dialog.CentreOnParent()

            def on_ok(_evt: wx.CommandEvent) -> None:
                sample_s = int(sample.GetValue())
                sig_s = int(sig.GetValue())
                if sig_s > sample_s:
                    wx.MessageBox(
                        t("adv.error.sig_gt_sample"),
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

                self._advanced.sample_duration_s = sample_s
                self._advanced.sig_duration_s = sig_s
                self._advanced.workers = int(workers.GetValue())
                self._advanced.min_api_interval_s = int(api_interval.GetValue())
                self._advanced.recognize_timeout_s = int(timeout.GetValue())
                self._advanced.max_windows_per_sample = int(windows.GetValue())
                self._advanced.window_step_s = int(step.GetValue())
                self._advanced.silence_dbfs_threshold = silence_dbfs
                self._advanced.debug_audio = bool(debug.GetValue())
                self._advanced.shazam_device = device.GetValue().strip() or _SHAZAM_DEVICE
                self._advanced.shazam_accept_language = accept.GetValue().strip()
                self._advanced.shazam_user_agent = ua.GetValue().strip() or _SHAZAM_USER_AGENT
                self._advanced.shazam_platform = platform.GetValue().strip() or _SHAZAM_PLATFORM
                self._advanced.shazam_app_version = appver.GetValue().strip() or _SHAZAM_APP_VERSION
                self._advanced.shazam_time_zone = tz.GetValue().strip() or _SHAZAM_TIME_ZONE
                self._persist_config()
                dialog.EndModal(wx.ID_OK)

            ok_btn.Bind(wx.EVT_BUTTON, on_ok)
            cancel_btn.Bind(wx.EVT_BUTTON, lambda _e: dialog.EndModal(wx.ID_CANCEL))
            dialog.Bind(wx.EVT_CLOSE, lambda _e: dialog.EndModal(wx.ID_CANCEL))

            dialog.ShowModal()
            dialog.Destroy()
            wx.CallAfter(_after_modal)
            wx.CallLater(50, _after_modal)

        def _on_scan(self, _event: wx.CommandEvent) -> None:
            if self._worker and self._worker.is_alive():
                return

            if not self._input_paths:
                wx.MessageBox(
                    t("error.add_file_first"),
                    _APP_NAME,
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return

            interval_s = int(self.interval.GetValue())
            if interval_s <= 0:
                wx.MessageBox(
                    t("error.interval_positive"), _APP_NAME, wx.OK | wx.ICON_ERROR, self
                )
                return

            language = _SHAZAM_URL_LANGUAGE
            lang_idx = self.language_choice.GetSelection()
            if lang_idx != wx.NOT_FOUND and lang_idx < len(self._language_codes):
                language = self._language_codes[lang_idx]

            endpoint_country = _SHAZAM_ENDPOINT_COUNTRY
            country_idx = self.country_choice.GetSelection()
            if country_idx != wx.NOT_FOUND and country_idx < len(self._country_codes):
                endpoint_country = self._country_codes[country_idx]

            input_paths = [p for p in self._input_paths if p.exists() and p.is_file()]
            if not input_paths:
                wx.MessageBox(
                    t("error.no_existing_files"),
                    _APP_NAME,
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return

            unknown_suffixes = [p for p in input_paths if p.suffix.lower() not in _SUPPORTED_SUFFIXES]
            if unknown_suffixes:
                exts = sorted({p.suffix.lower() or "(brak)" for p in unknown_suffixes})
                preview = ", ".join(exts[:8]) + ("..." if len(exts) > 8 else "")
                res = wx.MessageBox(
                    t("prompt.unknown_ext", preview=preview),
                    _APP_NAME,
                    wx.YES_NO | wx.ICON_WARNING,
                    self,
                )
                if res != wx.YES:
                    return

            output_override: Path | None = None
            if raw_out_dir := self.out_dir.GetValue().strip():
                output_override = Path(raw_out_dir).expanduser()
                try:
                    output_override.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    wx.MessageBox(
                        t("error.create_folder", error=str(exc)),
                        _APP_NAME,
                        wx.OK | wx.ICON_ERROR,
                        self,
                    )
                    return

            used_outputs: set[Path] = set()
            existing_outputs: list[Path] = []
            jobs: list[tuple[Path, Path]] = []
            for input_path in input_paths:
                out_dir = output_override if output_override is not None else input_path.parent
                out_path = out_dir / input_path.with_suffix(".txt").name
                if output_override is not None:
                    base = out_path
                    n = 2
                    while out_path in used_outputs:
                        out_path = base.with_name(f"{base.stem} ({n}){base.suffix}")
                        n += 1
                used_outputs.add(out_path)
                if out_path.exists():
                    existing_outputs.append(out_path)
                jobs.append((input_path, out_path))

            if existing_outputs:
                res = wx.MessageBox(
                    t("prompt.overwrite_outputs", count=len(existing_outputs)),
                    _APP_NAME,
                    wx.YES_NO | wx.ICON_WARNING,
                    self,
                )
                if res != wx.YES:
                    return

            self.log.SetValue("")
            self.progress.SetValue(0)
            self._stop_event.clear()
            self._set_running(True)
            self.SetStatusText(t("status.starting"))

            self._persist_config()

            self._worker = threading.Thread(
                target=self._worker_main,
                args=(
                    jobs,
                    interval_s,
                    language,
                    endpoint_country,
                    self._advanced,
                ),
                daemon=True,
            )
            self._worker.start()

        def _on_stop(self, _event: wx.CommandEvent) -> None:
            self._stop_event.set()
            self.SetStatusText(t("status.stopping"))

        def _worker_main(
            self,
            jobs: list[tuple[Path, Path]],
            interval_s: int,
            language: str,
            endpoint_country: str,
            advanced: _AdvancedSettings,
        ) -> None:
            file_total = max(1, len(jobs))
            try:
                for file_index, (input_path, output_file) in enumerate(jobs, start=1):
                    if self._stop_event.is_set():
                        break
                    try:
                        self._scan_one_file(
                            input_path=input_path,
                            output_file=output_file,
                            interval_s=interval_s,
                            language=language,
                            endpoint_country=endpoint_country,
                            advanced=advanced,
                            file_index=file_index,
                            file_total=file_total,
                        )
                    except FfmpegNotFoundError:
                        raise
                    except Exception as exc:
                        self._events.put(("warn", f"{input_path.name}\t{exc}"))

                if self._stop_event.is_set():
                    self._events.put(("stopped", t("status.stopped")))
                else:
                    self._events.put(("done", t("status.done")))
            except FfmpegNotFoundError:
                self._events.put(
                    (
                        "error",
                        t("error.ffmpeg_missing"),
                    )
                )
            except Exception as exc:
                self._events.put(("error", str(exc)))

        def _scan_one_file(
            self,
            *,
            input_path: Path,
            output_file: Path,
            interval_s: int,
            language: str,
            endpoint_country: str,
            advanced: _AdvancedSettings,
            file_index: int,
            file_total: int,
        ) -> None:
            language = language.strip() or _SHAZAM_URL_LANGUAGE
            endpoint_country = endpoint_country.strip().upper() or _SHAZAM_ENDPOINT_COUNTRY
            accept_language = advanced.shazam_accept_language.strip() or language

            workers = max(1, min(32, int(advanced.workers)))
            sample_duration_s = max(1, min(60, int(advanced.sample_duration_s)))
            sig_duration_s = max(1, min(sample_duration_s, int(advanced.sig_duration_s)))
            min_api_interval_s = max(0, min(60, int(advanced.min_api_interval_s)))
            recognize_timeout_s = max(10, min(600, int(advanced.recognize_timeout_s)))
            max_windows_per_sample = max(1, min(6, int(advanced.max_windows_per_sample)))
            window_step_s = max(1, min(60, int(advanced.window_step_s)))
            silence_dbfs_threshold = float(advanced.silence_dbfs_threshold)
            debug_audio = bool(advanced.debug_audio)

            shazam_device = advanced.shazam_device.strip() or _SHAZAM_DEVICE
            shazam_platform = advanced.shazam_platform.strip() or _SHAZAM_PLATFORM
            shazam_app_version = advanced.shazam_app_version.strip() or _SHAZAM_APP_VERSION
            shazam_user_agent = advanced.shazam_user_agent.strip() or _SHAZAM_USER_AGENT
            shazam_time_zone = advanced.shazam_time_zone.strip() or _SHAZAM_TIME_ZONE

            try:
                duration_s = probe_duration_seconds(input_path)
                total_samples = (
                    max(1, math.ceil(duration_s / interval_s)) if duration_s is not None else None
                )
                self._events.put(
                    (
                        "meta",
                        {
                            "file_index": file_index,
                            "file_total": file_total,
                            "input_file": str(input_path),
                            "duration_s": duration_s,
                            "total_samples": total_samples,
                            "output_file": str(output_file),
                            "workers": workers,
                            "sample_duration_s": int(sample_duration_s),
                            "sig_duration_s": int(sig_duration_s),
                            "min_api_interval_s": int(min_api_interval_s),
                            "language": language,
                            "endpoint_country": endpoint_country,
                        },
                    )
                )
                self._events.put(
                    (
                        "status",
                        t(
                            "status.scanning_file",
                            file_index=file_index,
                            file_total=file_total,
                            filename=input_path.name,
                        ),
                    )
                )

                seen: set[str] = set()
                started = time.monotonic()
                matches_count = 0
                nomatch_count = 0
                error_count = 0
                rate_limit_count = 0

                class _AdaptiveThrottle:
                    def __init__(self, base_interval_s: float) -> None:
                        self._lock = threading.Lock()
                        self._next_allowed = 0.0
                        self._freeze_until = 0.0
                        self._base_interval_s = base_interval_s
                        self._min_interval_s = base_interval_s
                        self._rate_limit_hits = 0
                        self._successes_since_limit = 0

                    def _compute_wait(self) -> float:
                        now = time.monotonic()
                        return max(self._freeze_until - now, self._next_allowed - now, 0.0)

                    def peek_wait_seconds(self) -> int:
                        with self._lock:
                            wait = self._compute_wait()
                        return int(math.ceil(wait)) if wait > 0 else 0

                    def wait_for_slot(self) -> None:
                        while True:
                            with self._lock:
                                wait = self._compute_wait()
                                if wait <= 0:
                                    now = time.monotonic()
                                    self._next_allowed = now + self._min_interval_s
                                    return
                            time.sleep(min(wait, 1.0))

                    def note_success(self) -> None:
                        with self._lock:
                            if self._rate_limit_hits == 0:
                                return
                            self._successes_since_limit += 1
                            if self._successes_since_limit >= 10:
                                self._successes_since_limit = 0
                                self._min_interval_s = max(
                                    self._base_interval_s, self._min_interval_s * 0.8
                                )

                    def note_rate_limit(self, retry_after_s: int | None) -> int:
                        with self._lock:
                            now = time.monotonic()
                            self._rate_limit_hits += 1
                            self._successes_since_limit = 0

                            if retry_after_s is None:
                                retry_after_s = min(300, 5 * (2 ** min(self._rate_limit_hits, 6)))
                            self._freeze_until = max(self._freeze_until, now + retry_after_s)
                            self._min_interval_s = min(
                                max(self._min_interval_s * 2, self._base_interval_s), 60.0
                            )

                            wait = self._compute_wait()
                        return int(math.ceil(wait)) if wait > 0 else 0

                    def note_near_rate_limit(self) -> None:
                        with self._lock:
                            if self._rate_limit_hits == 0:
                                self._rate_limit_hits = 1
                            self._successes_since_limit = 0
                            self._min_interval_s = min(
                                max(self._min_interval_s, self._base_interval_s), 60.0
                            )

                sample_duration_s = max(1, min(60, int(sample_duration_s)))
                segment_duration_s = max(1, min(sample_duration_s, int(sig_duration_s)))

                base_interval_s = max(0.0, min(60.0, float(min_api_interval_s)))
                throttle = _AdaptiveThrottle(base_interval_s)

                thread_state = threading.local()

                def _ensure_thread_runtime() -> tuple[Any, Any, Any]:
                    loop = getattr(thread_state, "loop", None)
                    if loop is None or getattr(loop, "is_closed", lambda: False)():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        thread_state.loop = loop
                        thread_state.shazam = None
                        thread_state.segment_duration_s = None
                        thread_state.language = None
                        thread_state.endpoint_country = None
                        thread_state.accept_language = None
                        thread_state.device = None
                        thread_state.platform = None
                        thread_state.app_version = None
                        thread_state.user_agent = None
                        thread_state.time_zone = None
                    else:
                        asyncio.set_event_loop(loop)

                    shazam = getattr(thread_state, "shazam", None)
                    if (
                        shazam is None
                        or getattr(thread_state, "segment_duration_s", None) != segment_duration_s
                        or getattr(thread_state, "language", None) != language
                        or getattr(thread_state, "endpoint_country", None) != endpoint_country
                        or getattr(thread_state, "accept_language", None) != accept_language
                        or getattr(thread_state, "device", None) != shazam_device
                        or getattr(thread_state, "platform", None) != shazam_platform
                        or getattr(thread_state, "app_version", None) != shazam_app_version
                        or getattr(thread_state, "user_agent", None) != shazam_user_agent
                        or getattr(thread_state, "time_zone", None) != shazam_time_zone
                    ):
                        shazam = _PinnedShazam(
                            language=language,
                            endpoint_country=endpoint_country,
                            device=shazam_device,
                            platform=shazam_platform,
                            app_version=shazam_app_version,
                            user_agent=shazam_user_agent,
                            time_zone=shazam_time_zone,
                            accept_language=accept_language,
                            segment_duration_seconds=segment_duration_s,
                        )
                        thread_state.shazam = shazam
                        thread_state.segment_duration_s = segment_duration_s
                        thread_state.language = language
                        thread_state.endpoint_country = endpoint_country
                        thread_state.accept_language = accept_language
                        thread_state.device = shazam_device
                        thread_state.platform = shazam_platform
                        thread_state.app_version = shazam_app_version
                        thread_state.user_agent = shazam_user_agent
                        thread_state.time_zone = shazam_time_zone

                    return loop, shazam, getattr(shazam, "http_client", None)

                def _parse_retry_after_seconds(value: str | None) -> int | None:
                    if not value:
                        return None
                    try:
                        seconds = int(value.strip())
                    except ValueError:
                        return None
                    if seconds <= 0:
                        return None
                    return seconds

                def _recognize(
                    audio_bytes: bytes, *, label_offset_s: int
                ) -> tuple[Any | None, str | None]:
                    nonlocal rate_limit_count
                    loop, shazam, http_client = _ensure_thread_runtime()

                    def _http_snapshot() -> tuple[
                        list[tuple[int, int]] | None, int | None, str | None, str | None
                    ]:
                        attempts: list[tuple[int, int]] | None = (
                            getattr(http_client, "attempts", None) if http_client else None
                        )
                        status: int | None = (
                            getattr(http_client, "last_status", None) if http_client else None
                        )
                        retry_after: str | None = None
                        content_type: str | None = None
                        if http_client and (headers := getattr(http_client, "last_headers", None)):
                            retry_after = headers.get("Retry-After")
                            content_type = headers.get("Content-Type")
                        return attempts, status, retry_after, content_type

                    def _attempt_chain(attempts: list[tuple[int, int]] | None) -> str:
                        if not attempts:
                            return ""
                        chain = "->".join(str(code) for _attempt, code in attempts)
                        return f" ({chain})"

                    try:
                        async def _make_sig() -> Any:
                            return await shazam.core_recognizer.recognize_bytes(value=audio_bytes)

                        sig = loop.run_until_complete(
                            asyncio.wait_for(_make_sig(), timeout=recognize_timeout_s)
                        )
                    except Exception as exc:
                        message = str(exc).strip()
                        if message:
                            return None, f"{type(exc).__name__}: {message}"
                        return None, type(exc).__name__

                    non_rate_limit_attempts = 0
                    while True:
                        if self._stop_event.is_set():
                            return None, "stopped"

                        wait_s = throttle.peek_wait_seconds()
                        if wait_s >= 5:
                            self._events.put(
                                ("status", t("status.api_limit_pause", seconds=wait_s))
                            )
                        throttle.wait_for_slot()

                        try:
                            coro = shazam.send_recognize_request_v2(sig=sig)
                            raw = loop.run_until_complete(
                                asyncio.wait_for(coro, timeout=recognize_timeout_s)
                            )
                        except Exception as exc:
                            attempts, status, retry_after, content_type = _http_snapshot()
                            chain = _attempt_chain(attempts)

                            extra_bits: list[str] = []
                            if status is not None:
                                extra_bits.append(f"HTTP {status}{chain}")
                            elif chain:
                                extra_bits.append(f"HTTP{chain}")
                            if retry_after:
                                extra_bits.append(f"Retry-After={retry_after}")
                            if content_type:
                                extra_bits.append(f"Content-Type={content_type}")
                            extra = f" ({', '.join(extra_bits)})" if extra_bits else ""

                            message = str(exc).strip()
                            if message:
                                message = f"{type(exc).__name__}: {message}{extra}"
                            else:
                                message = f"{type(exc).__name__}{extra}"

                            is_rate_limited = status == 429 or (
                                attempts and any(code == 429 for _attempt, code in attempts)
                            )
                            if not is_rate_limited and message:
                                lowered = message.lower()
                                is_rate_limited = (
                                    "http 429" in lowered
                                    or "429->" in lowered
                                    or "too many requests" in lowered
                                )
                            if is_rate_limited:
                                rate_limit_count += 1
                                wait_s = throttle.note_rate_limit(
                                    _parse_retry_after_seconds(retry_after)
                                )
                                extra_info = ""
                                if retry_after:
                                    extra_info += f" Retry-After={retry_after}"
                                if content_type:
                                    extra_info += f" Content-Type={content_type}"
                                self._events.put(
                                    (
                                        "warn",
                                        t(
                                            "warn.http_429_pause",
                                            timestamp=format_hms(label_offset_s),
                                            chain=chain,
                                            seconds=wait_s,
                                            extra=extra_info,
                                        ),
                                    )
                                )
                                continue

                            transient = (
                                status is None
                                or (status >= 500 if status is not None else False)
                                or "decode json" in message.lower()
                            )
                            non_rate_limit_attempts += 1
                            if (
                                transient
                                and non_rate_limit_attempts < 6
                                and not self._stop_event.is_set()
                            ):
                                throttle.note_near_rate_limit()
                                time.sleep(min(2.0**non_rate_limit_attempts, 60.0))
                                continue

                            return None, message

                        attempts, status, retry_after, _content_type = _http_snapshot()
                        chain = _attempt_chain(attempts)

                        if attempts and any(code == 429 for _attempt, code in attempts):
                            self._events.put(
                                (
                                    "warn",
                                    t(
                                        "warn.http_retry",
                                        timestamp=format_hms(label_offset_s),
                                        chain=chain,
                                    ),
                                )
                            )
                            if status == 200:
                                throttle.note_near_rate_limit()

                        if status == 429:
                            rate_limit_count += 1
                            wait_s = throttle.note_rate_limit(
                                _parse_retry_after_seconds(retry_after)
                            )
                            self._events.put(
                                (
                                    "warn",
                                    t(
                                        "warn.http_429_pause",
                                        timestamp=format_hms(label_offset_s),
                                        chain=chain,
                                        seconds=wait_s,
                                        extra="",
                                    ),
                                )
                            )
                            continue

                        if status is not None and status != 200:
                            detail = ""
                            if isinstance(raw, dict):
                                if isinstance(raw.get("error"), dict):
                                    msg = raw["error"].get("message") or raw["error"].get("detail")
                                    if msg:
                                        detail = str(msg)
                                elif msg := raw.get("message"):
                                    detail = str(msg)

                            extra = f", Retry-After={retry_after}" if retry_after else ""
                            diag = f"HTTP {status}{chain}{extra}"
                            if detail:
                                diag = f"{diag}: {detail}"
                            return None, diag

                        throttle.note_success()
                        return raw, None

                    return None, t("error.recognize_failed")

                audio_meta_lock = threading.Lock()
                audio_meta_logged = False

                def _rms_dbfs(samples: bytes, *, sampwidth: int) -> float:
                    if not samples:
                        return float("-inf")
                    rms = audioop.rms(samples, sampwidth)
                    if rms <= 0:
                        return float("-inf")
                    max_amp = float((1 << (8 * sampwidth - 1)) - 1)
                    return 20.0 * math.log10(rms / max_amp)

                def _rank_window_starts_by_rms(
                    wav_bytes: bytes,
                    *,
                    window_duration_s: int,
                ) -> tuple[list[int], str, float, float]:
                    try:
                        with wave.open(BytesIO(wav_bytes), "rb") as wav_in:
                            channels = wav_in.getnchannels()
                            sampwidth = wav_in.getsampwidth()
                            framerate = wav_in.getframerate()
                            declared_nframes = wav_in.getnframes()
                            frames = wav_in.readframes(declared_nframes)
                    except wave.Error:
                        return [0], "?", float("-inf"), float("-inf")

                    frame_size = channels * sampwidth
                    if frame_size <= 0:
                        return [0], "?", float("-inf"), float("-inf")

                    actual_nframes = len(frames) // frame_size
                    if actual_nframes <= 0:
                        duration_s = 0.0
                        meta = f"{framerate} Hz, {channels} ch, s{sampwidth * 8}le, {duration_s:.1f}s"
                        return [0], meta, float("-inf"), float("-inf")

                    frames = frames[: actual_nframes * frame_size]

                    duration_s = float(actual_nframes) / float(framerate) if framerate else 0.0
                    meta = f"{framerate} Hz, {channels} ch, s{sampwidth * 8}le, {duration_s:.1f}s"
                    overall_dbfs = _rms_dbfs(frames, sampwidth=sampwidth)

                    window_frames = int(window_duration_s * framerate)
                    if window_frames <= 0 or window_frames >= actual_nframes:
                        return [0], meta, overall_dbfs, overall_dbfs

                    step_frames = max(1, int(window_step_s * framerate))
                    candidates: list[tuple[int, int]] = []

                    last_start = actual_nframes - window_frames
                    for start_frame in range(0, last_start + 1, step_frames):
                        start = start_frame * frame_size
                        end = (start_frame + window_frames) * frame_size
                        window = frames[start:end]
                        rms = audioop.rms(window, sampwidth) if window else 0
                        candidates.append((int(rms), int(start_frame)))

                    candidates.sort(key=lambda item: (-item[0], item[1]))
                    best_rms = candidates[0][0] if candidates else 0
                    best_dbfs = (
                        float("-inf")
                        if best_rms <= 0
                        else 20.0
                        * math.log10(best_rms / float((1 << (8 * sampwidth - 1)) - 1))
                    )

                    starts: list[int] = []
                    seen: set[int] = set()
                    for _rms, start_frame in candidates:
                        start_s = int(start_frame / framerate) if framerate else 0
                        if start_s in seen:
                            continue
                        seen.add(start_s)
                        starts.append(start_s)
                        if len(starts) >= max_windows_per_sample:
                            break

                    if not starts:
                        starts = [0]

                    return starts, meta, overall_dbfs, best_dbfs

                def _process_sample(offset_s: int) -> tuple[int, str | None, str | None]:
                    if self._stop_event.is_set():
                        return offset_s, None, "stopped"

                    try:
                        audio = extract_wav_segment(
                            input_path,
                            start_s=offset_s,
                            duration_s=sample_duration_s,
                        )
                    except Exception as exc:
                        return offset_s, None, str(exc)

                    if audio is None or self._stop_event.is_set():
                        return offset_s, None, "eof" if audio is None else None

                    window_starts, audio_meta, overall_dbfs, best_dbfs = _rank_window_starts_by_rms(
                        audio,
                        window_duration_s=segment_duration_s,
                    )

                    nonlocal audio_meta_logged
                    with audio_meta_lock:
                        if not audio_meta_logged:
                            audio_meta_logged = True
                            self._events.put(
                                (
                                    "warn",
                                    f"{format_hms(offset_s)}\tAudio: {audio_meta}, "
                                    f"RMS: {overall_dbfs:.1f} dBFS",
                                )
                            )

                        if best_dbfs < silence_dbfs_threshold:
                            if debug_audio:
                                self._events.put(
                                    (
                                        "warn",
                                        t(
                                            "warn.silence_skip",
                                            timestamp=format_hms(offset_s),
                                            dbfs=best_dbfs,
                                        ),
                                    )
                                )
                            return offset_s, None, None

                    for rel_start_s in window_starts:
                        if self._stop_event.is_set():
                            return offset_s, None, "stopped"

                        window_audio = slice_wav_bytes(
                            audio, start_s=int(rel_start_s), duration_s=segment_duration_s
                        )
                        if window_audio is None:
                            continue

                        label_offset_s = offset_s + int(rel_start_s)
                        raw, error = _recognize(window_audio, label_offset_s=label_offset_s)
                        if error:
                            return label_offset_s, None, error
                        if raw is None:
                            return label_offset_s, None, t("error.recognize_failed")

                        try:
                            track = Serialize.full_track(raw)
                        except Exception as exc:
                            return label_offset_s, None, str(exc)

                        if track.track is not None:
                            line = f"{track.track.subtitle} - {track.track.title}"
                            return label_offset_s, line, None

                    return offset_s, None, None

                with output_file.open("w", encoding="utf-8") as out:
                    if total_samples is None:
                        offset_s = 0
                        done = 0
                        while not self._stop_event.is_set():
                            self._events.put(
                                ("status", t("status.sample", timestamp=format_hms(offset_s)))
                            )
                            sample_offset, line, error = _process_sample(offset_s)
                            if error == "eof":
                                break
                            if error and error != "stopped":
                                self._events.put(("warn", f"{format_hms(sample_offset)}\t{error}"))
                                error_count += 1
                                if "HTTP 429" in error:
                                    rate_limit_count += 1

                            if line:
                                matches_count += 1
                                if line not in seen:
                                    seen.add(line)
                                    out.write(f"{format_hms(sample_offset)}\t{line}\n")
                                    out.flush()
                                    self._events.put(
                                        ("match", f"{format_hms(sample_offset)}\t{line}")
                                    )
                            elif not error:
                                nomatch_count += 1

                            done += 1
                            self._events.put(
                                (
                                    "progress",
                                    {
                                        "done": done,
                                        "total": None,
                                        "matches": matches_count,
                                        "nomatch": nomatch_count,
                                        "errors": error_count,
                                        "rate_limits": rate_limit_count,
                                    },
                                )
                            )
                            offset_s += interval_s
                    else:
                        workers = max(1, int(workers))
                        max_inflight = max(4, workers * 3)
                        executor: ThreadPoolExecutor | None = None
                        inflight: dict[Future[tuple[int, str | None, str | None]], int] = {}

                        try:
                            executor = ThreadPoolExecutor(max_workers=workers)

                            def _submit(idx: int) -> None:
                                offset = idx * interval_s
                                fut = executor.submit(_process_sample, offset)
                                inflight[fut] = idx

                            next_submit = 0
                            while next_submit < total_samples and len(inflight) < max_inflight:
                                _submit(next_submit)
                                next_submit += 1

                            done = 0
                            eof_seen = False
                            while inflight and done < total_samples and not self._stop_event.is_set():
                                done_set, _pending = wait_futures(
                                    inflight.keys(),
                                    timeout=0.25,
                                    return_when=FIRST_COMPLETED,
                                )
                                if not done_set:
                                    continue

                                for fut in done_set:
                                    inflight.pop(fut, None)
                                    sample_offset, line, error = fut.result()
                                    if error == "eof":
                                        eof_seen = True

                                    if error and error != "stopped" and error != "eof":
                                        self._events.put(
                                            ("warn", f"{format_hms(sample_offset)}\t{error}")
                                        )
                                        error_count += 1
                                        if "HTTP 429" in error:
                                            rate_limit_count += 1

                                    if line:
                                        matches_count += 1
                                        if line not in seen:
                                            seen.add(line)
                                            out.write(f"{format_hms(sample_offset)}\t{line}\n")
                                            out.flush()
                                            self._events.put(
                                                ("match", f"{format_hms(sample_offset)}\t{line}")
                                            )
                                    elif not error:
                                        nomatch_count += 1

                                    done += 1
                                    elapsed_s = int(time.monotonic() - started)
                                    eta_s: int | None = None
                                    if done > 0 and not eof_seen:
                                        remaining = total_samples - done
                                        if remaining > 0:
                                            eta_s = int((elapsed_s / done) * remaining)

                                    self._events.put(
                                        (
                                            "progress",
                                            {
                                                "done": done,
                                                "total": total_samples,
                                                "elapsed_s": elapsed_s,
                                                "eta_s": eta_s,
                                                "offset_s": sample_offset,
                                                "matches": matches_count,
                                                "nomatch": nomatch_count,
                                                "errors": error_count,
                                                "rate_limits": rate_limit_count,
                                            },
                                        )
                                    )

                                    if eof_seen or self._stop_event.is_set():
                                        break

                                    while (
                                        next_submit < total_samples
                                        and len(inflight) < max_inflight
                                        and not self._stop_event.is_set()
                                    ):
                                        _submit(next_submit)
                                        next_submit += 1

                                if eof_seen:
                                    break
                        finally:
                            if executor is not None:
                                for fut in inflight.keys():
                                    fut.cancel()
                                executor.shutdown(wait=True, cancel_futures=True)

                if self._stop_event.is_set():
                    self._events.put(
                        (
                            "info",
                            t(
                                "info.file_stopped",
                                file_index=file_index,
                                file_total=file_total,
                                output_file=str(output_file),
                            ),
                        )
                    )
                else:
                    self._events.put(
                        (
                            "info",
                            t(
                                "info.file_done",
                                file_index=file_index,
                                file_total=file_total,
                                output_file=str(output_file),
                            ),
                        )
                    )
            except FfmpegNotFoundError:
                raise
            except Exception:
                raise

        def _on_timer(self, _event: wx.TimerEvent) -> None:
            while True:
                try:
                    kind, payload = self._events.get_nowait()
                except Empty:
                    break

                if kind == "meta":
                    file_index = payload.get("file_index")
                    file_total = payload.get("file_total")
                    input_file = payload.get("input_file")
                    self._scan_file_index = int(file_index) if file_index is not None else None
                    self._scan_file_total = int(file_total) if file_total is not None else None
                    self._scan_file_name = (
                        Path(str(input_file)).name if input_file is not None else None
                    )

                    file_prefix = ""
                    if self._scan_file_index and self._scan_file_total:
                        file_prefix = f"[{self._scan_file_index}/{self._scan_file_total}] "
                    if self._scan_file_name:
                        file_prefix = f"{file_prefix}{self._scan_file_name}: "

                    duration_s = payload.get("duration_s")
                    self._scan_duration_s = int(duration_s) if duration_s is not None else None
                    self._scan_elapsed_s = 0
                    self._scan_matches = 0
                    self._scan_nomatch = 0
                    self._scan_errors = 0
                    self._scan_rate_limits = 0
                    if duration_s is None:
                        self.progress.Pulse()
                    else:
                        self.progress.SetValue(0)
                    workers = payload.get("workers")
                    total_samples = payload.get("total_samples")
                    self._scan_total_samples = int(total_samples) if total_samples else None
                    if total_samples:
                        duration_label = (
                            format_hms(self._scan_duration_s) if self._scan_duration_s else "?"
                        )
                        self.progress_text.SetLabel(
                            t(
                                "progress.initial_known_total",
                                file_prefix=file_prefix,
                                total=total_samples,
                                duration=duration_label,
                                workers=workers,
                            )
                        )
                    else:
                        self.progress_text.SetLabel(
                            t(
                                "progress.initial_unknown_total",
                                file_prefix=file_prefix,
                                workers=workers,
                            )
                        )
                elif kind == "status":
                    self.SetStatusText(payload)
                elif kind == "progress":
                    done = payload.get("done")
                    total = payload.get("total")

                    file_prefix = ""
                    if self._scan_file_index and self._scan_file_total:
                        file_prefix = f"[{self._scan_file_index}/{self._scan_file_total}] "

                    if (matches := payload.get("matches")) is not None:
                        self._scan_matches = int(matches)
                    if (nomatch := payload.get("nomatch")) is not None:
                        self._scan_nomatch = int(nomatch)
                    if (errors := payload.get("errors")) is not None:
                        self._scan_errors = int(errors)
                    if (rate_limits := payload.get("rate_limits")) is not None:
                        self._scan_rate_limits = int(rate_limits)

                    stats = t(
                        "progress.stats",
                        matches=self._scan_matches,
                        nomatch=self._scan_nomatch,
                        errors=self._scan_errors,
                    )
                    if self._scan_rate_limits:
                        stats += t("progress.stats_rate_limits", rate_limits=self._scan_rate_limits)

                    if total:
                        percent = int(min(100, (int(done) / max(1, int(total))) * 100))
                        self.progress.SetValue(percent)
                        eta_s = payload.get("eta_s")
                        elapsed_s = payload.get("elapsed_s")
                        offset_s = payload.get("offset_s")
                        duration_label = (
                            format_hms(self._scan_duration_s) if self._scan_duration_s else "?"
                        )
                        offset_label = format_hms(offset_s) if offset_s is not None else "?"
                        if eta_s is not None and elapsed_s is not None:
                            self._scan_elapsed_s = int(elapsed_s)
                            self.progress_text.SetLabel(
                                t(
                                    "progress.update_with_eta",
                                    file_prefix=file_prefix,
                                    percent=percent,
                                    done=done,
                                    total=total,
                                    elapsed=format_hms(elapsed_s),
                                    eta=format_hms(eta_s),
                                    offset=offset_label,
                                    duration=duration_label,
                                    stats=stats,
                                )
                            )
                        else:
                            self.progress_text.SetLabel(
                                t(
                                    "progress.update_no_eta",
                                    file_prefix=file_prefix,
                                    percent=percent,
                                    done=done,
                                    total=total,
                                    offset=offset_label,
                                    duration=duration_label,
                                    stats=stats,
                                )
                            )
                    else:
                        self.progress.Pulse()
                        if done:
                            self.progress_text.SetLabel(
                                t(
                                    "progress.update_unknown_total_done",
                                    file_prefix=file_prefix,
                                    done=done,
                                    stats=stats,
                                )
                            )
                        else:
                            self.progress_text.SetLabel(
                                t("progress.update_unknown_total", file_prefix=file_prefix)
                            )
                elif kind == "match":
                    self.log.AppendText(payload + "\n")
                elif kind == "info":
                    self.log.AppendText(payload + "\n")
                elif kind == "warn":
                    self.log.AppendText(f"{t('log.warn_prefix')}{payload}\n")
                elif kind in {"done", "stopped"}:
                    file_prefix = ""
                    if self._scan_file_index and self._scan_file_total:
                        file_prefix = f"[{self._scan_file_index}/{self._scan_file_total}] "

                    self.SetStatusText(payload)
                    self._set_running(False)
                    self.progress.SetValue(100 if kind == "done" else self.progress.GetValue())
                    if kind == "done" and self._scan_total_samples is not None:
                        duration_label = (
                            format_hms(self._scan_duration_s) if self._scan_duration_s else "?"
                        )
                        total_samples = self._scan_total_samples
                        self.progress_text.SetLabel(
                            t(
                                "progress.done",
                                file_prefix=file_prefix,
                                total=total_samples,
                                elapsed=format_hms(self._scan_elapsed_s),
                                duration=duration_label,
                                matches=self._scan_matches,
                                nomatch=self._scan_nomatch,
                                errors=self._scan_errors,
                            )
                        )
                    elif kind == "stopped":
                        self.progress_text.SetLabel(t("progress.stopped", file_prefix=file_prefix))
                elif kind == "error":
                    self.SetStatusText(t("status.error"))
                    wx.MessageBox(payload, _APP_NAME, wx.OK | wx.ICON_ERROR, self)
                    self._stop_event.set()
                    self._set_running(False)

        def _on_close(self, event: wx.CloseEvent) -> None:
            self._timer.Stop()
            self._stop_event.set()
            if self._worker and self._worker.is_alive():
                self._worker.join(timeout=2.0)
            self._persist_config()
            event.Skip()

    frame = MainFrame()
    frame.Show(True)
    app.MainLoop()


if __name__ == "__main__":
    main()
