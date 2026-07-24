# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Last-resort real-browser retrieval for feeds that normal HTTP cannot fetch.

SeleniumBase is imported lazily and is never involved in the normal refresh
path. The UC/CDP Chromium session always uses SeleniumBase's ``headless2``
mode so no browser window, taskbar button, or user interaction is exposed.

The entry point fails closed.  It returns a small requests-compatible response
only after the browser body has been structurally validated as RSS, Atom, CDF,
or JSON Feed; browser errors, ordinary HTML pages, and missing optional runtime
pieces all return ``None``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from core import config as config_mod


log = logging.getLogger(__name__)

_FETCH_LOCK = threading.Lock()
_RUNTIME_DIRNAME = "feed_browser_runtime"
_PROFILE_DIRNAME = "feed_browser_profile"
_MAX_PAGE_SOURCE_CHARS = 30 * 1024 * 1024
_RUNTIME_FAILURE_COOLDOWN_SECONDS = 300.0
_runtime_unavailable_until = 0.0

# A URL whose browser attempt genuinely ran and still produced no feed is not
# retried in the browser for this long. Refresh cycles over a large collection
# would otherwise pay the same serialized Chromium launch for the same failing
# feed on every cycle (issue #79 follow-up: a several-hundred-feed refresh went
# from ~9 to ~21 minutes). Only the refresh path (fetch_feed) records and
# honors this; user-initiated page detection must always be allowed to retry.
_NEGATIVE_RESULT_COOLDOWN_SECONDS = 6 * 3600.0
_MAX_NEGATIVE_RESULTS = 512
_negative_results: dict[str, float] = {}
_negative_results_lock = threading.Lock()


def _negative_result_active(url: str) -> bool:
    with _negative_results_lock:
        return time.monotonic() < _negative_results.get(url, 0.0)


def _record_negative_result(url: str) -> None:
    now = time.monotonic()
    with _negative_results_lock:
        if len(_negative_results) >= _MAX_NEGATIVE_RESULTS:
            for key in [k for k, until in _negative_results.items() if until <= now]:
                _negative_results.pop(key, None)
            if len(_negative_results) >= _MAX_NEGATIVE_RESULTS:
                _negative_results.clear()
        _negative_results[url] = now + _NEGATIVE_RESULT_COOLDOWN_SECONDS


def _clear_negative_result(url: str) -> None:
    with _negative_results_lock:
        _negative_results.pop(url, None)


