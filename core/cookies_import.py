"""Helpers for importing a browser-exported cookies.txt (Netscape jar).

Chromium v127+ App-Bound Encryption blocks yt-dlp from reading Chrome/Edge/Brave
cookies directly on Windows, so the practical path for those browsers is: the user
exports a cookies.txt with a browser extension (e.g. "Get cookies.txt LOCALLY"),
then BlindRSS auto-detects that export and points yt-dlp at it.

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
            ok, _ = validate_cookie_file(path)
            if ok:
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
    """Background poller that auto-imports freshly exported YouTube cookies.

    Lightweight: it only lists a couple of directories and reads tiny .txt files
    on each tick. Stops cleanly on `stop()`.
    """

    def __init__(self, config_manager, data_dir: str, *, interval_s: float = 45.0, on_import=None):
        self._config_manager = config_manager
        self._data_dir = data_dir
        self._interval_s = max(10.0, float(interval_s))
        self._on_import = on_import
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="CookieImportWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # Wait one interval before the first check so startup isn't busier.
        while not self._stop.wait(self._interval_s):
            try:
                dest = auto_import_youtube_cookies(self._config_manager, self._data_dir)
            except Exception:
                log.exception("Cookie import watcher tick failed")
                continue
            if dest and self._on_import:
                try:
                    self._on_import(dest)
                except Exception:
                    log.exception("Cookie import on_import callback failed")
