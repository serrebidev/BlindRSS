# Guide de l’utilisateur BlindRSS

## Guide de l’utilisateur BlindRSS {#user-guide}

BlindRSS est un client de bureau pour flux RSS et podcasts, conçu pour les lecteurs d’écran. Il lit les flux RSS et Atom, lit les fichiers joints de podcast et de vidéo, et fonctionne seul ou avec un compte hébergé tel que Miniflux, Inoreader, The Old Reader ou BazQux.

Ce guide est inclus dans l’application : il fonctionne donc sans connexion Internet ni navigateur web. Appuyez sur F1 n’importe où dans BlindRSS pour l’ouvrir. Si le contrôle, la boîte de dialogue, l’élément de menu ou la fenêtre utilisée a sa propre section, F1 ouvre le guide à cette section plutôt qu’au début.

Tout est accessible au clavier. Utilisez la liste du contenu pour passer d’une section à l’autre, ou le champ de recherche pour trouver un mot dans le guide.

## Premiers pas {#getting-started}

Lors du premier démarrage, BlindRSS ne contient aucun flux. Vous pouvez en ajouter de plusieurs façons :

- Appuyez sur Ctrl+N pour ajouter un flux par son adresse. Voir Ajout d’un flux.
- Appuyez sur Ctrl+Shift+F pour rechercher des podcasts et des annuaires de flux par nom. Voir Recherche de podcasts et de flux RSS.
- Importez un fichier OPML exporté depuis un autre lecteur. Voir Importation d’OPML.
- Importez une archive YouTube Takeout pour vous abonner à toutes les chaînes que vous suivez déjà. Voir Importation d’une archive YouTube Takeout.
- Connectez-vous à un compte hébergé dans Outils, Paramètres, Fournisseur ; BlindRSS lit alors les abonnements déjà présents dans ce compte. Voir Comptes en ligne et fournisseurs.

Une fois vos flux ajoutés, appuyez sur F5 pour les actualiser. Les nouveaux articles apparaissent dans la liste des articles, et le nombre de non lus apparaît à côté de chaque flux dans l’arborescence.

Les trois endroits à consulter en premier sont Outils, Paramètres (le comportement de BlindRSS), Outils, Raccourcis clavier (chaque commande et sa touche), et ce guide.

## La fenêtre principale {#main-window}

La fenêtre principale comporte quatre régions, ainsi qu’une barre de menus et une barre d’état. Tab et Shift+Tab passent de l’une à l’autre, et F6 fait défiler les volets dans la plupart des gestionnaires de fenêtres.

- L’arborescence des flux et dossiers, à gauche.
- Le champ de recherche au-dessus de la liste des articles.
- La liste des articles.
- Le volet de lecture sous la liste des articles.

La barre de menus contient Fichier, Édition, Affichage, Lecteur, Outils et Aide. Appuyez sur Alt pour y accéder, puis utilisez les flèches. Chaque élément de menu possède une touche d’accès dans chaque langue d’interface, et la barre revient au début ou à la fin lorsqu’on la dépasse.

Les tailles, le flux sélectionné et l’état de la fenêtre sont mémorisés entre les lancements. L’option « Mémoriser le dernier flux/dossier sélectionné au démarrage » dans Paramètres, Général détermine si BlindRSS rouvre le flux que vous lisiez en dernier.

## Liste des flux et dossiers {#feed-tree}

L’arborescence à gauche répertorie vos flux, les catégories qui les regroupent, les dossiers intelligents, les recherches enregistrées et les vues intégrées (Tous les flux, Favoris, Articles supprimés et Flux avec erreurs).

- Les flèches Haut et Bas se déplacent entre les éléments.
- Flèche droite développe une catégorie, Flèche gauche la réduit.
- Enter ou la sélection d’un élément charge ses articles dans la liste.
- F2 ouvre les propriétés du flux ou de la catégorie sélectionné.
- La touche Applications ou Shift+F10 ouvre le menu contextuel.

Chaque flux affiche son nombre de non lus. Les catégories développées et réduites sont mémorisées ; l’arborescence est donc identique au prochain démarrage.

Les flux dont la mise à jour a échoué restent affichés normalement ; la vue Flux avec erreurs les rassemble afin qu’un flux qui a cessé silencieusement de fonctionner ne passe pas inaperçu.

## Liste des articles {#article-list}

La liste des articles affiche les articles de l’élément sélectionné dans l’arborescence, après application du filtre d’articles, de l’ordre de tri et du terme de recherche actuels.

- Les flèches Haut et Bas se déplacent entre les articles ; le volet de lecture suit.
- Enter ouvre l’article sélectionné.
- Shift+Up et Shift+Down étendent la sélection afin que les actions groupées s’appliquent à plusieurs articles.
- Backspace bascule l’état lu/non lu de l’article sélectionné.
- Delete supprime les articles sélectionnés ; Shift+Delete les supprime sans demander de confirmation.
- Ctrl+D ajoute ou retire un favori.
- La touche Applications ou Shift+F10 ouvre le menu contextuel.

Les colonnes affichées et leur ordre sont configurables globalement et flux par flux. Voir Colonnes de la liste des articles.

## Volet de lecture {#reading-pane}

Le volet de lecture sous la liste des articles contient le texte de l’article sélectionné. C’est une zone de texte en lecture seule : un lecteur d’écran peut la lire ligne par ligne, mot par mot ou caractère par caractère, et le texte peut être sélectionné et copié.

- Ctrl+F recherche dans le texte de l’article.
- F3 et Shift+F3 vont à la correspondance suivante et précédente.
- Enter sur un lien du texte ouvre ce lien.

La présentation du texte se règle dans Paramètres, Flux et articles : les titres peuvent être annoncés, les éléments de liste signalés par des puces et numéros, les citations signalées, les liens accompagnés de leur adresse, les tableaux décrits et le texte alternatif des images inclus. Le texte alternatif peut aussi être imposé ou désactivé pour un flux depuis son menu contextuel.

Si un flux ne publie qu’un court résumé, BlindRSS peut récupérer le texte intégral de l’article. Voir Récupération du texte intégral des articles.

## Fenêtre d’article {#article-window}

L’ouverture d’un article peut l’afficher dans une fenêtre distincte plutôt que dans le volet de lecture ; l’article occupe alors tout l’écran et reste ouvert pendant que vous avancez dans la liste.

La fenêtre est une zone de texte en lecture seule avec les mêmes fonctions de lecture, de sélection et de recherche que le volet de lecture. Escape la ferme.

## Champ de recherche {#search-field}

Le champ de recherche au-dessus de la liste des articles filtre la vue actuelle pendant la saisie, puis valide le terme avec Enter.

- Ctrl+E place le focus dans le champ de recherche.
- Enter applique le terme.
- Escape, ou le bouton Effacer, le vide et restaure la liste complète.

Le champ peut être masqué si vous ne l’utilisez jamais ; le menu Affichage contient la commande Afficher/Masquer le champ de recherche. Le choix entre la recherche dans les titres seuls ou dans les titres et le texte des articles se fait dans Paramètres, Flux et articles, sous « Correspondances de recherche ».

Une recherche à conserver peut devenir une recherche enregistrée qui reste dans l’arborescence. Voir Recherches persistantes.

## Barre d’état {#status-bar}

La barre d’état en bas de la fenêtre principale comporte trois champs :

- Des messages temporaires, par exemple le nombre d’articles correspondant à un filtre.
- L’activité en arrière-plan, par exemple l’actualisation d’un flux ou un téléchargement en cours.
- L’état de lecture : ce qui est lu, et le temps écoulé et restant.

Ils sont volontairement distincts afin qu’un message d’actualisation ne remplace pas un nombre de résultats de recherche pendant votre lecture.

