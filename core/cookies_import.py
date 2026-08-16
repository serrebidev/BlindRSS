# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Helpers for importing a browser-exported cookies.txt (Netscape jar).

Chromium v127+ App-Bound Encryption blocks BlindRSS and yt-dlp from reading
Chrome/Edge/Brave cookies directly on Windows, so the practical path for those
browsers is: the user exports a cookies.txt with a browser extension (e.g.
"Get cookies.txt LOCALLY"), then BlindRSS auto-detects that export. YouTube
cookies are provided to yt-dlp, and every valid export is also merged into the
per-site HTTP cookie jar.

These functions are intentionally GUI-free and side-effect-light so they can be
unit tested without wx. The Settings dialog wires them to a button.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time

log = logging.getLogger(__name__)

# Cookie jars are tiny; cap reads so a mis-detected huge .txt can't be slurped.
_MAX_JAR_BYTES = 4 * 1024 * 1024
# How recent an export must be (seconds) to be treated as "the one the user just made".
DEFAULT_MAX_AGE_S = 15 * 60
IMPORTED_COOKIE_FILENAME = "youtube_cookies.txt"

# Domains that indicate the export actually carries a YouTube/Google login.
_YOUTUBE_DOMAINS = ("youtube.com", "google.com")

# Header comments BlindRSS writes into the jars it manages itself. The export
# scan also watches the directory of the configured cookie file, which is the
# app data dir by default -- so without this check it re-"discovered" its own
# site_cookies.txt as a fresh browser export every time the browser harvest
# rewrote it, copied all 490 sites' cookies over the yt-dlp jar, and fired a
# "cookies updated" notification on every watcher tick (issue #101).
_MANAGED_JAR_MARKERS = (
    "# Imported by BlindRSS",
    "# Harvested from installed browsers by BlindRSS",
)


def is_blindrss_managed_jar(text: str) -> bool:
    """True when this cookies.txt is one BlindRSS wrote, not a browser export."""
    head = str(text or "")[:512]
    return any(marker in head for marker in _MANAGED_JAR_MARKERS)


def _read_text(path: str) -> str | None:
    try:
        if os.path.getsize(path) > _MAX_JAR_BYTES:
            return None
    except OSError:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _iter_cookie_records(text: str):
    """Yield the tab-split fields of each Netscape cookie data line."""
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        # Comments are '#'-prefixed, except the special '#HttpOnly_' domain marker.
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        fields = line.split("\t")
        if len(fields) >= 7:
            yield fields


def is_netscape_cookie_jar(text: str) -> bool:
    """True when the text parses as a Netscape/Mozilla cookie jar."""
    if not text:
        return False
    for fields in _iter_cookie_records(text):
        domain = fields[0].lstrip("#").replace("HttpOnly_", "", 1).strip()
        expiry = fields[4].strip()
        # A real record has a domain-ish first field and a numeric expiry column.
        if domain and "." in domain and (expiry.isdigit() or expiry == "0"):
            return True
    return False


def cookie_jar_domains(text: str) -> set[str]:
    domains: set[str] = set()
    for fields in _iter_cookie_records(text):
        domain = fields[0].lstrip("#")
        if domain.startswith("HttpOnly_"):
            domain = domain[len("HttpOnly_"):]
        domain = domain.lstrip(".").strip().lower()
        if domain:
            domains.add(domain)
    return domains


def cookie_jar_has_youtube(text: str) -> bool:
    for domain in cookie_jar_domains(text):
        if any(domain == d or domain.endswith("." + d) for d in _YOUTUBE_DOMAINS):
            return True
    return False


def validate_cookie_file(path: str) -> tuple[bool, str]:
    """Return (ok, message). ok means the file is a usable YouTube cookie jar."""
    if not path or not os.path.isfile(path):
        return False, "File not found."
    text = _read_text(path)
    if text is None:
        return False, "Could not read the file (too large or unreadable)."
    if not is_netscape_cookie_jar(text):
        return False, "This does not look like a Netscape cookies.txt export."
    if not cookie_jar_has_youtube(text):
        return False, "No YouTube/Google login cookies found in this file."
    return True, "Looks like a valid YouTube cookie export."


