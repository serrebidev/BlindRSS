# Guida utente di BlindRSS

## Guida utente di BlindRSS {#user-guide}

BlindRSS è un client desktop per RSS e podcast adatto agli screen reader. Legge feed RSS e Atom, riproduce allegati di podcast e video, e funziona autonomamente oppure con un account ospitato come Miniflux, Inoreader, The Old Reader o BazQux.

Questa guida è inclusa nell'applicazione, quindi funziona senza connessione Internet né browser web. Premere F1 ovunque in BlindRSS per aprirla. Se il controllo, la finestra di dialogo, la voce di menu o la finestra in uso ha una sezione dedicata, F1 apre la guida in quella sezione anziché all'inizio.

Tutto qui è raggiungibile dalla tastiera. Usare l'elenco dei contenuti per spostarsi tra le sezioni, oppure la casella di ricerca per trovare una parola in qualsiasi punto della guida.

## Per iniziare {#getting-started}

Al primo avvio BlindRSS non ha feed. Esistono diversi modi per aggiungerne:

- Premere Ctrl+N per aggiungere un feed tramite indirizzo. Vedere Aggiungere un feed.
- Premere Ctrl+Shift+F per cercare directory di podcast e feed per nome. Vedere Trovare podcast e feed RSS.
- Importare un file OPML esportato da un altro lettore. Vedere Importare OPML.
- Importare un archivio YouTube Takeout per iscriversi a tutti i canali già seguiti. Vedere Importare un archivio YouTube Takeout.
- Accedere a un account ospitato in Strumenti, Impostazioni, Provider: BlindRSS leggerà le iscrizioni già presenti in quell'account. Vedere Account online e provider.

Dopo aver aggiunto feed, premere F5 per aggiornarli. I nuovi articoli compaiono nell'elenco articoli e i conteggi dei non letti accanto a ciascun feed nell'albero.

I tre punti da visitare presto sono Strumenti, Impostazioni (come si comporta BlindRSS), Strumenti, Scorciatoie da tastiera (ogni comando e il suo tasto), e questa guida.

## La finestra principale {#main-window}

La finestra principale ha quattro aree principali, oltre a una barra dei menu e una barra di stato. Tab e Shift+Tab si spostano tra esse, e F6 cicla i riquadri nella maggior parte dei gestori di finestre.

- L'albero di feed e cartelle a sinistra.
- Il campo di ricerca sopra l'elenco articoli.
- L'elenco articoli.
- Il riquadro di lettura sotto l'elenco articoli.

La barra dei menu contiene File, Modifica, Visualizza, Lettore, Strumenti e Aiuto. Premere Alt per raggiungerla, poi usare i tasti freccia. Ogni voce dispone di un tasto di accesso in ogni lingua dell'interfaccia, e la barra dei menu ricomincia dall'altro estremo.

Dimensioni, feed selezionato e stato della finestra sono ricordati tra le esecuzioni. "Ricorda l'ultimo feed/cartella selezionato all'avvio" in Impostazioni, Generale controlla se BlindRSS riapre il feed che si stava leggendo.

## Elenco di feed e cartelle {#feed-tree}

L'albero a sinistra elenca feed, categorie che li raggruppano, cartelle intelligenti, ricerche salvate e viste integrate (Tutti i feed, Preferiti, Articoli eliminati e Feed con errori).

- Le frecce Su e Giù spostano tra gli elementi.
- Freccia Destra espande una categoria, Freccia Sinistra la comprime.
- Invio o la selezione di un elemento carica i suoi articoli nell'elenco articoli.
- F2 apre le proprietà del feed o della categoria selezionata.
- Il tasto Applicazioni o Shift+F10 apre il menu contestuale.

Ogni feed mostra il suo conteggio dei non letti. Le categorie espanse e compresse sono ricordate, quindi l'albero appare uguale al successivo avvio.

I feed il cui aggiornamento non è riuscito sono comunque elencati normalmente; la vista Feed con errori li raccoglie così che un feed che ha smesso silenziosamente di funzionare non passi inosservato.

## Elenco articoli {#article-list}

L'elenco articoli mostra gli articoli dell'elemento selezionato nell'albero, dopo l'applicazione del filtro articoli, dell'ordinamento e del termine di ricerca correnti.

- Le frecce Su e Giù spostano tra gli articoli; il riquadro di lettura segue.
- Invio apre l'articolo selezionato.
- Shift+Su e Shift+Giù estendono la selezione, permettendo azioni collettive su più articoli.
- Backspace alterna letto e non letto per l'articolo selezionato.
- Delete rimuove gli articoli selezionati; Shift+Delete li rimuove senza richiesta di conferma.
- Ctrl+D aggiunge o rimuove un preferito.
- Il tasto Applicazioni o Shift+F10 apre il menu contestuale.

Le colonne visualizzate e il relativo ordine sono configurabili globalmente e per feed. Vedere Colonne dell'elenco articoli.

## Riquadro di lettura {#reading-pane}

Il riquadro sotto l'elenco articoli contiene il testo dell'articolo selezionato. È un'area di testo di sola lettura, quindi uno screen reader può leggerla riga per riga, parola per parola o carattere per carattere, e il testo può essere selezionato e copiato.

- Ctrl+F cerca nel testo dell'articolo.
- F3 e Shift+F3 si spostano alla corrispondenza successiva e precedente.
- Invio su un collegamento nel testo apre quel collegamento.

La presentazione del testo è configurabile in Impostazioni, Feed e articoli: si possono annunciare titoli, contrassegnare elementi di elenco con punti e numeri, contrassegnare citazioni, mostrare i collegamenti con il loro indirizzo, descrivere tabelle e includere il testo alternativo delle immagini. Il testo alternativo delle immagini può anche essere forzato attivo o inattivo per un singolo feed dal suo menu contestuale.

Se un feed pubblica soltanto un breve riassunto, BlindRSS può recuperare il testo integrale dell'articolo. Vedere Recupero del testo integrale degli articoli.

## Finestra articolo {#article-window}

L'apertura di un articolo può visualizzarlo in una finestra propria anziché nel riquadro di lettura, dandogli tutto lo schermo e mantenendolo aperto mentre ci si sposta nell'elenco.

La finestra è un'area di testo di sola lettura con le stesse funzioni di lettura, selezione e ricerca nel testo del riquadro di lettura. Escape la chiude.

## Campo di ricerca {#search-field}

Il campo di ricerca sopra l'elenco articoli filtra la vista corrente mentre si digita e si conferma con Invio.

- Ctrl+E porta il focus al campo di ricerca.
- Invio applica il termine.
- Escape, oppure il pulsante cancella, lo svuota e ripristina l'elenco completo.

Il campo di ricerca può essere nascosto se non viene mai usato; il menu Visualizza contiene il comando Mostra/Nascondi campo di ricerca. Se la ricerca corrisponde solo ai titoli oppure ai titoli e al testo degli articoli si imposta in Impostazioni, Feed e articoli, sotto "La ricerca corrisponde a".

Una ricerca da conservare può diventare una ricerca salvata che rimane nell'albero. Vedere Ricerche persistenti.

## Barra di stato {#status-bar}

La barra di stato in fondo alla finestra principale ha tre campi:

- Messaggi transitori, come quanti articoli ha trovato un filtro.
- Attività in background, come l'aggiornamento di un feed o un download in corso.
- Stato della riproduzione: cosa sta riproducendo e il tempo trascorso e rimanente.