## Menus contextuels {#context-menus}

L’arborescence des flux et la liste des articles ont chacune un menu contextuel, ouvert avec la touche Applications ou Shift+F10. Ils contiennent les commandes qui s’appliquent à la sélection : actualiser, marquer comme lu, modifier, supprimer, copier des liens, mettre des médias en file d’attente, etc.

Les menus contextuels prennent aussi en charge F1 : lorsqu’un élément est en surbrillance, F1 ouvre la section du guide qui l’explique.

## Ajout d’un flux {#adding-feeds}

Fichier, Ajouter un flux (Ctrl+N) permet de s’abonner à un flux par son adresse.

Collez ou saisissez l’adresse du flux, ou celle du site lui-même : lorsque l’adresse n’est pas un flux, BlindRSS en cherche un dans la page. Vous pouvez aussi coller l’adresse d’une chaîne ou liste de lecture YouTube, d’un profil Mastodon ou Bluesky, d’une communauté PieFed ou Lemmy, d’une page SoundCloud ou Mixcloud, ou d’une adresse Reddit ou Groups.io ; BlindRSS la transforme en flux.

Choisissez la catégorie du flux, ou laissez-le non catégorisé. L’option « Ouvrir dans la vue HTML » ouvre par défaut les articles de ce flux dans la vue enrichie.

Si vous ne connaissez pas l’adresse, utilisez plutôt Recherche de podcasts et de flux RSS.

## Détection de flux sur une page {#detect-feeds}

Fichier, Détecter les flux sur la page prend l’adresse d’une page web ordinaire et liste les flux que cette page annonce, afin de vous permettre de vous abonner sans chercher vous-même le lien du flux.

C’est la bonne commande lorsqu’un site possède un lien « s’abonner » ou « RSS » difficile à atteindre, ou lorsqu’une page propose plusieurs flux (tous les billets, une catégorie, les commentaires) et que vous voulez choisir.

## Recherche de podcasts et de flux RSS {#find-podcast}

Outils, Rechercher un podcast ou un flux RSS (Ctrl+Shift+F) recherche dans des annuaires de podcasts et de flux par nom, sujet ou adresse de site, pour vous permettre de vous abonner sans connaître d’adresse de flux.

1. Saisissez ce que vous cherchez dans le champ de recherche : nom de podcast, sujet ou adresse de site.
2. Choisissez une source, ou laissez « Toutes les sources ».
3. Appuyez sur Enter ou sur le bouton Rechercher.
4. Parcourez la liste des résultats avec les flèches. Chaque ligne affiche le titre, l’annuaire d’origine et des détails.
5. Appuyez sur Enter sur un résultat, ou choisissez OK, pour vous y abonner.

Les recherches interrogent plusieurs annuaires à la fois ; les résultats arrivent au fil des réponses et la liste grandit pendant votre lecture. Escape ferme la boîte de dialogue et arrête la recherche.

## Annuaires de podcasts et de flux {#podcast-directories}

La zone Source de Rechercher un podcast ou un flux RSS choisit où effectuer la recherche. Outre « Toutes les sources », « Toutes les sources de podcasts » et « Toutes les sources de flux RSS », les annuaires suivants peuvent être choisis individuellement :

- Annuaires de podcasts : iTunes (Apple Podcasts), gPodder, fyyd, Podverse, SoundCloud et Mixcloud.
- Annuaires de flux : NewsBlur, Feedspot, Google News, Bing News et Feedly.
- Recherche de sites et communautés : YouTube, Reddit, Groups.io et le Fédiverse — Mastodon, Bluesky, PieFed et Lemmy ou Kbin, chacun également sélectionnable seul.
- Découverte par adresse : Feedsearch et l’analyse de site de BlindRSS, qui récupère un site et y recherche des flux.

Aucun annuaire unique n’est utilisé seul. La recherche « Toutes les sources » interroge ensemble les groupes podcasts et RSS et fusionne les résultats, en plaçant les flux de requête généraux de Google News sous les correspondances de flux directes.

## Abonnement à un résultat de recherche {#subscribing}

Dans toutes les boîtes de dialogue de recherche — Rechercher un podcast ou un flux RSS, Recherche de vidéos ou le bouton Rechercher des Archives de podcasts — appuyer sur Enter sur un résultat, ou choisir OK lorsqu’il est sélectionné, vous y abonne.

BlindRSS résout d’abord le résultat vers une véritable adresse de flux ; l’abonnement à un podcast trouvé dans un annuaire, à une chaîne YouTube ou à un compte du Fédiverse fonctionne donc de la même manière. Le nouveau flux apparaît dans l’arborescence et est immédiatement actualisé.

Si vous le souhaitez dans une catégorie précise, déplacez-le ensuite depuis son menu contextuel ou depuis Propriétés du flux.

## Archives de podcasts {#podcast-archive}

Outils, Archives de podcasts permet de parcourir l’historique complet des épisodes d’un podcast — à la fois les épisodes toujours présents dans son flux et les plus anciens récupérés par BlindRSS — et de les télécharger par lots.

De nombreux flux de podcasts ne publient que les épisodes les plus récents. La récupération des archives s’exécute automatiquement en arrière-plan ; cette fenêtre permet d’en voir l’état, de la relancer manuellement et de télécharger ce qu’elle a trouvé.

- Choisissez le podcast dans la zone Podcast.
- Filtrer les épisodes réduit la liste à mesure que vous saisissez du texte.
- Réanalyser l’archive relance la récupération pour ce podcast.
- Rechercher ou ajouter un podcast ouvre la recherche de flux pour archiver un podcast auquel vous n’êtes pas encore abonné.
- Lire lit l’épisode sélectionné, Télécharger la sélection la télécharge, et Tout télécharger télécharge toute la liste visible.
- Annuler les téléchargements arrête un lot en cours.

La fenêtre reste ouverte pendant le téléchargement d’un lot afin que vous puissiez continuer à lire.

## Recherche de vidéos {#video-search}

Outils, Recherche de vidéos interroge simultanément chaque site que yt-dlp sait rechercher et vous permet de lire, mettre en file d’attente ou suivre ce qu’il trouve.

- Saisissez un terme et appuyez sur Enter ou sur le bouton Rechercher.
- La zone de portée limite la recherche à un site ; par défaut, tous sont recherchés.
- Les résultats arrivent au fil des réponses des sites, les sites grand public en premier. Les titres arrivant comme espaces réservés sont complétés lorsqu’ils sont résolus.
- Charger plus de résultats récupère un autre lot depuis chaque site.
- Le tri par en-tête de colonne réordonne les résultats déjà arrivés.

Les vidéos identiques trouvées sur plusieurs sites sont fusionnées en une ligne. Les sites pour adultes sont exclus, sauf si « Activer les sites pour adultes dans Recherche de vidéos » est activé dans Paramètres, Avancé.

## Ouverture d’un article par URL {#open-article-url}

Fichier, Ouvrir un article prend l’adresse de toute page web et la lit dans BlindRSS comme s’il s’agissait d’un article : texte extrait, dans le volet de lecture, avec les mêmes options de lecture que le reste.

Utilisez cette fonction pour une page ponctuelle qui vous a été envoyée, sans vous abonner à quoi que ce soit. Si la page est un forum ou un fil de discussion, BlindRSS lit le fil entier. Voir Forums et fils de discussion.

## Ouverture d’une URL de média {#open-media-url}

Fichier, Ouvrir une URL de média lit de l’audio ou de la vidéo depuis une adresse dans le lecteur intégré, sans abonnement.

Il accepte les liens directs vers des médias et les adresses de pages que yt-dlp peut résoudre — YouTube, Rumble, Odysee, SoundCloud et bien d’autres. Le résultat est lu comme n’importe quel autre élément et peut être ajouté à la file de lecture.

