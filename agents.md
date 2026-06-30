# BlindRSS Architecture & Dev Guide

## Working Agreement (read first)
- Treat this file as the project source of truth. If code and this guide disagree,
  verify the code, fix the guide, and keep the operational rule here.
- Install whatever you need to get the job done.
- Debug and test your changes; add or extend tests in `tests/` for any behavior change.
- Fix any warnings or errors you hit along the way.
- Keep this file current when something here goes stale.

## System Overview
- Stack: Python 3.14, wxPython (GUI), SQLite (storage), feedparser + requests.
- Entry: `main.py` -> `core.factory` -> `gui.mainframe`.
- Build:
  - Windows: PyInstaller directory distribution (`main.spec` ->
    `dist/BlindRSS/BlindRSS.exe`), portable ZIP, and per-machine Program Files
    Inno Setup installer (`installer/BlindRSS.iss` ->
    `dist/BlindRSS-Setup-vX.Y.Z.exe`).
  - macOS: PyInstaller app build (`portable.spec` -> `dist/BlindRSS.app`).
  - Linux: PyInstaller directory distribution (`portable.spec` -> `dist/BlindRSS/`, packaged as `dist/BlindRSS-linux-vX.Y.Z.tar.gz`).
- App version source: `core/version.py`.
- `main.spec` embeds a Windows VERSIONINFO resource (ProductName/ProductVersion/FileVersion) built from `core/version.py` so screen readers (NVDA "Say Product Name and Version", JAWS) and Windows report the app name + version. macOS reports version via the `.app` bundle's `CFBundleShortVersionString` (`portable.spec` BUNDLE `version`, from `BLINDRSS_APP_VERSION`). Keep the version resource in sync with `core/version.py`.

## Build & Release
You should not need to open `build.bat`/`build.sh` to cut a release — everything operational is here. `build.md` has the long-form prose and the full env-var list.

### Ship a release (the only path)
- Run ONE command on Windows: `.\build.bat release`. It does the entire release. Do not hand-edit the version, tag manually, or run `gh release create` yourself.
- Only Windows originates the authoritative release (signed exe + updater manifest + GitHub release + Latest pointer). Never start a release from macOS/Linux.
- When it exits, the release is already published and marked Latest, and the macOS/Linux runner build is dispatched.

