# BlindRSS User Guide

## BlindRSS User Guide {#user-guide}

BlindRSS is a screen-reader-friendly desktop RSS and podcast client. It reads
RSS and Atom feeds, plays podcast and video enclosures, and works either on its
own or against a hosted account such as Miniflux, Inoreader, The Old Reader, or
BazQux.

This guide is stored inside the application, so it works with no internet
connection and no web browser. Press F1 anywhere in BlindRSS to open it. If the
control, dialog, menu item, or window you are using has its own section, F1
opens the guide at that section instead of at the beginning.

Everything here is reachable from the keyboard. Use the contents list to move
between sections, or the search box to find a word anywhere in the guide.

## Getting Started {#getting-started}

When BlindRSS starts for the first time it has no feeds. There are several ways
to add some:

- Press Ctrl+N to add a feed by address. See Adding a Feed.
- Press Ctrl+Shift+F to search podcast and feed directories by name. See
  Finding Podcasts and RSS Feeds.
- Import an OPML file exported from another reader. See Importing OPML.
- Import a YouTube Takeout archive to subscribe to every channel you already
  follow. See Importing a YouTube Takeout Archive.
- Sign in to a hosted account under Tools, Settings, Provider, and BlindRSS
  reads the subscriptions already in that account. See Online Accounts and
  Providers.

Once you have feeds, press F5 to refresh them. New articles appear in the
article list, and unread counts appear beside each feed in the tree.

The three places worth visiting early are Tools, Settings (how BlindRSS
behaves), Tools, Keyboard Shortcuts (every command and its key), and this
guide.

## The Main Window {#main-window}

The main window has four main regions plus a menu bar and a status bar. Tab and
Shift+Tab move between them, and F6 cycles panes in most window managers.

- The feeds and folders tree on the left.
- The search field above the article list.
- The article list.
- The reading pane below the article list.

The menu bar holds File, Edit, View, Player, Tools, and Help. Press Alt to
reach it, then use the arrow keys. Every menu item has an access key in every
interface language, and the menu bar wraps around at either end.

Sizes, the selected feed, and the window state are remembered between runs.
"Remember last selected feed/folder on startup" in Settings, General controls
whether BlindRSS reopens on the feed you were last reading.

## Feeds and Folders List {#feed-tree}

The tree on the left lists your feeds, the categories that group them, Smart
Folders, saved searches, and the built-in views (All Feeds, Favorites, Deleted
Articles, and Feeds with Errors).

- Up and Down arrows move between items.
- Right Arrow expands a category, Left Arrow collapses it.
- Enter or selecting an item loads its articles into the article list.
- F2 opens properties for the selected feed or category.
- Applications key or Shift+F10 opens the context menu.

Each feed shows its unread count. Expanded and collapsed categories are
remembered, so the tree looks the same the next time you start.

Feeds that failed to update are still listed normally; the Feeds with Errors
view collects them so a feed that quietly stopped working does not go unnoticed.

## Article List {#article-list}

The article list shows the articles of whatever is selected in the tree, after
the current Article Filter, sort order, and search term have been applied.

- Up and Down arrows move between articles; the reading pane follows.
- Enter opens the selected article.
- Shift+Up and Shift+Down extend the selection, so bulk actions work on several
  articles at once.
- Backspace toggles read and unread on the selected article.
- Delete removes the selected articles; Shift+Delete removes them without the
  confirmation prompt.
- Ctrl+D adds or removes a favorite.
- Applications key or Shift+F10 opens the context menu.

Which columns appear, and in what order, is configurable globally and per feed.
See Article List Columns.

## Reading Pane {#reading-pane}

The reading pane below the article list holds the text of the selected article.
It is a read-only text area, so a screen reader can read it line by line, word
by word, or character by character, and the text can be selected and copied.

- Ctrl+F searches inside the article text.
- F3 and Shift+F3 move to the next and previous match.
- Enter on a link in the text opens that link.

How the text is presented is configurable in Settings, Feeds and Articles:
headings can be announced, list items marked with bullets and numbers,
quotations marked, links shown with their address, tables described, and image
alt text included. Image alt text can also be forced on or off for one feed
from that feed's context menu.

If a feed only publishes a short summary, BlindRSS can fetch the full article
text. See Full-Text Article Recovery.

## Article Window {#article-window}

Opening an article can put it in a window of its own rather than in the reading
pane, which gives the article the whole screen and keeps it open while you move
on in the list.

The window is a read-only text area with the same reading, selection, and
find-in-text behaviour as the reading pane. Escape closes it.

## Search Field {#search-field}

The search field above the article list filters the current view as you type
and commit with Enter.

- Ctrl+E moves focus to the search field.
- Enter applies the term.
- Escape, or the clear button, empties it and restores the full list.

The search field can be hidden if you never use it; the View menu has a
Show/Hide Search Field command. Whether the search matches titles only or
titles and article text is set in Settings, Feeds and Articles under "Search
Matches".

A search you want to keep can be turned into a saved search that stays in the
tree. See Persistent Searches.

## Status Bar {#status-bar}

The status bar at the bottom of the main window has three fields:

- Transient messages such as how many articles a filter matched.
- Background activity, such as a feed refresh or a download in progress.
- Playback status: what is playing, and the elapsed and remaining time.

They are deliberately separate so a refresh message cannot overwrite a search
result count while you are reading it.

## Context Menus {#context-menus}

