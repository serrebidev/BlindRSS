# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Last-resort anonymous YouTube session bootstrap through hidden Chromium.

YouTube can return ``Video unavailable`` to every yt-dlp player client while
its real browser player succeeds from the same machine.  The browser receives
a current visitor identity and session cookies as part of normal page startup.
This module obtains those values from BlindRSS's dedicated, fully automated
headless profile and writes a YouTube-only Netscape jar for one final yt-dlp
retry.  It never opens or decrypts the user's Chrome/Edge profile.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass

from core import config as config_mod


log = logging.getLogger(__name__)

_PROFILE_DIRNAME = "youtube_browser_profile"
_COOKIE_FILENAME = "youtube_browser_cookies.txt"
_CACHE_SECONDS = 30 * 60.0
_cache_lock = threading.Lock()
_cached_session = None
_cached_until = 0.0


@dataclass(frozen=True)
class YouTubeBrowserSession:
    cookie_file: str
    visitor_data: str
    user_agent: str = ""
    title: str = ""


def _safe_field(value) -> str:
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _is_youtube_cookie(cookie: dict) -> bool:
    domain = str(cookie.get("domain") or "").strip().lower().lstrip(".")
    return domain in {"youtube.com", "youtube-nocookie.com"} or domain.endswith(
        (".youtube.com", ".youtube-nocookie.com")
    )


def _write_netscape_cookie_file(cookies, path: str) -> str:
    """Atomically write only YouTube cookies returned by the dedicated browser."""
    destination = os.path.abspath(path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temp_path = destination + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Netscape HTTP Cookie File\n")
        stream.write("# Generated from BlindRSS's anonymous YouTube browser profile.\n")
        for cookie in cookies or []:
            if not isinstance(cookie, dict) or not _is_youtube_cookie(cookie):
                continue
            raw_domain = _safe_field(cookie.get("domain"))
            domain = raw_domain
            if cookie.get("httpOnly") and not domain.startswith("#HttpOnly_"):
                domain = "#HttpOnly_" + domain
            try:
                expires = max(
                    0,
                    int(float(cookie.get("expiry") or cookie.get("expires") or 0)),
                )
            except (TypeError, ValueError, OverflowError):
                expires = 0
            stream.write(
                "\t".join(
                    (
                        domain,
                        "TRUE" if raw_domain.startswith(".") else "FALSE",
                        _safe_field(cookie.get("path") or "/"),
                        "TRUE" if cookie.get("secure") else "FALSE",
                        str(expires),
                        _safe_field(cookie.get("name")),
                        _safe_field(cookie.get("value")),
                    )
                )
                + "\n"
            )
    os.replace(temp_path, destination)
    return destination


def _page_identity(sb) -> dict:
    raw = sb.execute_script(
        "JSON.stringify({"
        "visitor:(window.ytcfg?.get('VISITOR_DATA')||''),"
        "status:(window.ytInitialPlayerResponse?.playabilityStatus?.status||''),"
        "title:(window.ytInitialPlayerResponse?.videoDetails?.title||''),"
        "ua:navigator.userAgent})"
    )
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def bootstrap_youtube_session(
    url: str,
    *,
    timeout_s: float = 45.0,
    cancel_event=None,
) -> YouTubeBrowserSession | None:
    """Return a fresh browser-derived anonymous identity for a yt-dlp retry.

    The hidden browser launch is globally serialized with the existing browser
    feed fallback because SeleniumBase's driver/runtime cache is process-global.
    A successful identity is reused briefly within the process so streaming and
    download-to-play do not launch Chromium twice for the same failure.
    """
    global _cached_session, _cached_until

    target = str(url or "").strip()
    if not target:
        return None
    with _cache_lock:
        if _cached_session is not None and time.monotonic() < _cached_until:
            if os.path.isfile(_cached_session.cookie_file):
                return _cached_session

        try:
            timeout_s = max(15.0, min(float(timeout_s or 45.0), 90.0))
        except (TypeError, ValueError):
            timeout_s = 45.0

        try:
            from seleniumbase import SB
            from seleniumbase.core import browser_launcher

            from core import browser_feed
        except Exception:
            log.info("YouTube browser-session fallback is unavailable", exc_info=True)
            return None

        if not browser_feed._acquire_fetch_lock(timeout_s, cancel_event=cancel_event):
            return None
        try:
            if browser_feed._cancelled(cancel_event):
                return None
            data_dir = config_mod.get_data_dir()
            runtime_dir = os.path.join(data_dir, browser_feed._RUNTIME_DIRNAME)
            profile_dir = os.path.join(data_dir, _PROFILE_DIRNAME)
            os.makedirs(runtime_dir, exist_ok=True)
            os.makedirs(profile_dir, exist_ok=True)
            browser_launcher.override_driver_dir(runtime_dir)
            browser_feed._redirect_seleniumbase_work_files(runtime_dir)
            options = browser_feed._browser_options(profile_dir, None)

            sb = None
            deadline = time.monotonic() + timeout_s
            for attempt in range(2):
                reused = browser_feed._session is not None
                try:
                    sb = browser_feed._session_locked(SB, options)
                    sb.activate_cdp_mode(target)
                    break
                except Exception:
                    browser_feed._close_session_locked()
                    if attempt == 0 and reused:
                        continue
                    log.info("Hidden YouTube browser failed to start", exc_info=True)
                    return None

            identity = {}
            while time.monotonic() < deadline and not browser_feed._cancelled(cancel_event):
                try:
                    identity = _page_identity(sb)
                except Exception:
                    identity = {}
                if identity.get("visitor") and identity.get("status"):
                    break
                time.sleep(0.25)

            status = str(identity.get("status") or "").strip().upper()
            visitor_data = str(identity.get("visitor") or "").strip()
            if status != "OK" or not visitor_data:
                log.info(
                    "Hidden YouTube browser did not produce a playable visitor session (status=%s)",
                    status or "missing",
                )
                return None
            if any(char in visitor_data for char in (";", "\r", "\n")):
                log.warning("Hidden YouTube browser returned malformed visitor data")
                return None

            cookies = sb.get_cookies() or []
            cookie_file = _write_netscape_cookie_file(
                cookies,
                os.path.join(data_dir, _COOKIE_FILENAME),
            )
            session = YouTubeBrowserSession(
                cookie_file=cookie_file,
                visitor_data=visitor_data,
                user_agent=str(identity.get("ua") or "").strip(),
                title=str(identity.get("title") or "").strip(),
            )
            _cached_session = session
            _cached_until = time.monotonic() + _CACHE_SECONDS
            log.info("Hidden YouTube browser produced a playable anonymous session")
            return session
        except Exception:
            log.info("YouTube browser-session fallback failed", exc_info=True)
            return None
        finally:
            browser_feed._FETCH_LOCK.release()


def _clear_cache_for_tests() -> None:
    global _cached_session, _cached_until
    with _cache_lock:
        _cached_session = None
        _cached_until = 0.0
