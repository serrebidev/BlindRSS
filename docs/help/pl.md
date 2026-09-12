# Podręcznik użytkownika BlindRSS

## Podręcznik użytkownika BlindRSS {#user-guide}

BlindRSS to przyjazny dla czytników ekranu komputerowy klient RSS i podcastów. Odczytuje
kanały RSS i Atom, odtwarza załączniki podcastów i filmów oraz działa samodzielnie
lub z kontem hostowanym, takim jak Miniflux, Inoreader, The Old Reader albo
BazQux.

Ten podręcznik jest zapisany w aplikacji, dlatego działa bez połączenia z internetem
i bez przeglądarki internetowej. Aby go otworzyć, naciśnij F1 w dowolnym miejscu
BlindRSS. Jeżeli używana kontrolka, okno dialogowe, element menu lub okno ma własną
sekcję, F1 otwiera podręcznik w tej sekcji, a nie na początku.

Wszystko opisane tutaj jest dostępne z klawiatury. Korzystaj z listy treści, aby
przechodzić między sekcjami, albo z pola wyszukiwania, aby znaleźć słowo w dowolnym
miejscu podręcznika.

## Pierwsze kroki {#getting-started}

Przy pierwszym uruchomieniu BlindRSS nie ma żadnych kanałów. Możesz dodać je na
kilka sposobów:

- Naciśnij Ctrl+N, aby dodać kanał według adresu. Zobacz Dodawanie kanału.
- Naciśnij Ctrl+Shift+F, aby wyszukać katalogi podcastów i kanałów według nazwy.
  Zobacz Wyszukiwanie podcastów i kanałów RSS.
- Zaimportuj plik OPML wyeksportowany z innego czytnika. Zobacz Importowanie OPML.
- Zaimportuj archiwum YouTube Takeout, aby zasubskrybować wszystkie kanały, które
  już obserwujesz. Zobacz Importowanie archiwum YouTube Takeout.
- Zaloguj się do konta hostowanego w Narzędzia, Ustawienia, Dostawca, a BlindRSS
  odczyta subskrypcje znajdujące się już na tym koncie. Zobacz Konta online i
  dostawcy.

Gdy masz już kanały, naciśnij F5, aby je odświeżyć. Nowe artykuły pojawią się na
liście artykułów, a przy każdym kanale w drzewie będą widoczne liczby nieprzeczytanych.

Trzy miejsca, które warto odwiedzić na początku, to Narzędzia, Ustawienia (sposób
działania BlindRSS), Narzędzia, Skróty klawiaturowe (każde polecenie i jego klawisz)
oraz ten podręcznik.

## Główne okno {#main-window}

Główne okno ma cztery główne obszary oraz pasek menu i pasek stanu. Tab i
Shift+Tab przechodzą między nimi, a F6 przełącza panele w większości menedżerów okien.

- Drzewo kanałów i folderów po lewej stronie.
- Pole wyszukiwania nad listą artykułów.
- Lista artykułów.
- Panel czytania pod listą artykułów.

Pasek menu zawiera pozycje Plik, Edycja, Widok, Odtwarzacz, Narzędzia i Pomoc.
Naciśnij Alt, aby do niego przejść, a potem używaj klawiszy strzałek. Każdy element
menu ma klawisz dostępu w każdym języku interfejsu, a pasek menu zawija się na obu
końcach.

Rozmiary, wybrany kanał i stan okna są pamiętane między uruchomieniami.
„Zapamiętaj ostatnio wybrany kanał/folder podczas uruchamiania” w Ustawieniach,
Ogólne określa, czy BlindRSS otworzy ponownie kanał, który ostatnio czytałeś.

## Lista kanałów i folderów {#feed-tree}

Drzewo po lewej stronie zawiera kanały, grupujące je kategorie, Inteligentne
foldery, zapisane wyszukiwania oraz wbudowane widoki (Wszystkie kanały, Ulubione,
Usunięte artykuły i Kanały z błędami).

- Strzałki w górę i w dół przechodzą między elementami.
- Strzałka w prawo rozwija kategorię, strzałka w lewo ją zwija.
- Enter lub wybranie elementu ładuje jego artykuły na listę artykułów.
- F2 otwiera właściwości wybranego kanału lub kategorii.
- Klawisz Applications albo Shift+F10 otwiera menu kontekstowe.

Każdy kanał pokazuje liczbę nieprzeczytanych. Rozwinięte i zwinięte kategorie są
zapamiętywane, więc drzewo wygląda tak samo przy następnym uruchomieniu.

Kanały, których aktualizacja się nie powiodła, są nadal wyświetlane normalnie;
widok Kanały z błędami zbiera je, aby kanał, który po cichu przestał działać, nie
pozostał niezauważony.

## Lista artykułów {#article-list}

Lista artykułów pokazuje artykuły elementu wybranego w drzewie po zastosowaniu
bieżącego Filtru artykułów, kolejności sortowania i wyszukiwanego terminu.

- Strzałki w górę i w dół przechodzą między artykułami; panel czytania podąża za wyborem.
- Enter otwiera wybrany artykuł.
- Shift+Up i Shift+Down rozszerzają zaznaczenie, więc działania zbiorcze działają
  na kilku artykułach naraz.
- Backspace przełącza stan przeczytany/nieprzeczytany wybranego artykułu.
- Delete usuwa wybrane artykuły; Shift+Delete usuwa je bez pytania o potwierdzenie.
- Ctrl+D dodaje artykuł do ulubionych lub go z nich usuwa.
- Klawisz Applications albo Shift+F10 otwiera menu kontekstowe.

Kolumny, które są wyświetlane, oraz ich kolejność można konfigurować globalnie i
osobno dla każdego kanału. Zobacz Kolumny listy artykułów.

## Panel czytania {#reading-pane}

Panel czytania pod listą artykułów zawiera tekst wybranego artykułu. Jest to obszar
tekstu tylko do odczytu, więc czytnik ekranu może czytać go wiersz po wierszu,
słowo po słowie lub znak po znaku, a tekst można zaznaczać i kopiować.

- Ctrl+F wyszukuje w tekście artykułu.
- F3 i Shift+F3 przechodzą do następnego i poprzedniego dopasowania.
- Enter na łączu w tekście otwiera to łącze.

Sposób prezentowania tekstu można ustawić w Ustawienia, Kanały i artykuły:
nagłówki mogą być ogłaszane, elementy list oznaczane punktami i liczbami, cytaty
oznaczane, łącza wyświetlane z ich adresem, tabele opisywane, a tekst alternatywny
obrazów dołączany. Tekst alternatywny obrazów można także wymusić lub wyłączyć dla
jednego kanału w jego menu kontekstowym.

Jeżeli kanał publikuje tylko krótkie podsumowanie, BlindRSS może pobrać pełny tekst
artykułu. Zobacz Odzyskiwanie pełnego tekstu artykułu.

## Okno artykułu {#article-window}

Otwarcie artykułu może umieścić go w osobnym oknie zamiast w panelu czytania, co
daje artykułowi cały ekran i utrzymuje go otwartego, gdy przechodzisz dalej po liście.

Okno zawiera obszar tekstu tylko do odczytu z takim samym działaniem czytania,
zaznaczania i wyszukiwania w tekście jak panel czytania. Escape zamyka je.

## Pole wyszukiwania {#search-field}

Pole wyszukiwania nad listą artykułów filtruje bieżący widok w trakcie pisania,
a termin zatwierdzasz klawiszem Enter.

- Ctrl+E przenosi fokus do pola wyszukiwania.
- Enter stosuje termin.
- Escape albo przycisk wyczyść opróżnia pole i przywraca pełną listę.

Pole wyszukiwania można ukryć, jeśli nigdy z niego nie korzystasz; menu Widok
zawiera polecenie Pokaż/ukryj pole wyszukiwania. To, czy wyszukiwanie dopasowuje
tylko tytuły czy tytuły i tekst artykułów, ustawia się w Ustawienia, Kanały i
artykuły, w opcji „Dopasowania wyszukiwania”.

Wyszukiwanie, które chcesz zachować, można przekształcić w zapisane wyszukiwanie,
które pozostanie w drzewie. Zobacz Trwałe wyszukiwania.

## Pasek stanu {#status-bar}

Pasek stanu na dole głównego okna ma trzy pola:

- Przemijające komunikaty, na przykład liczbę artykułów dopasowanych przez filtr.
- Działanie w tle, na przykład odświeżanie kanału lub pobieranie w toku.
- Stan odtwarzania: co jest odtwarzane oraz czas, który upłynął i pozostał.

