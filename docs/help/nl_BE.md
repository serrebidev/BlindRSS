# BlindRSS-gebruikershandleiding

## BlindRSS-gebruikershandleiding {#user-guide}

BlindRSS is een schermlezer-vriendelijke desktopclient voor RSS en podcasts. Hij leest RSS- en Atom-feeds, speelt podcast- en video-enclosures af en werkt zelfstandig of met een onlineaccount zoals Miniflux, Inoreader, The Old Reader of BazQux.

Deze handleiding staat in de toepassing, dus werkt zonder internetverbinding of webbrowser. Druk overal in BlindRSS op F1 om haar te openen. Heeft het besturingselement, dialoogvenster, menu-item of venster dat u gebruikt een eigen onderdeel, dan opent F1 dat onderdeel in plaats van het begin.

Alles hier is met het toetsenbord bereikbaar. Gebruik de inhoudslijst om tussen onderdelen te gaan of het zoekvak om een woord overal in de handleiding te vinden.

## Aan de slag {#getting-started}

Wanneer BlindRSS voor het eerst start, heeft het geen feeds. U kunt er op verschillende manieren toevoegen:

- Druk op Ctrl+N om een feed op adres toe te voegen. Zie Een feed toevoegen.
- Druk op Ctrl+Shift+F om podcast- en feedgidsen op naam te doorzoeken. Zie Podcasts en RSS-feeds zoeken.
- Importeer een OPML-bestand dat uit een andere lezer werd geëxporteerd. Zie OPML importeren.
- Importeer een YouTube Takeout-archief om u te abonneren op elk kanaal dat u al volgt. Zie Een YouTube Takeout-archief importeren.
- Meld u aan bij een onlineaccount via Extra, Instellingen, Provider; BlindRSS leest dan de abonnementen die al in dat account staan. Zie Onlineaccounts en providers.

Zodra u feeds hebt, drukt u op F5 om ze te verversen. Nieuwe artikelen verschijnen in de artikellijst en ongelezen aantallen staan naast elke feed in de boom.

De drie plaatsen die u best vroeg bezoekt zijn Extra, Instellingen (hoe BlindRSS zich gedraagt), Extra, Sneltoetsen (elke opdracht en toets), en deze handleiding.

## Het hoofdvenster {#main-window}

Het hoofdvenster heeft vier hoofdgebieden plus een menubalk en statusbalk. Tab en Shift+Tab gaan ertussen; F6 doorloopt deelvensters in de meeste vensterbeheerders.

- De boom met feeds en mappen links.
- Het zoekveld boven de artikellijst.
- De artikellijst.
- Het leesvenster onder de artikellijst.

De menubalk bevat Bestand, Bewerken, Beeld, Speler, Extra en Help. Druk op Alt om die te bereiken en gebruik daarna de pijltoetsen. Elk menu-item heeft in elke interfacetaal een sneltoetsletter en de menubalk loopt aan beide uiteinden rond.

Afmetingen, de geselecteerde feed en de vensterstatus worden tussen sessies onthouden. "Laatst geselecteerde feed/map onthouden bij opstarten" in Instellingen, Algemeen bepaalt of BlindRSS opnieuw opent bij de feed die u laatst las.

## Lijst met feeds en mappen {#feed-tree}

De boom links toont uw feeds, de categorieën die ze groeperen, Slimme mappen, bewaarde zoekopdrachten en de ingebouwde weergaven (Alle feeds, Favorieten, Verwijderde artikelen en Feeds met fouten).

- Pijl omhoog en pijl omlaag verplaatsen tussen items.
- Pijl rechts vouwt een categorie uit, pijl links vouwt die in.
- Enter of een item selecteren laadt de artikelen in de artikellijst.
- F2 opent de eigenschappen van de geselecteerde feed of categorie.
- De toepassings-toets of Shift+F10 opent het contextmenu.

Elke feed toont haar aantal ongelezen artikelen. Uit- en ingevouwen categorieën worden onthouden, zodat de boom er bij de volgende start hetzelfde uitziet.

Feeds die niet konden bijwerken blijven normaal vermeld; de weergave Feeds met fouten verzamelt ze, zodat een feed die stilletjes stopte niet onopgemerkt blijft.

## Artikellijst {#article-list}

De artikellijst toont de artikelen van wat in de boom is geselecteerd, nadat de huidige Artikelfilter, sorteervolgorde en zoekterm zijn toegepast.

- Pijl omhoog en pijl omlaag verplaatsen tussen artikelen; het leesvenster volgt.
- Enter opent het geselecteerde artikel.
- Shift+Up en Shift+Down breiden de selectie uit, zodat bulkacties op meerdere artikelen tegelijk werken.
- Backspace schakelt gelezen en ongelezen voor het geselecteerde artikel om.
- Delete verwijdert de geselecteerde artikelen; Shift+Delete verwijdert ze zonder bevestigingsvraag.
- Ctrl+D voegt een favoriet toe of verwijdert er een.
- De toepassings-toets of Shift+F10 opent het contextmenu.

Welke kolommen verschijnen en in welke volgorde, is globaal en per feed instelbaar. Zie Kolommen van de artikellijst.

## Leesvenster {#reading-pane}

Het leesvenster onder de artikellijst bevat de tekst van het geselecteerde artikel. Het is een alleen-lezen-tekstgebied; een schermlezer kan het dus regel per regel, woord per woord of teken per teken lezen, en de tekst kan worden geselecteerd en gekopieerd.

- Ctrl+F zoekt in de artikeltekst.
- F3 en Shift+F3 gaan naar de volgende en vorige overeenkomst.
- Enter op een koppeling in de tekst opent die koppeling.

Hoe de tekst wordt voorgesteld is instelbaar in Instellingen, Feeds en artikelen: koppen kunnen worden aangekondigd, lijstitems met opsommingstekens en nummers gemarkeerd, citaten gemarkeerd, koppelingen met hun adres getoond, tabellen beschreven en alternatieve afbeeldings-tekst opgenomen. Alternatieve tekst kan ook voor één feed aan of uit worden gezet via het contextmenu van die feed.

Publiceert een feed alleen een korte samenvatting, dan kan BlindRSS de volledige artikeltekst ophalen. Zie Volledige artikeltekst ophalen.

## Artikelvenster {#article-window}

Een artikel openen kan het in een eigen venster zetten in plaats van in het leesvenster. Zo krijgt het artikel het hele scherm en blijft het open terwijl u verdergaat in de lijst.

Het venster is een alleen-lezen-tekstgebied met hetzelfde lees-, selectie- en zoekgedrag als het leesvenster. Escape sluit het.

## Zoekveld {#search-field}

Het zoekveld boven de artikellijst filtert de huidige weergave terwijl u typt en bevestigt met Enter.

- Ctrl+E verplaatst de focus naar het zoekveld.
- Enter past de term toe.
- Escape, of de knop Wissen, leegt het veld en herstelt de volledige lijst.

Het zoekveld kan worden verborgen als u het nooit gebruikt; het menu Beeld heeft de opdracht Zoekveld tonen/verbergen. Of zoeken alleen titels dan wel titels en artikeltekst doorzoekt, stelt u in bij Instellingen, Feeds en artikelen onder "Zoeken komt overeen met".

Een zoekopdracht die u wilt houden kunt u omzetten in een bewaarde zoekopdracht die in de boom blijft staan. Zie Permanente zoekopdrachten.

## Statusbalk {#status-bar}

De statusbalk onderaan het hoofdvenster heeft drie velden:

- Tijdelijke berichten, bijvoorbeeld hoeveel artikelen een filter vond.
- Achtergrondactiviteit, zoals het verversen van een feed of een download die loopt.
- Afspeelstatus: wat speelt, en de verstreken en resterende tijd.

