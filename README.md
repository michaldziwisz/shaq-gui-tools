# shaq-gui-tools

## PL

`shaq-gui-tools` to zestaw dostępnych (czytniki ekranu) aplikacji GUI na Windows do rozpoznawania muzyki (Shazam) oraz pracy na plikach/strumieniu.

**Aplikacje (EXE):**

- `shaqgui` — nasłuch **Wyjścia (loopback)**, **Wejścia (mikrofon)**, **Programu**
  lub cichy odbiór **Strumienia radiowego** → rozpoznanie → zapis historii do pliku.
- `shaqfilegui` — skanowanie **wielu plików** (albo całego folderu) przez próbkowanie co N sekund → zapis wyników do `.txt`.
- `shaqcast` — nasłuch z wybranego urządzenia lub programu → rozpoznanie → aktualizacja “Now Playing” w Shoutcast (SIDy) lub Icecast (mounty).

**Konfiguracja (zapamiętywanie ustawień):**

- `shaqgui`: `%APPDATA%\\shaqgui\\config.json`
- `shaqfilegui`: `%APPDATA%\\shaqfilegui\\config.json`
- `shaqcast`: `%APPDATA%\\shaqcast\\config.json` (hasło w presetach jest szyfrowane DPAPI per użytkownik/komputer)

**Szczegóły techniczne i strojenie (dokładność/limity/backoff):**

- `SPECYFIKACJA_SHAQGUI_SHAQCAST.md`
- [Opis zmian, zależności i weryfikacji](ZMIANY_PROCES_RADIO_DOSTEPNOSC.md)

**Budowanie `.exe` (Windows):**

- `shaqgui` / `shaqfilegui`: `shaq/shaqgui.spec`, `shaq/shaqfilegui.spec`
- `shaqcast`: `shaqcast/shaqcast.spec`

Do budowania `shaqgui.exe` potrzebny jest `ffmpeg.exe`, a do `shaqfilegui.exe`
także `ffprobe.exe`, w katalogu `shaq/vendor/ffmpeg`. Można je pobrać skryptem
`shaq/fetch_ffmpeg_windows.py`. Gotowe EXE zawierają te narzędzia.

**Testy (pytest):**

- `cd shaq && python -m pip install -e .[test] && python -m pytest`
- `cd shaqcast && python -m pip install -e .[test] && python -m pytest`

Testy odbioru radia z lokalnego serwera HTTP wymagają FFmpeg i ustawienia
`SHAQ_TEST_RADIO=1`. Nie łączą się z publicznymi stacjami ani nie odtwarzają dźwięku.

### Nasłuch wybranego programu

W `shaqgui` i `shaqcast` wybierz **Źródło audio → Program (wybrany proces)**,
a następnie np. `winamp.exe`. Przycisk **Wskaż plik EXE…** pozwala wybrać również
zamknięty odtwarzacz. Ten tryb przechwytuje dźwięk programu i jego podprocesów;
dźwięki osobnych aplikacji, takich jak NVDA, nie trafiają do rozpoznawania.

Zapamiętywana jest pełna ścieżka programu, nie jego chwilowy PID. Po uruchomieniu
aplikacja informuje, jeśli zapisany odtwarzacz jest zamknięty. **Start** rozpoczyna
oczekiwanie na niego, a po uruchomieniu odtwarzacza nasłuch podejmuje pracę.
Zamknięcie i ponowne uruchomienie odtwarzacza podczas nasłuchu również zachowuje
wybór. **Stop** przerywa nagrywanie lub oczekiwanie. Przy kilku osobnych instancjach
tego samego programu należy pozostawić jedną. Przeniesienie pliku EXE wymaga
ponownego wskazania jego ścieżki.

Wymagana jest kompilacja Windows **20348 lub nowsza**, np. Windows 11.
Na starszym systemie pojawi się komunikat; aplikacja nie zastępuje tego trybu
nasłuchem całego wyjścia. Mechanizm korzysta bezpośrednio z
[WASAPI przechwytującego procesy](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/).

#### Ciche odtwarzanie i wyciszenie

Nasłuch procesu nie wymaga osobnej integracji z każdym odtwarzaczem. Obejmuje
strumienie wybranego programu dostępne przez Windows, również przy korzystaniu
z wyjścia WaveOut. Dostępność dźwięku zależy jednak od sposobu jego odtwarzania
i regulacji głośności; sam wybór programu nie omija wszystkich jego ustawień.

