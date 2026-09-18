# BlindRSS-gebruikershandleiding

## BlindRSS-gebruikershandleiding {#user-guide}

BlindRSS is een schermlezervriendelijke desktopclient voor RSS en podcasts. Het leest RSS- en Atom-feeds, speelt podcast- en videobijlagen af en werkt zelfstandig of met een gehost account zoals Miniflux, Inoreader, The Old Reader of BazQux.

Deze handleiding staat in de toepassing, dus werkt zonder internetverbinding en webbrowser. Druk overal in BlindRSS op F1 om haar te openen. Als het besturingselement, dialoogvenster, menu-item of venster dat u gebruikt een eigen onderdeel heeft, opent F1 de handleiding op dat onderdeel in plaats van aan het begin.

Alles hier is vanaf het toetsenbord bereikbaar. Gebruik de inhoudslijst om tussen onderdelen te gaan, of het zoekvak om overal in de handleiding een woord te vinden.

## Aan de slag {#getting-started}

Wanneer BlindRSS voor het eerst start, heeft het geen feeds. U kunt er op verschillende manieren toevoegen:

- Druk op Ctrl+N om een feed op adres toe te voegen. Zie Een feed toevoegen.
- Druk op Ctrl+Shift+F om podcast- en feedmappen op naam te doorzoeken. Zie Podcasts en RSS-feeds zoeken.
- Importeer een OPML-bestand dat uit een andere lezer is geëxporteerd. Zie OPML importeren.
- Importeer een YouTube-Takeout-archief om u te abonneren op elk kanaal dat u al volgt. Zie Een YouTube-Takeout-archief importeren.
- Meld u aan bij een gehost account via Extra, Instellingen, Provider; BlindRSS leest dan de abonnementen die al in dat account staan. Zie Onlineaccounts en providers.

Zodra u feeds hebt, drukt u op F5 om ze te vernieuwen. Nieuwe artikelen verschijnen in de artikelenlijst en ongelezen aantallen staan naast elke feed in de boom.

De drie plaatsen die u vroeg zou moeten bezoeken zijn Extra, Instellingen (hoe BlindRSS zich gedraagt), Extra, Sneltoetsen (elke opdracht en toets), en deze handleiding.

## Het hoofdvenster {#main-window}

Het hoofdvenster heeft vier hoofdgebieden plus een menubalk en een statusbalk. Tab en Shift+Tab gaan ertussen; F6 doorloopt deelvensters in de meeste vensterbeheerders.

- De boom met feeds en mappen links.
- Het zoekveld boven de artikelenlijst.
- De artikelenlijst.
- Het leesvenster onder de artikelenlijst.

De menubalk bevat Bestand, Bewerken, Beeld, Speler, Extra en Help. Druk op Alt om hem te bereiken en gebruik dan de pijltjestoetsen. Elk menu-item heeft in elke interfacetaal een toegangstoets; de menubalk loopt aan beide uiteinden rond.

Groottes, de geselecteerde feed en de vensterstatus worden tussen sessies onthouden. "Laatste geselecteerde feed/map bij starten onthouden" in Instellingen, Algemeen bepaalt of BlindRSS opnieuw opent bij de feed die u het laatst las.

## Lijst met feeds en mappen {#feed-tree}

De boom links bevat uw feeds, de categorieën die ze groeperen, Slimme mappen, opgeslagen zoekopdrachten en de ingebouwde weergaven (Alle feeds, Favorieten, Verwijderde artikelen en Feeds met fouten).

- Pijl omhoog en omlaag verplaatsen tussen items.
- Pijl rechts vouwt een categorie uit, pijl links vouwt haar in.
- Enter of het selecteren van een item laadt zijn artikelen in de artikelenlijst.
- F2 opent eigenschappen voor de geselecteerde feed of categorie.
- De Applications-toets of Shift+F10 opent het contextmenu.

Elke feed toont het aantal ongelezen artikelen. Uit- en ingevouwen categorieën worden onthouden, zodat de boom er bij de volgende start hetzelfde uitziet.

Feeds die niet konden worden bijgewerkt staan nog gewoon in de lijst; de weergave Feeds met fouten verzamelt ze zodat een feed die ongemerkt niet meer werkt niet onopgemerkt blijft.

## Artikelenlijst {#article-list}

De artikelenlijst toont de artikelen van wat in de boom is geselecteerd, nadat het huidige Artikelfilter, de sorteervolgorde en de zoekterm zijn toegepast.

- Pijl omhoog en omlaag verplaatsen tussen artikelen; het leesvenster volgt.
- Enter opent het geselecteerde artikel.
- Shift+Up en Shift+Down breiden de selectie uit, zodat massa-acties op meerdere artikelen tegelijk werken.
- Backspace schakelt gelezen en ongelezen voor het geselecteerde artikel om.
- Delete verwijdert de geselecteerde artikelen; Shift+Delete verwijdert ze zonder bevestigingsvraag.
- Ctrl+D voegt een favoriet toe of verwijdert die.
- De Applications-toets of Shift+F10 opent het contextmenu.

Welke kolommen verschijnen en in welke volgorde is globaal en per feed instelbaar. Zie Kolommen in de artikelenlijst.

## Leesvenster {#reading-pane}

Het leesvenster onder de artikelenlijst bevat de tekst van het geselecteerde artikel. Het is een alleen-lezen-tekstgebied, zodat een schermlezer regel voor regel, woord voor woord of teken voor teken kan lezen en de tekst geselecteerd en gekopieerd kan worden.

- Ctrl+F zoekt in de artikeltekst.
- F3 en Shift+F3 gaan naar de volgende en vorige overeenkomst.
- Enter op een koppeling in de tekst opent die koppeling.

De weergave van tekst is instelbaar in Instellingen, Feeds en artikelen: koppen kunnen worden aangekondigd, lijstitems met opsommingstekens en nummers gemarkeerd, citaten gemarkeerd, koppelingen met hun adres getoond, tabellen beschreven en alternatieve tekst van afbeeldingen opgenomen. Alternatieve tekst van afbeeldingen kan ook voor één feed aan of uit worden gezet via het contextmenu van die feed.

Als een feed alleen een korte samenvatting publiceert, kan BlindRSS de volledige artikeltekst ophalen. Zie Volledige artikeltekst ophalen.

## Artikelvenster {#article-window}

Een artikel openen kan het in een eigen venster zetten in plaats van in het leesvenster; zo krijgt het artikel het hele scherm en blijft het open terwijl u verdergaat in de lijst.

Het venster is een alleen-lezen-tekstgebied met hetzelfde lees-, selectie- en zoek-in-tekstgedrag als het leesvenster. Escape sluit het.

## Zoekveld {#search-field}

Het zoekveld boven de artikelenlijst filtert de huidige weergave terwijl u typt en bevestigt met Enter.

- Ctrl+E verplaatst de focus naar het zoekveld.
- Enter past de term toe.
- Escape, of de knop Wissen, leegt het en herstelt de volledige lijst.

Het zoekveld kan worden verborgen als u het nooit gebruikt; het menu Beeld heeft de opdracht Zoekveld tonen/verbergen. Of de zoekopdracht alleen titels of ook titels en artikeltekst doorzoekt, stelt u in bij Instellingen, Feeds en artikelen onder "Zoeken komt overeen met".

Een zoekopdracht die u wilt bewaren kan in een opgeslagen zoekopdracht worden omgezet die in de boom blijft staan. Zie Permanente zoekopdrachten.

## Statusbalk {#status-bar}

De statusbalk onder in het hoofdvenster heeft drie velden:

- Tijdelijke berichten, zoals hoeveel artikelen een filter vond.
- Achtergrondactiviteit, zoals een feedvernieuwing of download die bezig is.
- Afspeelstatus: wat speelt en de verstreken en resterende tijd.