Ze zijn bewust apart, zodat een verversbericht geen aantal zoekresultaten kan overschrijven terwijl u dat leest.

## Contextmenu's {#context-menus}

De feedsboom en de artikellijst hebben elk een contextmenu, dat u opent met de toepassings-toets of Shift+F10. Ze bevatten de opdrachten voor wat is geselecteerd — verversen, als gelezen markeren, bewerken, verwijderen, koppelingen kopiëren, media in de wachtrij plaatsen enzovoort.

Contextmenu's ondersteunen ook F1: met een item gemarkeerd opent F1 het onderdeel van deze handleiding dat het uitlegt.

## Een feed toevoegen {#adding-feeds}

Bestand, Feed toevoegen (Ctrl+N) abonneert u op een feed via adres.

Plak of typ het adres van de feed, of van de site zelf — BlindRSS zoekt op de pagina naar een feed wanneer het adres geen feed is. U kunt ook een YouTube-kanaal- of afspeellijstadres, Mastodon- of Bluesky-profiel, PieFed- of Lemmy-community, SoundCloud- of Mixcloud-pagina, of Reddit- of Groups.io-adres plakken; BlindRSS maakt er een feed van.

Kies de categorie waarin de feed moet staan of laat hem ongecategoriseerd. De optie "Openen in HTML-weergave" laat artikelen van deze feed standaard in de rijke weergave openen.

Kent u het adres niet, gebruik dan Podcasts en RSS-feeds zoeken.

## Feeds op een pagina detecteren {#detect-feeds}

Bestand, Feeds op pagina detecteren neemt het adres van een gewone webpagina en somt de feeds op die die pagina aanbiedt, zodat u zich kunt abonneren zonder zelf naar de feedkoppeling te zoeken.

Dit is de juiste opdracht als een site een koppeling "abonneren" of "RSS" heeft die u moeilijk kunt bereiken, of wanneer de pagina verschillende feeds biedt (alle berichten, één categorie, reacties) en u wilt kiezen.

## Podcasts en RSS-feeds zoeken {#find-podcast}

Extra, Een podcast of RSS-feed zoeken (Ctrl+Shift+F) doorzoekt podcast- en feedgidsen op naam, onderwerp of siteadres, zodat u zich kunt abonneren zonder een feedadres te kennen.

1. Typ in het zoekvak wat u zoekt — een podcastnaam, een onderwerp of een siteadres.
2. Kies een bron of laat die op "Alle bronnen" staan.
3. Druk op Enter of op de knop Zoeken.
4. Loop met de pijlen door de resultatenlijst. Elke rij toont de titel, uit welke gids die komt en details.
5. Druk op Enter bij een resultaat, of kies OK, om u erop te abonneren.

Zoekopdrachten lopen tegelijk bij meerdere gidsen en resultaten komen binnen zodra elke gids antwoordt; de lijst groeit dus terwijl u leest. Escape sluit het dialoogvenster en stopt het zoeken.

## Podcast- en feedgidsen {#podcast-directories}

Het vak Bron in Een podcast of RSS-feed zoeken bepaalt waar wordt gezocht. Naast "Alle bronnen", "Alle podcastbronnen" en "Alle RSS-feedbronnen" zijn deze gidsen afzonderlijk beschikbaar:

- Podcastgidsen: iTunes (Apple Podcasts), gPodder, fyyd, Podverse, SoundCloud en Mixcloud.
- Feedgidsen: NewsBlur, Feedspot, Google News, Bing News en Feedly.
- Zoeken naar sites en communities: YouTube, Reddit, Groups.io en de Fediverse — Mastodon, Bluesky, PieFed en Lemmy of Kbin, elk ook afzonderlijk kiesbaar.
- Ontdekking op adres: Feedsearch en BlindRSS' eigen websitescan, die een site ophaalt en daarin naar feeds zoekt.

BlindRSS steunt niet op één gids. Zoeken in "Alle bronnen" bevraagt podcast- en RSS-groepen samen en voegt de resultaten samen; brede Google News-zoekfeeds blijven onder rechtstreekse feedovereenkomsten.

## Abonneren op een zoekresultaat {#subscribing}

In elk zoekdialoogvenster — Een podcast of RSS-feed zoeken, Video zoeken of de zoekknop van Podcastarchief — abonneert Enter op een resultaat, of OK kiezen met dat resultaat geselecteerd, u erop.

BlindRSS zet het resultaat eerst om naar een echt feedadres; een podcast uit een gids, een YouTube-kanaal of een Fediverse-account abonneren werkt dus steeds hetzelfde. De nieuwe feed verschijnt in de boom en wordt onmiddellijk ververst.

Wilt u hem in een bepaalde categorie, verplaats hem dan daarna vanuit het contextmenu of Feed-eigenschappen.

## Podcastarchief {#podcast-archive}

Extra, Podcastarchief doorzoekt de volledige afleveringgeschiedenis van een podcast — zowel de afleveringen die nog in de feed staan als de oudere die BlindRSS herstelde — en downloadt ze in batches.

Veel podcastfeeds publiceren alleen de recentste afleveringen. Archiefherstel loopt automatisch op de achtergrond; in dit venster ziet u de status, probeert u het handmatig opnieuw en downloadt u wat het vond.

- Kies de podcast in het vak Podcast.
- Afleveringen filteren vernauwt de lijst terwijl u typt.
- Archief opnieuw scannen voert herstel voor die podcast opnieuw uit.
- Podcast zoeken of toevoegen opent feedzoeken zodat u een podcast kunt archiveren waarop u nog niet geabonneerd bent.
- Afspelen speelt de geselecteerde aflevering af, Geselecteerde downloaden downloadt ze en Alles downloaden downloadt de hele zichtbare lijst.
- Downloads annuleren stopt een lopende batch.

Het venster blijft open tijdens een batchdownload, zodat u kunt blijven lezen.

## Video zoeken {#video-search}

Extra, Video zoeken doorzoekt in één keer elke site die yt-dlp kan bevragen, en laat u gevonden resultaten afspelen, in de wachtrij zetten of erop abonneren.

- Typ een zoekterm en druk op Enter of de knop Zoeken.
- Het bereikvak beperkt de zoekopdracht tot één site; standaard worden ze allemaal doorzocht.
- Resultaten komen binnen wanneer elke site antwoordt, met grote sites eerst. Titels die als tijdelijke aanduiding binnenkomen worden ingevuld zodra ze zijn opgelost.
- Meer resultaten laden haalt van elke site een volgende batch op.
- Sorteren op een kolomkop herschikt wat al binnenkwam.

Identieke video's op verschillende sites worden tot één rij samengevoegd. Volwassenensites worden uitgesloten, tenzij "Volwassenensites inschakelen in Video zoeken" aanstaat bij Instellingen, Geavanceerd.

## Een artikel via URL openen {#open-article-url}

Bestand, Artikel openen neemt het adres van een willekeurige webpagina en leest die in BlindRSS alsof het een artikel was — geëxtraheerde tekst in het leesvenster, met dezelfde leesopties als al het andere.

Gebruik dit voor een eenmalige pagina die iemand u stuurde, zonder u ergens op te abonneren. Is de pagina een forum- of discussiedraad, dan leest BlindRSS de hele draad. Zie Forum- en discussiedraden.

## Een media-URL openen {#open-media-url}

Bestand, Media-URL openen speelt audio of video van een adres af in de ingebouwde speler, zonder u ergens op te abonneren.

