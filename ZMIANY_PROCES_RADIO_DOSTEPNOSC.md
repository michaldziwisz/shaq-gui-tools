# Nasłuch procesów i radia oraz dostępność wyników

Zmiany względem wersji 0.1.9 obejmują trzy programy. Radio i automatyczny odczyt
wyników są dostępne w ShaqGUI. Nasłuch procesu dodano również do ShaqCast,
a poprawki klienta rozpoznawania obejmują także ShaqFileGUI.

## Nasłuch konkretnego programu

- Nowe źródło „Program (wybrany proces)” w ShaqGUI i ShaqCast. Można wybrać
  uruchomiony program albo wskazać jego plik EXE, także gdy jest zamknięty.
- Konfiguracja przechowuje pełną ścieżkę EXE. Zmiana PID po restarcie odtwarzacza
  nie usuwa wyboru. Program informuje o niedostępności odtwarzacza, czeka na jego
  uruchomienie i podejmuje nasłuch. Stop przerywa również oczekiwanie.
- WASAPI przechwytuje wybrany proces i jego podprocesy. Mowa NVDA oraz dźwięki
  innych aplikacji nie trafiają do tej próbki. Kilka niezależnych instancji
  tego samego EXE wymaga pozostawienia jednej, zamiast przypadkowego wyboru.
- Wymagany Windows w kompilacji co najmniej 20348, np. Windows 11. Na starszym
  systemie wyświetlany jest komunikat. Nie są instalowane dodatkowe sterowniki.
- Całkowite wyciszenie odtwarzacza może wyzerować przechwytywany sygnał.
  README opisuje ten warunek oraz użycie istniejącego progu ciszy dla bardzo
  cichego, ale nadal obecnego dźwięku. Domyślny próg pozostaje bez zmian.

## Radio internetowe w ShaqGUI

- Nowe źródło „Strumień radiowy (cichy nasłuch)”: bezpośredni adres HTTP/HTTPS,
  import list stacji PLS/M3U/M3U8, wybór stacji z wieloma wpisami oraz adresy HLS.
- Start pobiera i rozpoznaje radio bez jego odtwarzania. Historia pozostaje na
  liście i w dotychczasowym pliku tekstowym. Nie jest zapisywana cała audycja.
- Osobne przyciski włączają i zatrzymują odsłuch. Suwak 0–100% reguluje wyłącznie
  odsłuch: 0% lub jego zatrzymanie nie zmienia próbek rozpoznawania.
- Adres oraz głośność są zapamiętywane; po otwarciu programu odsłuch jest wyłączony.
  Główny Stop zatrzymuje rozpoznawanie; odsłuch ma własny przycisk zatrzymania.
- Po zerwaniu połączenia następują automatyczne ponowienia. Bufor PCM ma limit
  65 sekund; próbki sprzed zerwania nie są łączone z nowymi. Zawieszony dekoder
  jest zatrzymywany, a wolne rozpoznawanie nie tworzy rosnącej kolejki audycji.
- Czytnik oznajmia połączenie, rozpoczęcie nasłuchu, błąd, powrót transmisji
  i zatrzymanie, również przy wyłączonym odczycie tytułów. Powtarzające się
  nieudane próby połączenia nie powodują ciągłego powtarzania komunikatu.
- FFmpeg jest dołączony do `shaqgui.exe`; instalacja systemowa nie jest wymagana.
  Zmieniono specyfikację PyInstaller i kolejność budowania w GitHub Actions.

## Czytniki ekranu i fokus

- W ustawieniach zaawansowanych ShaqGUI dodano domyślnie wyłączoną opcję
  „Odczytuj nowe rozpoznania, gdy jestem na liście wyników” oraz „Testuj odczyt”.
- Odczytywany jest wykonawca i tytuł, gdy aktywne okno ma fokus na liście.
  Zaznaczenie nie zmienia się; kolejne dopasowania tego samego utworu nie są
  ciągle powtarzane. Ustawienie jest zapamiętywane.
- Accessible Output 2 obsługuje aktywne czytniki, w tym NVDA i JAWS. Dodano
  dostosowanie API ZDSR, z preferencją biblioteki zainstalowanego czytnika,
  oraz powiadomienia Windows UI Automation dla Narratora.
- EXE zawiera biblioteki interfejsów czytników oraz metadane Accessible Output 2.
  Poprawiono wyszukiwanie DLL po rozpakowaniu jednoplikowego EXE przez PyInstaller.
  Aplikacja nie uruchamia dodatkowego głosu SAPI.
- Start przenosi fokus na listę wyników we wszystkich trybach ShaqGUI.
  Włączenie i wyłączenie odsłuchu zachowuje fokus na odpowiednim przycisku;
  nie przenosi go na suwak. Zakończenie operacji w tle nie odbiera fokusu,
  jeśli użytkownik zdążył przejść do innej kontrolki.

## Poprawki rozpoznawania

- Ograniczono sygnaturę Shazama do sprawdzonych 12 sekund, również po wczytaniu
  starszych ustawień. Nagrywana próbka nadal może być dłuższa, by wybrać fragment.
