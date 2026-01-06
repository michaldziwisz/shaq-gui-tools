# Specyfikacja: `shaqgui`, `shaqcast`, `shaqfilegui` (dokładność rozpoznawania)

Ten dokument opisuje aktualny pipeline audio, ustawienia domyślne oraz wszystkie gałki konfiguracyjne (ENV), które wpływają na skuteczność rozpoznawania.

## Artefakty / binarki

- `shaq/dist/shaqgui.exe` — GUI: loopback (wyjście) **lub** mikrofon (wejście) → Shazam → zapis unikalnych rozpoznań do pliku.
- `shaq/dist/shaqfilegui.exe` — GUI: plik audio → próbkowanie co N sekund → Shazam → zapis wyników do pliku `.txt` (`HH:MM:SS<TAB>ARTYSTA - TYTUŁ`).
- `shaqcast/dist/shaqcast.exe` — GUI: loopback (wyjście) **lub** mikrofon (wejście) → Shazam → aktualizacja “Now Playing” w Shoutcast.

Wszystkie binarki są budowane przez PyInstaller jako **pojedynczy plik `.exe`**. Na “czystej” maszynie może być wymagany **Microsoft Visual C++ Redistributable 2015–2022 (x64)** (typowe dla `wxPython`/`numpy`).

## Wspólne założenia audio (obu aplikacji)

- Źródło dźwięku: wybrane w GUI jako **Wyjście (loopback)** albo **Wejście (mikrofon)** (`soundcard`, Windows).
- Wewnętrzny format próbek, na którym pracuje Shazam: WAV w pamięci:
  - `16000 Hz`
  - `1 kanał`
  - `PCM16` (`s16le`)
- Nagrywanie odbywa się w blokach (`chunk_frames/chunk_size`, domyślnie 1024 ramek).

## Konfiguracja (pliki JSON)

Ustawienia są konfigurowane z GUI i zapisywane per-aplikacja do pliku `config.json`:

- `shaqgui`: `%APPDATA%\\shaqgui\\config.json` (np. `C:\\Users\\<user>\\AppData\\Roaming\\shaqgui\\config.json`)
- `shaqfilegui`: `%APPDATA%\\shaqfilegui\\config.json`
- `shaqcast`: `%APPDATA%\\shaqcast\\config.json`
  - hasło w presetach jest szyfrowane **DPAPI** (per użytkownik/komputer) z prefiksem `dpapi:`; w razie braku DPAPI fallback `b64:`
  - uwaga: przeniesienie configa na inną maszynę może wymagać ponownego wpisania hasła

ENV nadal mogą istnieć, ale służą jako “fabryczne domyślne” (gdy brak configa).

## Język i kraj Shazama (GUI + listy)

W GUI można wybrać:

- `language` (locale) — język odpowiedzi/metadanych po stronie Shazam.
- `endpoint_country` — “kraj” wykorzystywany przez endpoint (m.in. różne ustawienia regionalne po stronie Shazam).

Listy są wbudowane w aplikacje i pochodzą z publicznych źródeł:

- lista języków: inline skrypt `locale-redirect` na `https://www.shazam.com/` (`supported=[...]`),
- lista krajów: `https://www.shazam.com/services/charts/locations` (`countries[*].id/name`).

Implementacja list:

- `shaq/shaq/_shazam_regions.py` (dla `shaqgui` i `shaqfilegui`)
- `shaqcast/shaqcast/shazam_regions.py` (dla `shaqcast`)

## `shaqgui` — pipeline i ustawienia

### Wybór źródła w GUI

- `Źródło audio`: `Wyjście (loopback)` albo `Wejście (mikrofon)`.
- `Urządzenie`: lista filtruje się zależnie od wybranego źródła.

### Pipeline (high level)

1. Nagraj próbkę z wybranego źródła (loopback/mikrofon) o długości `SAMPLE_SECONDS` (domyślnie 15 s).
2. Wyznacz okna długości `SHAZAM_SEGMENT_SECONDS` (domyślnie 12 s) i policz RMS dla każdego okna w kroku `WINDOW_STEP_S` (domyślnie 1 s).
3. Wybierz top `MAX_WINDOWS_PER_SAMPLE` okien o najwyższym RMS (domyślnie 2).
4. Jeśli najlepsze okno jest ciszą (RMS < `SILENCE_DBFS_THRESHOLD`, domyślnie `-55 dBFS`) → pomiń rozpoznawanie tej próbki.
5. Dla wybranych okien:
   - dotnij WAV do okna (WAV slicing),
   - wyślij do Shazama,
   - przerwij na pierwszym match.
6. Jeśli match: zapisz linię `ARTYSTA - TYTUŁ` do pliku tylko jeśli jest unikalna (deduplikacja w obrębie sesji + pliku historii).

### Ustawienia domyślne i ENV

Ustawienia są czytane z ENV na starcie aplikacji:

- `SHAQGUI_SAMPLE_SECONDS` (domyślnie `15`)
  - Ile sekund nagrywa się na jedną próbkę.
  - Zawsze jest podbijane do co najmniej `SHAQGUI_SHAZAM_SEGMENT_SECONDS`.
  - Zakres: `<= 60`.
- `SHAQGUI_SHAZAM_SEGMENT_SECONDS` (domyślnie `12`)
  - Ile sekund trafia do Shazama jako “podpis” (`segment_duration_seconds` w `Shazam(...)`).
  - Zakres: `5..60`.
- `SHAQGUI_MAX_WINDOWS_PER_SAMPLE` (domyślnie `2`)
  - Ile “najgłośniejszych” okien (RMS) w ramach jednej próbki zostanie spróbowanych.
  - Zakres: `1..6`.
- `SHAQGUI_WINDOW_STEP_S` (domyślnie `1`)
  - Co ile sekund przesuwać okno przy liczeniu RMS.
  - Min: `1`.
- `SHAQGUI_SILENCE_DBFS_THRESHOLD` (domyślnie `-55.0`)
  - Jeśli najlepsze okno ma RMS poniżej progu → próbka jest traktowana jako cisza i nie jest wysyłana.

### Detekcja limitów i backoff (stabilność w długiej pracy)

Jeśli `recognize()` rzuca wyjątek, aplikacja robi pauzę i próbuje dalej:

- Backoff: `5s, 10s, 20s, ...` (wykładniczo), max `300s`.
- Jeśli błąd wygląda na limit (heurystyka po tekście: `429`, `too many requests`, `failed to decode json`) → minimalna pauza `30s`.
- Pauza jest realizowana przez `stop_event.wait(backoff)`, więc przycisk Stop przerywa czekanie.

Uwaga: `shaqgui` nie ma ustawienia “min odstęp między requestami”; kontrola odbywa się przez backoff po błędach i przez ograniczenie liczby okien na próbkę.

### Shazam (język/region)

Ustawiane w GUI:

- `language` (lista) — domyślnie z `SHAQGUI_SHAZAM_LANGUAGE`
- `endpoint_country` (lista) — domyślnie z `SHAQGUI_SHAZAM_COUNTRY`
- `segment_duration_seconds = SHAQGUI_SHAZAM_SEGMENT_SECONDS`

## `shaqcast` — pipeline i ustawienia

### Wybór źródła w GUI

- `Źródło audio`: `Wyjście (loopback)` albo `Wejście (mikrofon)`.
- `Urządzenie`: lista filtruje się zależnie od wybranego źródła.

### Pipeline (high level)

1. Nagraj próbkę z wybranego źródła (loopback/mikrofon) o długości `listen_seconds` (domyślnie 15 s; ustawiane w GUI).
2. Ustal długość podpisu: `segment_duration_s = min(listen_seconds, SHAQCAST_SHAZAM_SEGMENT_SECONDS)` (domyślnie 12 s).
3. (Opcjonalnie) policz RMS dla okien długości `segment_duration_s` i wybierz top okna (domyślnie 1 okno).
4. Wyślij wybrane okno do Shazama; jeśli match:
   - zbuduj `ARTYSTA - TYTUŁ`,
   - wyślij do Shoutcast (dla wszystkich SID), ale tylko jeśli utwór się zmienił.
5. Jeśli brak match:
   - jeśli w GUI ustawiono fallback tekst → wysyłaj fallback, ale tylko jeśli się zmienił,
   - w przeciwnym razie tylko loguj “No match”.

### Ustawienia domyślne i ENV

- `listen_seconds` (GUI + `StreamSettings.listen_seconds`)
  - Domyślnie `15`.
  - Zakres w GUI: `3..30`.
- `SHAQCAST_SHAZAM_SEGMENT_SECONDS` (domyślnie `12`, zakres `3..60`)
  - Maksymalna długość podpisu; realnie `min(listen_seconds, ...)`.
- `SHAQCAST_MAX_WINDOWS_PER_SAMPLE` (domyślnie `1`, zakres `1..6`)
  - Ile okien RMS spróbować w ramach jednej próbki.
- `SHAQCAST_WINDOW_STEP_S` (domyślnie `1`)
  - Krok przesuwania okna w RMS.
- `SHAQCAST_SILENCE_DBFS_THRESHOLD` (domyślnie `-55.0`)
  - Jeśli najlepsze okno jest ciszą → pomiń rozpoznawanie tej próbki.
- `SHAQCAST_MIN_REQUEST_INTERVAL_S` (domyślnie `10.0`, zakres `0..60`)
  - Minimalny odstęp między requestami do Shazama (szczególnie ważne gdy `MAX_WINDOWS_PER_SAMPLE > 1`).

### Detekcja limitów i backoff

Analogicznie jak w `shaqgui`:

- backoff wykładniczy `5s..300s`,
- minimum `30s` jeśli wygląda na limit (heurystyka po treści błędu),
- dodatkowo stały limiter “min odstęp” (`SHAQCAST_MIN_REQUEST_INTERVAL_S`).

### Shazam (język/region)

Ustawiane w GUI:

- `language` (lista) — domyślnie z `SHAQCAST_SHAZAM_LANGUAGE`
- `endpoint_country` (lista) — domyślnie z `SHAQCAST_SHAZAM_COUNTRY`
- `segment_duration_seconds = min(listen_seconds, SHAQCAST_SHAZAM_SEGMENT_SECONDS)`

## Jak zmieniać ustawienia (Windows)

Najprościej: w aplikacji kliknij **Ustawienia zaawansowane…** → ustaw wartości → OK. Zapis następuje do `config.json` (patrz wyżej). Zmienne ENV działają tylko jako wartości startowe (gdy brak configa).

### PowerShell

Przykład (zwiększamy dokładność kosztem liczby requestów):

```powershell
$env:SHAQGUI_SAMPLE_SECONDS="20"
$env:SHAQGUI_SHAZAM_SEGMENT_SECONDS="15"
$env:SHAQGUI_MAX_WINDOWS_PER_SAMPLE="3"
$env:SHAQGUI_WINDOW_STEP_S="1"
.\shaqgui.exe
```

`shaqcast` (np. 2 okna + większa przerwa między requestami):

```powershell
$env:SHAQCAST_MAX_WINDOWS_PER_SAMPLE="2"
$env:SHAQCAST_MIN_REQUEST_INTERVAL_S="15"
.\shaqcast.exe
```

### CMD

```bat
set SHAQGUI_SAMPLE_SECONDS=20
set SHAQGUI_SHAZAM_SEGMENT_SECONDS=15
set SHAQGUI_MAX_WINDOWS_PER_SAMPLE=3
shaqgui.exe
```

## Rekomendacje (dokładność vs limity)

- Jeśli zależy Ci na **maksymalnej dokładności**:
  - zwiększ `*_SHAZAM_SEGMENT_SECONDS` do 15–20,
  - zwiększ `*_SAMPLE_SECONDS`/`listen_seconds` tak, aby był ≥ segment,
  - zwiększ `*_MAX_WINDOWS_PER_SAMPLE` (np. 3–4) i zostaw `*_WINDOW_STEP_S=1`.
- Jeśli zaczynają się limity API (429/HTML zamiast JSON):
  - dla `shaqcast` zwiększ `SHAQCAST_MIN_REQUEST_INTERVAL_S`,
  - dla obu aplikacji zmniejsz liczbę okien (`*_MAX_WINDOWS_PER_SAMPLE`) albo wydłuż próbkę (rzadsze requesty).

## Notatka: ujednolicenie “PL” jak w `shaqfilegui`

`shaqfilegui` używa customowego klienta HTTP i nagłówków, a `Accept-Language` jest ustawiane na wybrany w GUI `language`. `shaqgui` i `shaqcast` używają domyślnego klienta `shazamio`, ale również pozwalają wybrać `language`/`endpoint_country` w GUI. Jeśli chcesz, można przenieść ten sam “pinned HTTP client + nagłówki” także do `shaqgui`/`shaqcast`.

## Dostępność (czytniki ekranu) — `shaqcast`

W `shaqcast` NVDA potrafiło ogłaszać pola jako generyczne “pole edycji”, bez etykiet.

Przyczyna: etykiety (`wx.StaticText`) były tworzone **po** kontrolkach, więc w drzewie okien Win32 (kolejność tworzenia) NVDA nie łączyło etykiety z polem.

Naprawa:

- etykiety są tworzone **przed** kontrolkami (tak jak w `shaqfilegui`)
- dodatkowo ustawiamy jawne nazwy MSAA przez `wx.Accessible` (NVDA wtedy widzi `accName` i czyta np. “Port”, “Nasłuch (sekundy)”)
- okno “Ustawienia zaawansowane…” ma własne przyciski OK/Anuluj (`wx.StdDialogButtonSizer`) i zamyka się przez `EndModal()`; po zamknięciu robimy `Refresh/Update/SendSizeEvent` (+ `CallLater(50, ...)`) na oknie głównym, żeby nie zostawał “ghost” na ekranie

## Testy jednostkowe (offline)

W repo są tylko testy, które mają sens bez sieci i bez zależności GUI/audio:

- `shaq/tests/*`: logika WAV (`slice_wav_bytes`), formatowanie czasu (`format_hms`), regiony/języki, zapis/odczyt configu, deduplikacja historii.
- `shaqcast/tests/*`: zapis/odczyt configu, szyfrowanie/odszyfrowanie hasła presetów, heurystyka odpowiedzi Shoutcast, regiony/języki.

CI (GitHub Actions) uruchamia `pytest` na Linux (bez instalowania ciężkich zależności typu `wxPython`).