Het aanvaardt rechtstreekse mediakoppelingen en pagina-adressen die yt-dlp kan oplossen — YouTube, Rumble, Odysee, SoundCloud en nog veel meer. Het resultaat speelt als elk ander item en kan aan de afspeelwachtrij worden toegevoegd.

## Een feed verwijderen {#removing-feeds}

Bestand, Feed verwijderen zegt het abonnement op de geselecteerde feed op. Dezelfde opdracht staat in het contextmenu van de feed.

Een feed verwijderen verwijdert haar artikelen uit de database. Het raakt niets aan dat u al naar schijf hebt gedownload. Gebruikt u een onlineprovider, dan wordt de opzegging ook naar dat account gestuurd.

Gebruik Categorie en feeds verwijderen in het contextmenu van een categorie om een hele categorie en alles daarin te verwijderen. Zie Categorieën en subcategorieën.

## Feed-eigenschappen {#feed-properties}

F2, of Feed bewerken in het contextmenu, opent de eigenschappen van de geselecteerde feed.

- De titel, die u kunt overschrijven; "Titel terugzetten naar feedstandaard" in het contextmenu zet de eigen titel van de feed terug.
- Het adres en de categorie waartoe de feed behoort.
- Of nieuwe artikelen ervan een melding geven.
- Of die in de rijke HTML-weergave opent.
- De eigen kolomindeling van de artikellijst op het tabblad Lijstkoppen, die de globale indeling overschrijft.

Feedbeschrijving weergeven in het contextmenu van de artikellijst toont de beschrijving die de feed zelf publiceert.

## Categorieën en subcategorieën {#categories}

Categorieën groeperen feeds in de boom en kunnen genest zijn: een categorie kan zowel feeds als verdere subcategorieën bevatten.

- Bestand, Categorie toevoegen maakt er een.
- Subcategorie toevoegen in het contextmenu van een categorie maakt er een binnenin.
- Categorie bewerken hernoemt of verplaatst die. Zie Categorie-eigenschappen.
- Categorie verwijderen verwijdert de categorie maar behoudt haar feeds.
- Categorie en feeds verwijderen verwijdert de categorie en zegt alle abonnementen erin op.
- OPML hier importeren importeert een bestand rechtstreeks in die categorie.
- Categorie exporteren naar OPML exporteert alleen die tak.

Sommige onlineproviders bewaren categorieën in één vlakke lijst. Is dat zo, dan zegt BlindRSS dat en zijn de opties om naar een bovenliggende categorie te verplaatsen niet beschikbaar.

## Categorie-eigenschappen {#category-properties}

Categorie bewerken opent de eigenschappen van de categorie: haar naam en de bovenliggende categorie waaronder zij staat.

Een categorie hernoemen behoudt al haar feeds. Ze verplaatsen verplaatst de hele tak, met eventuele subcategorieën.

## Feeds verversen {#refreshing}

- F5 ververst elke feed.
- Ctrl+F5 ververst alleen de geselecteerde feed of categorie.
- Shift+F5 stopt een lopende verversing.
- Categorie verversen in het contextmenu van een categorie ververst die tak.

Slechts één van Feeds verversen en Verversen stoppen is tegelijk beschikbaar, zodat de toetsenbordopdracht overeenkomt met wat het menu biedt. Voortgang verschijnt in het tweede veld van de statusbalk.

Automatisch verversen stelt u in bij Instellingen, Feeds en artikelen: het interval, hoeveel feeds tegelijk verversen, hoeveel verbindingen per host, de time-out per feed en hoe vaak een mislukte feed opnieuw wordt geprobeerd. "Feeds automatisch verversen bij opstarten" ververst alles bij de start, en de optie voor opstartwerklast kiest tussen de cache gebruiken en een volledige verversing forceren.

## Feeds met fouten {#feed-errors}

De weergave Feeds met fouten en Bestand, Feedfouten weergeven tonen de feeds waarvan de laatste update mislukte, met de reden.

Een feed die stilletjes stopte werkt ziet er precies uit als een feed zonder nieuwe artikelen; daarom bestaat deze weergave. Van daaruit kunt u:

- Geselecteerde verversen om het nu opnieuw te proberen.
- Details kopiëren om de fouttekst op het klembord te zetten.
- Feed-eigenschappen kiezen om het adres te corrigeren.
- Feed verwijderen wanneer de feed definitief verdwenen is.

Veelvoorkomende oorzaken zijn een verhuisde of stopgezette feed, een site die nu een browsercontrole vereist (zie Sitecookies importeren), en een tijdelijke serverstoring.

## OPML importeren {#import-opml}

OPML is het standaardbestandsformaat voor een lijst feedabonnementen. Elke feedlezer kan er een exporteren; via OPML verplaatst u abonnementen vanuit een andere lezer naar BlindRSS zonder ze een voor een toe te voegen.

Bestand, OPML importeren vraagt om het bestand en voegt elke feed erin toe, met behoud van de categorie-structuur die het bestand beschrijft. Feeds waarop u al bent geabonneerd worden niet gedupliceerd.

OPML hier importeren in het contextmenu van een categorie plaatst de hele import in die categorie in plaats van op het hoogste niveau.

Zoek in de instellingen van een andere lezer naar "Exporteren", "Back-up" of "Abonnementen" om er een OPML-bestand uit te halen.

## OPML exporteren {#export-opml}

Bestand, OPML exporteren schrijft al uw abonnementen met hun categorieën naar een OPML-bestand.

Gebruik het om abonnementen te back-uppen, naar een andere lezer of machine te verplaatsen, of om een set feeds met iemand anders te delen. Categorie exporteren naar OPML in het contextmenu van een categorie exporteert alleen die tak.

## Een YouTube Takeout-archief importeren {#import-youtube-takeout}

Google Takeout is de gegevens-exportdienst van Google. Een YouTube Takeout-archief is een ZIP-bestand met uw YouTube-gegevens, waaronder de lijst kanalen waarop u geabonneerd bent. Bestand, YouTube Takeout importeren leest die ZIP en abonneert u op die kanalen als feeds, zodat de nieuwe video's van elk kanaal als artikelen binnenkomen.

Om het archief te krijgen:

1. Ga naar takeout.google.com en meld u aan met het Google-account waarop uw YouTube-abonnementen staan.
2. Kies "Alles deselecteren" en selecteer daarna alleen YouTube en YouTube Music.
3. Behoud in "Alle YouTube-gegevens inbegrepen" minstens "abonnementen"; "geschiedenis" en "afspeellijsten" zijn optioneel en BlindRSS kan ze ook gebruiken.
4. Exporteer eenmaal als ZIP-bestand en wacht op de e-mail van Google — een groot archief kan uren duren.
5. Download de ZIP en wijs deze opdracht ernaar.

BlindRSS toont vervolgens wat het vond, gegroepeerd op bron, en laat u kiezen welke groepen te importeren:

- Abonnementen: de kanalen die u volgt.
- Geschiedenis: kanalen die u hebt bekeken maar niet volgt.
- Uw eigen kanalen.
- Afspeellijsten als eigen feeds.

Dubbele adressen worden verwijderd; een tweede archief later importeren voegt dus alleen nieuwe zaken toe. De ZIP wordt nooit naar schijf uitgepakt; alleen de kleine gegevensbestanden erin worden gelezen.

## Permanente zoekopdrachten {#persistent-search}

Een permanente zoekopdracht is een zoekterm die als eigen item in de boom blijft staan, zodat de passende artikelen altijd maar één pijltoets ver zijn.

Extra, Permanente zoekopdracht configureren beheert de lijst: Toevoegen maakt er een op basis van een term, Verwijderen wist die. Elke bewaarde zoekopdracht staat in de boom en wordt opnieuw geëvalueerd wanneer u haar selecteert, zodat zij steeds de huidige artikelen weergeeft.

