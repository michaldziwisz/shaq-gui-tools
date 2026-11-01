# Nasłuch wybranego programu w ShaqGUI i ShaqCast

W źródłach dźwięku dostępny jest tryb **Program (wybrany proces)**.
Można wybrać uruchomiony odtwarzacz lub wskazać jego plik EXE, także gdy jest
zamknięty. Zapamiętywana jest pełna ścieżka, więc restart odtwarzacza i zmiana
PID nie usuwają wyboru. Program informuje o niedostępności odtwarzacza i po
naciśnięciu Start czeka na jego uruchomienie. Stop przerywa to oczekiwanie.

WASAPI przechwytuje wskazany proces wraz z jego podprocesami, bez dźwięków
niezależnych aplikacji, np. NVDA. Kilka niezależnych instancji tego samego EXE
wymaga pozostawienia jednej. Przeniesiony EXE trzeba wskazać ponownie.

Wybór sprawdza cały łańcuch przodków, także gdy pomiędzy dwoma procesami
odtwarzacza znajduje się proces pomocniczy o innej nazwie. Taki łańcuch
jest jednym drzewem; dwie niezależne instancje nadal wymagają wyboru jednej.
Brak rodzica w odczytanej liście, ponowne użycie PID lub cykl nie powodują
zgadywania pokrewieństwa ani zapętlenia. Analiza ma złożoność O(n).

Wymagany jest Windows w kompilacji co najmniej 20348, np. Windows 11.
Tryb nie instaluje sterowników i nie zastępuje niedostępnego procesu nasłuchem
całego wyjścia. Całkowite wyciszenie odtwarzacza może usunąć jego sygnał przed
przechwyceniem; funkcja nie odtwarza dźwięku, którego nie dostarcza system.

Kontrolki, komunikaty i błędy nasłuchu mają tłumaczenia polskie i angielskie,
wybierane przez istniejące ustawienie języka interfejsu. Lista nie jest
automatycznie odczytywana ani przebudowywana, gdy ma fokus. Przycisk odświeżania
pozostaje świadomym żądaniem aktualizacji.

Nie dodano zależności zewnętrznych; używane są `ctypes` oraz API Windows.
Moduły są dostępne w obu niezależnych pakietach. Test regresji sprawdza identyczną
zawartość ich kopii, łącznie z katalogiem tłumaczeń.

Testy obejmują konfigurację, zamknięty i ponownie uruchomiony proces,
niejednoznaczny wybór, błędne dane, ochronę fokusu, tłumaczenia oraz kontrolki
obu programów. `SHAQ_TEST_GUI=1` włącza testy wxPython, a
`SHAQ_TEST_PROCESS_AUDIO=1` rzeczywisty test izolacji WASAPI z krótkimi tonami.
Ustawienia użytkownika są zastępowane konfiguracją tymczasową podczas testów.
Testy drzewa obejmują także 1500 procesów pomocniczych, odwróconą kolejność
listy, brak przodka, ponowne użycie PID, cykl i niezależne procesy siostrzane.