Są one celowo oddzielone, aby komunikat odświeżania nie mógł nadpisać liczby
wyników wyszukiwania podczas jej odczytywania.

## Menu kontekstowe {#context-menus}

Drzewo kanałów i lista artykułów mają własne menu kontekstowe, otwierane klawiszem
Applications albo Shift+F10. Zawierają one polecenia odnoszące się do wybranego
elementu — odświeżanie, oznaczanie jako przeczytane, edytowanie, usuwanie,
kopiowanie łączy, dodawanie multimediów do kolejki itd.

Menu kontekstowe również obsługuje F1: gdy element jest podświetlony, F1 otwiera
sekcję tego podręcznika, która go objaśnia.

## Dodawanie kanału {#adding-feeds}

Plik, Dodaj kanał (Ctrl+N) subskrybuje kanał według adresu.

Wklej lub wpisz adres kanału albo samej witryny — gdy adres nie jest kanałem,
BlindRSS szuka kanału na stronie. Możesz również wkleić adres kanału lub playlisty
YouTube, profil Mastodon lub Bluesky, społeczność PieFed lub Lemmy, stronę
SoundCloud lub Mixcloud albo adres Reddit czy Groups.io, a BlindRSS przekształci
go w kanał.

Wybierz kategorię, do której kanał ma trafić, albo pozostaw go bez kategorii.
Opcja „Otwórz w widoku HTML” sprawia, że artykuły z tego kanału są domyślnie
otwierane w widoku bogatym.

Jeśli nie znasz adresu, użyj zamiast tego Wyszukiwania podcastów i kanałów RSS.

## Wykrywanie kanałów na stronie {#detect-feeds}

Plik, Wykryj kanały na stronie przyjmuje adres zwykłej strony internetowej i
wyświetla kanały reklamowane przez tę stronę, dzięki czemu możesz je subskrybować
bez samodzielnego szukania łącza kanału.

To właściwe polecenie, gdy witryna ma łącze „subskrybuj” lub „RSS”, do którego
trudno dotrzeć, albo gdy strona oferuje kilka kanałów (wszystkie wpisy, jedna
kategoria, komentarze) i chcesz wybrać jeden z nich.

## Wyszukiwanie podcastów i kanałów RSS {#find-podcast}

Narzędzia, Znajdź podcast lub kanał RSS (Ctrl+Shift+F) przeszukuje katalogi
podcastów i kanałów według nazwy, tematu lub adresu witryny, dzięki czemu możesz
subskrybować bez znajomości adresu kanału.

1. Wpisz w polu wyszukiwania szukaną rzecz — nazwę podcastu, temat albo adres
   witryny.
2. Wybierz źródło albo pozostaw „Wszystkie źródła”.
3. Naciśnij Enter lub przycisk Szukaj.
4. Przechodź strzałkami po liście wyników. Każdy wiersz pokazuje tytuł, katalog,
   z którego pochodzi, oraz szczegóły.
5. Naciśnij Enter na wyniku albo wybierz OK, aby go subskrybować.

Wyszukiwania są wykonywane w kilku katalogach naraz, a wyniki pojawiają się w
miarę odpowiedzi każdego z nich, więc lista rośnie podczas jej czytania. Escape
zamyka okno dialogowe i zatrzymuje wyszukiwanie.

## Katalogi podcastów i kanałów {#podcast-directories}

Pole Źródło w oknie Znajdź podcast lub kanał RSS wybiera miejsce wyszukiwania.
Oprócz „Wszystkie źródła”, „Wszystkie źródła podcastów” i „Wszystkie źródła
kanałów RSS” poniższe katalogi są dostępne osobno:

- Katalogi podcastów: iTunes (Apple Podcasts), gPodder, fyyd, Podverse,
  SoundCloud i Mixcloud.
- Katalogi kanałów: NewsBlur, Feedspot, Google News, Bing News i Feedly.
- Wyszukiwanie witryn i społeczności: YouTube, Reddit, Groups.io i Fediverse —
  Mastodon, Bluesky, PieFed oraz Lemmy lub Kbin, które także można wybierać osobno.
- Wykrywanie na podstawie adresu: Feedsearch oraz własne skanowanie witryny przez
  BlindRSS, które pobiera witrynę i szuka w niej kanałów.

Nie opieramy się na pojedynczym katalogu. Wyszukanie „Wszystkie źródła” odpytuje
łącznie grupy podcastów i RSS oraz scala wyniki, utrzymując szerokie kanały zapytań
Google News poniżej bezpośrednich dopasowań kanałów.

## Subskrybowanie wyniku wyszukiwania {#subscribing}

W dowolnym oknie dialogowym wyszukiwania — Znajdź podcast lub kanał RSS,
Wyszukiwanie filmów albo przycisk znajdowania w Archiwum podcastów — naciśnięcie
Enter na wyniku albo wybranie OK przy zaznaczonym wyniku powoduje jego subskrypcję.

BlindRSS najpierw rozwiązuje wynik do rzeczywistego adresu kanału, dlatego
subskrybowanie podcastu znalezionego w katalogu, kanału YouTube lub konta Fediverse
działa tak samo. Nowy kanał pojawia się w drzewie i jest od razu odświeżany.

Jeśli chcesz umieścić go w konkretnej kategorii, przenieś go później z jego menu
kontekstowego lub z Właściwości kanału.

## Archiwum podcastów {#podcast-archive}

Narzędzia, Archiwum podcastów przegląda pełną historię odcinków podcastu — zarówno
odcinki nadal znajdujące się w jego kanale, jak i starsze odzyskane przez BlindRSS —
i pobiera je partiami.

Wiele kanałów podcastów publikuje tylko najnowsze odcinki. Odzyskiwanie archiwum
działa automatycznie w tle; w tym oknie widzisz jego stan, możesz uruchomić je
ręcznie ponownie i pobrać to, co znalazło.

- Wybierz podcast w polu Podcast.
- Filtruj odcinki zawęża listę podczas pisania.
- Przeskanuj archiwum ponownie uruchamia odzyskiwanie dla tego podcastu.
- Znajdź lub dodaj podcast otwiera wyszukiwanie kanałów, aby można było
  zarchiwizować podcast, którego jeszcze nie subskrybujesz.
- Odtwórz odtwarza wybrany odcinek, Pobierz zaznaczone go pobiera, a Pobierz
  wszystko pobiera całą widoczną listę.
- Anuluj pobieranie zatrzymuje trwające pobieranie wsadowe.

Okno pozostaje otwarte podczas pobierania partii, więc możesz dalej czytać.

## Wyszukiwanie filmów {#video-search}

Narzędzia, Wyszukiwanie filmów przeszukuje za jednym razem każdą witrynę, którą
może odpytać yt-dlp, i pozwala odtwarzać, kolejkować albo subskrybować znalezione elementy.

- Wpisz wyszukiwany termin i naciśnij Enter albo przycisk Szukaj.
- Pole zakresu ogranicza wyszukiwanie do jednej witryny; domyślnie przeszukiwane są wszystkie.
- Wyniki przychodzą w miarę odpowiedzi witryn, najpierw z popularnych witryn. Tytuły
  przychodzące jako symbole zastępcze są uzupełniane po ich rozwiązaniu.
- Wczytaj więcej wyników pobiera kolejną partię z każdej witryny.
- Sortowanie według nagłówka kolumny zmienia kolejność otrzymanych wyników.

Identyczne filmy znalezione w kilku witrynach są scalane w jeden wiersz. Witryny
dla dorosłych są wykluczone, chyba że w Ustawienia, Zaawansowane włączysz opcję
„Włącz witryny dla dorosłych w wyszukiwaniu filmów”.

## Otwieranie artykułu według adresu URL {#open-article-url}

Plik, Otwórz artykuł przyjmuje adres dowolnej strony internetowej i czyta go w
BlindRSS jak artykuł — jako wyodrębniony tekst w panelu czytania, z tymi samymi
opcjami czytania co wszystkie pozostałe elementy.

Użyj go dla pojedynczej strony, którą ktoś ci przesłał, bez subskrybowania
czegokolwiek. Jeżeli strona jest wątkiem forum lub dyskusji, BlindRSS odczyta cały
wątek. Zobacz Wątki forów i dyskusji.

## Otwieranie adresu URL multimediów {#open-media-url}

Plik, Otwórz adres URL multimediów odtwarza dźwięk lub wideo spod adresu we
wbudowanym odtwarzaczu bez subskrybowania czegokolwiek.

