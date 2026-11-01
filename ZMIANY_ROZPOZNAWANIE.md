# Kontrolowane rozpoznawanie w trzech programach

Propozycja obejmuje wyłącznie klienta Shazama, ustawienia sygnatury,
ponowienia oraz informowanie o wynikach. Nie wymaga trybu procesu ani radia.

Sygnatura ma maksymalnie 12 sekund, także po odczycie starszej konfiguracji.
Domyślna próbka ShaqGUI pozostaje **15-sekundowa**. Zachowuje to możliwość
wybrania najgłośniejszego 12-sekundowego okna. Nie ma miarodajnego pomiaru,
który uzasadniałby skrócenie całej próbki do 12 s, więc tej zmiany nie zachowano.

Nowy klient wykonuje jedno zapytanie z limitem 15 s, bez ukrytych ponowień
wewnątrz shazamio. Stop anuluje oczekiwanie na rozpoznanie oraz pauzy.
Błędy HTTP, brak dopasowania i niepoprawna odpowiedź są rozróżniane.
Nowe komunikaty respektują polski lub angielski język interfejsu.

W ShaqFileGUI odpowiedź **HTTP 429** odkłada dokładne bajty okna wraz z jego
pozycją w pliku. Zadanie wraca do ograniczonej kolejki i po pauzie ponawia to
samo okno. Nie zwiększa licznika ukończonych próbek, błędów ani braku dopasowania.
Nie odczytuje ponownie pliku i nie gubi pozostałych okien tej próbki. Działa to
również przy nieznanej długości pliku. Globalna pauza uwzględnia Retry-After;
odłożone zadania pozostają oczekujące do ustąpienia limitu lub naciśnięcia Stop.
Każde żądanie ma skończony limit czasu, a wszystkie oczekiwania można przerwać.
Przy błędach przejściowych innych niż 429 przywrócono maksymalnie **6 prób**.

W ShaqGUI i ShaqCast pozostaje wykładnicza przerwa do **300 s**, z minimum
30 s przy HTTP 429 i respektowaniem dłuższego Retry-After. Wycofano skrócenie
górnego limitu do 30 s: brak pomiaru, który uzasadniałby większą częstotliwość
zapytań podczas długiego dławienia usługi. Jawna kontrola pozostaje, bez
wielokrotnych, ukrytych zapytań biblioteki.

Lista ShaqGUI ponownie pokazuje tylko **unikalne wpisy rzeczywiście zapisane**
do historii, zgodnie z etykietą. Rozpoznanie znanego utworu jest widoczne w
statusie „Rozpoznano” i „Ostatnie rozpoznanie”; nie oznacza ponownego zapisu.
Błąd zapisu pozostaje widoczny jako ostrzeżenie w statusie, bez zakończenia
nasłuchu. Po usunięciu przyczyny kolejne zapisy mogą się powieść.

Testy obejmują HTTP 429 przed sukcesem, kolejne limity, przerwanie Retry-After,
6 prób błędu przejściowego, trwały błąd HTTP 400, dokładność zachowanego okna
i licznika postępu, brak podwójnego zliczania 429, brak ponownego dekodowania
próbki, nieznaną długość pliku, błąd zapisu i listę unikalnych wyników.
Porównanie obu kopii `_recognition.py` zapobiega ich rozjechaniu.

Zakres `shazamio>=0.6,<0.9` pozostaje zgodny z konfiguracją projektu i jest
stosowany także w budowaniu przez GitHub Actions. Numer wersji ustala opiekun
projektu; nie zmieniono go w tej propozycji.
