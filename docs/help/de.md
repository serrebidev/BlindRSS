# BlindRSS-Benutzerhandbuch

## BlindRSS-Benutzerhandbuch {#user-guide}

BlindRSS ist ein bildschirmleserfreundlicher Desktop-Client für RSS und
Podcasts. Er liest RSS- und Atom-Feeds, spielt Podcast- und Video-Anhänge ab
und arbeitet entweder eigenständig oder mit einem gehosteten Konto wie
Miniflux, Inoreader, The Old Reader oder BazQux.

Dieses Handbuch ist in der Anwendung gespeichert und funktioniert daher ohne
Internetverbindung und ohne Webbrowser. Drücken Sie überall in BlindRSS F1, um
es zu öffnen. Wenn das Steuerelement, das Dialogfeld, der Menüpunkt oder das
Fenster, das Sie gerade verwenden, einen eigenen Abschnitt hat, öffnet F1 das
Handbuch direkt an dieser Stelle statt am Anfang.

Alles hier ist über die Tastatur erreichbar. Verwenden Sie die Inhaltsliste, um
zwischen den Abschnitten zu wechseln, oder das Suchfeld, um ein Wort irgendwo
im Handbuch zu finden.

## Erste Schritte {#getting-started}

Beim ersten Start hat BlindRSS keine Feeds. Es gibt mehrere Möglichkeiten,
welche hinzuzufügen:

- Drücken Sie Ctrl+N, um einen Feed über seine Adresse hinzuzufügen. Siehe
  „Feed hinzufügen“.
- Drücken Sie Ctrl+Shift+F, um Podcast- und Feed-Verzeichnisse nach Namen zu
  durchsuchen. Siehe „Podcasts und RSS-Feeds finden“.
- Importieren Sie eine OPML-Datei aus einem anderen Reader. Siehe „OPML
  importieren“.
- Importieren Sie ein YouTube-Takeout-Archiv, um alle Kanäle zu abonnieren,
  denen Sie bereits folgen. Siehe „Ein YouTube-Takeout-Archiv importieren“.
- Melden Sie sich unter E&xtras, &Einstellungen..., Anbieter bei einem
  gehosteten Konto an; BlindRSS liest dann die Abonnements dieses Kontos.
  Siehe „Online-Konten und Anbieter“.

Sobald Sie Feeds haben, drücken Sie F5, um sie zu aktualisieren. Neue Artikel
erscheinen in der Artikelliste, und die Anzahl der ungelesenen Artikel steht
neben jedem Feed im Baum.

Drei Stellen lohnen sich früh: E&xtras, &Einstellungen... (wie BlindRSS sich
verhält), E&xtras, &Tastenkürzel... (jeder Befehl und seine Taste) und dieses
Handbuch.

## Das Hauptfenster {#main-window}

Das Hauptfenster hat vier Hauptbereiche sowie eine Menüleiste und eine
Statusleiste. Tab und Shift+Tab wechseln zwischen ihnen, und F6 durchläuft in
den meisten Fensterverwaltungen die Bereiche.

- Der Baum „Feeds und Ordner“ auf der linken Seite.
- Das Suchfeld über der Artikelliste.
- Die Artikelliste.
- Der Lesebereich unter der Artikelliste.

Die Menüleiste enthält &Datei, &Bearbeiten, &Ansicht, &Player, E&xtras und
&Hilfe. Drücken Sie Alt, um sie zu erreichen, und verwenden Sie dann die
Pfeiltasten. Jeder Menüpunkt hat in jeder Sprache einen Zugriffsbuchstaben, und
die Menüleiste läuft an beiden Enden umlaufend weiter.

Größen, der ausgewählte Feed und der Fensterzustand bleiben zwischen den
Sitzungen erhalten. „Zuletzt ausgewählten Feed/Ordner beim Start merken“ in den
Einstellungen unter „Allgemein“ steuert, ob BlindRSS wieder mit dem Feed
öffnet, den Sie zuletzt gelesen haben.

## Feeds und Ordner {#feed-tree}

Der Baum auf der linken Seite listet Ihre Feeds auf, die Kategorien, die sie
gruppieren, intelligente Ordner, gespeicherte Suchen und die integrierten
Ansichten (Alle Feeds, Favoriten, Gelöschte Artikel und Feeds mit Fehlern).

- Pfeil nach oben und unten bewegen sich zwischen den Einträgen.
- Pfeil nach rechts klappt eine Kategorie auf, Pfeil nach links klappt sie zu.
- Enter oder das Auswählen eines Eintrags lädt dessen Artikel in die
  Artikelliste.
- F2 öffnet die Eigenschaften des ausgewählten Feeds oder der Kategorie.
- Die Anwendungstaste oder Shift+F10 öffnet das Kontextmenü.

Jeder Feed zeigt die Anzahl seiner ungelesenen Artikel. Auf- und zugeklappte
Kategorien werden gespeichert, sodass der Baum beim nächsten Start gleich
aussieht.

Feeds, deren Aktualisierung fehlgeschlagen ist, bleiben normal aufgeführt; die
Ansicht „Feeds mit Fehlern“ sammelt sie, damit ein Feed, der still aufgehört
hat zu funktionieren, nicht unbemerkt bleibt.

## Artikelliste {#article-list}

Die Artikelliste zeigt die Artikel dessen, was im Baum ausgewählt ist, nachdem
der aktuelle Artikelfilter, die Sortierreihenfolge und der Suchbegriff
angewendet wurden.

- Pfeil nach oben und unten wechseln zwischen den Artikeln; der Lesebereich
  folgt.
- Enter öffnet den ausgewählten Artikel.
- Shift+Pfeil nach oben und Shift+Pfeil nach unten erweitern die Auswahl,
  sodass Sammelaktionen wie Löschen oder Kopieren auf mehrere Artikel wirken.
- Backspace schaltet den ausgewählten Artikel zwischen gelesen und ungelesen um.
- Delete entfernt die ausgewählten Artikel; Shift+Delete entfernt sie ohne
  Bestätigungsabfrage.
- Ctrl+D fügt einen Favoriten hinzu oder entfernt ihn.
- Die Anwendungstaste oder Shift+F10 öffnet das Kontextmenü.

Welche Spalten erscheinen und in welcher Reihenfolge, ist global und pro Feed
einstellbar. Siehe „Spalten der Artikelliste“.

## Lesebereich {#reading-pane}

Der Lesebereich unter der Artikelliste enthält den Text des ausgewählten
Artikels. Er ist ein schreibgeschütztes Textfeld, sodass ein Bildschirmleser
ihn Zeile für Zeile, Wort für Wort oder Zeichen für Zeichen vorlesen kann und
der Text markiert und kopiert werden kann.

- Ctrl+F sucht im Artikeltext.
- F3 und Shift+F3 springen zum nächsten und vorherigen Treffer.
- Enter auf einem Link im Text öffnet diesen Link.

Wie der Text dargestellt wird, ist unter „Einstellungen“, „Feeds && Artikel“
einstellbar: Überschriften können angesagt, Listenelemente mit Aufzählungs-
zeichen und Nummern versehen, Zitate gekennzeichnet, Links mit ihrer Adresse
angezeigt, Tabellen beschrieben und Bild-Alt-Texte einbezogen werden. Der
Bild-Alt-Text lässt sich im Kontextmenü eines Feeds auch für diesen einen Feed
erzwingen oder abschalten.

Wenn ein Feed nur eine kurze Zusammenfassung veröffentlicht, kann BlindRSS den
vollständigen Artikeltext nachladen. Siehe „Volltext-Wiederherstellung“.

## Artikelfenster {#article-window}

Ein Artikel kann statt im Lesebereich in einem eigenen Fenster geöffnet werden.
Das gibt ihm den ganzen Bildschirm und hält ihn geöffnet, während Sie in der
Liste weitergehen.

Das Fenster ist ein schreibgeschütztes Textfeld mit demselben Lese-, Markier-
und Suchverhalten wie der Lesebereich. Escape schließt es.

## Suchfeld {#search-field}

Das Suchfeld über der Artikelliste filtert die aktuelle Ansicht anhand dessen,
was Sie eingeben und mit Enter bestätigen.

- Ctrl+E setzt den Fokus auf das Suchfeld.
- Enter wendet den Begriff an.
- Escape oder die Schaltfläche zum Leeren setzt es zurück und stellt die
  vollständige Liste wieder her.

Das Suchfeld lässt sich ausblenden, wenn Sie es nie verwenden; im Menü
&Ansicht gibt es einen Befehl zum Ein- und Ausblenden. Ob die Suche nur Titel
oder Titel und Artikeltext durchsucht, wird unter „Einstellungen“, „Feeds &&
Artikel“ bei „Suchtreffer:“ festgelegt.

Eine Suche, die Sie behalten möchten, lässt sich in eine gespeicherte Suche
verwandeln, die im Baum bleibt. Siehe „Dauerhafte Suchen“.

## Statusleiste {#status-bar}

Die Statusleiste am unteren Rand des Hauptfensters hat drei Felder:

- Kurzzeitige Meldungen, etwa wie viele Artikel ein Filter gefunden hat.
- Hintergrundaktivität, etwa eine laufende Feed-Aktualisierung oder ein
  Download.