The feeds tree and the article list each have a context menu, opened with the
Applications key or Shift+F10. They hold the commands that apply to whatever is
selected — refreshing, marking read, editing, removing, copying links, queueing
media, and so on.

Context menus support F1 as well: with an item highlighted, F1 opens the
section of this guide that explains it.

## Adding a Feed {#adding-feeds}

File, Add Feed (Ctrl+N) subscribes to a feed by address.

Paste or type the address of the feed, or of the site itself — BlindRSS looks
for a feed on the page when the address is not a feed. You can also paste a
YouTube channel or playlist address, a Mastodon or Bluesky profile, a PieFed or
Lemmy community, a SoundCloud or Mixcloud page, or a Reddit or Groups.io
address, and BlindRSS turns it into a feed.

Choose the category the feed should go into, or leave it uncategorized. The
"Open in HTML view" option makes articles from this feed open in the rich view
by default.

If you do not know the address, use Finding Podcasts and RSS Feeds instead.

## Detecting Feeds on a Page {#detect-feeds}

File, Detect Feeds on Page takes the address of an ordinary web page and lists
the feeds that page advertises, so you can subscribe without hunting for the
feed link yourself.

This is the right command when a site has a "subscribe" or "RSS" link you
cannot easily reach, or when the page offers several feeds (all posts, one
category, comments) and you want to choose.

## Finding Podcasts and RSS Feeds {#find-podcast}

Tools, Find a Podcast or RSS Feed (Ctrl+Shift+F) searches podcast and feed
directories by name, topic, or site address, so you can subscribe without
knowing any feed address.

1. Type what you are looking for in the search box — a podcast name, a topic,
   or a site address.
2. Choose a source, or leave it on "All sources".
3. Press Enter or the Search button.
4. Arrow through the results list. Each row shows the title, which directory it
   came from, and details.
5. Press Enter on a result, or choose OK, to subscribe to it.

Searches run against several directories at once and results arrive as each
one answers, so the list grows while you read it. Escape closes the dialog and
stops the search.

## Podcast and Feed Directories {#podcast-directories}

The Source box in Find a Podcast or RSS Feed chooses where to search. Besides
"All sources", "All podcast sources", and "All RSS feed sources", these
directories are available individually:

- Podcast directories: iTunes (Apple Podcasts), gPodder, fyyd, Podverse,
  SoundCloud, and Mixcloud.
- Feed directories: NewsBlur, Feedspot, Google News, Bing News, and Feedly.
- Site and community search: YouTube, Reddit, Groups.io, and the Fediverse —
  Mastodon, Bluesky, PieFed, and Lemmy or Kbin, each also selectable on its own.
- Address-based discovery: Feedsearch, and BlindRSS's own website scan, which
  fetches a site and looks for feeds in it.

No single directory is relied on. Searching "All sources" queries the podcast
and RSS groups together and merges the results, keeping broad Google News query
feeds below direct feed matches.

## Subscribing to a Search Result {#subscribing}

In any of the search dialogs — Find a Podcast or RSS Feed, Video Search, or the
Podcast Archive's find button — pressing Enter on a result, or choosing OK with
it selected, subscribes to it.

BlindRSS resolves the result to a real feed address first, so subscribing to a
podcast found in a directory, a YouTube channel, or a Fediverse account all
work the same way. The new feed appears in the tree and is refreshed
immediately.

If you want it in a particular category, move it afterwards from its context
menu or from Feed Properties.

## Podcast Archive {#podcast-archive}

Tools, Podcast Archive browses a podcast's full episode history — both the
episodes still in its feed and the older ones BlindRSS recovered — and
downloads them in batches.

Many podcast feeds publish only the most recent episodes. Archive recovery runs
automatically in the background; this window is where you see its status,
retry it by hand, and download what it found.

- Choose the podcast in the Podcast box.
- Filter episodes narrows the list as you type.
- Rescan archive runs recovery again for that podcast.
- Find or add podcast opens the feed search so you can archive a podcast you do
  not subscribe to yet.
- Play plays the selected episode, Download selected downloads it, and Download
  all downloads the whole visible list.
- Cancel downloads stops a batch that is running.

The window stays open while a batch downloads, so you can keep reading.

## Video Search {#video-search}

Tools, Video Search searches every site yt-dlp can query, in one go, and lets
you play, queue, or subscribe to what it finds.

- Type a search term and press Enter or the Search button.
- The scope box limits the search to one site; the default searches all of them.
- Results arrive as each site answers, mainstream sites first. Titles that
  arrive as placeholders are filled in as they resolve.
- Load More Results fetches another batch from each site.
- Sorting by a column header reorders what has arrived.

Identical videos found on several sites are merged into one row. Adult sites
are excluded unless "Enable adult sites in Video Search" is turned on in
Settings, Advanced.

## Opening an Article by URL {#open-article-url}

File, Open Article takes the address of any web page and reads it in BlindRSS
as if it were an article — extracted text, in the reading pane, with the same
reading options as everything else.

Use it for a one-off page you were sent, without subscribing to anything. If
the page is a forum or discussion thread, BlindRSS reads the whole thread. See
Forum and Discussion Threads.

## Opening a Media URL {#open-media-url}

File, Open Media URL plays audio or video from an address in the built-in
player without subscribing to anything.

It accepts direct media links and page addresses that yt-dlp can resolve —
YouTube, Rumble, Odysee, SoundCloud, and many more. The result plays like any
other item and can be added to the play queue.