- Usunięto ukryte wielokrotne ponawianie zapytań HTTP. Pojedyncze zapytanie ma
  limit 15 sekund; oczekiwanie na rozpoznanie można przerwać przyciskiem Stop.
- Błędy HTTP, ograniczenia liczby zapytań i niepoprawne odpowiedzi są odróżniane
  od braku dopasowania. Ponowienia uwzględniają nagłówek Retry-After.
- Poprawiono zamykanie pętli asynchronicznych, przerywanie nagrywania w ShaqCast
  oraz ograniczono ponowienia i poprawiono obsługę HTTP 429 w ShaqFileGUI.
- Utwór zapisany wcześniej w historii znów pojawia się na liście ShaqGUI po
  rozpoznaniu. Plik historii nadal usuwa duplikaty; błąd jego zapisu kończy nasłuch.

## Zależności i budowanie

| Składnik | Zastosowanie i zmiana |
| --- | --- |
| `accessible-output2==0.17` | Nowa zależność ShaqGUI na Windows; odczyt przez czytniki i dołączone biblioteki ich interfejsów. |
| `ctypes`, Windows WASAPI i UI Automation | Nasłuch procesu i powiadomienia; bez nowego pakietu do przechwytywania dźwięku. |
| FFmpeg | Dotychczas używany w ShaqFileGUI; teraz dołączony także do ShaqGUI jako dekoder radia. |
| `soundcard`, `numpy`, `wxPython` | Istniejące zależności wykorzystane również do odsłuchu i jego kontrolek. |
| `shazamio>=0.6,<0.9`, `aiohttp` | Dotychczasowy silnik rozpoznawania z własną kontrolą czasu HTTP. Zakres wersji shazamio zachowano i zastosowano także przy budowaniu w Actions. |
| PyInstaller, `sygnalista-reporter` | Dotychczasowe pakowanie i zgłaszanie błędów; zaktualizowano wykaz dołączanych modułów. |

Nazwy plików wynikowych pozostają bez zmian: `shaqgui.exe`, `shaqfilegui.exe`,
`shaqcast.exe`. Każdy można uruchomić samodzielnie bez instalowania Pythona.
Paczka testowa zawiera również instrukcję, wykaz wersji użytych przy budowaniu,
licencje, informacje o FFmpeg i sumy kontrolne SHA-256.

Nie dodano jeszcze innego dostawcy rozpoznawania. README wymienia możliwe
integracje AudD, ACRCloud, AudioTag i AcoustID, lecz kod nadal korzysta z Shazama.

## Weryfikacja

Na Windows, Python 3.11, z włączonymi testami dodatkowymi:

- ShaqGUI/ShaqFileGUI: **230 testów zaliczonych**.
- ShaqCast: **105 testów zaliczonych, 1 pominięty**; test autostartu celowo nie
  tworzy prawdziwego skrótu w folderze Autostart użytkownika Windows.
- Wszystkie trzy gotowe EXE: poprawne otwarcie okna, zamknięcie i brak logu awarii.
- Rzeczywisty WASAPI: izolacja od drugiego procesu, Stop i ponowne uruchomienie
  procesu. Dodatkowo sprawdzono nasłuch działającego Winampa.
- Lokalny serwer HTTP: MP3, AAC, HLS, playlisty, błędy połączenia, ponowienia,
  zawieszenie dekodera i zwolnienie jego procesu.
- Strumień publicznego radia: rozpoznanie w gotowym EXE z FFmpeg z paczki,
  przy braku systemowego FFmpeg w PATH. Odsłuch i wyciszenie suwakiem sprawdzono
  również pomiarem dźwięku.
- NVDA: potwierdzony odczyt. UI Automation: sprawdzono wywołanie powiadomienia.
  Dla JAWS i ZDSR sprawdzono kod oraz testy interfejsów, bez pełnej próby z
  uruchomionymi czytnikami. Nie wykonano całonocnego testu ciągłej pracy.

Zwykły przebieg testów jest dostosowany do CI bez urządzeń audio. Testy rozszerzone
na Windows wymagają zainstalowanych `pytest`, `wxPython`, `soundcard`,
`shazamio>=0.6,<0.9`, `accessible-output2==0.17` oraz FFmpeg w katalogu dostawcy.
Użyto Pythona 3.11; Python 3.13 i nowsze wymagają osobnego sprawdzenia ze względu
na wykorzystywany przez projekt moduł `audioop`.

Przykładowe polecenia PowerShell z głównego katalogu repozytorium:

```powershell
$env:SHAQ_TEST_GUI = '1'
$env:SHAQ_TEST_RADIO = '1'
$env:SHAQ_TEST_PROCESS_AUDIO = '1'
$env:SHAQ_TEST_UIA = '1'
Push-Location shaq
python -m pytest -q
Pop-Location
Push-Location shaqcast
python -m pytest -q
Pop-Location
```

`SHAQ_TEST_PROCESS_AUDIO=1` odtwarza krótkie sygnały kontrolne. Test UI Automation
wymaga aktywnego klienta dostępności. Testy nie zapisują konfiguracji użytkownika
i nie potrzebują jego prywatnych nagrań.
