"""Polskie i angielskie komunikaty radia, wspólne dla interfejsu i odbiornika."""

from __future__ import annotations

from typing import Any

_STRINGS: dict[str, dict[str, str]] = {
    "radio.source": {
        "pl": "Strumień radiowy (cichy nasłuch)",
        "en": "Radio stream (silent monitoring)",
    },
    "radio.url_label": {"pl": "Adres strumienia radia:", "en": "Radio stream URL:"},
    "radio.url_name": {"pl": "Adres strumienia radia", "en": "Radio stream URL"},
    "radio.url_hint": {
        "pl": "Bezpośredni adres HTTP lub HTTPS, np. strumień MP3, AAC albo HLS.",
        "en": "Direct HTTP or HTTPS URL, for example an MP3, AAC or HLS stream.",
    },
    "radio.import_button": {"pl": "Importuj PLS / M3U…", "en": "Import PLS / M3U…"},
    "radio.preview_start": {"pl": "Włącz odsłuch", "en": "Start preview"},
    "radio.preview_start_hint": {
        "pl": "Włącz słuchanie radia. Cichy nasłuch działa niezależnie.",
        "en": "Listen to the radio. Silent monitoring works independently.",
    },
    "radio.preview_stop": {"pl": "Zatrzymaj odsłuch", "en": "Stop preview"},
    "radio.preview_stop_hint": {
        "pl": "Wyłącz dźwięk radia, zachowując rozpoznawanie utworów.",
        "en": "Turn off radio playback while keeping song recognition running.",
    },
    "radio.volume_label": {"pl": "Głośność odsłuchu (%):", "en": "Preview volume (%):"},
    "radio.volume_name": {
        "pl": "Głośność odsłuchu w procentach",
        "en": "Preview volume in percent",
    },
    "radio.preview_off": {
        "pl": "Odsłuch wyłączony. Start uruchamia cichy nasłuch.",
        "en": "Preview is off. Start enables silent monitoring.",
    },
    "radio.disconnected": {
        "pl": "Strumień nie jest połączony.",
        "en": "The stream is not connected.",
    },
    "radio.stop_before_url": {
        "pl": "Zatrzymaj nasłuch i odsłuch przed zmianą adresu radia.",
        "en": "Stop monitoring and preview before changing the radio URL.",
    },
    "radio.monitor_started": {
        "pl": "Nasłuch strumienia rozpoczęty.",
        "en": "Stream monitoring started.",
    },
    "radio.monitor_connecting": {
        "pl": "Łączenie z radiem. Nasłuch rozpocznie się po odebraniu dźwięku.",
        "en": "Connecting to the radio. Monitoring will begin when audio is received.",
    },
    "radio.monitor_stopped": {
        "pl": "Nasłuch strumienia zatrzymany.",
        "en": "Stream monitoring stopped.",
    },
    "radio.connection_lost": {
        "pl": "Brak połączenia z radiem. Będę ponawiać połączenie automatycznie.",
        "en": "The radio connection is unavailable. Reconnecting automatically.",
    },
    "radio.connection_restored_monitor": {
        "pl": "Połączenie z radiem przywrócone. Nasłuch rozpoczęty.",
        "en": "Radio connection restored. Monitoring started.",
    },
    "radio.connection_restored_preview": {
        "pl": "Połączenie z radiem przywrócone. Odsłuch włączony.",
        "en": "Radio connection restored. Preview is on.",
    },
    "radio.connection_ready_monitor": {
        "pl": "Połączono ze strumieniem radia. Nasłuch rozpoczęty.",
        "en": "Connected to the radio stream. Monitoring started.",
    },
    "radio.connection_ready_preview": {
        "pl": "Połączono ze strumieniem radia. Odsłuch włączony.",
        "en": "Connected to the radio stream. Preview is on.",
    },
    "radio.preview_title": {"pl": "Odsłuch radia", "en": "Radio preview"},
    "radio.preview_stopped_monitor": {
        "pl": "Odsłuch wyłączony. Nasłuch trwa dalej.",
        "en": "Preview is off. Monitoring continues.",
    },
    "radio.preview_stopped": {"pl": "Odsłuch radia wyłączony.", "en": "Radio preview is off."},
    "radio.preview_on": {
        "pl": "Odsłuch włączony. Jego głośność nie wpływa na rozpoznawanie.",
        "en": "Preview is on. Its volume does not affect recognition.",
    },
    "radio.monitor_silent": {
        "pl": "Cichy nasłuch włączony. Radio nie jest odtwarzane w głośnikach.",
        "en": "Silent monitoring is on. Radio audio is not played through the speakers.",
    },
    "radio.playlist_choose": {"pl": "Wybierz playlistę radia", "en": "Choose a radio playlist"},
    "radio.playlist_filter": {
        "pl": "Playlisty radia (*.pls;*.m3u;*.m3u8)|*.pls;*.m3u;*.m3u8|Wszystkie pliki (*.*)|*.*",
        "en": "Radio playlists (*.pls;*.m3u;*.m3u8)|*.pls;*.m3u;*.m3u8|All files (*.*)|*.*",
    },
    "radio.import_title": {"pl": "Import radia", "en": "Import radio"},
    "radio.station_choose": {
        "pl": "Wybierz stację do nasłuchu:",
        "en": "Choose a station to monitor:",
    },
    "radio.stations_title": {"pl": "Stacje z playlisty", "en": "Playlist stations"},
    "radio.import_done": {
        "pl": "Wczytano adres radia. Naciśnij Start, aby rozpocząć cichy nasłuch.",
        "en": "Radio URL loaded. Press Start to begin silent monitoring.",
    },
    "radio.preview_started": {"pl": "Włączono odsłuch radia.", "en": "Radio preview started."},
    "radio.preview_stopping": {
        "pl": "Zatrzymywanie odsłuchu. Rozpoznawanie pozostaje niezależne.",
        "en": "Stopping preview. Recognition continues independently.",
    },
    "radio.url_type": {
        "pl": "Adres strumienia musi być tekstem.",
        "en": "The stream URL must be text.",
    },
    "radio.url_invalid": {
        "pl": "Podaj poprawny adres strumienia radia HTTP lub HTTPS.",
        "en": "Enter a valid HTTP or HTTPS radio stream URL.",
    },
    "radio.station_type": {
        "pl": "Nazwa stacji musi być tekstem.",
        "en": "The station name must be text.",
    },
    "radio.playlist_type": {
        "pl": "Zawartość playlisty musi być ciągiem bajtów.",
        "en": "Playlist content must be bytes.",
    },
    "radio.playlist_large": {
        "pl": "Playlista jest zbyt duża; limit wynosi 1 MB.",
        "en": "The playlist is too large; the limit is 1 MB.",
    },
    "radio.playlist_hls": {
        "pl": "To manifest HLS. Wklej internetowy adres pliku M3U8 w pole strumienia.",
        "en": "This is an HLS manifest. Paste the online M3U8 URL into the stream field.",
    },
    "radio.playlist_invalid": {
        "pl": "Nie można odczytać playlisty PLS.",
        "en": "Unable to read the PLS playlist.",
    },
    "radio.playlist_many": {
        "pl": "Playlista zawiera za dużo stacji; limit wynosi 500.",
        "en": "The playlist contains too many stations; the limit is 500.",
    },
    "radio.playlist_empty": {
        "pl": "Playlista nie zawiera żadnego poprawnego adresu radia HTTP lub HTTPS.",
        "en": "The playlist contains no valid HTTP or HTTPS radio URLs.",
    },
    "radio.playlist_cycle": {
        "pl": "Playlista odsyła ponownie do samej siebie.",
        "en": "The playlist refers back to itself.",
    },
    "radio.playlist_nested": {
        "pl": "Zbyt wiele zagnieżdżonych playlist radia.",
        "en": "Too many nested radio playlists.",
    },
    "radio.ffmpeg_missing": {
        "pl": (
            "Brak dołączonego dekodera FFmpeg. Pobierz pełną wersję ShaqGUI z obsługą radia. "
            "Pozostałe tryby nasłuchu nie wymagają tego dekodera."
        ),
        "en": (
            "The bundled FFmpeg decoder is missing. Download the full ShaqGUI version with "
            "radio support. Other monitoring modes do not require this decoder."
        ),
    },
    "radio.pcm_type": {
        "pl": "Próbki strumienia muszą być ciągiem bajtów.",
        "en": "Stream samples must be bytes.",
    },
    "radio.pcm_frame": {
        "pl": "Niepełna ramka dźwięku stereo.",
        "en": "Incomplete stereo audio frame.",
    },
    "radio.duration_type": {
        "pl": "Długość próbki musi być liczbą.",
        "en": "Sample duration must be a number.",
    },
    "radio.duration_range": {
        "pl": "Długość próbki musi wynosić więcej niż zero i najwyżej 60 sekund.",
        "en": "Sample duration must be greater than zero and at most 60 seconds.",
    },
    "radio.session_closed": {
        "pl": "Sesja radia została już zamknięta.",
        "en": "The radio session has already been closed.",
    },
    "radio.decoder_empty": {
        "pl": "Dekoder nie udostępnił dźwięku.",
        "en": "The decoder provided no audio output.",
    },
    "radio.connecting": {
        "pl": "Łączenie ze strumieniem radia…",
        "en": "Connecting to the radio stream…",
    },
    "radio.connected": {
        "pl": "Połączono. Odbieram dźwięk radia.",
        "en": "Connected. Receiving radio audio.",
    },
    "radio.failed": {
        "pl": (
            "Brak transmisji radia. Ponowna próba za {seconds} s. "
            "Sprawdź połączenie i adres strumienia."
        ),
        "en": (
            "Radio stream unavailable. Retrying in {seconds} s. "
            "Check the connection and stream URL."
        ),
    },
    "radio.volume_type": {
        "pl": "Głośność odsłuchu musi być liczbą całkowitą.",
        "en": "Preview volume must be an integer.",
    },
    "radio.volume_range": {
        "pl": "Głośność odsłuchu musi należeć do zakresu 0–100.",
        "en": "Preview volume must be between 0 and 100.",
    },
    "radio.preview_restarted": {
        "pl": "Odsłuch został już uruchomiony lub zamknięty.",
        "en": "Preview has already been started or closed.",
    },
    "radio.windows_audio": {
        "pl": "Nie można uruchomić obsługi dźwięku Windows.",
        "en": "Unable to initialize Windows audio.",
    },
    "radio.no_speaker": {
        "pl": "Brak domyślnego urządzenia odtwarzającego.",
        "en": "No default playback device is available.",
    },
    "radio.preview_error": {
        "pl": "Nie można uruchomić odsłuchu. Sprawdź domyślne wyjście dźwięku Windows.",
        "en": "Unable to start preview. Check the default Windows audio output.",
    },
}


def default_translate(key: str, **values: Any) -> str:
    """Udostępnia polskie komunikaty wywołaniom bez tłumacza interfejsu."""
    entry = _STRINGS.get(key)
    return entry["pl"].format(**values) if entry else key
