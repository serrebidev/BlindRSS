# BlindRSS användarguide

## BlindRSS användarguide {#user-guide}

BlindRSS är en skrivbordsapp för RSS och poddar, utformad för skärmläsare. Den läser RSS- och Atom-flöden, spelar podd- och videobilagor och fungerar både självständigt och med ett värdkonto som Miniflux, Inoreader, The Old Reader eller BazQux.

Guiden finns lagrad i programmet och fungerar därför utan internetanslutning och webbläsare. Tryck F1 var som helst i BlindRSS för att öppna den. Om kontrollen, dialogrutan, menyalternativet eller fönstret du använder har ett eget avsnitt, öppnar F1 guiden där i stället för i början.

Allt här kan nås med tangentbordet. Använd innehållslistan för att flytta mellan avsnitt eller sökrutan för att hitta ett ord var som helst i guiden.

## Komma igång {#getting-started}

När BlindRSS startar för första gången finns inga flöden. Du kan lägga till några på flera sätt:

- Tryck Ctrl+N för att lägga till ett flöde med adress. Se Lägga till ett flöde.
- Tryck Ctrl+Shift+F för att söka efter poddar och flöden efter namn. Se Hitta poddar och RSS-flöden.
- Importera en OPML-fil som exporterats från en annan läsare. Se Importera OPML.
- Importera ett YouTube Takeout-arkiv för att prenumerera på alla kanaler du redan följer. Se Importera ett YouTube Takeout-arkiv.
- Logga in på ett värdkonto via Verktyg, Inställningar, Leverantör, så läser BlindRSS prenumerationerna som redan finns i kontot. Se Onlinekonton och leverantörer.

När du har flöden trycker du F5 för att uppdatera dem. Nya artiklar visas i artikellistan och antalet olästa visas intill varje flöde i trädet.

Tre ställen är särskilt värda att besöka tidigt: Verktyg, Inställningar (hur BlindRSS fungerar), Verktyg, Tangentbordsgenvägar (alla kommandon och deras tangenter) och denna guide.

## Huvudfönstret {#main-window}

Huvudfönstret har fyra huvudområden samt en menyrad och en statusrad. Tab och Shift+Tab flyttar mellan dem, och F6 växlar panel i de flesta fönsterhanterare.

- Trädet med flöden och mappar till vänster.
- Sökfältet ovanför artikellistan.
- Artikellistan.
- Läsrutan under artikellistan.

Menyraden innehåller Arkiv, Redigera, Visa, Spelare, Verktyg och Hjälp. Tryck Alt för att nå den och använd sedan piltangenterna. Varje menyalternativ har en åtkomsttangent på varje gränssnittsspråk, och menyraden går runt i båda ändarna.

Storlekar, valt flöde och fönstrets tillstånd sparas mellan körningar. ”Kom ihåg senast valda flöde/mapp vid start” i Inställningar, Allmänt styr om BlindRSS öppnar det flöde du senast läste.

## Lista över flöden och mappar {#feed-tree}

Trädet till vänster visar dina flöden, kategorierna som grupperar dem, Smarta mappar, sparade sökningar och de inbyggda vyerna (Alla flöden, Favoriter, Borttagna artiklar och Flöden med fel).

- Up and Down arrows flyttar mellan objekt.
- Right Arrow expanderar en kategori, Left Arrow fäller ihop den.
- Enter eller val av ett objekt laddar dess artiklar i artikellistan.
- F2 öppnar egenskaper för valt flöde eller kategori.
- Applications key eller Shift+F10 öppnar snabbmenyn.

Varje flöde visar sitt antal olästa. Expanderade och ihopfällda kategorier sparas, så trädet ser likadant ut nästa gång du startar.

Flöden som inte kunde uppdateras visas fortfarande normalt; vyn Flöden med fel samlar dem så att ett flöde som i tysthet slutat fungera inte förbises.

## Artikellista {#article-list}

Artikellistan visar artiklarna för det som är valt i trädet, efter att aktuellt artikelfilter, sorteringsordning och sökterm har tillämpats.

- Up and Down arrows flyttar mellan artiklar; läsrutan följer med.
- Enter öppnar vald artikel.
- Shift+Up och Shift+Down utökar markeringen så att gruppåtgärder fungerar på flera artiklar samtidigt.
- Backsteg växlar läst och oläst för vald artikel.
- Delete tar bort valda artiklar; Shift+Delete tar bort dem utan bekräftelsefrågan.
- Ctrl+D lägger till eller tar bort en favorit.
- Applications key eller Shift+F10 öppnar snabbmenyn.

Vilka kolumner som visas och i vilken ordning kan ställas in globalt och per flöde. Se Kolumner i artikellistan.

## Läsruta {#reading-pane}

Läsrutan under artikellistan innehåller texten i den valda artikeln. Den är ett skrivskyddat textområde, så en skärmläsare kan läsa rad för rad, ord för ord eller tecken för tecken, och texten kan markeras och kopieras.

- Ctrl+F söker i artikeltexten.
- F3 och Shift+F3 flyttar till nästa respektive föregående träff.
- Enter på en länk i texten öppnar länken.

Hur text visas kan ställas in i Inställningar, Flöden och artiklar: rubriker kan meddelas, listobjekt märkas med punkter och nummer, citat märkas, länkar visas med sin adress, tabeller beskrivas och alternativtext för bilder inkluderas. Alternativtext för bilder kan också tvingas på eller av för ett enskilt flöde från flödets snabbmeny.

Om ett flöde bara publicerar en kort sammanfattning kan BlindRSS hämta hela artikeltexten. Se Hämtning av hela artikeltexten.

## Artikelfönster {#article-window}

Att öppna en artikel kan placera den i ett eget fönster i stället för i läsrutan. Då får artikeln hela skärmen och förblir öppen medan du går vidare i listan.

Fönstret är ett skrivskyddat textområde med samma funktioner för läsning, markering och textsökning som läsrutan. Escape stänger det.

## Sökfält {#search-field}

Sökfältet ovanför artikellistan filtrerar den aktuella vyn medan du skriver och bekräftar med Enter.

- Ctrl+E flyttar fokus till sökfältet.
- Enter tillämpar termen.
- Escape eller knappen rensa tömmer fältet och återställer hela listan.

Sökfältet kan döljas om du aldrig använder det; menyn Visa har kommandot Visa/dölj sökfält. Om sökningen matchar bara rubriker eller både rubriker och artikeltext ställs in under ”Sökning matchar” i Inställningar, Flöden och artiklar.

En sökning du vill behålla kan göras till en sparad sökning som ligger kvar i trädet. Se Beständiga sökningar.

## Statusrad {#status-bar}

Statusraden längst ned i huvudfönstret har tre fält:

- Tillfälliga meddelanden, såsom hur många artiklar ett filter matchade.
- Bakgrundsaktivitet, såsom flödesuppdatering eller pågående hämtning.
- Uppspelningsstatus: vad som spelas och förfluten respektive återstående tid.

De är avsiktligt separata så att ett uppdateringsmeddelande inte kan skriva över ett sökresultatantal medan du läser det.