Ze zijn bewust gescheiden, zodat een vernieuwingsbericht geen aantal zoekresultaten kan overschrijven terwijl u het leest.

## Contextmenu's {#context-menus}

De feedboom en artikelenlijst hebben elk een contextmenu, dat wordt geopend met de Applications-toets of Shift+F10. Ze bevatten de opdrachten die op het geselecteerde van toepassing zijn — vernieuwen, als gelezen markeren, bewerken, verwijderen, koppelingen kopiëren, media in de wachtrij zetten, enzovoort.

Contextmenu's ondersteunen ook F1: met een item gemarkeerd opent F1 het onderdeel van deze handleiding dat het uitlegt.

## Een feed toevoegen {#adding-feeds}

Bestand, Feed toevoegen (Ctrl+N) abonneert zich op een feed via adres.

Plak of typ het adres van de feed of van de site zelf — BlindRSS zoekt op de pagina naar een feed als het adres geen feed is. U kunt ook een adres van een YouTube-kanaal of -afspeellijst, een Mastodon- of Bluesky-profiel, een PieFed- of Lemmy-community, een SoundCloud- of Mixcloud-pagina of een Reddit- of Groups.io-adres plakken; BlindRSS maakt er een feed van.

Kies de categorie waarin de feed moet staan of laat hem ongecategoriseerd. De optie "Openen in HTML-weergave" zorgt ervoor dat artikelen van deze feed standaard in de rijke weergave openen.

Als u het adres niet kent, gebruikt u in plaats daarvan Podcasts en RSS-feeds zoeken.

## Feeds op een pagina detecteren {#detect-feeds}

Bestand, Feeds op pagina detecteren neemt het adres van een gewone webpagina en toont de feeds die die pagina aanbiedt, zodat u zich kunt abonneren zonder zelf naar de feedkoppeling te zoeken.

Dit is de juiste opdracht als een site een koppeling "abonneren" of "RSS" heeft die u niet gemakkelijk kunt bereiken, of als de pagina meerdere feeds aanbiedt (alle berichten, één categorie, reacties) en u wilt kiezen.

## Podcasts en RSS-feeds zoeken {#find-podcast}

Extra, Podcast of RSS-feed zoeken (Ctrl+Shift+F) doorzoekt podcast- en feedmappen op naam, onderwerp of siteadres, zodat u zich kunt abonneren zonder een feedadres te kennen.

1. Typ in het zoekvak wat u zoekt — een podcastnaam, onderwerp of siteadres.
2. Kies een bron of laat die op "Alle bronnen" staan.
3. Druk op Enter of op de knop Zoeken.
4. Gebruik de pijlen in de resultatenlijst. Elke rij toont de titel, uit welke map hij kwam en details.
5. Druk op Enter op een resultaat of kies OK om u erop te abonneren.

Zoekopdrachten lopen tegelijk tegen meerdere mappen en resultaten komen binnen zodra ieder antwoordt; de lijst groeit dus terwijl u leest. Escape sluit het dialoogvenster en stopt de zoekopdracht.

## Podcast- en feedmappen {#podcast-directories}

Het vak Bron in Podcast of RSS-feed zoeken kiest waar wordt gezocht. Naast "Alle bronnen", "Alle podcastbronnen" en "Alle RSS-feedbronnen" zijn deze mappen afzonderlijk beschikbaar:

- Podcastmappen: iTunes (Apple Podcasts), gPodder, fyyd, Podverse, SoundCloud en Mixcloud.
- Feedmappen: NewsBlur, Feedspot, Google News, Bing News en Feedly.
- Zoeken naar sites en communities: YouTube, Reddit, Groups.io en de Fediverse — Mastodon, Bluesky, PieFed en Lemmy of Kbin, elk ook afzonderlijk selecteerbaar.
- Ontdekking op adres: Feedsearch en BlindRSS' eigen websitescan, die een site ophaalt en naar feeds daarin zoekt.

BlindRSS vertrouwt niet op één enkele map. Zoeken in "Alle bronnen" bevraagt de podcast- en RSS-groepen samen en voegt de resultaten samen, waarbij brede Google News-zoekfeeds onder directe feedovereenkomsten blijven.

## Abonneren op een zoekresultaat {#subscribing}

In elk zoekdialoogvenster — Podcast of RSS-feed zoeken, Video zoeken of de zoekknop van Podcastarchief — abonneert Enter op een resultaat, of OK kiezen terwijl het is geselecteerd, zich erop.

BlindRSS lost het resultaat eerst op tot een echt feedadres; daardoor werkt abonneren op een podcast uit een map, een YouTube-kanaal of een Fediverse-account allemaal hetzelfde. De nieuwe feed verschijnt in de boom en wordt meteen vernieuwd.

Als u hem in een specifieke categorie wilt, verplaatst u hem daarna vanuit zijn contextmenu of vanuit Feedeigenschappen.

## Podcastarchief {#podcast-archive}

Extra, Podcastarchief bladert door de volledige afleveringsgeschiedenis van een podcast — zowel afleveringen die nog in de feed staan als oudere die BlindRSS herstelde — en downloadt ze in batches.

Veel podcastfeeds publiceren alleen de recentste afleveringen. Archiefherstel draait automatisch op de achtergrond; in dit venster ziet u de status, probeert u het handmatig opnieuw en downloadt u wat het vond.

- Kies de podcast in het vak Podcast.
- Afleveringen filteren vernauwt de lijst terwijl u typt.
- Archief opnieuw scannen voert het herstel opnieuw uit voor die podcast.
- Podcast zoeken of toevoegen opent de feedzoekopdracht zodat u een podcast kunt archiveren waarop u nog niet bent geabonneerd.
- Afspelen speelt de geselecteerde aflevering af, Geselecteerde downloaden downloadt die en Alles downloaden downloadt de volledige zichtbare lijst.
- Downloads annuleren stopt een lopende batch.

Het venster blijft open tijdens een batchdownload, zodat u kunt blijven lezen.

## Video zoeken {#video-search}

Extra, Video zoeken doorzoekt in één keer elke site die yt-dlp kan bevragen en laat u afspelen, in de wachtrij zetten of u abonneren op wat het vindt.

- Typ een zoekterm en druk op Enter of de knop Zoeken.
- Het bereikvak beperkt de zoekopdracht tot één site; standaard worden ze allemaal doorzocht.
- Resultaten komen binnen wanneer elke site antwoordt, bekende sites het eerst. Titels die als plaatsaanduiding binnenkomen worden ingevuld zodra ze zijn opgelost.
- Meer resultaten laden haalt van elke site een volgende batch op.
- Sorteren via een kolomkop herschikt wat al is binnengekomen.

Identieke video's die op meerdere sites zijn gevonden worden samengevoegd tot één rij. Volwassensites zijn uitgesloten tenzij "Volwassensites inschakelen in Video zoeken" in Instellingen, Geavanceerd is ingeschakeld.

## Een artikel openen op URL {#open-article-url}

Bestand, Artikel openen neemt het adres van elke webpagina en leest het in BlindRSS alsof het een artikel is — geëxtraheerde tekst in het leesvenster, met dezelfde leesopties als al het andere.

Gebruik dit voor een eenmalige pagina die u is gestuurd, zonder ergens op te abonneren. Als de pagina een forum- of discussiethread is, leest BlindRSS de volledige thread. Zie Forum- en discussiethreads.

## Een media-URL openen {#open-media-url}

Bestand, Media-URL openen speelt audio of video van een adres af in de ingebouwde speler zonder ergens op te abonneren.