- Wiedergabestatus: was gerade läuft sowie die verstrichene und verbleibende
  Zeit.

Sie sind bewusst getrennt, damit eine Aktualisierungsmeldung die Trefferzahl
einer Suche nicht überschreibt, während Sie sie gerade lesen.

## Kontextmenüs {#context-menus}

Der Feed-Baum und die Artikelliste haben jeweils ein Kontextmenü, das mit der
Anwendungstaste oder Shift+F10 geöffnet wird. Es enthält die Befehle, die für
das jeweils Ausgewählte gelten – aktualisieren, als gelesen markieren,
bearbeiten, entfernen, Links kopieren, Medien in die Warteschlange stellen und
so weiter.

Auch Kontextmenüs unterstützen F1: Wenn ein Eintrag hervorgehoben ist, öffnet
F1 den Abschnitt dieses Handbuchs, der ihn erklärt.

## Feed hinzufügen {#adding-feeds}

&Datei, Feed &hinzufügen... (Ctrl+N) abonniert einen Feed über seine Adresse.

Fügen Sie die Adresse des Feeds oder der Website selbst ein oder tippen Sie sie
ein – BlindRSS sucht auf der Seite nach einem Feed, wenn die Adresse kein Feed
ist. Sie können auch eine YouTube-Kanal- oder Playlist-Adresse, ein Mastodon-
oder Bluesky-Profil, eine PieFed- oder Lemmy-Community, eine SoundCloud- oder
Mixcloud-Seite oder eine Reddit- oder Groups.io-Adresse einfügen; BlindRSS
macht daraus einen Feed.

Wählen Sie die Kategorie, in die der Feed gehört, oder lassen Sie ihn ohne
Kategorie. Die Option „Als HTML-Ansicht öffnen“ sorgt dafür, dass Artikel
dieses Feeds standardmäßig in der HTML-Ansicht geöffnet werden.

Wenn Sie die Adresse nicht kennen, verwenden Sie stattdessen „Podcasts und
RSS-Feeds finden“.

## Feeds auf einer Seite erkennen {#detect-feeds}

&Datei, „Feeds auf Seite erkennen“ nimmt die Adresse einer normalen Webseite
und listet die Feeds auf, die diese Seite anbietet, sodass Sie abonnieren
können, ohne den Feed-Link selbst suchen zu müssen.

Das ist der richtige Befehl, wenn eine Website einen „Abonnieren“- oder
„RSS“-Link hat, den Sie schlecht erreichen, oder wenn die Seite mehrere Feeds
anbietet (alle Beiträge, eine Kategorie, Kommentare) und Sie wählen möchten.

## Podcasts und RSS-Feeds finden {#find-podcast}

E&xtras, &Podcast oder RSS-Feed finden... (Ctrl+Shift+F) durchsucht Podcast-
und Feed-Verzeichnisse nach Namen, Thema oder Website-Adresse, sodass Sie
abonnieren können, ohne eine Feed-Adresse zu kennen.

1. Geben Sie in das Suchfeld ein, wonach Sie suchen – einen Podcast-Namen, ein
   Thema oder eine Website-Adresse.
2. Wählen Sie eine Quelle oder belassen Sie es bei „Alle Quellen“.
3. Drücken Sie Enter oder die Schaltfläche „Suchen“.
4. Gehen Sie mit den Pfeiltasten durch die Ergebnisliste. Jede Zeile zeigt den
   Titel, das Verzeichnis, aus dem er stammt, und Details.
5. Drücken Sie Enter auf einem Ergebnis oder wählen Sie OK, um es zu abonnieren.

Die Suche läuft gleichzeitig über mehrere Verzeichnisse, und die Ergebnisse
treffen ein, sobald das jeweilige Verzeichnis antwortet; die Liste wächst also,
während Sie sie lesen. Escape schließt das Dialogfeld und stoppt die Suche.

## Podcast- und Feed-Verzeichnisse {#podcast-directories}

Das Feld „Quelle“ in „Podcast oder RSS-Feed finden“ bestimmt, wo gesucht wird.
Neben „Alle Quellen“, „Alle Podcast-Quellen“ und „Alle RSS-Feed-Quellen“ stehen
diese Verzeichnisse einzeln zur Verfügung:

- Podcast-Verzeichnisse: iTunes (Apple Podcasts), gPodder, fyyd, Podverse,
  SoundCloud und Mixcloud.
- Feed-Verzeichnisse: NewsBlur, Feedspot, Google News, Bing News und Feedly.
- Website- und Community-Suche: YouTube, Reddit, Groups.io und das Fediverse –
  Mastodon, Bluesky, PieFed sowie Lemmy oder Kbin, jeweils auch einzeln
  auswählbar.
- Adressbasierte Erkennung: Feedsearch und der eigene Website-Scan von
  BlindRSS, der eine Website abruft und darin nach Feeds sucht.

Kein einzelnes Verzeichnis ist unverzichtbar. Die Suche über „Alle Quellen“
fragt die Podcast- und die RSS-Gruppe gemeinsam ab und führt die Ergebnisse
zusammen, wobei breite Google-News-Suchfeeds unter den direkten Feed-Treffern
einsortiert werden.

## Ein Suchergebnis abonnieren {#subscribing}

In jedem der Suchdialoge – „Podcast oder RSS-Feed finden“, „Videosuche“ oder
die Suchschaltfläche des Podcast-Archivs – abonniert Enter auf einem Ergebnis
oder OK bei ausgewähltem Ergebnis dieses Ergebnis.

BlindRSS löst das Ergebnis zuerst in eine echte Feed-Adresse auf; das Abonnieren
eines in einem Verzeichnis gefundenen Podcasts, eines YouTube-Kanals oder eines
Fediverse-Kontos funktioniert daher jeweils gleich. Der neue Feed erscheint im
Baum und wird sofort aktualisiert.

Wenn Sie ihn in einer bestimmten Kategorie haben möchten, verschieben Sie ihn
anschließend über sein Kontextmenü oder über die Feed-Eigenschaften.

## Podcast-Archiv {#podcast-archive}

E&xtras, „Podcast-Archiv“ durchsucht die vollständige Episodenliste eines
Podcasts – sowohl die noch im Feed enthaltenen Episoden als auch die älteren,
die BlindRSS wiederhergestellt hat – und lädt sie stapelweise herunter.

Viele Podcast-Feeds veröffentlichen nur die neuesten Episoden. Die
Archivwiederherstellung läuft automatisch im Hintergrund; in diesem Fenster
sehen Sie ihren Status, starten sie von Hand neu und laden herunter, was sie
gefunden hat.

- Wählen Sie den Podcast im Feld „Podcast“.
- „Episoden filtern“ grenzt die Liste ein, während Sie tippen.
- „Archiv erneut durchsuchen“ startet die Wiederherstellung für diesen Podcast
  erneut.
- „Podcast finden oder hinzufügen“ öffnet die Feed-Suche, sodass Sie einen
  noch nicht abonnierten Podcast archivieren können.
- „Wiedergabe“ spielt die ausgewählte Episode ab, „Ausgewählte herunterladen“
  lädt sie herunter, und „Alle herunterladen“ lädt die gesamte sichtbare Liste.
- „Downloads abbrechen“ stoppt einen laufenden Stapel.

Das Fenster bleibt geöffnet, während ein Stapel geladen wird, sodass Sie
weiterlesen können.

## Videosuche {#video-search}

E&xtras, &Videosuche... durchsucht in einem Durchgang alle Websites, die yt-dlp
abfragen kann, und lässt Sie die Treffer abspielen, in die Warteschlange
stellen oder abonnieren.

- Geben Sie einen Suchbegriff ein und drücken Sie Enter oder „Suchen“.
- Das Feld für den Umfang beschränkt die Suche auf eine Website; standardmäßig
  wird über alle gesucht.
- Ergebnisse treffen ein, sobald die jeweilige Website antwortet, große
  Anbieter zuerst. Titel, die zunächst als Platzhalter erscheinen, werden
  nachgeladen.
- „Weitere Ergebnisse laden“ holt einen weiteren Schwung von jeder Website.
- Das Sortieren nach einer Spaltenüberschrift ordnet das bereits Eingetroffene
  neu.

Identische Videos, die auf mehreren Websites gefunden werden, werden zu einer
Zeile zusammengefasst. Erwachsenenseiten sind ausgeschlossen, solange
„Erwachsenenseiten in der Videosuche aktivieren“ unter „Einstellungen“,
„Erweitert“ nicht eingeschaltet ist.

## Einen Artikel über seine Adresse öffnen {#open-article-url}

&Datei, „Artikel öffnen“ nimmt die Adresse einer beliebigen Webseite und liest
sie in BlindRSS wie einen Artikel – als extrahierten Text, im Lesebereich, mit
denselben Leseoptionen wie alles andere.

Verwenden Sie es für eine einzelne Seite, die Ihnen jemand geschickt hat, ohne
etwas zu abonnieren. Ist die Seite ein Forum oder ein Diskussionsfaden, liest
BlindRSS den ganzen Faden. Siehe „Foren- und Diskussionsfäden“.

## Eine Medienadresse öffnen {#open-media-url}