## Suppression d’un flux {#removing-feeds}

Fichier, Supprimer le flux désabonne du flux sélectionné. La même commande se trouve dans le menu contextuel du flux.

Supprimer un flux retire ses articles de la base de données. Cela ne touche à rien de ce que vous avez déjà téléchargé sur le disque. Avec un fournisseur hébergé, le désabonnement est également envoyé à ce compte.

Pour supprimer toute une catégorie et tout ce qu’elle contient, utilisez Supprimer la catégorie et les flux dans le menu contextuel de la catégorie. Voir Catégories et sous-catégories.

## Propriétés du flux {#feed-properties}

F2, ou Modifier le flux dans le menu contextuel, ouvre les propriétés du flux sélectionné.

- Son titre, que vous pouvez remplacer ; « Réinitialiser le titre au titre par défaut du flux » dans le menu contextuel rétablit le titre du flux.
- Son adresse et la catégorie à laquelle il appartient.
- Si ses nouveaux articles déclenchent une notification.
- S’il s’ouvre dans la vue HTML enrichie.
- Sa propre disposition de colonnes de liste, dans l’onglet En-têtes de liste, qui remplace la disposition globale.

Afficher la description du flux dans le menu contextuel de la liste d’articles montre la description publiée par le flux lui-même.

## Catégories et sous-catégories {#categories}

Les catégories regroupent les flux dans l’arborescence et peuvent être imbriquées : une catégorie peut contenir des flux et d’autres sous-catégories.

- Fichier, Ajouter une catégorie en crée une.
- Ajouter une sous-catégorie dans le menu contextuel d’une catégorie en crée une à l’intérieur.
- Modifier la catégorie la renomme ou la déplace. Voir Propriétés de la catégorie.
- Supprimer la catégorie supprime la catégorie mais conserve ses flux.
- Supprimer la catégorie et les flux supprime la catégorie et désabonne de tout ce qu’elle contient.
- Importer l’OPML ici importe un fichier directement dans cette catégorie.
- Exporter la catégorie au format OPML n’exporte que cette branche.

Certains fournisseurs hébergés conservent les catégories dans une liste plate. Dans ce cas, BlindRSS l’indique et les options « déplacer vers le parent » ne sont pas disponibles.

## Propriétés de la catégorie {#category-properties}

Modifier la catégorie ouvre ses propriétés : son nom et la catégorie parente dans laquelle elle se trouve.

Renommer une catégorie conserve tous ses flux. La déplacer déplace toute la branche, y compris ses sous-catégories.

## Actualisation des flux {#refreshing}

- F5 actualise chaque flux.
- Ctrl+F5 actualise seulement le flux ou la catégorie sélectionné.
- Shift+F5 arrête une actualisation en cours.
- Actualiser la catégorie dans le menu contextuel d’une catégorie actualise cette branche.

Une seule des commandes Actualiser les flux et Arrêter l’actualisation est disponible à la fois ; la commande clavier correspond donc à ce que propose le menu. La progression apparaît dans le deuxième champ de la barre d’état.

L’actualisation automatique se configure dans Paramètres, Flux et articles : l’intervalle, le nombre de flux actualisés à la fois, le nombre de connexions par hôte, le délai d’attente par flux et le nombre de tentatives pour un flux défaillant. « Actualiser automatiquement les flux au démarrage » actualise tout au lancement, et l’option de charge de démarrage choisit entre l’utilisation du cache et une actualisation complète forcée.

## Flux avec erreurs {#feed-errors}

La vue Flux avec erreurs et Fichier, Afficher les erreurs de flux répertorient les
flux dont la dernière mise à jour a échoué, avec la raison.

Un flux qui cesse discrètement de fonctionner ressemble exactement à un flux sans
nouvel article, d’où l’existence de cette vue. Depuis celle-ci, vous pouvez :

- Actualiser la sélection, pour réessayer maintenant.
- Copier les détails, pour placer le texte de l’erreur dans le presse-papiers.
- Propriétés du flux, pour corriger l’adresse.
- Supprimer le flux, lorsqu’il a définitivement disparu.

Les causes courantes sont un flux déplacé ou retiré, un site qui exige désormais
une vérification dans le navigateur (voir Importation de cookies de sites), ou
une indisponibilité temporaire du serveur.

## Importation d’OPML {#import-opml}

OPML est le format de fichier standard pour une liste d’abonnements à des flux.
Tout lecteur de flux peut en exporter un ; c’est donc avec OPML que vous déplacez
vos abonnements depuis un autre lecteur vers BlindRSS sans les ajouter un par un.

Fichier, Importer un OPML demande le fichier et ajoute tous les flux qu’il
contient, en conservant la structure de catégories qu’il décrit. Les flux
auxquels vous êtes déjà abonné ne sont pas dupliqués.

Importer l’OPML ici, dans le menu contextuel d’une catégorie, place toute
l’importation dans cette catégorie plutôt qu’au niveau supérieur.

Pour obtenir un fichier OPML depuis un autre lecteur, cherchez « Exporter »,
« Sauvegarde » ou « Abonnements » dans ses paramètres.

## Exportation d’OPML {#export-opml}

Fichier, Exporter l’OPML écrit tous vos abonnements, avec leurs catégories, dans
un fichier OPML.

Utilisez-le pour sauvegarder vos abonnements, les déplacer vers un autre lecteur
ou ordinateur, ou partager une sélection de flux avec quelqu’un. Exporter la
catégorie au format OPML, dans le menu contextuel d’une catégorie, n’exporte que
cette branche.

## Importation d’une archive YouTube Takeout {#import-youtube-takeout}

Google Takeout est le service d’exportation de données de Google. Une archive
YouTube Takeout est un fichier ZIP contenant vos données YouTube, y compris la
liste des chaînes auxquelles vous êtes abonné. Fichier, Importer YouTube Takeout
lit ce ZIP et vous abonne à ces chaînes sous forme de flux, de sorte que les
nouvelles vidéos de chaque chaîne arrivent comme articles.

Pour obtenir l’archive :

1. Allez sur takeout.google.com et connectez-vous avec le compte Google où se
   trouvent vos abonnements YouTube.
2. Choisissez « Tout désélectionner », puis ne sélectionnez que YouTube et
   YouTube Music.
3. Dans « Toutes les données YouTube incluses », conservez au minimum
   « abonnements » ; « historique » et « playlists » sont facultatifs, mais
   BlindRSS peut aussi les utiliser.
4. Exportez une fois sous forme de fichier ZIP et attendez l’e-mail de Google —
   une archive volumineuse peut demander plusieurs heures.
5. Téléchargez le ZIP et indiquez-le à cette commande.

BlindRSS affiche ensuite ce qu’il a trouvé, regroupé par source, et vous laisse
choisir les groupes à importer :

- Abonnements : les chaînes que vous suivez.
- Historique : les chaînes que vous avez regardées mais ne suivez pas.
- Vos propres chaînes.
- Playlists, comme flux à part entière.

Les adresses en double sont supprimées ; importer une seconde archive plus tard
n’ajoute donc que les nouveautés. Le ZIP n’est jamais décompressé sur le disque :
seuls les petits fichiers de données qu’il contient sont lus.

## Recherches persistantes {#persistent-search}

Une recherche persistante est un terme de recherche qui reste dans
l’arborescence comme son propre élément ; les articles qui y correspondent sont
ainsi toujours à une pression de flèche.

Outils, Configurer la recherche persistante gère la liste : Ajouter en crée une
à partir d’un terme, Supprimer l’efface. Chaque recherche enregistrée apparaît
dans l’arborescence et est réévaluée chaque fois que vous la sélectionnez ; elle
reflète donc toujours les articles actuels.