def _is_importable_export(path: str) -> bool:
    """True when `path` is a browser export we should import, not our own jar."""
    text = _read_text(path)
    if text is None or is_blindrss_managed_jar(text):
        return False
    return is_netscape_cookie_jar(text) and cookie_jar_has_youtube(text)


def default_download_dirs(extra_dirs: list[str] | None = None) -> list[str]:
    """Likely locations of a freshly exported cookies.txt, newest-intent first."""
    dirs: list[str] = []

    def _add(d: str | None) -> None:
        if not d:
            return
        try:
            ap = os.path.abspath(d)
        except Exception:
            return
        if os.path.isdir(ap) and ap not in dirs:
            dirs.append(ap)

    for d in extra_dirs or []:
        _add(d)
    home = os.path.expanduser("~")
    _add(os.path.join(home, "Downloads"))
    _add(os.environ.get("USERPROFILE") and os.path.join(os.environ["USERPROFILE"], "Downloads"))
    _add(home)
    return dirs


def find_latest_youtube_cookie_export(
    search_dirs: list[str],
    *,
    since_ts: float | None = None,
    max_age_s: float = DEFAULT_MAX_AGE_S,
    now: float | None = None,
) -> str | None:
    """Newest .txt across search_dirs that validates as a YouTube cookie jar.

    Only files modified after `since_ts` (if given) and within `max_age_s` of
    `now` are considered, so we pick up the export the user just made rather than
    a stale unrelated text file.
    """
    now_ts = time.time() if now is None else now
    cutoff = now_ts - max_age_s
    if since_ts is not None:
        cutoff = max(cutoff, since_ts)

    best_path: str | None = None
    best_mtime = -1.0
    seen: set[str] = set()
    for d in search_dirs or []:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".txt"):
                continue
            path = os.path.join(d, name)
            ap = os.path.abspath(path)
            if ap in seen:
                continue
            seen.add(ap)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime < cutoff or mtime <= best_mtime:
                continue
            if _is_importable_export(path):
                best_path = path
                best_mtime = mtime
    return best_path


def import_cookie_file(src_path: str, dest_dir: str) -> str:
    """Copy a validated cookie jar into dest_dir as the app's managed cookie file.

    Returns the destination path. Raises ValueError if the source is not a valid
    YouTube cookie jar, or OSError if the copy fails.
    """
    ok, message = validate_cookie_file(src_path)
    if not ok:
        raise ValueError(message)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, IMPORTED_COOKIE_FILENAME)
    # If the user re-exports to the same managed path, copying onto itself is a no-op.
    if os.path.abspath(src_path) != os.path.abspath(dest_path):
        shutil.copyfile(src_path, dest_path)
    return dest_path


def auto_import_youtube_cookies(
    config_manager,
    data_dir: str,
    *,
    search_dirs: list[str] | None = None,
    now: float | None = None,
) -> str | None:
    """Detect a freshly exported YouTube cookies.txt and import it, hands-free.

    Returns the imported destination path when a new export was imported, else
    None. Persists the source mtime (`ytdlp_cookies_last_import_mtime`) so the
    same export is never imported twice and the user's own newer export always
    wins. Honors the `auto_import_browser_cookies` setting.
    """
    try:
        if not bool(config_manager.get("auto_import_browser_cookies", True)):
            return None
    except Exception:
        return None

    try:
        last_mtime = float(config_manager.get("ytdlp_cookies_last_import_mtime", 0) or 0)
    except (TypeError, ValueError):
        last_mtime = 0.0

    managed_path = os.path.join(data_dir, IMPORTED_COOKIE_FILENAME)
    extra_dirs: list[str] = []
    try:
        current = str(config_manager.get("ytdlp_cookies_file", "") or "").strip()
        if current:
            extra_dirs.append(os.path.dirname(current))
    except Exception:
        current = ""

    dirs = search_dirs if search_dirs is not None else default_download_dirs(extra_dirs)
    # since_ts gates on the last import; the recency window still guards the very
    # first run so we don't import an ancient unrelated jar sitting in Downloads.
    found = find_latest_youtube_cookie_export(
        dirs, since_ts=(last_mtime or None), now=now
    )
    if not found:
        return None

    # Never re-import our own managed file.
    if os.path.abspath(found) == os.path.abspath(managed_path):
        return None
    try:
        src_mtime = os.path.getmtime(found)
    except OSError:
        return None
    if src_mtime <= last_mtime:
        return None

    try:
        dest = import_cookie_file(found, data_dir)
    except (ValueError, OSError) as e:
        log.debug("Auto cookie import skipped (%s): %s", found, e)
        return None

    try:
        config_manager.set("ytdlp_cookies_file", dest)
        config_manager.set("ytdlp_cookies_last_import_mtime", src_mtime)
    except Exception:
        log.exception("Failed to persist auto-imported cookie settings")
        return None

    log.info("Auto-imported YouTube cookies from %s", found)
    return dest