Przy bardzo cichym, ale nadal odtwarzanym dźwięku warto sprawdzić
**Ustawienia zaawansowane → Próg ciszy (dBFS)**. Domyślnie próbki poniżej
**−55 dBFS** są pomijane jeszcze przed wysłaniem do Shazama. W trybie **Program**
można wypróbować **−80 dBFS**. Dwie próbki kontrolne zostały rozpoznane nawet
po tysiąckrotnym zmniejszeniu amplitudy, choć przy domyślnym progu program by je
pominął. To wynik tych prób, a nie gwarancja rozpoznania dowolnego cichego nagrania.
Zmiana progu nie wzmacnia dźwięku, nie zmienia głośności odtwarzacza ani długości
sygnatury. Ustawienie dotyczy także innych źródeł: przy mikrofonie niższy próg
może dopuszczać szum, dlatego domyślna wartość pozostaje bez zmian.

Całkowite wyciszenie aplikacji może usunąć sygnał przed jego przechwyceniem.
W pomiarach WaveOut oraz wyciszenia sesji w mikserze Windows nagranie nie zawierało
wtedy muzyki. Obniżenie progu lub wzmocnienie próbki nie odtworzy utraconego sygnału.
[Dokumentacja Windows](https://learn.microsoft.com/en-us/windows/win32/coreaudio/session-volume-controls)
opisuje zastosowanie głośności sesji do jej strumieni. Regulacja wewnątrz
odtwarzacza i regulacja całego urządzenia wyjściowego to różne etapy.

Jeżeli potrzebne jest rozpoznawanie pliku bez słyszalnego odtwarzania, służy do
tego **shaqfilegui**. Inną możliwością jest skierowanie dźwięku odtwarzacza na
osobne wyjście lub wirtualny kabel, pozostawienie jego głośności i nasłuch procesu.
Wymaga to odpowiedniej konfiguracji urządzeń; aplikacja nie zmienia jej samodzielnie.

### Cichy nasłuch radia internetowego

W **ShaqGUI → Źródło audio → Strumień radiowy (cichy nasłuch)** wklej bezpośredni
adres radia HTTP/HTTPS albo użyj przycisku **Importuj PLS / M3U…**. Przy kilku
stacjach w playliście pojawi się lista wyboru. Obsługiwane są również adresy
manifestów HLS M3U8. Adres jest zapamiętywany między uruchomieniami.

**Start** rozpoczyna rozpoznawanie radia bez odtwarzania dźwięku. Wyniki pojawiają
się na dotychczasowej liście i są na bieżąco zapisywane w wybranym pliku historii.
Muzyka z komputera, mowa NVDA i głośność systemowa nie wpływają na pobieraną próbkę.
Transmisję dekoduje [FFmpeg](https://ffmpeg.org/ffmpeg.html), dołączony do EXE:
nie trzeba instalować go w Windows ani ustawiać PATH. Własna kopia dekodera ma
pierwszeństwo przed instalacją systemową.

**Włącz odsłuch** pozwala posłuchać tego samego strumienia. **Zatrzymaj odsłuch**
wyłącza słuchanie, pozostawiając rozpoznawanie. Osobny suwak **Głośność odsłuchu**
działa w zakresie 0–100%, obsługuje klawiaturę i zapamiętuje ustawienie. Nawet 0%
nie wycisza próbek przesyłanych do rozpoznawania. Odsłuch można też uruchomić przed
nasłuchem; naciśnięcie głównego **Stop** zatrzymuje rozpoznawanie, a osobny przycisk
odsłuchu steruje słuchaniem. Po ponownym otwarciu aplikacji odsłuch jest wyłączony.

Czytnik ekranu oznajmia rozpoczęcie nasłuchu, błędy połączenia, przywrócenie
transmisji oraz zatrzymanie. Te komunikaty są niezależne od opcjonalnego odczytu
tytułów i działają również poza listą wyników. Kolejne próby połączenia podczas
tej samej awarii nie powtarzają komunikatu co kilka sekund. Stan pozostaje także
widoczny w oknie aplikacji.

Po utracie transmisji program ponawia połączenie z przerwami do 30 sekund.
Próbki sprzed awarii nie są sklejane z nowymi, a po opóźnionej odpowiedzi Shazama
nasłuch pobiera świeży dźwięk. Bufor transmisji jest ograniczony do 65 sekund;
cała audycja nie jest zapisywana na dysku. Komputer musi pozostać uruchomiony,
bez uśpienia, i mieć dostęp do internetu. Dostępność stacji oraz Shazama nadal
wpływa na liczbę rozpoznanych utworów.

### Czas i wynik rozpoznawania

W **ShaqGUI → Ustawienia zaawansowane** można włączyć
**Odczytuj nowe rozpoznania, gdy jestem na liście wyników**. Opcja jest domyślnie
wyłączona i zapamiętywana między uruchomieniami. W aktywnym oknie czytnik odczytuje
wykonawcę i tytuł, kiedy fokus jest na liście. Nie przesuwa zaznaczenia i nie
powtarza kolejnych dopasowań tego samego utworu. Po ponownym naciśnięciu Start
pierwszy wynik może zostać odczytany ponownie. Przycisk **Testuj odczyt** pozwala
sprawdzić działanie przed rozpoczęciem nasłuchu, również przy wyłączonej opcji.

NVDA, JAWS, ZDSR i pozostałe czytniki obsługiwane przez
[Accessible Output 2](https://pypi.org/project/accessible-output2/) korzystają
z odpowiednich interfejsów biblioteki. Narrator korzysta z powiadomień
[Windows UI Automation](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationcoreapi/nf-uiautomationcoreapi-uiaraisenotificationevent).
W ZDSR aplikacja preferuje bibliotekę API z zainstalowanego lub uruchomionego
czytnika, zgodnie z [dokumentacją ZDSR](https://www.zdsr.com/docs/api/zdsr-api/).
Odczyt trafia do kolejki czytnika bez przerywania bieżącej mowy. Nie uruchamia
osobnego głosu SAPI. Obsługa mowy jest ładowana dopiero przy pierwszym odczycie.

Sygnatura wysyłana do Shazama ma najwyżej **12 sekund**. Dłuższe wartości ze
starszych ustawień są automatycznie ograniczane; cała nagrywana próbka może być
dłuższa, żeby program mógł wybrać jej najlepszy fragment. W sprawdzonych próbkach
15-sekundowe sygnatury dawały pusty wynik pomimo poprawnego rozpoznania przy 12 s.

Zapytanie HTTP ma limit 15 s i nie jest ponawiane w ukryciu przez bibliotekę.
**Stop** przerywa oczekiwanie na odpowiedź i przerwę po błędzie. Błąd usługi jest
zgłaszany osobno od braku dopasowania. Ponownie rozpoznany utwór jest widoczny
w `shaqgui` także wtedy, gdy już znajduje się w pliku historii; sam plik nadal
zawiera unikalne wpisy.

### Inne usługi rozpoznawania muzyki

Obecnie rozpoznawanie nadal korzysta z Shazama. Możliwe kolejne integracje:

- [AudD](https://docs.audd.io/): rozpoznawanie przesłanej próbki WAV przez HTTP;
  potrzebny własny token API. Usługa udostępnia okres próbny i płatne limity.
- [ACRCloud](https://docs.acrcloud.com/reference/identification-api/identification-api):
  rozpoznawanie próbki lub odcisku audio; potrzebne adres projektu, klucz i sekret.
  Zalecane są krótkie fragmenty, do około 15 sekund.
- [AudioTag](https://user.audiotag.info/doc/AudioTag-API_v1.0.pdf): API przyjmuje pliki
  i udostępnia wynik po zakończeniu analizy; wymaga konta i klucza dostępu.
- [AcoustID](https://acoustid.org/webservice): wyszukuje odciski Chromaprint i metadane
  MusicBrainz; wymaga klucza aplikacji i dodatkowego narzędzia do odcisków audio.

Dodanie innej bazy może pomóc przy utworze nieznanym Shazamowi, ale nie gwarantuje
identyfikacji nagrania z infolinii. Żadna z powyższych integracji nie jest jeszcze
włączona w programie.

## EN

`shaq-gui-tools` is a set of accessible (screen-reader friendly) Windows GUI apps for music recognition (Shazam) and file/stream workflows.

**Apps (EXE):**

- `shaqgui` — listen from **Output (loopback)** or **Input (microphone)** → recognize → append to a history file.
- `shaqfilegui` — scan **multiple files** (or a whole folder) by sampling every N seconds → write results to `.txt`.
- `shaqcast` — listen from a selected device → recognize → update Shoutcast “Now Playing” (one or more SIDs) or Icecast (mounts).

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