## Removing a Feed {#removing-feeds}

File, Remove Feed unsubscribes from the selected feed. The same command is on
the feed's context menu.

Removing a feed removes its articles from the database. It does not touch
anything you have already downloaded to disk. If you use a hosted provider, the
unsubscribe is sent to that account as well.

To remove a whole category and everything in it, use Delete Category and Feeds
on the category's context menu. See Categories and Subcategories.

## Feed Properties {#feed-properties}

F2, or Edit Feed on the context menu, opens the properties of the selected
feed.

- Its title, which you can override; "Reset Title to Feed Default" on the
  context menu puts the feed's own title back.
- Its address and the category it belongs to.
- Whether new articles from it raise a notification.
- Whether it opens in the rich HTML view.
- Its own article-list column layout, on the List Headers tab, overriding the
  global one.

View Feed Description on the article list's context menu shows the description
the feed itself publishes.

## Categories and Subcategories {#categories}

Categories group feeds in the tree, and they can nest: a category may contain
both feeds and further subcategories.

- File, Add Category creates one.
- Add Subcategory on a category's context menu creates one inside it.
- Edit Category renames or moves it. See Category Properties.
- Remove Category deletes the category but keeps its feeds.
- Delete Category and Feeds deletes the category and unsubscribes from
  everything in it.
- Import OPML Here imports a file straight into that category.
- Export Category to OPML exports just that branch.

Some hosted providers keep categories in a single flat list. When that is the
case, BlindRSS says so and the "move to parent" options are unavailable.

## Category Properties {#category-properties}

Edit Category opens the category's properties: its name, and the parent
category it sits under.

Renaming a category keeps all its feeds. Moving it moves the whole branch,
including any subcategories.

## Refreshing Feeds {#refreshing}

- F5 refreshes every feed.
- Ctrl+F5 refreshes just the selected feed or category.
- Shift+F5 stops a refresh that is running.
- Refresh Category on a category's context menu refreshes that branch.

Only one of Refresh Feeds and Stop Refresh is available at a time, so the
keyboard command matches what the menu offers. Progress appears in the second
status bar field.

Automatic refreshing is configured in Settings, Feeds and Articles: the
interval, how many feeds refresh at once, how many connections per host, the
per-feed timeout, and how many times a failed feed is retried. "Automatically
refresh feeds upon start" refreshes everything at launch, and the startup
workload option chooses between using the cache and forcing a full refresh.

## Feeds with Errors {#feed-errors}

The Feeds with Errors view, and File, View Feed Errors, list the feeds whose
last update failed, with the reason.

A feed that quietly stopped working looks exactly like a feed with no new
articles, which is why this view exists. From it you can:

- Refresh Selected, to try again now.
- Copy Details, to put the error text on the clipboard.
- Feed Properties, to correct the address.
- Remove Feed, when the feed is gone for good.

Common causes are a moved or retired feed, a site that now requires a browser
check (see Importing Site Cookies), and a temporary server outage.

## Importing OPML {#import-opml}

OPML is the standard file format for a list of feed subscriptions. Every feed
reader can export one, so OPML is how you move your subscriptions from another
reader into BlindRSS without adding them one at a time.

File, Import OPML asks for the file and adds every feed in it, keeping the
category structure the file describes. Feeds you are already subscribed to are
not duplicated.

Import OPML Here, on a category's context menu, puts the whole import inside
that category instead of at the top level.

To get an OPML file out of another reader, look for "Export", "Backup", or
"Subscriptions" in its settings.

## Exporting OPML {#export-opml}

File, Export OPML writes all your subscriptions, with their categories, to an
OPML file.

Use it to back up your subscriptions, to move them to another reader or
machine, or to share a set of feeds with someone else. Export Category to OPML
on a category's context menu exports only that branch.

## Importing a YouTube Takeout Archive {#import-youtube-takeout}

Google Takeout is Google's data-export service. A YouTube Takeout archive is a
ZIP file containing your YouTube data, including the list of channels you
subscribe to. File, Import YouTube Takeout reads that ZIP and subscribes you to
those channels as feeds, so each channel's new videos arrive as articles.

To get the archive:

1. Go to takeout.google.com and sign in with the Google account your YouTube
   subscriptions are on.
2. Choose "Deselect all", then select only YouTube and YouTube Music.
3. In "All YouTube data included", keep at least "subscriptions"; "history" and
   "playlists" are optional and BlindRSS can use them too.
4. Export once as a ZIP file, and wait for Google's email — a large archive can
   take hours.
5. Download the ZIP and point this command at it.

BlindRSS then shows what it found, grouped by source, and lets you choose which
groups to import:

- Subscriptions: the channels you follow.
- History: channels you have watched but do not follow.
- Your own channels.
- Playlists, as feeds of their own.

Duplicate addresses are removed, so importing a second archive later adds only
what is new. The ZIP is never unpacked to disk; only the small data files inside
it are read.

## Persistent Searches {#persistent-search}

A persistent search is a search term that stays in the tree as its own item, so
the articles matching it are always one arrow key away.

Tools, Configure Persistent Search manages the list: Add creates one from a
term, Remove deletes it. Each saved search appears in the tree and is
re-evaluated whenever you select it, so it always reflects the current
articles.

Use it for a topic you follow across every feed — a person's name, a product, a
place. For anything more structured than a phrase, use Smart Folders.

