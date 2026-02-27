Install anything you need.

You are a python expert skilled in yt-dlp, ffmpeg, and rss.

# BlindRSS Architecture & Dev Guide

## System Overview
- Stack: Python 3.13, wxPython (GUI), SQLite (storage), feedparser + requests.
- Entry: `main.py` -> `core.factory` -> `gui.mainframe`.
- Build: PyInstaller directory distribution (`main.spec` -> `dist/BlindRSS/BlindRSS.exe`).
- App version source: `core/version.py`.

## Build & Release
- Full build/release instructions are in `build.md`.
- Mandatory release protocol: always use `.\build.bat release`.
- Never publish manually from GitHub UI/CLI without generating artifacts via `build.bat release` first.

## File Structure & Responsibilities
- `main.py`
  - App bootstrap, dependency checks, provider creation, and main frame startup.
  - Starts UI and refresh work without blocking startup.

- `core/`
  - `db.py`: SQLite schema setup/migrations, WAL/busy timeout pragmas, connection helpers, retention cleanup.
    - Includes tables: `feeds`, `articles`, `chapters`, `categories`, `playback_state`.
  - `utils.py`: Critical helpers.
    - `HEADERS` and request helpers (`safe_requests_get` / `safe_requests_head`).
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
  - `audio_silence.py`: Silence scanning/detection pipeline used by skip-silence playback.
  - `playback_state.py`: Resume position persistence and lock-safe playback state writes.
  - `updater.py`: GitHub release check, manifest/hash verification, Authenticode verification, update handoff to `update_helper.bat`.
  - `windows_integration.py`: Windows startup registration and shortcut creation helpers.
  - `dependency_check.py`: Dependency/path handling and media tool availability logic.
  - `config.py`: Config defaults + migrations; paths are exe-relative when frozen.
  - `factory.py`: Provider wiring; initializes DB.

- `gui/`
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
  - `miniflux.py`, `inoreader.py`, `theoldreader.py`, `bazqux.py`: Hosted provider implementations.
  - Favorites are supported across providers through `supports_favorites` / `set_favorite` / `toggle_favorite`.
  - Inoreader note: `stream/contents` expects URL-encoded `streamId` in path segment, not `s=` query parameter.

## Data Model (`rss.db`)
- `feeds`: `id`, `url`, `title`, `category`, `icon_url`, `etag`, `last_modified`.
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

### 2. UI & Threading
- Startup refresh is backgrounded; tree/list updates are marshaled to main thread via `wx.CallAfter`.
- Main window supports tray minimize/close-to-tray behavior with tray controls.
- Remember-last-feed can restore the last selected feed/folder/special view on startup.

### 3. Media Playback & Caching
- Player opens immediately; media/chapter loads continue asynchronously.
- Optional local range cache proxy can reduce seek latency and improve scrubbing reliability.
- Partial downloaded media chunks are retained for faster rewind/reseek.
- Skip-silence pipeline can analyze media and skip detected silent spans.
- Casting path proxies media for external devices and remuxes when required.

### 4. Full Text & Discovery
- Full-text extraction runs when feed content is missing/partial.
- Discovery dialog aggregates multiple providers in parallel (Apple Podcasts, gPodder, Feedly, NewsBlur, Reddit, Fediverse, Feedsearch, local discovery).
- URL-based media/feed support includes YouTube, Rumble, and Odysee handling.

### 5. Updates (Windows packaged app)
- Checks latest GitHub release + manifest.
- Verifies zip SHA-256 and signed executable before apply.
- Uses helper batch script for safe staged replacement/restart.

## Operational Mandates
1. User-Agent safety: always use `core.utils.safe_requests_get` / `core.utils.HEADERS` for network requests.
2. Date handling: use `core.utils.normalize_date`; trust title/URL-derived dates over feed metadata when mismatched.
3. Performance: use `get_chapters_batch` for lists; avoid per-item DB loops in UI thread.
4. Network safety: in `RangeCacheProxy`, never share `requests.Session` instances across threads.
5. Naming: app name is **BlindRSS**.
6. Timeouts: all provider HTTP requests must set finite timeouts.
7. Inoreader OAuth: HTTPS localhost redirect URIs may require pasted redirect URL flow; validate `state`.
8. Releases: use `.\build.bat release` only (details in `build.md`).
9. Tests: add/extend tests in `tests/` for behavior changes and regressions.