Sono volutamente separati, così un messaggio di aggiornamento non può sovrascrivere un conteggio di risultati della ricerca mentre lo si legge.

## Menu contestuali {#context-menus}

L'albero dei feed e l'elenco articoli hanno ciascuno un menu contestuale, aperto con il tasto Applicazioni o Shift+F10. Contengono i comandi applicabili alla selezione: aggiornare, contrassegnare come letto, modificare, rimuovere, copiare collegamenti, accodare elementi multimediali e così via.

Anche i menu contestuali supportano F1: con una voce evidenziata, F1 apre la sezione di questa guida che la spiega.

## Aggiungere un feed {#adding-feeds}

File, Aggiungi feed (Ctrl+N) iscrive a un feed tramite indirizzo.

Incollare o digitare l'indirizzo del feed, oppure del sito stesso: quando l'indirizzo non è un feed BlindRSS cerca un feed nella pagina. Si può anche incollare l'indirizzo di un canale o playlist YouTube, un profilo Mastodon o Bluesky, una comunità PieFed o Lemmy, una pagina SoundCloud o Mixcloud, oppure un indirizzo Reddit o Groups.io, e BlindRSS lo trasforma in un feed.

Scegliere la categoria in cui inserire il feed, oppure lasciarlo senza categoria. L'opzione "Apri nella vista HTML" fa aprire per impostazione predefinita gli articoli di questo feed nella vista ricca.

Se non si conosce l'indirizzo, usare invece Trovare podcast e feed RSS.

## Rilevare feed in una pagina {#detect-feeds}

File, Rileva feed nella pagina prende l'indirizzo di una normale pagina web ed elenca i feed pubblicizzati dalla pagina, consentendo di iscriversi senza cercare personalmente il collegamento del feed.

È il comando giusto quando un sito ha un collegamento "iscriviti" o "RSS" difficile da raggiungere, oppure quando la pagina offre più feed (tutti i post, una categoria, commenti) e si desidera scegliere.

## Trovare podcast e feed RSS {#find-podcast}

Strumenti, Trova un podcast o feed RSS (Ctrl+Shift+F) cerca per nome, argomento o indirizzo del sito nelle directory di podcast e feed, per iscriversi senza conoscere alcun indirizzo di feed.

1. Digitare nella casella di ricerca ciò che si cerca: un nome di podcast, un argomento o l'indirizzo di un sito.
2. Scegliere una fonte, oppure lasciare "Tutte le fonti".
3. Premere Invio o il pulsante Cerca.
4. Scorrere con le frecce l'elenco dei risultati. Ogni riga mostra titolo, directory di provenienza e dettagli.
5. Premere Invio su un risultato, oppure scegliere OK, per iscriversi.

Le ricerche vengono eseguite contemporaneamente su più directory e i risultati arrivano mano a mano che ciascuna risponde, quindi l'elenco cresce mentre lo si legge. Escape chiude la finestra di dialogo e interrompe la ricerca.

## Directory di podcast e feed {#podcast-directories}

La casella Fonte in Trova un podcast o feed RSS sceglie dove cercare. Oltre a "Tutte le fonti", "Tutte le fonti podcast" e "Tutte le fonti di feed RSS", sono disponibili singolarmente queste directory:

- Directory podcast: iTunes (Apple Podcasts), gPodder, fyyd, Podverse, SoundCloud e Mixcloud.
- Directory di feed: NewsBlur, Feedspot, Google News, Bing News e Feedly.
- Ricerca di siti e comunità: YouTube, Reddit, Groups.io e Fediverse — Mastodon, Bluesky, PieFed e Lemmy o Kbin, ognuno selezionabile anche singolarmente.
- Rilevamento basato sull'indirizzo: Feedsearch e la scansione dei siti di BlindRSS, che recupera un sito e cerca al suo interno i feed.

Non ci si affida a una sola directory. La ricerca in "Tutte le fonti" interroga insieme i gruppi podcast e RSS e unisce i risultati, mantenendo i feed di query generici di Google News sotto le corrispondenze dirette dei feed.

## Iscriversi a un risultato di ricerca {#subscribing}

In qualsiasi finestra di ricerca — Trova un podcast o feed RSS, Ricerca video o il pulsante Trova di Archivio podcast — premere Invio su un risultato, oppure scegliere OK con esso selezionato, effettua l'iscrizione.

BlindRSS risolve prima il risultato in un vero indirizzo di feed, quindi l'iscrizione a un podcast trovato in una directory, a un canale YouTube o a un account Fediverse funziona nello stesso modo. Il nuovo feed appare nell'albero e viene aggiornato immediatamente.

Se lo si vuole in una categoria particolare, spostarlo in seguito dal suo menu contestuale o da Proprietà feed.

## Archivio podcast {#podcast-archive}

Strumenti, Archivio podcast sfoglia tutta la cronologia degli episodi di un podcast — sia quelli ancora nel feed sia quelli meno recenti recuperati da BlindRSS — e li scarica in gruppi.

Molti feed podcast pubblicano soltanto gli episodi più recenti. Il recupero dall'archivio viene eseguito automaticamente in background; questa finestra permette di vederne lo stato, ritentarlo manualmente e scaricare ciò che ha trovato.

- Scegliere il podcast nella casella Podcast.
- Filtra episodi restringe l'elenco mentre si digita.
- Riesegui scansione archivio esegue nuovamente il recupero per quel podcast.
- Trova o aggiungi podcast apre la ricerca dei feed per archiviare un podcast a cui non si è ancora iscritti.
- Riproduci riproduce l'episodio selezionato, Scarica selezionato lo scarica e Scarica tutto scarica l'intero elenco visibile.
- Annulla download interrompe un gruppo di download in esecuzione.

La finestra resta aperta durante il download di un gruppo, così si può continuare a leggere.

## Ricerca video {#video-search}

Strumenti, Ricerca video cerca in una sola volta tutti i siti interrogabili da yt-dlp e permette di riprodurre, accodare o sottoscrivere ciò che trova.

- Digitare un termine di ricerca e premere Invio o il pulsante Cerca.
- La casella ambito limita la ricerca a un sito; l'impostazione predefinita li cerca tutti.
- I risultati arrivano quando risponde ciascun sito, prima i siti principali. I titoli che arrivano come segnaposto vengono compilati quando si risolvono.
- Carica altri risultati recupera un altro gruppo da ogni sito.
- L'ordinamento tramite un'intestazione di colonna riordina quanto è arrivato.

I video identici trovati su più siti vengono uniti in una riga. I siti per adulti sono esclusi salvo che "Abilita siti per adulti nella ricerca video" sia attivato in Impostazioni, Avanzate.

## Aprire un articolo tramite URL {#open-article-url}

File, Apri articolo prende l'indirizzo di qualunque pagina web e lo legge in BlindRSS come fosse un articolo: testo estratto, nel riquadro di lettura, con le stesse opzioni di lettura di tutto il resto.

Usarlo per una pagina isolata ricevuta, senza iscriversi a nulla. Se la pagina è un forum o una discussione, BlindRSS legge l'intera discussione. Vedere Forum e discussioni.

## Aprire un URL multimediale {#open-media-url}

File, Apri URL multimediale riproduce audio o video da un indirizzo nel lettore integrato senza iscriversi a nulla.