## Snabbmenyer {#context-menus}

Flödesträdet och artikellistan har var sin snabbmeny, öppnad med Applications key eller Shift+F10. De innehåller kommandon som gäller det valda — uppdatera, markera som läst, redigera, ta bort, kopiera länkar, köa media och så vidare.

Snabbmenyer stöder också F1: när ett objekt är markerat öppnar F1 avsnittet i guiden som förklarar det.

## Lägga till ett flöde {#adding-feeds}

Arkiv, Lägg till flöde (Ctrl+N) prenumererar på ett flöde med adress.

Klistra in eller skriv flödets eller webbplatsens adress — BlindRSS letar efter ett flöde på sidan när adressen inte är ett flöde. Du kan också klistra in en adress till en YouTube-kanal eller spellista, en Mastodon- eller Bluesky-profil, en PieFed- eller Lemmy-gemenskap, en SoundCloud- eller Mixcloud-sida eller en Reddit- eller Groups.io-adress, och BlindRSS gör om den till ett flöde.

Välj den kategori flödet ska hamna i eller lämna det okategoriserat. Alternativet ”Öppna i HTML-vy” gör att artiklar från detta flöde öppnas i den rika vyn som standard.

Om du inte känner till adressen använder du Hitta poddar och RSS-flöden i stället.

## Upptäcka flöden på en sida {#detect-feeds}

Arkiv, Upptäck flöden på sidan tar adressen till en vanlig webbsida och listar de flöden sidan annonserar, så att du kan prenumerera utan att själv leta efter flödeslänken.

Detta är rätt kommando när en webbplats har en ”prenumerera”- eller ”RSS”-länk som du inte lätt kan nå, eller när sidan erbjuder flera flöden (alla inlägg, en kategori, kommentarer) och du vill välja.

## Hitta poddar och RSS-flöden {#find-podcast}

Verktyg, Hitta en podd eller RSS-flöde (Ctrl+Shift+F) söker i podd- och flödeskataloger efter namn, ämne eller webbplatsadress, så att du kan prenumerera utan att känna till någon flödesadress.

1. Skriv det du letar efter i sökrutan — ett poddnamn, ett ämne eller en webbplatsadress.
2. Välj en källa eller lämna den på ”Alla källor”.
3. Tryck Enter eller knappen Sök.
4. Bläddra med piltangenterna i resultatlistan. Varje rad visar titeln, vilken katalog den kommer från och detaljer.
5. Tryck Enter på ett resultat eller välj OK för att prenumerera på det.

Sökningar görs i flera kataloger samtidigt och resultat kommer när var och en svarar, så listan växer medan du läser. Escape stänger dialogrutan och stoppar sökningen.

## Podd- och flödeskataloger {#podcast-directories}

Rutan Källa i Hitta en podd eller RSS-flöde väljer var sökningen sker. Utöver ”Alla källor”, ”Alla poddkällor” och ”Alla RSS-flödeskällor” finns dessa kataloger var för sig:

- Poddkataloger: iTunes (Apple Podcasts), gPodder, fyyd, Podverse, SoundCloud och Mixcloud.
- Flödeskataloger: NewsBlur, Feedspot, Google News, Bing News och Feedly.
- Webbplats- och gemenskapssökning: YouTube, Reddit, Groups.io och Fediverse — Mastodon, Bluesky, PieFed och Lemmy eller Kbin, som alla också kan väljas var för sig.
- Adressbaserad upptäckt: Feedsearch och BlindRSS egen webbplatsskanning, som hämtar en webbplats och letar efter flöden i den.

Ingen enskild katalog används som enda källa. Sökning i ”Alla källor” frågar podd- och RSS-grupperna tillsammans och sammanfogar resultaten, med breda Google News-frågeflöden under direkta flödesträffar.

## Prenumerera på ett sökresultat {#subscribing}

I alla sökdialoger — Hitta en podd eller RSS-flöde, Videosökning eller Podcast Archives sökknapp — prenumererar du på resultatet genom att trycka Enter eller välja OK när det är markerat.

BlindRSS löser först resultatet till en riktig flödesadress, så en podd från en katalog, en YouTube-kanal eller ett Fediverse-konto prenumereras på på samma sätt. Det nya flödet visas i trädet och uppdateras direkt.

Om du vill ha det i en viss kategori flyttar du det efteråt från snabbmenyn eller från Flödesegenskaper.

## Podcast Archive {#podcast-archive}

Verktyg, Podcast Archive bläddrar i en podds fullständiga avsnittshistorik — både avsnitten som fortfarande finns i dess flöde och äldre som BlindRSS återställde — och hämtar dem i omgångar.

Många poddflöden publicerar bara de senaste avsnitten. Arkivåterställning körs automatiskt i bakgrunden; i det här fönstret ser du status, försöker igen manuellt och hämtar det som hittades.

- Välj podden i rutan Podd.
- Filtrera avsnitt begränsar listan medan du skriver.
- Skanna om arkiv kör återställningen igen för den podden.
- Hitta eller lägg till podd öppnar flödessökningen så att du kan arkivera en podd som du ännu inte prenumererar på.
- Spela spelar valt avsnitt, Hämta valda hämtar det och Hämta alla hämtar hela den synliga listan.
- Avbryt hämtningar stoppar en pågående omgång.

Fönstret förblir öppet medan en omgång hämtas, så du kan fortsätta läsa.

## Videosökning {#video-search}

Verktyg, Videosökning söker i alla webbplatser som yt-dlp kan söka i på en gång och låter dig spela upp, köa eller prenumerera på det som hittas.

- Skriv en sökterm och tryck Enter eller knappen Sök.
- Rutan omfattning begränsar sökningen till en webbplats; standardläget söker i alla.
- Resultat kommer när varje webbplats svarar, med vanliga webbplatser först. Titlar som först kommer som platshållare fylls i när de löses.
- Läs in fler resultat hämtar ytterligare en omgång från varje webbplats.
- Sortering efter kolumnrubrik ordnar om det som har kommit.

Identiska videor som hittas på flera webbplatser slås ihop till en rad. Vuxenwebbplatser utesluts om inte ”Aktivera vuxenwebbplatser i Videosökning” är påslaget i Inställningar, Avancerat.

## Öppna en artikel med URL {#open-article-url}

Arkiv, Öppna artikel tar adressen till vilken webbsida som helst och läser den i BlindRSS som om den vore en artikel — extraherad text i läsrutan med samma läsalternativ som allt annat.

Använd det för en enstaka sida som du har fått skickad till dig utan att prenumerera på något. Om sidan är en forum- eller diskussionstråd läser BlindRSS hela tråden. Se Forum- och diskussionstrådar.

## Öppna en medie-URL {#open-media-url}

Arkiv, Öppna medie-URL spelar ljud eller video från en adress i den inbyggda spelaren utan att prenumerera på något.

Det accepterar direkta medielänkar och sidadresser som yt-dlp kan lösa — YouTube, Rumble, Odysee, SoundCloud och många fler. Resultatet spelas som vilket annat objekt som helst och kan läggas till i spelkön.