Gebruik dit voor een onderwerp dat u over alle feeds volgt — een persoonsnaam, product of plaats. Gebruik voor iets gestructureerders dan een woordgroep Slimme mappen.

## Slimme mappen {#smart-folders}

Een Slimme map is een map in de boom waarvan de inhoud door een regel wordt bepaald in plaats van door de feed waaruit een artikel kwam.

Nieuwe slimme map in het contextmenu van de boom opent de regelbewerker. Een regel is een verzameling voorwaarden verbonden met "alles overeenkomt" (en) of "iets overeenkomt" (of), en groepen voorwaarden kunnen nesten; "(A en B) of C" kan dus worden uitgedrukt.

Voorwaarden testen deze velden:

- Ja/nee-velden: gelezen, favoriet, geopend, bijgewerkt.
- Tekstvelden: titel, inhoud, beschrijving, auteur, feed, url en tag — de categorieën of tags die de site zelf publiceert.

Tekstvoorwaarden gebruiken bevat, bevat niet, is gelijk aan of begint met.

Slimme mappen verplaatsen of kopiëren nooit iets; ze zijn een weergave van de artikelen die u al hebt. Gebruik Filterregels om artikelen te veranderen terwijl ze binnenkomen.

## Filterregels {#filter-rules}

Extra, Filterregels is BlindRSS' sorteerprogramma voor artikelen. Regels werken op binnenkomende artikelen zoals e-mailfilters op binnenkomende e-mail werken.

Elke regel koppelt een voorwaarde — dezelfde regelbewerker die Slimme mappen gebruiken — aan een set acties:

- Het artikel naar een categorie verplaatsen.
- Het ook met een categorie labelen, terwijl het blijft waar het is.
- Het als gelezen markeren.
- Het als favoriet markeren.
- Het verwijderen volgens uw ingestelde verwijdergedrag.
- De melding voor nieuw artikel overslaan.

Regels lopen in lijstvolgorde; elke ingeschakelde regel die overeenkomt draagt zijn acties bij. Een regel die is gemarkeerd om te stoppen beëindigt de pijplijn voor dat artikel zodra hij overeenkomt, zodat latere regels het nooit zien. Verplaats regels omhoog of omlaag om te bepalen welke wint.

Een regel zonder acties doet niets en wordt geweigerd, zodat een half afgewerkte regel niet stilletjes artikelen kan opslokken.

## Artikelfilter {#article-filter}

Beeld, Artikelfilter beperkt elke weergave op leesstatus en op de vraag of een artikel media heeft. De twee groepen worden gecombineerd.

- Ctrl+1: alle artikelen.
- Ctrl+2: alleen ongelezen.
- Ctrl+3: alleen gelezen.
- Ctrl+4: media en niet-media.
- Ctrl+5: alleen met media.
- Ctrl+6: alleen zonder media.

Het filter geldt voor wat u ook in de boom selecteert, inclusief Slimme mappen en bewaarde zoekopdrachten, en blijft tussen sessies behouden. "Alleen met media" is de snelste manier om een gemengde feed in een podcastlijst te veranderen.

## Artikelen sorteren {#sorting}

Beeld, Sorteren op ordent de artikellijst op datum, naam, auteur, beschrijving, feed of status. Oplopend wisselt de richting; standaard staat de nieuwste eerst.

De sortering geldt voor elke weergave en wordt tussen sessies onthouden. Sorteren op feed is nuttig in Alle feeds en Slimme mappen, waar artikelen uit veel bronnen tegelijk komen.

## Kolommen van de artikellijst {#list-headers}

De kolommen in de artikellijst, hun volgorde en breedtes kiest u zelf. Instellingen, Lijstkoppen zet de globale indeling; het eigen tabblad Lijstkoppen van een feed overschrijft die voor die feed en "De globale kolomindeling gebruiken" schakelt de overschrijving weer uit.

Minder kolommen betekent minder dat een schermlezer op elke rij moet lezen; daarom loont het om kolommen die u nooit gebruikt weg te halen.

## Artikelen openen {#opening-articles}

Enter op een artikel in de lijst opent het. Afhankelijk van artikel en instellingen betekent dat het leesvenster, een eigen venster of de rijke HTML-weergave.

- Artikel openen in het contextmenu doet hetzelfde.
- Openen in browser geeft het adres van het artikel door aan uw systeemwebbrowser.
- Toegankelijke browser openen leest de pagina in plaats daarvan binnen BlindRSS. Zie Toegankelijke browser.

Een artikel openen markeert het als gelezen tenzij u dat gedrag hebt veranderd.

## Gelezen en ongelezen artikelen {#read-status}

- Backspace, of Gelezen/ongelezen schakelen, wisselt het geselecteerde artikel.
- Ctrl+Shift+R markeert alles in de huidige weergave als gelezen.
- Alle items als gelezen markeren in het contextmenu van een feed of categorie doet hetzelfde voor die tak.
- Als gelezen markeren en Als ongelezen markeren in het contextmenu van de artikellijst werken op de hele selectie en zeggen op hoeveel artikelen zij van toepassing zijn.

Aantallen ongelezen artikelen staan naast elke feed in de boom. De Artikelfilter kan gelezen artikelen volledig verbergen.

## Favorieten {#favorites}

Ctrl+D voegt het geselecteerde artikel toe aan Favorieten, of verwijdert het als het daar al staat. De weergave Favorieten in de boom toont alles wat u hebt gemarkeerd.

Favorieten overleven het bewaarbeleid: een artikel dat u een ster gaf wordt niet verwijderd wanneer oudere artikelen worden opgeruimd. Favoriet is ook bruikbaar als voorwaarde in Slimme mappen en Filterregels.

## Verwijderde artikelen {#deleted-articles}

Wat Delete doet is instelbaar in Instellingen, Algemeen onder "Wanneer ik een artikel verwijder":

- Het naar Verwijderde artikelen verplaatsen, waar het kan worden hersteld.
- Het permanent verwijderen.
- Het naar een categorie verplaatsen die u noemt.

Bij de eerste instelling toont de weergave Verwijderde artikelen in de boom wat u verwijderde, Herstellen zet een artikel terug en verwijderen vanuit die weergave verwijdert het definitief.

"Bevestigen voor het verwijderen van artikelen" regelt de bevestigingsvraag. Shift+Delete slaat die altijd over.

## Volledige artikeltekst ophalen {#full-text}

Veel feeds publiceren alleen een kop en een zin of twee. BlindRSS kan de artikelpagina ophalen en de echte tekst extraheren, zodat het leesvenster het hele artikel toont in plaats van een teaser.

Dit gebeurt automatisch op de achtergrond terwijl u door de lijst beweegt, en het resultaat wordt in cache bewaard. "Volledige tekst op achtergrond cachen" in Instellingen, Feeds en artikelen haalt de artikelen rond uw positie vooraf op, zodat naar beneden gaan in de lijst niet op het netwerk wacht.

Weigert een site volledig gelezen te worden, dan staat die meestal achter een browsercontrole. Zie Sitecookies importeren.

## Rijke volledige-tekstweergave {#rich-view}

Ctrl+Shift+H schakelt het leesvenster naar de rijke HTML-weergave, die het artikel weergeeft zoals een browser dat zou doen, met koppen, lijsten, tabellen en koppelingen als echte elementen waar een schermlezer met eigen structuurcommando's door kan navigeren.

De plattetekstweergave is standaard omdat ze sneller is en u nooit verrast. De rijke weergave is de moeite waard voor artikelen waarvan de structuur betekenis draagt.