## Smart Folders {#smart-folders}

A Smart Folder is a folder in the tree whose contents are defined by a rule
rather than by which feed an article came from.

New Smart Folder, on the tree's context menu, opens the rule editor. A rule is
a set of conditions joined by "match all" (and) or "match any" (or), and groups
of conditions can nest, so "(A and B) or C" is expressible.

Conditions test these fields:

- Yes/no fields: read, favorite, opened, updated.
- Text fields: title, content, description, author, feed, url, and tag — the
  categories or tags the site itself publishes.

Text conditions use contains, does not contain, equals, or starts with.

Smart Folders never move or copy anything; they are a view over the articles
you already have. To change articles as they arrive, use Filter Rules.

## Filter Rules {#filter-rules}

Tools, Filter Rules is BlindRSS's article-sorting engine. Rules run over
incoming articles the way email filters run over incoming mail.

Each rule pairs a condition — the same rule editor Smart Folders use — with a
set of actions:

- Move the article to a category.
- Also label it with a category, leaving it where it is.
- Mark it read.
- Mark it favorite.
- Delete it, following your configured delete behaviour.
- Skip its new-article notification.

Rules run in list order, and every enabled rule that matches contributes its
actions. A rule marked to stop ends the pipeline for that article once it has
matched, so later rules never see it. Move rules up and down to control which
wins.

A rule with no actions does nothing and is rejected, so a half-finished rule
cannot silently swallow articles.

## Article Filter {#article-filter}

View, Article Filter limits every view by read status and by whether an article
has media attached. The two groups combine.

- Ctrl+1: all articles.
- Ctrl+2: unread only.
- Ctrl+3: read only.
- Ctrl+4: media and non-media.
- Ctrl+5: with media only.
- Ctrl+6: without media only.

The filter applies to whatever is selected in the tree, including Smart Folders
and saved searches, and it persists between runs. "With media only" is the
quickest way to turn a mixed feed into a podcast list.

## Sorting Articles {#sorting}

View, Sort By orders the article list by date, name, author, description, feed,
or status. Ascending toggles the direction; the default is newest first.

The sort applies to every view and is remembered between runs. Sorting by feed
is useful in All Feeds and in Smart Folders, where articles come from many
sources at once.

## Article List Columns {#list-headers}

The columns in the article list, their order, and their widths are yours to
choose. Settings, List Headers sets the global layout; a feed's own List
Headers tab overrides it for that feed, and "Use the global column layout"
turns the override back off.

Fewer columns mean less for a screen reader to read on every row, so it is
worth removing any you never use.

## Opening Articles {#opening-articles}

Enter on an article in the list opens it. Depending on the article and your
settings, that means the reading pane, a window of its own, or the rich HTML
view.

- Open Article on the context menu does the same thing.
- Open in Browser hands the article's address to your system web browser.
- Open Accessible Browser reads the page inside BlindRSS instead. See
  Accessible Browser.

Opening an article marks it read unless you have changed that behaviour.

## Read and Unread Articles {#read-status}

- Backspace, or Toggle Read/Unread, flips the selected article.
- Ctrl+Shift+R marks everything in the current view as read.
- Mark All Items as Read, on a feed's or category's context menu, does the same
  for that branch.
- Mark as Read and Mark as Unread on the article list's context menu act on the
  whole selection, and say how many articles they will affect.

Unread counts appear beside each feed in the tree. The Article Filter can hide
read articles entirely.

## Favorites {#favorites}

Ctrl+D adds the selected article to Favorites, or removes it if it is already
there. The Favorites view in the tree lists everything you have marked.

Favorites survive the retention policy: an article you have starred is not
removed when older articles are cleaned up. Favorite is also usable as a
condition in Smart Folders and Filter Rules.

## Deleted Articles {#deleted-articles}

What Delete does is configurable in Settings, General, under "When I delete an
article":

- Move it to Deleted Articles, where it can be restored.
- Remove it permanently.
- Move it to a category you name.

With the first setting, the Deleted Articles view in the tree lists what you
removed, Restore puts an article back, and deleting from inside that view
removes it for good.

"Confirm before deleting articles" controls the confirmation prompt.
Shift+Delete always skips it.

## Full-Text Article Recovery {#full-text}

Many feeds publish only a headline and a sentence or two. BlindRSS can fetch
the article page and extract the real text, so the reading pane shows the whole
article instead of a teaser.

This happens automatically as you move through the list, in the background, and
the result is cached. "Cache full text in background" in Settings, Feeds and
Articles pre-fetches the articles around your position so moving down the list
does not wait on the network.

If a site refuses to be read at all, it is usually behind a browser check. See
Importing Site Cookies.

## Rich Full-Text View {#rich-view}

Ctrl+Shift+H switches the reading pane to the rich HTML view, which renders the
article the way a browser would, with headings, lists, tables, and links as
real elements a screen reader can navigate with its own structural commands.

The plain text view is the default because it is faster and never surprises
you. The rich view is worth it for articles whose structure carries meaning.

A feed can be set to always open in the rich view from its Feed Properties, and
links in the rich view open in your system browser rather than inside the view.

## Accessible Browser {#accessible-browser}

View, Open Accessible Browser opens a page inside BlindRSS in a window built
for screen-reader reading, rather than handing it to your system browser.

