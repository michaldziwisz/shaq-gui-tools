"""Odczyt list stacji PLS/M3U oraz sprawdzanie adresów radia internetowego."""

from __future__ import annotations

import configparser
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_PLAYLIST_BYTES = 1024 * 1024
MAX_STATIONS = 500


def validate_stream_url(value: str) -> str:
    """Zwraca adres HTTP(S); odrzuca brak hosta, błędny port i znaki sterujące."""
    if not isinstance(value, str):
        raise TypeError("Adres strumienia musi być tekstem.")
    value = value.strip()
    if not value or len(value) > 8192 or any(ord(char) < 32 for char in value):
        raise ValueError("Podaj poprawny adres strumienia radia HTTP lub HTTPS.")
    if value.lower().startswith("icy://"):
        value = "http://" + value[6:]
    try:
        parts = urlsplit(value)
        port = parts.port
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if any(char.isspace() for char in parts.netloc) or port == 0:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Podaj poprawny adres strumienia radia HTTP lub HTTPS.") from exc
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))


@dataclass(frozen=True)
class RadioStation:
    """Nazwa stacji i sprawdzony adres strumienia."""

    url: str
    title: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", validate_stream_url(self.url))
        if not isinstance(self.title, str):
            raise TypeError("Nazwa stacji musi być tekstem.")
        object.__setattr__(self, "title", " ".join(self.title.split())[:300])

    @property
    def label(self) -> str:
        """Opis do wyboru stacji, bez hasła i parametrów zapytania z adresu."""
        parts = urlsplit(self.url)
        address = f"{parts.hostname}{parts.path}"
        return f"{self.title} — {address}" if self.title else address


def _decode(data: bytes) -> str:
    if not isinstance(data, bytes):
        raise TypeError("Zawartość playlisty musi być ciągiem bajtów.")
    if len(data) > MAX_PLAYLIST_BYTES:
        raise ValueError("Playlista jest zbyt duża; limit wynosi 1 MB.")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250", errors="replace")


def is_hls_playlist(data: bytes) -> bool:
    """Rozróżnia manifest HLS od listy adresów stacji."""
    return any(line.lstrip().upper().startswith("#EXT-X-") for line in _decode(data).splitlines())


def parse_playlist(data: bytes, *, base_url: str | None = None) -> list[RadioStation]:
    """Czyta PLS/M3U, pomijając lokalne pliki, duplikaty i nieobsługiwane adresy."""
    text = _decode(data)
    if is_hls_playlist(data):
        raise ValueError("To manifest HLS. Wklej internetowy adres pliku M3U8 w pole strumienia.")
    if base_url is not None:
        base_url = validate_stream_url(base_url)
    candidates: list[tuple[str, str]] = []
    if re.search(r"^\s*\[playlist\]\s*$", text, flags=re.MULTILINE | re.IGNORECASE):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(text)
            section = next(parser[name] for name in parser.sections() if name.lower() == "playlist")
        except (configparser.Error, StopIteration) as exc:
            raise ValueError("Nie można odczytać playlisty PLS.") from exc
        files = sorted(
            (
                (int(key[4:]), value)
                for key, value in section.items()
                if re.fullmatch(r"file\d{1,8}", key)
            ),
            key=lambda item: item[0],
        )
        candidates = [(url, section.get(f"title{index}", "")) for index, url in files]
    else:
        title = ""
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("#EXTINF:"):
                title = line.partition(",")[2].strip()
            elif line and not line.startswith(("#", ";")):
                candidates.append((line, title))
                title = ""
    stations: list[RadioStation] = []
    seen: set[str] = set()
    for address, title in candidates:
        try:
            address = address.strip()
            if base_url:
                address = urljoin(base_url, address)
            station = RadioStation(address, title)
        except ValueError:
            continue
        if station.url not in seen:
            stations.append(station)
            seen.add(station.url)
        if len(stations) > MAX_STATIONS:
            raise ValueError("Playlista zawiera za dużo stacji; limit wynosi 500.")
    if not stations:
        raise ValueError("Playlista nie zawiera żadnego poprawnego adresu radia HTTP lub HTTPS.")
    return stations


def load_playlist(path: Path) -> list[RadioStation]:
    """Wczytuje plik playlisty z ograniczeniem rozmiaru."""
    with path.open("rb") as source:
        return parse_playlist(source.read(MAX_PLAYLIST_BYTES + 1))


class _RadioRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        """Sprawdza protokół także po przekierowaniu playlisty."""
        validate_stream_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def resolve_stream_url(url: str, stop_event: threading.Event) -> str | None:
    """Rozwija sieciowe playlisty; manifest HLS pozostawia dekoderowi FFmpeg."""
    visited: set[str] = set()
    opener = build_opener(_RadioRedirect())
    for _attempt in range(5):
        if stop_event.is_set():
            return None
        url = validate_stream_url(url)
        if url in visited:
            raise ValueError("Playlista odsyła ponownie do samej siebie.")
        visited.add(url)
        if Path(urlsplit(url).path).suffix.lower() not in {".pls", ".m3u", ".m3u8"}:
            return url
        request = Request(url, headers={"User-Agent": "ShaqGUI/Radio", "Accept": "*/*"})
        with opener.open(request, timeout=5) as response:
            content = response.read(MAX_PLAYLIST_BYTES + 1)
            final_url = validate_stream_url(response.geturl())
        if is_hls_playlist(content):
            return final_url
        url = parse_playlist(content, base_url=final_url)[0].url
    raise ValueError("Zbyt wiele zagnieżdżonych playlist radia.")