Een feed kan via haar Feed-eigenschappen altijd in de rijke weergave openen; koppelingen in die weergave openen in uw systeembrowser in plaats van binnen de weergave.

## Toegankelijke browser {#accessible-browser}

Beeld, Toegankelijke browser openen opent een pagina binnen BlindRSS in een venster dat voor lezen met een schermlezer is gebouwd, in plaats van ze aan uw systeembrowser te geven.

Dit is het juiste hulpmiddel voor een pagina die moet worden gelezen in plaats van gebruikt, en voor sites waarvan de eigen interface lastig te navigeren is. Het deelt BlindRSS' cookie- en browseridentiteitsinstellingen; pagina's achter een browsercontrole openen hier dus ook nadat u er cookies voor hebt geïmporteerd.

## YouTube-video's {#youtube}

U kunt zich op een YouTube-kanaal- of afspeellijstadres abonneren zoals op elke feed. De video's komen dan als artikelen binnen, met beschrijving, transcript en hoofdstukkenlijst inline, zodat een video kan worden gelezen in plaats van bekeken.

Afspelen gaat via yt-dlp. Instellingen, YouTube regelt dit:

- Een cookies-bestand waarmee BlindRSS video's met leeftijdsbeperking en alleen voor leden kan zien waartoe u toegang hebt. Het kan rechtstreeks uit een browser worden geïmporteerd of automatisch worden opgehaald uit cookies.txt-exporten in uw map Downloads.
- "YouTube eerst downloaden om af te spelen", dat trager start maar veel betrouwbaarder is.
- De map voor afspeelcache en de maximale grootte ervan, met een knop om ze te wissen.

YouTube Takeout importeren abonneert u in één stap op alle kanalen die u al volgt.

## Forum- en discussiedraden {#forums}

Reddit, Lemmy, Groups.io en Google Groups worden als volledige draden gelezen in plaats van één bericht tegelijk: een discussie openen geeft u het oorspronkelijke bericht en de antwoorden in één doorlopende tekst, veel sneller te lezen dan een draad volgen in een browser.

Abonneren werkt zoals bij elke feed — plak het adres van de subreddit, community of groep. GitHub-opslagplaatsen worden op dezelfde manier ondersteund, net als Mastodon-, Bluesky- en PieFed-accounts en communities.

## Knippen, kopiëren en plakken {#clipboard}

Het menu Bewerken bevat de standaardklembordopdrachten — Knippen (Ctrl+X), Kopiëren (Ctrl+C), Plakken (Ctrl+V) en Alles selecteren (Ctrl+A) — en ze werken in elk tekstveld en het leesvenster.

BlindRSS voegt opdrachten toe die zaken kopiëren die het kent:

- Koppeling kopiëren, het adres van het artikel.
- Mediakoppeling kopiëren, het adres van audio of video.
- Tekst kopiëren, de artikeltekst zoals die in het leesvenster wordt gelezen.
- Feed-URL kopiëren, het adres van de geselecteerde feed.
- Afbeeldingskoppeling kopiëren bij een artikel met een afbeelding.

## De ingebouwde speler {#player}

BlindRSS speelt podcast- en video-enclosures zelf af via VLC; afspelen verlaat de toepassing dus nooit. Ctrl+Shift+P toont of verbergt het spelervenster en afspelen gaat in beide gevallen door.

Afspelen wordt vloeiender gemaakt door een lokale range-cacheproxy; daarom is zoeken in een lange aflevering snel, zelfs bij een trage verbinding. Streams die moeten worden opgelost — YouTube, Rumble, Odysee — gaan eerst door yt-dlp.

"Spelervenster tonen bij starten van afspelen" in Instellingen, Mediaspeler bepaalt of het venster vanzelf verschijnt wanneer iets start.

## Spelerbediening {#player-controls}

Het spelervenster bevat in tabvolgorde: de afspeelstatus, de positieschuifregelaar, verstreken en totale tijd, knoppen terugspoelen en vooruitspoelen, het snelheidsvak, de hoofdstukkenknop en de volumeschuifregelaar. Ze zijn allemaal met het toetsenbord bereikbaar en bedienbaar, en elk kondigt zijn huidige waarde aan.

- Ctrl+P speelt af en pauzeert.
- Ctrl+S stopt.
- Ctrl+Left en Ctrl+Right spoelen terug en vooruit en herhalen terwijl ze ingedrukt zijn. Op macOS doen Option+Left en Option+Right hetzelfde, omdat Ctrl+Left en Ctrl+Right daar bij Mission Control horen.
- Ctrl+Up en Ctrl+Down wijzigen het volume.

De toetsen voor zoeken en volume werken overal in BlindRSS terwijl iets speelt, ook in een dialoogvenster; u hoeft dus nooit het spelervenster te vinden om te pauzeren.

## Sneltoetsen van de speler {#player-shortcuts}

- Ctrl+Shift+P: het spelervenster tonen of verbergen.
- Ctrl+P: afspelen of pauzeren.
- Ctrl+S: stoppen.
- Ctrl+Left en Ctrl+Right: terug- en vooruitspoelen (Option+Left en Option+Right op macOS).
- Ctrl+Up en Ctrl+Down: volume hoger en lager.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: sneller, trager, terug naar normale snelheid.
- Ctrl+Shift+E: de equalizer.
- Ctrl+Shift+C: de afspeelwachtrij.
- Ctrl+Shift+T en Ctrl+Shift+V: volgende en vorige in de wachtrij.

Al deze zijn in Extra, Sneltoetsen opnieuw toe te wijzen. De snelheidsopdrachten gebruiken bewust standaard letters in plaats van Ctrl+Shift+cijfer of Ctrl+Shift+punt, omdat Windows en sommige NVDA-add-ons die onderscheppen vóór een toepassing ze ziet.

## Afspeelsnelheid {#playback-speed}

Speler, Afspeelsnelheid wijzigt hoe snel media afspelen, van halve tot driedubbele snelheid, met behoud van toonhoogte.

- Ctrl+Shift+U versnelt, Ctrl+Shift+D vertraagt, Ctrl+Shift+N keert terug naar 1x.
- Het submenu heeft vaste stappen: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x en 3x.
- Het spelervenster heeft een snelheidsvak dat u rechtstreeks kunt instellen.

"Standaard afspeelsnelheid" in Instellingen, Mediaspeler stelt de snelheid in waarmee alles start.

## Equalizer {#equalizer}

Ctrl+Shift+E, of Speler, Equalizer, opent een tientraps-equalizer met voorversterker.

- "Equalizer inschakelen" schakelt alles in en uit.
- Elke band is een schuifregelaar die de versterking aankondigt wanneer u die wijzigt.
- Opslaan als voorinstelling bewaart de huidige banden onder een naam; Voorinstelling verwijderen verwijdert er een.
- Herstellen (vlak) zet elke band op nul terug.

De equalizer geldt voor alles wat BlindRSS speelt en de instelling wordt onthouden.

## Hoofdstukken {#chapters}

Podcasts en YouTube-video's hebben vaak hoofdstukken. Wanneer het spelende item ze heeft, toont Speler, Hoofdstukken ze en springt kiezen van een hoofdstuk daarheen.

- Het submenu Hoofdstukken wordt gevuld zodra de hoofdstukken van het item bekend zijn en zegt "Geen hoofdstukken beschikbaar" als het er geen heeft.
- Het spelervenster heeft een hoofdstukkenknop en een hoofdstukkenvak.
- Hoofdstukkoppelingen in het contextmenu van de artikellijst somt de koppelingen op die een hoofdstukbeschrijving bevat.

Hoofdstukken worden op de achtergrond geladen terwijl u door de lijst beweegt; meestal zijn ze dus klaar voordat u op afspelen drukt.