It is the right tool for a page that needs to be read rather than interacted
with, and for sites whose own interface is hard to navigate. It shares
BlindRSS's cookie and browser-identity settings, so pages behind a browser
check open here too once you have imported cookies for them.

## YouTube Videos {#youtube}

A YouTube channel or playlist address can be subscribed to like any feed. Its
videos then arrive as articles, with the description, the transcript, and the
chapter list inline, so a video can be read rather than watched.

Playback goes through yt-dlp. Settings, YouTube controls it:

- A cookies file, which lets BlindRSS see age-restricted and members-only
  videos you have access to. It can be imported from a browser directly, or
  picked up automatically from cookies.txt exports in your Downloads folder.
- "Play YouTube by downloading first", which is slower to start and much more
  reliable.
- The playback cache folder and its maximum size, with a button to clear it.

Import YouTube Takeout subscribes you to every channel you already follow in
one step.

## Forum and Discussion Threads {#forums}

Reddit, Lemmy, Groups.io, and Google Groups are read as whole threads rather
than as one post at a time: opening a discussion gives you the original post
and the replies in one continuous piece of text, which is far quicker to read
than following a thread in a browser.

Subscribing works the same way as any feed — paste the address of the subreddit,
community, or group. GitHub repositories are supported the same way, as are
Mastodon, Bluesky, and PieFed accounts and communities.

## Cut, Copy, and Paste {#clipboard}

The Edit menu holds the standard clipboard commands — Cut (Ctrl+X), Copy
(Ctrl+C), Paste (Ctrl+V), and Select All (Ctrl+A) — and they work in every text
field and in the reading pane.

BlindRSS adds commands that copy things it knows about:

- Copy Link, the article's address.
- Copy Media Link, the address of its audio or video.
- Copy Text, the article's text as read in the reading pane.
- Copy Feed URL, the address of the selected feed.
- Copy Image Link, on an article with an image.

## The Built-in Player {#player}

BlindRSS plays podcast and video enclosures itself, through VLC, so playback
never leaves the application. Ctrl+Shift+P shows or hides the player window,
and playback continues either way.

Playback is smoothed by a local range-cache proxy, which is why seeking in a
long episode is quick even on a slow connection. Streams that need resolving —
YouTube, Rumble, Odysee — go through yt-dlp first.

"Show player window when starting playback" in Settings, Media Player decides
whether the window appears on its own when something starts.

## Player Controls {#player-controls}

The player window holds, in tab order: the playback status, the position
slider, elapsed and total time, rewind and fast-forward buttons, the speed box,
the chapters button, and the volume slider. Every one of them is reachable and
operable from the keyboard, and each announces its current value.

- Ctrl+P plays and pauses.
- Ctrl+S stops.
- Ctrl+Left and Ctrl+Right rewind and fast-forward, and repeat while held. On
  macOS, Option+Left and Option+Right do the same, because Ctrl+Left and
  Ctrl+Right belong to Mission Control there.
- Ctrl+Up and Ctrl+Down change the volume.

The seek and volume keys work from anywhere in BlindRSS while something is
playing, including from inside a dialog, so you never have to find the player
window to pause.

## Player Keyboard Shortcuts {#player-shortcuts}

- Ctrl+Shift+P: show or hide the player window.
- Ctrl+P: play or pause.
- Ctrl+S: stop.
- Ctrl+Left and Ctrl+Right: rewind and fast-forward (Option+Left and
  Option+Right on macOS).
- Ctrl+Up and Ctrl+Down: volume up and down.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: faster, slower, back to normal
  speed.
- Ctrl+Shift+E: the equalizer.
- Ctrl+Shift+C: the play queue.
- Ctrl+Shift+T and Ctrl+Shift+V: next and previous in the queue.

All of these are remappable in Tools, Keyboard Shortcuts. The speed commands
deliberately default to letters rather than to Ctrl+Shift+digit or
Ctrl+Shift+period, because Windows and some NVDA add-ons take those before any
application sees them.

## Playback Speed {#playback-speed}

Player, Playback Speed changes how fast media plays, from half speed to triple
speed, with the pitch preserved.

- Ctrl+Shift+U speeds up, Ctrl+Shift+D slows down, Ctrl+Shift+N returns to 1x.
- The submenu has fixed steps: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x,
  and 3x.
- The player window has a speed box you can set directly.

"Default Playback Speed" in Settings, Media Player sets the speed everything
starts at.

## Equalizer {#equalizer}

Ctrl+Shift+E, or Player, Equalizer, opens a ten-band equalizer with a preamp.

- "Enable equalizer" turns the whole thing on and off.
- Each band is a slider that announces its gain as you change it.
- Save as Preset stores the current bands under a name; Delete Preset removes
  one.
- Reset (Flat) returns every band to zero.

The equalizer applies to everything BlindRSS plays, and its setting is
remembered.

## Chapters {#chapters}

Podcasts and YouTube videos often carry chapters. When the playing item has
them, Player, Chapters lists them and jumping to one seeks there.

- The chapters submenu fills in once the item's chapters are known, and says
  "No chapters available" when it has none.
- The player window has a chapters button and a chapters box.
- Chapter Links, on the article list's context menu, lists the links a chapter
  description contains.

Chapters are loaded in the background as you move through the list, so they are
usually ready before you press play.

## Play Queue {#play-queue}

The play queue is the list of what plays next.