## Ta bort ett flöde {#removing-feeds}

Arkiv, Ta bort flöde avslutar prenumerationen på valt flöde. Samma kommando finns på flödets snabbmeny.

Att ta bort ett flöde tar bort dess artiklar ur databasen. Det rör inte något du redan har hämtat till disk. Om du använder en värdleverantör skickas avslutandet av prenumerationen även till det kontot.

För att ta bort en hel kategori och allt i den använder du Ta bort kategori och flöden på kategorins snabbmeny. Se Kategorier och underkategorier.

## Flödesegenskaper {#feed-properties}

F2, eller Redigera flöde på snabbmenyn, öppnar egenskaperna för valt flöde.

- Dess titel, som du kan åsidosätta; ”Återställ titel till flödets standard” på snabbmenyn återställer flödets egen titel.
- Dess adress och kategorin det tillhör.
- Om nya artiklar från det ger en avisering.
- Om det öppnas i den rika HTML-vyn.
- Dess egen kolumnlayout för artikellistan på fliken Listrubriker, som åsidosätter den globala.

Visa flödesbeskrivning på artikellistans snabbmeny visar beskrivningen som flödet självt publicerar.

## Kategorier och underkategorier {#categories}

Kategorier grupperar flöden i trädet och kan vara nästlade: en kategori kan innehålla både flöden och fler underkategorier.

- Arkiv, Lägg till kategori skapar en.
- Lägg till underkategori på en kategoris snabbmeny skapar en i den.
- Redigera kategori byter namn på eller flyttar den. Se Kategoriegenskaper.
- Ta bort kategori tar bort kategorin men behåller dess flöden.
- Ta bort kategori och flöden tar bort kategorin och avslutar prenumerationen på allt i den.
- Importera OPML här importerar en fil direkt till den kategorin.
- Exportera kategori till OPML exporterar bara den grenen.

Vissa värdleverantörer håller kategorier i en enda platt lista. När så är fallet säger BlindRSS det och alternativen ”flytta till överordnad” är inte tillgängliga.

## Kategoriegenskaper {#category-properties}

Redigera kategori öppnar kategorins egenskaper: dess namn och den överordnade kategori den ligger under.

Att byta namn på en kategori behåller alla dess flöden. Att flytta den flyttar hela grenen, inklusive underkategorier.

## Uppdatera flöden {#refreshing}

- F5 uppdaterar alla flöden.
- Ctrl+F5 uppdaterar bara valt flöde eller kategori.
- Shift+F5 stoppar en pågående uppdatering.
- Uppdatera kategori på en kategoris snabbmeny uppdaterar den grenen.

Endast ett av Uppdatera flöden och Stoppa uppdatering är tillgängligt åt gången, så tangentbordskommandot motsvarar vad menyn erbjuder. Förlopp visas i statusradens andra fält.

Automatisk uppdatering ställs in i Inställningar, Flöden och artiklar: intervallet, hur många flöden som uppdateras samtidigt, hur många anslutningar per värd, tidsgränsen per flöde och hur många gånger ett misslyckat flöde försöks igen. ”Uppdatera flöden automatiskt vid start” uppdaterar allt vid start och alternativet för startarbetsbelastning väljer mellan att använda cachen och att tvinga fram en fullständig uppdatering.

## Flöden med fel {#feed-errors}

Vyn Flöden med fel och Arkiv, Visa flödesfel listar flöden vars senaste uppdatering misslyckades tillsammans med orsaken.

Ett flöde som i tysthet slutat fungera ser precis ut som ett flöde utan nya artiklar, vilket är skälet till denna vy. Därifrån kan du:

- Uppdatera valda för att försöka igen nu.
- Kopiera detaljer för att placera feltexten på Urklipp.
- Flödesegenskaper för att rätta adressen.
- Ta bort flöde när flödet är borta för gott.

Vanliga orsaker är ett flyttat eller avvecklat flöde, en webbplats som nu kräver webbläsarkontroll (se Importera webbplatskakor) och ett tillfälligt serveravbrott.

## Importera OPML {#import-opml}

OPML är standardfilformatet för en lista över flödesprenumerationer. Alla flödesläsare kan exportera en, så OPML är sättet att flytta prenumerationerna från en annan läsare till BlindRSS utan att lägga till dem en i taget.

Arkiv, Importera OPML frågar efter filen och lägger till varje flöde i den, med den kategoristruktur filen beskriver. Flöden du redan prenumererar på dupliceras inte.

Importera OPML här på en kategoris snabbmeny placerar hela importen i den kategorin i stället för på toppnivån.

För att få ut en OPML-fil från en annan läsare letar du efter ”Exportera”, ”Säkerhetskopia” eller ”Prenumerationer” i dess inställningar.

## Exportera OPML {#export-opml}

Arkiv, Exportera OPML skriver alla dina prenumerationer med deras kategorier till en OPML-fil.

Använd den för att säkerhetskopiera dina prenumerationer, flytta dem till en annan läsare eller dator eller dela en uppsättning flöden med någon annan. Exportera kategori till OPML på en kategoris snabbmeny exporterar bara den grenen.

## Importera ett YouTube Takeout-arkiv {#import-youtube-takeout}

Google Takeout är Googles tjänst för dataexport. Ett YouTube Takeout-arkiv är en ZIP-fil som innehåller dina YouTube-data, inklusive listan över kanaler du prenumererar på. Arkiv, Importera YouTube Takeout läser ZIP-filen och prenumererar på dessa kanaler som flöden, så att varje kanals nya videor kommer som artiklar.

Så här hämtar du arkivet:

1. Gå till takeout.google.com och logga in med det Google-konto där dina YouTube-prenumerationer finns.
2. Välj ”Avmarkera alla” och välj sedan bara YouTube och YouTube Music.
3. I ”All YouTube-data ingår” behåller du åtminstone ”prenumerationer”; ”historik” och ”spellistor” är valfria och BlindRSS kan använda dem också.
4. Exportera en gång som ZIP-fil och vänta på Googles e-post — ett stort arkiv kan ta timmar.
5. Hämta ZIP-filen och peka detta kommando på den.

BlindRSS visar sedan vad som hittades grupperat efter källa och låter dig välja vilka grupper som ska importeras:

- Prenumerationer: kanalerna du följer.
- Historik: kanaler du har tittat på men inte följer.
- Dina egna kanaler.
- Spellistor som egna flöden.

Duplicerade adresser tas bort, så att importera ett andra arkiv senare lägger bara till det som är nytt. ZIP-filen packas aldrig upp till disk; bara de små datafilerna i den läses.

## Beständiga sökningar {#persistent-search}

En beständig sökning är en sökterm som ligger kvar i trädet som eget objekt, så att artiklarna den matchar alltid är en piltryckning bort.

Verktyg, Konfigurera beständig sökning hanterar listan: Lägg till skapar en från en term, Ta bort raderar den. Varje sparad sökning visas i trädet och utvärderas på nytt varje gång du väljer den, så den avspeglar alltid de aktuella artiklarna.