Utilisez-la pour un sujet que vous suivez dans tous les flux — le nom d’une
personne, un produit, un lieu. Pour tout ce qui est plus structuré qu’une phrase,
utilisez les dossiers intelligents.

## Dossiers intelligents {#smart-folders}

Un dossier intelligent est un dossier de l’arborescence dont le contenu est
défini par une règle plutôt que par le flux dont provient un article.

Nouveau dossier intelligent, dans le menu contextuel de l’arborescence, ouvre
l’éditeur de règles. Une règle est un ensemble de conditions reliées par
« toutes correspondent » (et) ou « une correspond » (ou) ; des groupes de
conditions peuvent être imbriqués, donc « (A et B) ou C » peut s’exprimer.

Les conditions testent les champs suivants :

- Champs oui/non : lu, favori, ouvert, mis à jour.
- Champs de texte : titre, contenu, description, auteur, flux, url et tag — les
  catégories ou étiquettes que le site lui-même publie.

Les conditions de texte utilisent contient, ne contient pas, est égal à ou
commence par.

Les dossiers intelligents ne déplacent ni ne copient jamais rien ; ils offrent
une vue des articles que vous possédez déjà. Pour modifier les articles à leur
arrivée, utilisez les règles de filtrage.

## Règles de filtrage {#filter-rules}

Outils, Règles de filtrage est le moteur de tri d’articles de BlindRSS. Les
règles s’appliquent aux articles entrants comme les filtres de messagerie au
courrier entrant.

Chaque règle associe une condition — le même éditeur de règles que les dossiers
intelligents utilisent — à un ensemble d’actions :

- Déplacer l’article vers une catégorie.
- Lui attribuer aussi une catégorie, sans le déplacer.
- Le marquer comme lu.
- Le marquer comme favori.
- Le supprimer, selon votre comportement de suppression configuré.
- Ignorer sa notification de nouvel article.

Les règles s’exécutent dans l’ordre de la liste, et chaque règle activée qui
correspond apporte ses actions. Une règle marquée pour s’arrêter termine le
pipeline pour cet article dès qu’elle correspond ; les règles suivantes ne le
voient donc jamais. Déplacez les règles vers le haut ou le bas pour déterminer
laquelle l’emporte.

Une règle sans action ne fait rien et est refusée, afin qu’une règle inachevée ne
puisse pas engloutir silencieusement des articles.

## Filtre d’articles {#article-filter}

Affichage, Filtre d’articles limite chaque vue par état de lecture et selon qu’un
article a un média joint. Les deux groupes se combinent.

- Ctrl+1 : tous les articles.
- Ctrl+2 : non lus uniquement.
- Ctrl+3 : lus uniquement.
- Ctrl+4 : avec et sans média.
- Ctrl+5 : avec média uniquement.
- Ctrl+6 : sans média uniquement.

Le filtre s’applique à tout élément sélectionné dans l’arborescence, y compris
aux dossiers intelligents et recherches enregistrées, et persiste entre les
lancements. « Avec média uniquement » est le moyen le plus rapide de transformer
un flux mixte en liste de podcasts.

## Tri des articles {#sorting}

Affichage, Trier par ordonne la liste des articles par date, nom, auteur,
description, flux ou état. Croissant bascule le sens ; le plus récent en premier
est l’option par défaut.

Le tri s’applique à toutes les vues et est mémorisé entre les lancements. Trier
par flux est utile dans Tous les flux et les dossiers intelligents, où les
articles viennent de nombreuses sources à la fois.

## Colonnes de la liste des articles {#list-headers}

Vous choisissez les colonnes de la liste d’articles, leur ordre et leur largeur.
Paramètres, En-têtes de liste règle la disposition globale ; l’onglet En-têtes
de liste d’un flux la remplace pour ce flux, et « Utiliser la disposition globale
des colonnes » désactive de nouveau ce remplacement.

Moins de colonnes signifie moins de contenu à lire par un lecteur d’écran sur
chaque ligne ; il vaut donc la peine de retirer celles que vous n’utilisez jamais.

## Ouverture des articles {#opening-articles}

Enter sur un article de la liste l’ouvre. Selon l’article et vos paramètres,
cela signifie le volet de lecture, une fenêtre distincte ou la vue HTML enrichie.

- Ouvrir l’article dans le menu contextuel fait la même chose.
- Ouvrir dans le navigateur transmet l’adresse de l’article à votre navigateur
  web système.
- Ouvrir le navigateur accessible lit plutôt la page dans BlindRSS. Voir
  Navigateur accessible.

Ouvrir un article le marque comme lu, sauf si vous avez modifié ce comportement.

## Articles lus et non lus {#read-status}

- Backspace, ou Basculer lu/non lu, inverse l’état de l’article sélectionné.
- Ctrl+Shift+R marque comme lus tous les éléments de la vue actuelle.
- Marquer tous les éléments comme lus, dans le menu contextuel d’un flux ou
  d’une catégorie, fait la même chose pour cette branche.
- Marquer comme lu et Marquer comme non lu, dans le menu contextuel de la liste
  d’articles, agissent sur toute la sélection et indiquent combien d’articles
  ils affecteront.

Le nombre de non lus apparaît à côté de chaque flux dans l’arborescence. Le
filtre d’articles peut masquer complètement les articles lus.

## Favoris {#favorites}

Ctrl+D ajoute l’article sélectionné aux Favoris ou le retire s’il y est déjà. La
vue Favoris de l’arborescence affiche tout ce que vous avez marqué.

Les favoris survivent à la politique de rétention : un article que vous avez mis
en favori n’est pas supprimé lors du nettoyage des anciens articles. Favori peut
aussi servir de condition dans les dossiers intelligents et les règles de
filtrage.

## Articles supprimés {#deleted-articles}

Le comportement de Delete se configure dans Paramètres, Général, sous « Lorsque
je supprime un article » :

- Le déplacer vers Articles supprimés, où il peut être restauré.
- Le supprimer définitivement.
- Le déplacer vers une catégorie que vous indiquez.

Avec le premier réglage, la vue Articles supprimés de l’arborescence liste ce que
vous avez retiré, Restaurer remet un article en place et le supprimer depuis
cette vue le retire définitivement.

« Confirmer avant de supprimer des articles » contrôle l’invite de confirmation.
Shift+Delete l’ignore toujours.

## Récupération du texte intégral des articles {#full-text}

De nombreux flux ne publient qu’un titre et une ou deux phrases. BlindRSS peut
récupérer la page de l’article et en extraire le texte réel, afin que le volet de
lecture affiche l’article complet plutôt qu’un aperçu.

Cela se produit automatiquement lorsque vous parcourez la liste, en arrière-plan,
et le résultat est mis en cache. « Mettre en cache le texte intégral en
arrière-plan » dans Paramètres, Flux et articles précharge les articles autour de
votre position afin que descendre dans la liste n’attende pas le réseau.

Lorsqu’un site refuse toute lecture, il est généralement protégé par une
vérification du navigateur. Voir Importation de cookies de sites.

## Vue enrichie de texte intégral {#rich-view}

Ctrl+Shift+H bascule le volet de lecture vers la vue HTML enrichie, qui affiche
l’article comme le ferait un navigateur, avec les titres, listes, tableaux et
liens sous forme d’éléments réels qu’un lecteur d’écran peut parcourir avec ses
propres commandes structurelles.

La vue en texte brut est celle par défaut parce qu’elle est plus rapide et ne
vous surprend jamais. La vue enrichie vaut la peine pour les articles dont la
structure porte du sens.

Un flux peut être configuré pour s’ouvrir toujours dans la vue enrichie depuis
ses propriétés, et les liens de la vue enrichie s’ouvrent dans votre navigateur
système plutôt qu’à l’intérieur de la vue.

