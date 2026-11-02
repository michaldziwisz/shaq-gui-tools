# Ciche radio, odsłuch i odczyt rozpoznań w ShaqGUI

Źródło **Strumień radiowy (cichy nasłuch)** przyjmuje adres HTTP/HTTPS
strumienia MP3, AAC lub HLS. Przycisk importu wczytuje PLS/M3U/M3U8;
jeżeli lista zawiera kilka stacji, użytkownik wybiera jedną. Lokalny manifest
HLS nie jest listą stacji: jego adres internetowy należy wkleić w pole radia.

Start uruchamia ciche rozpoznawanie i przenosi fokus na listę wyników.
Radio jest dekodowane bez otwierania urządzenia odtwarzającego. Można więc
monitorować stację bez dźwięku w głośnikach. Ograniczony bufor przechowuje
najwyżej 65 s PCM; po opóźnieniu rozpoznawania pobierana jest świeża próbka,
a po utracie połączenia nie są sklejane fragmenty sprzed i po przerwie.
Odbiornik ponawia połączenie i nadzoruje brak danych z dekodera.

Odsłuch ma osobne przyciski włączania i zatrzymywania oraz suwak 0–100%.
Jego głośność nie zmienia próbki wysyłanej do rozpoznania. Zatrzymanie odsłuchu
pozostawia nasłuch, a zatrzymanie nasłuchu pozwala nadal słuchać radia.
Adres i głośność są zapamiętywane; odsłuch nie uruchamia się sam po restarcie.
Zmiana stanu przycisków nie przesuwa fokusu na suwak, a opóźnione zakończenie
odsłuchu nie odbiera fokusu kontrolce wybranej w międzyczasie.

W ustawieniach zaawansowanych jest domyślnie wyłączony odczyt rozpoznania
oraz przycisk testowy. Wykonawca i tytuł są odczytywani tylko przy fokusie
na liście w aktywnym oknie. Kolejne dopasowania tego samego utworu nie są
odczytywane ponownie. Zaznaczenie listy pozostaje bez zmian.

Odczyt rozpoznania i zapis historii są osobnymi zdarzeniami. Lista pokazuje
**unikalne rozpoznania z bieżącego uruchomienia**, także utwory już obecne
w historii. Zapis do pliku nadal pomija duplikaty. Błąd zapisu pozostaje widoczny
w osobnym polu **Stan zapisu historii** i nie zatrzymuje nasłuchu. Jest
ogłaszany raz na serię niepowodzeń niezależnie od opcji odczytu tytułów
i fokusu; gdy przekazanie do czytnika się nie powiedzie, pojawia się dostępne
okno ostrzeżenia. Zwykłe statusy i rozpoznanie znanego utworu nie kasują
ostrzeżenia. Znika ono dopiero po rzeczywistym, udanym zapisie nowego wpisu.
Odczyt tytułu może przekazać również utwór już obecny w historii.

Informacje o łączeniu, rozpoczęciu nasłuchu, błędzie, odzyskaniu transmisji
i zatrzymaniu są przekazywane do czytnika niezależnie od opcji odczytu tytułów.
Kontrolki, statusy i błędy radia korzystają z `_STRINGS` i tłumacza `t()`.
Odbiornik przekazuje `RadioStatus` z rodzajem zdarzenia i czasem ponowienia;
interfejs nie ustala stanu po początku polskiego ani angielskiego tekstu.
Także awaria rozpoznawania ma osobny rodzaj zdarzenia.

## Zależności i wielkość pliku

- Nowa zależność Windows: `accessible-output2==0.17`, z bibliotekami czytników
  i ich metadanymi licencyjnymi dołączanymi przez PyInstaller.
- NVDA i JAWS obsługiwane są przez Accessible Output 2. Dla ZDSR sprawdzane są
  wyniki wywołań API; preferowana jest biblioteka z zainstalowanego czytnika.
  Wyszukiwanie DLL obejmuje wyłącznie katalog instalacji ZDSR pod Program Files,
  z kontrolą ścieżki po rozwiązaniu dowiązań. Nazwa uruchomionego procesu
  nie służy do wskazywania biblioteki. Przy braku instalacji pozostaje wersja
  dołączona do Accessible Output 2. Nie wymaga to kodu nasłuchu procesu.
- Powiadomienia Windows UI Automation stanowią ścieżkę dla Narratora,
  gdy nie zostanie znaleziony aktywny czytnik obsługiwany przez bibliotekę.
- FFmpeg jest dołączony do `shaqgui.exe`, tak jak wcześniej do ShaqFileGUI.
  Instalacja systemowego FFmpeg nie jest wymagana. Jego brak w niepełnej
  paczce daje czytelny komunikat tylko przy korzystaniu z radia.
- Odsłuch używa istniejących `soundcard`, `numpy` i `wxPython`.

Dołączenie FFmpeg zwiększa `shaqgui.exe` z około **32 do 129 MB**, jak
odnotowano podczas przeglądu pierwszej paczki; dokładny rozmiar zależy od
wersji dekodera i bibliotek. To koszt samodzielnej obsługi radia bez instalacji
dodatkowych narzędzi przez użytkownika. Nazwa EXE i numer **0.1.9** pozostają
bez zmian; numer następnego wydania ustala opiekun projektu.

## Weryfikacja i ograniczenia

Testy obejmują playlisty i błędne adresy, ograniczenia bufora, niezależność
odsłuchu, głośność, zatrzymanie i ponowne łączenie, tłumaczenia PL/EN,
ogłaszanie błędów i wznowienia, konfigurację oraz zachowanie fokusu.
Obejmują także trwałość i jednokrotne ogłaszanie błędu zapisu, brak jego
kasowania przez duplikaty oraz wybór DLL ZDSR wyłącznie z katalogu instalacji.
Lokalny serwer sprawdza rzeczywiste dekodowanie MP3, AAC i HLS przez FFmpeg,
HTTP 404, przerwaną transmisję, zawieszony odbiór i sprzątanie procesu dekodera.

`SHAQ_TEST_GUI=1` włącza testy wxPython, `SHAQ_TEST_RADIO=1` testy lokalnego
serwera z FFmpeg, a `SHAQ_TEST_UIA=1` rzeczywiste wywołanie powiadomienia
Windows. Testy automatyczne podmieniają konfigurację użytkownika.

Bieżący kod przekazał komunikat do uruchomionego NVDA: wywołanie zostało
przyjęte bez błędu. JAWS i ZDSR nie są tu uruchomione ani dostępne do pełnej
próby. Testy adapterów i przyjęcie powiadomienia przez
UI Automation nie zastępują odsłuchu z JAWS, ZDSR i Narratorem; takiego odsłuchu
nie oznaczono jako wykonanego. Nie wykonano całonocnego testu ciągłej pracy.