## Afspeelwachtrij {#play-queue}

De afspeelwachtrij is de lijst van wat hierna speelt.

- Ctrl+Shift+C opent het wachtrijvenster.
- Ctrl+Shift+T en Ctrl+Shift+V spelen het volgende en vorige item.
- Aan afspeelwachtrij toevoegen en Uit afspeelwachtrij verwijderen in het contextmenu van de artikellijst wijzigen die.

In het wachtrijvenster start Afspelen het geselecteerde item, Omhoog en Omlaag verplaatsen ordenen de wachtrij opnieuw, Verwijderen laat één item vallen en Alles wissen leegt haar. De wachtrij overleeft herstarts.

## Casten naar andere apparaten {#casting}

BlindRSS kan wat het speelt naar een apparaat op uw netwerk sturen: Chromecast, DLNA/UPnP-renderers en AirPlay-ontvangers.

Kies het apparaat in het castdialoogvenster; BlindRSS streamt via zijn eigen lokale proxy, zodat een apparaat dat zelf het oorspronkelijke adres niet kan ophalen het item toch afspeelt. Transportbediening blijft vanuit BlindRSS werken tijdens het casten.

## Stilte overslaan {#silence-skipping}

"Stilte overslaan (experimenteel)" in Instellingen, Mediaspeler detecteert stille passages tijdens afspelen en slaat ze over, wat praatpodcasts met lange pauzes merkbaar verkort.

Het analyseert audio tijdens het afspelen en kost dus wat CPU; daarom is het experimenteel gemarkeerd. Zet het uit als afspelen niet vloeiend is.

## Media downloaden {#downloads}

- Downloaden bewaart de audio of video van het geselecteerde artikel in de standaardindeling.
- Downloaden als laat u eerst de indeling kiezen.

Downloads moeten worden ingeschakeld met "Downloads inschakelen" in Instellingen. De downloadmap, het bewaarbeleid en de standaardindeling voor videodownloads staan op dezelfde pagina; standaard is de map Downloads van uw systeem.

Voortgang staat in het tweede statusbalkveld en gedownloade items spelen daarna van schijf in plaats van via het netwerk. Podcastarchief kan de volledige achtercatalogus van een podcast in één batch downloaden.

## Instellingen {#settings}

Extra, Instellingen (Ctrl+comma) bevat elke optie op de tabbladen: Algemeen, Feeds en artikelen, YouTube, Mediaspeler, Provider, Meldingen, Vertalen, Lijstkoppen, Geavanceerd en CAPTCHA oplossen.

Ctrl+Tab en Ctrl+Shift+Tab wisselen tussen tabbladen; Tab doorloopt de besturingselementen op het huidige tabblad. OK past alles toe, Annuleren verwerpt alles. Posities van tabbladen blijven stabiel tussen uitgaven omdat ze spiergeheugen worden.

F1 op een tabblad openen drukt het onderdeel van deze handleiding voor dat tabblad.

## Instellingen: Algemeen {#settings-general}

- Interfacetaal en of BlindRSS uw systeemtaal volgt. Een wijziging wordt actief bij herstart. Zie Interfacetaal.
- "Laatst geselecteerde feed/map onthouden bij opstarten".
- "Bevestigen voor het verwijderen van artikelen", en wat verwijderen doet — naar Verwijderde artikelen verplaatsen, permanent verwijderen of naar een categorie die u noemt verplaatsen.
- "Debugmodus (console tonen bij opstarten)", die ook een roterende blindrss.log naast uw gegevens schrijft.
- Opstarten en systeemvak: sluiten naar systeemvak, minimaliseren naar systeemvak, starten in systeemvak, altijd gemaximaliseerd starten en bij opstarten op updates controleren.

## Instellingen: Feeds en artikelen {#settings-feeds}

- Het automatische verversinterval, van vijf minuten tot vier uur.
- Of zoeken alleen titels matcht, dan wel titels en artikeltekst.
- Maximum gelijktijdige verversingen, maximum verbindingen per host, de feed-time-out en hoe vaak een mislukte feed opnieuw wordt geprobeerd.
- Maximum aantal gecachte weergaven en "Volledige tekst op achtergrond cachen".
- "Feeds automatisch verversen bij opstarten", en de opstartververswerklast: cache gebruiken, volledig verversen bij opstarten of altijd volledig verversen.
- Bewaren van artikelen, dat bepaalt hoe lang artikelen blijven. Favorieten worden nooit door bewaren verwijderd.
- Hoe artikeltekst wordt voorgesteld: koppen aankondigen, lijstitems met opsommingstekens en nummers markeren, citaten markeren, koppelingen met hun adres tonen, tabellen beschrijven en alternatieve afbeeldings-tekst opnemen.

## Instellingen: YouTube {#settings-youtube}

- Het yt-dlp-cookies-bestand, met een knop Bladeren, een knop "Uit browser importeren" en een optie om cookies.txt-exporten automatisch op te halen uit uw map Downloads.
- Cookies rechtstreeks uit een geïnstalleerde browser lezen.
- "YouTube eerst downloaden om af te spelen", dat trager start maar de betrouwbaarste optie is.
- De YouTube-afspeelcachemap, de maximale grootte in megabytes en een knop om die nu te wissen.

Cookies maken video's met leeftijdsbeperking en alleen voor leden afspeelbaar; zij zijn wat de fout "aanmelden om te bevestigen dat u geen bot bent" vraagt.

## Instellingen: Mediaspeler {#settings-media-player}

- De voorkeursgeluidskaart of de systeemstandaard.
- "Stilte overslaan (experimenteel)". Zie Stilte overslaan.
- De standaard afspeelsnelheid.
- "Spelervenster tonen bij starten van afspelen".
- De netwerkgrootte in milliseconden, die opstartvertraging afweegt tegen bestendigheid bij een trage verbinding.
- Paden naar ffmpeg, ffprobe en yt-dlp. Laat er één leeg om automatisch te detecteren; een ingesteld pad overschrijft detectie en wat werd gedetecteerd wordt ernaast getoond.
- Downloads: of downloads zijn ingeschakeld, de downloadmap, het bewaarbeleid en de standaardindeling voor videodownloads.
- Geluiden: of BlindRSS zijn meldingsgeluiden speelt.

## Instellingen: Provider {#settings-provider}

Kiest waar uw abonnementen leven: lokaal in BlindRSS of in een onlineaccount. Zie Onlineaccounts en providers voor wat elk nodig heeft.

De pagina toont welke provider actief is en de aanmeldgegevens ervan — een Miniflux-adres en API-sleutel, een Inoreader-app-ID en -sleutel met een knop Autoriseren, of een e-mailadres en wachtwoord voor The Old Reader of BazQux. Autorisatie wissen meldt een Inoreader-account af.

De lokale provider gebruikt de feeds die u binnen de app toevoegt met Feed toevoegen en OPML importeren.

## Instellingen: Meldingen {#settings-notifications}

- "Meldingen inschakelen voor nieuwe artikelen", en of de naam van de feed in de meldingstekst verschijnt.
- Het maximumaantal meldingen per verversing en of een samenvattingsmelding wordt getoond zodra die limiet is bereikt.
- Melding testen verstuurt er nu een.
- Feeds uitsluiten kiest feeds die nooit melden.
- Aankondigingen: welke gebeurtenissen BlindRSS rechtstreeks aan uw schermlezer uitspreekt, per gebeurtenis, met een knop Aankondiging testen die een test via zowel spraak als braille stuurt.

## Instellingen: Vertalen {#settings-translate}

Schakelt automatische vertaling van artikelinhoud in en kiest de dienst die dit doet.

