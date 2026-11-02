# shaq-gui-tools

## PL

[Opis nasłuchu wybranego programu](ZMIANY_PROCES.md).

`shaq-gui-tools` to zestaw dostępnych (czytniki ekranu) aplikacji GUI na Windows do rozpoznawania muzyki (Shazam) oraz pracy na plikach/strumieniu.

**Aplikacje (EXE):**

- `shaqgui` — nasłuch z **Wyjścia (loopback)**, **Wejścia (mikrofon)** albo **Strumienia radiowego** → rozpoznanie → zapis historii do pliku.
- `shaqfilegui` — skanowanie **wielu plików** (albo całego folderu) przez próbkowanie co N sekund → zapis wyników do `.txt`.
- `shaqcast` — nasłuch z wybranego urządzenia → rozpoznanie → aktualizacja “Now Playing” w Shoutcast (SIDy) lub Icecast (mounty).

**Kopiowanie wyników (ShaqGUI):**

Na liście zapisanych rozpoznań w `shaqgui` **Ctrl+C** kopiuje sam tytuł
zaznaczonego utworu, a **Ctrl+Shift+C** kopiuje wykonawców i tytuł.
Czytnik ekranu oznajmia wynik działania, również przy wyłączonym automatycznym
odczycie rozpoznań. Brak zaznaczenia lub błąd schowka daje osobny komunikat.
Skróty działają tylko na tej liście; tytuł pochodzi z danych rozpoznania,
więc myślniki w nazwach wykonawców i utworów pozostają zachowane.

**Konfiguracja (zapamiętywanie ustawień):**

- `shaqgui`: `%APPDATA%\\shaqgui\\config.json`
- `shaqfilegui`: `%APPDATA%\\shaqfilegui\\config.json`
- `shaqcast`: `%APPDATA%\\shaqcast\\config.json` (hasło w presetach jest szyfrowane DPAPI per użytkownik/komputer)

**Szczegóły techniczne i strojenie (dokładność/limity/backoff):**

- `SPECYFIKACJA_SHAQGUI_SHAQCAST.md`
- [Radio, odsłuch i czytniki ekranu](ZMIANY_RADIO_CZYTNIKI.md)
- [Klient HTTP, limity i ponowienia rozpoznawania](ZMIANY_ROZPOZNAWANIE.md)

**Budowanie `.exe` (Windows):**

- `shaqgui` / `shaqfilegui`: `shaq/shaqgui.spec`, `shaq/shaqfilegui.spec`
- `shaqcast`: `shaqcast/shaqcast.spec`

Uwaga: do budowania `shaqgui.exe` potrzebny jest `ffmpeg.exe`, a do `shaqfilegui.exe` także `ffprobe.exe` w `shaq/vendor/ffmpeg` (można je pobrać skryptem `shaq/fetch_ffmpeg_windows.py`). Dekoder trafia do EXE, więc użytkownik nie musi instalować go w systemie.

**Testy (pytest):**

- `cd shaq && python -m pip install -e .[test] && python -m pytest`
- `cd shaqcast && python -m pip install -e .[test] && python -m pytest`

## EN

`shaq-gui-tools` is a set of accessible (screen-reader friendly) Windows GUI apps for music recognition (Shazam) and file/stream workflows.

**Apps (EXE):**

- `shaqgui` — listen from **Output (loopback)** or **Input (microphone)** → recognize → append to a history file.
- `shaqfilegui` — scan **multiple files** (or a whole folder) by sampling every N seconds → write results to `.txt`.
- `shaqcast` — listen from a selected device → recognize → update Shoutcast “Now Playing” (one or more SIDs) or Icecast (mounts).

**Copying results (ShaqGUI):**

In the `shaqgui` saved results list, **Ctrl+C** copies the selected song title,
and **Ctrl+Shift+C** copies its artists and title. The screen reader announces
the outcome even when automatic recognition announcements are disabled.
An empty selection or a clipboard error produces a separate message.
These shortcuts only apply to the results list. The title comes from recognition
metadata, preserving hyphens in artist names and song titles.

**Config (settings persistence):**

- `shaqgui`: `%APPDATA%\\shaqgui\\config.json`
- `shaqfilegui`: `%APPDATA%\\shaqfilegui\\config.json`
- `shaqcast`: `%APPDATA%\\shaqcast\\config.json` (passwords in presets are DPAPI-encrypted per user/machine)

**Technical details / tuning (accuracy vs rate limits / backoff):**

- `SPECYFIKACJA_SHAQGUI_SHAQCAST.md`

**Building `.exe` (Windows):**

- `shaqgui` / `shaqfilegui`: `shaq/shaqgui.spec`, `shaq/shaqfilegui.spec`
- `shaqcast`: `shaqcast/shaqcast.spec`

Note: building `shaqfilegui.exe` requires `ffmpeg.exe`/`ffprobe.exe` in `shaq/vendor/ffmpeg` (you can fetch them via `shaq/fetch_ffmpeg_windows.py`).

**Tests (pytest):**

- `cd shaq && python -m pip install -e .[test] && python -m pytest`
- `cd shaqcast && python -m pip install -e .[test] && python -m pytest`