## Navigateur accessible {#accessible-browser}

Affichage, Ouvrir le navigateur accessible ouvre une page dans BlindRSS, dans
une fenêtre conçue pour la lecture avec un lecteur d’écran, plutôt que de la
transmettre à votre navigateur système.

C’est l’outil approprié pour une page à lire plutôt qu’à utiliser de manière
interactive, et pour les sites dont l’interface est difficile à parcourir. Il
partage les paramètres de cookies et d’identité de navigateur de BlindRSS ; les
pages derrière une vérification de navigateur s’y ouvrent donc elles aussi une
fois leurs cookies importés.

## Vidéos YouTube {#youtube}

Vous pouvez vous abonner à l’adresse d’une chaîne ou d’une playlist YouTube comme
à n’importe quel flux. Ses vidéos arrivent alors comme articles, avec la
description, la transcription et la liste des chapitres en ligne, de sorte qu’une
vidéo peut être lue plutôt que regardée.

La lecture passe par yt-dlp. Paramètres, YouTube la contrôle :

- Un fichier de cookies, qui permet à BlindRSS d’accéder aux vidéos soumises à
  une limite d’âge et réservées aux membres auxquelles vous avez accès. Il peut
  être importé directement depuis un navigateur, ou détecté automatiquement
  parmi les exports cookies.txt de votre dossier Téléchargements.
- « Lire YouTube en téléchargeant d’abord », une option plus lente à démarrer et
  beaucoup plus fiable.
- Le dossier du cache de lecture et sa taille maximale, avec un bouton pour le
  vider.

Importer YouTube Takeout vous abonne à toutes les chaînes que vous suivez déjà,
en une seule étape.

## Forums et fils de discussion {#forums}

Reddit, Lemmy, Groups.io et Google Groups sont lus comme des fils entiers plutôt
que comme un message à la fois : ouvrir une discussion fournit le message
d’origine et les réponses dans un seul texte continu, bien plus rapide à lire
que de suivre un fil dans un navigateur.

L’abonnement fonctionne comme pour n’importe quel flux — collez l’adresse du
subreddit, de la communauté ou du groupe. Les dépôts GitHub sont pris en charge
de la même façon, ainsi que les comptes et communautés Mastodon, Bluesky et
PieFed.

## Couper, copier et coller {#clipboard}

Le menu Édition contient les commandes standard du presse-papiers — Couper
(Ctrl+X), Copier (Ctrl+C), Coller (Ctrl+V) et Sélectionner tout (Ctrl+A) — et
elles fonctionnent dans tous les champs de texte et dans le volet de lecture.

BlindRSS ajoute des commandes qui copient les éléments qu’il connaît :

- Copier le lien, l’adresse de l’article.
- Copier le lien du média, l’adresse de son audio ou de sa vidéo.
- Copier le texte, le texte de l’article tel qu’il est lu dans le volet de
  lecture.
- Copier l’URL du flux, l’adresse du flux sélectionné.
- Copier le lien de l’image, sur un article qui comporte une image.

## Lecteur intégré {#player}

BlindRSS lit lui-même les fichiers joints de podcast et de vidéo, par VLC ; la
lecture ne quitte donc jamais l’application. Ctrl+Shift+P affiche ou masque la
fenêtre du lecteur, et la lecture continue dans les deux cas.

La lecture est fluidifiée par un proxy local de cache par plages ; c’est pourquoi
se déplacer dans un épisode long reste rapide même sur une connexion lente. Les
flux à résoudre — YouTube, Rumble, Odysee — passent d’abord par yt-dlp.

« Afficher la fenêtre du lecteur au démarrage de la lecture » dans Paramètres,
Lecteur multimédia décide si la fenêtre apparaît d’elle-même au début d’un
élément.

## Commandes du lecteur {#player-controls}

La fenêtre du lecteur contient, dans l’ordre de tabulation : l’état de lecture,
le curseur de position, le temps écoulé et total, les boutons de retour et
d’avance rapide, la zone de vitesse, le bouton des chapitres et le curseur de
volume. Chacun est accessible et utilisable au clavier, et annonce sa valeur
actuelle.

- Ctrl+P lit et met en pause.
- Ctrl+S arrête.
- Ctrl+Left et Ctrl+Right reculent et avancent rapidement, et se répètent tant
  qu’ils sont maintenus. Sur macOS, Option+Left et Option+Right font de même,
  parce que Ctrl+Left et Ctrl+Right appartiennent alors à Mission Control.
- Ctrl+Up et Ctrl+Down modifient le volume.

Les touches de déplacement et de volume fonctionnent depuis n’importe où dans
BlindRSS pendant une lecture, y compris dans une boîte de dialogue : vous n’avez
donc jamais à retrouver la fenêtre du lecteur pour mettre en pause.

## Raccourcis clavier du lecteur {#player-shortcuts}

- Ctrl+Shift+P : afficher ou masquer la fenêtre du lecteur.
- Ctrl+P : lire ou mettre en pause.
- Ctrl+S : arrêter.
- Ctrl+Left et Ctrl+Right : reculer et avancer rapidement (Option+Left et
  Option+Right sous macOS).
- Ctrl+Up et Ctrl+Down : augmenter et diminuer le volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N : accélérer, ralentir, revenir à la
  vitesse normale.
- Ctrl+Shift+E : l’égaliseur.
- Ctrl+Shift+C : la file de lecture.
- Ctrl+Shift+T et Ctrl+Shift+V : élément suivant et précédent de la file.

Tous ces raccourcis sont reconfigurables dans Outils, Raccourcis clavier. Les
commandes de vitesse utilisent délibérément par défaut des lettres plutôt que
Ctrl+Shift+digit ou Ctrl+Shift+period, car Windows et certains modules NVDA
prennent ces derniers avant qu’une application ne les reçoive.

## Vitesse de lecture {#playback-speed}

Lecteur, Vitesse de lecture change la vitesse de lecture des médias, d’une
demi-vitesse à une vitesse triple, tout en conservant la hauteur du son.

- Ctrl+Shift+U accélère, Ctrl+Shift+D ralentit, Ctrl+Shift+N revient à 1x.
- Le sous-menu offre des paliers fixes : 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x,
  2.5x et 3x.
- La fenêtre du lecteur possède une zone de vitesse que vous pouvez régler
  directement.

« Vitesse de lecture par défaut » dans Paramètres, Lecteur multimédia définit la
vitesse à laquelle tout commence.

## Égaliseur {#equalizer}

Ctrl+Shift+E, ou Lecteur, Égaliseur, ouvre un égaliseur à dix bandes avec
préamplification.

- « Activer l’égaliseur » active et désactive l’ensemble.
- Chaque bande est un curseur qui annonce son gain à mesure que vous le
  modifiez.
- Enregistrer comme préréglage enregistre les bandes actuelles sous un nom ;
  Supprimer le préréglage en efface un.
- Réinitialiser (plat) ramène chaque bande à zéro.

L’égaliseur s’applique à tout ce que BlindRSS lit et son réglage est mémorisé.

## Chapitres {#chapters}

Les podcasts et vidéos YouTube comportent souvent des chapitres. Lorsque
l’élément en lecture en a, Lecteur, Chapitres les liste et passer à l’un d’eux
place la lecture à cet endroit.

- Le sous-menu des chapitres se remplit une fois les chapitres de l’élément
  connus et indique « Aucun chapitre disponible » lorsqu’il n’y en a pas.
- La fenêtre du lecteur possède un bouton Chapitres et une zone Chapitres.
- Liens de chapitre, dans le menu contextuel de la liste d’articles, liste les
  liens contenus dans la description d’un chapitre.

Les chapitres se chargent en arrière-plan lorsque vous parcourez la liste ; ils
sont donc généralement prêts avant que vous appuyiez sur lecture.