- Ctrl+Shift+C opens the queue window.
- Ctrl+Shift+T and Ctrl+Shift+V play the next and previous item.
- Add to Play Queue and Remove from Play Queue, on the article list's context
  menu, change it.

In the queue window, Play starts the selected item, Move Up and Move Down
reorder the queue, Remove drops one item, and Clear All empties it. The queue
survives restarts.

## Casting to Other Devices {#casting}

BlindRSS can send what it plays to a device on your network: Chromecast,
AirPlay speakers, DLNA/UPnP renderers, Sonos speakers, Roku players and Kodi.
An episode continues on the device from where it was playing, and pause, seek
and the position work there as they do locally (Roku has no seek).

Choose the device from the cast dialog; BlindRSS streams through its own local
proxy, so a device that cannot fetch the original address itself still plays
the item. Transport controls keep working from BlindRSS while it is casting.

## Skip Silence {#silence-skipping}

"Skip Silence (Experimental)" in Settings, Media Player detects silent passages
during playback and skips over them, which noticeably shortens talk podcasts
with long pauses.

It analyses audio as it plays, so it costs some CPU and is marked experimental.
Turn it off if playback is not smooth.

## Downloading Media {#downloads}

- Download saves the selected article's audio or video with its default format.
- Download As lets you choose the format first.

Downloads must be turned on with "Enable Downloads" in Settings. The download
folder, the retention policy, and the default video download format are set on
the same page; the default folder is your system Downloads folder.

Progress appears in the second status bar field, and downloaded items play from
disk afterwards rather than over the network. The Podcast Archive can download
a podcast's whole back catalogue in one batch.

## Settings {#settings}

Tools, Settings (Ctrl+comma) holds every option, on tabs: General, Feeds and
Articles, YouTube, Media Player, Provider, Notifications, Translate, List
Headers, Advanced, and CAPTCHA Solving.

Ctrl+Tab and Ctrl+Shift+Tab move between tabs; Tab moves through the controls
on the current tab. OK applies everything, Cancel discards it all. Tab
positions are kept stable between releases, because they become muscle memory.

Pressing F1 on a tab opens that tab's section of this guide.

## Settings: General {#settings-general}

- Interface language, and whether BlindRSS follows your system language. A
  change takes effect on restart. See Interface Language.
- "Remember last selected feed/folder on startup".
- "Confirm before deleting articles", and what deleting does — move to Deleted
  Articles, delete permanently, or move to a category you name.
- "Debug mode (show console on startup)", which also writes a rotating
  blindrss.log next to your data.
- Startup and tray: close to tray, minimize to tray, start in the tray, always
  start maximized, and check for updates on startup.

## Settings: Feeds and Articles {#settings-feeds}

- The automatic refresh interval, from five minutes to four hours.
- Whether search matches titles only, or titles and article text.
- Maximum concurrent refreshes, maximum connections per host, the feed timeout,
  and how many times a failed feed is retried.
- Maximum cached views, and "Cache full text in background".
- "Automatically refresh feeds upon start", and the startup refresh workload:
  use the cache, fully refresh at startup, or always fully refresh.
- Article retention, which decides how long articles are kept. Favorites are
  never removed by retention.
- How article text is presented: announce headings, mark list items with
  bullets and numbers, mark quotations, show links with their address, describe
  tables, and include image alt text.

## Settings: YouTube {#settings-youtube}

- The yt-dlp cookies file, with a Browse button, an "Import from browser"
  button, and an option to pick up cookies.txt exports from your Downloads
  folder automatically.
- Reading cookies straight from an installed browser.
- "Play YouTube by downloading first", which starts more slowly but is the most
  reliable option.
- The YouTube playback cache folder, its maximum size in megabytes, and a
  button to clear it now.

Cookies are what make age-restricted and members-only videos playable, and they
are what a "sign in to confirm you're not a bot" error is asking for.

## Settings: Media Player {#settings-media-player}

- The preferred soundcard, or the system default.
- "Skip Silence (Experimental)". See Skip Silence.
- The default playback speed.
- "Show player window when starting playback".
- The network cache size in milliseconds, which trades startup delay for
  resilience on a slow connection.
- Paths to ffmpeg, ffprobe, and yt-dlp. Leave one blank to auto-detect; a path
  you set overrides detection, and what was detected is shown beside each.
- Downloads: whether downloads are enabled, the download folder, the retention
  policy, and the default video download format.
- Sounds: whether BlindRSS plays its notification sounds.

## Settings: Provider {#settings-provider}

Chooses where your subscriptions live: locally in BlindRSS, or in a hosted
account. See Online Accounts and Providers for what each one needs.

The page shows which provider is active and the credentials for it — a Miniflux
address and API key, an Inoreader app ID and key with an Authorize button, or
an email address and password for The Old Reader or BazQux. Clear Authorization
signs an Inoreader account out.

The local provider uses the feeds you add inside the app with Add Feed and
Import OPML.

## Settings: Notifications {#settings-notifications}

- "Enable notifications for new articles", and whether the feed's name appears
  in the notification text.
- The maximum number of notifications per refresh, and whether a summary
  notification is shown once that cap is reached.
- Test Notification sends one now.
- Exclude Feeds chooses feeds that never notify.
- Announcements: which events BlindRSS speaks directly to your screen reader,
  per event, with a Test Announcement button that sends a test through both
  speech and Braille.

## Settings: Translate {#settings-translate}

Turns on automatic translation of article content, and chooses the service that
does it.