Het accepteert directe mediakoppelingen en pagina-adressen die yt-dlp kan oplossen — YouTube, Rumble, Odysee, SoundCloud en nog veel meer. Het resultaat speelt als elk ander item en kan aan de afspeelwachtrij worden toegevoegd.

## Een feed verwijderen {#removing-feeds}

Bestand, Feed verwijderen zegt het abonnement op de geselecteerde feed op. Dezelfde opdracht staat in het contextmenu van de feed.

Een feed verwijderen verwijdert zijn artikelen uit de database. Het raakt niets aan dat u al naar schijf hebt gedownload. Als u een gehoste provider gebruikt, wordt de opzegging ook naar dat account gestuurd.

Om een hele categorie en alles daarin te verwijderen, gebruikt u Categorie en feeds verwijderen in het contextmenu van de categorie. Zie Categorieën en subcategorieën.

## Feedeigenschappen {#feed-properties}

F2, of Feed bewerken in het contextmenu, opent de eigenschappen van de geselecteerde feed.

- De titel, die u kunt overschrijven; "Titel terugzetten naar standaard van feed" in het contextmenu zet de eigen titel van de feed terug.
- Het adres en de categorie waartoe hij behoort.
- Of nieuwe artikelen ervan een melding geven.
- Of hij in de rijke HTML-weergave opent.
- Zijn eigen indeling van de artikelenlijstkolommen, op het tabblad Lijstkoppen, die de globale overschrijft.

Feedbeschrijving weergeven in het contextmenu van de artikelenlijst toont de beschrijving die de feed zelf publiceert.

## Categorieën en subcategorieën {#categories}

Categorieën groeperen feeds in de boom en kunnen nesten: een categorie kan zowel feeds als verdere subcategorieën bevatten.

- Bestand, Categorie toevoegen maakt er één.
- Subcategorie toevoegen in het contextmenu van een categorie maakt er één daarbinnen.
- Categorie bewerken hernoemt of verplaatst haar. Zie Categorie-eigenschappen.
- Categorie verwijderen verwijdert de categorie maar behoudt de feeds.
- Categorie en feeds verwijderen verwijdert de categorie en zegt alles erin op.
- OPML hier importeren importeert een bestand rechtstreeks in die categorie.
- Categorie naar OPML exporteren exporteert alleen die tak.

Sommige gehoste providers houden categorieën in één platte lijst. Wanneer dat zo is, zegt BlindRSS dat en zijn de opties "naar bovenliggende verplaatsen" niet beschikbaar.

## Categorie-eigenschappen {#category-properties}

Categorie bewerken opent de eigenschappen van de categorie: haar naam en de bovenliggende categorie waarin zij staat.

Een categorie hernoemen behoudt al haar feeds. Verplaatsen verplaatst de hele tak, met alle subcategorieën.

## Feeds vernieuwen {#refreshing}

- F5 vernieuwt elke feed.
- Ctrl+F5 vernieuwt alleen de geselecteerde feed of categorie.
- Shift+F5 stopt een lopende vernieuwing.
- Categorie vernieuwen in het contextmenu van een categorie vernieuwt die tak.

Slechts één van Feeds vernieuwen en Vernieuwing stoppen is tegelijk beschikbaar, zodat de toetsenbordopdracht overeenkomt met wat het menu biedt. Voortgang verschijnt in het tweede statusbalkveld.

Automatisch vernieuwen stelt u in bij Instellingen, Feeds en artikelen: het interval, hoeveel feeds tegelijk vernieuwen, hoeveel verbindingen per host, de timeout per feed en hoe vaak een mislukte feed opnieuw wordt geprobeerd. "Feeds automatisch vernieuwen bij starten" vernieuwt alles bij het opstarten, en de optie voor opstartbelasting kiest tussen de cache gebruiken en een volledige vernieuwing afdwingen.

## Feeds met fouten {#feed-errors}

De weergave Feeds met fouten en Bestand, Feedfouten weergeven tonen de feeds waarvan de laatste bijwerking mislukte, met de reden.

Een feed die stil is opgehouden lijkt precies op een feed zonder nieuwe artikelen; daarom bestaat deze weergave. Van hieruit kunt u:

- Geselecteerde vernieuwen, om het nu opnieuw te proberen.
- Details kopiëren, om de fouttekst op het klembord te zetten.
- Feedeigenschappen, om het adres te corrigeren.
- Feed verwijderen, wanneer de feed definitief weg is.

Veelvoorkomende oorzaken zijn een verplaatste of opgeheven feed, een site die nu een browsercontrole vereist (zie Sitecookies importeren) en een tijdelijke serverstoring.

## OPML importeren {#import-opml}

OPML is de standaardbestandsindeling voor een lijst feedabonnementen. Elke feedlezer kan er één exporteren; via OPML verplaatst u uw abonnementen dus vanuit een andere lezer naar BlindRSS zonder ze één voor één toe te voegen.

Bestand, OPML importeren vraagt om het bestand en voegt elke feed erin toe, met behoud van de categorie-structuur die het bestand beschrijft. Feeds waarop u al bent geabonneerd worden niet gedupliceerd.

OPML hier importeren in het contextmenu van een categorie plaatst de hele import in die categorie in plaats van op het hoogste niveau.

Om een OPML-bestand uit een andere lezer te krijgen, zoekt u in diens instellingen naar "Exporteren", "Back-up" of "Abonnementen".

## OPML exporteren {#export-opml}

Bestand, OPML exporteren schrijft al uw abonnementen, met hun categorieën, naar een OPML-bestand.

Gebruik het om abonnementen te back-uppen, ze naar een andere lezer of machine te verplaatsen of een reeks feeds met iemand anders te delen. Categorie naar OPML exporteren in het contextmenu van een categorie exporteert alleen die tak.

## Een YouTube-Takeout-archief importeren {#import-youtube-takeout}

Google Takeout is de gegevens-exportdienst van Google. Een YouTube-Takeout-archief is een ZIP-bestand met uw YouTube-gegevens, waaronder de lijst kanalen waarop u bent geabonneerd. Bestand, YouTube Takeout importeren leest die ZIP en abonneert u op die kanalen als feeds, zodat de nieuwe video's van elk kanaal als artikelen arriveren.

Om het archief te krijgen:

1. Ga naar takeout.google.com en meld u aan met het Google-account waarop uw YouTube-abonnementen staan.
2. Kies "Alles deselecteren" en selecteer daarna alleen YouTube en YouTube Music.
3. Laat in "Alle YouTube-gegevens inbegrepen" ten minste "abonnementen" staan; "geschiedenis" en "afspeellijsten" zijn optioneel en BlindRSS kan die ook gebruiken.
4. Exporteer eenmaal als ZIP-bestand en wacht op Googles e-mail — een groot archief kan uren duren.
5. Download de ZIP en wijs deze opdracht ernaar.

BlindRSS toont vervolgens wat het vond, gegroepeerd per bron, en laat u kiezen welke groepen u importeert:

- Abonnementen: de kanalen die u volgt.
- Geschiedenis: kanalen die u hebt bekeken maar niet volgt.
- Uw eigen kanalen.
- Afspeellijsten, als eigen feeds.

Dubbele adressen worden verwijderd, dus een tweede archief later importeren voegt alleen toe wat nieuw is. De ZIP wordt nooit naar schijf uitgepakt; alleen de kleine gegevensbestanden erin worden gelezen.

## Permanente zoekopdrachten {#persistent-search}

Een permanente zoekopdracht is een zoekterm die als eigen item in de boom blijft staan, zodat de bijpassende artikelen altijd één pijltjestoets verder zijn.

Extra, Permanente zoekopdracht configureren beheert de lijst: Toevoegen maakt er één van een term, Verwijderen wist hem. Elke opgeslagen zoekopdracht verschijnt in de boom en wordt opnieuw geëvalueerd wanneer u hem selecteert, zodat hij altijd de huidige artikelen weerspiegelt.