## File de lecture {#play-queue}

La file de lecture est la liste des éléments lus ensuite.

- Ctrl+Shift+C ouvre la fenêtre de file.
- Ctrl+Shift+T et Ctrl+Shift+V lisent l’élément suivant et précédent.
- Ajouter à la file de lecture et Retirer de la file de lecture, dans le menu
  contextuel de la liste d’articles, la modifient.

Dans la fenêtre de file, Lire démarre l’élément sélectionné, Monter et Descendre
réorganisent la file, Retirer ôte un élément et Tout effacer vide la file. La
file survit aux redémarrages.

## Diffusion vers d’autres appareils {#casting}

BlindRSS peut envoyer ce qu’il lit vers un appareil de votre réseau : Chromecast,
lecteurs DLNA/UPnP et récepteurs AirPlay.

Choisissez l’appareil dans la boîte de dialogue de diffusion ; BlindRSS transmet
le flux par son propre proxy local, de sorte qu’un appareil incapable de récupérer
lui-même l’adresse d’origine lit tout de même l’élément. Les commandes de
transport continuent de fonctionner depuis BlindRSS pendant la diffusion.

## Ignorer les silences {#silence-skipping}

« Ignorer les silences (expérimental) » dans Paramètres, Lecteur multimédia
détecte les passages silencieux pendant la lecture et les saute, ce qui raccourcit
sensiblement les podcasts parlés comportant de longues pauses.

Il analyse l’audio pendant la lecture, ce qui consomme un peu de processeur ; il
est donc marqué expérimental. Désactivez-le si la lecture n’est pas fluide.

## Téléchargement de médias {#downloads}

- Télécharger enregistre l’audio ou la vidéo de l’article sélectionné dans son
  format par défaut.
- Télécharger sous permet d’abord de choisir le format.

Les téléchargements doivent être activés avec « Activer les téléchargements »
dans Paramètres. Le dossier de téléchargement, la politique de rétention et le
format vidéo de téléchargement par défaut se règlent sur la même page ; le dossier
par défaut est celui des Téléchargements de votre système.

La progression apparaît dans le deuxième champ de la barre d’état et les
éléments téléchargés sont ensuite lus depuis le disque plutôt que par le réseau.
Les Archives de podcasts peuvent télécharger en un lot tout le catalogue passé
d’un podcast.

## Paramètres {#settings}

Outils, Paramètres (Ctrl+comma) contient toutes les options, dans les onglets :
Général, Flux et articles, YouTube, Lecteur multimédia, Fournisseur,
Notifications, Traduire, En-têtes de liste, Avancé et Résolution de CAPTCHA.

Ctrl+Tab et Ctrl+Shift+Tab passent d’un onglet à l’autre ; Tab parcourt les
contrôles de l’onglet actuel. OK applique tout, Annuler rejette tout. Les
positions des onglets restent stables entre les versions, car elles deviennent
une mémoire musculaire.

Appuyer sur F1 dans un onglet ouvre la section correspondante de ce guide.

## Paramètres : Général {#settings-general}

- Langue d’interface, et choix de laisser BlindRSS suivre la langue du système.
  Une modification prend effet au redémarrage. Voir Langue de l’interface.
- « Mémoriser le dernier flux/dossier sélectionné au démarrage ».
- « Confirmer avant de supprimer des articles », et ce que fait la suppression —
  déplacer vers Articles supprimés, supprimer définitivement ou déplacer vers
  une catégorie que vous indiquez.
- « Mode débogage (afficher la console au démarrage) », qui écrit également un
  fichier blindrss.log rotatif à côté de vos données.
- Démarrage et zone de notification : fermer dans la zone de notification,
  réduire dans cette zone, y démarrer, toujours démarrer maximisé et vérifier les
  mises à jour au démarrage.

## Paramètres : Flux et articles {#settings-feeds}

- L’intervalle d’actualisation automatique, de cinq minutes à quatre heures.
- Le choix entre chercher dans les titres seuls ou dans les titres et le texte.
- Le maximum d’actualisations simultanées, de connexions par hôte, le délai
  d’attente des flux et le nombre de tentatives d’un flux défaillant.
- Le maximum de vues mises en cache et « Mettre en cache le texte intégral en
  arrière-plan ».
- « Actualiser automatiquement les flux au démarrage » et la charge
  d’actualisation initiale : utiliser le cache, actualiser entièrement au
  démarrage ou toujours actualiser entièrement.
- La rétention des articles, qui décide combien de temps ils sont conservés. Les
  favoris ne sont jamais supprimés par la rétention.
- La présentation du texte : annoncer les titres, marquer les éléments de liste
  par des puces et numéros, marquer les citations, afficher les liens avec leur
  adresse, décrire les tableaux et inclure le texte alternatif des images.

## Paramètres : YouTube {#settings-youtube}

- Le fichier de cookies yt-dlp, avec un bouton Parcourir, un bouton « Importer
  depuis le navigateur » et une option pour détecter automatiquement les exports
  cookies.txt de votre dossier Téléchargements.
- La lecture directe des cookies d’un navigateur installé.
- « Lire YouTube en téléchargeant d’abord », qui démarre plus lentement mais est
  l’option la plus fiable.
- Le dossier de cache de lecture YouTube, sa taille maximale en mégaoctets et un
  bouton pour le vider maintenant.

Les cookies permettent de lire les vidéos soumises à une limite d’âge et réservées
aux membres ; c’est aussi ce que demande l’erreur « connectez-vous pour confirmer
que vous n’êtes pas un robot ».

## Paramètres : Lecteur multimédia {#settings-media-player}

- La carte son préférée ou celle du système par défaut.
- « Ignorer les silences (expérimental) ». Voir Ignorer les silences.
- La vitesse de lecture par défaut.
- « Afficher la fenêtre du lecteur au démarrage de la lecture ».
- La taille du cache réseau en millisecondes, qui arbitre entre délai initial et
  résilience sur une connexion lente.
- Les chemins vers ffmpeg, ffprobe et yt-dlp. Laissez un champ vide pour une
  détection automatique ; un chemin défini remplace la détection et ce qui a été
  détecté est affiché à côté de chacun.
- Téléchargements : activation, dossier de téléchargement, politique de
  rétention et format vidéo de téléchargement par défaut.
- Sons : le choix que BlindRSS joue ses sons de notification.

## Paramètres : Fournisseur {#settings-provider}

Détermine l’endroit où résident vos abonnements : localement dans BlindRSS ou
dans un compte hébergé. Voir Comptes en ligne et fournisseurs pour les éléments
nécessaires à chacun.

La page affiche le fournisseur actif et ses identifiants — adresse et clé API
Miniflux, identifiant et clé d’application Inoreader avec un bouton Autoriser,
ou adresse e-mail et mot de passe pour The Old Reader ou BazQux. Effacer
l’autorisation déconnecte un compte Inoreader.

Le fournisseur local utilise les flux que vous ajoutez dans l’application avec
Ajouter un flux et Importer l’OPML.

## Paramètres : Notifications {#settings-notifications}

- « Activer les notifications pour les nouveaux articles », et le choix
  d’inclure le nom du flux dans le texte de notification.
- Le maximum de notifications par actualisation, et le choix d’afficher une
  notification récapitulative une fois cette limite atteinte.
- Tester la notification en envoie une maintenant.
- Exclure des flux choisit les flux qui ne notifient jamais.
- Annonces : les événements que BlindRSS prononce directement au lecteur d’écran,
  événement par événement, avec un bouton Tester l’annonce qui envoie un test à
  la fois vers la parole et le braille.

## Paramètres : Traduire {#settings-translate}

Active la traduction automatique du contenu des articles et choisit le service
qui s’en charge.