- "Automatische vertaling voor artikelinhoud inschakelen".
- De provider: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini of Qwen.
- De doeltaal, uit de lijst gekozen of als code getypt zoals en, es, fr of pt-BR.
- Een API-sleutel voor de gekozen provider en eventueel een specifiek model. Voor OpenRouter haalt "OpenRouter-modellen laden" de beschikbare modellenlijst op.

Grok en Groq zijn verschillende diensten met verwarrend gelijkende namen: Grok is van xAI, met sleutels van console.x.ai die met "xai-" beginnen; Groq host LLaMA en Mistral, met gratis sleutels van console.groq.com die met "gsk_" beginnen.

Dit vertaalt artikeltekst. Zie Interfacetaal om de taal van BlindRSS' eigen interface te wijzigen.

## Instellingen: Lijstkoppen {#settings-list-headers}

Stelt de globale kolomindeling voor de artikellijst in: welke kolommen verschijnen, in welke volgorde en hoe breed. Zie Kolommen van de artikellijst.

Een individuele feed kan dit vanuit haar eigen Feed-eigenschappen overschrijven.

## Instellingen: Geavanceerd {#settings-advanced}

- Locatie voor gegevensopslag: bewaar database en instellingen in de gebruikersgegevensmap of toepassingsmap; beide paden worden getoond. De optie toepassingsmap maakt een draagbare installatie draagbaar.
- Updates: "Updates automatisch installeren zonder bevestiging".
- Browseridentificatie: als welke browser BlindRSS zich identificeert bij het ophalen van feeds, of een aangepaste User-Agent-tekenreeks die u typt. De werkelijke tekenreeks wordt eronder getoond. Dit is van belang voor sites die onbekende clients blokkeren.
- Video zoeken: "Volwassenensites inschakelen in Video zoeken", standaard uit.

## Instellingen: CAPTCHA oplossen {#settings-captcha}

Een optionele, betaalde laatste uitweg voor sites die met een CAPTCHA antwoorden waar geïmporteerde cookies niet door raken.

"CAPTCHA-oplossingsdienst inschakelen" zet dit aan; het API-sleutelveld bevat uw accountsleutel bij de oplossingsdienst. Kosten per oplossing zijn van toepassing; daarom staat dit standaard uit en wordt het pas geprobeerd nadat al het andere faalde.

Probeer eerst Sitecookies importeren; dat is gratis en lost de meeste gevallen op.

## Onlineaccounts en providers {#providers}

BlindRSS kan uw abonnementen zelf bewaren of ze uit een onlineaccount lezen. Instellingen, Provider kiest welke.

- Lokaal: abonnementen leven in BlindRSS' eigen database op deze machine. Niets wordt ergens gesynchroniseerd.
- Miniflux: vereist het adres van uw Miniflux-server en een API-sleutel uit de instellingen van uw Miniflux-account.
- Inoreader: vereist een app-ID en appsleutel van de ontwikkelaarspagina van Inoreader en daarna de knop Autoriseren om aan te melden.
- The Old Reader: vereist het e-mailadres en wachtwoord van uw account.
- BazQux: vereist het e-mailadres en wachtwoord van uw account.

Bij een onlineprovider zijn leesstatus, abonnementen en categorieën die van het account; ze volgen u dus naar elk ander apparaat dat op hetzelfde account is aangemeld. Sommige providers bewaren categorieën in één vlakke lijst; BlindRSS zegt dat dan in plaats van nesting aan te bieden die niet zou blijven.

## Meldingen {#notifications}

BlindRSS geeft een systeemmelding wanneer nieuwe artikelen binnenkomen, onderhevig aan Instellingen, Meldingen.

- Meldingen kunnen volledig worden uitgeschakeld.
- De feednaam kan in de tekst worden opgenomen.
- Een limiet beperkt hoeveel er per verversing komen, met een optionele samenvattingsmelding zodra die limiet wordt bereikt.
- Individuele feeds kunnen worden uitgesloten, via Feeds uitsluiten in Instellingen of via "Meldingen voor deze feed" in het contextmenu van de feed.
- Een Filterregel kan de melding onderdrukken voor artikelen waarmee zij overeenkomt.

Afzonderlijk daarvan spreken Aankondigingen gekozen gebeurtenissen rechtstreeks uit via de eigen interface van NVDA of JAWS en via braille, wat doorkomt zelfs wanneer een systeemmelding dat niet doet.

## Artikelvertaling {#translation}

Met vertaling ingeschakeld in Instellingen, Vertalen wordt artikeltekst tijdens het lezen naar uw doeltaal vertaald, met de AI-dienst die u instelde.

Vertaling gebeurt op aanvraag en wordt in cache bewaard; een artikel opnieuw lezen kost dus niet tweemaal. Het vereist een internetverbinding en uw eigen API-sleutel bij de gekozen dienst.

De toepassingsinterface wordt afzonderlijk vertaald, via eigen catalogi. Zie Interfacetaal.

## Sitecookies importeren {#site-cookies}

Sommige sites zetten een browserverificatiepagina — meestal een Cloudflare-uitdaging "checking your browser" — voor hun inhoud. Die sites antwoorden alleen aan een sessie die de uitdaging al in een echte browser doorliep; BlindRSS kan ze dus niet zelf ophalen.

Extra, Sitecookies importeren geeft BlindRSS die sessie:

1. Open de website in uw webbrowser en wacht tot die volledig is geladen.
2. Exporteer de cookies naar een cookies.txt-bestand met een browserextensie voor cookies.txt. Voor Chrome-gebaseerde browsers verwijst het dialoogvenster naar "Get cookies.txt LOCALLY".
3. Kies het geëxporteerde bestand in het dialoogvenster.
4. Plak de User-Agent-tekenreeks van uw browser in het onderstaande veld. Zoeken op het web naar "what is my user agent" toont die. Cloudflare vereist exact de User-Agent waarvoor de cookie werd uitgegeven; daarom is dit belangrijk.

Browsers uit de Firefox-familie hebben een weg met één klik: "Uit browser importeren" leest hun cookiedatabase rechtstreeks. Chromium-gebaseerde browsers versleutelen die; daarom hebben zij de extensie nodig.

## Sneltoetsen {#keyboard-shortcuts}

Extra, Sneltoetsen somt elke opdracht in BlindRSS op, gegroepeerd per categorie, met de huidige toets en laat u elke toets wijzigen.

- Selecteer een opdracht en kies Sneltoets wijzigen. Het opnamedialoogvenster registreert dan de volgende toetscombinatie die u indrukt.
- Sneltoets verwijderen laat een opdracht ongebonden; zij werkt nog steeds vanuit haar menu.
- Alles terugzetten naar standaarden herstelt de geleverde toetsen.

Sneltoetsen worden vóór menuversnellers verzonden en werken vensterbreed, ook wanneer het spelervenster focus heeft; het toetsenbordpad kondigt zichzelf aan waar het menupad stil blijft. Uw wijzigingen worden met uw instellingen opgeslagen en overleven updates.

## Standaardsneltoetsen {#shortcuts-reference}

Feeds:

- Ctrl+N: Feed toevoegen.
- F5: Feeds verversen. Shift+F5: Verversen stoppen. Ctrl+F5: De geselecteerde feed verversen.
- F2: Feed of categorie bewerken.
- Ctrl+Shift+R: Alle items als gelezen markeren.
- Ctrl+Shift+F: Een podcast of RSS-feed zoeken.

Artikelen en weergaven:

- Ctrl+D: toevoegen aan of verwijderen uit Favorieten.
- Backspace: gelezen en ongelezen schakelen. Delete: verwijderen. Shift+Delete: verwijderen zonder bevestiging.
- Ctrl+E: focus op het zoekveld.
- Ctrl+Shift+H: rijke volledige-tekstweergave.
- Ctrl+1 tot Ctrl+3: alle, ongelezen, gelezen. Ctrl+4 tot Ctrl+6: media en niet-media, met media, zonder media.

Speler:

- Ctrl+P: afspelen of pauzeren. Ctrl+S: stoppen. Ctrl+Shift+P: speler tonen of verbergen.
- Ctrl+Left en Ctrl+Right: zoeken. Ctrl+Up en Ctrl+Down: volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: versnellen, vertragen, normaal.
- Ctrl+Shift+E: equalizer.
- Ctrl+Shift+C: afspeelwachtrij. Ctrl+Shift+T en Ctrl+Shift+V: volgende en vorige.

Toepassing:

- F1: deze handleiding, geopend bij het onderdeel voor wat u gebruikt.
- Ctrl+comma: Instellingen.
- Ctrl+Shift+A: de actieve versie aankondigen.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: knippen, kopiëren, plakken, alles selecteren.

Opdrachten die hier niet staan worden ongebonden geleverd en kunnen in Extra, Sneltoetsen elke toets krijgen.

## Interfacetaal {#language}

BlindRSS' interface is in vijftien talen vertaald. Instellingen, Algemeen kiest er een of laat de systeemtaal volgen. De wijziging wordt actief wanneer u opnieuw start.

Vertalingen worden zowel tussen als met toepassingsuitgaven geleverd; een gecorrigeerde vertaling bereikt u dus zonder op een nieuwe versie te wachten.

Deze handleiding volgt dezelfde taal wanneer er een vertaalde handleiding voor bestaat en valt anders terug op Engels.

## Systeemvakpictogram en mediatoetsen {#tray}

BlindRSS kan in het systeemvak leven. Instellingen, Algemeen bepaalt of het venster bij sluiten naar het systeemvak gaat, of minimaliseren dat doet en of het daar start.

Het systeemvakpictogram heeft afspeelbediening en opent het hoofdvenster opnieuw. De mediatoetsen van uw toetsenbord — afspelen/pauzeren, stoppen, volgende, vorige — bedienen de BlindRSS-speler systeemwijd.

## Bureaubladsnelkoppelingen toevoegen {#desktop-shortcuts}

Bestand, Snelkoppelingen toevoegen maakt snelkoppelingen naar BlindRSS op het bureaublad, in het Startmenu en op de taakbalk. Vink aan wat u wilt en kies OK; het resultaat van elk wordt terug gemeld.

Een item in het Startmenu is ook wat Windows vereist voordat een toepassing meldingen mag geven; het is dus nuttig, zelfs als u BlindRSS op een andere manier start.

## Op updates controleren {#updates}

Help, Op updates controleren vraagt of er een nieuwere versie beschikbaar is en biedt aan die te installeren.

Elke update wordt geverifieerd vóór ze wordt toegepast: haar SHA-256 moet overeenkomen met het gepubliceerde manifest en in Windows moet haar Authenticode-handtekening geldig zijn. Een update die een van beide controles niet doorstaat wordt niet geïnstalleerd.

"Bij opstarten op updates controleren" in Instellingen, Algemeen doet dit automatisch; "Updates automatisch installeren zonder bevestiging" in Instellingen, Geavanceerd past ze toe zonder te vragen. Uw instellingen, database en downloads blijven door een update onaangeroerd.

## De versie aankondigen {#version}

Help, Versie aankondigen (Ctrl+Shift+A) spreekt de actieve BlindRSS-versie rechtstreeks uit naar uw schermlezer.

De eigen opdracht van een schermlezer om de toepassingsversie te melden leest de versiebron van het uitvoerbare bestand. Dat werkt voor een geïnstalleerde build, maar meldt de Python-versie wanneer BlindRSS vanuit bron wordt uitgevoerd. Deze opdracht geeft in beide gevallen het juiste antwoord.

## Over BlindRSS {#about}

Help, Over toont de versie, de licentie en koppelingen: het GitHub-profiel, de opslagplaats en de changelog.

BlindRSS valt onder de MIT-licentie — u mag het gebruiken, wijzigen, herverdelen of verpakken voor de opslagplaatsen van een distributie, zonder toestemming.

## Dit helpvenster gebruiken {#help-window}

Dit venster is een eenvoudige, volledig via toetsenbord toegankelijke lezer voor de handleiding.

- De inhoudslijst bevat elk onderdeel. Loop er met de pijlen door; een onderdeel selecteren springt met de tekst ernaartoe en kondigt de titel aan.
- Het tekstgebied is alleen-lezen en selecteerbaar, zodat een schermlezer het regel per regel kan lezen en u eruit kunt kopiëren.
- Ctrl+F gaat naar het zoekvak. Typ een woord en druk op Enter om naar de volgende keer dat het voorkomt te springen.
- F3 zoekt de volgende keer dat het voorkomt, Shift+F3 de vorige. Zoeken loopt rond.
- Tab en Shift+Tab gaan tussen zoekvak, inhoudslijst en tekst.
- Escape sluit het venster.

F1 overal in BlindRSS opent dit venster bij het onderdeel voor wat u gebruikt — het besturingselement met focus, het actieve dialoogvenster, het gemarkeerde menu-item of de speler. Bestaat er geen onderdeel voor, dan opent de handleiding bij het begin.

De handleiding wordt getoond in BlindRSS' interfacetaal wanneer er een vertaling bestaat, en anders in het Engels.

## Problemen oplossen {#troubleshooting}

Een feed stopt met bijwerken. Kijk bij Feeds met fouten naar de reden. Het adres van een verhuisde feed moet in Feed-eigenschappen worden gecorrigeerd; een site die een browsercontrole eist heeft Sitecookies importeren nodig.

Een YouTube-video speelt niet af. Importeer YouTube-cookies bij Instellingen, YouTube en schakel "YouTube eerst downloaden om af te spelen" in. De fout "aanmelden om te bevestigen dat u geen bot bent" betekent altijd cookies.

Afspelen stottert. Verhoog de netwerkcache in Instellingen, Mediaspeler en zet Stilte overslaan uit; die functie is experimenteel en kost CPU.

Een site geeft helemaal niets terug. Wijzig de browseridentificatie bij Instellingen, Geavanceerd; sommige sites weigeren onbekende clients rechtstreeks.

Er wordt niets uitgesproken wanneer een opdracht loopt. Controleer Aankondigingen bij Instellingen, Meldingen — elke gebeurtenis kan afzonderlijk aan of uit, en er is een testknop.

Iets gedraagt zich vreemd en u wilt het melden. Schakel debugmodus in bij Instellingen, Algemeen, reproduceer het probleem en voeg de blindrss.log toe die naast uw instellingen en gegevens wordt geschreven.

## Ondersteuning en gemeenschap {#support}

Fouten en functieverzoeken horen thuis in de GitHub-issue-tracker op github.com/serrebidev/BlindRSS/issues.

Voor vragen, hulp en uitgavenieuws is de SerrebiProjects-groep op Telegram via t.me/SerrebiProjects de snelste plaats om antwoord te krijgen.

Vertalingen zijn altijd welkom. Spreekt u een van de ondersteunde talen en leest iets verkeerd, dan wordt een pull request die het corrigeert bijna zeker aanvaard — zie locale/README.md in de opslagplaats voor de indeling van de bestanden. Hetzelfde geldt voor deze handleiding: een vertaalde kopie hoort in docs/help/<language>.md, met de {#anchor}-markeringen exact zoals in het Engelse bestand zodat contextgevoelige hulp blijft werken.