&Datei, „Medien-URL öffnen“ spielt Audio oder Video von einer Adresse im
integrierten Player ab, ohne etwas zu abonnieren.

Es akzeptiert direkte Medienlinks und Seitenadressen, die yt-dlp auflösen kann –
YouTube, Rumble, Odysee, SoundCloud und viele weitere. Das Ergebnis wird wie
jedes andere Element abgespielt und kann in die Wiedergabe-Warteschlange
aufgenommen werden.

## Feed entfernen {#removing-feeds}

&Datei, Feed &entfernen kündigt das Abonnement des ausgewählten Feeds. Derselbe
Befehl steht im Kontextmenü des Feeds.

Das Entfernen eines Feeds entfernt seine Artikel aus der Datenbank. Bereits auf
die Festplatte heruntergeladene Dateien bleiben unberührt. Wenn Sie einen
gehosteten Anbieter verwenden, wird die Kündigung auch an dieses Konto gesendet.

Um eine ganze Kategorie mit allem darin zu entfernen, verwenden Sie „Kategorie
und Feeds löschen“ im Kontextmenü der Kategorie. Siehe „Kategorien und
Unterkategorien“.

## Feed-Eigenschaften {#feed-properties}

F2 oder „Feed bearbeiten“ im Kontextmenü öffnet die Eigenschaften des
ausgewählten Feeds.

- Seinen Titel, den Sie überschreiben können; „Titel auf Feed-Standard
  zurücksetzen“ im Kontextmenü stellt den ursprünglichen Titel wieder her.
- Seine Adresse und die Kategorie, zu der er gehört.
- Ob neue Artikel daraus eine Benachrichtigung auslösen.
- Ob er in der HTML-Ansicht geöffnet wird.
- Sein eigenes Spaltenlayout für die Artikelliste auf der Registerkarte
  „Listenüberschriften“, das das globale Layout überschreibt.

„Feed-Beschreibung anzeigen...“ im Kontextmenü der Artikelliste zeigt die
Beschreibung, die der Feed selbst veröffentlicht.

## Kategorien und Unterkategorien {#categories}

Kategorien gruppieren Feeds im Baum und können verschachtelt werden: Eine
Kategorie kann sowohl Feeds als auch weitere Unterkategorien enthalten.

- &Datei, &Kategorie hinzufügen... legt eine an.
- „Unterkategorie hinzufügen“ im Kontextmenü einer Kategorie legt eine darin an.
- „Kategorie bearbeiten“ benennt sie um oder verschiebt sie. Siehe
  „Kategorie-Eigenschaften“.
- „Kategorie entfernen“ löscht die Kategorie, behält aber ihre Feeds.
- „Kategorie und Feeds löschen“ löscht die Kategorie und kündigt alle
  Abonnements darin.
- „OPML hier importieren...“ importiert eine Datei direkt in diese Kategorie.
- „Kategorie nach OPML exportieren...“ exportiert nur diesen Zweig.

Manche gehosteten Anbieter führen Kategorien in einer einzigen flachen Liste.
In diesem Fall weist BlindRSS darauf hin, und die Optionen zum Verschieben in
eine übergeordnete Kategorie stehen nicht zur Verfügung.

## Kategorie-Eigenschaften {#category-properties}

„Kategorie bearbeiten“ öffnet die Eigenschaften der Kategorie: ihren Namen und
die übergeordnete Kategorie, unter der sie liegt.

Das Umbenennen einer Kategorie behält alle ihre Feeds. Das Verschieben
verschiebt den ganzen Zweig einschließlich aller Unterkategorien.

## Feeds aktualisieren {#refreshing}

- F5 aktualisiert alle Feeds.
- Ctrl+F5 aktualisiert nur den ausgewählten Feed oder die ausgewählte Kategorie.
- Shift+F5 stoppt eine laufende Aktualisierung.
- „Kategorie aktualisieren“ im Kontextmenü einer Kategorie aktualisiert diesen
  Zweig.

Es ist immer nur einer der beiden Befehle „Feeds aktualisieren“ und
„Aktualisierung stoppen“ verfügbar, damit das Tastenkürzel zu dem passt, was das
Menü anbietet. Der Fortschritt erscheint im zweiten Feld der Statusleiste.

Die automatische Aktualisierung wird unter „Einstellungen“, „Feeds && Artikel“
eingerichtet: das Intervall, wie viele Feeds gleichzeitig aktualisiert werden,
wie viele Verbindungen pro Host erlaubt sind, die Zeitüberschreitung pro Feed
und wie oft ein fehlgeschlagener Feed erneut versucht wird. „Feeds beim Start
automatisch aktualisieren“ aktualisiert beim Start alles, und die Option zur
Startlast wählt zwischen der Nutzung des Caches und einer vollständigen
Aktualisierung.

## Feeds mit Fehlern {#feed-errors}

Die Ansicht „Feeds mit Fehlern“ und &Datei, „Feed-Fehler anzeigen“ listen die
Feeds auf, deren letzte Aktualisierung fehlgeschlagen ist, mitsamt dem Grund.

Ein Feed, der still aufgehört hat zu funktionieren, sieht genauso aus wie ein
Feed ohne neue Artikel – deshalb gibt es diese Ansicht. Von dort aus können Sie:

- „Ausgewählte aktualisieren“, um es jetzt erneut zu versuchen.
- „Details kopieren“, um den Fehlertext in die Zwischenablage zu legen.
- „Feed-Eigenschaften“, um die Adresse zu korrigieren.
- „Feed entfernen“, wenn der Feed endgültig verschwunden ist.

Häufige Ursachen sind ein umgezogener oder eingestellter Feed, eine Website, die
nun eine Browserprüfung verlangt (siehe „Website-Cookies importieren“), und ein
vorübergehender Serverausfall.

## OPML importieren {#import-opml}

OPML ist das Standarddateiformat für eine Liste von Feed-Abonnements. Jeder
Feed-Reader kann eines exportieren; OPML ist also der Weg, Ihre Abonnements aus
einem anderen Reader nach BlindRSS zu übernehmen, ohne sie einzeln anzulegen.

&Datei, OPML &importieren... fragt nach der Datei und fügt jeden darin
enthaltenen Feed hinzu, wobei die in der Datei beschriebene Kategoriestruktur
erhalten bleibt. Bereits abonnierte Feeds werden nicht doppelt angelegt.

„OPML hier importieren...“ im Kontextmenü einer Kategorie legt den gesamten
Import in diese Kategorie statt auf die oberste Ebene.

Um eine OPML-Datei aus einem anderen Reader zu erhalten, suchen Sie dort in den
Einstellungen nach „Export“, „Backup“ oder „Abonnements“.

## OPML exportieren {#export-opml}

&Datei, OPML e&xportieren... schreibt alle Ihre Abonnements mit ihren
Kategorien in eine OPML-Datei.

Verwenden Sie das, um Ihre Abonnements zu sichern, sie zu einem anderen Reader
oder auf einen anderen Rechner zu übertragen oder eine Feed-Sammlung mit
jemandem zu teilen. „Kategorie nach OPML exportieren...“ im Kontextmenü einer
Kategorie exportiert nur diesen Zweig.

## Ein YouTube-Takeout-Archiv importieren {#import-youtube-takeout}

Google Takeout ist der Datenexportdienst von Google. Ein
YouTube-Takeout-Archiv ist eine ZIP-Datei mit Ihren YouTube-Daten, darunter die
Liste der Kanäle, die Sie abonniert haben. &Datei, YouTube Takeout
&importieren... liest diese ZIP-Datei und abonniert diese Kanäle als Feeds,
sodass die neuen Videos jedes Kanals als Artikel eintreffen.

So erhalten Sie das Archiv:

1. Gehen Sie zu takeout.google.com und melden Sie sich mit dem Google-Konto an,
   zu dem Ihre YouTube-Abonnements gehören.
2. Wählen Sie „Alle abwählen“ und dann nur YouTube und YouTube Music aus.
3. Behalten Sie unter „Alle enthaltenen YouTube-Daten“ mindestens
   „subscriptions“ bei; „history“ und „playlists“ sind optional, BlindRSS kann
   sie ebenfalls verwenden.
4. Exportieren Sie einmalig als ZIP-Datei und warten Sie auf die E-Mail von
   Google – ein großes Archiv kann Stunden dauern.
5. Laden Sie die ZIP-Datei herunter und wählen Sie sie mit diesem Befehl aus.

BlindRSS zeigt dann nach Quelle gruppiert, was es gefunden hat, und lässt Sie
wählen, welche Gruppen importiert werden:

- Abonnements: die Kanäle, denen Sie folgen.
- Verlauf: Kanäle, die Sie angesehen haben, denen Sie aber nicht folgen.
- Ihre eigenen Kanäle.
- Playlists, als eigene Feeds.

Doppelte Adressen werden entfernt, sodass ein späterer zweiter Import nur das
Neue hinzufügt. Die ZIP-Datei wird nie auf die Festplatte entpackt; es werden
nur die kleinen Datendateien darin gelesen.

## Dauerhafte Suchen {#persistent-search}

Eine dauerhafte Suche ist ein Suchbegriff, der als eigener Eintrag im Baum
bleibt, sodass die passenden Artikel immer nur einen Tastendruck entfernt sind.

