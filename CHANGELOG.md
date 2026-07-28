# Changelog

Readable release history for BlindRSS. When adjacent releases were part of the
same fix stream, they are combined with a version range such as
`v1.78.1-v1.78.2`.

## v1.124.5 - 2026-07-28

- Play directly when the local proxy cannot deliver a response body.
- Pace the silence scan to the listener and stop forcing the proxy.
- Cut 75% of the skip-silence scan's CPU cost.

## v1.124.4 - 2026-07-28

- Drop articles from Unread Only / Read Only lists once their status changes.

## v1.124.3 - 2026-07-25

- Stop discarding NPR program pages as "no readable article text".

## v1.124.2 - 2026-07-25

- Cut 1.6s of dead local health-checking from every playback start.

## v1.124.1 - 2026-07-25

- Stop the Miniflux per-feed refresh storm and silent non-media playback.

## v1.124.0 - 2026-07-25

- Translate every user-facing string, complete 14 locales.
- Fix Russian translation.
- Merge PR #94 (tseykovets) plus full i18n coverage and 14 completed locales.
- Update Russian translation.
- Add gettext support to new strings.
- Remove unnecessary gettext function calls on strings that don't need to be translated.

## v1.123.0 - 2026-07-25

- Open any media URL from the File menu, and fix the YouTube seek ceiling.

## v1.122.1 - 2026-07-25

- Repair PR #93 format bug and complete all 15 locales.
- Fix Russian translation.
- Merge pull request #93 from tseykovets/ru.
- Update Russian translation.
- Add gettext support to new strings.

## v1.122.0 - 2026-07-24

- Choose YouTube download formats, detect channel feeds, fix seek cap.

## v1.121.3 - 2026-07-24