Använd den för ett ämne du följer i alla flöden — en persons namn, en produkt eller en plats. Använd Smarta mappar för något mer strukturerat än en fras.

## Smarta mappar {#smart-folders}

En smart mapp är en mapp i trädet vars innehåll definieras av en regel i stället för av vilket flöde en artikel kom från.

Ny smart mapp på trädets snabbmeny öppnar regelredigeraren. En regel är en uppsättning villkor som förenas med ”matcha alla” (och) eller ”matcha något” (eller), och grupper av villkor kan nästlas, så ”(A och B) eller C” kan uttryckas.

Villkor testar dessa fält:

- Ja/nej-fält: läst, favorit, öppnad, uppdaterad.
- Textfält: titel, innehåll, beskrivning, författare, flöde, url och tagg — kategorier eller taggar som webbplatsen själv publicerar.

Textvillkor använder innehåller, innehåller inte, är lika med eller börjar med.

Smarta mappar flyttar eller kopierar aldrig något; de är en vy över artiklarna du redan har. Använd Filterregler för att ändra artiklar när de anländer.

## Filterregler {#filter-rules}

Verktyg, Filterregler är BlindRSS motor för artikelsortering. Regler körs på inkommande artiklar på samma sätt som e-postfilter körs på inkommande e-post.

Varje regel kopplar ett villkor — samma regelredigerare som Smarta mappar använder — till en uppsättning åtgärder:

- Flytta artikeln till en kategori.
- Märk den också med en kategori och låt den ligga kvar där den är.
- Markera den som läst.
- Markera den som favorit.
- Ta bort den enligt ditt inställda borttagningsbeteende.
- Hoppa över aviseringen om ny artikel.

Regler körs i listordning och varje aktiverad regel som matchar bidrar med sina åtgärder. En regel markerad för att stoppa avslutar kedjan för den artikeln när den har matchat, så senare regler aldrig ser den. Flytta regler uppåt och nedåt för att styra vilken som vinner.

En regel utan åtgärder gör ingenting och avvisas, så att en halvfärdig regel inte i tysthet kan svälja artiklar.

## Artikelfilter {#article-filter}

Visa, Artikelfilter begränsar varje vy efter lässtatus och efter om en artikel har bifogade medier. De två grupperna kombineras.

- Ctrl+1: alla artiklar.
- Ctrl+2: endast olästa.
- Ctrl+3: endast lästa.
- Ctrl+4: media och icke-media.
- Ctrl+5: endast med media.
- Ctrl+6: utan media endast.

Filtret gäller det som är valt i trädet, inklusive Smarta mappar och sparade sökningar, och sparas mellan körningar. ”Endast med media” är det snabbaste sättet att göra ett blandat flöde till en poddlista.

## Sortera artiklar {#sorting}

Visa, Sortera efter ordnar artikellistan efter datum, namn, författare, beskrivning, flöde eller status. Stigande växlar riktning; standard är nyaste först.

Sorteringen gäller alla vyer och sparas mellan körningar. Sortering efter flöde är användbar i Alla flöden och Smarta mappar, där artiklar kommer från många källor samtidigt.

## Kolumner i artikellistan {#list-headers}

Kolumnerna i artikellistan, deras ordning och bredder väljer du själv. Inställningar, Listrubriker ställer in den globala layouten; ett flödes egen flik Listrubriker åsidosätter den för flödet och ”Använd global kolumnlayout” stänger av åsidosättningen igen.

Färre kolumner innebär mindre för en skärmläsare att läsa på varje rad, så det är värt att ta bort kolumner du aldrig använder.

## Öppna artiklar {#opening-articles}

Enter på en artikel i listan öppnar den. Beroende på artikeln och dina inställningar innebär det läsrutan, ett eget fönster eller den rika HTML-vyn.

- Öppna artikel på snabbmenyn gör samma sak.
- Öppna i webbläsare lämnar artikelns adress till systemets webbläsare.
- Öppna tillgänglig webbläsare läser i stället sidan i BlindRSS. Se Tillgänglig webbläsare.

Att öppna en artikel markerar den som läst om du inte har ändrat det beteendet.

## Lästa och olästa artiklar {#read-status}

- Backsteg eller Växla läst/oläst växlar vald artikel.
- Ctrl+Shift+R markerar allt i den aktuella vyn som läst.
- Markera alla objekt som lästa på ett flödes eller en kategoris snabbmeny gör samma sak för den grenen.
- Markera som läst och Markera som oläst på artikellistans snabbmeny gäller hela markeringen och anger hur många artiklar de påverkar.

Antalet olästa visas intill varje flöde i trädet. Artikelfiltret kan dölja lästa artiklar helt.

## Favoriter {#favorites}

Ctrl+D lägger till vald artikel i Favoriter eller tar bort den om den redan finns där. Vyn Favoriter i trädet listar allt du har markerat.

Favoriter överlever kvarhållningsprincipen: en artikel du har stjärnmärkt tas inte bort när äldre artiklar rensas. Favorit kan också användas som villkor i Smarta mappar och Filterregler.

## Borttagna artiklar {#deleted-articles}

Vad Delete gör kan ställas in i Inställningar, Allmänt under ”När jag tar bort en artikel”:

- Flytta den till Borttagna artiklar, där den kan återställas.
- Ta bort den permanent.
- Flytta den till en kategori du anger.

Med den första inställningen listar vyn Borttagna artiklar i trädet det du har tagit bort, Återställ lägger tillbaka en artikel och borttagning inifrån den vyn tar bort den för gott.

”Bekräfta före borttagning av artiklar” styr bekräftelsefrågan. Shift+Delete hoppar alltid över den.

## Hämtning av hela artikeltexten {#full-text}

Många flöden publicerar bara en rubrik och en eller två meningar. BlindRSS kan hämta artikelsidan och extrahera den riktiga texten, så att läsrutan visar hela artikeln i stället för en puff.

Detta sker automatiskt i bakgrunden när du flyttar genom listan och resultatet cachas. ”Cacha hela texten i bakgrunden” i Inställningar, Flöden och artiklar förhämtar artiklarna runt din position så att nedflyttning i listan inte väntar på nätverket.

Om en webbplats helt vägrar läsas ligger den vanligtvis bakom en webbläsarkontroll. Se Importera webbplatskakor.

## Rik vy av hela artikeltexten {#rich-view}

Ctrl+Shift+H växlar läsrutan till den rika HTML-vyn, som återger artikeln som en webbläsare skulle göra, med rubriker, listor, tabeller och länkar som riktiga element som en skärmläsare kan navigera med sina egna strukturkommandon.

Oformaterad textvy är standard eftersom den är snabbare och aldrig överraskar dig. Den rika vyn är värd det för artiklar vars struktur bär betydelse.

Ett flöde kan ställas in att alltid öppnas i den rika vyn från sina Flödesegenskaper, och länkar i den rika vyn öppnas i systemets webbläsare i stället för i vyn.

## Tillgänglig webbläsare {#accessible-browser}

Visa, Öppna tillgänglig webbläsare öppnar en sida i BlindRSS i ett fönster gjort för läsning med skärmläsare, i stället för att lämna den till systemets webbläsare.