Gebruik dit voor een onderwerp dat u in elke feed volgt — een persoonsnaam, product of plaats. Gebruik voor iets dat meer structuur heeft dan een woordgroep Slimme mappen.

## Slimme mappen {#smart-folders}

Een Slimme map is een map in de boom waarvan de inhoud wordt bepaald door een regel en niet door de feed waaruit een artikel kwam.

Nieuwe Slimme map in het contextmenu van de boom opent de regelbewerker. Een regel is een verzameling voorwaarden verbonden met "alle overeenkomst" (en) of "een overeenkomst" (of), en groepen voorwaarden kunnen nesten, zodat "(A en B) of C" uitdrukbaar is.

Voorwaarden testen deze velden:

- Ja/nee-velden: gelezen, favoriet, geopend, bijgewerkt.
- Tekstvelden: titel, inhoud, beschrijving, auteur, feed, url en tag — de categorieën of tags die de site zelf publiceert.

Tekstvoorwaarden gebruiken bevat, bevat niet, is gelijk aan of begint met.

Slimme mappen verplaatsen of kopiëren nooit iets; ze zijn een weergave van artikelen die u al hebt. Gebruik Filterregels om artikelen te wijzigen wanneer ze binnenkomen.

## Filterregels {#filter-rules}

Extra, Filterregels is BlindRSS' motor voor het sorteren van artikelen. Regels lopen over binnenkomende artikelen zoals e-mailfilters over binnenkomende e-mail lopen.

Elke regel koppelt een voorwaarde — dezelfde regelbewerker die Slimme mappen gebruiken — aan een reeks acties:

- Het artikel naar een categorie verplaatsen.
- Het ook met een categorie labelen en op zijn plaats laten.
- Het als gelezen markeren.
- Het als favoriet markeren.
- Het verwijderen volgens uw ingestelde verwijdergedrag.
- De melding over het nieuwe artikel overslaan.

Regels lopen in lijstvolgorde en elke ingeschakelde regel die overeenkomt draagt zijn acties bij. Een als stoppen gemarkeerde regel beëindigt de pijplijn voor dat artikel zodra hij overeenkomt, zodat latere regels het nooit zien. Verplaats regels omhoog en omlaag om te bepalen welke wint.

Een regel zonder acties doet niets en wordt afgewezen, zodat een half-afgemaakte regel niet stil artikelen kan opslokken.

## Artikelfilter {#article-filter}

Beeld, Artikelfilter beperkt elke weergave op leesstatus en op of een artikel media bevat. De twee groepen worden gecombineerd.

- Ctrl+1: alle artikelen.
- Ctrl+2: alleen ongelezen.
- Ctrl+3: alleen gelezen.
- Ctrl+4: media en niet-media.
- Ctrl+5: alleen met media.
- Ctrl+6: zonder media.

Het filter geldt voor wat in de boom geselecteerd is, ook Slimme mappen en opgeslagen zoekopdrachten, en blijft tussen sessies behouden. "Alleen met media" is de snelste manier om een gemengde feed in een podcastlijst te veranderen.

## Artikelen sorteren {#sorting}

Beeld, Sorteren op ordent de artikelenlijst op datum, naam, auteur, beschrijving, feed of status. Oplopend schakelt de richting om; de standaard is nieuwste eerst.

De sortering geldt voor elke weergave en wordt tussen sessies onthouden. Sorteren op feed is nuttig in Alle feeds en in Slimme mappen, waar artikelen uit veel bronnen tegelijk komen.

## Kolommen in de artikelenlijst {#list-headers}

De kolommen in de artikelenlijst, hun volgorde en breedtes kiest u zelf. Instellingen, Lijstkoppen stelt de globale indeling in; het eigen tabblad Lijstkoppen van een feed overschrijft dit voor die feed, en "De globale kolomindeling gebruiken" schakelt de overschrijving weer uit.

Minder kolommen betekent minder dat een schermlezer op elke rij moet lezen, dus het loont kolommen te verwijderen die u nooit gebruikt.

## Artikelen openen {#opening-articles}

Enter op een artikel in de lijst opent het. Afhankelijk van artikel en instellingen betekent dat het leesvenster, een eigen venster of de rijke HTML-weergave.

- Artikel openen in het contextmenu doet hetzelfde.
- In browser openen geeft het adres van het artikel door aan uw systeemwebbrowser.
- Toegankelijke browser openen leest de pagina in plaats daarvan in BlindRSS. Zie Toegankelijke browser.

Een artikel openen markeert het als gelezen tenzij u dat gedrag hebt gewijzigd.

## Gelezen en ongelezen artikelen {#read-status}

- Backspace, of Gelezen/ongelezen schakelen, wisselt het geselecteerde artikel.
- Ctrl+Shift+R markeert alles in de huidige weergave als gelezen.
- Alle items als gelezen markeren in het contextmenu van een feed of categorie doet hetzelfde voor die tak.
- Als gelezen markeren en Als ongelezen markeren in het contextmenu van de artikelenlijst werken op de hele selectie en zeggen hoeveel artikelen ze zullen beïnvloeden.

Ongelezen aantallen verschijnen naast elke feed in de boom. Het Artikelfilter kan gelezen artikelen volledig verbergen.

## Favorieten {#favorites}

Ctrl+D voegt het geselecteerde artikel toe aan Favorieten, of verwijdert het als het daar al staat. De weergave Favorieten in de boom bevat alles wat u hebt gemarkeerd.

Favorieten overleven het bewaarbeleid: een artikel dat u een ster gaf wordt niet verwijderd bij het opruimen van oudere artikelen. Favoriet is ook bruikbaar als voorwaarde in Slimme mappen en Filterregels.

## Verwijderde artikelen {#deleted-articles}

Wat Delete doet is instelbaar in Instellingen, Algemeen, onder "Wanneer ik een artikel verwijder":

- Het naar Verwijderde artikelen verplaatsen, waar het hersteld kan worden.
- Het permanent verwijderen.
- Het naar een categorie verplaatsen die u noemt.

Met de eerste instelling bevat de weergave Verwijderde artikelen in de boom wat u hebt verwijderd, Herstellen zet een artikel terug, en verwijderen vanuit die weergave verwijdert het definitief.

"Bevestigen vóór artikelen verwijderen" bepaalt de bevestigingsvraag. Shift+Delete slaat die altijd over.

## Volledige artikeltekst ophalen {#full-text}

Veel feeds publiceren alleen een kop en een zin of twee. BlindRSS kan de artikelpagina ophalen en de echte tekst extraheren, zodat het leesvenster het hele artikel toont in plaats van een teaser.

Dit gebeurt automatisch terwijl u door de lijst beweegt, op de achtergrond, en het resultaat wordt gecachet. "Volledige tekst op achtergrond cachen" in Instellingen, Feeds en artikelen haalt artikelen rond uw positie vooraf op, zodat omlaag door de lijst gaan niet op het netwerk wacht.

Als een site helemaal niet gelezen wil worden, staat zij meestal achter een browsercontrole. Zie Sitecookies importeren.

## Rijke weergave van volledige tekst {#rich-view}

Ctrl+Shift+H schakelt het leesvenster naar de rijke HTML-weergave, die het artikel weergeeft zoals een browser dat zou doen, met koppen, lijsten, tabellen en koppelingen als echte elementen waar een schermlezer met zijn eigen structuurcommando's doorheen kan navigeren.

De plattetekstweergave is standaard omdat zij sneller is en u nooit verrast. De rijke weergave is de moeite waard voor artikelen waarvan de structuur betekenis draagt.