- License BlindRSS under MIT, with an SPDX header on every source file (#92).
- Ship the license text with the app, as MIT requires.
- Bring the README's capability list up to date.

## v1.121.2 - 2026-07-24

- Open Settings on General and stop the delay on OK.
- Fold five thin Settings tabs into the pages they belong to.

## v1.121.1 - 2026-07-24

- Open Settings about four times faster.

## v1.121.0 - 2026-07-24

- Deliver translation updates without an app release.
- Bundle translation update modules in frozen builds.

## v1.120.5 - 2026-07-24

- Stop stale article text sticking in the reader pane.

## v1.120.4 - 2026-07-24

- Complete YouTube Takeout translations in all 15 locales.
- Update Russian translation (#90).

## v1.120.3 - 2026-07-24

- Recover Sky News podcast content.

## v1.120.2 - 2026-07-24

- Reduce NVDA lag in YouTube readers.

## v1.120.1 - 2026-07-24

- Reduce long reader rendering lag.

## v1.120.0 - 2026-07-23

- Add complete YouTube full text.

## v1.119.2 - 2026-07-23

- Improve Takeout accessibility and large-account performance.

## v1.119.1 - 2026-07-23

- Bulk import Miniflux OPML.

## v1.119.0 - 2026-07-23

- Import YouTube Takeout subscriptions.
- Merge pull request #88 from tseykovets/ru.
- Update Russian translation.

## v1.118.0 - 2026-07-23

- Add Google forum support.

## v1.117.0 - 2026-07-23

- Add Groups.io support.

## v1.116.1 - 2026-07-23

- Filter unused behave modules from frozen builds.

## v1.116.0 - 2026-07-23

- Add complete Lemmy feed and thread support.

## v1.115.0 - 2026-07-23

- Add Reddit subscriptions and complete thread reading.

## v1.114.3 - 2026-07-22

- Decode git output as UTF-8 so non-ASCII commit bodies work.
- I18n(ru): apply Nikita Tseykovets' Russian fixes (PR #87).
- Show the whole forum thread on selection, not one post.

## v1.114.2 - 2026-07-22

- Let the real "Uncategorized" category be removed and edited.

## v1.114.1 - 2026-07-22

- Edit Category did nothing on the Uncategorized folder.

## v1.114.0 - 2026-07-22

- Refresh progress counts and a Category Properties dialog.
- Merge PR #84: Add gettext support to new strings and update Russian translation (@tseykovets).
- Add gettext support to new strings and update Russian translation.

## v1.113.2 - 2026-07-22

- Stop sending contradictory fingerprints and stalling on gated sites.

## v1.113.1 - 2026-07-22

- Stop pinning a UA on hosts without a clearance, refresh stale ones.

## v1.113.0 - 2026-07-22

- Configurable browser identity and automatic clearance import.

## v1.112.13 - 2026-07-22

- Drop blank lines between paragraphs in article text.

## v1.112.12 - 2026-07-21

- Complete all non-Russian catalogs after the Russian update.
- Merge pull request #83 from tseykovets/ru.
- Update Russian translation.

## v1.112.11 - 2026-07-21

- AppleVis threads, feed author names, and a much faster browser fallback.

## v1.112.10 - 2026-07-21

- Keep whole forum threads instead of one stray post.

## v1.112.9 - 2026-07-21

- Make NYT and other DataDome sites readable in full text and rich view.

## v1.112.8 - 2026-07-21

- Strip leaked page JavaScript and decode entities in full text.

## v1.112.7 - 2026-07-21

- Strip leading share/ad/gallery chrome so the reader opens on the article, not junk labels.

## v1.112.6 - 2026-07-21

- Auto-update signature verification failed because zip extraction flattened Python.framework symlinks.

## v1.112.5 - 2026-07-21

- Don't announce "Full text loaded" when extraction failed and the pane shows feed content.

## v1.112.4 - 2026-07-21

- Announce when full text replaces the feed snippet in the reader.

## v1.112.3 - 2026-07-21

- Full text collapsed to a stub after repeated extraction; rich reader keys and focus.

## v1.112.2 - 2026-07-20

- MacOS and Linux auto-update now work like Windows.
- Full text and rich view now load on article selection under VoiceOver.
- Playback failed with 'VLC is not initialized' because Windows-only libVLC options reached libvlc_new.

## v1.112.1 - 2026-07-20

- Maintenance update.

## v1.112.0 - 2026-07-20

- Feed/category management, smart folders, and Deleted view in accessible browser.

## v1.111.7 - 2026-07-20

- Accessible-browser parity, spoken announcements, Homebrew install, Mac-driven CI.

## v1.111.6 - 2026-07-20

- Don't flag every Bluesky post as containing audio.
- Add gettext support to new strings and update Russian translation (#82).

## v1.111.5 - 2026-07-20

- Render all pages of multi-page articles in the rich full-text view.

## v1.111.4 - 2026-07-19

- Complete all locale translations for the View Feed Errors dialog strings.
- Only escalate refresh failures that look like bot protection to the browser fallback.
- Add gettext support to new strings and update Russian translation (#81).

## v1.111.3 - 2026-07-19

- Fix Russian translation.
- Make uniform and more translation-proof wildcard design.
- Add a separate name for the language Dutch (Belgium).

## v1.111.2 - 2026-07-19

- Recover protected feeds through Miniflux host.

## v1.111.1 - 2026-07-18

- Add browser fallback for protected feeds.

## v1.111.0 - 2026-07-18

- Import site cookies from browsers and Downloads.
- Import existing cookie exports at startup.

## v1.110.0 - 2026-07-18

- Editable shortcuts for every command, menu access keys, and site-cookie access to challenge-protected feeds.
- Make checkable lists readable by NVDA and copy real audio URLs.
- Merge PR #78: Improving internationalization (@tseykovets).
- Display interface language options with human-readable names.
- Add internationalization of translation language presets and update Russian translation.
- Update Russian translation.

## v1.109.3 - 2026-07-18

- Report real episode length when tracker redirects outlast the probe.

## v1.109.2 - 2026-07-17

- Complete gettext catalog coverage.
- Merge PR #77: Add gettext support to new strings and update Russian translation (@tseykovets).
- Add gettext support to new strings and update Russian translation.

## v1.109.1 - 2026-07-17

- Classic full-text view no longer drops short headings.
- Patch all known dependency vulnerabilities (pip-audit clean).
- Upgrade trafilatura/htmldate/justext/courlan on every build.

## v1.109.0 - 2026-07-17

- Ctrl+Shift+H toggles the rich full-text view.

## v1.108.0 - 2026-07-17

- Per-feed encoding overrides and feed detection on webpages.

## v1.107.2 - 2026-07-16

- Apply the rich-view toggle to the reader you are reading.

## v1.107.1 - 2026-07-16

- Repair four test doubles that had drifted from production.
- Show the localized reader context menu on Windows (#73).
- Merge PR #74: Update Russian translation (@tseykovets).
- Update Russian translation.

## v1.107.0 - 2026-07-16

- Favorites/test announcements, localized reader menu, rich-view language.

## v1.106.0 - 2026-07-16

- Per-feed and global article list columns; fix untranslated extraction errors.

## v1.105.8 - 2026-07-16

- ALT/menu, F6/Shift+F6, and Shift+Tab navigation in the rich reader.

## v1.105.7 - 2026-07-16

- ALT opens the menu bar while the rich full-text reader is focused.

## v1.105.6 - 2026-07-16

- Full newsletter/paragraph extraction, rich-view toggle, and NVDA column-review.

## v1.105.5 - 2026-07-16

- Clean reader boilerplate for Reuters, simonwillison.net, and The Information.

## v1.105.4 - 2026-07-16

- Stop category-expand from popping "list control item N" error dialog.

## v1.105.3 - 2026-07-16

- Treat feeds.soundcloud.com as plain podcast RSS, not a SoundCloud listing.

## v1.105.2 - 2026-07-16

- Complete all 15 locale catalogs for the PR #68 update strings.
- Enumerate SoundCloud via api-v2 with real dates and best-quality audio.
- Merge PR #68: add gettext support to new strings and update Russian translation.
- Add gettext support to new strings and update Russian translation.

## v1.105.1 - 2026-07-15

- Complete all locale catalogs except Russian.
- Extract the whole story body from socast/Pattison-portals sites.

## v1.105.0 - 2026-07-15

- Skip chronically-broken feeds on manual miniflux refresh.

## v1.104.0 - 2026-07-15

- Stream slow feeds so manual miniflux refresh completes in ~5s.

## v1.103.0 - 2026-07-15

- Screen-reader announcements for key events (#67).

## v1.102.1 - 2026-07-15

- Escape literal ampersands in settings tab labels across all locales (#66).
- Merge PR #65: Fix ampersand display in UI labels and Russian translation (@tseykovets).
- Fix Russian translation.
- Fix incorrect display of ampersands in settings tab labels.

## v1.102.0 - 2026-07-15

- Opt-in rich full-text reader with links, embeds, and clean article HTML.
- Translate rich-reader and link settings into all 15 locales.

## v1.101.0 - 2026-07-15

- Opt-in article structure markers (headings, lists, quotes).
- Translate structure-marker settings into all 15 locales.
- Bundle mf2py data so extruct metadata works in frozen builds.
- Cap Rumble stream rendition at 480p to stop slow playback starts.

## v1.100.0 - 2026-07-15

- Preserve article tables as accessible text.

## v1.99.7 - 2026-07-15

- Cancel stale article list preparation.

## v1.99.6 - 2026-07-14

- Keep refresh navigation responsive.
- Merge pull request #64 from tseykovets/ru.
- Add gettext support to new strings and update Russian translation.

## v1.99.5 - 2026-07-14

- Complete translations for all 15 languages.
- New articles appear during refresh instead of all at once at the end.
- Retention settings survive UI language changes.
- Local provider info in Settings is reachable by keyboard and screen readers.
- Saved-search dialog no longer crashes the app on OK.

## v1.99.4 - 2026-07-14

- Read-proxy fallback resolves Google News where Google is blocked.
- Send consent cookies so Google News resolves outside the US.

## v1.99.3 - 2026-07-14

- Skip link-list junk when a page has no article body.

## v1.99.2 - 2026-07-14

- Improve RSS refresh responsiveness and Google News.

## v1.99.1 - 2026-07-14

- Keep refresh responsive and resolve Google News articles.

## v1.99.0 - 2026-07-13

- Make NewsBlur the primary feed directory.
- Website scan in Find-a-Feed finds unadvertised feeds like TechSpot's backend.xml.
- Merge pull request #62 from tseykovets/ru.
- Merge main into ru and regenerate translations.
- Update Russian translation.
- Add gettext support to new strings.
- Add plural forms with ngettext.

## v1.98.1 - 2026-07-13

- Stop refresh from holding the SQLite write lock across per-entry work.
- Stop refresh churn from starving on-demand full-text extraction.

## v1.98.0 - 2026-07-13

- Allow delete/restore during refresh, add filter shortcuts, fix i18n init order.

## v1.97.2 - 2026-07-13

- Stop refresh top-ups from starving full-text extraction, fix i18n bugs from PR #58.
- Merge pull request #58 from tseykovets/ru.
- Add gettext support to new strings and update Russian translation.

## v1.97.1 - 2026-07-13

- Complete translations for all locales after gettext PR.
- Merge pull request #57 from tseykovets/ru.
- Add gettext support to new strings and update Russian translation.

## v1.97.0 - 2026-07-12

- Improve gettext and Russian translations (#56).
- Add gettext support to new strings and update Russian translation.

## v1.96.1 - 2026-07-12

- Harden Chromecast to AirPlay-level robustness.

## v1.96.0 - 2026-07-12

- AirPlay 2 (RAOP) audio streaming, seek, status, and pairing.

## v1.95.3 - 2026-07-12

- Preserve articles after closing settings.

## v1.95.2 - 2026-07-12

- Recover Sky News full-text extraction.

## v1.95.1 - 2026-07-12

- Translate automatic update setting.

## v1.95.0 - 2026-07-12

- Add automatic update installation setting.

## v1.94.0 - 2026-07-12

- Start BlindRSS in the system tray and reorganize settings tabs (#55).

## v1.93.3 - 2026-07-11

- Complete translations for all 15 languages.
- Merge pull request #54 from tseykovets/ru.
- Update Russian translation.

## v1.93.2 - 2026-07-11

- Media column stuck on "No audio" after Detect Audio attaches media.

## v1.93.1 - 2026-07-11

- Improve full text and live media duration.
- Stop Slashdot full-text extraction pulling in the next story and privacy footer.

## v1.93.0 - 2026-07-11

- Play queue Enter-to-play, item lengths, and Media column play times.

## v1.92.4 - 2026-07-10

- Media shortcuts work while the article text field has focus.

## v1.92.3 - 2026-07-09

- Feed dialog focus order and refresh menu enablement.

## v1.92.2 - 2026-07-09

- Improve refresh cancellation and bloomberg extraction.

## v1.92.1 - 2026-07-09

- Prevent podcast playback from stopping.

## v1.92.0 - 2026-07-09

- Per-feed refresh intervals, Stop Refresh, and faster UI with many feeds.

## v1.91.3 - 2026-07-09

- Gray article context menu items when the list has no target article.
- Detect and refresh feeds behind anti-bot WAFs via impersonated retry.

## v1.91.2 - 2026-07-09

- Use feed lede, not photo caption, as article content fallback.

## v1.91.1 - 2026-07-09

- Strip TechRadar and Al Jazeera boilerplate; readable release summary.

## v1.91.0 - 2026-07-09

- Full-text extraction fallbacks and article-list column reorder.

## v1.90.7 - 2026-07-08

- Maintenance update.

## v1.90.6 - 2026-07-08

- Startup hang (Not Responding) â€” deferred list restore livelocked the event loop.

## v1.90.5 - 2026-07-08

- Zero warnings in the test run and the release build.
- MacRumors full text merged the next article into the current one.
- Startup freeze/lag â€” dependency scan off the UI thread, preview cache across refresh reloads.

## v1.90.4 - 2026-07-08

- Tree expand/collapse felt laggy during large-category loads; keep the UI thread responsive.

## v1.90.3 - 2026-07-08

- Large categories lagged the UI; precompute article row annotations off the UI thread.
- Speed changes silenced audio for seconds; use WASAPI output and an even 0.1 speed grid.

## v1.90.2 - 2026-07-08

- Speed shortcuts never fired â€” default combos are eaten system-wide; use Ctrl+Shift+U/D/N.

## v1.90.1 - 2026-07-08

- Playback-speed menu items did nothing; speed keys blocked while reading.

## v1.90.0 - 2026-07-08

- Show each item's source feed in the Play Queue.

## v1.89.0 - 2026-07-08

- EQ presets + correct band labels, media filter, queue play/pause, Ctrl+P fix.

## v1.88.0 - 2026-07-08

- Editable Equalizer shortcut and NVDA-labeled equalizer sliders.

## v1.87.0 - 2026-07-07

- Editable shortcuts, queue nav, media column, speed menu, equalizer.

## v1.86.0 - 2026-07-07

- Play queue, playback time display, and play/pause/stop shortcuts.

## v1.85.0 - 2026-07-07

- SoundCloud/Mixcloud search + feeds, adult-search gating; fix mid-podcast stop.
- Adult site scope, 8-way search, and cross-site dedupe in Video Search.

## v1.84.1 - 2026-07-07

- App no longer freezes while preparing audio playback.

## v1.84.0 - 2026-07-06

- Full Feedspot topic pages, Google News and Bing News feed search sources.

## v1.83.0 - 2026-07-06

- Add Feedspot source to Find a Podcast or RSS Feed.
- OpenRSS fallback when adding unresolvable feeds, podcast/RSS source group filters in feed search.

## v1.82.0 - 2026-07-06

- Faster video search title labeling, sort-by combo, fyyd and Podverse feed search sources.

## v1.81.0 - 2026-07-06

- Free Space for article selection, add Ctrl+Space play/pause and Ctrl+F5 single-feed refresh with completion sound.
- Extract Axios article bodies from __NEXT_DATA__ JSON.

## v1.80.3 - 2026-07-05

- Merge pull request #53 from tseykovets/gettext.
- Restore internationalization infrastructure to state of release v1.80.1.

## v1.80.2 - 2026-07-05

- Merge pull request #52 from tseykovets/ru.
- Update Russian translation.
- Add gettext function calls for localizability of interface strings.

## v1.80.1 - 2026-07-05

- Merge pull request #51 from tseykovets/ru.
- Update Russian translation.
- Add gettext function calls for localizability of interface strings.

## v1.80.0 - 2026-07-05

- Add German, Japanese, Spanish, Hindi, Chinese (Simplified/Traditional), Polish, French, Dutch (NL/BE), Italian, and Portuguese (BR/PT) translations.

## v1.79.1 - 2026-07-05

- Sync Claude memory index in agents.md.
- Merge pull request #50 from tseykovets/gettext.
- Merge pull request #49 from tseykovets/ru.
- Remove gettext functions around strings that don't need translation.
- Update Russian translation.

## v1.79.0 - 2026-07-04

- Add Russian translation.
- Merge pull request #47 from tseykovets/ru.

## v1.78.3 - 2026-07-03
- Fixed feeds whose URLs use internationalized domains and non-ASCII paths, including Cyrillic domains and paths.
- Made feed refresh errors report the real problem instead of replacing non-HTTP exceptions with a missing `response` attribute error.
- Added build-time gettext catalog compilation so translators only need to maintain `.po` files.
- Kept the focused feed in the channel tree when Mark All Items as Read is used under Unread Only.
- Added a repository changelog, linked it from the README, and added a View Changelog button to About.

## v1.78.1-v1.78.2 - 2026-07-03
- Fixed first volume adjustments jumping unexpectedly, including on slow streams.

## v1.78.0 - 2026-07-03
- Added the global All, Unread Only, and Read Only article filter with a matching filtered channel tree.
- Added the initial gettext-based interface internationalization support.

## v1.77.5 - 2026-07-03
- Stopped refresh from overwriting user-customized feed names.

## v1.77.4 - 2026-07-03
- Added initial support for non-ASCII feed URLs and optional tolerance for SSL certificate errors.
- Clarified Mark All as Read and Show Only Unread scoping.
- Removed the duplicate app name from tray status labels.

## v1.77.3 - 2026-07-03
- Stopped treating podcast enclosures as article webpage URLs.

## v1.77.1-v1.77.2 - 2026-07-03
- Improved screen reader announcements for article find misses.

## v1.77.0 - 2026-07-03
- Added the filter rules pipeline, configurable delete behavior, and related screen-reader find announcements.

## v1.76.0 - 2026-07-02
- Added permanent delete from Deleted Articles.
- Improved article find behavior so matches do not wrap unexpectedly.
- Included several bug-scan fixes.

## v1.75.0 - 2026-07-02
- Added Smart Folders and restorable deleted articles.
- Added find-in-article shortcuts and freed Space for list multi-select.

## v1.74.0-v1.74.1 - 2026-07-02
- Added multi-select article actions for bulk delete and copy.
- Blocked article deletion while refresh is active to avoid inconsistent state.

## v1.73.4-v1.73.5 - 2026-07-01/2026-07-02
- Improved NVDA responsiveness while navigating large article lists and the feed tree, including arrow, paging, Home, and End navigation.

## v1.73.3 - 2026-07-01
- Preserved missing full-text ledes when JSON-LD extraction had dropped them.

## v1.73.2 - 2026-07-01
- Avoided high-bitrate combined formats for YouTube live streams.
- Raised refresh concurrency and bounded per-feed retry time.

## v1.73.1 - 2026-07-01
- Handled URL-only feed item text more reliably.

## v1.73.0 - 2026-07-01
- Showed refresh status in the tray label.

## v1.72.0 - 2026-06-30
- Added recursive unread totals on category tree nodes.
- Showed feed refresh and download activity in the status bar.
- Made the Feed Description dialog close with Escape.

## v1.71.1 - 2026-06-30
- Exposed feed item descriptions in the UI.

## v1.71.0 - 2026-06-30
- Added a configurable article opening method with custom command support.
- Added a configurable default expanded/collapsed state for the category tree.
- Added a Feeds with Errors view for failed feed updates.

## v1.70.4-v1.70.6 - 2026-06-30
- Improved feed fetching against anti-bot WAFs, including browser impersonation and per-feed proxy support.
- Improved feed format compatibility.

## v1.70.2-v1.70.3 - 2026-06-28/2026-06-29
- Broadened RSS and Atom feed compatibility.

## v1.70.1 - 2026-06-28
- Preserved nested category hierarchy during OPML export/import.
- Refreshed the README and community links.

## v1.70.0 - 2026-06-25
- Added Windows installed-app support with Program Files installation and mutable data stored outside the install directory.

## v1.69.1 - 2026-06-25
- Retried update backup moves when a runtime DLL is transiently locked.

## v1.69.0 - 2026-06-25
- Added the Windows per-user installer, roaming AppData storage behavior, and Chromecast handoff support.

## v1.68.0 - 2026-06-25
- Added podcast and media chapters across providers, the player, and the accessible reader.
- Improved VoiceOver accessible names across the main window, dialogs, and player.
- Added native menu behavior, start-at-login support, and macOS Option+Arrow media keys.

## v1.67.5 - 2026-06-22
- Allowed same-named subcategories under different parent categories.

## v1.67.4 - 2026-06-10
- Fixed full text loading in the macOS accessible browser and improved macOS parity.

## v1.65.0-v1.67.3 - 2026-06-01/2026-06-07
- Improved YouTube and offline playback reliability with yt-dlp/VLC fallback exhaustion, cookie import, local-download playback, playback cache management, offline podcast playback, and MKV retry for conversion failures.
- Added a Download button to the accessible browser.

## v1.64.0 - 2026-05-31
- Broadened media-tool detection and improved YouTube playback stability.

## v1.63.53-v1.63.54 - 2026-05-31
- Improved article copy actions so Copy Text can include already-extracted full text with title and author headers.
- Cleaned up YouTube/media context menu behavior for copy and download actions.

## v1.63.52 - 2026-05-29
- Added cross-platform updater work, search subscriptions, accessibility fixes, and refresh fixes.

## v1.63.50-v1.63.51 - 2026-05-29
- Added Linux build support to the cross-platform release pipeline.
- Added a Copy Audio Link context-menu option for media items.

## v1.63.47-v1.63.49 - 2026-05-21/2026-05-25
- Fixed eager video search metadata lookups.
- Fixed Supercast/subscriber feed episode titles being replaced by footer links.
- Fixed updater window and article shortcut behavior.

## v1.63.43-v1.63.46 - 2026-05-21
- Made Windows updates more robust around locked files, updater handoff, security, and playback cleanup.
- Raised the Miniflux session pool size above targeted-refresh worker limits.

## v1.63.41-v1.63.42 - 2026-05-21
- Improved Miniflux refresh behavior, including startup refresh fanout, keep-alive sessions, shorter connect timeouts, and pre-release robustness fixes.

## v1.63.38-v1.63.40 - 2026-05-19/2026-05-21
- Fixed article delete shortcut/menu behavior and clipboard preservation on shutdown.
- Required Python 3.14 for builds.

## v1.63.37 - 2026-05-19
- Forced startup refresh and gated debug file logging.

## v1.63.36 - 2026-05-09
- Improved feed refresh reliability.

## v1.63.34-v1.63.35 - 2026-05-08
- Improved release publication checks so updater-visible releases are published and marked Latest.
- Fixed Miniflux refresh status reporting.

## v1.63.33 - 2026-05-08
- Bugfixes.

## Historical Changelog

Older entries below were reconstructed from the Forgejo mirror's tag history and
the historical notes kept in the repository.

## v1.63.31-v1.63.32 - 2026-04-29
- Fixed updater GitHub owner detection and signature verification fallback.

## v1.63.28-v1.63.30 - 2026-04-15
- Added accessible browser category expansion and Enter-to-open behavior.
- Moved user data into a safer config location and restored the accessible browser after settings.
- Improved macOS release flow, bundled dependency detection, and cross-platform release docs.

## v1.63.27 - 2026-04-06
- Fixed local OPML imports, homepage feed repair, feed selection, dead-feed retries, chapter download timing, conditional refresh, and refresh CPU usage.

## v1.63.23-v1.63.26 - 2026-03-08/2026-03-15
- Added nested subcategory support in the tree.
- Improved YouTube feed search ranking and playlist priority.
- Reduced local refresh CPU load and refreshed imported OPML feeds.

## v1.63.17-v1.63.22 - 2026-02-27/2026-02-28
- Improved YouTube playback in packaged builds with proxy fallback, stream-proxy fallback, and the `android_vr` client.
- Improved search dialog keyboard/status behavior and preserved article text selection shortcuts.
- Clarified Grok/Groq naming in translation settings.

## v1.63.12-v1.63.16 - 2026-02-27
- Added Qwen, OpenRouter, and Groq translation support with provider-scoped settings.
- Improved translation fallback reliability, model coverage, Gemini auth compatibility, and media search playback.
- Fixed Windows notification prerequisites.

## v1.63.8-v1.63.11 - 2026-02-25/2026-02-27
- Improved Ning activity feed titles, formatting, and full-text replacement behavior.
- Added feed-search source filtering and preserved text selection shortcuts.

## v1.63.4-v1.63.7 - 2026-02-25
- Added YouTube channel, YouTube playlist, Mastodon, Bluesky, PieFed, and video-search sources.
- Added a feed tree delete shortcut and Miniflux fixes.

## v1.63.0-v1.63.3 - 2026-02-19/2026-02-24
- Restored podcast chapter support and added previous/next chapter keyboard shortcuts.
- Added requested issue fixes, translation and UX improvements, and contact/community info.
- Fixed Ctrl+Up/Down volume shortcuts, YouTube playback stalls, and OPML feed title preservation.

## v1.62.0-v1.62.2 - 2026-02-17
- Added Windows notification activation so articles can open/play from notifications.
- Improved notification persistence in Action Center.

## v1.61.0-v1.61.1 - 2026-02-17
- Expanded Windows UX with sorting, startup, and notification improvements.
- Fixed desktop shortcut creation.

## v1.60.37-v1.60.39 - 2026-02-10/2026-02-17
- Added built-in player soundcard selection.
- Improved feed refreshing and Inoreader support.
- Fixed stale feed refresh across providers and yt-dlp playback for YouTube Shorts and similar URLs.

## v1.60.27-v1.60.36 - 2026-02-04/2026-02-10
- Added article search filtering, persistent search visibility/configuration, and search scope controls.
- Fixed search clearing, tab traversal, title+text search, RangeCacheProxy probe stalls, and yt-dlp playback.

## v1.60.14-v1.60.26 - 2026-01-31/2026-02-02
- Fixed VLC, proxy, and range-cache playback issues including URL normalization, undefined playback variables, new-feed episode visibility, slow startup, open-ended range handling, GUI-blocking probes, duplicate redirect resolution, and yt-dlp extractor preloading.
- Tightened PyInstaller package collection.

## v1.60.10-v1.60.13 - 2026-01-30
- Bugfixes.
- Made skip-silence defaults more conservative so quiet speech and natural pauses are less likely to be skipped.
- Fixed Remember last selected feed/folder, including feeds nested in categories.
- Fixed Mark All as Read plus refresh behavior so old read articles were not deleted during tree rebuild and recreated as unread later.

## v1.60.0-v1.60.9 - 2026-01-26/2026-01-29
- Added first-load article caching and Mark All as Read.
- Improved playback startup responsiveness, duplicate article ID handling, provider/feed-scoped cache IDs, tree unread counts, Delete key feed removal, Show Only Unread, immediate shutdown, and updater logging/rollback behavior.
- Fixed NPR conditional refresh behavior.

## v1.58.0-v1.59.0 - 2026-01-24
- Added and improved BazQux Reader support, including read/unread handling, strict filters, and Hide Read Articles setting.

## v1.57.0-v1.57.5 - 2026-01-22/2026-01-23
- Added podcast/player fixes.
- Optimized large-feed refresh with batched database writes.
- Improved Windows media-tool installation reliability.
- Fixed dependency-check crashes, Alt+Space system menu behavior, and first-letter navigation.

## v1.56.17-v1.56.27 - 2026-01-19/2026-01-21
- Improved playback resume, seek repeat handling, silence-skip behavior, and startup maximize behavior.
- Fixed Inoreader support and improved Windows dependency checks, dependency installs, and updater behavior.

## v1.56.8-v1.56.16 - 2026-01-12/2026-01-17
- Hardened yt-dlp headers and fixed menu IDs, cached column ordering, skip-silence backward seeks, BBC article detection, resume persistence, play/pause keyboard behavior, Bluesky RSS parsing, media fallback/open-in-browser behavior, article column order, and bundled Deno support.

## v1.56.0-v1.56.7 - 2026-01-07/2026-01-12
- Added an option to disable startup refresh.
- Improved Load more articles behavior, focus retention, scroll/selection preservation, refresh sounds, and startup behavior.

## v1.55.0 - 2026-01-07
- Added Open in Browser to the article context menu.

## v1.54.0-v1.54.2 - 2026-01-07
- Fixed dialog closing, focus reset, undefined variables, feed refresh, NPR refresh, Android Authority boilerplate, list focus on refresh, All Articles naming, and Feed Properties button handling.
- Added core and GUI unit tests.

## v1.53.0-v1.53.7 - 2026-01-06
- Improved article status management and full-text extraction triggers.
- Fixed NPR audio/feed handling, sounds, accessibility, window maximize, bundled sound paths, update preservation of sounds, custom sound priority, feed parsing resilience, and dialog tab order.

## v1.52.0-v1.52.5 - 2026-01-05/2026-01-06
- Added single-feed refresh and Tyee boilerplate cleanup.
- Fixed media content handling without enclosures, BBC yt-dlp support, Miniflux refresh argument handling, and Mutagen import issues.

## v1.51.0 - 2026-01-05
- Added Help menu, About dialog, interactive media-tool check, feed refresh fixes, and single-instance enforcement.

## v1.50.0-v1.50.5 - 2026-01-05
- Added feed editing and media polish.
- Improved Wired/full-text extraction, podcast detection, pagination detection, All Feeds feed-source display, updater cleanup, podcast resume consistency, and range-cache Content-Range handling.

## v1.49.0-v1.49.5 - 2026-01-03/2026-01-05
- Prevented yt-dlp autoplay on publisher articles and avoided treating VoxMedia articles as yt-dlp-supported.
- Improved build dry-run Python detection, PyInstaller webrtcvad packaging, locked SQLite playback-state handling, large local database responsiveness, full-text lead extraction, and feed deletion safety.

## v1.48.11-v1.48.17 - 2026-01-03
- Added Favorites view across providers.
- Added lazy chapters and stable playback resume/seek persistence.
- Fixed webrtcvad packaging, OneDrive updater behavior, media resolution for BBC/playlist-like sites, and reduced Miniflux refresh log noise.

## v1.48.0-v1.48.10 - 2025-12-30/2025-12-31
- Added Fediverse search and improved search/menu placement.
- Reduced startup/update CPU, improved search focus/text, made updater launches invisible, supported cross-drive installs, fixed feed preview during refresh, and improved Odysee/Rumble URL handling and ffmpeg header behavior.

## v1.43.0-v1.47.0 - 2025-12-30
- Improved media support for Rumble/Odysee.
- Added feed finder, gPodder keyword search, unified feed search, and Reddit search.
- Fixed updater install-dir lock handling, config/database preservation on update, and OneDrive update retries.

## v1.42.0-v1.42.10 - 2025-12-28
- Added updater and release automation, debug mode, and update manifest support.
- Improved signing, thumbprint, and hash handling for update manifests and release builds.

## v1.34-v1.41 - 2025-12-20/2025-12-22
- Refactored HTTP handling and added yt-dlp cookie support.
- Added Read and Unread sections and date parsing fixes.
- Improved the build process and Miniflux behavior.

## v1.31-v1.33 - 2025-12-19
- Improved dependency checks, media-tool detection, PyInstaller package collection, and Python version documentation.
- Improved silence-skip and seek handling for remote streams.

## v1.3 - 2025-12-18
- Improved thread safety, UI responsiveness, and error handling.

## v1.21 - 2025-12-16
- Added silence skipping and detection with WebRTC VAD.

## v1.1-v1.2 - 2025-12-04/2025-12-16
- Added the download manager, VLC backend, playback speed, retention options, tray options, unified casting, range-cache proxy, article extraction, and casting improvements.
- Improved config and database portability, date handling, database handling, Miniflux sync, Windows dependency setup, and project documentation.

## v1.01 - 2025-11-30
- Fixed importing.

## v1.0 - 2025-11-30
- Created the initial BlindRSS source, documentation, license, and repository history.