Det är rätt verktyg för en sida som behöver läsas snarare än användas interaktivt och för webbplatser vars egna gränssnitt är svåra att navigera. Den delar BlindRSS inställningar för kakor och webbläsaridentitet, så sidor bakom en webbläsarkontroll öppnas också här när du har importerat kakor för dem.

## YouTube-videor {#youtube}

En YouTube-kanal eller spellisteadress kan prenumereras på som vilket flöde som helst. Dess videor kommer då som artiklar med beskrivning, transkription och kapitelrad inbäddade, så att en video kan läsas i stället för att ses.

Uppspelning går genom yt-dlp. Inställningar, YouTube styr det:

- En kakfil som låter BlindRSS se åldersbegränsade videor och videor endast för medlemmar som du har åtkomst till. Den kan importeras direkt från en webbläsare eller hämtas automatiskt från cookies.txt-exporter i mappen Hämtade filer.
- ”Spela YouTube genom att hämta först”, som startar långsammare men är mycket mer tillförlitligt.
- Mappen för uppspelningscache och dess största storlek med en knapp för att rensa den.

Kakor gör åldersbegränsade videor och medlemsvideor spelbara, och det är vad felet ”logga in för att bekräfta att du inte är en robot” efterfrågar.

Importera YouTube Takeout prenumererar på varje kanal du redan följer i ett steg.

## Forum- och diskussionstrådar {#forums}

Reddit, Lemmy, Groups.io och Google Groups läses som hela trådar i stället för ett inlägg åt gången: att öppna en diskussion ger dig originalinlägget och svaren i en sammanhängande text, som går mycket snabbare att läsa än att följa en tråd i en webbläsare.

Prenumeration fungerar på samma sätt som för alla flöden — klistra in adressen till subredditen, gemenskapen eller gruppen. GitHub-arkiv stöds på samma sätt, liksom Mastodon-, Bluesky- och PieFed-konton och -gemenskaper.

## Klipp ut, kopiera och klistra in {#clipboard}

Menyn Redigera innehåller standardkommandona för Urklipp — Klipp ut (Ctrl+X), Kopiera (Ctrl+C), Klistra in (Ctrl+V) och Markera allt (Ctrl+A) — och de fungerar i varje textfält och i läsrutan.

BlindRSS lägger till kommandon som kopierar sådant den känner till:

- Kopiera länk, artikelns adress.
- Kopiera medielänk, adressen till dess ljud eller video.
- Kopiera text, artikelns text så som den läses i läsrutan.
- Kopiera flödes-URL, adressen till valt flöde.
- Kopiera bildlänk på en artikel med bild.

## Den inbyggda spelaren {#player}

BlindRSS spelar själv upp podd- och videobilagor genom VLC, så uppspelningen lämnar aldrig programmet. Ctrl+Shift+P visar eller döljer spelarfönstret och uppspelningen fortsätter oavsett.

Uppspelning jämnas ut av en lokal mellanserver med intervallcache, vilket gör sökning i ett långt avsnitt snabb även på långsam anslutning. Strömmar som behöver lösas — YouTube, Rumble, Odysee — går först genom yt-dlp.

”Visa spelarfönstret när uppspelning startar” i Inställningar, Mediaspelare avgör om fönstret visas av sig självt när något startar.

## Spelarkontroller {#player-controls}

Spelarfönstret innehåller i tabbordning: uppspelningsstatus, positionsreglage, förfluten och total tid, knappar för bakåt- och framspolning, hastighetsruta, kapitelknapp och volymreglage. Alla kan nås och användas med tangentbordet och meddelar sitt aktuella värde.

- Ctrl+P spelar upp och pausar.
- Ctrl+S stoppar.
- Ctrl+Left och Ctrl+Right spolar bakåt och framåt och upprepas medan de hålls nedtryckta. På macOS gör Option+Left och Option+Right samma sak eftersom Ctrl+Left och Ctrl+Right tillhör Mission Control där.
- Ctrl+Up och Ctrl+Down ändrar volymen.

Tangenterna för sökning och volym fungerar var som helst i BlindRSS medan något spelas, även inifrån en dialogruta, så du behöver aldrig hitta spelarfönstret för att pausa.

## Spelarens tangentbordsgenvägar {#player-shortcuts}

- Ctrl+Shift+P: visa eller dölj spelarfönstret.
- Ctrl+P: spela upp eller pausa.
- Ctrl+S: stoppa.
- Ctrl+Left och Ctrl+Right: spola bakåt och framåt (Option+Left och Option+Right på macOS).
- Ctrl+Up och Ctrl+Down: höj och sänk volymen.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: snabbare, långsammare, tillbaka till normal hastighet.
- Ctrl+Shift+E: equalizer.
- Ctrl+Shift+C: spelkön.
- Ctrl+Shift+T och Ctrl+Shift+V: nästa och föregående i kön.

Alla dessa kan ändras i Verktyg, Tangentbordsgenvägar. Hastighetskommandona använder med avsikt bokstäver som standard i stället för Ctrl+Shift+siffra eller Ctrl+Shift+punkt, eftersom Windows och vissa NVDA-tillägg fångar upp dem innan något program ser dem.

## Uppspelningshastighet {#playback-speed}

Spelare, Uppspelningshastighet ändrar hur fort media spelas, från halv till tredubbel hastighet, med bibehållen tonhöjd.

- Ctrl+Shift+U ökar, Ctrl+Shift+D minskar och Ctrl+Shift+N återgår till 1x.
- Undermenyn har fasta steg: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x och 3x.
- Spelarfönstret har en hastighetsruta som du kan ange direkt.

”Standarduppspelningshastighet” i Inställningar, Mediaspelare anger hastigheten som allt startar med.

## Equalizer {#equalizer}

Ctrl+Shift+E eller Spelare, Equalizer öppnar en equalizer med tio band och förförstärkning.

- ”Aktivera equalizer” slår på och av alltihop.
- Varje band är ett reglage som meddelar sin förstärkning när du ändrar det.
- Spara som förinställning sparar aktuella band under ett namn; Ta bort förinställning tar bort en.
- Återställ (plant) återställer varje band till noll.

Equalizern gäller allt som BlindRSS spelar och dess inställning sparas.

## Kapitel {#chapters}

Poddar och YouTube-videor har ofta kapitel. När det spelade objektet har dem listar Spelare, Kapitel dem och att hoppa till ett söker dit.

- Kapitelundermenyn fylls när objektets kapitel är kända och säger ”Inga kapitel tillgängliga” när det saknar dem.
- Spelarfönstret har en kapitelknapp och en kapitelruta.
- Kapitellänkar på artikellistans snabbmeny listar länkarna som en kapitelbeskrivning innehåller.

Kapitel läses in i bakgrunden medan du flyttar genom listan, så de är vanligen klara innan du trycker på spela upp.

## Spelkö {#play-queue}

Spelkön är listan över vad som spelas härnäst.