Accetta collegamenti diretti ai media e indirizzi di pagine risolvibili da yt-dlp — YouTube, Rumble, Odysee, SoundCloud e molti altri. Il risultato viene riprodotto come qualsiasi altro elemento e può essere aggiunto alla coda di riproduzione.

## Rimuovere un feed {#removing-feeds}

File, Rimuovi feed annulla l'iscrizione al feed selezionato. Lo stesso comando si trova nel menu contestuale del feed.

La rimozione di un feed elimina i suoi articoli dal database. Non tocca ciò che è già stato scaricato su disco. Se si usa un provider ospitato, l'annullamento dell'iscrizione viene inviato anche a quell'account.

Per rimuovere un'intera categoria e tutto ciò che contiene, usare Elimina categoria e feed nel menu contestuale della categoria. Vedere Categorie e sottocategorie.

## Proprietà feed {#feed-properties}

F2, oppure Modifica feed nel menu contestuale, apre le proprietà del feed selezionato.

- Il suo titolo, che si può sostituire; "Ripristina titolo predefinito del feed" nel menu contestuale ripristina il titolo del feed stesso.
- Il suo indirizzo e la categoria a cui appartiene.
- Se i suoi nuovi articoli generano una notifica.
- Se si apre nella vista HTML ricca.
- La propria disposizione delle colonne dell'elenco articoli, nella scheda Intestazioni elenco, che prevale su quella globale.

Visualizza descrizione feed nel menu contestuale dell'elenco articoli mostra la descrizione pubblicata dal feed stesso.

## Categorie e sottocategorie {#categories}

Le categorie raggruppano i feed nell'albero e possono essere nidificate: una categoria può contenere sia feed sia ulteriori sottocategorie.

- File, Aggiungi categoria ne crea una.
- Aggiungi sottocategoria nel menu contestuale di una categoria ne crea una al suo interno.
- Modifica categoria la rinomina o la sposta. Vedere Proprietà categoria.
- Rimuovi categoria elimina la categoria ma conserva i suoi feed.
- Elimina categoria e feed elimina la categoria e annulla l'iscrizione a tutto ciò che contiene.
- Importa OPML qui importa un file direttamente in quella categoria.
- Esporta categoria in OPML esporta solo quel ramo.

Alcuni provider ospitati mantengono le categorie in un unico elenco piatto. In tal caso BlindRSS lo comunica e le opzioni "sposta nel genitore" non sono disponibili.

## Proprietà categoria {#category-properties}

Modifica categoria apre le proprietà della categoria: il nome e la categoria genitore in cui si trova.

Rinominare una categoria conserva tutti i suoi feed. Spostarla sposta l'intero ramo, incluse eventuali sottocategorie.

## Aggiornare i feed {#refreshing}

- F5 aggiorna ogni feed.
- Ctrl+F5 aggiorna soltanto il feed o la categoria selezionata.
- Shift+F5 interrompe un aggiornamento in corso.
- Aggiorna categoria nel menu contestuale di una categoria aggiorna quel ramo.

Solo uno tra Aggiorna feed e Interrompi aggiornamento è disponibile alla volta, quindi il comando da tastiera corrisponde a quanto offre il menu. Il progresso appare nel secondo campo della barra di stato.

L'aggiornamento automatico si configura in Impostazioni, Feed e articoli: intervallo, quanti feed aggiornare alla volta, quante connessioni per host, timeout per feed e quante volte ritentare un feed non riuscito. "Aggiorna automaticamente i feed all'avvio" aggiorna tutto al lancio, e l'opzione del carico di avvio sceglie tra usare la cache e forzare un aggiornamento completo.

## Feed con errori {#feed-errors}

La vista Feed con errori, e File, Visualizza errori feed, elencano i feed il cui ultimo aggiornamento non è riuscito, con la ragione.

Un feed che ha smesso silenziosamente di funzionare appare esattamente come un feed senza nuovi articoli; per questo esiste questa vista. Da essa si può:

- Aggiorna selezionato, per provare subito di nuovo.
- Copia dettagli, per inserire negli appunti il testo dell'errore.
- Proprietà feed, per correggere l'indirizzo.
- Rimuovi feed, quando il feed non esiste più.

Cause comuni sono un feed spostato o ritirato, un sito che ora richiede un controllo del browser (vedere Importare cookie del sito) e un'interruzione temporanea del server.

## Importare OPML {#import-opml}

OPML è il formato di file standard per un elenco di iscrizioni a feed. Ogni lettore di feed può esportarne uno, quindi OPML permette di spostare le iscrizioni da un altro lettore in BlindRSS senza aggiungerle una alla volta.

File, Importa OPML chiede il file e aggiunge ogni feed che contiene, mantenendo la struttura di categorie descritta dal file. I feed a cui si è già iscritti non vengono duplicati.

Importa OPML qui, nel menu contestuale di una categoria, inserisce l'intera importazione in quella categoria anziché al livello superiore.

Per ottenere un file OPML da un altro lettore, cercare "Esporta", "Backup" o "Iscrizioni" nelle sue impostazioni.

## Esportare OPML {#export-opml}

File, Esporta OPML scrive tutte le iscrizioni, con le rispettive categorie, in un file OPML.

Usarlo per fare il backup delle iscrizioni, spostarle in un altro lettore o computer oppure condividere un insieme di feed con qualcun altro. Esporta categoria in OPML nel menu contestuale di una categoria esporta solo quel ramo.

## Importare un archivio YouTube Takeout {#import-youtube-takeout}

Google Takeout è il servizio di esportazione dati di Google. Un archivio YouTube Takeout è un file ZIP che contiene i dati YouTube, incluso l'elenco dei canali a cui si è iscritti. File, Importa YouTube Takeout legge tale ZIP e iscrive a quei canali come feed, così i nuovi video di ogni canale arrivano come articoli.

Per ottenere l'archivio:

1. Andare a takeout.google.com e accedere con l'account Google in cui si trovano le iscrizioni YouTube.
2. Scegliere "Deseleziona tutto", poi selezionare soltanto YouTube e YouTube Music.
3. In "Tutti i dati YouTube inclusi", mantenere almeno "iscrizioni"; "cronologia" e "playlist" sono facoltativi e BlindRSS può usarli anch'essi.
4. Esportare una volta come file ZIP e attendere l'email di Google: un archivio grande può richiedere ore.
5. Scaricare lo ZIP e indicarlo a questo comando.

BlindRSS mostra quindi ciò che ha trovato, raggruppato per fonte, e permette di scegliere i gruppi da importare:

- Iscrizioni: i canali seguiti.
- Cronologia: canali guardati ma non seguiti.
- I propri canali.
- Playlist, come feed a sé stanti.

Gli indirizzi duplicati vengono rimossi, quindi l'importazione di un secondo archivio in seguito aggiunge solo le novità. Lo ZIP non viene mai estratto su disco; vengono letti soltanto i piccoli file di dati al suo interno.

## Ricerche persistenti {#persistent-search}

Una ricerca persistente è un termine di ricerca che resta nell'albero come elemento proprio, così gli articoli che vi corrispondono sono sempre a un tasto freccia di distanza.

Strumenti, Configura ricerca persistente gestisce l'elenco: Aggiungi ne crea una da un termine, Rimuovi la elimina. Ogni ricerca salvata appare nell'albero e viene rivalutata quando la si seleziona, quindi riflette sempre gli articoli correnti.

Usarla per un argomento seguito in tutti i feed — il nome di una persona, un prodotto, un luogo. Per qualcosa di più strutturato di una frase, usare Cartelle intelligenti.