Een feed kan vanuit Feedeigenschappen altijd in de rijke weergave laten openen; koppelingen in de rijke weergave openen in uw systeembrowser en niet in de weergave zelf.

## Toegankelijke browser {#accessible-browser}

Beeld, Toegankelijke browser openen opent een pagina in BlindRSS in een venster dat is gemaakt voor lezen met een schermlezer, in plaats van hem aan uw systeembrowser door te geven.

Dit is het juiste hulpmiddel voor een pagina die gelezen moet worden in plaats van gebruikt, en voor sites waarvan de eigen interface lastig te navigeren is. Hij deelt BlindRSS' cookie- en browseridentiteitsinstellingen, dus pagina's achter een browsercontrole openen hier ook zodra u er cookies voor hebt geïmporteerd.

## YouTube-video's {#youtube}

U kunt zich op een YouTube-kanaal of -afspeellijstadres abonneren zoals op elke feed. Video's komen dan als artikelen binnen, met de beschrijving, het transcript en de hoofdstuklijst inline, zodat een video gelezen kan worden in plaats van bekeken.

Afspelen gaat via yt-dlp. Instellingen, YouTube beheert dit:

- Een cookiebestand, waarmee BlindRSS video's met leeftijdsbeperking en alleen voor leden kan zien waartoe u toegang hebt. Het kan rechtstreeks uit een browser worden geïmporteerd of automatisch worden opgepikt uit cookies.txt-exporten in uw map Downloads.
- "YouTube afspelen door eerst te downloaden", dat langzamer start maar veel betrouwbaarder is.
- De cachemap voor afspelen en de maximale grootte ervan, met een knop om hem nu te wissen.

YouTube Takeout importeren abonneert u in één stap op elk kanaal dat u al volgt.

## Forum- en discussiethreads {#forums}

Reddit, Lemmy, Groups.io en Google Groups worden gelezen als hele threads in plaats van als één bericht tegelijk: een discussie openen geeft u het oorspronkelijke bericht en de antwoorden in één doorlopend stuk tekst, dat veel sneller te lezen is dan een thread volgen in een browser.

Abonneren werkt hetzelfde als bij elke feed — plak het adres van de subreddit, community of groep. GitHub-repositories worden op dezelfde manier ondersteund, evenals Mastodon-, Bluesky- en PieFed-accounts en -communities.

## Knippen, kopiëren en plakken {#clipboard}

Het menu Bewerken bevat de standaard klembordopdrachten — Knippen (Ctrl+X), Kopiëren (Ctrl+C), Plakken (Ctrl+V) en Alles selecteren (Ctrl+A) — en ze werken in elk tekstveld en in het leesvenster.

BlindRSS voegt opdrachten toe die dingen kopiëren die het kent:

- Koppeling kopiëren, het adres van het artikel.
- Mediakoppeling kopiëren, het adres van audio of video.
- Tekst kopiëren, de artikeltekst zoals gelezen in het leesvenster.
- Feed-URL kopiëren, het adres van de geselecteerde feed.
- Afbeeldingskoppeling kopiëren, bij een artikel met een afbeelding.

## De ingebouwde speler {#player}

BlindRSS speelt podcast- en videobijlagen zelf af, via VLC, zodat afspelen de toepassing nooit verlaat. Ctrl+Shift+P toont of verbergt het spelervenster; het afspelen gaat in beide gevallen door.

Het afspelen wordt soepel gemaakt door een lokale range-cacheproxy; daarom is zoeken in een lange aflevering snel, zelfs op een trage verbinding. Streams die moeten worden opgelost — YouTube, Rumble, Odysee — gaan eerst door yt-dlp.

"Spelervenster tonen bij starten van afspelen" in Instellingen, Mediaspeler bepaalt of het venster vanzelf verschijnt wanneer iets start.

## Spelerbediening {#player-controls}

Het spelervenster bevat in tabvolgorde: de afspeelstatus, de positieschuifregelaar, verstreken en totale tijd, terugspoel- en vooruitspoelknoppen, het snelheidsvak, de hoofdstukkenknop en de volumeschuifregelaar. Ze zijn allemaal vanaf het toetsenbord bereikbaar en bedienbaar, en elk kondigt zijn huidige waarde aan.

- Ctrl+P speelt af en pauzeert.
- Ctrl+S stopt.
- Ctrl+Left en Ctrl+Right spoelen terug en vooruit en herhalen terwijl ze worden ingedrukt. Op macOS doen Option+Left en Option+Right hetzelfde, omdat Ctrl+Left en Ctrl+Right daar bij Mission Control horen.
- Ctrl+Up en Ctrl+Down veranderen het volume.

De toetsen voor zoeken en volume werken overal in BlindRSS terwijl iets speelt, ook vanuit een dialoogvenster, zodat u nooit het spelervenster hoeft te zoeken om te pauzeren.

## Sneltoetsen van de speler {#player-shortcuts}

- Ctrl+Shift+P: het spelervenster tonen of verbergen.
- Ctrl+P: afspelen of pauzeren.
- Ctrl+S: stoppen.
- Ctrl+Left en Ctrl+Right: terug- en vooruitspoelen (Option+Left en Option+Right op macOS).
- Ctrl+Up en Ctrl+Down: volume hoger en lager.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: sneller, langzamer, terug naar normale snelheid.
- Ctrl+Shift+E: de equalizer.
- Ctrl+Shift+C: de afspeelwachtrij.
- Ctrl+Shift+T en Ctrl+Shift+V: volgende en vorige in de wachtrij.

Al deze sneltoetsen kunnen worden gewijzigd in Extra, Sneltoetsen. De snelheidsopdrachten gebruiken bewust standaard letters in plaats van Ctrl+Shift+cijfer of Ctrl+Shift+punt, omdat Windows en sommige NVDA-add-ons die onderscheppen voordat een toepassing ze ziet.

## Afspeelsnelheid {#playback-speed}

Speler, Afspeelsnelheid wijzigt hoe snel media speelt, van halve tot driedubbele snelheid, met behoud van toonhoogte.

- Ctrl+Shift+U versnelt, Ctrl+Shift+D vertraagt, Ctrl+Shift+N keert terug naar 1x.
- Het submenu heeft vaste stappen: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x en 3x.
- Het spelervenster heeft een snelheidsvak dat u rechtstreeks kunt instellen.

"Standaard afspeelsnelheid" in Instellingen, Mediaspeler stelt de snelheid in waarmee alles begint.

## Equalizer {#equalizer}

Ctrl+Shift+E, of Speler, Equalizer, opent een tientraps-equalizer met voorversterking.

- "Equalizer inschakelen" zet alles aan en uit.
- Elke band is een schuifregelaar die de versterking aankondigt terwijl u die wijzigt.
- Opslaan als voorinstelling bewaart de huidige banden onder een naam; Voorinstelling verwijderen wist er één.
- Reset (vlak) zet elke band terug op nul.

De equalizer geldt voor alles dat BlindRSS afspeelt en de instelling wordt onthouden.

## Hoofdstukken {#chapters}

Podcasts en YouTube-video's bevatten vaak hoofdstukken. Wanneer het spelende item die heeft, toont Speler, Hoofdstukken ze en naar één springen zoekt daarheen.

- Het submenu Hoofdstukken vult zich zodra de hoofdstukken van het item bekend zijn en zegt "Geen hoofdstukken beschikbaar" wanneer het er geen heeft.
- Het spelervenster heeft een hoofdstukkenknop en een hoofdstukkenvak.
- Hoofdstukkoppelingen in het contextmenu van de artikelenlijst toont de koppelingen in een hoofdstukbeschrijving.

Hoofdstukken worden op de achtergrond geladen wanneer u door de lijst beweegt, dus meestal zijn ze klaar voordat u op afspelen drukt.

## Afspeelwachtrij {#play-queue}