- Ctrl+Shift+C öppnar köfönstret.
- Ctrl+Shift+T och Ctrl+Shift+V spelar nästa respektive föregående objekt.
- Lägg till i spelkö och Ta bort från spelkö på artikellistans snabbmeny ändrar den.

I köfönstret startar Spela upp valt objekt, Flytta upp och Flytta ned ordnar om kön, Ta bort släpper ett objekt och Rensa alla tömmer den. Kön överlever omstarter.

## Casta till andra enheter {#casting}

BlindRSS kan skicka det som spelas till en enhet i ditt nätverk: Chromecast, AirPlay-högtalare, DLNA/UPnP-renderare, Sonos-högtalare, Roku-spelare och Kodi. Ett avsnitt fortsätter på enheten där det var, och paus, spolning och position fungerar där som lokalt (Roku kan inte spola).

Välj enheten i castdialogrutan; BlindRSS strömmar genom sin egen lokala proxy, så en enhet som inte själv kan hämta originaladressen ändå spelar objektet. Transportkontroller fortsätter fungera från BlindRSS medan den castar.

## Hoppa över tystnad {#silence-skipping}

”Hoppa över tystnad (experimentellt)” i Inställningar, Mediaspelare upptäcker tysta partier under uppspelning och hoppar över dem, vilket märkbart kortar pratpoddar med långa pauser.

Den analyserar ljud medan det spelas och använder därför en del CPU och är märkt som experimentell. Stäng av den om uppspelningen inte är jämn.

## Hämta media {#downloads}

- Hämta sparar den valda artikelns ljud eller video i standardformatet.
- Hämta som låter dig först välja format.

Hämtningar måste aktiveras med ”Aktivera hämtningar” i Inställningar. Hämtningsmappen, kvarhållningsprincipen och standardformatet för videohämtning ställs in på samma sida; standardmappen är systemets mapp Hämtade filer.

Förlopp visas i statusradens andra fält och hämtade objekt spelas efteråt från disk i stället för över nätverket. Podcast Archive kan hämta en podds hela bakre katalog i en omgång.

## Inställningar {#settings}

Verktyg, Inställningar (Ctrl+comma) innehåller alla alternativ på flikarna: Allmänt, Flöden och artiklar, YouTube, Mediaspelare, Leverantör, Aviseringar, Översätt, Listrubriker, Avancerat och CAPTCHA-lösning.

Ctrl+Tab och Ctrl+Shift+Tab flyttar mellan flikar; Tab flyttar mellan kontroller på aktuell flik. OK tillämpar allt, Avbryt förkastar allt. Flikpositionerna hålls stabila mellan utgåvor eftersom de blir muskelminne.

Att trycka F1 på en flik öppnar den flikens avsnitt i denna guide.

## Inställningar: Allmänt {#settings-general}

- Gränssnittsspråk och om BlindRSS följer systemets språk. En ändring träder i kraft vid omstart. Se Gränssnittsspråk.
- ”Kom ihåg senast valda flöde/mapp vid start”.
- ”Bekräfta före borttagning av artiklar” och vad borttagning gör — flytta till Borttagna artiklar, ta bort permanent eller flytta till en kategori du anger.
- ”Felsökningsläge (visa konsol vid start)”, som också skriver en roterande blindrss.log intill dina data.
- Start och systemfält: stäng till systemfältet, minimera till systemfältet, starta i systemfältet, starta alltid maximerat och sök efter uppdateringar vid start.

## Inställningar: Flöden och artiklar {#settings-feeds}

- Intervallet för automatisk uppdatering, från fem minuter till fyra timmar.
- Om sökningen matchar bara rubriker eller rubriker och artikeltext.
- Maximalt antal samtidiga uppdateringar, maximalt antal anslutningar per värd, flödets tidsgräns och hur många gånger ett misslyckat flöde försöks igen.
- Maximalt antal cachade vyer och ”Cacha hela texten i bakgrunden”.
- ”Uppdatera flöden automatiskt vid start” och arbetsbelastningen vid start: använd cachen, uppdatera fullständigt vid start eller uppdatera alltid fullständigt.
- Artikelkvarhållning, som bestämmer hur länge artiklar behålls. Favoriter tas aldrig bort av kvarhållning.
- Hur artikeltext presenteras: meddela rubriker, markera listobjekt med punkter och nummer, markera citat, visa länkar med deras adress, beskriv tabeller och inkludera alternativtext för bilder.

## Inställningar: YouTube {#settings-youtube}

- Kakfilen för yt-dlp med en knappen Bläddra, en knapp ”Importera från webbläsare” och ett alternativ för att automatiskt hitta cookies.txt-exporter i mappen Hämtade filer.
- Läsa kakor direkt från en installerad webbläsare.
- ”Spela YouTube genom att hämta först”, som startar långsammare men är det mest tillförlitliga alternativet.
- Mappen för YouTube-uppspelningscache, dess maximala storlek i megabyte och en knapp för att rensa den nu.

Kakor är vad som gör åldersbegränsade videor och videor endast för medlemmar spelbara och vad ett fel ”logga in för att bekräfta att du inte är en robot” efterfrågar.

## Inställningar: Mediaspelare {#settings-media-player}

- Föredraget ljudkort eller systemets standard.
- ”Hoppa över tystnad (experimentellt)”. Se Hoppa över tystnad.
- Standarduppspelningshastigheten.
- ”Visa spelarfönstret när uppspelning startar”.
- Nätverkscachens storlek i millisekunder, som byter startfördröjning mot motståndskraft vid långsam anslutning.
- Sökvägar till ffmpeg, ffprobe och yt-dlp. Lämna en tom för automatisk identifiering; en sökväg du anger åsidosätter identifieringen och det som identifierats visas intill varje.
- Hämtningar: om hämtningar är aktiverade, hämtningsmappen, kvarhållningsprincipen och standardformatet för videohämtning.
- Ljud: om BlindRSS spelar sina aviseringsljud.

## Inställningar: Leverantör {#settings-provider}

Väljer var dina prenumerationer finns: lokalt i BlindRSS eller i ett värdkonto. Se Onlinekonton och leverantörer för vad var och en behöver.

Sidan visar vilken leverantör som är aktiv och dess inloggningsuppgifter — en Miniflux-adress och API-nyckel, ett Inoreader-app-ID och en nyckel med knappen Auktorisera eller en e-postadress och ett lösenord för The Old Reader eller BazQux. Rensa auktorisering loggar ut ett Inoreader-konto.

Den lokala leverantören använder flödena du lägger till i appen med Lägg till flöde och Importera OPML.

## Inställningar: Aviseringar {#settings-notifications}

- ”Aktivera aviseringar för nya artiklar” och om flödets namn visas i aviseringstexten.
- Maximalt antal aviseringar per uppdatering och om en sammanfattande avisering visas när gränsen nås.
- Testavisering skickar en nu.
- Exkludera flöden väljer flöden som aldrig aviserar.
- Meddelanden: vilka händelser BlindRSS talar direkt till skärmläsaren, per händelse, med en knapp Testmeddelande som skickar ett test genom både tal och punktskrift.

## Inställningar: Översätt {#settings-translate}