- "Enable automatic translation for article content".
- The provider: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini, or Qwen.
- The target language, chosen from the list or typed as a code such as en, es,
  fr, or pt-BR.
- An API key for the chosen provider, and optionally a specific model. For
  OpenRouter, "Load OpenRouter Models" fetches the available model list.

Grok and Groq are different services with confusingly similar names: Grok is
xAI's, with keys from console.x.ai that start with "xai-"; Groq hosts LLaMA and
Mistral, with free keys from console.groq.com that start with "gsk_".

This translates article text. To change the language of BlindRSS's own
interface, see Interface Language.

## Settings: List Headers {#settings-list-headers}

Sets the global article-list column layout: which columns appear, in what
order, and how wide. See Article List Columns.

An individual feed can override this from its own Feed Properties.

## Settings: Advanced {#settings-advanced}

- Data storage location: keep your database and settings in the user data
  folder or in the application folder, with both paths shown. The
  app-folder option is what makes a portable install portable.
- Updates: "Automatically install updates without confirmation".
- Browser identification: which browser BlindRSS identifies itself as when
  fetching feeds, or a custom User-Agent string you type. The effective string
  is shown below. This matters for sites that block unknown clients.
- Video Search: "Enable adult sites in Video Search", off by default.

## Settings: CAPTCHA Solving {#settings-captcha}

An opt-in, paid, last-resort route for sites that answer with a CAPTCHA that
imported cookies cannot get past.

"Enable CAPTCHA solving service" turns it on, and the API key field holds your
account key with the solving service. Per-solve fees apply, which is why it is
off by default and tried only after everything else has failed.

Try Importing Site Cookies first; it is free and it solves most cases.

## Online Accounts and Providers {#providers}

BlindRSS can keep your subscriptions itself, or read them from a hosted
account. Settings, Provider chooses which.

- Local: subscriptions live in BlindRSS's own database on this machine. Nothing
  is synchronized anywhere.
- Miniflux: needs the address of your Miniflux server and an API key from your
  Miniflux account settings.
- Inoreader: needs an app ID and app key from Inoreader's developer page, then
  the Authorize button to sign in.
- The Old Reader: needs your account email address and password.
- BazQux: needs your account email address and password.

With a hosted provider, read state, subscriptions, and categories are the
account's, so they follow you to any other device signed in to the same
account. Some providers keep categories in a single flat list, and BlindRSS
says so rather than offering nesting that would not stick.

## Notifications {#notifications}

BlindRSS raises a system notification when new articles arrive, subject to
Settings, Notifications.

- Notifications can be turned off entirely.
- The feed name can be included in the text.
- A cap limits how many arrive per refresh, with an optional summary
  notification once the cap is reached.
- Individual feeds can be excluded, either from Exclude Feeds in Settings or
  from "Notifications for This Feed" on the feed's context menu.
- A Filter Rule can suppress the notification for the articles it matches.

Separately, Announcements speak chosen events straight to your screen reader
through NVDA's or JAWS's own interface, and through Braille, which gets through
even when a system notification does not.

## Article Translation {#translation}

With translation enabled in Settings, Translate, article text is translated
into your target language as you read it, using the AI service you configured.

Translation happens on demand and is cached, so re-reading an article does not
pay for it twice. It needs an internet connection and your own API key with the
chosen service.

The application interface is translated separately, through its own catalogues.
See Interface Language.

## Importing Site Cookies {#site-cookies}

Some sites put a browser verification page — typically a Cloudflare "checking
your browser" challenge — in front of their content. Those sites only answer to
a session that already passed the challenge in a real browser, so BlindRSS
cannot fetch them on its own.

Tools, Import Site Cookies gives it that session:

1. Open the website in your web browser and wait for it to finish loading.
2. Export its cookies to a cookies.txt file with a cookies.txt browser
   extension. For Chrome-based browsers, the dialog links to "Get cookies.txt
   LOCALLY".
3. Choose the exported file in the dialog.
4. Paste your browser's User-Agent string into the field below. Searching the
   web for "what is my user agent" shows it. Cloudflare requires the exact
   User-Agent the cookie was issued to, so this matters.

Firefox-family browsers have a one-click path: "Import from Browser" reads
their cookie database directly. Chromium-based browsers encrypt theirs, which
is why they need the extension.

## Keyboard Shortcuts {#keyboard-shortcuts}

Tools, Keyboard Shortcuts lists every command in BlindRSS, grouped by category,
with its current key, and lets you change any of them.

- Select a command and choose Change Shortcut. The capture dialog then records
  the next key combination you press.
- Remove Shortcut leaves a command unbound; it still works from its menu.
- Reset All to Defaults restores the shipped keys.

Shortcuts are dispatched before menu accelerators and work window-wide,
including while the player window has focus, and the keyboard path announces
itself where the menu path stays silent. Your changes are stored with your
settings and survive updates.

## Default Keyboard Shortcuts {#shortcuts-reference}

Feeds:

- Ctrl+N: Add Feed.
- F5: Refresh Feeds. Shift+F5: Stop Refresh. Ctrl+F5: Refresh the selected feed.
- F2: Edit Feed or Category.
- Ctrl+Shift+R: Mark All Items as Read.
- Ctrl+Shift+F: Find a Podcast or RSS Feed.

Articles and views:

- Ctrl+D: add to or remove from Favorites.
- Backspace: toggle read and unread. Delete: delete. Shift+Delete: delete
  without confirming.