Przyjmuje bezpośrednie łącza do multimediów i adresy stron, które może rozwiązać
yt-dlp — YouTube, Rumble, Odysee, SoundCloud i wiele innych. Wynik jest odtwarzany
jak każdy inny element i można dodać go do kolejki odtwarzania.

## Usuwanie kanału {#removing-feeds}

Plik, Usuń kanał anuluje subskrypcję wybranego kanału. To samo polecenie znajduje
się w menu kontekstowym kanału.

Usunięcie kanału usuwa jego artykuły z bazy danych. Nie wpływa na nic, co zostało
już pobrane na dysk. Jeżeli używasz dostawcy hostowanego, anulowanie subskrypcji
jest także wysyłane do tego konta.

Aby usunąć całą kategorię wraz ze wszystkim, co zawiera, użyj Usuń kategorię i
kanały z menu kontekstowego kategorii. Zobacz Kategorie i podkategorie.

## Właściwości kanału {#feed-properties}

F2 albo Edytuj kanał w menu kontekstowym otwiera właściwości wybranego kanału.

- Jego tytuł, który możesz zastąpić; „Przywróć domyślny tytuł kanału” w menu
  kontekstowym przywraca własny tytuł kanału.
- Jego adres i kategorię, do której należy.
- To, czy nowe artykuły z niego wywołują powiadomienie.
- To, czy otwiera się w bogatym widoku HTML.
- Własny układ kolumn listy artykułów na karcie Nagłówki listy, zastępujący układ globalny.

Wyświetl opis kanału w menu kontekstowym listy artykułów pokazuje opis publikowany
przez sam kanał.

## Kategorie i podkategorie {#categories}

Kategorie grupują kanały w drzewie i mogą być zagnieżdżone: kategoria może zawierać
zarówno kanały, jak i dalsze podkategorie.

- Plik, Dodaj kategorię tworzy kategorię.
- Dodaj podkategorię w menu kontekstowym kategorii tworzy ją wewnątrz tej kategorii.
- Edytuj kategorię zmienia jej nazwę lub ją przenosi. Zobacz Właściwości kategorii.
- Usuń kategorię usuwa kategorię, lecz zachowuje jej kanały.
- Usuń kategorię i kanały usuwa kategorię i anuluje subskrypcję wszystkiego,
  co się w niej znajduje.
- Importuj OPML tutaj importuje plik bezpośrednio do tej kategorii.
- Eksportuj kategorię do OPML eksportuje tylko tę gałąź.

Niektórzy dostawcy hostowani przechowują kategorie na jednej płaskiej liście. Gdy
tak jest, BlindRSS informuje o tym, a opcje „przenieś do elementu nadrzędnego” są niedostępne.

## Właściwości kategorii {#category-properties}

Edytuj kategorię otwiera właściwości kategorii: jej nazwę i kategorię nadrzędną,
w której się znajduje.

Zmiana nazwy kategorii zachowuje wszystkie jej kanały. Przeniesienie jej przenosi
całą gałąź, włącznie z podkategoriami.

## Odświeżanie kanałów {#refreshing}

- F5 odświeża każdy kanał.
- Ctrl+F5 odświeża tylko wybrany kanał lub kategorię.
- Shift+F5 zatrzymuje trwające odświeżanie.
- Odśwież kategorię w menu kontekstowym kategorii odświeża tę gałąź.

Tylko jedno z poleceń Odśwież kanały i Zatrzymaj odświeżanie jest dostępne w
danym momencie, więc polecenie klawiaturowe odpowiada temu, co oferuje menu.
Postęp pojawia się w drugim polu paska stanu.

Automatyczne odświeżanie konfiguruje się w Ustawienia, Kanały i artykuły: interwał,
liczbę kanałów odświeżanych naraz, liczbę połączeń na hosta, limit czasu dla kanału
i liczbę ponawiania nieudanego kanału. „Automatycznie odśwież kanały przy
uruchamianiu” odświeża wszystko przy starcie, a opcja obciążenia uruchamiania pozwala
wybrać między użyciem pamięci podręcznej a wymuszeniem pełnego odświeżenia.

## Kanały z błędami {#feed-errors}

Widok Kanały z błędami oraz Plik, Wyświetl błędy kanałów zawierają listę kanałów,
których ostatnia aktualizacja się nie powiodła, wraz z przyczyną.

Kanał, który po cichu przestał działać, wygląda dokładnie jak kanał bez nowych
artykułów, dlatego ten widok istnieje. Możesz z niego:

- Odświeżyć zaznaczone, aby spróbować ponownie teraz.
- Skopiować szczegóły, aby umieścić tekst błędu w schowku.
- Otworzyć właściwości kanału, aby poprawić adres.
- Usunąć kanał, gdy zniknął na dobre.

Typowe przyczyny to przeniesiony lub wycofany kanał, witryna wymagająca teraz
sprawdzenia przeglądarki (zobacz Importowanie ciasteczek witryny) oraz tymczasowa
awaria serwera.

## Importowanie OPML {#import-opml}

OPML to standardowy format pliku z listą subskrypcji kanałów. Każdy czytnik
kanałów może taki plik eksportować, dlatego przez OPML przenosisz subskrypcje z
innego czytnika do BlindRSS bez dodawania ich pojedynczo.

Plik, Importuj OPML prosi o plik i dodaje wszystkie kanały z niego, zachowując
opisaną w nim strukturę kategorii. Kanały, które już subskrybujesz, nie są dublowane.

Importuj OPML tutaj w menu kontekstowym kategorii umieszcza cały import w tej
kategorii zamiast na najwyższym poziomie.

Aby uzyskać plik OPML z innego czytnika, poszukaj w jego ustawieniach opcji
„Eksportuj”, „Kopia zapasowa” albo „Subskrypcje”.

## Eksportowanie OPML {#export-opml}

Plik, Eksportuj OPML zapisuje wszystkie twoje subskrypcje wraz z kategoriami do
pliku OPML.

Użyj go do utworzenia kopii zapasowej subskrypcji, przeniesienia ich do innego
czytnika lub na inną maszynę albo udostępnienia zestawu kanałów komuś innemu.
Eksportuj kategorię do OPML w menu kontekstowym kategorii eksportuje tylko tę gałąź.

## Importowanie archiwum YouTube Takeout {#import-youtube-takeout}

Google Takeout to usługa eksportu danych Google. Archiwum YouTube Takeout to plik
ZIP zawierający dane YouTube, w tym listę subskrybowanych kanałów. Plik, Importuj
YouTube Takeout odczytuje ten ZIP i subskrybuje te kanały jako kanały RSS, dzięki
czemu nowe filmy każdego kanału trafiają jako artykuły.

Aby uzyskać archiwum:

1. Przejdź do takeout.google.com i zaloguj się na konto Google, na którym masz
   subskrypcje YouTube.
2. Wybierz „Odznacz wszystko”, a następnie zaznacz tylko YouTube i YouTube Music.
3. W „Uwzględniono wszystkie dane YouTube” pozostaw co najmniej „subskrypcje”;
   „historia” i „playlisty” są opcjonalne, a BlindRSS także może ich użyć.
4. Wyeksportuj dane jeden raz jako plik ZIP i poczekaj na wiadomość e-mail Google —
   duże archiwum może wymagać wielu godzin.
5. Pobierz ZIP i wskaż go temu poleceniu.

BlindRSS pokazuje następnie znalezione dane pogrupowane według źródła i pozwala
wybrać grupy do zaimportowania:

- Subskrypcje: obserwowane kanały.
- Historia: kanały, które oglądałeś, lecz których nie obserwujesz.
- Twoje własne kanały.
- Playlisty jako samodzielne kanały.

Zduplikowane adresy są usuwane, więc późniejsze zaimportowanie drugiego archiwum
dodaje tylko nowe elementy. ZIP nigdy nie jest rozpakowywany na dysk; odczytywane
są wyłącznie małe pliki danych w nim zawarte.

## Trwałe wyszukiwania {#persistent-search}

Trwałe wyszukiwanie to termin wyszukiwania, który pozostaje w drzewie jako własny
element, dzięki czemu pasujące artykuły są zawsze dostępne po jednym naciśnięciu strzałki.

Narzędzia, Konfiguruj trwałe wyszukiwanie zarządza listą: Dodaj tworzy wyszukiwanie
z terminu, a Usuń je usuwa. Każde zapisane wyszukiwanie pojawia się w drzewie i
jest oceniane ponownie, gdy je wybierzesz, więc zawsze odzwierciedla bieżące artykuły.