Slår på automatisk översättning av artikelinnehåll och väljer tjänsten som gör det.

- ”Aktivera automatisk översättning för artikelinnehåll”.
- Leverantören: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini eller Qwen.
- Målspråket väljs från listan eller skrivs som en kod, såsom en, es, fr eller pt-BR.
- En API-nyckel för vald leverantör och valfritt en specifik modell. För OpenRouter hämtar ”Läs in OpenRouter-modeller” listan över tillgängliga modeller.

Grok och Groq är olika tjänster med förvirrande lika namn: Grok är xAI:s med nycklar från console.x.ai som börjar med ”xai-”; Groq är värd för LLaMA och Mistral med kostnadsfria nycklar från console.groq.com som börjar med ”gsk_”.

Detta översätter artikeltext. Se Gränssnittsspråk för att ändra språket i BlindRSS eget gränssnitt.

## Inställningar: Listrubriker {#settings-list-headers}

Ställer in den globala kolumnlayouten för artikellistan: vilka kolumner som visas, i vilken ordning och hur breda de är. Se Kolumner i artikellistan.

Ett enskilt flöde kan åsidosätta detta från sina egna Flödesegenskaper.

## Inställningar: Avancerat {#settings-advanced}

- Datalagringsplats: behåll databasen och inställningarna i användardatamappen eller programmappen, med båda sökvägarna visade. Alternativet programmapp är vad som gör en portabel installation portabel.
- Uppdateringar: ”Installera uppdateringar automatiskt utan bekräftelse”.
- Webbläsaridentifiering: vilken webbläsare BlindRSS identifierar sig som när det hämtar flöden eller en anpassad User-Agent-sträng som du skriver. Den faktiska strängen visas nedan. Detta är viktigt för webbplatser som blockerar okända klienter.
- Videosökning: ”Aktivera vuxenwebbplatser i Videosökning”, avstängt som standard.

## Inställningar: CAPTCHA-lösning {#settings-captcha}

En frivillig, betald sista utväg för webbplatser som svarar med en CAPTCHA som importerade kakor inte kan passera.

”Aktivera CAPTCHA-lösningstjänst” slår på den och API-nyckelfältet innehåller kontonyckeln hos lösningstjänsten. Avgifter per lösning gäller, vilket är varför den är avstängd som standard och bara prövas efter att allt annat har misslyckats.

Försök först Importera webbplatskakor; det är gratis och löser de flesta fall.

## Onlinekonton och leverantörer {#providers}

BlindRSS kan behålla dina prenumerationer själv eller läsa dem från ett värdkonto. Inställningar, Leverantör väljer vilket.

- Lokal: prenumerationer finns i BlindRSS egen databas på denna dator. Inget synkroniseras någonstans.
- Miniflux: kräver adressen till din Miniflux-server och en API-nyckel från inställningarna för ditt Miniflux-konto.
- Inoreader: kräver ett app-ID och en appnyckel från Inoreaders utvecklarsida och sedan knappen Auktorisera för att logga in.
- The Old Reader: kräver kontots e-postadress och lösenord.
- BazQux: kräver kontots e-postadress och lösenord.

Med en värdleverantör tillhör lässtatus, prenumerationer och kategorier kontot, så de följer dig till andra enheter som är inloggade på samma konto. Vissa leverantörer håller kategorier i en enda platt lista och BlindRSS säger det i stället för att erbjuda nästling som inte skulle bestå.

## Aviseringar {#notifications}

BlindRSS visar en systemavisering när nya artiklar anländer, enligt Inställningar, Aviseringar.

- Aviseringar kan stängas av helt.
- Flödets namn kan inkluderas i texten.
- En gräns begränsar hur många som kommer per uppdatering, med en valfri sammanfattande avisering när gränsen nås.
- Enskilda flöden kan exkluderas, antingen från Exkludera flöden i Inställningar eller från ”Aviseringar för detta flöde” på flödets snabbmeny.
- En Filterregel kan undertrycka aviseringen för artiklarna den matchar.

Separat talar Meddelanden valda händelser direkt till skärmläsaren genom NVDAs eller JAWS eget gränssnitt och genom punktskrift, vilket kommer fram även när en systemavisering inte gör det.

## Artikelöversättning {#translation}

När översättning är aktiverad i Inställningar, Översätt, översätts artikeltext till ditt målspråk medan du läser den med AI-tjänsten du har konfigurerat.

Översättning sker vid behov och cachas, så att läsa om en artikel inte kostar för den två gånger. Den kräver internetanslutning och din egen API-nyckel hos den valda tjänsten.

Programgränssnittet översätts separat genom sina egna kataloger. Se Gränssnittsspråk.

## Importera webbplatskakor {#site-cookies}

Vissa webbplatser placerar en webbläsarverifieringssida — vanligtvis en Cloudflare-utmaning ”kontrollerar din webbläsare” — framför sitt innehåll. Dessa webbplatser svarar bara en session som redan har klarat utmaningen i en riktig webbläsare, så BlindRSS kan inte hämta dem självt.

Verktyg, Importera webbplatskakor ger den sessionen:

1. Öppna webbplatsen i din webbläsare och vänta tills den har laddats klart.
2. Exportera dess kakor till en cookies.txt-fil med ett webbläsartillägg för cookies.txt. För Chrome-baserade webbläsare länkar dialogrutan till ”Hämta cookies.txt LOKALT”.
3. Välj den exporterade filen i dialogrutan.
4. Klistra in webbläsarens User-Agent-sträng i fältet nedan. En webbsökning på ”what is my user agent” visar den. Cloudflare kräver exakt den User-Agent som kakan utfärdades till, så detta är viktigt.

Webbläsare i Firefox-familjen har en en-klicksväg: ”Importera från webbläsare” läser deras kakdatabas direkt. Chromium-baserade webbläsare krypterar sin, vilket är varför de behöver tillägget.

## Tangentbordsgenvägar {#keyboard-shortcuts}

Verktyg, Tangentbordsgenvägar listar alla kommandon i BlindRSS grupperade efter kategori med deras aktuella tangent och låter dig ändra vilket som helst.

- Välj ett kommando och välj Ändra genväg. Inspelningsdialogrutan registrerar sedan nästa tangentkombination du trycker.
- Ta bort genväg lämnar ett kommando obundet; det fungerar fortfarande från sin meny.
- Återställ alla till standard återställer de medföljande tangenterna.

Genvägar skickas före menyacceleratorer och fungerar i hela fönstret, även medan spelarfönstret har fokus, och tangentbordsvägen meddelar sig där menysökvägen är tyst. Dina ändringar sparas med inställningarna och överlever uppdateringar.

## Standardtangentbordsgenvägar {#shortcuts-reference}

Flöden:

- Ctrl+N: Lägg till flöde.
- F5: Uppdatera flöden. Shift+F5: Stoppa uppdatering. Ctrl+F5: Uppdatera valt flöde.
- F2: Redigera flöde eller kategori.
- Ctrl+Shift+R: Markera alla objekt som lästa.
- Ctrl+Shift+F: Hitta en podd eller RSS-flöde.