De afspeelwachtrij is de lijst van wat hierna speelt.

- Ctrl+Shift+C opent het wachtrijvenster.
- Ctrl+Shift+T en Ctrl+Shift+V spelen het volgende en vorige item.
- Aan afspeelwachtrij toevoegen en Uit afspeelwachtrij verwijderen in het contextmenu van de artikelenlijst wijzigen hem.

In het wachtrijvenster start Afspelen het geselecteerde item, Omhoog en Omlaag verplaatsen herschikken de wachtrij, Verwijderen laat één item vallen en Alles wissen leegt hem. De wachtrij overleeft herstarts.

## Casten naar andere apparaten {#casting}

BlindRSS kan wat het afspeelt naar een apparaat op uw netwerk sturen: Chromecast, AirPlay-luidsprekers, DLNA/UPnP-renderers, Sonos-luidsprekers, Roku-spelers en Kodi. Een aflevering gaat op het apparaat verder waar ze was, en pauzeren, spoelen en de positie werken daar net als lokaal (Roku kan niet spoelen).

Kies het apparaat in het castdialoogvenster; BlindRSS streamt via zijn eigen lokale proxy, zodat een apparaat dat het oorspronkelijke adres niet zelf kan ophalen het item toch afspeelt. Transportbediening blijft vanuit BlindRSS werken tijdens het casten.

## Stilte overslaan {#silence-skipping}

"Stilte overslaan (experimenteel)" in Instellingen, Mediaspeler detecteert stille passages tijdens afspelen en slaat ze over, wat praatpodcasts met lange stiltes merkbaar verkort.

Het analyseert audio tijdens het afspelen, dus kost het wat CPU en is het experimenteel gemarkeerd. Zet het uit als afspelen niet vloeiend is.

## Media downloaden {#downloads}

- Downloaden slaat de audio of video van het geselecteerde artikel op in de standaardindeling.
- Downloaden als laat u eerst de indeling kiezen.

Downloads moeten worden ingeschakeld met "Downloads inschakelen" in Instellingen. De downloadmap, het bewaarbeleid en de standaardindeling voor videodownloads staan op dezelfde pagina; de standaardmap is de Downloads-map van uw systeem.

Voortgang verschijnt in het tweede statusbalkveld en gedownloade items spelen daarna vanaf schijf in plaats van via het netwerk. Podcastarchief kan de hele backcatalogus van een podcast in één batch downloaden.

## Instellingen {#settings}

Extra, Instellingen (Ctrl+comma) bevat elke optie op tabbladen: Algemeen, Feeds en artikelen, YouTube, Mediaspeler, Provider, Meldingen, Vertalen, Lijstkoppen, Geavanceerd en CAPTCHA oplossen.

Ctrl+Tab en Ctrl+Shift+Tab gaan tussen tabbladen; Tab gaat door de besturingselementen op het huidige tabblad. OK past alles toe, Annuleren verwerpt alles. Tabposities blijven stabiel tussen releases omdat ze spiergeheugen worden.

F1 indrukken op een tabblad opent het onderdeel van deze handleiding voor dat tabblad.

## Instellingen: Algemeen {#settings-general}

- Interfacetaal en of BlindRSS uw systeemtaal volgt. Een wijziging wordt actief na herstart. Zie Interfacetaal.
- "Laatste geselecteerde feed/map bij starten onthouden".
- "Bevestigen vóór artikelen verwijderen" en wat verwijderen doet — naar Verwijderde artikelen verplaatsen, permanent verwijderen of naar een categorie verplaatsen die u noemt.
- "Debugmodus (console tonen bij opstarten)", die ook een roterend blindrss.log naast uw gegevens schrijft.
- Starten en systeemvak: sluiten naar systeemvak, minimaliseren naar systeemvak, in het systeemvak starten, altijd gemaximaliseerd starten en bij opstarten op updates controleren.

## Instellingen: Feeds en artikelen {#settings-feeds}

- Het automatische vernieuwingsinterval, van vijf minuten tot vier uur.
- Of zoeken alleen titels of titels en artikeltekst vergelijkt.
- Maximum gelijktijdige vernieuwingen, maximum verbindingen per host, de feedtimeout en hoe vaak een mislukte feed opnieuw wordt geprobeerd.
- Maximum gecachete weergaven en "Volledige tekst op achtergrond cachen".
- "Feeds automatisch vernieuwen bij starten" en de opstartvernieuwingsbelasting: de cache gebruiken, bij starten volledig vernieuwen of altijd volledig vernieuwen.
- Artikelbewaring, die bepaalt hoe lang artikelen worden bewaard. Favorieten worden nooit door bewaring verwijderd.
- Hoe artikeltekst wordt getoond: koppen aankondigen, lijstitems met opsommingstekens en nummers markeren, citaten markeren, koppelingen met hun adres tonen, tabellen beschrijven en alternatieve tekst van afbeeldingen opnemen.

## Instellingen: YouTube {#settings-youtube}

- Het yt-dlp-cookiebestand met een knop Bladeren, een knop "Importeren uit browser" en een optie om cookies.txt-exporten automatisch uit uw map Downloads op te halen.
- Cookies rechtstreeks lezen uit een geïnstalleerde browser.
- "YouTube afspelen door eerst te downloaden", dat langzamer start maar de betrouwbaarste optie is.
- De YouTube-afspeelcachemap, de maximale grootte in megabytes en een knop om hem nu te wissen.

Cookies maken video's met leeftijdsbeperking en alleen voor leden afspeelbaar; ze zijn waar een fout "meld u aan om te bevestigen dat u geen bot bent" om vraagt.

## Instellingen: Mediaspeler {#settings-media-player}

- De voorkeursgeluidskaart of de systeemstandaard.
- "Stilte overslaan (experimenteel)". Zie Stilte overslaan.
- De standaard afspeelsnelheid.
- "Spelervenster tonen bij starten van afspelen".
- De netwerkgrootte van de cache in milliseconden, die opstartvertraging afweegt tegen robuustheid op een trage verbinding.
- Paden naar ffmpeg, ffprobe en yt-dlp. Laat er één leeg voor autodetectie; een ingesteld pad overschrijft detectie en wat werd gedetecteerd staat naast elk pad.
- Downloads: of downloads zijn ingeschakeld, de downloadmap, het bewaarbeleid en de standaardindeling voor videodownloads.
- Geluiden: of BlindRSS zijn meldingsgeluiden speelt.

## Instellingen: Provider {#settings-provider}

Kiest waar uw abonnementen leven: lokaal in BlindRSS of in een gehost account. Zie Onlineaccounts en providers voor wat ieder nodig heeft.

De pagina toont welke provider actief is en de gegevens ervoor — een Miniflux-adres en API-sleutel, een Inoreader-app-ID en -sleutel met een knop Autoriseren, of een e-mailadres en wachtwoord voor The Old Reader of BazQux. Autorisatie wissen meldt een Inoreader-account af.

De lokale provider gebruikt feeds die u in de app toevoegt met Feed toevoegen en OPML importeren.

## Instellingen: Meldingen {#settings-notifications}

- "Meldingen inschakelen voor nieuwe artikelen" en of de naam van de feed in de meldingstekst verschijnt.
- Het maximum aantal meldingen per vernieuwing en of een samenvattingsmelding wordt getoond zodra die limiet is bereikt.
- Testmelding verstuurt er nu één.
- Feeds uitsluiten kiest feeds die nooit melden.
- Aankondigingen: welke gebeurtenissen BlindRSS rechtstreeks aan uw schermlezer uitspreekt, per gebeurtenis, met een knop Testaankondiging die zowel via spraak als braille een test stuurt.

## Instellingen: Vertalen {#settings-translate}