## Cartelle intelligenti {#smart-folders}

Una cartella intelligente è una cartella nell'albero il cui contenuto è definito da una regola anziché dal feed di provenienza di un articolo.

Nuova cartella intelligente, nel menu contestuale dell'albero, apre l'editor di regole. Una regola è un insieme di condizioni unite da "corrisponde a tutte" (e) o "corrisponde a una qualsiasi" (o); i gruppi di condizioni possono nidificarsi, quindi è possibile esprimere "(A e B) o C".

Le condizioni verificano questi campi:

- Campi sì/no: letto, preferito, aperto, aggiornato.
- Campi di testo: titolo, contenuto, descrizione, autore, feed, url e tag — le categorie o etichette pubblicate dal sito stesso.

Le condizioni di testo usano contiene, non contiene, è uguale a o inizia con.

Le cartelle intelligenti non spostano né copiano nulla; sono una vista degli articoli già presenti. Per modificare gli articoli al loro arrivo, usare Regole filtro.

## Regole filtro {#filter-rules}

Strumenti, Regole filtro è il motore di ordinamento degli articoli di BlindRSS. Le regole elaborano gli articoli in arrivo come i filtri email elaborano la posta in arrivo.

Ogni regola associa una condizione — lo stesso editor di regole usato dalle Cartelle intelligenti — a un insieme di azioni:

- Sposta l'articolo in una categoria.
- Etichettalo anche con una categoria, lasciandolo dov'è.
- Contrassegnalo come letto.
- Contrassegnalo come preferito.
- Eliminalo, seguendo il comportamento di eliminazione configurato.
- Non inviare la sua notifica di nuovo articolo.

Le regole vengono eseguite nell'ordine dell'elenco e ogni regola abilitata che corrisponde aggiunge le proprie azioni. Una regola impostata per fermarsi termina la pipeline per l'articolo dopo una corrispondenza, quindi le regole successive non lo vedono. Spostare le regole in alto e in basso per controllare quale prevale.

Una regola senza azioni non fa nulla e viene rifiutata, così una regola incompleta non può assorbire silenziosamente articoli.

## Filtro articoli {#article-filter}

Visualizza, Filtro articoli limita ogni vista in base allo stato di lettura e alla presenza di media allegati a un articolo. I due gruppi si combinano.

- Ctrl+1: tutti gli articoli.
- Ctrl+2: solo non letti.
- Ctrl+3: solo letti.
- Ctrl+4: con e senza media.
- Ctrl+5: solo con media.
- Ctrl+6: senza media.

Il filtro si applica a qualunque elemento selezionato nell'albero, comprese Cartelle intelligenti e ricerche salvate, e persiste tra le esecuzioni. "Solo con media" è il modo più rapido per trasformare un feed misto in un elenco di podcast.

## Ordinare gli articoli {#sorting}

Visualizza, Ordina per ordina l'elenco articoli per data, nome, autore, descrizione, feed o stato. Crescente inverte la direzione; l'impostazione predefinita è dal più recente.

L'ordinamento si applica a ogni vista ed è ricordato tra le esecuzioni. Ordinare per feed è utile in Tutti i feed e nelle Cartelle intelligenti, dove gli articoli provengono contemporaneamente da molte fonti.

## Colonne dell'elenco articoli {#list-headers}

Le colonne dell'elenco articoli, il loro ordine e la loro larghezza si possono scegliere liberamente. Impostazioni, Intestazioni elenco imposta la disposizione globale; la scheda Intestazioni elenco del feed la sostituisce per quel feed, e "Usa la disposizione globale delle colonne" disattiva nuovamente la sostituzione.

Meno colonne significano meno informazioni da leggere per uno screen reader su ogni riga, perciò vale la pena rimuovere quelle inutilizzate.

## Aprire gli articoli {#opening-articles}

Invio su un articolo nell'elenco lo apre. A seconda dell'articolo e delle impostazioni, ciò significa il riquadro di lettura, una finestra propria o la vista HTML ricca.

- Apri articolo nel menu contestuale fa la stessa cosa.
- Apri nel browser passa l'indirizzo dell'articolo al browser web di sistema.
- Apri browser accessibile legge invece la pagina all'interno di BlindRSS. Vedere Browser accessibile.

L'apertura di un articolo lo contrassegna come letto salvo modifica di questo comportamento.

## Articoli letti e non letti {#read-status}

- Backspace, oppure Alterna letto/non letto, cambia lo stato dell'articolo selezionato.
- Ctrl+Shift+R contrassegna come letto tutto nella vista corrente.
- Contrassegna tutti gli elementi come letti, nel menu contestuale di un feed o categoria, fa lo stesso per quel ramo.
- Contrassegna come letto e Contrassegna come non letto nel menu contestuale dell'elenco articoli agiscono sull'intera selezione e indicano quanti articoli interesseranno.

I conteggi dei non letti appaiono accanto a ogni feed nell'albero. Il filtro articoli può nascondere completamente gli articoli letti.

## Preferiti {#favorites}

Ctrl+D aggiunge l'articolo selezionato ai Preferiti, oppure lo rimuove se vi è già. La vista Preferiti nell'albero elenca tutto ciò che è stato contrassegnato.

I preferiti sopravvivono alla politica di conservazione: un articolo contrassegnato non viene rimosso quando vengono puliti gli articoli più vecchi. Preferito può essere usato anche come condizione in Cartelle intelligenti e Regole filtro.

## Articoli eliminati {#deleted-articles}

Il comportamento di Delete è configurabile in Impostazioni, Generale, sotto "Quando elimino un articolo":

- Spostalo in Articoli eliminati, da cui può essere ripristinato.
- Rimuovilo definitivamente.
- Spostalo in una categoria indicata dall'utente.

Con la prima impostazione, la vista Articoli eliminati nell'albero elenca ciò che è stato rimosso, Ripristina riporta indietro un articolo, ed eliminarlo dall'interno di quella vista lo rimuove definitivamente.

"Conferma prima di eliminare gli articoli" controlla la richiesta di conferma. Shift+Delete la salta sempre.

## Recupero del testo integrale degli articoli {#full-text}

Molti feed pubblicano soltanto un titolo e una o due frasi. BlindRSS può recuperare la pagina dell'articolo ed estrarne il testo reale, così il riquadro di lettura mostra l'articolo intero invece di un'anteprima.

Ciò avviene automaticamente mentre ci si sposta nell'elenco, in background, e il risultato viene memorizzato nella cache. "Memorizza in background il testo integrale" in Impostazioni, Feed e articoli recupera anticipatamente gli articoli vicini alla posizione, così spostarsi in basso nell'elenco non attende la rete.

Se un sito rifiuta completamente di essere letto, di solito è protetto da un controllo del browser. Vedere Importare cookie del sito.

## Vista ricca del testo integrale {#rich-view}

Ctrl+Shift+H porta il riquadro di lettura alla vista HTML ricca, che rende l'articolo come farebbe un browser, con titoli, elenchi, tabelle e collegamenti come elementi reali su cui uno screen reader può navigare con i propri comandi strutturali.

La vista testo semplice è l'impostazione predefinita perché è più veloce e non sorprende mai. La vista ricca è utile per gli articoli la cui struttura trasmette significato.

Un feed può essere impostato per aprirsi sempre nella vista ricca dalle Proprietà feed, e i collegamenti nella vista ricca si aprono nel browser di sistema anziché nella vista.

