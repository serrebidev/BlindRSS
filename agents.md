# BlindRSS Architecture & Dev Guide

## Working Agreement (read first)
- Install whatever you need to get the job done.
- Debug and test your changes; add or extend tests in `tests/` for any behavior change.
- Fix any warnings or errors you hit along the way.
- Keep this file current when something here goes stale.

## System Overview
- Stack: Python 3.14, wxPython (GUI), SQLite (storage), feedparser + requests.
- Entry: `main.py` -> `core.factory` -> `gui.mainframe`.
- Build:
  - Windows: PyInstaller directory distribution (`main.spec` -> `dist/BlindRSS/BlindRSS.exe`).
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
- `release` — full release, in order: verify `origin` is `serrebidev/BlindRSS` → compute next version → bump `core/version.py` → clean PyInstaller build (`main.spec`) → Authenticode-sign `BlindRSS.exe` (signtool) → zip → SHA-256 → release notes → write `BlindRSS-update.json` → `git commit "Release vX.Y.Z"` + tag + push → `gh release create` (ZIP + manifest, `--latest`) → force `--draft=false --latest` → assert no drafts → assert `/releases/latest` == new tag → dispatch `cross-platform-release.yml`. Any failed step aborts non-zero; fix it, don't bypass.
- `build` — iterative LOCAL build only; no version bump, no git, no GitHub. Preserves `dist\BlindRSS` user data (`rss.db*`, `podcasts\`) across rebuilds.
- `dry-run` — prints the next version and planned steps; changes nothing.

### Version numbers are automatic — never pick them
- Computed from Conventional-Commit subjects since the last tag (`tools/release.py`): breaking (`type!:`/`BREAKING`) → major; `feat` → minor; else → patch. (`fix:` → patch, e.g. `v1.63.52` → `v1.63.53`.)
- `core/version.py` is the version source of truth and is rewritten by `release`. Do not bump it by hand.

### Artifacts
- `dist\BlindRSS-vX.Y.Z.zip` (signed exe inside) + a `BlindRSS.zip` copy at repo root.
- `dist\BlindRSS-update.json` (Windows updater manifest: version, asset name, SHA-256, signing thumbprint).
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
- Windows release host: Python 3.14 (`py`/`python`), VLC 64-bit at `C:\Program Files\VideoLAN\VLC`, authenticated `gh`, Windows SDK `signtool.exe`, network access.
- Pushes to `main` also trigger `cross-platform-release.yml` to build Windows/macOS/Linux VALIDATION artifacts (no published release).
- Env toggles (full list in `build.md`): `SKIP_SIGN=1` (build mode only), `SIGNTOOL_PATH`, `SIGN_CERT_THUMBPRINT`, `GITHUB_REPO_SLUG`, `RELEASE_REMOTE`, `BLINDRSS_VLC_*`, `BLINDRSS_*CODESIGN*`.

## File Structure & Responsibilities
- `main.py`
  - App bootstrap, dependency checks, provider creation, and main frame startup.
  - Starts UI and refresh work without blocking startup.
  - When debug mode is enabled, configures rotating `blindrss.log` in the active data/config directory. This file log should capture DEBUG and above from app and third-party Python loggers; when debug mode is disabled, do not create or attach the file log.

- `core/`
  - `db.py`: SQLite schema setup/migrations, WAL/busy timeout pragmas, connection helpers, retention cleanup.
    - Includes tables: `feeds`, `articles`, `chapters`, `categories`, `playback_state`.
  - `utils.py`: Critical helpers.
    - `HEADERS` and request helpers (`safe_requests_get` / `safe_requests_head`).
    - `html_to_text(html, include_images=False)`, `first_image_url(html)`, `content_has_images(html)`: HTML→text for the article pane. With `include_images`, each `<img>` becomes `[Image: alt]` (or `[Image]`) so screen readers announce images; the image URL is never inlined.
    - `normalize_date(raw, title, content, url)` with priority: title > URL > feed date > content.
    - `get_chapters_batch(ids)` for list performance.
  - `range_cache_proxy.py`: Local VLC HTTP range proxy/cache.
    - Uses isolated `requests.Session` per operation for thread safety.
    - Resolves redirects early, supports partial chunk persistence, and optimized seek behavior.
  - `stream_proxy.py`: Network proxy for cast targets.
    - Serves local/remote media to external devices.
    - Supports header forwarding and HLS remuxing via ffmpeg for compatibility.
  - `article_extractor.py`: Full-text extraction (trafilatura primary, BeautifulSoup fallback), pagination merge, boilerplate cleanup.
    - Ning handling: avoid pagination-follow on `*.ning.com`; prefer web full-text for forum/topic/article links, and prefer feed fragments only for profile-style activity links.
  - `casting.py`: Unified casting manager for Chromecast, DLNA/UPnP, and AirPlay.
  - `discovery.py`: Feed/media discovery and yt-dlp URL support checks.
    - Supports direct handling/discovery logic for YouTube, Rumble, and Odysee.
    - Search subscriptions: `is_youtube_search_url`/`youtube_search_query`/`fetch_youtube_search_items` enumerate a YouTube search (`/results?search_query=...`) as date-sorted videos via yt-dlp against the `sp=CAI%3D` results URL (the `ytsearchdate` prefix is unreliable across yt-dlp versions). `get_ytdlp_feed_url` returns None for search URLs so they are not rewritten to a channel feed.
    - Cookie sources (`_build_cookie_sources`) detect all major installed browsers in priority order (Brave first, incl. Brave Beta/Nightly via explicit profile path, then Chrome/Chromium/Vivaldi/Edge/Opera, then Firefox/LibreWolf). Format a source for the CLI with `cookie_arg_for_ytdlp`. Playback (`gui/player.py`) and search enumeration both iterate these then fall back to anonymous, so a locked/undecryptable cookie DB never breaks them.
    - Windows caveat: Chromium v127+ uses App-Bound Encryption (yt-dlp #10927), so `--cookies-from-browser` fails for Brave/Chrome/Edge even when closed; only Firefox/LibreWolf work via browser extraction. For Chromium logins, set a `cookies.txt` (`ytdlp_cookies_file` setting): it is passed via yt-dlp `cookiefile`/`--cookies` and tried first by both playback and search enumeration.
  - `audio_silence.py`: Silence scanning/detection pipeline used by skip-silence playback.
  - `playback_state.py`: Resume position persistence and lock-safe playback state writes.
  - `updater.py`: Cross-platform GitHub release check, manifest/hash verification, and update handoff.
    - Platform-aware: picks a per-platform manifest (`BlindRSS-update.json` on Windows, `BlindRSS-update-macos.json`, `BlindRSS-update-linux.json`) and validates the asset extension (`.zip` Windows/macOS, `.tar.gz` Linux).
    - Windows: Authenticode-verifies the new exe and hands off to `update_helper.bat`.
    - macOS/Linux: hands off to `update_helper.sh` (bundled next to the executable). macOS swaps the whole `.app` bundle and relaunches with `open`; Linux swaps the install dir (preserving in-dir user data) and relaunches the binary. macOS does a best-effort `codesign --verify` of the staged bundle.
  - `windows_integration.py`: Windows startup registration and shortcut creation helpers.
  - `dependency_check.py`: Dependency/path handling and media tool availability logic.
  - `config.py`: Config defaults + migrations; paths are exe-relative when frozen and source-root-relative when run from checkout.
  - `factory.py`: Provider wiring; initializes DB.
  - `runtime_env.py`: Frozen runtime PATH/VLC environment setup for packaged app bundles.

- `gui/`
  - `accessibility.py`: macOS VoiceOver-friendly accessible browser window.
  - `mainframe.py`: Main UI, feed refresh orchestration, list rendering, notifications, and menu actions.
    - Includes special views: All, Unread, Read, Favorites.
    - Includes persistent search UI and remember-last-feed restore behavior.
  - `player.py`: VLC-backed player window with proxy integration and async chapter/media load.
  - `hotkeys.py`: Global media key event filter.
  - `tray.py`: System tray icon and tray media controls.
  - `dialogs.py`: Add feed, settings, provider auth, feed discovery search, and Windows notification controls.

- `providers/`
  - `base.py`: `RSSProvider` interface.
  - `local.py`: Local RSS provider, parallel refresh (`ThreadPoolExecutor`), conditional GET, cache revalidation headers.
    - Retries Cloudflare-challenged WordPress-style `/feed` URLs with the canonical trailing slash and persists the working URL after success.
  - `miniflux.py`, `inoreader.py`, `theoldreader.py`, `bazqux.py`: Hosted provider implementations.
    - Miniflux refresh uses `PUT /v1/feeds/refresh` and `PUT /v1/feeds/{id}/refresh`; HTTP 204 is a successful refresh response and must update request-status tracking as success.
    - Miniflux per-feed refresh timeout/5xx retries are expected for some server-side feed failures and should stay at debug/backoff level; keep global API failures visible as warnings/errors.
    - Miniflux manual/targeted per-feed refreshes run through a bounded worker pool (`miniflux_targeted_refresh_workers`, default 8) so slow feeds do not serialize the whole refresh.
    - Miniflux entries may carry plausible near-future `published_at` values used by the web UI for ordering; preserve those server dates instead of demoting them to the sentinel date.
  - Favorites are supported across providers through `supports_favorites` / `set_favorite` / `toggle_favorite`.
  - Inoreader note: `stream/contents` expects URL-encoded `streamId` in path segment, not `s=` query parameter.

- `tools/`
  - `release.py`: Windows release/version automation.
  - `build_utils.py`: helper utilities used by build flows.

## Data Model (`rss.db`)
- `feeds`: `id`, `url`, `title`, `category`, `icon_url`, `etag`, `last_modified`, `show_images`.
  - `show_images`: per-feed image-alt override. NULL = inherit the global `show_image_alt` setting, 0 = never, 1 = always. Resolved by `db.get_feed_show_images` / set by `db.set_feed_show_images`.
- `articles`: `id`, `feed_id`, `title`, `url`, `content`, `date`, `author`, `is_read`, `is_favorite`, `media_url`, `media_type`.
  - Indexed for `feed_id`, `is_read`, `date`, plus composite indexes for common list/count paths.
- `chapters`: `id`, `article_id`, `start`, `title`, `href`.
- `categories`: `id`, `title`.
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

### 2. UI & Threading
- Startup refresh is backgrounded; tree/list updates are marshaled to main thread via `wx.CallAfter`.
- Main window supports tray minimize/close-to-tray behavior with tray controls.
- Remember-last-feed can restore the last selected feed/folder/special view on startup.
- On macOS with VoiceOver running, the accessible browser fallback is the intended accessibility path.

### 3. Media Playback & Caching
- Player opens immediately; media/chapter loads continue asynchronously.
- Optional local range cache proxy can reduce seek latency and improve scrubbing reliability.
- Partial downloaded media chunks are retained for faster rewind/reseek.
- Skip-silence pipeline can analyze media and skip detected silent spans.
- Casting path proxies media for external devices and remuxes when required.

### 4. Full Text & Discovery
- Full-text extraction runs when feed content is missing/partial.
- Image alt text: the article pane (`_strip_html` -> `utils.html_to_text`) optionally surfaces `<img>` alt text as `[Image: alt]` so image-only entries are not blank for screen-reader users. Controlled by the global `show_image_alt` setting with a per-feed override (`feeds.show_images`); resolve via `MainFrame._show_images_for_feed(feed_id)`.
- Article context menu offers "Copy Text" (`MainFrame._compose_article_copy_text`), "Copy Media Link", and "Copy Image Link" (first `<img>` src) when available. "Copy Text" mirrors the reading pane: if the full text has already been extracted (on focus or via background prefetch, keyed in `_fulltext_cache`) it copies that complete text — which `article_extractor.render_full_article` prefixes with a `Title:`/`Author:` header — otherwise it copies the pre-extraction header (title, date, author, link) plus the cleaned feed body (honoring the feed's image-alt setting). It does not copy only the raw feed snippet. "Copy Media Link" appears only for a genuine direct media file (`MainFrame._has_direct_media_link`): yt-dlp page items (YouTube, etc.) store the watch-page URL as `media_url` and have no single combined audio+video direct link, so the item is hidden for them rather than duplicating "Copy Link". "Download" for yt-dlp-supported items routes through the yt-dlp CLI (`MainFrame._download_article_via_ytdlp`, format `bv*+ba/b`, merged to mp4) so audio and video are combined into one playable file; direct-file media still uses the plain streaming download.
- Discovery dialog aggregates multiple providers in parallel (Apple Podcasts, gPodder, Feedly, NewsBlur, Reddit, Fediverse, Feedsearch, local discovery).
- URL-based media/feed support includes YouTube, Rumble, and Odysee handling.
- Listing/search feeds (no native RSS) are scraped/enumerated on refresh in `providers/local.py` `_refresh_single_feed`: Rumble channels/search (`fetch_listing_items`; search URLs are forced to `sort=date`), Odysee listings, and YouTube search (`discovery.fetch_youtube_search_items`, stored as `video/youtube` articles so the yt-dlp playback path handles them). These branches run before generic feed parsing and store `etag`/`last_modified` as NULL.

### 5. Updates (packaged app, all platforms)
- Checks latest GitHub release + a per-platform manifest (`BlindRSS-update.json` / `-macos.json` / `-linux.json`).
- Each platform's manifest is published by the build flow that produces that platform's asset, so its SHA-256 always matches the asset on the same release. The macOS/Linux manifests are uploaded by the dispatched GitHub Actions job, so there is a short window after a Windows release where the mac/Linux manifest is not yet present (the client just reports "manifest not found" until the workflow finishes).
- Verifies asset SHA-256 before apply. Windows also verifies the signed executable (Authenticode); macOS does a best-effort `codesign --verify`; Linux relies on SHA-256.
- Windows uses `update_helper.bat`; macOS/Linux use `update_helper.sh`.
- Windows helper must close/wait for BlindRSS processes launched from the install directory, verify key install files are unlocked, and verify the old install was fully moved before applying staged files. If locks remain, abort before destructive overlay and roll back/restart cleanly.
- POSIX helper waits for the app PID to exit, backs up the install target, swaps in the staged build (macOS `.app` bundle via `ditto`; Linux install dir, restoring in-dir user data such as `config.json`/`rss.db*`/`podcasts`/`sounds`), relaunches, and rolls back on failure. It is run from a temp copy so the swap cannot delete it mid-run.

### 6. Cross-Platform Packaging
- `build.sh` bundles `yt-dlp`, `deno`, `ffmpeg`, and VLC runtime files outside Windows (macOS and Linux).
- macOS builds are ad-hoc signed for free with `codesign` unless disabled.
- Linux builds require system VLC (`vlc` + `libvlc-dev`) and ffmpeg; `portable.spec` bundles `libvlc.so*` and the VLC plugins dir, overridable via `BLINDRSS_VLC_LIB_DIR` / `BLINDRSS_VLC_PLUGINS`. Output is a `tar.gz` (preserves the executable bit), not a `.app`.

## Build Quality
- When building, always fix any warnings, bugs, or errors you can before considering the build complete.
- Pytest is configured by `pytest.ini` to use `.tmp_test/pytest` as its base temp directory. Keep this repo-local temp base so Windows machines with broken or inaccessible global pytest temp folders can still run the full suite reliably.

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