Schakelt automatische vertaling van artikelinhoud in en kiest de dienst die dat doet.

- "Automatische vertaling voor artikelinhoud inschakelen".
- De provider: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini of Qwen.
- De doeltaal, gekozen uit de lijst of getypt als code zoals en, es, fr of pt-BR.
- Een API-sleutel voor de gekozen provider en eventueel een specifiek model. Voor OpenRouter haalt "OpenRouter-modellen laden" de beschikbare modellenlijst op.

Grok en Groq zijn verschillende diensten met verwarrend vergelijkbare namen: Grok is van xAI, met sleutels van console.x.ai die met "xai-" beginnen; Groq host LLaMA en Mistral, met gratis sleutels van console.groq.com die met "gsk_" beginnen.

Dit vertaalt artikeltekst. Zie Interfacetaal om de taal van BlindRSS' eigen interface te wijzigen.

## Instellingen: Lijstkoppen {#settings-list-headers}

Stelt de globale kolomindeling van de artikelenlijst in: welke kolommen verschijnen, in welke volgorde en hoe breed. Zie Kolommen in de artikelenlijst.

Een individuele feed kan dit vanuit zijn eigen Feedeigenschappen overschrijven.

## Instellingen: Geavanceerd {#settings-advanced}

- Opslaglocatie voor gegevens: bewaar database en instellingen in de gebruikersgegevensmap of in de toepassingsmap, met beide paden getoond. De optie toepassingsmap maakt een draagbare installatie draagbaar.
- Updates: "Updates automatisch installeren zonder bevestiging".
- Browseridentificatie: met welke browser BlindRSS zich identificeert bij het ophalen van feeds, of een eigen User-Agent-tekenreeks die u typt. De werkzame tekenreeks staat eronder. Dit is van belang voor sites die onbekende clients blokkeren.
- Video zoeken: "Volwassensites inschakelen in Video zoeken", standaard uit.

## Instellingen: CAPTCHA oplossen {#settings-captcha}

Een optionele, betaalde laatste uitweg voor sites die antwoorden met een CAPTCHA waar geïmporteerde cookies niet doorheen komen.

"CAPTCHA-oplossingsdienst inschakelen" zet dit aan; het API-sleutelveld bevat uw accountsleutel bij de oplossingsdienst. Per oplossing gelden kosten; daarom staat het standaard uit en wordt het alleen geprobeerd nadat al het andere mislukte.

Probeer eerst Sitecookies importeren; dat is gratis en lost de meeste gevallen op.

## Onlineaccounts en providers {#providers}

BlindRSS kan uw abonnementen zelf bewaren of ze uit een gehost account lezen. Instellingen, Provider kiest welke.

- Lokaal: abonnementen staan in BlindRSS' eigen database op deze machine. Niets wordt ergens gesynchroniseerd.
- Miniflux: heeft het adres van uw Miniflux-server en een API-sleutel uit de accountinstellingen van Miniflux nodig.
- Inoreader: heeft een app-ID en appsleutel van de ontwikkelaarspagina van Inoreader nodig, daarna de knop Autoriseren om aan te melden.
- The Old Reader: heeft het e-mailadres en wachtwoord van uw account nodig.
- BazQux: heeft het e-mailadres en wachtwoord van uw account nodig.

Bij een gehoste provider zijn leesstatus, abonnementen en categorieën die van het account en volgen ze u naar elk ander apparaat waarop u zich bij hetzelfde account aanmeldt. Sommige providers houden categorieën in één platte lijst; BlindRSS zegt dat in plaats van nesting aan te bieden die niet zou blijven bestaan.

## Meldingen {#notifications}

BlindRSS toont een systeemmelding wanneer nieuwe artikelen arriveren, afhankelijk van Instellingen, Meldingen.

- Meldingen kunnen volledig worden uitgeschakeld.
- De feednaam kan in de tekst worden opgenomen.
- Een limiet beperkt hoeveel er per vernieuwing komen, met een optionele samenvattingsmelding zodra de limiet is bereikt.
- Individuele feeds kunnen worden uitgesloten, vanuit Feeds uitsluiten in Instellingen of vanuit "Meldingen voor deze feed" in het contextmenu van de feed.
- Een Filterregel kan de melding voor artikelen die ermee overeenkomen onderdrukken.

Afzonderlijk daarvan spreken Aankondigingen gekozen gebeurtenissen rechtstreeks via NVDA's of JAWS' eigen interface en via braille naar uw schermlezer, wat ook doorkomt wanneer een systeemmelding dat niet doet.

## Artikelvertaling {#translation}

Als vertaling is ingeschakeld in Instellingen, Vertalen, wordt artikeltekst tijdens het lezen vertaald naar uw doeltaal met de AI-dienst die u hebt ingesteld.

Vertaling gebeurt op aanvraag en wordt gecachet, zodat een artikel opnieuw lezen niet tweemaal kost. Zij heeft een internetverbinding en uw eigen API-sleutel voor de gekozen dienst nodig.

De toepassingsinterface wordt afzonderlijk vertaald, via eigen catalogi. Zie Interfacetaal.

## Sitecookies importeren {#site-cookies}

Sommige sites zetten een browserverificatiepagina — doorgaans een Cloudflare-uitdaging "uw browser controleren" — voor hun inhoud. Die sites antwoorden alleen aan een sessie die de uitdaging al in een echte browser doorstond, zodat BlindRSS ze niet zelf kan ophalen.

Extra, Sitecookies importeren geeft het die sessie:

1. Open de website in uw webbrowser en wacht tot hij klaar is met laden.
2. Exporteer de cookies naar een cookies.txt-bestand met een browserextensie voor cookies.txt. Voor Chrome-gebaseerde browsers verwijst het dialoogvenster naar "Get cookies.txt LOCALLY".
3. Kies het geëxporteerde bestand in het dialoogvenster.
4. Plak de User-Agent-tekenreeks van uw browser in het veld eronder. Zoeken op het web naar "what is my user agent" toont hem. Cloudflare vereist exact de User-Agent waarop het cookie is uitgegeven, dus dit is belangrijk.

Browsers uit de Firefox-familie hebben een eenklikpad: "Importeren uit browser" leest hun cookiedatabase rechtstreeks. Chromium-gebaseerde browsers versleutelen de hunne; daarom hebben zij de extensie nodig.

## Sneltoetsen {#keyboard-shortcuts}

Extra, Sneltoetsen toont elke opdracht in BlindRSS, gegroepeerd op categorie, met de huidige toets, en laat u elke toets wijzigen.

- Selecteer een opdracht en kies Sneltoets wijzigen. Het opnamedialoogvenster legt dan de volgende toetscombinatie vast die u indrukt.
- Sneltoets verwijderen laat een opdracht ongebonden; hij werkt nog vanuit het menu.
- Alles terugzetten naar standaard herstelt de meegeleverde toetsen.

Sneltoetsen worden vóór menuversnellers uitgevoerd en werken vensterbreed, ook wanneer het spelervenster focus heeft; het toetsenbordpad kondigt zichzelf aan waar het menupad stil blijft. Uw wijzigingen worden met uw instellingen opgeslagen en overleven updates.

## Standaardsneltoetsen {#shortcuts-reference}

Feeds:

- Ctrl+N: Feed toevoegen.
- F5: Feeds vernieuwen. Shift+F5: Vernieuwing stoppen. Ctrl+F5: De geselecteerde feed vernieuwen.
- F2: Feed of categorie bewerken.
- Ctrl+Shift+R: Alle items als gelezen markeren.
- Ctrl+Shift+F: Podcast of RSS-feed zoeken.

Artikelen en weergaven:

- Ctrl+D: toevoegen aan of verwijderen uit Favorieten.
- Backspace: gelezen en ongelezen schakelen. Delete: verwijderen. Shift+Delete: verwijderen zonder bevestiging.
- Ctrl+E: focus op het zoekveld.
- Ctrl+Shift+H: rijke weergave van volledige tekst.
- Ctrl+1 tot Ctrl+3: alles, ongelezen, gelezen. Ctrl+4 tot Ctrl+6: media en niet-media, met media, zonder media.

Speler:

- Ctrl+P: afspelen of pauzeren. Ctrl+S: stoppen. Ctrl+Shift+P: speler tonen of verbergen.
- Ctrl+Left en Ctrl+Right: zoeken. Ctrl+Up en Ctrl+Down: volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: sneller, langzamer, normaal.
- Ctrl+Shift+E: equalizer.
- Ctrl+Shift+C: afspeelwachtrij. Ctrl+Shift+T en Ctrl+Shift+V: volgende en vorige.

Toepassing:

- F1: deze handleiding, geopend bij het onderdeel voor wat u gebruikt.
- Ctrl+comma: Instellingen.
- Ctrl+Shift+A: de actieve versie aankondigen.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: knippen, kopiëren, plakken, alles selecteren.

Opdrachten die hier niet staan worden ongebonden geleverd en kunnen in Extra, Sneltoetsen elke toets krijgen.

## Interfacetaal {#language}

BlindRSS' interface is in vijftien talen vertaald. Instellingen, Algemeen kiest er één, of laat deze uw systeemtaal volgen. De wijziging wordt actief wanneer u herstart.

Vertalingen worden zowel tussen toepassingsreleases als ermee geleverd, zodat een gecorrigeerde vertaling u bereikt zonder dat u op een nieuwe versie hoeft te wachten.

Deze handleiding volgt dezelfde taal wanneer er een vertaalde handleiding voor bestaat en valt anders terug op Engels.

## Systeemvakpictogram en mediatoetsen {#tray}

BlindRSS kan in het systeemvak leven. Instellingen, Algemeen bepaalt of sluiten het venster daarheen stuurt, of minimaliseren dat doet en of het daar start.

Het systeemvakpictogram heeft afspeelbediening en opent het hoofdvenster opnieuw. De mediatoetsen van uw toetsenbord — afspelen/pauzeren, stoppen, volgende, vorige — bedienen de speler van BlindRSS systeembreed.

## Bureaubladsnelkoppelingen toevoegen {#desktop-shortcuts}

Bestand, Snelkoppelingen toevoegen maakt snelkoppelingen naar BlindRSS op het bureaublad, in het Startmenu en op de taakbalk. Vink aan wat u wilt en kies OK; het resultaat van elk wordt teruggerapporteerd.

Een Startmenuvermelding is ook wat Windows vereist voordat een toepassing meldingen mag geven; het is dus de moeite waard er één te hebben, zelfs als u BlindRSS anders start.

## Op updates controleren {#updates}

Help, Op updates controleren vraagt of er een nieuwere versie beschikbaar is en biedt aan die te installeren.

Elke update wordt geverifieerd voordat hij wordt toegepast: de SHA-256 moet overeenkomen met het gepubliceerde manifest en in Windows moet de Authenticode-handtekening geldig zijn. Een update die een van beide controles niet doorstaat, wordt niet geïnstalleerd.

"Bij opstarten op updates controleren" in Instellingen, Algemeen doet dit automatisch, en "Updates automatisch installeren zonder bevestiging" in Instellingen, Geavanceerd past ze toe zonder te vragen. Uw instellingen, database en downloads blijven door een update onaangeroerd.

## De versie aankondigen {#version}

Help, Versie aankondigen (Ctrl+Shift+A) spreekt de actieve BlindRSS-versie rechtstreeks naar uw schermlezer uit.

De eigen opdracht van een schermlezer om de toepassingsversie te melden leest de versiebron van het uitvoerbare bestand; die werkt voor een geïnstalleerde build maar meldt de versie van Python wanneer BlindRSS vanuit de bron wordt uitgevoerd. Deze opdracht geeft in beide gevallen het juiste antwoord.

## Over BlindRSS {#about}

Help, Over toont de versie, de licentie en koppelingen: het GitHub-profiel, de repository en de changelog.

BlindRSS valt onder de MIT-licentie — gebruik het, wijzig het, verspreid het opnieuw of verpak het voor de repositories van een distributie, zonder toestemming nodig te hebben.

## Dit helpvenster gebruiken {#help-window}

Dit venster is een eenvoudige, volledig toetsenbordtoegankelijke lezer voor de handleiding.

- De inhoudslijst bevat elk onderdeel. Gebruik de pijlen; een onderdeel selecteren springt de tekst erheen en kondigt de titel aan.
- Het tekstgebied is alleen-lezen en selecteerbaar, zodat een schermlezer regel voor regel kan lezen en u eruit kunt kopiëren.
- Ctrl+F verplaatst naar het zoekvak. Typ een woord en druk op Enter om naar de volgende vindplaats te springen.
- F3 vindt de volgende vindplaats, Shift+F3 de vorige. Zoeken loopt rond.
- Tab en Shift+Tab verplaatsen tussen het zoekvak, de inhoudslijst en de tekst.
- Escape sluit het venster.

F1 overal in BlindRSS opent dit venster bij het onderdeel voor wat u gebruikt — het gefocuste besturingselement, het actieve dialoogvenster, het gemarkeerde menu-item of de speler. Wanneer er geen onderdeel voor is, opent de handleiding aan het begin.

De handleiding wordt getoond in de interfacetaal van BlindRSS als een vertaling ervan bestaat, en anders in het Engels.

## Problemen oplossen {#troubleshooting}

Een feed wordt niet meer bijgewerkt. Kijk in Feeds met fouten naar de reden. Van een verplaatste feed moet het adres worden gecorrigeerd in Feedeigenschappen; een site die een browsercontrole eist heeft Sitecookies importeren nodig.

Een YouTube-video speelt niet af. Importeer YouTube-cookies in Instellingen, YouTube en schakel "YouTube afspelen door eerst te downloaden" in. Een fout "meld u aan om te bevestigen dat u geen bot bent" betekent altijd cookies.

Afspelen hapert. Vergroot de netwerkcache in Instellingen, Mediaspeler en schakel Stilte overslaan uit, dat experimenteel is en CPU kost.

Een site geeft helemaal niets terug. Wijzig de browseridentificatie in Instellingen, Geavanceerd; sommige sites weigeren onbekende clients ronduit.

Er wordt niets uitgesproken wanneer een opdracht draait. Controleer Aankondigingen in Instellingen, Meldingen — elke gebeurtenis kan afzonderlijk aan of uit en er is een testknop.

Iets gedraagt zich vreemd en u wilt het melden. Zet debugmodus aan in Instellingen, Algemeen, reproduceer het probleem en voeg het blindrss.log bij dat naast uw instellingen en gegevens is geschreven.

## Ondersteuning en gemeenschap {#support}

Fouten en functieverzoeken horen in de GitHub-issuetracker, op github.com/serrebidev/BlindRSS/issues.

Voor vragen, hulp en releasenieuws is de SerrebiProjects-groep op Telegram, op t.me/SerrebiProjects, de snelste plaats om antwoord te krijgen.

Vertalingen zijn altijd welkom. Als u een van de ondersteunde talen spreekt en iets verkeerd leest, wordt een pull request dat dit repareert vrijwel zeker geaccepteerd — zie locale/README.md in de repository voor de indeling van de bestanden. Hetzelfde geldt voor deze handleiding: een vertaalde kopie hoort in docs/help/<language>.md, waarbij de markeringen {#anchor} exact behouden blijven zoals in het Engelse bestand zodat contextgevoelige help blijft werken.