E&xtras, &Dauerhafte Suche konfigurieren... verwaltet die Liste: „Hinzufügen“
legt eine aus einem Begriff an, „Entfernen“ löscht sie. Jede gespeicherte Suche
erscheint im Baum und wird bei jeder Auswahl neu ausgewertet, sodass sie stets
die aktuellen Artikel widerspiegelt.

Verwenden Sie das für ein Thema, das Sie über alle Feeds hinweg verfolgen – den
Namen einer Person, ein Produkt, einen Ort. Für etwas Strukturierteres als eine
Wortfolge verwenden Sie intelligente Ordner.

## Intelligente Ordner {#smart-folders}

Ein intelligenter Ordner ist ein Ordner im Baum, dessen Inhalt durch eine Regel
statt durch die Herkunft der Artikel bestimmt wird.

„Neuer intelligenter Ordner...“ im Kontextmenü des Baums öffnet den
Regeleditor. Eine Regel ist eine Menge von Bedingungen, verknüpft mit „alle
erfüllen“ (und) oder „eine erfüllen“ (oder); Bedingungsgruppen lassen sich
verschachteln, sodass „(A und B) oder C“ ausdrückbar ist.

Bedingungen prüfen diese Felder:

- Ja/Nein-Felder: gelesen, Favorit, geöffnet, aktualisiert.
- Textfelder: Titel, Inhalt, Beschreibung, Autor, Feed, URL und Tag – die
  Kategorien oder Schlagwörter, die die Website selbst veröffentlicht.

Textbedingungen verwenden „enthält“, „enthält nicht“, „ist gleich“ oder
„beginnt mit“.

Intelligente Ordner verschieben oder kopieren nichts; sie sind eine Sicht auf
die Artikel, die Sie bereits haben. Um Artikel beim Eintreffen zu verändern,
verwenden Sie Filterregeln.

## Filterregeln {#filter-rules}

E&xtras, Filter&regeln... ist die Sortiermaschine für Artikel in BlindRSS.
Regeln laufen über eingehende Artikel, so wie E-Mail-Filter über eingehende
Nachrichten laufen.

Jede Regel verbindet eine Bedingung – denselben Regeleditor, den auch
intelligente Ordner verwenden – mit einer Menge von Aktionen:

- Den Artikel in eine Kategorie verschieben.
- Ihn zusätzlich mit einer Kategorie kennzeichnen und dabei an Ort und Stelle
  belassen.
- Ihn als gelesen markieren.
- Ihn als Favorit markieren.
- Ihn löschen, gemäß Ihrem eingestellten Löschverhalten.
- Seine Benachrichtigung über neue Artikel unterdrücken.

Regeln laufen in Listenreihenfolge, und jede aktivierte Regel, die zutrifft,
steuert ihre Aktionen bei. Eine Regel, die zum Stoppen markiert ist, beendet
die Kette für diesen Artikel, sobald sie zugetroffen hat, sodass spätere Regeln
ihn nicht mehr sehen. Verschieben Sie Regeln nach oben oder unten, um zu
bestimmen, welche gewinnt.

Eine Regel ohne Aktionen bewirkt nichts und wird abgelehnt, damit eine halb
fertige Regel keine Artikel stillschweigend verschluckt.

## Artikelfilter {#article-filter}

&Ansicht, Artikel&filter begrenzt jede Ansicht nach Lesestatus und danach, ob
ein Artikel Medien enthält. Die beiden Gruppen wirken zusammen.

- Ctrl+1: alle Artikel.
- Ctrl+2: nur ungelesene.
- Ctrl+3: nur gelesene.
- Ctrl+4: mit und ohne Medien.
- Ctrl+5: nur mit Medien.
- Ctrl+6: nur ohne Medien.

Der Filter gilt für das im Baum Ausgewählte, einschließlich intelligenter
Ordner und gespeicherter Suchen, und bleibt zwischen den Sitzungen erhalten.
„Nur mit Medien“ ist der schnellste Weg, aus einem gemischten Feed eine
Podcast-Liste zu machen.

## Artikel sortieren {#sorting}

&Ansicht, Sortieren &nach ordnet die Artikelliste nach Datum, Name, Autor,
Beschreibung, Feed oder Status. „Aufsteigend“ kehrt die Richtung um; die
Voreinstellung ist neueste zuerst.

Die Sortierung gilt für jede Ansicht und bleibt zwischen den Sitzungen
erhalten. Das Sortieren nach Feed ist in „Alle Feeds“ und in intelligenten
Ordnern nützlich, wo Artikel aus vielen Quellen zusammenkommen.

## Spalten der Artikelliste {#list-headers}

Die Spalten der Artikelliste, ihre Reihenfolge und ihre Breiten sind Ihre Wahl.
„Einstellungen“, „Listenüberschriften“ legt das globale Layout fest; die eigene
Registerkarte „Listenüberschriften“ eines Feeds überschreibt es für diesen
Feed, und „Globales Spaltenlayout verwenden“ schaltet die Überschreibung wieder
ab.

Weniger Spalten bedeuten weniger, was ein Bildschirmleser in jeder Zeile
vorlesen muss – es lohnt sich also, alle zu entfernen, die Sie nie verwenden.

## Artikel öffnen {#opening-articles}

Enter auf einem Artikel in der Liste öffnet ihn. Je nach Artikel und Ihren
Einstellungen bedeutet das den Lesebereich, ein eigenes Fenster oder die
HTML-Ansicht.

- „Artikel öffnen“ im Kontextmenü tut dasselbe.
- „Im Standardbrowser öffnen“ übergibt die Adresse des Artikels an Ihren
  Webbrowser.
- „Barrierefreien Browser öffnen“ liest die Seite stattdessen in BlindRSS.
  Siehe „Barrierefreier Browser“.

Das Öffnen eines Artikels markiert ihn als gelesen, sofern Sie dieses Verhalten
nicht geändert haben.

## Gelesene und ungelesene Artikel {#read-status}

- Backspace oder „Gelesen/Ungelesen umschalten“ kehrt den Status des
  ausgewählten Artikels um.
- Ctrl+Shift+R markiert alles in der aktuellen Ansicht als gelesen.
- „Alle Einträge als gelesen markieren“ im Kontextmenü eines Feeds oder einer
  Kategorie tut dasselbe für diesen Zweig.
- „Als gelesen markieren“ und „Als ungelesen markieren“ im Kontextmenü der
  Artikelliste wirken auf die gesamte Auswahl und nennen die Anzahl der
  betroffenen Artikel.

Die Anzahl der ungelesenen Artikel steht im Baum neben jedem Feed. Der
Artikelfilter kann gelesene Artikel ganz ausblenden.

## Favoriten {#favorites}

Ctrl+D fügt den ausgewählten Artikel zu den Favoriten hinzu oder entfernt ihn,
wenn er bereits dort ist. Die Ansicht „Favoriten“ im Baum listet alles auf, was
Sie markiert haben.

Favoriten überdauern die Aufbewahrungsrichtlinie: Ein markierter Artikel wird
nicht entfernt, wenn ältere Artikel aufgeräumt werden. „Favorit“ ist außerdem
als Bedingung in intelligenten Ordnern und Filterregeln nutzbar.

## Gelöschte Artikel {#deleted-articles}

Was „Löschen“ bewirkt, ist unter „Einstellungen“, „Allgemein“ bei „Wenn ich
einen Artikel lösche:“ einstellbar:

- In die gelöschten Artikel verschieben, von wo er wiederhergestellt werden kann.
- Endgültig entfernen.
- In eine Kategorie verschieben, die Sie angeben.

Mit der ersten Einstellung listet die Ansicht „Gelöschte Artikel“ im Baum auf,
was Sie entfernt haben, „Wiederherstellen“ holt einen Artikel zurück, und das
Löschen innerhalb dieser Ansicht entfernt ihn endgültig.

„Vor dem Löschen von Artikeln bestätigen“ steuert die Bestätigungsabfrage.
Shift+Delete überspringt sie immer.

## Volltext-Wiederherstellung {#full-text}

Viele Feeds veröffentlichen nur eine Überschrift und ein, zwei Sätze. BlindRSS
kann die Artikelseite abrufen und den eigentlichen Text extrahieren, sodass der
Lesebereich den ganzen Artikel statt eines Anrisses zeigt.

Das geschieht automatisch im Hintergrund, während Sie sich durch die Liste
bewegen, und das Ergebnis wird zwischengespeichert. „Volltext im Hintergrund
zwischenspeichern“ unter „Einstellungen“, „Feeds && Artikel“ lädt die Artikel
rund um Ihre Position im Voraus, sodass das Weitergehen in der Liste nicht auf
das Netzwerk wartet.

Weigert sich eine Website ganz, gelesen zu werden, steckt meist eine
Browserprüfung dahinter. Siehe „Website-Cookies importieren“.

## HTML-Volltextansicht {#rich-view}

Ctrl+Shift+H schaltet den Lesebereich auf die HTML-Ansicht um, die den Artikel
so darstellt, wie es ein Browser täte – mit Überschriften, Listen, Tabellen und
Links als echten Elementen, durch die ein Bildschirmleser mit seinen eigenen
Strukturbefehlen navigieren kann.