- « Activer la traduction automatique du contenu des articles ».
- Le fournisseur : Grok (xAI), Groq, OpenAI, OpenRouter, Gemini ou Qwen.
- La langue cible, choisie dans la liste ou saisie comme code tel que en, es,
  fr ou pt-BR.
- Une clé API pour le fournisseur choisi et, facultativement, un modèle précis.
  Pour OpenRouter, « Charger les modèles OpenRouter » récupère la liste des
  modèles disponibles.

Grok et Groq sont des services distincts aux noms trompeusement proches : Grok
est celui de xAI, avec des clés de console.x.ai qui commencent par « xai- » ;
Groq héberge LLaMA et Mistral, avec des clés gratuites de console.groq.com qui
commencent par « gsk_ ».

Cela traduit le texte des articles. Pour changer la langue de l’interface de
BlindRSS elle-même, voir Langue de l’interface.

## Paramètres : En-têtes de liste {#settings-list-headers}

Définit la disposition globale des colonnes de la liste d’articles : les
colonnes affichées, leur ordre et leur largeur. Voir Colonnes de la liste des
articles.

Un flux individuel peut remplacer ce réglage depuis ses propres Propriétés du
flux.

## Paramètres : Avancé {#settings-advanced}

- Emplacement de stockage des données : conservez votre base de données et vos
  paramètres dans le dossier de données utilisateur ou dans le dossier de
  l’application, les deux chemins étant affichés. L’option de dossier
  d’application est ce qui rend une installation portable réellement portable.
- Mises à jour : « Installer automatiquement les mises à jour sans confirmation ».
- Identification du navigateur : le navigateur que BlindRSS prétend être lors de
  la récupération des flux, ou une chaîne User-Agent personnalisée que vous
  saisissez. La chaîne effective est affichée dessous. Cela importe pour les
  sites qui bloquent les clients inconnus.
- Recherche de vidéos : « Activer les sites pour adultes dans Recherche de
  vidéos », désactivé par défaut.

## Paramètres : Résolution de CAPTCHA {#settings-captcha}

Une voie de dernier recours, payante et facultative, pour les sites qui répondent
par un CAPTCHA que les cookies importés ne permettent pas de franchir.

« Activer le service de résolution de CAPTCHA » l’active, et le champ de clé API
contient la clé de votre compte auprès du service de résolution. Des frais
s’appliquent à chaque résolution ; c’est pourquoi cette fonction est désactivée
par défaut et tentée uniquement après l’échec de tout le reste.

Essayez d’abord Importation de cookies de sites : c’est gratuit et cela résout la
plupart des cas.

## Comptes en ligne et fournisseurs {#providers}

BlindRSS peut conserver lui-même vos abonnements ou les lire depuis un compte
hébergé. Paramètres, Fournisseur choisit lequel.

- Local : les abonnements résident dans la base de données de BlindRSS sur cette
  machine. Rien n’est synchronisé ailleurs.
- Miniflux : nécessite l’adresse de votre serveur Miniflux et une clé API dans
  les paramètres de votre compte Miniflux.
- Inoreader : nécessite un identifiant et une clé d’application de la page
  développeur Inoreader, puis le bouton Autoriser pour se connecter.
- The Old Reader : nécessite l’adresse e-mail et le mot de passe de votre compte.
- BazQux : nécessite l’adresse e-mail et le mot de passe de votre compte.

Avec un fournisseur hébergé, l’état de lecture, les abonnements et les catégories
sont ceux du compte : ils vous suivent donc sur tout autre appareil connecté au
même compte. Certains fournisseurs conservent les catégories dans une seule liste
plate ; BlindRSS le signale plutôt que de proposer une imbrication qui ne
persisterait pas.

## Notifications {#notifications}

BlindRSS affiche une notification système à l’arrivée de nouveaux articles,
conformément à Paramètres, Notifications.

- Les notifications peuvent être entièrement désactivées.
- Le nom du flux peut être inclus dans le texte.
- Une limite restreint leur nombre par actualisation, avec une notification
  récapitulative facultative une fois la limite atteinte.
- Les flux individuels peuvent être exclus, soit par Exclure des flux dans les
  paramètres, soit par « Notifications pour ce flux » dans le menu contextuel
  du flux.
- Une règle de filtrage peut supprimer la notification des articles auxquels
  elle correspond.

Séparément, les annonces prononcent les événements choisis directement dans votre
lecteur d’écran par l’interface propre à NVDA ou JAWS, et en braille, ce qui passe
même lorsqu’une notification système ne passe pas.

## Traduction des articles {#translation}

Lorsque la traduction est activée dans Paramètres, Traduire, le texte des articles
est traduit dans votre langue cible pendant que vous le lisez, avec le service IA
que vous avez configuré.

La traduction se produit à la demande et est mise en cache ; relire un article ne
la paie donc pas deux fois. Elle nécessite une connexion Internet et votre propre
clé API auprès du service choisi.

L’interface de l’application est traduite séparément, par ses propres catalogues.
Voir Langue de l’interface.

## Importation de cookies de sites {#site-cookies}

Certains sites placent une page de vérification de navigateur — généralement une
épreuve Cloudflare « vérification de votre navigateur » — devant leur contenu.
Ces sites ne répondent qu’à une session ayant déjà franchi l’épreuve dans un vrai
navigateur ; BlindRSS ne peut donc pas les récupérer seul.

Outils, Importer les cookies de sites lui fournit cette session :

1. Ouvrez le site dans votre navigateur web et attendez la fin de son chargement.
2. Exportez ses cookies vers un fichier cookies.txt avec une extension de
   navigateur cookies.txt. Pour les navigateurs basés sur Chrome, la boîte de
   dialogue renvoie vers « Get cookies.txt LOCALLY ».
3. Choisissez le fichier exporté dans la boîte de dialogue.
4. Collez la chaîne User-Agent de votre navigateur dans le champ ci-dessous.
   Une recherche web pour « quel est mon user agent » l’affiche. Cloudflare exige
   exactement le User-Agent auquel le cookie a été délivré ; c’est donc important.

Les navigateurs de la famille Firefox offrent un chemin en un clic : « Importer
depuis le navigateur » lit directement leur base de cookies. Les navigateurs
basés sur Chromium chiffrent les leurs, d’où l’extension nécessaire.

## Raccourcis clavier {#keyboard-shortcuts}

Outils, Raccourcis clavier répertorie chaque commande de BlindRSS, groupée par
catégorie avec sa touche actuelle, et permet de toutes les modifier.

- Sélectionnez une commande et choisissez Modifier le raccourci. La boîte de
  capture enregistre alors la combinaison de touches suivante que vous pressez.
- Retirer le raccourci laisse une commande sans touche ; elle fonctionne toujours
  depuis son menu.
- Tout réinitialiser aux valeurs par défaut restaure les touches fournies.

Les raccourcis sont distribués avant les accélérateurs de menu et fonctionnent
dans toute la fenêtre, y compris lorsque la fenêtre du lecteur a le focus ; le
chemin clavier s’annonce là où le chemin de menu reste silencieux. Vos changements
sont enregistrés avec vos paramètres et survivent aux mises à jour.

## Raccourcis clavier par défaut {#shortcuts-reference}

Flux :

- Ctrl+N : Ajouter un flux.
- F5 : Actualiser les flux. Shift+F5 : Arrêter l’actualisation. Ctrl+F5 :
  actualiser le flux sélectionné.
- F2 : Modifier le flux ou la catégorie.
- Ctrl+Shift+R : Marquer tous les éléments comme lus.
- Ctrl+Shift+F : Rechercher un podcast ou un flux RSS.

Articles et vues :