Użyj go dla tematu śledzonego we wszystkich kanałach — nazwiska osoby, produktu
albo miejsca. Dla czegokolwiek bardziej złożonego niż fraza użyj Inteligentnych folderów.

## Inteligentne foldery {#smart-folders}

Inteligentny folder to folder w drzewie, którego zawartość określa reguła, a nie
kanał, z którego pochodzi artykuł.

Nowy inteligentny folder w menu kontekstowym drzewa otwiera edytor reguł. Reguła
to zestaw warunków połączonych przez „dopasuj wszystkie” (i) lub „dopasuj dowolny”
(lub), a grupy warunków mogą być zagnieżdżane, więc można wyrazić „(A i B) lub C”.

Warunki sprawdzają te pola:

- Pola tak/nie: przeczytany, ulubiony, otwarty, zaktualizowany.
- Pola tekstowe: tytuł, treść, opis, autor, kanał, url i tag — kategorie lub
  tagi publikowane przez samą witrynę.

Warunki tekstowe używają operatorów zawiera, nie zawiera, równa się albo zaczyna się od.

Inteligentne foldery nigdy niczego nie przenoszą ani nie kopiują; są widokiem
artykułów, które już masz. Aby zmieniać artykuły w chwili ich nadejścia, użyj Reguł filtrowania.

## Reguły filtrowania {#filter-rules}

Narzędzia, Reguły filtrowania to mechanizm sortowania artykułów BlindRSS. Reguły
działają na przychodzących artykułach tak, jak filtry poczty działają na przychodzącej poczcie.

Każda reguła łączy warunek — ten sam edytor reguł, którego używają Inteligentne
foldery — z zestawem działań:

- Przenieś artykuł do kategorii.
- Oznacz go także kategorią, pozostawiając go w dotychczasowym miejscu.
- Oznacz go jako przeczytany.
- Oznacz go jako ulubiony.
- Usuń go zgodnie ze skonfigurowanym zachowaniem usuwania.
- Pomiń powiadomienie o nowym artykule.

Reguły działają w kolejności listy, a każda włączona pasująca reguła wnosi swoje
działania. Reguła oznaczona jako zatrzymująca kończy potok dla artykułu po dopasowaniu,
więc późniejsze reguły go nie widzą. Przesuwaj reguły w górę i w dół, aby określić,
która ma pierwszeństwo.

Reguła bez działań nic nie robi i jest odrzucana, więc niedokończona reguła nie
może po cichu pochłaniać artykułów.

## Filtr artykułów {#article-filter}

Widok, Filtr artykułów ogranicza każdy widok według stanu przeczytania i tego,
czy artykuł ma załączone multimedia. Obie grupy łączą się.

- Ctrl+1: wszystkie artykuły.
- Ctrl+2: tylko nieprzeczytane.
- Ctrl+3: tylko przeczytane.
- Ctrl+4: multimedia i inne artykuły.
- Ctrl+5: tylko z multimediami.
- Ctrl+6: tylko bez multimediów.

Filtr stosuje się do każdego elementu wybranego w drzewie, w tym Inteligentnych
folderów i zapisanych wyszukiwań, oraz jest pamiętany między uruchomieniami.
„Tylko z multimediami” to najszybszy sposób na zamianę mieszanego kanału w listę podcastów.

## Sortowanie artykułów {#sorting}

Widok, Sortuj według porządkuje listę artykułów według daty, nazwy, autora, opisu,
kanału lub stanu. Rosnąco przełącza kierunek; domyślnie najnowsze są pierwsze.

Sortowanie dotyczy każdego widoku i jest pamiętane między uruchomieniami. Sortowanie
według kanału jest przydatne w widoku Wszystkie kanały i w Inteligentnych folderach,
gdzie artykuły pochodzą z wielu źródeł naraz.

## Kolumny listy artykułów {#list-headers}

Kolumny na liście artykułów, ich kolejność i szerokości możesz wybrać samodzielnie.
Ustawienia, Nagłówki listy ustawia układ globalny; karta Nagłówki listy własnego
kanału zastępuje go dla tego kanału, a „Użyj globalnego układu kolumn” wyłącza
to zastąpienie.

Mniej kolumn oznacza mniej informacji odczytywanych przez czytnik ekranu w każdym
wierszu, więc warto usunąć wszystkie, których nigdy nie używasz.

## Otwieranie artykułów {#opening-articles}

Enter na artykule z listy otwiera go. W zależności od artykułu i ustawień oznacza
to panel czytania, osobne okno albo bogaty widok HTML.

- Otwórz artykuł w menu kontekstowym robi to samo.
- Otwórz w przeglądarce przekazuje adres artykułu systemowej przeglądarce internetowej.
- Otwórz dostępną przeglądarkę odczytuje stronę w BlindRSS. Zobacz Dostępna przeglądarka.

Otwarcie artykułu oznacza go jako przeczytany, chyba że zmieniono to zachowanie.

## Przeczytane i nieprzeczytane artykuły {#read-status}

- Backspace albo Przełącz przeczytany/nieprzeczytany zmienia stan wybranego artykułu.
- Ctrl+Shift+R oznacza jako przeczytane wszystko w bieżącym widoku.
- Oznacz wszystkie elementy jako przeczytane w menu kontekstowym kanału lub kategorii
  robi to samo dla tej gałęzi.
- Oznacz jako przeczytane i Oznacz jako nieprzeczytane w menu kontekstowym listy
  artykułów działają na całym zaznaczeniu i mówią, ilu artykułów dotyczą.

Liczby nieprzeczytanych pojawiają się przy każdym kanale w drzewie. Filtr artykułów
może całkowicie ukryć przeczytane artykuły.

## Ulubione {#favorites}

Ctrl+D dodaje wybrany artykuł do Ulubionych albo usuwa go z nich, jeśli już tam jest.
Widok Ulubione w drzewie zawiera wszystko, co oznaczyłeś.

Ulubione pozostają mimo zasad przechowywania: oznaczony gwiazdką artykuł nie jest
usuwany podczas czyszczenia starszych artykułów. Ulubiony może być również warunkiem
w Inteligentnych folderach i Regułach filtrowania.

## Usunięte artykuły {#deleted-articles}

To, co robi Delete, konfiguruje się w Ustawienia, Ogólne, w opcji „Gdy usuwam artykuł”:

- Przeniesienie go do Usuniętych artykułów, skąd można go przywrócić.
- Usunięcie go na stałe.
- Przeniesienie go do wskazanej kategorii.

Przy pierwszym ustawieniu widok Usunięte artykuły w drzewie zawiera usunięte elementy,
Przywróć umieszcza artykuł z powrotem, a usunięcie go z tego widoku usuwa go na dobre.

„Potwierdź przed usunięciem artykułów” steruje monitem o potwierdzenie.
Shift+Delete zawsze go pomija.

## Odzyskiwanie pełnego tekstu artykułu {#full-text}

Wiele kanałów publikuje tylko nagłówek i jedno lub dwa zdania. BlindRSS może pobrać
stronę artykułu i wyodrębnić właściwy tekst, dzięki czemu panel czytania pokazuje
cały artykuł zamiast zajawki.

Dzieje się to automatycznie w tle podczas przechodzenia po liście, a wynik jest
zapisywany w pamięci podręcznej. „Buforuj pełny tekst w tle” w Ustawienia,
Kanały i artykuły pobiera wcześniej artykuły wokół twojej pozycji, aby przejście
w dół listy nie czekało na sieć.

Jeśli witryny w ogóle nie da się odczytać, zwykle stoi za sprawdzeniem przeglądarki.
Zobacz Importowanie ciasteczek witryny.

## Bogaty widok pełnego tekstu {#rich-view}

Ctrl+Shift+H przełącza panel czytania na bogaty widok HTML, który renderuje artykuł
tak jak przeglądarka, z nagłówkami, listami, tabelami i łączami jako rzeczywistymi
elementami, po których czytnik ekranu może nawigować własnymi poleceniami strukturalnymi.

Widok zwykłego tekstu jest domyślny, ponieważ działa szybciej i nigdy nie zaskakuje.
Bogaty widok jest wart użycia dla artykułów, których struktura niesie znaczenie.

Kanał można ustawić tak, aby zawsze otwierał się w bogatym widoku z jego Właściwości
kanału, a łącza w bogatym widoku otwierają się w przeglądarce systemowej, a nie wewnątrz widoku.

## Dostępna przeglądarka {#accessible-browser}