Die reine Textansicht ist die Voreinstellung, weil sie schneller ist und nie
überrascht. Die HTML-Ansicht lohnt sich bei Artikeln, deren Struktur Bedeutung
trägt.

Ein Feed kann über seine Feed-Eigenschaften so eingestellt werden, dass er
immer in der HTML-Ansicht öffnet; Links in der HTML-Ansicht öffnen sich in
Ihrem Webbrowser statt innerhalb der Ansicht.

## Barrierefreier Browser {#accessible-browser}

&Ansicht, „Barrierefreien Browser öffnen“ öffnet eine Seite innerhalb von
BlindRSS in einem Fenster, das für das Lesen mit einem Bildschirmleser gebaut
ist, statt sie an Ihren Webbrowser zu übergeben.

Es ist das richtige Werkzeug für eine Seite, die gelesen statt bedient werden
soll, und für Websites, deren eigene Oberfläche schwer zu navigieren ist. Es
teilt sich die Cookie- und Browser-Identitätseinstellungen von BlindRSS, sodass
sich Seiten hinter einer Browserprüfung auch hier öffnen, sobald Sie Cookies
dafür importiert haben.

## YouTube-Videos {#youtube}

Eine YouTube-Kanal- oder Playlist-Adresse kann wie jeder Feed abonniert werden.
Die Videos treffen dann als Artikel ein, mit Beschreibung, Transkript und
Kapitelliste im Text, sodass ein Video gelesen statt angesehen werden kann.

Die Wiedergabe läuft über yt-dlp. „Einstellungen“, „YouTube“ steuert sie:

- Eine Cookie-Datei, mit der BlindRSS altersbeschränkte und
  mitgliederexklusive Videos sehen kann, auf die Sie Zugriff haben. Sie kann
  direkt aus einem Browser importiert oder automatisch aus
  cookies.txt-Exporten in Ihrem Downloads-Ordner übernommen werden.
- „YouTube-Inhalte zuerst herunterladen und dann abspielen“, was langsamer
  startet und deutlich zuverlässiger ist.
- Der Ordner für den Wiedergabe-Cache und seine Maximalgröße, mit einer
  Schaltfläche zum Leeren.

„YouTube Takeout importieren“ abonniert in einem Schritt jeden Kanal, dem Sie
bereits folgen.

## Foren- und Diskussionsfäden {#forums}

Reddit, Lemmy, Groups.io und Google Groups werden als ganze Fäden gelesen statt
Beitrag für Beitrag: Das Öffnen einer Diskussion liefert den ursprünglichen
Beitrag und die Antworten als einen zusammenhängenden Text, was sich weit
schneller liest als ein Faden im Browser.

Das Abonnieren funktioniert wie bei jedem Feed – fügen Sie die Adresse des
Subreddits, der Community oder der Gruppe ein. GitHub-Repositorys werden
genauso unterstützt, ebenso Mastodon-, Bluesky- und PieFed-Konten und
-Communitys.

## Ausschneiden, Kopieren und Einfügen {#clipboard}

Das Menü &Bearbeiten enthält die üblichen Zwischenablage-Befehle –
&Ausschneiden (Ctrl+X), &Kopieren (Ctrl+C), &Einfügen (Ctrl+V) und &Alles
auswählen (Ctrl+A) – und sie funktionieren in jedem Textfeld und im Lesebereich.

BlindRSS ergänzt Befehle, die Dinge kopieren, die es selbst kennt:

- „Link kopieren“, die Adresse des Artikels.
- „Medienlink kopieren“, die Adresse seines Audios oder Videos.
- „Text kopieren“, den Artikeltext, wie er im Lesebereich steht.
- „Feed-URL kopieren“, die Adresse des ausgewählten Feeds.
- „Bildlink kopieren“ bei einem Artikel mit Bild.

## Der integrierte Player {#player}

BlindRSS spielt Podcast- und Video-Anhänge selbst ab, über VLC, sodass die
Wiedergabe die Anwendung nie verlässt. Ctrl+Shift+P blendet das Player-Fenster
ein oder aus; die Wiedergabe läuft in beiden Fällen weiter.

Die Wiedergabe wird durch einen lokalen Range-Cache-Proxy geglättet – deshalb
ist das Spulen in einer langen Episode auch bei langsamer Verbindung zügig.
Streams, die aufgelöst werden müssen – YouTube, Rumble, Odysee – laufen zuerst
durch yt-dlp.

„Player-Fenster beim Start der Wiedergabe anzeigen“ unter „Einstellungen“,
„Medienplayer“ entscheidet, ob das Fenster von selbst erscheint, wenn etwas
startet.

## Player-Bedienelemente {#player-controls}

Das Player-Fenster enthält in dieser Tab-Reihenfolge: den Wiedergabestatus, den
Positionsregler, die verstrichene und die Gesamtzeit, die Schaltflächen zum
Zurück- und Vorspulen, das Geschwindigkeitsfeld, die Kapitelschaltfläche und
den Lautstärkeregler. Jedes davon ist über die Tastatur erreichbar und
bedienbar, und jedes sagt seinen aktuellen Wert an.

- Ctrl+P startet und pausiert die Wiedergabe.
- Ctrl+S stoppt.
- Ctrl+Left und Ctrl+Right spulen zurück und vor und wiederholen beim Halten.
  Unter macOS tun Option+Left und Option+Right dasselbe, weil Ctrl+Left und
  Ctrl+Right dort zu Mission Control gehören.
- Ctrl+Up und Ctrl+Down ändern die Lautstärke.

Die Spul- und Lautstärketasten funktionieren überall in BlindRSS, solange etwas
läuft, auch aus einem Dialogfeld heraus – Sie müssen also nie das
Player-Fenster suchen, um zu pausieren.

## Tastenkürzel des Players {#player-shortcuts}

- Ctrl+Shift+P: Player-Fenster anzeigen oder ausblenden.
- Ctrl+P: Wiedergabe oder Pause.
- Ctrl+S: Stopp.
- Ctrl+Left und Ctrl+Right: zurück- und vorspulen (Option+Left und
  Option+Right unter macOS).
- Ctrl+Up und Ctrl+Down: Lautstärke lauter und leiser.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: schneller, langsamer, zurück zur
  normalen Geschwindigkeit.
- Ctrl+Shift+E: der Equalizer.
- Ctrl+Shift+C: die Wiedergabe-Warteschlange.
- Ctrl+Shift+T und Ctrl+Shift+V: nächstes und vorheriges Element der
  Warteschlange.

All das lässt sich unter E&xtras, &Tastenkürzel... neu belegen. Die
Geschwindigkeitsbefehle liegen bewusst auf Buchstaben statt auf
Ctrl+Shift+Ziffer oder Ctrl+Shift+Punkt, weil Windows und manche
NVDA-Erweiterungen diese Kombinationen abfangen, bevor eine Anwendung sie sieht.

## Wiedergabegeschwindigkeit {#playback-speed}

&Player, Wiedergabe&geschwindigkeit ändert, wie schnell Medien abgespielt
werden, von halber bis dreifacher Geschwindigkeit, bei gleichbleibender
Tonhöhe.

- Ctrl+Shift+U beschleunigt, Ctrl+Shift+D verlangsamt, Ctrl+Shift+N kehrt zu 1x
  zurück.
- Das Untermenü hat feste Stufen: 0,5x, 0,75x, 1x, 1,25x, 1,5x, 1,75x, 2x, 2,5x
  und 3x.
- Das Player-Fenster hat ein Geschwindigkeitsfeld, das Sie direkt setzen können.

„Standard-Wiedergabegeschwindigkeit:“ unter „Einstellungen“, „Medienplayer“
legt fest, mit welcher Geschwindigkeit alles beginnt.

## Equalizer {#equalizer}

Ctrl+Shift+E oder &Player, &Equalizer... öffnet einen Zehnband-Equalizer mit
Vorverstärkung.

- „Equalizer aktivieren“ schaltet das Ganze ein und aus.
- Jedes Band ist ein Regler, der seine Verstärkung beim Ändern ansagt.
- „Als Voreinstellung speichern...“ legt die aktuellen Bänder unter einem Namen
  ab; „Voreinstellung löschen“ entfernt eine.
- „Zurücksetzen (Neutral)“ setzt jedes Band auf null.

Der Equalizer gilt für alles, was BlindRSS abspielt, und seine Einstellung
bleibt erhalten.

## Kapitel {#chapters}

Podcasts und YouTube-Videos tragen oft Kapitel. Wenn das laufende Element
welche hat, listet &Player, Kapitel sie auf, und das Anspringen eines Kapitels
spult dorthin.

- Das Kapitel-Untermenü füllt sich, sobald die Kapitel des Elements bekannt
  sind, und meldet „Keine Kapitel verfügbar“, wenn es keine gibt.
- Das Player-Fenster hat eine Kapitelschaltfläche und ein Kapitelfeld.
- „Kapitel-Links“ im Kontextmenü der Artikelliste listet die Links auf, die
  eine Kapitelbeschreibung enthält.

Kapitel werden im Hintergrund geladen, während Sie sich durch die Liste
bewegen, sodass sie meist bereit sind, bevor Sie auf Wiedergabe drücken.