- Ctrl+E: focus the search field.
- Ctrl+Shift+H: rich full-text view.
- Ctrl+1 to Ctrl+3: all, unread, read. Ctrl+4 to Ctrl+6: media and non-media,
  with media, without media.

Player:

- Ctrl+P: play or pause. Ctrl+S: stop. Ctrl+Shift+P: show or hide the player.
- Ctrl+Left and Ctrl+Right: seek. Ctrl+Up and Ctrl+Down: volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: speed up, down, normal.
- Ctrl+Shift+E: equalizer.
- Ctrl+Shift+C: play queue. Ctrl+Shift+T and Ctrl+Shift+V: next and previous.

Application:

- F1: this guide, opened at the section for whatever you are using.
- Ctrl+comma: Settings.
- Ctrl+Shift+A: announce the running version.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: cut, copy, paste, select all.

Commands not listed here ship unbound and can be given any key in Tools,
Keyboard Shortcuts.

## Interface Language {#language}

BlindRSS's interface is translated into fifteen languages. Settings, General
chooses one, or leaves it following your system language. The change takes
effect when you restart.

Translations are delivered between application releases as well as with them,
so a corrected translation reaches you without waiting for a new version.

This guide follows the same language when a translated guide exists for it, and
falls back to English when it does not.

## Tray Icon and Media Keys {#tray}

BlindRSS can live in the system tray. Settings, General decides whether closing
the window sends it to the tray, whether minimizing does, and whether it starts
there.

The tray icon has playback controls and reopens the main window. Your
keyboard's media keys — play/pause, stop, next, previous — control BlindRSS's
player system-wide.

## Adding Desktop Shortcuts {#desktop-shortcuts}

File, Add Shortcuts creates shortcuts to BlindRSS on the desktop, in the Start
Menu, and on the taskbar. Tick the ones you want and choose OK; the result of
each is reported back.

A Start Menu entry is also what Windows requires before an application may
raise notifications, so it is worth having even if you launch BlindRSS another
way.

## Checking for Updates {#updates}

Help, Check for Updates asks whether a newer version is available and offers to
install it.

Each update is verified before it is applied: its SHA-256 must match the
published manifest, and on Windows its Authenticode signature must be valid. An
update that fails either check is not installed.

"Check for updates on startup" in Settings, General does this automatically, and
"Automatically install updates without confirmation" in Settings, Advanced
applies them without asking. Your settings, database, and downloads are
untouched by an update.

## Announcing the Version {#version}

Help, Announce Version (Ctrl+Shift+A) speaks the running BlindRSS version
straight to your screen reader.

A screen reader's own "report application version" command reads the
executable's version resource, which works for an installed build but reports
Python's version when BlindRSS is run from source. This command gives the right
answer either way.

## About BlindRSS {#about}

Help, About shows the version, the licence, and links: the GitHub profile, the
repository, and the changelog.

BlindRSS is under the MIT licence — use it, change it, redistribute it, or
package it for a distribution's repositories, with no permission needed.

## Using This Help Window {#help-window}

This window is a plain, fully keyboard-accessible reader for the guide.

- The contents list holds every section. Arrow through it; selecting a section
  jumps the text to it and announces its title.
- The text area is read-only and selectable, so a screen reader can read it
  line by line and you can copy from it.
- Ctrl+F moves to the search box. Type a word and press Enter to jump to the
  next occurrence.
- F3 finds the next occurrence, Shift+F3 the previous. Searching wraps around.
- Tab and Shift+Tab move between the search box, the contents list, and the
  text.
- Escape closes the window.

F1 anywhere in BlindRSS opens this window at the section for whatever you are
using — the focused control, the active dialog, the highlighted menu item, or
the player. When there is no section for it, the guide opens at the beginning.

The guide is shown in BlindRSS's interface language when a translation of it
exists, and in English otherwise.

## Troubleshooting {#troubleshooting}

A feed stopped updating. Look in Feeds with Errors for the reason. A moved feed
needs its address corrected in Feed Properties; a site demanding a browser check
needs Importing Site Cookies.

A YouTube video will not play. Import YouTube cookies in Settings, YouTube, and
turn on "Play YouTube by downloading first". A "sign in to confirm you're not a
bot" error always means cookies.

Playback stutters. Raise the network cache in Settings, Media Player, and turn
off Skip Silence, which is experimental and costs CPU.

A site returns nothing at all. Change the browser identification in Settings,
Advanced; some sites reject unknown clients outright.

Nothing speaks when a command runs. Check Announcements in Settings,
Notifications — each event can be turned on or off individually, and there is a
test button.

Something behaves oddly and you want to report it. Turn on debug mode in
Settings, General, reproduce the problem, and attach the blindrss.log written
beside your settings and data.

## Support and Community {#support}

Bugs and feature requests belong in the GitHub issue tracker, at
github.com/serrebidev/BlindRSS/issues.

For questions, help, and release news, the SerrebiProjects group on Telegram at
t.me/SerrebiProjects is the fastest place to get an answer.

Translations are always welcome. If you speak one of the supported languages
and something reads wrong, a pull request fixing it will almost certainly be
accepted — see locale/README.md in the repository for how the files are laid
out. The same goes for this guide: a translated copy belongs in
docs/help/<language>.md, keeping the {#anchor} markers exactly as they are in
the English file so context-sensitive help keeps working.