Widok, Otwórz dostępną przeglądarkę otwiera stronę w BlindRSS w oknie zbudowanym
do czytania przez czytnik ekranu, zamiast przekazywać ją systemowej przeglądarce.

Jest to właściwe narzędzie dla strony, którą trzeba przeczytać, a nie obsłużyć, oraz
dla witryn, których własny interfejs jest trudny w nawigacji. Współdzieli ustawienia
ciasteczek i identyfikacji przeglądarki BlindRSS, więc strony za sprawdzeniem
przeglądarki także otwierają się tutaj po zaimportowaniu dla nich ciasteczek.

## Filmy YouTube {#youtube}

Adres kanału lub playlisty YouTube można subskrybować tak jak każdy kanał. Filmy
trafiają wtedy jako artykuły, z opisem, transkrypcją i listą rozdziałów w tekście,
więc film można czytać zamiast oglądać.

Odtwarzanie odbywa się przez yt-dlp. Ustawienia, YouTube nim sterują:

- Plik ciasteczek, który umożliwia BlindRSS oglądanie dostępnych dla ciebie filmów
  z ograniczeniem wieku i tylko dla członków. Można go zaimportować bezpośrednio
  z przeglądarki albo automatycznie pobierać z eksportów cookies.txt w folderze Pobrane.
- „Odtwarzaj YouTube po uprzednim pobraniu”, co uruchamia się wolniej, ale działa
  znacznie pewniej.
- Folder pamięci podręcznej odtwarzania i jego maksymalny rozmiar wraz z przyciskiem
  pozwalającym go wyczyścić.

Import YouTube Takeout subskrybuje wszystkie kanały, które już obserwujesz, w jednym kroku.

## Wątki forów i dyskusji {#forums}

Reddit, Lemmy, Groups.io i Google Groups są odczytywane jako całe wątki, a nie po
jednym wpisie: otwarcie dyskusji daje pierwotny wpis i odpowiedzi w jednym ciągłym
fragmencie tekstu, co jest znacznie szybsze do czytania niż śledzenie wątku w przeglądarce.

Subskrybowanie działa tak samo jak w przypadku każdego kanału — wklej adres subreddita,
społeczności lub grupy. Repozytoria GitHub są obsługiwane tak samo, podobnie jak konta
i społeczności Mastodon, Bluesky oraz PieFed.

## Wytnij, kopiuj i wklej {#clipboard}

Menu Edycja zawiera standardowe polecenia schowka — Wytnij (Ctrl+X), Kopiuj
(Ctrl+C), Wklej (Ctrl+V) i Zaznacz wszystko (Ctrl+A) — działające w każdym polu
tekstowym i w panelu czytania.

BlindRSS dodaje polecenia kopiujące znane mu elementy:

- Kopiuj łącze — adres artykułu.
- Kopiuj łącze multimediów — adres jego dźwięku lub filmu.
- Kopiuj tekst — tekst artykułu odczytywany w panelu czytania.
- Kopiuj URL kanału — adres wybranego kanału.
- Kopiuj łącze obrazu — przy artykule z obrazem.

## Wbudowany odtwarzacz {#player}

BlindRSS sam odtwarza załączniki podcastów i filmów przez VLC, dlatego odtwarzanie
nigdy nie opuszcza aplikacji. Ctrl+Shift+P pokazuje lub ukrywa okno odtwarzacza,
a odtwarzanie trwa w obu przypadkach.

Odtwarzanie jest usprawniane przez lokalny serwer proxy z pamięcią podręczną zakresów,
dlatego przewijanie długiego odcinka jest szybkie nawet przy wolnym połączeniu.
Strumienie wymagające rozwiązania — YouTube, Rumble, Odysee — najpierw przechodzą przez yt-dlp.

„Pokaż okno odtwarzacza podczas rozpoczynania odtwarzania” w Ustawienia,
Odtwarzacz multimediów określa, czy okno pojawia się samo po rozpoczęciu odtwarzania.

## Sterowanie odtwarzaczem {#player-controls}

Okno odtwarzacza zawiera w kolejności tabulacji: stan odtwarzania, suwak pozycji,
czas, który upłynął, i całkowity, przyciski przewijania wstecz i do przodu, pole
prędkości, przycisk rozdziałów oraz suwak głośności. Każdy z nich jest dostępny
i obsługiwalny z klawiatury oraz ogłasza bieżącą wartość.

- Ctrl+P odtwarza i wstrzymuje.
- Ctrl+S zatrzymuje.
- Ctrl+Left i Ctrl+Right przewijają wstecz i do przodu oraz powtarzają działanie
  podczas przytrzymania. W systemie macOS Option+Left i Option+Right robią to samo,
  ponieważ Ctrl+Left i Ctrl+Right należą tam do Mission Control.
- Ctrl+Up i Ctrl+Down zmieniają głośność.

Klawisze przewijania i głośności działają z dowolnego miejsca BlindRSS podczas
odtwarzania, również wewnątrz okna dialogowego, więc nie trzeba szukać okna
odtwarzacza, aby wstrzymać odtwarzanie.

## Skróty klawiaturowe odtwarzacza {#player-shortcuts}

- Ctrl+Shift+P: pokaż lub ukryj okno odtwarzacza.
- Ctrl+P: odtwórz albo wstrzymaj.
- Ctrl+S: zatrzymaj.
- Ctrl+Left i Ctrl+Right: przewiń wstecz i do przodu (Option+Left i
  Option+Right w systemie macOS).
- Ctrl+Up i Ctrl+Down: zwiększ i zmniejsz głośność.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: szybciej, wolniej, powrót do normalnej
  prędkości.
- Ctrl+Shift+E: korektor.
- Ctrl+Shift+C: kolejka odtwarzania.
- Ctrl+Shift+T i Ctrl+Shift+V: następny i poprzedni element w kolejce.

Wszystkie te skróty można zmienić w Narzędzia, Skróty klawiaturowe. Polecenia
prędkości celowo domyślnie używają liter, a nie Ctrl+Shift+digit ani
Ctrl+Shift+period, ponieważ Windows i niektóre dodatki NVDA przechwytują je,
zanim zobaczy je jakakolwiek aplikacja.

## Prędkość odtwarzania {#playback-speed}

Odtwarzacz, Prędkość odtwarzania zmienia tempo odtwarzania multimediów od połowy
do trzykrotnej prędkości, z zachowaniem wysokości dźwięku.

- Ctrl+Shift+U przyspiesza, Ctrl+Shift+D zwalnia, Ctrl+Shift+N przywraca 1x.
- Podmenu ma stałe kroki: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x
  i 3x.
- Okno odtwarzacza ma pole prędkości, które możesz ustawić bezpośrednio.

„Domyślna prędkość odtwarzania” w Ustawienia, Odtwarzacz multimediów ustawia
prędkość, od której rozpoczyna się każde odtwarzanie.

## Korektor {#equalizer}

Ctrl+Shift+E albo Odtwarzacz, Korektor otwiera dziesięciopasmowy korektor z przedwzmacniaczem.

- „Włącz korektor” włącza i wyłącza całość.
- Każde pasmo jest suwakiem ogłaszającym wzmocnienie podczas zmiany.
- Zapisz jako ustawienie wstępne zapisuje bieżące pasma pod nazwą; Usuń ustawienie
  wstępne usuwa jedno z nich.
- Resetuj (Płasko) przywraca wszystkim pasmom wartość zero.

Korektor stosuje się do wszystkiego, co odtwarza BlindRSS, a jego ustawienie jest pamiętane.

## Rozdziały {#chapters}

Podcasty i filmy YouTube często zawierają rozdziały. Gdy odtwarzany element je ma,
Odtwarzacz, Rozdziały wyświetla je, a przejście do jednego z nich przewija do niego.

- Podmenu rozdziałów wypełnia się, gdy rozdziały elementu są znane, i mówi
  „Brak dostępnych rozdziałów”, kiedy ich nie ma.
- Okno odtwarzacza ma przycisk rozdziałów i pole rozdziałów.
- Łącza rozdziału w menu kontekstowym listy artykułów wyświetla łącza zawarte
  w opisie rozdziału.

Rozdziały są ładowane w tle podczas przechodzenia po liście, więc zwykle są gotowe
zanim naciśniesz odtwarzanie.

## Kolejka odtwarzania {#play-queue}

Kolejka odtwarzania to lista tego, co będzie odtwarzane następnie.