Artiklar och vyer:

- Ctrl+D: lägg till i eller ta bort från Favoriter.
- Backsteg: växla läst och oläst. Delete: ta bort. Shift+Delete: ta bort utan bekräftelse.
- Ctrl+E: fokusera sökfältet.
- Ctrl+Shift+H: rik vy av hela texten.
- Ctrl+1 till Ctrl+3: alla, olästa, lästa. Ctrl+4 till Ctrl+6: media och icke-media, med media, utan media.

Spelare:

- Ctrl+P: spela upp eller pausa. Ctrl+S: stoppa. Ctrl+Shift+P: visa eller dölj spelaren.
- Ctrl+Left och Ctrl+Right: sök. Ctrl+Up och Ctrl+Down: volym.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: snabbare, långsammare, normal.
- Ctrl+Shift+E: equalizer.
- Ctrl+Shift+C: spelkö. Ctrl+Shift+T och Ctrl+Shift+V: nästa och föregående.

Program:

- F1: denna guide, öppnad vid avsnittet för det du använder.
- Ctrl+comma: Inställningar.
- Ctrl+Shift+A: meddela den körande versionen.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: klipp ut, kopiera, klistra in, markera allt.

Kommandon som inte listas här levereras obundna och kan ges valfri tangent i Verktyg, Tangentbordsgenvägar.

## Gränssnittsspråk {#language}

BlindRSS gränssnitt är översatt till femton språk. Inställningar, Allmänt väljer ett eller låter det följa systemets språk. Ändringen träder i kraft när du startar om.

Översättningar levereras även mellan programutgåvor, så en rättad översättning når dig utan att vänta på en ny version.

Den här guiden följer samma språk när en översatt guide finns för det och faller annars tillbaka till engelska.

## Systemfältsikon och medietangenter {#tray}

BlindRSS kan bo i systemfältet. Inställningar, Allmänt bestämmer om fönstret skickas till systemfältet när det stängs eller minimeras och om det startar där.

Systemfältsikonen har uppspelningskontroller och öppnar huvudfönstret igen. Tangentbordets medietangenter — spela/pausa, stoppa, nästa, föregående — styr BlindRSS spelare i hela systemet.

## Lägga till skrivbordsgenvägar {#desktop-shortcuts}

Arkiv, Lägg till genvägar skapar genvägar till BlindRSS på skrivbordet, i Start-menyn och på aktivitetsfältet. Markera dem du vill ha och välj OK; resultatet för var och en rapporteras tillbaka.

En post i Start-menyn är också vad Windows kräver innan ett program får visa aviseringar, så den är värd att ha även om du startar BlindRSS på annat sätt.

## Kontrollera uppdateringar {#updates}

Hjälp, Kontrollera uppdateringar frågar om en nyare version finns och erbjuder att installera den.

Varje uppdatering verifieras innan den tillämpas: dess SHA-256 måste matcha det publicerade manifestet och dess Authenticode-signatur på Windows måste vara giltig. En uppdatering som inte klarar någon av kontrollerna installeras inte.

”Sök efter uppdateringar vid start” i Inställningar, Allmänt gör detta automatiskt och ”Installera uppdateringar automatiskt utan bekräftelse” i Inställningar, Avancerat tillämpar dem utan att fråga. Dina inställningar, databasen och hämtningar berörs inte av en uppdatering.

## Meddela versionen {#version}

Hjälp, Meddela version (Ctrl+Shift+A) talar den körande BlindRSS-versionen direkt till din skärmläsare.

En skärmläsares eget kommando ”rapportera programversion” läser körfilens versionsresurs, vilket fungerar för en installerad version men rapporterar Pythons version när BlindRSS körs från källkod. Detta kommando ger rätt svar i båda fallen.

## Om BlindRSS {#about}

Hjälp, Om visar versionen, licensen och länkar: GitHub-profilen, arkivet och ändringsloggen.

BlindRSS använder MIT-licensen — använd den, ändra den, distribuera om den eller paketera den för en distributions arkiv utan tillstånd.

## Använda detta hjälpfönster {#help-window}

Detta fönster är en vanlig, helt tangentbordstillgänglig läsare för guiden.

- Innehållslistan innehåller varje avsnitt. Bläddra med piltangenterna; att välja ett avsnitt flyttar texten till det och meddelar dess titel.
- Textområdet är skrivskyddat och markerbart, så en skärmläsare kan läsa det rad för rad och du kan kopiera från det.
- Ctrl+F flyttar till sökrutan. Skriv ett ord och tryck Enter för att hoppa till nästa förekomst.
- F3 hittar nästa förekomst, Shift+F3 den föregående. Sökningen går runt.
- Tab och Shift+Tab flyttar mellan sökrutan, innehållslistan och texten.
- Escape stänger fönstret.

F1 var som helst i BlindRSS öppnar detta fönster vid avsnittet för det du använder — den fokuserade kontrollen, den aktiva dialogrutan, det markerade menyalternativet eller spelaren. När det saknar avsnitt öppnas guiden i början.

Guiden visas på BlindRSS gränssnittsspråk när en översättning av den finns och annars på engelska.

## Felsökning {#troubleshooting}

Ett flöde slutade uppdateras. Se orsaken i Flöden med fel. Ett flyttat flöde behöver sin adress rättad i Flödesegenskaper; en webbplats som kräver webbläsarkontroll behöver Importera webbplatskakor.

En YouTube-video spelas inte. Importera YouTube-kakor i Inställningar, YouTube och slå på ”Spela YouTube genom att hämta först”. Felet ”logga in för att bekräfta att du inte är en robot” betyder alltid kakor.

Uppspelningen hackar. Öka nätverkscachen i Inställningar, Mediaspelare och stäng av Hoppa över tystnad, som är experimentellt och använder CPU.

En webbplats returnerar ingenting alls. Ändra webbläsaridentifieringen i Inställningar, Avancerat; vissa webbplatser avvisar okända klienter direkt.

Inget talas när ett kommando körs. Kontrollera Meddelanden i Inställningar, Aviseringar — varje händelse kan slås på eller av individuellt och det finns en testknapp.

Något beter sig märkligt och du vill rapportera det. Slå på felsökningsläge i Inställningar, Allmänt, återskapa problemet och bifoga blindrss.log som skrivs intill dina inställningar och data.

## Support och gemenskap {#support}

Felrapporter och funktionsönskemål hör hemma i GitHubs ärendehanterare på github.com/serrebidev/BlindRSS/issues.

För frågor, hjälp och utgivningsnyheter är SerrebiProjects-gruppen på Telegram på t.me/SerrebiProjects den snabbaste platsen att få svar.

Översättningar är alltid välkomna. Om du talar ett av de språk som stöds och något låter fel kommer en pull request som rättar det nästan säkert att godtas — se locale/README.md i arkivet för hur filerna är upplagda. Detsamma gäller den här guiden: en översatt kopia hör hemma i docs/help/<language>.md och behåller {#anchor}-markörerna exakt som i den engelska filen så att kontextkänslig hjälp fortsätter fungera.