class CookieImportWatcher:
    """Background poller that auto-imports freshly exported cookie jars.

    Every tick it checks Downloads twice: a YouTube-login export goes to the
    yt-dlp cookie file, and ANY fresh cookies.txt export (e.g.
    ``example.com_cookies.txt`` from the "Get cookies.txt LOCALLY" extension)
    is merged into the site cookie jar so challenge-protected sites start
    working hands-free (issue #79). Lightweight: it only lists a couple of
    directories and reads tiny .txt files. Stops cleanly on `stop()`.
    """

    def __init__(self, config_manager, data_dir: str, *, interval_s: float = 45.0,
                 on_import=None, on_site_import=None, on_browser_import=None):
        self._config_manager = config_manager
        self._data_dir = data_dir
        self._interval_s = max(10.0, float(interval_s))
        self._on_import = on_import
        self._on_site_import = on_site_import
        self._on_browser_import = on_browser_import
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._full_harvest_inflight = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="CookieImportWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # The scan itself runs on this background thread, so check immediately:
        # an export already in Downloads must be ready before the user reaches a
        # feed that needs it. Subsequent checks retain the bounded cadence.
        while not self._stop.is_set():
            try:
                dest = auto_import_youtube_cookies(self._config_manager, self._data_dir)
            except Exception:
                log.exception("Cookie import watcher tick failed")
                dest = None
            if dest and self._on_import:
                try:
                    self._on_import(dest)
                except Exception:
                    log.exception("Cookie import on_import callback failed")
            try:
                from core import site_cookies
                site_src = site_cookies.auto_import_downloads(self._config_manager)
            except Exception:
                log.exception("Site cookie import watcher tick failed")
                site_src = None
            # Browsers whose cookie store we can read directly need no export
            # step at all; refresh their bot-check clearance in the same pass.
            try:
                from core import site_cookies
                site_cookies.auto_import_browser_profiles(self._config_manager)
            except Exception:
                log.exception("Browser-profile clearance import tick failed")
            # Full session-cookie import from installed browsers (Firefox +
            # Chromium incl. v20) runs on its own thread so a one-time UAC
            # elevation never delays the Downloads/clearance scans above.
            self._maybe_start_full_browser_harvest()
            if site_src and self._on_site_import:
                try:
                    self._on_site_import(site_src)
                except Exception:
                    log.exception("Cookie import on_site_import callback failed")
            if self._stop.wait(self._interval_s):
                break

    def _maybe_start_full_browser_harvest(self) -> None:
        if self._full_harvest_inflight:
            return
        self._full_harvest_inflight = True
        try:
            threading.Thread(
                target=self._full_browser_harvest_worker,
                daemon=True,
                name="BrowserCookieHarvest",
            ).start()
        except Exception:
            self._full_harvest_inflight = False
            log.exception("Could not start the full browser cookie harvest")

    def _full_browser_harvest_worker(self) -> None:
        stats = None
        try:
            from core import site_cookies

            stats = site_cookies.auto_import_installed_browser_cookies(self._config_manager)
        except Exception:
            log.exception("Full browser cookie harvest tick failed")
        finally:
            self._full_harvest_inflight = False
        # Notify only when the harvest actually brought something new in.
        # Reporting every pass meant a "cookies updated" toast on every watcher
        # tick for as long as a browser was open (issue #101).
        if stats and stats.get("new") and self._on_browser_import:
            try:
                self._on_browser_import(stats)
            except Exception:
                log.exception("Cookie import on_browser_import callback failed")