- Ctrl+Shift+C otwiera okno kolejki.
- Ctrl+Shift+T i Ctrl+Shift+V odtwarzają następny i poprzedni element.
- Dodaj do kolejki odtwarzania i Usuń z kolejki odtwarzania w menu kontekstowym
  listy artykułów ją zmieniają.

W oknie kolejki Odtwórz uruchamia wybrany element, Przenieś w górę i Przenieś w dół
zmieniają kolejność kolejki, Usuń usuwa jeden element, a Wyczyść wszystko ją opróżnia.
Kolejka pozostaje po ponownym uruchomieniu.

## Przesyłanie na inne urządzenia {#casting}

BlindRSS może wysyłać odtwarzane treści do urządzenia w twojej sieci: Chromecasta,
rendererów DLNA/UPnP oraz odbiorników AirPlay.

Wybierz urządzenie w oknie przesyłania; BlindRSS przesyła strumień przez własny
lokalny serwer proxy, więc urządzenie, które nie może samodzielnie pobrać pierwotnego
adresu, nadal odtworzy element. Sterowanie odtwarzaniem nadal działa z BlindRSS
podczas przesyłania.

## Pomijanie ciszy {#silence-skipping}

„Pomijanie ciszy (eksperymentalne)” w Ustawienia, Odtwarzacz multimediów wykrywa
ciche fragmenty podczas odtwarzania i pomija je, co zauważalnie skraca podcasty
mówione z długimi przerwami.

Analizuje dźwięk w trakcie odtwarzania, więc zużywa trochę procesora i jest oznaczone
jako eksperymentalne. Wyłącz je, jeśli odtwarzanie nie jest płynne.

## Pobieranie multimediów {#downloads}

- Pobierz zapisuje dźwięk lub film wybranego artykułu w domyślnym formacie.
- Pobierz jako pozwala najpierw wybrać format.

Pobieranie musi być włączone przez „Włącz pobieranie” w Ustawieniach. Folder
pobierania, zasady przechowywania i domyślny format pobierania filmów są ustawiane
na tej samej stronie; domyślny folder to systemowy folder Pobrane.

Postęp pojawia się w drugim polu paska stanu, a pobrane elementy są potem
odtwarzane z dysku zamiast przez sieć. Archiwum podcastów może pobrać całą
historię podcastu w jednej partii.

## Ustawienia {#settings}

Narzędzia, Ustawienia (Ctrl+comma) zawierają wszystkie opcje na kartach: Ogólne,
Kanały i artykuły, YouTube, Odtwarzacz multimediów, Dostawca, Powiadomienia,
Tłumaczenie, Nagłówki listy, Zaawansowane i Rozwiązywanie CAPTCHA.

Ctrl+Tab i Ctrl+Shift+Tab przechodzą między kartami; Tab przechodzi po kontrolkach
bieżącej karty. OK stosuje wszystko, Anuluj odrzuca wszystko. Pozycje kart pozostają
stabilne między wydaniami, ponieważ stają się pamięcią mięśniową.

Naciśnięcie F1 na karcie otwiera sekcję tego podręcznika dotyczącą tej karty.

## Ustawienia: Ogólne {#settings-general}

- Język interfejsu oraz to, czy BlindRSS podąża za językiem systemu. Zmiana
  zaczyna działać po ponownym uruchomieniu. Zobacz Język interfejsu.
- „Zapamiętaj ostatnio wybrany kanał/folder podczas uruchamiania”.
- „Potwierdź przed usunięciem artykułów” oraz to, co robi usuwanie — przenosi do
  Usuniętych artykułów, usuwa na stałe albo przenosi do wskazanej kategorii.
- „Tryb debugowania (pokaż konsolę przy uruchamianiu)”, który zapisuje także
  rotujący plik blindrss.log obok twoich danych.
- Uruchamianie i zasobnik: zamykanie do zasobnika, minimalizowanie do zasobnika,
  uruchamianie w zasobniku, zawsze uruchamiaj zmaksymalizowane oraz sprawdzanie
  aktualizacji przy uruchomieniu.

## Ustawienia: Kanały i artykuły {#settings-feeds}

- Interwał automatycznego odświeżania — od pięciu minut do czterech godzin.
- To, czy wyszukiwanie dopasowuje tylko tytuły, czy tytuły i tekst artykułów.
- Maksymalna liczba równoczesnych odświeżeń, maksymalna liczba połączeń na hosta,
  limit czasu kanału oraz liczba ponowień nieudanego kanału.
- Maksymalna liczba widoków w pamięci podręcznej oraz „Buforuj pełny tekst w tle”.
- „Automatycznie odśwież kanały przy uruchamianiu” i obciążenie odświeżania przy
  uruchamianiu: użyj pamięci podręcznej, w pełni odśwież przy uruchomieniu albo
  zawsze odświeżaj w pełni.
- Przechowywanie artykułów, które określa, jak długo są zachowywane. Ulubione
  nigdy nie są usuwane przez zasady przechowywania.
- Sposób prezentacji tekstu artykułu: ogłaszaj nagłówki, oznaczaj elementy list
  punktami i liczbami, oznaczaj cytaty, pokazuj łącza z ich adresem, opisuj
  tabele oraz dołączaj tekst alternatywny obrazów.

## Ustawienia: YouTube {#settings-youtube}

- Plik ciasteczek yt-dlp z przyciskiem Przeglądaj, przyciskiem „Importuj z
  przeglądarki” i opcją automatycznego pobierania eksportów cookies.txt z
  folderu Pobrane.
- Odczytywanie ciasteczek bezpośrednio z zainstalowanej przeglądarki.
- „Odtwarzaj YouTube po uprzednim pobraniu”, które uruchamia się wolniej, lecz
  jest najpewniejszą opcją.
- Folder pamięci podręcznej odtwarzania YouTube, jego maksymalny rozmiar w
  megabajtach oraz przycisk natychmiastowego czyszczenia.

Ciasteczka umożliwiają odtwarzanie filmów z ograniczeniem wieku i tylko dla członków
i są tym, o co pyta błąd „zaloguj się, aby potwierdzić, że nie jesteś botem”.

## Ustawienia: Odtwarzacz multimediów {#settings-media-player}

- Preferowana karta dźwiękowa albo domyślna systemowa.
- „Pomijanie ciszy (eksperymentalne)”. Zobacz Pomijanie ciszy.
- Domyślna prędkość odtwarzania.
- „Pokaż okno odtwarzacza podczas rozpoczynania odtwarzania”.
- Rozmiar pamięci podręcznej sieci w milisekundach, który wymienia opóźnienie
  startu na odporność przy wolnym połączeniu.
- Ścieżki do ffmpeg, ffprobe i yt-dlp. Pozostaw pustą, aby automatycznie wykryć;
  ustawiona ścieżka zastępuje wykrywanie, a wykryte narzędzie jest pokazane obok.
- Pobieranie: czy jest włączone, folder pobierania, zasady przechowywania i
  domyślny format pobierania filmów.
- Dźwięki: czy BlindRSS odtwarza dźwięki powiadomień.

## Ustawienia: Dostawca {#settings-provider}

Wybiera, gdzie znajdują się subskrypcje: lokalnie w BlindRSS albo na koncie
hostowanym. Zobacz Konta online i dostawcy, aby poznać wymagania każdego z nich.

Strona pokazuje aktywnego dostawcę i jego poświadczenia — adres oraz klucz API
Miniflux, identyfikator i klucz aplikacji Inoreader z przyciskiem Autoryzuj albo
adres e-mail i hasło do The Old Reader lub BazQux. Wyczyść autoryzację wylogowuje
konto Inoreader.

Lokalny dostawca korzysta z kanałów dodawanych w aplikacji przez Dodaj kanał i
Importuj OPML.

## Ustawienia: Powiadomienia {#settings-notifications}

- „Włącz powiadomienia o nowych artykułach” oraz to, czy w tekście powiadomienia
  pojawia się nazwa kanału.
- Maksymalna liczba powiadomień na odświeżenie oraz to, czy po osiągnięciu limitu
  jest pokazywane powiadomienie podsumowujące.
- Test powiadomienia wysyła je teraz.
- Wyklucz kanały wybiera kanały, które nigdy nie powiadamiają.
- Ogłoszenia: zdarzenia, które BlindRSS przekazuje bezpośrednio czytnikowi ekranu,
  dla każdego zdarzenia, z przyciskiem Test ogłoszenia wysyłającym test przez mowę i Braille'a.

## Ustawienia: Tłumaczenie {#settings-translate}

Włącza automatyczne tłumaczenie treści artykułów i wybiera wykonującą je usługę.