## Browser accessibile {#accessible-browser}

Visualizza, Apri browser accessibile apre una pagina dentro BlindRSS in una finestra realizzata per la lettura con screen reader, anziché passarla al browser di sistema.

È lo strumento giusto per una pagina da leggere anziché con cui interagire, e per siti la cui interfaccia è difficile da navigare. Condivide le impostazioni cookie e identità del browser di BlindRSS, quindi anche le pagine dietro un controllo del browser si aprono qui dopo avere importato i loro cookie.

## Video YouTube {#youtube}

L'indirizzo di un canale o playlist YouTube può essere sottoscritto come qualunque feed. I suoi video arrivano quindi come articoli, con descrizione, trascrizione ed elenco capitoli in linea, così un video può essere letto anziché guardato.

La riproduzione passa tramite yt-dlp. Impostazioni, YouTube la controlla:

- Un file cookie, che permette a BlindRSS di vedere i video con limite di età e per soli membri ai quali si ha accesso. Può essere importato direttamente da un browser o raccolto automaticamente da esportazioni cookies.txt nella cartella Download.
- "Riproduci YouTube scaricando prima", che avvia più lentamente ma è molto più affidabile.
- La cartella cache di riproduzione YouTube e la sua dimensione massima, con un pulsante per svuotarla.

Importa YouTube Takeout iscrive in un passaggio a ogni canale già seguito.

## Forum e discussioni {#forums}

Reddit, Lemmy, Groups.io e Google Groups vengono letti come discussioni intere anziché un post alla volta: aprire una discussione fornisce il post originale e le risposte in un unico testo continuo, molto più rapido da leggere che seguire una discussione in un browser.

L'iscrizione funziona come per ogni feed: incollare l'indirizzo del subreddit, della comunità o del gruppo. I repository GitHub sono supportati allo stesso modo, come gli account e le comunità Mastodon, Bluesky e PieFed.

## Taglia, copia e incolla {#clipboard}

Il menu Modifica contiene i comandi standard degli appunti — Taglia (Ctrl+X), Copia (Ctrl+C), Incolla (Ctrl+V) e Seleziona tutto (Ctrl+A) — e funzionano in ogni campo di testo e nel riquadro di lettura.

BlindRSS aggiunge comandi che copiano elementi che conosce:

- Copia collegamento, l'indirizzo dell'articolo.
- Copia collegamento media, l'indirizzo del suo audio o video.
- Copia testo, il testo dell'articolo letto nel riquadro di lettura.
- Copia URL feed, l'indirizzo del feed selezionato.
- Copia collegamento immagine, su un articolo con un'immagine.

## Il lettore integrato {#player}

BlindRSS riproduce direttamente gli allegati podcast e video tramite VLC, quindi la riproduzione non esce mai dall'applicazione. Ctrl+Shift+P mostra o nasconde la finestra del lettore e la riproduzione continua in entrambi i casi.

La riproduzione è resa fluida da un proxy locale con cache degli intervalli, perciò la ricerca in un episodio lungo è rapida anche con una connessione lenta. I flussi che richiedono risoluzione — YouTube, Rumble, Odysee — passano prima da yt-dlp.

"Mostra la finestra del lettore all'avvio della riproduzione" in Impostazioni, Lettore multimediale decide se la finestra appare automaticamente quando qualcosa inizia.

## Controlli del lettore {#player-controls}

La finestra del lettore contiene, nell'ordine di tabulazione: stato della riproduzione, cursore di posizione, tempo trascorso e totale, pulsanti riavvolgi e avanti veloce, casella velocità, pulsante capitoli e cursore volume. Ognuno è raggiungibile e utilizzabile dalla tastiera, e ciascuno annuncia il valore corrente.

- Ctrl+P riproduce e mette in pausa.
- Ctrl+S interrompe.
- Ctrl+Left e Ctrl+Right riavvolgono e avanzano velocemente, e si ripetono se tenuti premuti. Su macOS, Option+Left e Option+Right fanno lo stesso, perché lì Ctrl+Left e Ctrl+Right appartengono a Mission Control.
- Ctrl+Up e Ctrl+Down cambiano il volume.

I tasti di ricerca e volume funzionano ovunque in BlindRSS durante una riproduzione, anche dentro una finestra di dialogo, quindi non è mai necessario trovare la finestra del lettore per mettere in pausa.

## Scorciatoie da tastiera del lettore {#player-shortcuts}

- Ctrl+Shift+P: mostra o nasconde la finestra del lettore.
- Ctrl+P: riproduci o pausa.
- Ctrl+S: interrompi.
- Ctrl+Left e Ctrl+Right: riavvolgi e avanti veloce (Option+Left e Option+Right su macOS).
- Ctrl+Up e Ctrl+Down: aumenta e diminuisci volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: più veloce, più lento, torna alla velocità normale.
- Ctrl+Shift+E: equalizzatore.
- Ctrl+Shift+C: coda di riproduzione.
- Ctrl+Shift+T e Ctrl+Shift+V: successivo e precedente nella coda.

Tutte queste sono rimappabili in Strumenti, Scorciatoie da tastiera. I comandi di velocità usano volutamente lettere anziché Ctrl+Shift+digit o Ctrl+Shift+period, perché Windows e alcuni componenti aggiuntivi NVDA li intercettano prima che un'applicazione li riceva.

## Velocità di riproduzione {#playback-speed}

Lettore, Velocità di riproduzione modifica la velocità di riproduzione dei media, da metà velocità a tripla velocità, preservando il tono.

- Ctrl+Shift+U accelera, Ctrl+Shift+D rallenta, Ctrl+Shift+N torna a 1x.
- Il sottomenu ha passi fissi: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x e 3x.
- La finestra del lettore ha una casella velocità impostabile direttamente.

"Velocità di riproduzione predefinita" in Impostazioni, Lettore multimediale stabilisce la velocità iniziale di tutto.

## Equalizzatore {#equalizer}

Ctrl+Shift+E, oppure Lettore, Equalizzatore, apre un equalizzatore a dieci bande con preamplificatore.

- "Abilita equalizzatore" attiva e disattiva l'intera funzione.
- Ogni banda è un cursore che annuncia il guadagno durante la modifica.
- Salva come preimpostazione conserva le bande correnti con un nome; Elimina preimpostazione ne rimuove una.
- Ripristina (piatto) riporta tutte le bande a zero.

L'equalizzatore si applica a tutto ciò che BlindRSS riproduce e la sua impostazione viene ricordata.

## Capitoli {#chapters}

Podcast e video YouTube spesso contengono capitoli. Quando l'elemento in riproduzione li possiede, Lettore, Capitoli li elenca e passare a uno di essi cerca quella posizione.

- Il sottomenu dei capitoli si riempie quando i capitoli dell'elemento sono noti e dice "Nessun capitolo disponibile" quando non ne ha.
- La finestra del lettore ha un pulsante capitoli e una casella capitoli.
- Collegamenti capitoli, nel menu contestuale dell'elenco articoli, elenca i collegamenti contenuti nella descrizione di un capitolo.

I capitoli vengono caricati in background mentre ci si sposta nell'elenco, quindi di solito sono pronti prima di premere riproduci.

## Coda di riproduzione {#play-queue}

La coda di riproduzione è l'elenco di ciò che verrà riprodotto dopo.