### `build.bat` modes (Windows)
- `release` — full release, in order: verify `origin` is `serrebidev/BlindRSS` → compute next version → bump `core/version.py` → clean PyInstaller build (`main.spec`) → Authenticode-sign `BlindRSS.exe` (signtool) → create portable ZIP → build/sign the Program Files Inno Setup installer → SHA-256 both → release notes → write `BlindRSS-update.json` → `git commit "Release vX.Y.Z"` + tag + push → `gh release create` (ZIP + installer + manifest, `--latest`) → force `--draft=false --latest` → assert no drafts → assert `/releases/latest` == new tag → dispatch `cross-platform-release.yml`. Any failed step aborts non-zero; fix it, don't bypass.
- `build` — iterative LOCAL build only; no version bump, no git, no GitHub. Preserves `dist\BlindRSS` user data (`rss.db*`, `podcasts\`) across rebuilds.
- `dry-run` — prints the next version and planned steps; changes nothing.

### Version numbers are automatic — never pick them
- Computed from Conventional-Commit subjects since the last tag (`tools/release.py`): breaking (`type!:`/`BREAKING`) → major; `feat` → minor; else → patch. (`fix:` → patch, e.g. `v1.63.52` → `v1.63.53`.)
- `core/version.py` is the version source of truth and is rewritten by `release`. Do not bump it by hand.

### Artifacts
- `dist\BlindRSS-vX.Y.Z.zip` (portable; signed exe inside) + a `BlindRSS.zip` copy at repo root.
- `dist\BlindRSS-Setup-vX.Y.Z.exe` (signed, per-machine Program Files installer; requires admin/UAC, including for in-app installer updates).
- `dist\BlindRSS-update.json` (Windows updater manifest: portable ZIP metadata plus installer metadata, published-at, optional notes summary, and signing thumbprint). Installed copies select the installer; portable/legacy copies select the ZIP.
- `dist\release-notes-vX.Y.Z.md`.
- The GitHub release carries the Windows ZIP + manifest immediately; the macOS ZIP + `BlindRSS-update-macos.json` and Linux tarball + `BlindRSS-update-linux.json` are added minutes later by `cross-platform-release.yml`.

### macOS / Linux (`build.sh`, auto-detects platform)
- `build` — LOCAL packaging only (bundles `yt-dlp`/`deno`/`ffmpeg`/VLC, runs `portable.spec`). macOS → ad-hoc-signed `dist/BlindRSS.app` + `dist/BlindRSS-macos-vX.Y.Z.zip`; Linux → `dist/BlindRSS/` + `dist/BlindRSS-linux-vX.Y.Z.tar.gz`. Never versions or releases.
- `release <tag>` — does NOT build; only dispatches `cross-platform-release.yml` to attach mac/Linux assets to an EXISTING Windows-created tag.
- `dry-run` — prints the plan; changes nothing.

### Updater visibility (why the guards exist)
- The updater reads only GitHub `repos/serrebidev/BlindRSS/releases/latest`, then the platform manifest on that release. It ignores git tags, `main` commits, and workflow artifacts. A release MUST be published and Latest or no one gets it. `build.bat release` enforces and self-verifies this — do not remove the guards, and do not auto-delete releases (publish/delete drafts manually by exact tag).
- Post-release check: `gh api repos/serrebidev/BlindRSS/releases/latest --jq .tag_name` must print the new tag.

### Prerequisites & toggles
- Windows release host: Python 3.14 (`py`/`python`), VLC 64-bit at `C:\Program Files\VideoLAN\VLC`, Inno Setup 6/7 (`ISCC.exe`; per-user/Program Files/PATH auto-detected or `INNO_SETUP_COMPILER`), authenticated `gh`, Windows SDK `signtool.exe`, network access.
- Pushes to `main` also trigger `cross-platform-release.yml` to build Windows/macOS/Linux VALIDATION artifacts (no published release).
- Env toggles (full list in `build.md`): `SKIP_SIGN=1` (build mode only), `SIGNTOOL_PATH`, `SIGN_CERT_THUMBPRINT`, `GITHUB_REPO_SLUG`, `RELEASE_REMOTE`, `BLINDRSS_VLC_*`, `BLINDRSS_*CODESIGN*`.

## File Structure & Responsibilities
- `main.py`
  - App bootstrap, dependency checks, provider creation, and main frame startup.
  - Starts UI and refresh work without blocking startup.
  - When debug mode is enabled, configures rotating `blindrss.log` in the active data/config directory. This file log should capture DEBUG and above from app and third-party Python loggers; when debug mode is disabled, do not create or attach the file log.

- `core/`
  - `db.py`: SQLite schema setup/migrations, WAL/busy timeout pragmas, connection helpers, retention cleanup.
    - Includes tables: `feeds`, `articles`, `chapters`, `chapter_cache`, `chapter_sources`, `categories`, `playback_state`.
    - Category identity is the full path string (`Parent / Child`) in `categories.title` and `feeds.category`; the UI can display only the leaf, but storage must keep the full path so duplicate leaf names under different parents do not collide.
    - Hosted-provider chapter rows do not belong in the local FK-backed `chapters` table; use provider-scoped cache keys in `chapter_cache` / `chapter_sources`.
  - `utils.py`: Critical helpers.
    - `HEADERS` and request helpers (`safe_requests_get` / `safe_requests_head`).
    - `html_to_text(html, include_images=False)`, `first_image_url(html)`, `content_has_images(html)`: HTML→text for the article pane. With `include_images`, each `<img>` becomes `[Image: alt]` (or `[Image]`) so screen readers announce images; the image URL is never inlined.
    - `normalize_date(raw, title, content, url)` with priority: title > URL > feed date > content.
    - `build_cache_id(article_id, feed_id, provider)` scopes article caches where provider/feed IDs can collide.
    - Chapter helpers (`chapter_source_and_media`, `fetch_and_store_chapters`, `get_chapters_batch`, `build_chapter_cache_key`) handle Podcasting 2.0 JSON chapters, embedded ID3/MP4 chapters, conditional chapter revalidation, and hosted-provider cache isolation.
    - `write_opml` preserves nested category paths as nested OPML outlines. Do not flatten `Parent / Child` into a single outline label on export.
    - `get_chapters_batch(ids, cache_keys=...)` is required for list performance; hosted providers must pass provider-scoped `cache_keys`.
  - `http_headers.py`: Converts per-channel HTTP metadata (`http-user-agent`, referrer, origin, cookie, authorization, accept, headers) into headers for players/casters/proxies. Keep this centralized so feeds with protected media work consistently.
  - `range_cache_proxy.py`: Local VLC HTTP range proxy/cache.
    - Uses isolated `requests.Session` per operation for thread safety.
    - Resolves redirects early, supports partial chunk persistence, and optimized seek behavior.
  - `stream_proxy.py`: Network proxy for cast targets.
    - Serves local/remote media to external devices.
    - Supports header forwarding and HLS remuxing via ffmpeg for compatibility.
  - `article_extractor.py`: Full-text extraction (trafilatura primary, BeautifulSoup fallback), pagination merge, boilerplate cleanup.
    - Ning handling: avoid pagination-follow on `*.ning.com`; prefer web full-text for forum/topic/article links, and prefer feed fragments only for profile-style activity links.
    - Bot/interstitial handling should return the clear "open in browser" style failure rather than replacing good feed content with anti-bot boilerplate.
  - `casting.py`: Unified casting manager for Chromecast, DLNA/UPnP, and AirPlay.
  - `browser_bridge.py`: Optional registered browser fetch hook used by extraction fallback paths. It must fail closed (`None`) so missing browser integration never breaks normal fetch.
  - `translation.py`: Optional automatic article translation. Supports Grok/xAI, Groq, OpenAI, OpenRouter, Gemini, and Qwen; chunks text, caps total submitted text, retries alternate model candidates/endpoints on model-access failures, and stores API keys only in local `config.json`.
  - `discovery.py`: Feed/media discovery and yt-dlp URL support checks.
    - Global yt-dlp search sites are discovered from the installed yt-dlp extractor registry; adult search extractors are filtered unless explicitly included.
    - Quick title enrichment is intentionally bounded and mostly opt-in; do not add broad per-result network lookups to search result arrival paths.
    - Supports direct handling/discovery logic for YouTube, Rumble, and Odysee.
    - YouTube playback reliability: `YOUTUBE_PLAYER_CLIENTS` (default `("default", "android_vr")`) is the single source of truth for which yt-dlp player clients to extract from. `youtube_player_client_arg(clients=None)` (CLI `--extractor-args`) and `youtube_player_client_list(clients=None)` (Python `extractor_args`) are used by both playback paths in `gui/player.py` (CLI `_extract_ytdlp_info_via_cli` and embedded `yt_dlp`) and by the merged download in `mainframe._download_article_via_ytdlp`. Widening the client pool past a single client (YouTube throttles/blocks individual clients and now requires PO tokens for plain `android`) is what makes playback consistent; `default` tracks yt-dlp's maintained best clients and `android_vr` is the packaged-build workaround. Change the clients in one place.
    - Playback exhausts every method before giving up (in `_resolve_and_play`): for each cookie attempt it tries embedded `yt_dlp` then the on-disk CLI; if all fail it retries embedded+CLI with the wider `YOUTUBE_PLAYER_CLIENTS_FALLBACK` pool (anonymous + configured cookies.txt); only then, as a final last resort, it hands the original page URL to VLC directly (`vlc_direct` in `_finish_media_load` skips the range-cache/stream proxy and silence scan since the URL is a page, not a media stream, and lets VLC's own extractors/error surface). Pass the fallback pool via the `clients=` arg, not by editing the primary set.
    - Local-download playback fallback: the bundled Windows VLC often cannot stream a resolved googlevideo URL even though yt-dlp can fetch it (so downloads work but streaming doesn't). `maybe_play_ytdlp_via_download` re-runs the proven yt-dlp CLI to pull the audio into the playback cache and replays it as a local file (`use_ytdlp=False`, original `article_id` kept for resume). It is armed per-load in `load_media` (`_ytdlp_page_url`/`_ytdlp_download_fallback_tried`) and triggered from three places: a VLC error event (`_handle_vlc_error`), a startup stall with no error event (`_maybe_recover_stalled_direct_playback`, after the stream-proxy retry), and a full yt-dlp resolve failure. The `youtube_play_via_download` setting (default off) skips streaming entirely and uses this path first — recommend it when a user's VLC never streams YouTube.
    - Playback cache (`core/play_cache.py`, GUI-free + tested): the download fallback writes to `resolve_cache_dir(config)` — `youtube_play_cache_dir` if set, else `{data_dir}/ytplay_cache`. After each download `_prune_ytplay_cache` calls `prune_cache` to trim oldest-first to `youtube_play_cache_max_mb` (default 500; 0 = unlimited). Settings (General) expose the folder (Browse), the size cap, and a "Clear cache now" button (`SettingsDialog._on_clear_play_cache` → `clear_cache`). Reuse these helpers instead of hand-rolling cache paths.
    - Search subscriptions: `is_youtube_search_url`/`youtube_search_query`/`fetch_youtube_search_items` enumerate a YouTube search (`/results?search_query=...`) as date-sorted videos via yt-dlp against the `sp=CAI%3D` results URL (the `ytsearchdate` prefix is unreliable across yt-dlp versions). `get_ytdlp_feed_url` returns None for search URLs so they are not rewritten to a channel feed.
    - Cookie sources (`_build_cookie_sources`) detect all major installed browsers in priority order (Brave first, incl. Brave Beta/Nightly, then Chrome incl. Chrome Beta/Canary (`Chrome SxS`), Chromium/Vivaldi, Edge incl. Edge Beta/Canary (`Edge SxS`), Opera, then Firefox/LibreWolf). yt-dlp has no per-channel browser keyword, so each Beta/Nightly/Canary variant is `(base_keyword, explicit User Data path)` read through its base extractor (`brave`/`chrome`/`edge`); default installs are the bare keyword. LibreWolf is read via the `firefox` extractor with its `Profiles` path. Format a source as `browser:profile` with `cookie_arg_for_ytdlp` — both the merged download (`mainframe`) and the playback CLI fallback (`player._extract_ytdlp_info_via_cli`) must keep the profile path, or cookie-gated variants that download fine fail to play. Playback (`gui/player.py`) and search enumeration both iterate these then fall back to anonymous, so a locked/undecryptable cookie DB never breaks them.
    - Windows caveat: Chromium v127+ uses App-Bound Encryption (yt-dlp #10927), so `--cookies-from-browser` fails for Brave/Chrome/Edge even when closed; only Firefox/LibreWolf work via browser extraction. For Chromium logins, set a `cookies.txt` (`ytdlp_cookies_file` setting): it is passed via yt-dlp `cookiefile`/`--cookies` and tried first by both playback and search enumeration.
    - Cookie-export import (`core/cookies_import.py`): App-Bound-encrypted cookies cannot be read directly, so the user exports a Netscape `cookies.txt` with a browser extension and BlindRSS imports it. Two paths, both GUI-free core + unit-tested (`tests/test_cookies_import.py`):
      - Manual: Settings "Import from browser..." button (`SettingsDialog._on_import_cookies_from_browser`) guides the export then finds/imports the newest valid jar.
      - Automatic (default on, `auto_import_browser_cookies` setting): `CookieImportWatcher` is started in `main.py` `OnInit` and polls the Downloads folder (~45s); `auto_import_youtube_cookies` detects the newest valid YouTube jar newer than `ytdlp_cookies_last_import_mtime`, imports it, sets `ytdlp_cookies_file`, and notifies via `MainFrame._show_windows_notification`. The persisted mtime stops re-import loops; the recency window guards the first run from importing an ancient unrelated jar.
      - Shared helpers: `find_latest_youtube_cookie_export` → `validate_cookie_file` (requires Netscape format + a youtube.com/google.com cookie) → `import_cookie_file` copies into `config.get_data_dir()` as `youtube_cookies.txt`.
  - `audio_silence.py`: Silence scanning/detection pipeline used by skip-silence playback.
  - `playback_state.py`: Resume position persistence and lock-safe playback state writes.
  - `updater.py`: Cross-platform GitHub release check, manifest/hash verification, and update handoff.
    - Platform-aware: picks a per-platform manifest (`BlindRSS-update.json` on Windows, `BlindRSS-update-macos.json`, `BlindRSS-update-linux.json`) and validates the asset extension (`.zip` Windows/macOS, `.tar.gz` Linux).
    - Windows: Authenticode-verifies the new exe and hands off to `update_helper.bat`.
    - macOS/Linux: hands off to `update_helper.sh` (bundled next to the executable). macOS swaps the whole `.app` bundle and relaunches with `open`; Linux swaps the install dir (preserving in-dir user data) and relaunches the binary. macOS does a best-effort `codesign --verify` of the staged bundle.
  - `update_config.py`: Canonical app/repo/platform update manifest names and asset extensions. Keep updater, build scripts, manifests, and tests aligned here instead of hard-coding names in new code.
  - `macos_integration.py`: macOS start-at-login support via per-user LaunchAgent plist, routed through the cross-platform startup helpers.
  - `windows_integration.py`: Windows startup registration and shortcut creation helpers.
  - `dependency_check.py`: Dependency/path handling and media tool availability logic.
    - Executable detection order in `_find_executable_path(name, extra_dirs=)`: (1) a user-chosen path from Settings via `set_user_tool_paths()` (`_USER_TOOL_PATHS`, fed from `custom_ffmpeg_path`/`custom_ffprobe_path`/`custom_ytdlp_path` at startup in `main.py` and on settings-save in `mainframe`), (2) `shutil.which` (PATH) before hard-coded package paths, (3) ordered bundled runtime roots when frozen, (4) Windows `where`, (5) `_collect_tool_candidates` dirs, (6) bounded `os.walk` of `search_roots` (WinGet Packages). Never blind-scans the whole drive or Downloads.
    - `ffprobe` is a first-class tool: it shares ffmpeg's candidate dirs and `check_media_tools_status` resolves it beside the found ffmpeg (`extra_dirs=[ffmpeg_dir]`). `check_media_tools_status` still returns the 3-tuple `(vlc_missing, ffmpeg_missing, ytdlp_missing)`.
    - `_collect_tool_candidates` covers portable `{APP_DIR}`/`bin`/`tools` layouts, `%USERPROFILE%\bin`, `C:\ffmpeg\bin`, Scoop (shims + `apps\*\current\bin`, incl. ffmpeg-essentials/shared/gyan-nightly, user + ProgramData), Chocolatey (`bin` shims + versioned `lib\ffmpeg*\tools\*\bin`), WinGet (`Links` + versioned `Packages\Gyan.FFmpeg_*\*\bin`, `yt-dlp.yt-dlp_*`, `yt-dlp.FFmpeg_*\*\bin`), pip/venv (`Python*\Scripts`, `venv`/`.venv`/`env\Scripts`, `~/.local/bin`), MSYS2/Cygwin, and POSIX (`/usr/bin`, `/usr/local/bin`, `/opt/homebrew/bin`, etc.). Versioned/generated `*` folders are resolved with `_expand_path_globs` (glob), not recursive scans.
    - `_validate_executable(path, tool=)` runs the harmless version command (`ffmpeg -version`, `ffprobe -version`, `yt-dlp --version`). `detect_media_tool_paths(validate=True)` returns `{tool: {"path", "valid"}}` for the Settings display (Media Player tab shows detected paths + manual overrides, populated in a background thread).
  - `config.py`: Config defaults + migrations; paths are exe-relative when frozen and source-root-relative when run from checkout.
    - Windows installer copies are identified by `.windows-installed` beside the executable (installed into Program Files, read-only). They force `%APPDATA%\BlindRSS` for `config.json`/`rss.db`/logs/cookies/playback cache, default episode downloads to the user's Downloads folder (`Downloads\BlindRSS`, via `_default_download_dir` → `_windows_downloads_dir`), and keep the runtime-managed `yt-dlp.exe` under `%LOCALAPPDATA%\BlindRSS\bin` (`dependency_check._ytdlp_runtime_bin_dir`) so nothing writes to the install dir. They copy-first migrate legacy app-folder config, SQLite data (via SQLite backup, including WAL contents), podcasts, imported cookies, playback cache, and app-relative user-data paths. Portable ZIP/source behavior remains app-relative; uninstall leaves roaming data intact.
  - `factory.py`: Provider wiring; initializes DB.
  - `runtime_env.py`: Frozen runtime PATH/VLC environment setup for packaged app bundles.

- `gui/`
  - `accessibility.py`: macOS VoiceOver-friendly accessible browser window. On macOS+VoiceOver this is the primary reading surface (auto-opened from `mainframe`), so it must do its own full-text extraction: selecting an article shows the feed snippet immediately, then a debounced background thread calls `extract_article_body` (GUI-free wrapper over `article_extractor`) and replaces the body with the full text. `extract_article_body` ALWAYS attempts real web extraction for a non-media URL (`extract_full_article`) — do NOT gate it on `article_extractor._should_prefer_feed_content` (the ">2500 chars of feed HTML" heuristic), which silently suppresses extraction for substantial feeds like Miniflux. BUT it also extracts the feed body (`extract_from_html`) and keeps whichever is LONGER: web extraction frequently returns LESS than the feed already has (truncated/partial page — e.g. a feed with 1886 chars vs a 672-char scrape), and replacing the fuller feed with that shorter result is exactly what reads as "full text doesn't work". Never downgrade below the feed. The feed candidate is the LONGER of `extract_from_html` (boilerplate-cleaned) and `utils.html_to_text` (what the reader pane shows as the snippet): `extract_from_html`/trafilatura sometimes drops the lead and returns LESS than the snippet, so the "full text" came out SHORTER than what the user already heard — never go below the snippet. The accessible browser also calls with `max_pages=1` (no pagination following): on news sites a "next" link is the NEXT STORY, so following it merges unrelated articles into one giant blob. It also takes an optional `provider_fetch(article_id, url) -> html` (the provider's server-side fetcher, e.g. Miniflux fetch-content): when web+feed don't yield a clearly-full article (best is `None` or `< _PROVIDER_FETCH_MIN_LEN` ≈ 1500 chars — a paywall/anti-bot stub can still be longer than a tiny feed, so the gate is by LENGTH, not "web lost"), it asks the provider and uses that if longer. The accessible browser passes a lock-serialized wrapper (`_provider_fetch_locked`) since the provider session isn't thread-safe across the prefetch workers. It returns `(body_text, cacheable)`: `cacheable` is True for a web/provider result, for a no-web-target item (no URL / media), or when the feed beat a working web fetch (stable); only a TOTAL web+provider failure for a web article is uncacheable so it retries next visit. Guarded by a per-selection `_content_token` (stale loads can't overwrite), an in-flight set, and a body cache keyed by `_article_cache_id`. Focusing the reader pane forces an immediate (non-debounced) load.
    - Read-ahead PREFETCH is essential for VoiceOver: every article switch fires `EVT_LISTBOX`/`on_article_selected` and the full-text load works, BUT web extraction takes 2-7s while the user navigates faster, and the async swap into the read-only `content_ctrl` is silent (VoiceOver won't re-announce it) — so without prefetch the user always hears the feed snippet. `_enqueue_prefetch_from(idx)` warms the next `_prefetch_ahead` (5) articles via a single bounded background worker (`_prefetch_worker_loop`), caching only `cacheable` results; on arrival `_show_article_at_index` hits the cache and VoiceOver reads the full article immediately. The queue is cleared on view change and the worker stopped in `Destroy`.
    - Reader width: the three-column layout (Views | Articles | Content) must give the content `TextCtrl` a generous min width (`SetMinSize`, ~620px, proportion 3) and the lists capped min widths — otherwise long feed labels in the Views list expand that column and squeeze the reader to ONE WORD PER LINE, which reads as "no full text" to a VoiceOver user even when the full article is loaded.
    - Wiring full text only into the main-window `content_ctrl` leaves macOS users with feed snippets only. The main-window full-text path triggers on real keyboard focus of `content_ctrl` (`EVT_SET_FOCUS`), which VoiceOver cursor navigation does not fire — that's why the accessible browser triggers on selection AND prefetches.
  - `mainframe.py`: Main UI, feed refresh orchestration, list rendering, notifications, and menu actions.
    - Includes special views: All, Unread, Read, Favorites.
    - Includes persistent search UI, article sorting, and remember-last-feed restore behavior.
    - The article list includes a truncated Description column and the article context menu includes "View Feed Description..." so RSS item `<description>` / feed summary text remains available even when the reader pane loads extracted full text.
    - Optional translation is triggered through the background full-text pipeline; translated full-text cache keys include a `::tr[provider:lang]` suffix and the cache is cleared when translation settings change.
    - macOS uses standard wx menu role IDs (`ID_ABOUT`, `ID_PREFERENCES`, `ID_EXIT`) and an Edit menu so native relocation/accelerators and focused text-control copy/select-all keep working.
    - Player chapter actions live in menus and shortcuts (`Ctrl+Shift+Left/Right` for previous/next). Keep menu labels screen-reader friendly and direction buttons disabled when unavailable.
  - `player.py`: VLC-backed player window with proxy integration and async chapter/media load.
  - `hotkeys.py`: `HoldRepeatHotkeys` — hold-to-repeat handler for Ctrl+key shortcuts (quick tap fires once; holding repeats), used by `mainframe.py`/`player.py` to avoid multi-seek on quick taps. Not a global/OS media-key hook.
    - On macOS, Option/Alt+Arrow maps to the same seek/volume actions because Ctrl+Left/Right are often captured by Mission Control. Off macOS, Alt+Arrow must stay free for normal navigation.
  - `tray.py`: System tray icon and tray media controls.
  - `dialogs.py`: Add feed, settings, provider auth, feed discovery search, and notification controls.
    - Settings has a Translate tab for automatic article translation. API keys are local config only; do not introduce cloud sync or logging of keys.
    - New-article notifications work on Windows (toast) AND macOS (Notification Center) via `wx.adv.NotificationMessage`. Gate everything on `core.utils.platform_supports_notifications()` (win+darwin), not `sys.platform.startswith("win")`; the config keys keep their `windows_notifications_*` names for back-compat. The Windows-only AppUserModelID prerequisite (`main.py`/`mainframe._ensure_notification_prerequisites`) stays Windows-gated — macOS needs no prerequisite.

- `providers/`
  - `base.py`: `RSSProvider` interface.
  - `local.py`: Local RSS provider, parallel refresh (`ThreadPoolExecutor`), conditional GET, cache revalidation headers.
    - Retries Cloudflare-challenged WordPress-style `/feed` URLs with the canonical trailing slash and persists the working URL after success.
    - Parses broad feed shapes: RSS 0.90/0.91 (Netscape/Userland)/0.92/0.93/0.94/1.0/RDF/2.0, Atom 0.3/1.0, JSON Feed 1.0/1.1, best-effort CDF, WordPress `content:encoded`, common metadata/media namespaces (`dc`, `dcterms`, `media`, `itunes`, `georss`, `opensearch`, `sy`, `slash`, `wfw`), and older feeds with no GUID/link. Compatibility priority is RSS 2.0, Atom 1.0, RSS 1.0/RDF, older RSS 0.9x, JSON Feed, then extensions. Use the RSS 2.0 spec, Atom RFC 4287, JSON Feed 1.1 spec, and W3C Feed Validator docs/examples as secondary references and test sources, but expect most real-world bugs to come from messy feeds: bad dates, wrong MIME types, missing GUIDs, HTML in descriptions, relative links, namespaces, and podcast/media enclosures. When an entry has no stable ID/link, generate a deterministic `blindrss:entry:{uuid5}` seed scoped by feed and content.
    - Some servers reject normal RSS Accept headers. If a feed-like URL returns HTTP 406, retry once with `Accept: */*` and `User-Agent: BlindRSS/1.0`; keep that narrow so normal requests still use `core.utils.HEADERS`.
  - `miniflux.py`, `inoreader.py`, `theoldreader.py`, `bazqux.py`: Hosted provider implementations.
    - Miniflux refresh uses `PUT /v1/feeds/refresh` and `PUT /v1/feeds/{id}/refresh`; HTTP 204 is a successful refresh response and must update request-status tracking as success.
    - Miniflux per-feed refresh timeout/5xx retries are expected for some server-side feed failures and should stay at debug/backoff level; keep global API failures visible as warnings/errors.
    - Miniflux manual/targeted per-feed refreshes run through a bounded worker pool (`miniflux_targeted_refresh_workers`, default 8) so slow feeds do not serialize the whole refresh.
    - Miniflux entries may carry plausible near-future `published_at` values used by the web UI for ordering; preserve those server dates instead of demoting them to the sentinel date.
    - `fetch_full_content` (server-side full-text) MUST use `GET /v1/entries/{id}/fetch-content` — current Miniflux returns 405 for the old `PUT` form, which silently disabled the full-text provider fallback in BOTH the main window and the accessible browser. Keep `GET` primary with a `PUT` fallback only on 405.
  - Favorites are supported across providers through `supports_favorites` / `set_favorite` / `toggle_favorite`.
  - Inoreader note: `stream/contents` expects URL-encoded `streamId` in path segment, not `s=` query parameter.

- `tools/`
  - `release.py`: Windows release/version automation.
  - `build_utils.py`: helper utilities used by build flows.

## Data Model (`rss.db`)
- `feeds`: `id`, `url`, `title`, `title_is_custom`, `category`, `icon_url`, `etag`, `last_modified`, `show_images`.
  - `title_is_custom`: 1 when the user renamed the feed, so a refresh does not overwrite the custom title with the feed's own.
  - `show_images`: per-feed image-alt override. NULL = inherit the global `show_image_alt` setting, 0 = never, 1 = always. Resolved by `db.get_feed_show_images` / set by `db.set_feed_show_images`.
- `articles`: `id`, `feed_id`, `title`, `url`, `content`, `description`, `date`, `author`, `is_read`, `is_favorite`, `media_url`, `media_type`, `chapter_url`.
  - `chapter_url`: optional external chapter source (e.g. podcast chapters JSON) fetched lazily via `utils.fetch_and_store_chapters`.
  - `description`: the feed-provided item description/summary when distinct from richer content (for example RSS `<description>` alongside `content:encoded`). UI may fall back to `content` for legacy rows/providers that do not expose a separate summary.
  - Indexed for `feed_id`, `is_read`, `date`, plus composite indexes for common list/count paths.
- `chapters`: `id`, `article_id`, `start`, `title`, `href`.
- `chapter_cache`: `id`, `cache_key`, `start`, `title`, `href`.
  - Used for hosted-provider chapter rows where the article is not in the local `articles` table.
- `chapter_sources`: `cache_key`, `source_url`, `etag`, `last_modified`, `checked_at`, `fetched_at`.
  - Stores the chapter-source revalidation clock and conditional headers. Source rows are the retention clock for hosted chapter cache cleanup.
- `categories`: `id`, `title`, `parent_id`.
  - `title` stores the full category path (`Parent / Child`), not only the leaf; `parent_id` references another `categories.id` to support nested subcategories (NULL = top-level).
  - Duplicate leaf names under different parents are valid because their full paths differ. Never "simplify" category identity back to the leaf title.
- `playback_state`: `id`, `position_ms`, `duration_ms`, `updated_at`, `completed`, `seek_supported`, `title`.

## Key Workflows

### 1. Feed Refresh
- Local provider refreshes feeds in parallel; each worker uses its own DB connection.
- Conditional refresh uses ETag/Last-Modified.
- Revalidation headers (`Cache-Control: no-cache`, `Pragma: no-cache`) are sent to avoid stale CDN-cached feed responses.
- Date normalization is strict; title/URL-derived dates can override feed metadata when inconsistent.
- Retention cleanup runs in refresh execution flow to avoid read-state resurrection bugs.
- Provider HTTP requests must use finite timeouts (`feed_timeout_seconds`).
- When startup refresh is enabled, the first background refresh runs immediately. Whether it forces is decided per provider via `RSSProvider.should_force_startup_refresh()`: the local provider returns True (forcing is just one full GET per feed, so a fresh launch is never left stale by servers that return a spurious 304), while hosted providers such as Miniflux return False to avoid an expensive per-feed fan-out on startup. Manual full refresh remains `force=True`.
- The `ignore_feed_cache` config (default False) makes the local provider treat every refresh (including periodic/background) as forced, so feeds whose servers return spurious 304s keep updating in the background. The startup refresh fetches fresh regardless; this setting only affects periodic refreshes. Exposed in Settings as "Always fetch full feeds in the background (ignore feed caching)".
- Feed-format compatibility is part of refresh, not discovery only. Keep tests for legacy RSS/RDF, Atom, JSON Feed, WordPress `content:encoded`, 406 retry, and generated entry IDs when touching parser code.

### 2. UI & Threading
- Startup refresh is backgrounded; tree/list updates are marshaled to main thread via `wx.CallAfter`.
- Main window supports tray minimize/close-to-tray behavior with tray controls.
- Remember-last-feed can restore the last selected feed/folder/special view on startup.
- On macOS with VoiceOver running, the accessible browser fallback is the intended accessibility path. It runs the full-text extraction pipeline itself (see `gui/accessibility.py`), so any reading-pane behavior added to the main window must be mirrored there or macOS users won't get it.
- Translation runs in the full-text worker, not the UI thread. If translation is enabled but fails, show/log the failure and fall back to the original rendered article text.

### 3. Media Playback & Caching
- Player opens immediately; media/chapter loads continue asynchronously.
- Optional local range cache proxy can reduce seek latency and improve scrubbing reliability.
- Partial downloaded media chunks are retained for faster rewind/reseek.
- Skip-silence pipeline can analyze media and skip detected silent spans.
- Casting path proxies media for external devices and remuxes when required.
- Chapter data can come from Podcasting 2.0 JSON, hosted provider item APIs, or embedded ID3/MP4 metadata. Local articles use `chapters`; hosted providers use `chapter_cache` with provider/account/server-scoped keys.

### 4. Full Text & Discovery
- Full-text extraction runs when feed content is missing/partial.
- Image alt text: the article pane (`_strip_html` -> `utils.html_to_text`) optionally surfaces `<img>` alt text as `[Image: alt]` so image-only entries are not blank for screen-reader users. Controlled by the global `show_image_alt` setting with a per-feed override (`feeds.show_images`); resolve via `MainFrame._show_images_for_feed(feed_id)`.
- Article context menu offers "Copy Text" (`MainFrame._compose_article_copy_text`), "Copy Media Link", and "Copy Image Link" (first `<img>` src) when available. "Copy Text" mirrors the reading pane: if the full text has already been extracted (on focus or via background prefetch, keyed in `_fulltext_cache`) it copies that complete text — which `article_extractor.render_full_article` prefixes with a `Title:`/`Author:` header — otherwise it copies the pre-extraction header (title, date, author, link) plus the cleaned feed body (honoring the feed's image-alt setting). It does not copy only the raw feed snippet. "Copy Media Link" appears only for a genuine direct media file (`MainFrame._has_direct_media_link`): yt-dlp page items (YouTube, etc.) store the watch-page URL as `media_url` and have no single combined audio+video direct link, so the item is hidden for them rather than duplicating "Copy Link". "Download" for yt-dlp-supported items routes through the yt-dlp CLI (`MainFrame._download_article_via_ytdlp`, format `bv*+ba/b`) so audio and video are combined into one playable file. The merge prefers MP4 and falls back to MKV when the selected codecs are not MP4-compatible; forcing every YouTube merge to MP4 can make ffmpeg fail on common AV1/Opus selections. If ffmpeg still reports `Conversion failed`, BlindRSS retries explicitly as MKV before giving up. Direct-file media still uses the plain streaming download.
- Discovery dialog aggregates multiple providers in parallel (Apple Podcasts, gPodder, Feedly, NewsBlur, Reddit, Fediverse, Feedsearch, local discovery).
- URL-based media/feed support includes YouTube, Rumble, and Odysee handling.
- Listing/search feeds (no native RSS) are scraped/enumerated on refresh in `providers/local.py` `_refresh_single_feed`: Rumble channels/search (`fetch_listing_items`; search URLs are forced to `sort=date`), Odysee listings, and YouTube search (`discovery.fetch_youtube_search_items`, stored as `video/youtube` articles so the yt-dlp playback path handles them). These branches run before generic feed parsing and store `etag`/`last_modified` as NULL.
- The global yt-dlp search dialog is for user-initiated search. It should not auto-enrich every fallback title on result arrival; bounded quick-title prefetch exists for selected/supported rows so search stays responsive.

### 5. Translation
- Disabled by default (`translation_enabled=False`). Settings exposes provider, target language, model override, and API key for Grok/xAI, Groq, OpenAI, OpenRouter, Gemini, and Qwen.
- Translation operates on rendered full-text output, splits into chunks (`translation_chunk_chars`, default 3500), and caps total submitted text at 50k characters.
- Model defaults are intentionally current/provider-specific and tested. When updating model names, update `core/translation.py` and `tests/test_translation_multi_provider.py` together.
- OpenRouter model listing uses `core.utils.safe_requests_get`; chat-completion providers use POST requests with finite timeouts and should not log request bodies or API keys.

### 6. Updates (packaged app, all platforms)
- Checks latest GitHub release + a per-platform manifest (`BlindRSS-update.json` / `-macos.json` / `-linux.json`).
- Each platform's manifest is published by the build flow that produces that platform's asset, so its SHA-256 always matches the asset on the same release. The macOS/Linux manifests are uploaded by the dispatched GitHub Actions job, so there is a short window after a Windows release where the mac/Linux manifest is not yet present (the client just reports "manifest not found" until the workflow finishes).
- Verifies asset SHA-256 before apply. Windows also verifies the signed executable (Authenticode); macOS does a best-effort `codesign --verify`; Linux relies on SHA-256.
- Windows uses `update_helper.bat`; macOS/Linux use `update_helper.sh`.
- Installed Windows copies use signed installer metadata from
  `BlindRSS-update.json`; portable/legacy copies continue to use the ZIP asset.
- Windows helper must close/wait for BlindRSS processes launched from the install directory, verify key install files are unlocked, and verify the old install was fully moved before applying staged files. If locks remain, abort before destructive overlay and roll back/restart cleanly.
- POSIX helper waits for the app PID to exit, backs up the install target, swaps in the staged build (macOS `.app` bundle via `ditto`; Linux install dir, restoring in-dir user data such as `config.json`/`rss.db*`/`podcasts`/`sounds`), relaunches, and rolls back on failure. It is run from a temp copy so the swap cannot delete it mid-run. Covered by `tests/test_posix_update_helper.py` (static invariants + real-execution swap/restore/abort tests, skipped off POSIX).

### 7. Cross-Platform Packaging
- `build.sh` bundles `yt-dlp`, `deno`, `ffmpeg`, and VLC runtime files outside Windows (macOS and Linux).
- macOS builds are ad-hoc signed for free with `codesign` unless disabled.
- Linux builds require system VLC (`vlc` + `libvlc-dev`) and ffmpeg; `portable.spec` bundles `libvlc.so*` and the VLC plugins dir, overridable via `BLINDRSS_VLC_LIB_DIR` / `BLINDRSS_VLC_PLUGINS`. Output is a `tar.gz` (preserves the executable bit), not a `.app`.

## Build Quality
- When building, always fix any warnings, bugs, or errors you can before considering the build complete.
- Pytest is configured by `pytest.ini` to use `.tmp_test/pytest` as its base temp directory. Keep this repo-local temp base so Windows machines with broken or inaccessible global pytest temp folders can still run the full suite reliably.

## Blunt Things To Remember
- BlindRSS is accessibility-first. A fix that works visually but regresses NVDA, JAWS, or VoiceOver is not done.
- Do not block startup with network, dependency checks, yt-dlp extractor loading, translation, full-text extraction, or media probing. Use background workers and marshal GUI changes with `wx.CallAfter`.
- Do not write mutable runtime data into Program Files installed builds. Installed Windows data goes to `%APPDATA%\BlindRSS`; runtime-managed `yt-dlp.exe` goes to `%LOCALAPPDATA%\BlindRSS\bin`; episode downloads default to `Downloads\BlindRSS`.
- Do not invent new release steps. `.\build.bat release` is the release process.
- Do not trust one provider shape. Local feeds, Miniflux, Inoreader, The Old Reader, and BazQux have different article IDs, chapter APIs, category behavior, and favorite support.
- Do not replace fuller feed/article text with a shorter scrape, translation failure, or bot-interstitial page.
- Do not add broad synchronous loops in the UI thread. Batch DB reads (`get_chapters_batch`), cap prefetch/enrichment work, and keep provider refreshes bounded.
- Do not log secrets: provider API keys, cookies, Authorization headers, imported cookies.txt contents, and translation request text are user data.

## Operational Mandates
1. User-Agent safety: always use `core.utils.safe_requests_get` / `core.utils.HEADERS` for network requests.
2. Date handling: use `core.utils.normalize_date`; trust title/URL-derived dates over feed metadata when mismatched.
3. Performance: use `get_chapters_batch` for lists; avoid per-item DB loops in UI thread.
4. Network safety: in `RangeCacheProxy`, never share `requests.Session` instances across threads.
5. Naming: app name is **BlindRSS**.
6. Timeouts: all provider HTTP requests must set finite timeouts.
7. Inoreader OAuth: HTTPS localhost redirect URIs may require pasted redirect URL flow; validate `state`.
8. Releases: cut every official release with `.\build.bat release` on Windows; never hand-pick the version or tag. Full mechanics and the publish/Latest guards are in **Build & Release** above.
9. Release publication: a release MUST end up published and Latest or the updater never sees it. Do not remove the `build.bat release` guards (`--draft=false --latest`, no-drafts check, `/releases/latest` verify) or auto-delete releases. See **Build & Release** > Updater visibility.
10. Tests: add/extend tests in `tests/` for behavior changes and regressions.
11. Secrets: never print, log, commit, or include API keys/cookies/Authorization headers in tests or diagnostics.

<!-- claude-memory:begin (managed by sync-claude-memory.py; canonical files live in C:\Users\admin\.claude - edit there, not here) -->
## Memories (shared from ~/.claude - project: C--Users-admin-git-BlindRSS)
@C:\Users\admin\.claude\projects\C--Users-admin-git-BlindRSS\memory\MEMORY.md
@C:\Users\admin\.claude\projects\C--Users-admin-git-BlindRSS\memory\category-identity-model.md
@C:\Users\admin\.claude\projects\C--Users-admin-git-BlindRSS\memory\curl-cffi-impersonation-transport.md
@C:\Users\admin\.claude\projects\C--Users-admin-git-BlindRSS\memory\provider-flat-vs-nested.md
@C:\Users\admin\.claude\projects\C--Users-admin-git-BlindRSS\memory\release-build-process.md
<!-- claude-memory:end -->