- „Włącz automatyczne tłumaczenie treści artykułów”.
- Dostawca: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini albo Qwen.
- Język docelowy, wybrany z listy lub wpisany jako kod, taki jak en, es, fr albo pt-BR.
- Klucz API wybranego dostawcy i opcjonalnie konkretny model. W przypadku
  OpenRouter „Wczytaj modele OpenRouter” pobiera listę dostępnych modeli.

Grok i Groq to różne usługi o myląco podobnych nazwach: Grok należy do xAI i ma
klucze z console.x.ai zaczynające się od „xai-”; Groq hostuje LLaMA i Mistral,
z bezpłatnymi kluczami z console.groq.com zaczynającymi się od „gsk_”.

To tłumaczy tekst artykułów. Aby zmienić język własnego interfejsu BlindRSS,
zobacz Język interfejsu.

## Ustawienia: Nagłówki listy {#settings-list-headers}

Ustawia globalny układ kolumn listy artykułów: które kolumny się pojawiają, w
jakiej kolejności i jakiej są szerokości. Zobacz Kolumny listy artykułów.

Pojedynczy kanał może zastąpić to ustawienie we własnych Właściwościach kanału.

## Ustawienia: Zaawansowane {#settings-advanced}

- Miejsce przechowywania danych: zachowaj bazę danych i ustawienia w folderze
  danych użytkownika albo w folderze aplikacji; obie ścieżki są pokazane. Opcja
  folderu aplikacji sprawia, że instalacja przenośna jest przenośna.
- Aktualizacje: „Automatycznie instaluj aktualizacje bez potwierdzenia”.
- Identyfikacja przeglądarki: przeglądarka, za którą BlindRSS podaje się przy
  pobieraniu kanałów, albo wpisany własny ciąg User-Agent. Obowiązujący ciąg jest
  pokazany poniżej. Ma to znaczenie dla witryn blokujących nieznanych klientów.
- Wyszukiwanie filmów: „Włącz witryny dla dorosłych w wyszukiwaniu filmów”,
  domyślnie wyłączone.

## Ustawienia: Rozwiązywanie CAPTCHA {#settings-captcha}

Opcjonalna, płatna droga ostatniej szansy dla witryn odpowiadających CAPTCHA,
której zaimportowane ciasteczka nie potrafią ominąć.

„Włącz usługę rozwiązywania CAPTCHA” ją uruchamia, a pole klucza API zawiera klucz
konta w usłudze rozwiązywania. Obowiązują opłaty za każde rozwiązanie, dlatego
jest domyślnie wyłączona i próbowana dopiero po niepowodzeniu wszystkiego innego.

Najpierw spróbuj Importowania ciasteczek witryny; jest bezpłatne i rozwiązuje większość przypadków.

## Konta online i dostawcy {#providers}

BlindRSS może sam przechowywać subskrypcje albo odczytywać je z konta hostowanego.
Wybór znajduje się w Ustawienia, Dostawca.

- Lokalnie: subskrypcje znajdują się w bazie danych BlindRSS na tym komputerze.
  Nic nie jest nigdzie synchronizowane.
- Miniflux: wymaga adresu serwera Miniflux i klucza API z ustawień konta Miniflux.
- Inoreader: wymaga identyfikatora i klucza aplikacji ze strony dla deweloperów
  Inoreader, a potem przycisku Autoryzuj do zalogowania.
- The Old Reader: wymaga adresu e-mail konta i hasła.
- BazQux: wymaga adresu e-mail konta i hasła.

Przy dostawcy hostowanym stan przeczytania, subskrypcje i kategorie należą do
konta, więc podążają za tobą na każde inne urządzenie zalogowane na to samo konto.
Niektórzy dostawcy przechowują kategorie na jednej płaskiej liście, a BlindRSS
informuje o tym zamiast oferować zagnieżdżanie, które by się nie zachowało.

## Powiadomienia {#notifications}

BlindRSS wyświetla powiadomienie systemowe, gdy przychodzą nowe artykuły, zgodnie
z Ustawienia, Powiadomienia.

- Powiadomienia można całkowicie wyłączyć.
- Nazwa kanału może być zawarta w tekście.
- Limit ogranicza liczbę powiadomień przychodzących na odświeżenie, z opcjonalnym
  powiadomieniem podsumowującym po osiągnięciu limitu.
- Poszczególne kanały można wykluczyć w Wyklucz kanały w Ustawieniach albo przez
  „Powiadomienia dla tego kanału” w menu kontekstowym kanału.
- Reguła filtrowania może pominąć powiadomienie dla pasujących artykułów.

Osobno Ogłoszenia przekazują wybrane zdarzenia bezpośrednio do czytnika ekranu
przez własny interfejs NVDA lub JAWS oraz przez Braille'a, co dociera nawet wtedy,
gdy powiadomienie systemowe nie dotrze.

## Tłumaczenie artykułów {#translation}

Przy włączonym tłumaczeniu w Ustawienia, Tłumaczenie tekst artykułu jest tłumaczony
na język docelowy podczas czytania za pomocą skonfigurowanej usługi AI.

Tłumaczenie odbywa się na żądanie i jest buforowane, więc ponowne przeczytanie
artykułu nie płaci za nie drugi raz. Wymaga połączenia z internetem i własnego
klucza API wybranej usługi.

Interfejs aplikacji jest tłumaczony osobno przez własne katalogi. Zobacz Język interfejsu.

## Importowanie ciasteczek witryny {#site-cookies}

Niektóre witryny umieszczają przed treścią stronę weryfikacji przeglądarki — zwykle
wyzwanie Cloudflare „checking your browser”. Takie witryny odpowiadają tylko sesji,
która przeszła już wyzwanie w prawdziwej przeglądarce, więc BlindRSS nie może sam ich pobrać.

Narzędzia, Importuj ciasteczka witryny daje mu tę sesję:

1. Otwórz witrynę w przeglądarce internetowej i poczekaj, aż w pełni się załaduje.
2. Wyeksportuj jej ciasteczka do pliku cookies.txt za pomocą rozszerzenia przeglądarki
   cookies.txt. Dla przeglądarek opartych na Chrome okno dialogowe zawiera łącze
   „Pobierz cookies.txt LOKALNIE”.
3. Wybierz wyeksportowany plik w oknie dialogowym.
4. Wklej ciąg User-Agent swojej przeglądarki w pole poniżej. Wyszukanie w sieci
   „what is my user agent” go pokaże. Cloudflare wymaga dokładnie tego User-Agent,
   dla którego wydano ciasteczko, dlatego ma to znaczenie.

Przeglądarki z rodziny Firefox mają ścieżkę jednym kliknięciem: „Importuj z
przeglądarki” odczytuje bezpośrednio ich bazę ciasteczek. Przeglądarki oparte na
Chromium szyfrują swoje ciasteczka, dlatego potrzebują rozszerzenia.

## Skróty klawiaturowe {#keyboard-shortcuts}

Narzędzia, Skróty klawiaturowe wyświetla każde polecenie BlindRSS pogrupowane
według kategorii wraz z bieżącym klawiszem i pozwala zmienić dowolne z nich.

- Wybierz polecenie i wybierz Zmień skrót. Okno przechwytywania zapisze wtedy
  następną naciśniętą kombinację klawiszy.
- Usuń skrót pozostawia polecenie bez przypisania; nadal działa ono z menu.
- Przywróć wszystkie domyślne przywraca dostarczone skróty.

Skróty są wysyłane przed akceleratorami menu i działają w całym oknie, także gdy
fokus ma okno odtwarzacza, a ścieżka klawiaturowa ogłasza się tam, gdzie ścieżka
menu pozostaje cicha. Zmiany są zapisywane z ustawieniami i przetrwają aktualizacje.

## Domyślne skróty klawiaturowe {#shortcuts-reference}

Kanały:

- Ctrl+N: Dodaj kanał.
- F5: Odśwież kanały. Shift+F5: Zatrzymaj odświeżanie. Ctrl+F5: Odśwież wybrany kanał.
- F2: Edytuj kanał lub kategorię.
- Ctrl+Shift+R: Oznacz wszystkie elementy jako przeczytane.
- Ctrl+Shift+F: Znajdź podcast lub kanał RSS.

Artykuły i widoki:

- Ctrl+D: dodaj do Ulubionych albo usuń z nich.
- Backspace: przełącz przeczytany i nieprzeczytany. Delete: usuń. Shift+Delete:
  usuń bez potwierdzenia.