- Ctrl+Shift+C apre la finestra della coda.
- Ctrl+Shift+T e Ctrl+Shift+V riproducono l'elemento successivo e precedente.
- Aggiungi alla coda di riproduzione e Rimuovi dalla coda di riproduzione, nel menu contestuale dell'elenco articoli, la modificano.

Nella finestra della coda, Riproduci avvia l'elemento selezionato, Sposta su e Sposta giù riordinano la coda, Rimuovi elimina un elemento e Cancella tutto la svuota. La coda sopravvive ai riavvii.

## Trasmettere ad altri dispositivi {#casting}

BlindRSS può inviare ciò che riproduce a un dispositivo in rete: Chromecast, altoparlanti AirPlay, renderer DLNA/UPnP, altoparlanti Sonos, lettori Roku e Kodi. Un episodio prosegue sul dispositivo dal punto in cui si trovava, e pausa, spostamento e posizione funzionano lì come in locale (Roku non consente lo spostamento).

Scegliere il dispositivo dalla finestra di trasmissione; BlindRSS trasmette tramite il proprio proxy locale, così un dispositivo che non può recuperare da solo l'indirizzo originale riproduce comunque l'elemento. I controlli di trasporto restano operativi da BlindRSS durante la trasmissione.

## Salta silenzio {#silence-skipping}

"Salta silenzio (sperimentale)" in Impostazioni, Lettore multimediale rileva i passaggi silenziosi durante la riproduzione e li salta, accorciando sensibilmente i podcast parlati con pause lunghe.

Analizza l'audio mentre viene riprodotto, quindi usa una parte della CPU ed è contrassegnato come sperimentale. Disattivarlo se la riproduzione non è fluida.

## Scaricare media {#downloads}

- Scarica salva l'audio o il video dell'articolo selezionato nel formato predefinito.
- Scarica come permette di scegliere prima il formato.

I download devono essere attivati con "Abilita download" in Impostazioni. Cartella download, politica di conservazione e formato predefinito dei download video sono impostati nella stessa pagina; la cartella predefinita è la cartella Download di sistema.

Il progresso appare nel secondo campo della barra di stato e gli elementi scaricati vengono poi riprodotti dal disco anziché dalla rete. Archivio podcast può scaricare in un gruppo l'intero catalogo arretrato di un podcast.

## Impostazioni {#settings}

Strumenti, Impostazioni (Ctrl+comma) contiene ogni opzione, nelle schede: Generale, Feed e articoli, YouTube, Lettore multimediale, Provider, Notifiche, Traduci, Intestazioni elenco, Avanzate e Risoluzione CAPTCHA.

Ctrl+Tab e Ctrl+Shift+Tab si spostano tra le schede; Tab si sposta tra i controlli della scheda corrente. OK applica tutto, Annulla scarta tutto. Le posizioni delle schede restano stabili tra le versioni perché diventano memoria muscolare.

Premere F1 in una scheda apre la sezione corrispondente di questa guida.

## Impostazioni: Generale {#settings-general}

- Lingua dell'interfaccia e scelta se BlindRSS segue la lingua del sistema. Una modifica ha effetto al riavvio. Vedere Lingua dell'interfaccia.
- "Ricorda l'ultimo feed/cartella selezionato all'avvio".
- "Conferma prima di eliminare gli articoli" e cosa fa l'eliminazione — spostare in Articoli eliminati, eliminare definitivamente o spostare in una categoria indicata.
- "Modalità debug (mostra console all'avvio)", che scrive anche un blindrss.log a rotazione accanto ai dati.
- Avvio e area di notifica: chiudi nell'area di notifica, minimizza nell'area di notifica, avvia nell'area di notifica, avvia sempre ingrandito e verifica gli aggiornamenti all'avvio.

## Impostazioni: Feed e articoli {#settings-feeds}

- L'intervallo di aggiornamento automatico, da cinque minuti a quattro ore.
- Se la ricerca corrisponde solo ai titoli oppure ai titoli e al testo degli articoli.
- Aggiornamenti concorrenti massimi, connessioni massime per host, timeout dei feed e quante volte ritentare un feed non riuscito.
- Viste memorizzate nella cache massime e "Memorizza in background il testo integrale".
- "Aggiorna automaticamente i feed all'avvio" e il carico dell'aggiornamento all'avvio: usa la cache, aggiorna completamente all'avvio o aggiorna sempre completamente.
- Conservazione degli articoli, che decide per quanto tempo conservarli. I preferiti non vengono mai rimossi dalla conservazione.
- Come viene presentato il testo dell'articolo: annuncia titoli, contrassegna gli elementi di elenco con punti e numeri, contrassegna citazioni, mostra i collegamenti con l'indirizzo, descrivi tabelle e includi testo alternativo delle immagini.

## Impostazioni: YouTube {#settings-youtube}

- Il file cookie yt-dlp, con un pulsante Sfoglia, un pulsante "Importa dal browser" e un'opzione per raccogliere automaticamente le esportazioni cookies.txt dalla cartella Download.
- Lettura dei cookie direttamente da un browser installato.
- "Riproduci YouTube scaricando prima", che si avvia più lentamente ma è l'opzione più affidabile.
- La cartella cache di riproduzione YouTube, la dimensione massima in megabyte e un pulsante per svuotarla ora.

I cookie permettono di riprodurre video con limite di età e per soli membri, e sono ciò che richiede un errore "accedi per confermare che non sei un bot".

## Impostazioni: Lettore multimediale {#settings-media-player}

- La scheda audio preferita oppure quella predefinita del sistema.
- "Salta silenzio (sperimentale)". Vedere Salta silenzio.
- La velocità di riproduzione predefinita.
- "Mostra la finestra del lettore all'avvio della riproduzione".
- La dimensione della cache di rete in millisecondi, che scambia ritardo di avvio con resilienza su una connessione lenta.
- Percorsi a ffmpeg, ffprobe e yt-dlp. Lasciarne uno vuoto per il rilevamento automatico; un percorso impostato sostituisce il rilevamento e ciò che è stato rilevato è mostrato accanto a ciascuno.
- Download: se i download sono abilitati, cartella download, politica di conservazione e formato predefinito dei download video.
- Suoni: se BlindRSS riproduce i suoi suoni di notifica.

## Impostazioni: Provider {#settings-provider}

Sceglie dove risiedono le iscrizioni: localmente in BlindRSS oppure in un account ospitato. Vedere Account online e provider per ciò che richiede ciascuno.

La pagina mostra il provider attivo e le sue credenziali — un indirizzo Miniflux e chiave API, ID e chiave dell'app Inoreader con pulsante Autorizza, oppure indirizzo email e password per The Old Reader o BazQux. Cancella autorizzazione disconnette un account Inoreader.

Il provider locale usa i feed aggiunti nell'app con Aggiungi feed e Importa OPML.

## Impostazioni: Notifiche {#settings-notifications}

- "Abilita notifiche per nuovi articoli" e se il nome del feed appare nel testo della notifica.
- Numero massimo di notifiche per aggiornamento e se una notifica di riepilogo viene mostrata una volta raggiunto tale limite.
- Prova notifica ne invia una ora.
- Escludi feed sceglie i feed che non notificano mai.
- Annunci: quali eventi BlindRSS comunica direttamente allo screen reader, per evento, con un pulsante Prova annuncio che invia una prova sia tramite voce sia tramite Braille.

## Impostazioni: Traduci {#settings-translate}

Attiva la traduzione automatica del contenuto degli articoli e sceglie il servizio che la esegue.