## Wiedergabe-Warteschlange {#play-queue}

Die Wiedergabe-Warteschlange ist die Liste dessen, was als Nächstes läuft.

- Ctrl+Shift+C öffnet das Warteschlangenfenster.
- Ctrl+Shift+T und Ctrl+Shift+V spielen das nächste und das vorherige Element.
- „Zur Wiedergabe-Warteschlange hinzufügen“ und „Aus der Wiedergabe-
  Warteschlange entfernen“ im Kontextmenü der Artikelliste ändern sie.

Im Warteschlangenfenster startet „Wiedergabe“ das ausgewählte Element, „Nach
oben verschieben“ und „Nach unten verschieben“ ordnen die Warteschlange um,
„Entfernen“ nimmt ein Element heraus und „Alle löschen“ leert sie. Die
Warteschlange überdauert einen Neustart.

## Übertragung an andere Geräte {#casting}

BlindRSS kann das, was es abspielt, an ein Gerät in Ihrem Netzwerk senden: Chromecast, AirPlay-Lautsprecher, DLNA/UPnP-Renderer, Sonos-Lautsprecher, Roku-Player und Kodi. Eine Folge läuft auf dem Gerät an der Stelle weiter, an der sie gerade war, und Pause, Spulen und die Position funktionieren dort wie lokal (Roku kann nicht spulen).

Wählen Sie das Gerät im Übertragungsdialog; BlindRSS streamt über seinen
eigenen lokalen Proxy, sodass auch ein Gerät, das die Originaladresse nicht
selbst abrufen kann, das Element abspielt. Die Transportsteuerung funktioniert
währenddessen weiter aus BlindRSS heraus.

## Stille überspringen {#silence-skipping}

„Stille überspringen (experimentell)“ unter „Einstellungen“, „Medienplayer“
erkennt stille Passagen während der Wiedergabe und überspringt sie, was
Gesprächs-Podcasts mit langen Pausen spürbar verkürzt.

Es analysiert den Ton während der Wiedergabe, kostet also etwas Rechenleistung
und ist als experimentell gekennzeichnet. Schalten Sie es ab, wenn die
Wiedergabe stockt.

## Medien herunterladen {#downloads}

- „Download“ speichert das Audio oder Video des ausgewählten Artikels im
  Standardformat.
- „Download als“ lässt Sie zuerst das Format wählen.

Downloads müssen mit „Downloads aktivieren“ in den Einstellungen eingeschaltet
werden. Der Download-Ordner, die Aufbewahrungsrichtlinie und das
Standard-Videodownloadformat werden auf derselben Seite festgelegt; der
Standardordner ist Ihr Downloads-Ordner.

Der Fortschritt erscheint im zweiten Feld der Statusleiste, und
heruntergeladene Elemente werden anschließend von der Festplatte statt über das
Netzwerk abgespielt. Das Podcast-Archiv kann den gesamten Rückkatalog eines
Podcasts in einem Stapel herunterladen.

## Einstellungen {#settings}

E&xtras, &Einstellungen... (Ctrl+Komma) enthält alle Optionen, auf
Registerkarten: Allgemein, Feeds && Artikel, YouTube, Medienplayer, Anbieter,
Benachrichtigungen, Übersetzen, Listenüberschriften, Erweitert und
CAPTCHA-Lösung.

Ctrl+Tab und Ctrl+Shift+Tab wechseln zwischen den Registerkarten; Tab bewegt
sich durch die Steuerelemente der aktuellen Registerkarte. OK übernimmt alles,
Abbrechen verwirft alles. Die Reihenfolge der Registerkarten bleibt zwischen
Versionen stabil, weil sie zur Muskelerinnerung wird.

F1 auf einer Registerkarte öffnet den Abschnitt dieses Handbuchs zu dieser
Registerkarte.

## Einstellungen: Allgemein {#settings-general}

- Sprache der Oberfläche und ob BlindRSS Ihrer Systemsprache folgt. Eine
  Änderung wirkt nach einem Neustart. Siehe „Sprache der Oberfläche“.
- „Zuletzt ausgewählten Feed/Ordner beim Start merken“.
- „Vor dem Löschen von Artikeln bestätigen“ und was das Löschen bewirkt – in
  die gelöschten Artikel verschieben, endgültig löschen oder in eine von Ihnen
  angegebene Kategorie verschieben.
- „Debug-Modus (Konsole beim Start anzeigen)“, wodurch außerdem eine rotierende
  blindrss.log neben Ihren Daten geschrieben wird.
- Start und Infobereich: beim Schließen in den Infobereich, beim Minimieren in
  den Infobereich, im Infobereich starten, immer maximiert starten und beim
  Start nach Updates suchen.

## Einstellungen: Feeds && Artikel {#settings-feeds}

- Das automatische Aktualisierungsintervall, von fünf Minuten bis vier Stunden.
- Ob die Suche nur Titel oder Titel und Artikeltext durchsucht.
- Maximale gleichzeitige Aktualisierungen, maximale Verbindungen pro Host, die
  Zeitüberschreitung pro Feed und wie oft ein fehlgeschlagener Feed erneut
  versucht wird.
- Maximale zwischengespeicherte Ansichten und „Volltext im Hintergrund
  zwischenspeichern“.
- „Feeds beim Start automatisch aktualisieren“ und die Startlast: den Cache
  verwenden, beim Start vollständig aktualisieren oder immer vollständig
  aktualisieren.
- Die Artikelaufbewahrung, die bestimmt, wie lange Artikel behalten werden.
  Favoriten werden von der Aufbewahrung nie entfernt.
- Wie der Artikeltext dargestellt wird: Überschriften ansagen, Listenelemente
  mit Aufzählungszeichen und Nummern kennzeichnen, Zitate kennzeichnen, Links
  mit ihrer Adresse anzeigen, Tabellen beschreiben und Bild-Alt-Text
  einbeziehen.

## Einstellungen: YouTube {#settings-youtube}

- Die yt-dlp-Cookie-Datei, mit einer Schaltfläche zum Durchsuchen, einer
  Schaltfläche „Aus Browser importieren“ und einer Option, cookies.txt-Exporte
  automatisch aus Ihrem Downloads-Ordner zu übernehmen.
- Das direkte Auslesen von Cookies aus einem installierten Browser.
- „YouTube-Inhalte zuerst herunterladen und dann abspielen“, was langsamer
  startet, aber die zuverlässigste Option ist.
- Der Ordner für den YouTube-Wiedergabe-Cache, seine Maximalgröße in Megabyte
  und eine Schaltfläche zum sofortigen Leeren.

Cookies sind das, was altersbeschränkte und mitgliederexklusive Videos
abspielbar macht, und sie sind das, wonach ein Fehler „Melde dich an, um zu
bestätigen, dass du kein Bot bist“ verlangt.

## Einstellungen: Medienplayer {#settings-media-player}

- Die bevorzugte Soundkarte oder der Systemstandard.
- „Stille überspringen (experimentell)“. Siehe „Stille überspringen“.
- Die Standard-Wiedergabegeschwindigkeit.
- „Player-Fenster beim Start der Wiedergabe anzeigen“.
- Die Größe des Netzwerk-Caches in Millisekunden, ein Kompromiss zwischen
  Startverzögerung und Robustheit bei langsamer Verbindung.
- Pfade zu ffmpeg, ffprobe und yt-dlp. Lassen Sie einen Pfad leer für die
  automatische Erkennung; ein gesetzter Pfad überschreibt die Erkennung, und
  das Erkannte steht jeweils daneben.
- Downloads: ob Downloads aktiviert sind, der Download-Ordner, die
  Aufbewahrungsrichtlinie und das Standard-Videodownloadformat.
- Klänge: ob BlindRSS seine Hinweistöne abspielt.

## Einstellungen: Anbieter {#settings-provider}

Legt fest, wo Ihre Abonnements liegen: lokal in BlindRSS oder in einem
gehosteten Konto. Siehe „Online-Konten und Anbieter“ für das, was jedes davon
benötigt.

Die Seite zeigt, welcher Anbieter aktiv ist, und die zugehörigen Zugangsdaten –
eine Miniflux-Adresse und ein API-Schlüssel, eine Inoreader-App-ID und ein
-Schlüssel mit einer Schaltfläche zum Autorisieren oder eine E-Mail-Adresse und
ein Passwort für The Old Reader oder BazQux. „Autorisierung löschen“ meldet ein
Inoreader-Konto ab.

Der lokale Anbieter verwendet die Feeds, die Sie in der Anwendung mit „Feed
hinzufügen“ und „OPML importieren“ anlegen.

## Einstellungen: Benachrichtigungen {#settings-notifications}

- „Benachrichtigungen für neue Artikel aktivieren“ und ob der Name des Feeds im
  Benachrichtigungstext erscheint.
- Die Höchstzahl an Benachrichtigungen pro Aktualisierung und ob eine
  Zusammenfassung angezeigt wird, sobald diese Grenze erreicht ist.
- „Testbenachrichtigung“ sendet sofort eine.
- „Feeds ausschließen...“ wählt Feeds, die nie benachrichtigen.
- Ansagen: welche Ereignisse BlindRSS direkt an Ihren Bildschirmleser meldet,
  einzeln einstellbar, mit einer Schaltfläche für eine Testansage, die über
  Sprache und Braille gesendet wird.