- Ctrl+E: przenieś fokus do pola wyszukiwania.
- Ctrl+Shift+H: bogaty widok pełnego tekstu.
- Ctrl+1 do Ctrl+3: wszystkie, nieprzeczytane, przeczytane. Ctrl+4 do Ctrl+6:
  multimedia i inne, z multimediami, bez multimediów.

Odtwarzacz:

- Ctrl+P: odtwórz albo wstrzymaj. Ctrl+S: zatrzymaj. Ctrl+Shift+P: pokaż lub ukryj odtwarzacz.
- Ctrl+Left i Ctrl+Right: przewiń. Ctrl+Up i Ctrl+Down: głośność.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: przyspiesz, zwolnij, normalna prędkość.
- Ctrl+Shift+E: korektor.
- Ctrl+Shift+C: kolejka odtwarzania. Ctrl+Shift+T i Ctrl+Shift+V: następny i poprzedni.

Aplikacja:

- F1: ten podręcznik, otwarty w sekcji dotyczącej używanego elementu.
- Ctrl+comma: Ustawienia.
- Ctrl+Shift+A: ogłoś uruchomioną wersję.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: wytnij, kopiuj, wklej, zaznacz wszystko.

Polecenia niewymienione tutaj są dostarczane bez przypisania i można im nadać
dowolny klawisz w Narzędzia, Skróty klawiaturowe.

## Język interfejsu {#language}

Interfejs BlindRSS jest przetłumaczony na piętnaście języków. Ustawienia, Ogólne
wybiera jeden z nich albo pozostawia język systemowy. Zmiana zaczyna działać po
ponownym uruchomieniu.

Tłumaczenia są dostarczane pomiędzy wydaniami aplikacji, jak również wraz z nimi,
więc poprawione tłumaczenie dociera bez czekania na nową wersję.

Ten podręcznik używa tego samego języka, jeśli istnieje jego przetłumaczona wersja,
a w przeciwnym razie korzysta z angielskiego.

## Ikona zasobnika i klawisze multimedialne {#tray}

BlindRSS może działać w zasobniku systemowym. Ustawienia, Ogólne określają, czy
zamknięcie okna wysyła je do zasobnika, czy robi to minimalizacja oraz czy aplikacja
uruchamia się tam.

Ikona zasobnika ma elementy sterowania odtwarzaniem i ponownie otwiera główne okno.
Klawisze multimedialne klawiatury — odtwórz/wstrzymaj, zatrzymaj, następny, poprzedni —
sterują odtwarzaczem BlindRSS w całym systemie.

## Dodawanie skrótów pulpitu {#desktop-shortcuts}

Plik, Dodaj skróty tworzy skróty do BlindRSS na pulpicie, w menu Start i na pasku
zadań. Zaznacz wybrane elementy i wybierz OK; wynik każdego działania zostanie zgłoszony.

Wpis w menu Start jest również wymagany przez Windows, zanim aplikacja będzie mogła
wyświetlać powiadomienia, dlatego warto go mieć nawet, jeśli uruchamiasz BlindRSS inaczej.

## Sprawdzanie aktualizacji {#updates}

Pomoc, Sprawdź aktualizacje pyta, czy dostępna jest nowsza wersja, i oferuje jej
instalację.

Każda aktualizacja jest weryfikowana przed zastosowaniem: jej SHA-256 musi pasować
do opublikowanego manifestu, a w Windows podpis Authenticode musi być prawidłowy.
Aktualizacja, która nie przejdzie któregokolwiek z tych sprawdzeń, nie jest instalowana.

„Sprawdzaj aktualizacje przy uruchomieniu” w Ustawienia, Ogólne robi to automatycznie,
a „Automatycznie instaluj aktualizacje bez potwierdzenia” w Ustawienia, Zaawansowane
stosuje je bez pytania. Ustawienia, baza danych i pobrania pozostają nietknięte przez aktualizację.

## Ogłaszanie wersji {#version}

Pomoc, Ogłoś wersję (Ctrl+Shift+A) przekazuje uruchomioną wersję BlindRSS bezpośrednio
do czytnika ekranu.

Własne polecenie czytnika ekranu „zgłoś wersję aplikacji” odczytuje zasób wersji
pliku wykonywalnego, co działa dla zainstalowanej wersji, lecz przy uruchomieniu
BlindRSS ze źródła zgłasza wersję Pythona. To polecenie daje prawidłową odpowiedź
w obu przypadkach.

## O BlindRSS {#about}

Pomoc, O programie pokazuje wersję, licencję oraz łącza: profil GitHub,
repozytorium i dziennik zmian.

BlindRSS jest objęty licencją MIT — możesz go używać, zmieniać, rozpowszechniać
lub pakować do repozytoriów dystrybucji bez potrzeby uzyskania pozwolenia.

## Korzystanie z tego okna pomocy {#help-window}

To okno jest prostym, w pełni dostępnym z klawiatury czytnikiem podręcznika.

- Lista treści zawiera każdą sekcję. Przechodź po niej strzałkami; wybranie sekcji
  przewija tekst do niej i ogłasza jej tytuł.
- Obszar tekstu jest tylko do odczytu i można go zaznaczać, więc czytnik ekranu
  może czytać go wiersz po wierszu, a ty możesz z niego kopiować.
- Ctrl+F przenosi do pola wyszukiwania. Wpisz słowo i naciśnij Enter, aby przejść
  do następnego wystąpienia.
- F3 znajduje następne wystąpienie, Shift+F3 poprzednie. Wyszukiwanie zawija się.
- Tab i Shift+Tab przechodzą między polem wyszukiwania, listą treści i tekstem.
- Escape zamyka okno.

F1 w dowolnym miejscu BlindRSS otwiera to okno w sekcji dotyczącej używanego elementu
— kontrolki z fokusem, aktywnego okna dialogowego, podświetlonego elementu menu albo
odtwarzacza. Gdy nie ma dla niego sekcji, podręcznik otwiera się na początku.

Podręcznik jest wyświetlany w języku interfejsu BlindRSS, gdy jego tłumaczenie
istnieje, a w przeciwnym razie po angielsku.

## Rozwiązywanie problemów {#troubleshooting}

Kanał przestał się aktualizować. Poszukaj przyczyny w Kanałach z błędami. Przeniesiony
kanał wymaga poprawienia adresu we Właściwościach kanału; witryna żądająca sprawdzenia
przeglądarki wymaga Importowania ciasteczek witryny.

Film YouTube nie chce się odtworzyć. Zaimportuj ciasteczka YouTube w Ustawienia,
YouTube i włącz „Odtwarzaj YouTube po uprzednim pobraniu”. Błąd „zaloguj się, aby
potwierdzić, że nie jesteś botem” zawsze oznacza ciasteczka.

Odtwarzanie zacina się. Zwiększ pamięć podręczną sieci w Ustawienia, Odtwarzacz
multimediów i wyłącz Pomijanie ciszy, które jest eksperymentalne i zużywa procesor.

Witryna nie zwraca niczego. Zmień identyfikację przeglądarki w Ustawienia,
Zaawansowane; niektóre witryny wprost odrzucają nieznanych klientów.

Nic nie jest mówione po uruchomieniu polecenia. Sprawdź Ogłoszenia w Ustawienia,
Powiadomienia — każde zdarzenie można osobno włączyć lub wyłączyć, a istnieje przycisk testowy.

Coś zachowuje się dziwnie i chcesz to zgłosić. Włącz tryb debugowania w Ustawienia,
Ogólne, odtwórz problem i dołącz plik blindrss.log zapisany obok ustawień i danych.

## Wsparcie i społeczność {#support}

Błędy i prośby o funkcje należy zgłaszać w śledzeniu zgłoszeń GitHub pod adresem
github.com/serrebidev/BlindRSS/issues.

W przypadku pytań, pomocy i wiadomości o wydaniach najszybszym miejscem uzyskania
odpowiedzi jest grupa SerrebiProjects w Telegramie pod adresem t.me/SerrebiProjects.

Tłumaczenia są zawsze mile widziane. Jeśli znasz jeden z obsługiwanych języków i
coś brzmi niepoprawnie, pull request, który to poprawi, niemal na pewno zostanie
zaakceptowany — zobacz locale/README.md w repozytorium, aby dowiedzieć się, jak są
rozmieszczone pliki. To samo dotyczy tego podręcznika: przetłumaczona kopia należy
do docs/help/<language>.md, z zachowaniem znaczników {#anchor} dokładnie takich,
jak w pliku angielskim, aby pomoc zależna od kontekstu nadal działała.