- Ctrl+D : ajouter aux Favoris ou retirer des Favoris.
- Backspace : basculer lu et non lu. Delete : supprimer. Shift+Delete :
  supprimer sans confirmation.
- Ctrl+E : placer le focus dans le champ de recherche.
- Ctrl+Shift+H : vue enrichie de texte intégral.
- Ctrl+1 à Ctrl+3 : tous, non lus, lus. Ctrl+4 à Ctrl+6 : avec et sans média,
  avec média, sans média.

Lecteur :

- Ctrl+P : lire ou mettre en pause. Ctrl+S : arrêter. Ctrl+Shift+P : afficher ou
  masquer le lecteur.
- Ctrl+Left et Ctrl+Right : se déplacer. Ctrl+Up et Ctrl+Down : volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N : accélérer, ralentir, normal.
- Ctrl+Shift+E : égaliseur.
- Ctrl+Shift+C : file de lecture. Ctrl+Shift+T et Ctrl+Shift+V : suivant et
  précédent.

Application :

- F1 : ce guide, ouvert à la section correspondant à ce que vous utilisez.
- Ctrl+comma : Paramètres.
- Ctrl+Shift+A : annoncer la version en cours.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A : couper, copier, coller, sélectionner tout.

Les commandes non listées ici sont fournies sans touche associée et peuvent
recevoir n’importe quelle touche dans Outils, Raccourcis clavier.

## Langue de l’interface {#language}

L’interface de BlindRSS est traduite en quinze langues. Paramètres, Général en
choisit une ou la laisse suivre la langue de votre système. La modification prend
effet au redémarrage.

Les traductions sont fournies entre les versions de l’application aussi bien
qu’avec elles ; une traduction corrigée vous parvient donc sans attendre une
nouvelle version.

Ce guide suit la même langue lorsqu’une traduction du guide existe, et revient à
l’anglais dans le cas contraire.

## Icône de zone de notification et touches multimédia {#tray}

BlindRSS peut résider dans la zone de notification système. Paramètres, Général
décide si fermer la fenêtre l’y envoie, si la réduire fait de même et s’il y
démarre.

L’icône de zone de notification possède des commandes de lecture et rouvre la
fenêtre principale. Les touches multimédia de votre clavier — lecture/pause,
arrêt, suivant, précédent — contrôlent le lecteur BlindRSS dans tout le système.

## Ajout de raccourcis de bureau {#desktop-shortcuts}

Fichier, Ajouter des raccourcis crée des raccourcis vers BlindRSS sur le bureau,
dans le menu Démarrer et dans la barre des tâches. Cochez ceux que vous souhaitez
et choisissez OK ; le résultat de chacun est signalé.

Une entrée du menu Démarrer est aussi ce que Windows exige avant qu’une application
puisse afficher des notifications ; elle est donc utile même si vous lancez
BlindRSS d’une autre manière.

## Vérification des mises à jour {#updates}

Aide, Rechercher les mises à jour demande si une version plus récente est
disponible et propose de l’installer.

Chaque mise à jour est vérifiée avant son application : son SHA-256 doit
correspondre au manifeste publié et, sous Windows, sa signature Authenticode doit
être valide. Une mise à jour qui échoue à l’une de ces vérifications n’est pas
installée.

« Vérifier les mises à jour au démarrage » dans Paramètres, Général réalise cela
automatiquement, et « Installer automatiquement les mises à jour sans
confirmation » dans Paramètres, Avancé les applique sans demander. Vos paramètres,
base de données et téléchargements ne sont pas modifiés par une mise à jour.

## Annonce de la version {#version}

Aide, Annoncer la version (Ctrl+Shift+A) prononce la version de BlindRSS en cours
d’exécution directement dans votre lecteur d’écran.

La commande propre au lecteur d’écran pour « signaler la version de l’application »
lit la ressource de version de l’exécutable ; elle fonctionne pour une version
installée mais signale la version de Python lorsque BlindRSS est lancé depuis le
code source. Cette commande donne la bonne réponse dans les deux cas.

## À propos de BlindRSS {#about}

Aide, À propos affiche la version, la licence et des liens : le profil GitHub,
le dépôt et le journal des modifications.

BlindRSS est sous licence MIT — vous pouvez l’utiliser, le modifier, le
redistribuer ou le conditionner pour les dépôts d’une distribution, sans demander
d’autorisation.

## Utilisation de cette fenêtre d’aide {#help-window}

Cette fenêtre est un lecteur simple et entièrement accessible au clavier pour le
guide.

- La liste du contenu contient chaque section. Parcourez-la avec les flèches ;
  sélectionner une section y amène le texte et annonce son titre.
- La zone de texte est en lecture seule et sélectionnable ; un lecteur d’écran
  peut donc la lire ligne par ligne et vous pouvez en copier le contenu.
- Ctrl+F place le focus dans la zone de recherche. Saisissez un mot et appuyez
  sur Enter pour passer à l’occurrence suivante.
- F3 trouve l’occurrence suivante, Shift+F3 la précédente. La recherche revient
  au début après la fin.
- Tab et Shift+Tab passent entre la zone de recherche, la liste du contenu et le
  texte.
- Escape ferme la fenêtre.

F1, n’importe où dans BlindRSS, ouvre cette fenêtre à la section correspondant à
ce que vous utilisez — le contrôle ayant le focus, la boîte de dialogue active,
l’élément de menu en surbrillance ou le lecteur. Lorsqu’il n’y a pas de section,
le guide s’ouvre au début.

Le guide est affiché dans la langue de l’interface de BlindRSS lorsqu’une
traduction existe, et en anglais autrement.

## Dépannage {#troubleshooting}

Un flux ne se met plus à jour. Consultez Flux avec erreurs pour connaître la
raison. Un flux déplacé doit voir son adresse corrigée dans Propriétés du flux ;
un site exigeant une vérification de navigateur nécessite Importation de cookies
de sites.

Une vidéo YouTube ne se lit pas. Importez les cookies YouTube dans Paramètres,
YouTube et activez « Lire YouTube en téléchargeant d’abord ». Une erreur
« connectez-vous pour confirmer que vous n’êtes pas un robot » signifie toujours
que des cookies sont requis.

La lecture saccade. Augmentez le cache réseau dans Paramètres, Lecteur multimédia
et désactivez Ignorer les silences, qui est expérimental et consomme du processeur.

Un site ne renvoie absolument rien. Modifiez l’identification du navigateur dans
Paramètres, Avancé ; certains sites refusent catégoriquement les clients inconnus.

Rien n’est prononcé lorsqu’une commande s’exécute. Consultez Annonces dans
Paramètres, Notifications — chaque événement peut être activé ou désactivé
individuellement, et un bouton de test est disponible.

Un comportement est étrange et vous voulez le signaler. Activez le mode débogage
dans Paramètres, Général, reproduisez le problème et joignez le fichier
blindrss.log écrit à côté de vos paramètres et données.

## Assistance et communauté {#support}

Les bogues et demandes de fonctionnalités doivent être déposés dans le suivi des
problèmes GitHub, à github.com/serrebidev/BlindRSS/issues.

Pour les questions, l’aide et les nouvelles de publication, le groupe
SerrebiProjects sur Telegram, à t.me/SerrebiProjects, est le moyen le plus rapide
d’obtenir une réponse.

Les traductions sont toujours les bienvenues. Si vous parlez l’une des langues
prises en charge et qu’un texte semble incorrect, une pull request qui le corrige
sera presque certainement acceptée — consultez locale/README.md dans le dépôt pour
savoir comment les fichiers sont organisés. Il en va de même pour ce guide : une
copie traduite appartient à docs/help/<language>.md et doit conserver les marqueurs
{#anchor} exactement comme dans le fichier anglais, afin que l’aide contextuelle
continue de fonctionner.