def _local_name(tag) -> str:
    text = str(tag or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text.lower()


def _looks_like_feed_text(text: str) -> bool:
    """Return True only for a structurally recognizable feed document."""
    body = str(text or "").lstrip("\ufeff\x00 \t\r\n")
    if not body:
        return False

    if body.startswith("{"):
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        version = str(payload.get("version") or "")
        return version.startswith("https://jsonfeed.org/version/") and isinstance(
            payload.get("items", []), list
        )

    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        return False
    return _local_name(root.tag) in {"rss", "rdf", "feed", "channel"}


def _feed_text_from_page_source(page_source: str) -> str | None:
    """Extract the raw feed text Chromium displays inside its ``pre`` wrapper."""
    source = str(page_source or "")
    if not source or len(source) > _MAX_PAGE_SOURCE_CHARS:
        return None
    if _looks_like_feed_text(source):
        return source

    try:
        soup = BeautifulSoup(source, "html.parser")
        pre = soup.find("pre")
        candidate = pre.get_text() if pre is not None else ""
    except Exception:
        return None
    return candidate if _looks_like_feed_text(candidate) else None


@dataclass
class BrowserPageResponse:
    """Minimal requests.Response-compatible value returned by browser fetches."""

    text: str
    url: str
    status_code: int = 200
    headers: dict = field(
        default_factory=lambda: {"Content-Type": "text/html; charset=utf-8"}
    )
    history: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.content = self.text.encode("utf-8")
        self.response = self

    def raise_for_status(self) -> None:
        return None


@dataclass
class BrowserFeedResponse(BrowserPageResponse):
    """Requests-compatible browser response containing a validated feed."""

    headers: dict = field(
        default_factory=lambda: {"Content-Type": "application/rss+xml; charset=utf-8"}
    )


def _looks_like_challenge_page(page_source: str) -> bool:
    """Recognize common browser-verification documents regardless of HTTP status."""
    text = str(page_source or "")[:200000].casefold()
    markers = (
        "challenges.cloudflare.com",
        "just a moment...",
        "_cf_chl_opt",
        "cf-chl-",
        "performing security verification",
        "verify you are human",
    )
    return any(marker in text for marker in markers)


def _google_chrome_available() -> bool:
    names = ("google-chrome", "google-chrome-stable", "chrome", "chrome.exe")
    if any(shutil.which(name) for name in names):
        return True

    candidates = []
    if sys.platform.startswith("win"):
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        candidates.extend(("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"))
    return any(os.path.isfile(path) for path in candidates)


def _redirect_seleniumbase_work_files(runtime_dir: str) -> None:
    """Move SeleniumBase's cwd-relative locks/downloads into writable storage."""
    from seleniumbase.fixtures import constants as sb_constants

    work_dir = os.path.join(runtime_dir, "work")
    os.makedirs(work_dir, exist_ok=True)
    sb_constants.Files.DOWNLOADS_FOLDER = work_dir
    # These values are computed from Files.DOWNLOADS_FOLDER at import time, so
    # update the cached paths too. In an installed Windows build the process
    # cwd may be Program Files and must never receive runtime lock files.
    for group_name in ("MultiBrowser", "PipInstall", "Dashboard", "Report"):
        group = getattr(sb_constants, group_name, None)
        if group is None:
            continue
        for name, value in vars(group).items():
            if name.isupper() and isinstance(value, str) and value.endswith(".lock"):
                setattr(group, name, os.path.join(work_dir, os.path.basename(value)))


def _browser_options(profile_dir: str, proxy: str | None) -> dict:
    """Build mandatory fully automated, invisible SeleniumBase options.

    Nothing here depends on a per-call timeout, so one live session serves every
    fetch (see _session_locked). Deadlines are enforced by the caller instead.

    We want the DOM, never the pixels: `block_images` drops the heaviest requests a
    page makes, and the `eager` load strategy hands control back at DOMContentLoaded
    rather than waiting on trailing subresources.

    Deliberately NOT `ad_block_on`: it unpacks its extension into a `downloaded_files`
    directory beside the process cwd, which _redirect_seleniumbase_work_files does not
    catch, and in an installed build that cwd is Program Files.
    """
    options = {
        "uc": True,
        "headless2": True,
        "test": False,
        "locale": "en",
        "user_data_dir": profile_dir,
        "no_screenshot": True,
        "block_images": True,
        "page_load_strategy": "eager",
    }
    if not _google_chrome_available():
        options["cft"] = True
    if proxy:
        options["proxy"] = str(proxy).strip()
    return options


def _cancelled(cancel_event) -> bool:
    try:
        return bool(cancel_event and cancel_event.is_set())
    except Exception:
        return False


def _acquire_fetch_lock(timeout_s: float, cancel_event=None) -> bool:
    deadline = time.monotonic() + max(1.0, float(timeout_s or 1.0))
    while not _cancelled(cancel_event):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if _FETCH_LOCK.acquire(timeout=min(0.25, remaining)):
            return True
    return False


# Launching Chromium costs ~8s, dwarfing the ~4.5s navigation and ~2.5s challenge
# settle that follow it. Paying that per article made a refresh that touched
# several gated pages crawl, so the session is kept warm and reused. Every access
# happens under _FETCH_LOCK, which already serializes browser work.
_SESSION_IDLE_SECONDS = 120.0
_SESSION_REAP_INTERVAL = 15.0
_session = None  # (context_manager, sb) while a browser is live
_session_options: dict | None = None
_session_expires_at = 0.0
_reaper_started = False


def _close_session_locked() -> None:
    """Shut the live browser down. Caller holds _FETCH_LOCK."""
    global _session, _session_options, _session_expires_at
    session, _session = _session, None
    _session_options = None
    _session_expires_at = 0.0
    if session is None:
        return
    try:
        session[0].__exit__(None, None, None)
    except Exception:
        log.debug("Ignoring error while closing the browser session", exc_info=True)


def _reap_idle_sessions() -> None:
    """Close a warm browser once it has gone unused, so Chromium never lingers."""
    while True:
        time.sleep(_SESSION_REAP_INTERVAL)
        if _session is None:
            continue
        if not _FETCH_LOCK.acquire(timeout=0.5):
            continue  # a fetch is in flight; it will refresh the deadline anyway
        try:
            if _session is not None and time.monotonic() >= _session_expires_at:
                log.info("Closing idle automated browser session")
                _close_session_locked()
        finally:
            _FETCH_LOCK.release()


def _start_reaper_locked() -> None:
    global _reaper_started
    if _reaper_started:
        return
    _reaper_started = True
    threading.Thread(
        target=_reap_idle_sessions, name="browser-session-reaper", daemon=True
    ).start()


def _session_locked(SB, options: dict):
    """Return a live ``sb``, reusing the warm one when its options still match."""
    global _session, _session_options, _session_expires_at
    if _session is not None and _session_options != options:
        _close_session_locked()
    if _session is None:
        context = SB(**options)
        _session = (context, context.__enter__())
        _session_options = dict(options)
        _start_reaper_locked()
    _session_expires_at = time.monotonic() + _SESSION_IDLE_SECONDS
    return _session[1]


def shutdown() -> None:
    """Close any warm browser session (called on application exit)."""
    acquired = _FETCH_LOCK.acquire(timeout=10.0)
    try:
        _close_session_locked()
    finally:
        if acquired:
            _FETCH_LOCK.release()


def _harvest_clearance(sb, url: str) -> None:
    """Save the challenge clearance this session just won, with its exact UA.

    Getting here means the browser cleared whatever gate the page had, which is
    the one thing no HTTP client can do for an interactive challenge. Handing
    the cookie to `site_cookies` lets the cheap fetch paths reuse it until it
    lapses, instead of launching Chromium again for the same site minutes later.

    Best-effort throughout: a failure here must never turn a successful fetch
    into a failed one.
    """
    try:
        from core import site_cookies
    except Exception:
        return
    try:
        cookies = sb.cdp.get_all_cookies()
    except Exception:
        log.debug("Could not read cookies from the browser session", exc_info=True)
        return
    user_agent = ""
    try:
        user_agent = str(sb.cdp.get_user_agent() or "").strip()
    except Exception:
        log.debug("Could not read the browser User-Agent", exc_info=True)
    try:
        site_cookies.record_browser_session(url, cookies, user_agent)
    except Exception:
        log.debug("Could not store the browser clearance cookies", exc_info=True)


def _current_browser_url(sb, fallback: str) -> str:
    for getter in (
        lambda: sb.get_current_url(),
        lambda: sb.cdp.get_current_url(),
    ):
        try:
            value = str(getter() or "").strip()
            if value:
                return value
        except Exception:
            continue
    return fallback


# A page is polled until it settles rather than slept on for a fixed 2s + 3s + 3s.
# Chromium hands over a near-empty document between the challenge clearing and the
# real navigation (measured: a 636-byte body one poll before the 346 KB article), so
# "not a challenge page" alone is not enough to accept — a page must also carry
# enough markup to be a document at all.
_SETTLE_POLL_SECONDS = 0.35
_SETTLE_MAX_SECONDS = 25.0
_MIN_USABLE_PAGE_CHARS = 2048
# Give the interstitial time to render its widget before the first click attempt,
# then keep trying while it is still up.
_SOLVE_FIRST_DELAY_SECONDS = 2.0
_SOLVE_RETRY_SECONDS = 3.0


def _usable_document(source: str, *, feed_only: bool) -> str | None:
    """Return the usable text of `source`, or None while the page is still settling."""
    if not source or len(source) > _MAX_PAGE_SOURCE_CHARS:
        return None
    if feed_only:
        # Structural feed validation is its own sufficient check.
        return _feed_text_from_page_source(source)
    if len(source) < _MIN_USABLE_PAGE_CHARS or _looks_like_challenge_page(source):
        return None
    return source


def _settle_page(sb, *, timeout_s: float, feed_only: bool, cancel_event) -> str | None:
    """Poll the loading page until it is usable, then return its text.

    ``solve_captcha`` is retried on a slow cadence for as long as a challenge is on
    screen, never once: the widget it clicks does not exist yet at the moment the
    interstitial first appears, so a single early call reliably misses it. It is a
    no-op when the page has no supported challenge, so the common path pays nothing
    and keeps polling at full speed.
    """
    deadline = time.monotonic() + min(max(float(timeout_s or 30.0), 5.0), _SETTLE_MAX_SECONDS)
    next_solve_at = time.monotonic() + _SOLVE_FIRST_DELAY_SECONDS
    while not _cancelled(cancel_event):
        try:
            source = str(sb.get_page_source() or "")
        except Exception:
            source = ""
        text = _usable_document(source, feed_only=feed_only)
        if text is not None:
            return text
        if time.monotonic() >= deadline:
            return None
        now = time.monotonic()
        if source and now >= next_solve_at and _looks_like_challenge_page(source):
            next_solve_at = now + _SOLVE_RETRY_SECONDS
            try:
                sb.solve_captcha()
            except Exception:
                log.debug("solve_captcha failed; continuing to poll", exc_info=True)
        time.sleep(_SETTLE_POLL_SECONDS)
    return None


def _fetch_browser_document(
    url: str,
    *,
    timeout_s: float = 90.0,
    proxy: str | None = None,
    cancel_event=None,
    feed_only: bool,
    remember_failures: bool = False,
) -> BrowserPageResponse | None:
    """Fetch a browser document, optionally requiring a validated feed.

    Calls are serialized because SeleniumBase's UC driver installer/cache and
    GUI challenge click are process-global.  The persistent per-user profile
    keeps clearance cookies between refreshes.  When Google Chrome is absent,
    SeleniumBase downloads Chrome-for-Testing into the writable BlindRSS data
    directory on the first fallback attempt.
    """
    global _runtime_unavailable_until

    target = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(target)
    except Exception:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    if _cancelled(cancel_event) or time.monotonic() < _runtime_unavailable_until:
        return None
    if remember_failures and _negative_result_active(target):
        log.info("Skipping automated browser fetch during failure cooldown url=%s", target)
        return None

    timeout_s = max(15.0, min(float(timeout_s or 90.0), 180.0))
    if not _acquire_fetch_lock(timeout_s, cancel_event=cancel_event):
        return None

    try:
        if _cancelled(cancel_event):
            return None
        try:
            from seleniumbase import SB
            from seleniumbase.core import browser_launcher
        except Exception:
            log.warning("Browser feed fallback is unavailable because SeleniumBase could not be imported")
            _runtime_unavailable_until = time.monotonic() + _RUNTIME_FAILURE_COOLDOWN_SECONDS
            return None

        data_dir = config_mod.get_data_dir()
        runtime_dir = os.path.join(data_dir, _RUNTIME_DIRNAME)
        profile_dir = os.path.join(data_dir, _PROFILE_DIRNAME)
        try:
            os.makedirs(runtime_dir, exist_ok=True)
            os.makedirs(profile_dir, exist_ok=True)
            browser_launcher.override_driver_dir(runtime_dir)
            _redirect_seleniumbase_work_files(runtime_dir)
        except OSError:
            log.exception("Could not prepare the browser feed fallback directories")
            _runtime_unavailable_until = time.monotonic() + _RUNTIME_FAILURE_COOLDOWN_SECONDS
            return None

        options = _browser_options(profile_dir, proxy)

        log.info("Attempting automated browser feed fallback url=%s", target)
        text = None
        final_url = target
        # A warm session can still have been killed off-process (crash, driver
        # restart), and that only shows up on use. One retry from scratch covers it.
        for attempt in range(2):
            reused = _session is not None
            try:
                sb = _session_locked(SB, options)
                sb.activate_cdp_mode(target)
                text = _settle_page(
                    sb,
                    timeout_s=timeout_s,
                    feed_only=feed_only,
                    cancel_event=cancel_event,
                )
                if text is not None:
                    final_url = _current_browser_url(sb, target)
                    _harvest_clearance(sb, final_url)
                break
            except Exception:
                _close_session_locked()
                if attempt == 0 and reused:
                    log.info("Warm browser session was unusable; retrying with a fresh one")
                    continue
                log.exception("Automated browser feed fallback failed for %s", target)
                if remember_failures and not _cancelled(cancel_event):
                    _record_negative_result(target)
                return None

        if text is not None:
            log.info(
                "Automated browser %s fallback succeeded bytes=%s url=%s",
                "feed" if feed_only else "page",
                len(text.encode("utf-8")),
                final_url,
            )
            _clear_negative_result(target)
            response_type = BrowserFeedResponse if feed_only else BrowserPageResponse
            return response_type(text=text, url=final_url)

        log.info(
            "Automated browser fallback returned no usable %s url=%s",
            "feed" if feed_only else "page",
            target,
        )
        if remember_failures:
            _record_negative_result(target)
        return None
    finally:
        _FETCH_LOCK.release()


def fetch_feed(
    url: str,
    *,
    timeout_s: float = 90.0,
    proxy: str | None = None,
    cancel_event=None,
) -> BrowserFeedResponse | None:
    """Fetch a feed through the browser and return it only after validation.

    Attempts that genuinely ran the browser and still produced no feed start a
    per-URL cooldown so refresh cycles do not repeat the launch back to back.
    """
    response = _fetch_browser_document(
        url,
        timeout_s=timeout_s,
        proxy=proxy,
        cancel_event=cancel_event,
        feed_only=True,
        remember_failures=True,
    )
    return response if isinstance(response, BrowserFeedResponse) else None


def fetch_page(
    url: str,
    *,
    timeout_s: float = 90.0,
    proxy: str | None = None,
    cancel_event=None,
    remember_failures: bool = False,
) -> BrowserPageResponse | None:
    """Fetch a webpage after automatically completing a browser challenge.

    ``remember_failures`` starts the per-URL cooldown on a genuine failure, for
    repeating callers (full-text extraction) that would otherwise pay the
    serialized Chromium launch again for a permanently blocked page. It stays
    off for one-shot, user-initiated detection, which must always retry.
    """
    return _fetch_browser_document(
        url,
        timeout_s=timeout_s,
        proxy=proxy,
        cancel_event=cancel_event,
        feed_only=False,
        remember_failures=remember_failures,
    )