## Einstellungen: Übersetzen {#settings-translate}

Schaltet die automatische Übersetzung von Artikelinhalten ein und wählt den
Dienst, der sie ausführt.

- „Automatische Übersetzung des Artikelinhalts aktivieren“.
- Den Anbieter: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini oder Qwen.
- Die Zielsprache, aus der Liste gewählt oder als Code wie en, es, fr oder
  pt-BR eingegeben.
- Einen API-Schlüssel für den gewählten Anbieter und optional ein bestimmtes
  Modell. Für OpenRouter holt „OpenRouter-Modelle laden“ die verfügbare
  Modellliste.

Grok und Groq sind verschiedene Dienste mit verwirrend ähnlichen Namen: Grok
gehört zu xAI, mit Schlüsseln von console.x.ai, die mit „xai-“ beginnen; Groq
betreibt LLaMA und Mistral, mit kostenlosen Schlüsseln von console.groq.com,
die mit „gsk_“ beginnen.

Dies übersetzt Artikeltexte. Um die Sprache der Oberfläche von BlindRSS zu
ändern, siehe „Sprache der Oberfläche“.

## Einstellungen: Listenüberschriften {#settings-list-headers}

Legt das globale Spaltenlayout der Artikelliste fest: welche Spalten
erscheinen, in welcher Reihenfolge und wie breit. Siehe „Spalten der
Artikelliste“.

Ein einzelner Feed kann dies über seine eigenen Feed-Eigenschaften
überschreiben.

## Einstellungen: Erweitert {#settings-advanced}

- Speicherort der Daten: Datenbank und Einstellungen im Benutzerdatenordner
  oder im Anwendungsordner ablegen, mit beiden angezeigten Pfaden. Die Option
  „Anwendungsordner“ ist das, was eine portable Installation portabel macht.
- Updates: „Automatische Installation von Updates ohne Bestätigung“.
- Browser-Identifikation: als welcher Browser sich BlindRSS beim Abrufen von
  Feeds ausgibt, oder eine eigene User-Agent-Zeichenkette, die Sie eingeben.
  Die wirksame Zeichenkette steht darunter. Das ist wichtig bei Websites, die
  unbekannte Clients abweisen.
- Videosuche: „Erwachsenenseiten in der Videosuche aktivieren“, standardmäßig
  aus.

## Einstellungen: CAPTCHA-Lösung {#settings-captcha}

Ein optionaler, kostenpflichtiger letzter Ausweg für Websites, die mit einem
CAPTCHA antworten, an dem importierte Cookies scheitern.

„CAPTCHA-Lösungsdienst aktivieren“ schaltet ihn ein, und das Feld für den
API-Schlüssel enthält Ihren Kontoschlüssel beim Lösungsdienst. Es fallen
Gebühren pro Lösung an – deshalb ist er standardmäßig aus und wird erst
versucht, wenn alles andere gescheitert ist.

Versuchen Sie es zuerst mit „Website-Cookies importieren“; das ist kostenlos
und löst die meisten Fälle.

## Online-Konten und Anbieter {#providers}

BlindRSS kann Ihre Abonnements selbst verwalten oder sie aus einem gehosteten
Konto lesen. „Einstellungen“, „Anbieter“ legt fest, was gilt.

- Lokal: Die Abonnements liegen in der eigenen Datenbank von BlindRSS auf
  diesem Rechner. Es wird nichts irgendwohin synchronisiert.
- Miniflux: benötigt die Adresse Ihres Miniflux-Servers und einen API-Schlüssel
  aus Ihren Miniflux-Kontoeinstellungen.
- Inoreader: benötigt eine App-ID und einen App-Schlüssel von der
  Entwicklerseite von Inoreader und danach die Schaltfläche zum Autorisieren.
- The Old Reader: benötigt die E-Mail-Adresse und das Passwort Ihres Kontos.
- BazQux: benötigt die E-Mail-Adresse und das Passwort Ihres Kontos.

Bei einem gehosteten Anbieter gehören Lesestatus, Abonnements und Kategorien
dem Konto und folgen Ihnen daher auf jedes andere Gerät, das mit demselben
Konto angemeldet ist. Manche Anbieter führen Kategorien in einer einzigen
flachen Liste; BlindRSS weist darauf hin, statt eine Verschachtelung
anzubieten, die nicht bestehen bliebe.

## Benachrichtigungen {#notifications}

BlindRSS zeigt eine Systembenachrichtigung, wenn neue Artikel eintreffen,
gemäß „Einstellungen“, „Benachrichtigungen“.

- Benachrichtigungen lassen sich ganz abschalten.
- Der Feed-Name kann im Text enthalten sein.
- Eine Obergrenze begrenzt, wie viele pro Aktualisierung eintreffen, mit einer
  optionalen Zusammenfassung, sobald sie erreicht ist.
- Einzelne Feeds können ausgeschlossen werden, entweder über „Feeds
  ausschließen...“ in den Einstellungen oder über „Benachrichtigungen für
  diesen Feed“ im Kontextmenü des Feeds.
- Eine Filterregel kann die Benachrichtigung für die Artikel unterdrücken, auf
  die sie zutrifft.

Davon getrennt melden Ansagen ausgewählte Ereignisse direkt an Ihren
Bildschirmleser über dessen eigene Schnittstelle (NVDA oder JAWS) sowie über
Braille, was auch dann durchkommt, wenn eine Systembenachrichtigung es nicht
tut.

## Artikelübersetzung {#translation}

Wenn die Übersetzung unter „Einstellungen“, „Übersetzen“ aktiviert ist, wird
der Artikeltext beim Lesen mit dem von Ihnen eingerichteten KI-Dienst in Ihre
Zielsprache übersetzt.

Die Übersetzung erfolgt bei Bedarf und wird zwischengespeichert, sodass das
erneute Lesen eines Artikels nicht zweimal kostet. Sie benötigt eine
Internetverbindung und Ihren eigenen API-Schlüssel beim gewählten Dienst.

Die Anwendungsoberfläche wird getrennt davon über eigene Kataloge übersetzt.
Siehe „Sprache der Oberfläche“.

## Website-Cookies importieren {#site-cookies}

Manche Websites setzen eine Browser-Überprüfungsseite – typischerweise eine
Cloudflare-Prüfung „Überprüfung Ihres Browsers“ – vor ihre Inhalte. Solche
Websites antworten nur einer Sitzung, die die Prüfung bereits in einem echten
Browser bestanden hat; BlindRSS kann sie also nicht von sich aus abrufen.

E&xtras, „Website-Cookies importieren“ gibt ihm diese Sitzung:

1. Öffnen Sie die Website in Ihrem Webbrowser und warten Sie, bis sie fertig
   geladen ist.
2. Exportieren Sie ihre Cookies mit einer cookies.txt-Browsererweiterung in
   eine cookies.txt-Datei. Für Chrome-basierte Browser verweist das Dialogfeld
   auf „Get cookies.txt LOCALLY“.
3. Wählen Sie die exportierte Datei im Dialogfeld aus.
4. Fügen Sie in das Feld darunter die User-Agent-Zeichenkette Ihres Browsers
   ein. Eine Websuche nach „what is my user agent“ zeigt sie an. Cloudflare
   verlangt genau den User-Agent, für den das Cookie ausgestellt wurde – das
   ist also wichtig.

Browser der Firefox-Familie haben einen Ein-Klick-Weg: „Aus Browser
importieren...“ liest deren Cookie-Datenbank direkt. Chromium-basierte Browser
verschlüsseln ihre – deshalb brauchen sie die Erweiterung.

## Tastenkürzel {#keyboard-shortcuts}

E&xtras, &Tastenkürzel... listet jeden Befehl in BlindRSS nach Kategorie
gruppiert mit seiner aktuellen Taste auf und lässt Sie jede davon ändern.

- Wählen Sie einen Befehl und dann „Tastenkürzel ändern...“. Das
  Aufnahmedialogfeld zeichnet dann die nächste Tastenkombination auf, die Sie
  drücken.
- „Tastenkürzel entfernen“ lässt einen Befehl ohne Belegung; er funktioniert
  weiterhin über sein Menü.
- „Alle auf Standard zurücksetzen“ stellt die ausgelieferten Tasten wieder her.

Tastenkürzel werden vor den Menü-Zugriffstasten verarbeitet und wirken im
ganzen Fenster, auch wenn das Player-Fenster den Fokus hat; der Tastaturweg
meldet sich an, wo der Menüweg still bleibt. Ihre Änderungen werden mit Ihren
Einstellungen gespeichert und überdauern Updates.

## Standard-Tastenkürzel {#shortcuts-reference}

Feeds:

- Ctrl+N: Feed hinzufügen.
- F5: Feeds aktualisieren. Shift+F5: Aktualisierung stoppen. Ctrl+F5: den
  ausgewählten Feed aktualisieren.
- F2: Feed oder Kategorie bearbeiten.
- Ctrl+Shift+R: Alle Einträge als gelesen markieren.
- Ctrl+Shift+F: Podcast oder RSS-Feed finden.

Artikel und Ansichten:

- Ctrl+D: zu den Favoriten hinzufügen oder daraus entfernen.
- Backspace: gelesen/ungelesen umschalten. Delete: löschen. Shift+Delete: ohne
  Bestätigung löschen.
- Ctrl+E: Fokus auf das Suchfeld.
- Ctrl+Shift+H: HTML-Volltextansicht.
- Ctrl+1 bis Ctrl+3: alle, ungelesene, gelesene. Ctrl+4 bis Ctrl+6: mit und
  ohne Medien, nur mit Medien, nur ohne Medien.

Player:

- Ctrl+P: Wiedergabe oder Pause. Ctrl+S: Stopp. Ctrl+Shift+P: Player anzeigen
  oder ausblenden.
- Ctrl+Left und Ctrl+Right: spulen. Ctrl+Up und Ctrl+Down: Lautstärke.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: schneller, langsamer, normal.
- Ctrl+Shift+E: Equalizer.
- Ctrl+Shift+C: Wiedergabe-Warteschlange. Ctrl+Shift+T und Ctrl+Shift+V:
  nächstes und vorheriges.

Anwendung:

- F1: dieses Handbuch, geöffnet an der Stelle, die zu dem passt, was Sie gerade
  verwenden.
- Ctrl+Komma: Einstellungen.
- Ctrl+Shift+A: die laufende Version ansagen.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: ausschneiden, kopieren, einfügen, alles
  auswählen.

Befehle, die hier nicht aufgeführt sind, werden ohne Belegung ausgeliefert und
können unter E&xtras, &Tastenkürzel... beliebig belegt werden.

## Sprache der Oberfläche {#language}

Die Oberfläche von BlindRSS ist in fünfzehn Sprachen übersetzt.
„Einstellungen“, „Allgemein“ wählt eine aus oder lässt sie der Systemsprache
folgen. Die Änderung wirkt nach einem Neustart.

Übersetzungen werden auch zwischen den Anwendungsversionen ausgeliefert, sodass
eine korrigierte Übersetzung Sie erreicht, ohne auf eine neue Version zu warten.

Dieses Handbuch folgt derselben Sprache, sofern es dafür eine Übersetzung gibt,
und fällt sonst auf Englisch zurück.

## Infobereichssymbol und Medientasten {#tray}

BlindRSS kann im Infobereich leben. „Einstellungen“, „Allgemein“ entscheidet,
ob das Schließen des Fensters es dorthin schickt, ob das Minimieren es tut und
ob es dort startet.

Das Infobereichssymbol hat Wiedergabesteuerungen und öffnet das Hauptfenster
wieder. Die Medientasten Ihrer Tastatur – Wiedergabe/Pause, Stopp, Weiter,
Zurück – steuern den Player von BlindRSS systemweit.

## Verknüpfungen hinzufügen {#desktop-shortcuts}

&Datei, &Verknüpfungen hinzufügen... legt Verknüpfungen zu BlindRSS auf dem
Desktop, im Startmenü und in der Taskleiste an. Setzen Sie die gewünschten
Haken und wählen Sie OK; das Ergebnis jeder einzelnen wird zurückgemeldet.

Ein Startmenü-Eintrag ist außerdem das, was Windows verlangt, bevor eine
Anwendung Benachrichtigungen anzeigen darf – er lohnt sich also, selbst wenn
Sie BlindRSS anders starten.

## Nach Updates suchen {#updates}

&Hilfe, Nach &Updates suchen... fragt, ob eine neuere Version verfügbar ist,
und bietet an, sie zu installieren.

Jedes Update wird vor der Installation geprüft: Sein SHA-256 muss zum
veröffentlichten Manifest passen, und unter Windows muss seine
Authenticode-Signatur gültig sein. Ein Update, das eine der beiden Prüfungen
nicht besteht, wird nicht installiert.

„Beim Start nach Updates suchen“ unter „Einstellungen“, „Allgemein“ erledigt
das automatisch, und „Automatische Installation von Updates ohne Bestätigung“
unter „Einstellungen“, „Erweitert“ spielt sie ohne Rückfrage ein. Ihre
Einstellungen, Ihre Datenbank und Ihre Downloads bleiben von einem Update
unberührt.

## Version ansagen {#version}

&Hilfe, &Version ansagen (Ctrl+Shift+A) sagt die laufende BlindRSS-Version
direkt über Ihren Bildschirmleser an.

Der eigene Befehl eines Bildschirmlesers zum Melden der Anwendungsversion liest
die Versionsressource der ausführbaren Datei, was bei einer installierten
Fassung funktioniert, bei einem Start aus dem Quelltext aber die Version von
Python meldet. Dieser Befehl liefert in beiden Fällen die richtige Antwort.

## Über BlindRSS {#about}

&Hilfe, &Über zeigt die Version, die Lizenz und Links: das GitHub-Profil, das
Repository und das Änderungsprotokoll.

BlindRSS steht unter der MIT-Lizenz – verwenden, ändern, weitergeben oder für
die Paketquellen einer Distribution paketieren, ohne dass eine Erlaubnis nötig
ist.

## Dieses Hilfefenster verwenden {#help-window}

Dieses Fenster ist ein schlichter, vollständig über die Tastatur bedienbarer
Leser für das Handbuch.

- Die Inhaltsliste enthält jeden Abschnitt. Gehen Sie mit den Pfeiltasten
  hindurch; das Auswählen eines Abschnitts springt im Text dorthin und sagt
  seinen Titel an.
- Das Textfeld ist schreibgeschützt und markierbar, sodass ein Bildschirmleser
  es Zeile für Zeile lesen kann und Sie daraus kopieren können.
- Ctrl+F springt zum Suchfeld. Geben Sie ein Wort ein und drücken Sie Enter, um
  zum nächsten Vorkommen zu springen.
- F3 findet das nächste Vorkommen, Shift+F3 das vorherige. Die Suche läuft
  umlaufend weiter.
- Tab und Shift+Tab wechseln zwischen Suchfeld, Inhaltsliste und Text.
- Escape schließt das Fenster.

F1 öffnet überall in BlindRSS dieses Fenster an dem Abschnitt, der zu dem passt,
was Sie gerade verwenden – dem fokussierten Steuerelement, dem aktiven
Dialogfeld, dem hervorgehobenen Menüpunkt oder dem Player. Gibt es dafür keinen
Abschnitt, öffnet das Handbuch am Anfang.

Das Handbuch wird in der Oberflächensprache von BlindRSS angezeigt, sofern eine
Übersetzung davon vorliegt, und sonst auf Englisch.

## Fehlersuche {#troubleshooting}

Ein Feed aktualisiert sich nicht mehr. Schauen Sie unter „Feeds mit Fehlern“
nach dem Grund. Ein umgezogener Feed braucht eine korrigierte Adresse in den
Feed-Eigenschaften; eine Website, die eine Browserprüfung verlangt, braucht
„Website-Cookies importieren“.

Ein YouTube-Video spielt nicht ab. Importieren Sie YouTube-Cookies unter
„Einstellungen“, „YouTube“ und schalten Sie „YouTube-Inhalte zuerst
herunterladen und dann abspielen“ ein. Ein Fehler „Melde dich an, um zu
bestätigen, dass du kein Bot bist“ bedeutet immer Cookies.

Die Wiedergabe stockt. Erhöhen Sie den Netzwerk-Cache unter „Einstellungen“,
„Medienplayer“ und schalten Sie „Stille überspringen“ ab, das experimentell ist
und Rechenleistung kostet.

Eine Website liefert überhaupt nichts. Ändern Sie die Browser-Identifikation
unter „Einstellungen“, „Erweitert“; manche Websites weisen unbekannte Clients
rundheraus ab.

Es wird nichts gesprochen, wenn ein Befehl ausgeführt wird. Prüfen Sie die
Ansagen unter „Einstellungen“, „Benachrichtigungen“ – jedes Ereignis lässt sich
einzeln ein- und ausschalten, und es gibt eine Testschaltfläche.

Etwas verhält sich seltsam und Sie möchten es melden. Schalten Sie den
Debug-Modus unter „Einstellungen“, „Allgemein“ ein, führen Sie das Problem
herbei und hängen Sie die blindrss.log an, die neben Ihren Einstellungen und
Daten geschrieben wird.

## Unterstützung und Community {#support}

Fehler und Funktionswünsche gehören in den Issue-Tracker auf GitHub unter
github.com/serrebidev/BlindRSS/issues.

Für Fragen, Hilfe und Neuigkeiten zu Versionen ist die Gruppe SerrebiProjects
auf Telegram unter t.me/SerrebiProjects der schnellste Weg zu einer Antwort.

Übersetzungen sind immer willkommen. Wenn Sie eine der unterstützten Sprachen
sprechen und etwas falsch, holprig oder einfach schief klingt, wird ein Pull
Request, der es korrigiert, mit ziemlicher Sicherheit angenommen – siehe
locale/README.md im Repository zum Aufbau der Dateien. Dasselbe gilt für dieses
Handbuch: Eine übersetzte Fassung gehört nach docs/help/<sprache>.md, wobei die
{#anchor}-Markierungen genau so bleiben müssen wie in der englischen Datei,
damit die kontextabhängige Hilfe weiter funktioniert.