- "Abilita traduzione automatica del contenuto degli articoli".
- Il provider: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini o Qwen.
- La lingua di destinazione, scelta dall'elenco o digitata come codice quale en, es, fr o pt-BR.
- Una chiave API per il provider scelto e, facoltativamente, un modello specifico. Per OpenRouter, "Carica modelli OpenRouter" recupera l'elenco dei modelli disponibili.

Grok e Groq sono servizi diversi dai nomi confondibilmente simili: Grok è di xAI, con chiavi da console.x.ai che iniziano con "xai-"; Groq ospita LLaMA e Mistral, con chiavi gratuite da console.groq.com che iniziano con "gsk_".

Questo traduce il testo degli articoli. Per cambiare la lingua dell'interfaccia di BlindRSS, vedere Lingua dell'interfaccia.

## Impostazioni: Intestazioni elenco {#settings-list-headers}

Imposta la disposizione globale delle colonne dell'elenco articoli: quali colonne appaiono, in quale ordine e con quale larghezza. Vedere Colonne dell'elenco articoli.

Un singolo feed può sostituirla dalle proprie Proprietà feed.

## Impostazioni: Avanzate {#settings-advanced}

- Posizione di archiviazione dati: mantenere database e impostazioni nella cartella dati utente oppure nella cartella dell'applicazione, con entrambi i percorsi mostrati. L'opzione della cartella dell'applicazione rende portatile un'installazione portatile.
- Aggiornamenti: "Installa automaticamente gli aggiornamenti senza conferma".
- Identificazione browser: il browser come cui BlindRSS si identifica nel recuperare feed, oppure una stringa User-Agent personalizzata digitata. La stringa effettiva è mostrata sotto. Questo è importante per i siti che bloccano client sconosciuti.
- Ricerca video: "Abilita siti per adulti nella ricerca video", disattivata per impostazione predefinita.

## Impostazioni: Risoluzione CAPTCHA {#settings-captcha}

Un percorso facoltativo, a pagamento e di ultima risorsa per siti che rispondono con un CAPTCHA che i cookie importati non riescono a superare.

"Abilita servizio di risoluzione CAPTCHA" lo attiva e il campo chiave API contiene la chiave dell'account presso il servizio di risoluzione. Si applicano tariffe per ogni risoluzione; per questo è disattivato per impostazione predefinita e provato solo dopo che tutto il resto ha fallito.

Provare prima Importare cookie del sito: è gratuito e risolve la maggior parte dei casi.

## Account online e provider {#providers}

BlindRSS può conservare autonomamente le iscrizioni oppure leggerle da un account ospitato. Impostazioni, Provider sceglie quale.

- Locale: le iscrizioni risiedono nel database di BlindRSS su questo computer. Nulla viene sincronizzato altrove.
- Miniflux: richiede l'indirizzo del server Miniflux e una chiave API dalle impostazioni dell'account Miniflux.
- Inoreader: richiede ID e chiave app dalla pagina sviluppatori Inoreader, poi il pulsante Autorizza per accedere.
- The Old Reader: richiede l'indirizzo email e la password dell'account.
- BazQux: richiede l'indirizzo email e la password dell'account.

Con un provider ospitato, stato di lettura, iscrizioni e categorie appartengono all'account, quindi seguono su ogni altro dispositivo connesso allo stesso account. Alcuni provider mantengono le categorie in un solo elenco piatto, e BlindRSS lo segnala anziché offrire un annidamento che non persisterebbe.

## Notifiche {#notifications}

BlindRSS invia una notifica di sistema all'arrivo di nuovi articoli, in base a Impostazioni, Notifiche.

- Le notifiche possono essere completamente disattivate.
- Il nome del feed può essere incluso nel testo.
- Un limite riduce quante ne arrivano per aggiornamento, con una notifica di riepilogo facoltativa una volta raggiunto.
- I singoli feed possono essere esclusi, sia da Escludi feed in Impostazioni sia da "Notifiche per questo feed" nel menu contestuale del feed.
- Una Regola filtro può sopprimere la notifica degli articoli a cui corrisponde.

Separatamente, gli Annunci comunicano gli eventi scelti direttamente allo screen reader tramite l'interfaccia di NVDA o JAWS e tramite Braille, che passa anche quando una notifica di sistema non lo fa.

## Traduzione degli articoli {#translation}

Con la traduzione abilitata in Impostazioni, Traduci, il testo dell'articolo viene tradotto nella lingua di destinazione mentre lo si legge, usando il servizio AI configurato.

La traduzione avviene su richiesta e viene memorizzata nella cache, quindi rileggere un articolo non la paga due volte. Richiede una connessione Internet e una propria chiave API del servizio scelto.

L'interfaccia dell'applicazione è tradotta separatamente, tramite i propri cataloghi. Vedere Lingua dell'interfaccia.

## Importare cookie del sito {#site-cookies}

Alcuni siti collocano davanti ai contenuti una pagina di verifica del browser — tipicamente una verifica Cloudflare "checking your browser". Tali siti rispondono soltanto a una sessione che ha già superato la verifica in un browser reale, quindi BlindRSS non può recuperarli da solo.

Strumenti, Importa cookie del sito gli fornisce tale sessione:

1. Aprire il sito web nel browser e attendere che termini il caricamento.
2. Esportare i suoi cookie in un file cookies.txt con un'estensione browser cookies.txt. Per browser basati su Chrome, la finestra di dialogo collega a "Get cookies.txt LOCALLY".
3. Scegliere il file esportato nella finestra di dialogo.
4. Incollare la stringa User-Agent del browser nel campo sottostante. Cercare sul web "what is my user agent" la mostra. Cloudflare richiede l'esatto User-Agent a cui è stato emesso il cookie, quindi questo è importante.

I browser della famiglia Firefox hanno un percorso con un clic: "Importa dal browser" legge direttamente il database cookie. Quelli basati su Chromium cifrano i propri, per questo necessitano dell'estensione.

## Scorciatoie da tastiera {#keyboard-shortcuts}

Strumenti, Scorciatoie da tastiera elenca ogni comando di BlindRSS, raggruppato per categoria, con il tasto corrente, e permette di modificarne ciascuno.

- Selezionare un comando e scegliere Cambia scorciatoia. La finestra di acquisizione registra quindi la successiva combinazione di tasti premuta.
- Rimuovi scorciatoia lascia un comando senza associazione; continua a funzionare dal suo menu.
- Ripristina tutti i valori predefiniti ripristina i tasti forniti.

Le scorciatoie vengono inviate prima degli acceleratori di menu e funzionano nell'intera finestra, anche quando la finestra del lettore ha il focus; il percorso da tastiera si annuncia dove quello del menu rimane silenzioso. Le modifiche sono memorizzate con le impostazioni e sopravvivono agli aggiornamenti.

## Scorciatoie da tastiera predefinite {#shortcuts-reference}

Feed:

- Ctrl+N: Aggiungi feed.
- F5: Aggiorna feed. Shift+F5: Interrompi aggiornamento. Ctrl+F5: Aggiorna il feed selezionato.
- F2: Modifica feed o categoria.
- Ctrl+Shift+R: Contrassegna tutti gli elementi come letti.
- Ctrl+Shift+F: Trova un podcast o feed RSS.

Articoli e viste:

- Ctrl+D: aggiungi o rimuovi dai Preferiti.
- Backspace: alterna letto e non letto. Delete: elimina. Shift+Delete: elimina senza confermare.
- Ctrl+E: porta il focus al campo di ricerca.
- Ctrl+Shift+H: vista ricca del testo integrale.
- Ctrl+1 a Ctrl+3: tutti, non letti, letti. Ctrl+4 a Ctrl+6: con e senza media, con media, senza media.

Lettore:

- Ctrl+P: riproduci o pausa. Ctrl+S: interrompi. Ctrl+Shift+P: mostra o nascondi il lettore.
- Ctrl+Left e Ctrl+Right: cerca. Ctrl+Up e Ctrl+Down: volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: accelera, rallenta, normale.
- Ctrl+Shift+E: equalizzatore.
- Ctrl+Shift+C: coda di riproduzione. Ctrl+Shift+T e Ctrl+Shift+V: successivo e precedente.

Applicazione:

- F1: questa guida, aperta nella sezione relativa a ciò che si sta usando.
- Ctrl+comma: Impostazioni.
- Ctrl+Shift+A: annuncia la versione in esecuzione.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: taglia, copia, incolla, seleziona tutto.

I comandi non elencati qui vengono forniti senza associazione e possono ricevere qualsiasi tasto in Strumenti, Scorciatoie da tastiera.

## Lingua dell'interfaccia {#language}

L'interfaccia di BlindRSS è tradotta in quindici lingue. Impostazioni, Generale ne sceglie una, oppure la lascia seguire la lingua di sistema. La modifica ha effetto al riavvio.

Le traduzioni vengono distribuite tra le versioni dell'applicazione oltre che con esse, quindi una traduzione corretta arriva senza attendere una nuova versione.

Questa guida segue la stessa lingua quando ne esiste una traduzione e ricorre all'inglese quando non esiste.

## Icona nell'area di notifica e tasti multimediali {#tray}

BlindRSS può risiedere nell'area di notifica del sistema. Impostazioni, Generale decide se chiudere la finestra la invia lì, se lo fa minimizzarla e se si avvia lì.

L'icona nell'area di notifica possiede controlli di riproduzione e riapre la finestra principale. I tasti multimediali della tastiera — riproduci/pausa, interrompi, successivo, precedente — controllano il lettore BlindRSS a livello di sistema.

## Aggiungere collegamenti sul desktop {#desktop-shortcuts}

File, Aggiungi collegamenti crea collegamenti a BlindRSS sul desktop, nel menu Start e sulla barra delle applicazioni. Selezionare quelli desiderati e scegliere OK; viene riportato il risultato di ciascuno.

Una voce del menu Start è anche ciò che Windows richiede prima che un'applicazione possa inviare notifiche, quindi vale la pena averla anche se BlindRSS viene avviato in un altro modo.

## Verificare gli aggiornamenti {#updates}

Aiuto, Verifica aggiornamenti chiede se è disponibile una versione più recente e offre di installarla.

Ogni aggiornamento viene verificato prima dell'applicazione: il relativo SHA-256 deve corrispondere al manifesto pubblicato e su Windows la firma Authenticode deve essere valida. Un aggiornamento che non supera uno dei due controlli non viene installato.

"Verifica gli aggiornamenti all'avvio" in Impostazioni, Generale esegue questa operazione automaticamente e "Installa automaticamente gli aggiornamenti senza conferma" in Impostazioni, Avanzate li applica senza chiedere. Impostazioni, database e download non vengono toccati da un aggiornamento.

## Annunciare la versione {#version}

Aiuto, Annuncia versione (Ctrl+Shift+A) comunica la versione di BlindRSS in esecuzione direttamente allo screen reader.

Il comando proprio dello screen reader "segnala versione applicazione" legge la risorsa di versione dell'eseguibile, che funziona per una build installata ma riporta la versione di Python quando BlindRSS viene eseguito dai sorgenti. Questo comando fornisce la risposta corretta in entrambi i casi.

## Informazioni su BlindRSS {#about}

Aiuto, Informazioni mostra versione, licenza e collegamenti: profilo GitHub, repository e changelog.

BlindRSS è rilasciato con licenza MIT: è possibile usarlo, modificarlo, ridistribuirlo o pacchettizzarlo per i repository di una distribuzione, senza necessità di autorizzazione.

## Usare questa finestra di aiuto {#help-window}

Questa finestra è un lettore semplice e completamente accessibile da tastiera per la guida.

- L'elenco dei contenuti contiene ogni sezione. Scorrerlo con le frecce; la selezione di una sezione porta il testo a essa e ne annuncia il titolo.
- L'area di testo è di sola lettura e selezionabile, quindi uno screen reader può leggerla riga per riga e se ne può copiare il contenuto.
- Ctrl+F porta alla casella di ricerca. Digitare una parola e premere Invio per andare all'occorrenza successiva.
- F3 trova l'occorrenza successiva, Shift+F3 la precedente. La ricerca ricomincia dall'inizio.
- Tab e Shift+Tab si spostano tra casella di ricerca, elenco contenuti e testo.
- Escape chiude la finestra.

F1 ovunque in BlindRSS apre questa finestra nella sezione relativa a ciò che si sta usando — controllo con focus, finestra di dialogo attiva, voce di menu evidenziata o lettore. Quando non esiste una sezione, la guida si apre all'inizio.

La guida viene mostrata nella lingua dell'interfaccia di BlindRSS quando esiste una sua traduzione, e altrimenti in inglese.

## Risoluzione dei problemi {#troubleshooting}

Un feed ha smesso di aggiornarsi. Cercare la ragione in Feed con errori. Un feed spostato necessita della correzione dell'indirizzo in Proprietà feed; un sito che richiede un controllo del browser necessita di Importare cookie del sito.

Un video YouTube non viene riprodotto. Importare i cookie YouTube in Impostazioni, YouTube e attivare "Riproduci YouTube scaricando prima". Un errore "accedi per confermare che non sei un bot" indica sempre i cookie.

La riproduzione balbetta. Aumentare la cache di rete in Impostazioni, Lettore multimediale e disattivare Salta silenzio, che è sperimentale e usa CPU.

Un sito non restituisce proprio nulla. Cambiare l'identificazione browser in Impostazioni, Avanzate; alcuni siti rifiutano categoricamente client sconosciuti.

Non viene pronunciato nulla all'esecuzione di un comando. Controllare Annunci in Impostazioni, Notifiche: ogni evento può essere attivato o disattivato singolarmente ed è presente un pulsante di prova.

Qualcosa si comporta in modo strano e lo si vuole segnalare. Attivare la modalità debug in Impostazioni, Generale, riprodurre il problema e allegare il blindrss.log scritto accanto alle impostazioni e ai dati.

## Supporto e comunità {#support}

Bug e richieste di funzionalità appartengono al tracker di problemi GitHub, all'indirizzo github.com/serrebidev/BlindRSS/issues.

Per domande, aiuto e notizie sulle versioni, il gruppo SerrebiProjects su Telegram, t.me/SerrebiProjects, è il posto più rapido per ricevere risposta.

Le traduzioni sono sempre benvenute. Se si parla una delle lingue supportate e qualcosa suona sbagliato, una pull request che lo corregge sarà quasi certamente accettata: vedere locale/README.md nel repository per sapere come sono disposti i file. Lo stesso vale per questa guida: una copia tradotta appartiene a docs/help/<language>.md, mantenendo i marcatori {#anchor} esattamente come nel file inglese affinché l'aiuto sensibile al contesto continui a funzionare.
