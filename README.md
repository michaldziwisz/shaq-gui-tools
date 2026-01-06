# shaq-gui-tools

## PL

`shaq-gui-tools` to zestaw dostępnych (czytniki ekranu) aplikacji GUI na Windows do rozpoznawania muzyki (Shazam) oraz pracy na plikach/strumieniu.

**Aplikacje (EXE):**

- `shaqgui` — nasłuch z **Wyjścia (loopback)** albo **Wejścia (mikrofon)** → rozpoznanie → zapis historii do pliku.
- `shaqfilegui` — skanowanie **wielu plików** (albo całego folderu) przez próbkowanie co N sekund → zapis wyników do `.txt`.
- `shaqcast` — nasłuch z wybranego urządzenia → rozpoznanie → aktualizacja “Now Playing” w Shoutcast (SIDy).

**Konfiguracja (zapamiętywanie ustawień):**

- `shaqgui`: `%APPDATA%\\shaqgui\\config.json`
- `shaqfilegui`: `%APPDATA%\\shaqfilegui\\config.json`
- `shaqcast`: `%APPDATA%\\shaqcast\\config.json` (hasło w presetach jest szyfrowane DPAPI per użytkownik/komputer)

**Szczegóły techniczne i strojenie (dokładność/limity/backoff):**

- `SPECYFIKACJA_SHAQGUI_SHAQCAST.md`

**Budowanie `.exe` (Windows):**

- `shaqgui` / `shaqfilegui`: `shaq/shaqgui.spec`, `shaq/shaqfilegui.spec`
- `shaqcast`: `shaqcast/shaqcast.spec`

Uwaga: do budowania `shaqfilegui.exe` potrzebne są `ffmpeg.exe`/`ffprobe.exe` w `shaq/vendor/ffmpeg` (można je pobrać skryptem `shaq/fetch_ffmpeg_windows.py`).

**Testy (pytest):**

- `cd shaq && python -m pip install -e .[test] && python -m pytest`
- `cd shaqcast && python -m pip install -e .[test] && python -m pytest`

## EN

`shaq-gui-tools` is a set of accessible (screen-reader friendly) Windows GUI apps for music recognition (Shazam) and file/stream workflows.

**Apps (EXE):**

- `shaqgui` — listen from **Output (loopback)** or **Input (microphone)** → recognize → append to a history file.
- `shaqfilegui` — scan **multiple files** (or a whole folder) by sampling every N seconds → write results to `.txt`.
- `shaqcast` — listen from a selected device → recognize → update Shoutcast “Now Playing” metadata (one or more SIDs).

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
