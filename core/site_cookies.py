# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Per-site cookie jar for the HTTP fetch layer (issue #79).

Sites behind an interactive bot check (Cloudflare's "Just a moment..."
interstitial, as on forum.audiogames.net) cannot be fetched by any plain HTTP
client — the challenge requires real JavaScript in a real browser, and TLS
impersonation alone never passes it. The workable client-side approach is to
reuse a browser session that already passed the challenge: the user exports a
Netscape cookies.txt from their browser (same extension workflow as the
YouTube cookie import) and imports it via Tools > Import Site Cookies. Every
``safe_requests_*`` call then attaches the matching cookies (e.g.
``cf_clearance``) — and the browser's own User-Agent string, because
Cloudflare only accepts a clearance cookie together with the exact UA it was
issued to.

The jar lives in the app data dir as ``site_cookies.txt`` with the browser UA
in a ``site_cookies_ua.txt`` sidecar, so this module needs no config-manager
plumbing and stays importable from ``core.utils`` without cycles.
"""

from __future__ import annotations

import configparser
import glob as glob_mod
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import json
import threading
import time
import urllib.parse

from core import config as config_mod
from core.cookies_import import _read_text, is_netscape_cookie_jar, _iter_cookie_records

log = logging.getLogger(__name__)

JAR_FILENAME = "site_cookies.txt"
UA_FILENAME = "site_cookies_ua.txt"
# Per-host User-Agents, for cookies harvested automatically from the headless
# browser. The single UA_FILENAME is the user's own manual entry and applies to
# every site; a harvested clearance belongs to exactly one host and must not
# change the fingerprint the app presents to any other.
HOST_UA_FILENAME = "site_cookies_ua_hosts.json"

_lock = threading.Lock()
_write_lock = threading.Lock()
_cache = {"path": None, "mtime": None, "cookies": [], "ua_mtime": None, "ua": ""}


def jar_path() -> str:
    return os.path.join(config_mod.get_data_dir(), JAR_FILENAME)


def ua_path() -> str:
    return os.path.join(config_mod.get_data_dir(), UA_FILENAME)


def host_ua_path() -> str:
    return os.path.join(config_mod.get_data_dir(), HOST_UA_FILENAME)


def validate_jar_file(path: str) -> tuple[bool, str]:
    """Return (ok, message) for a user-picked cookies.txt (any domains)."""
    if not path or not os.path.isfile(path):
        return False, "File not found."
    text = _read_text(path)
    if text is None:
        return False, "Could not read the file (too large or unreadable)."
    if not is_netscape_cookie_jar(text):
        return False, "This does not look like a Netscape cookies.txt export."
    return True, "Looks like a valid cookie export."


def import_jar(src_path: str) -> str:
    """Merge a validated export into the managed site jar.

    Merging (rather than replacing) means importing cookies for a second site
    never wipes the first site's imported session.
    """
    merge_jar_file(src_path)
    return jar_path()


def set_user_agent(ua: str) -> None:
    """Persist (or clear) the browser User-Agent the cookies belong to."""
    ua = str(ua or "").strip()
    path = ua_path()
    try:
        if ua:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ua + "\n")
        elif os.path.isfile(path):
            os.remove(path)
    except OSError:
        log.exception("Could not persist site-cookies User-Agent")
    _invalidate()


def get_user_agent() -> str:
    try:
        with open(ua_path(), "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _invalidate() -> None:
    with _lock:
        _cache["mtime"] = None
        _cache["ua_mtime"] = None


def _parse_jar(text: str):
    """[(domain, include_subdomains, path, name, value, expires), ...]"""
    out = []
    for fields in _iter_cookie_records(text):
        domain = fields[0].lstrip("#")
        if domain.startswith("HttpOnly_"):
            domain = domain[len("HttpOnly_"):]
        raw_domain = domain.strip().lower()
        include_sub = raw_domain.startswith(".") or fields[1].strip().upper() == "TRUE"
        domain_clean = raw_domain.lstrip(".")
        cookie_path = fields[2].strip() or "/"
        try:
            expires = int(fields[4].strip() or 0)
        except ValueError:
            expires = 0
        name = fields[5]
        value = fields[6]
        if domain_clean and name:
            out.append((domain_clean, include_sub, cookie_path, name, value, expires))
    return out


def _load_cookies():
    path = jar_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    with _lock:
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return _cache["cookies"]
    text = _read_text(path) or ""
    cookies = _parse_jar(text) if is_netscape_cookie_jar(text) else []
    with _lock:
        _cache.update({"path": path, "mtime": mtime, "cookies": cookies})
    return cookies


def _host_matches(host: str, domain: str, include_sub: bool) -> bool:
    if host == domain:
        return True
    return include_sub and host.endswith("." + domain)


def cookies_for(url: str, *, now: float | None = None) -> dict:
    """Unexpired jar cookies applicable to ``url`` as an ordered name->value map."""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
        host = (parts.hostname or "").lower()
        req_path = parts.path or "/"
    except Exception:
        return {}
    if not host:
        return {}
    now_ts = time.time() if now is None else now
    matched = {}
    for domain, include_sub, cookie_path, name, value, expires in _load_cookies():
        if not _host_matches(host, domain, include_sub):
            continue
        if expires and expires < now_ts:
            continue
        if cookie_path not in ("", "/") and not (
            req_path == cookie_path or req_path.startswith(cookie_path.rstrip("/") + "/")
        ):
            continue
        matched[name] = value
    return matched


def cookie_header_for(url: str, *, now: float | None = None) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies_for(url, now=now).items())


def _load_host_user_agents() -> dict:
    try:
        with open(host_ua_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in data.items() if k and v}


def set_host_user_agent(host: str, ua: str) -> None:
    """Record the UA a harvested session for `host` was issued to (or clear it)."""
    host = str(host or "").strip().lower().lstrip(".")
    if not host:
        return
    ua = str(ua or "").strip()
    path = host_ua_path()
    with _write_lock:
        mapping = _load_host_user_agents()
        if ua:
            mapping[host] = ua
        else:
            mapping.pop(host, None)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(mapping, fh, indent=1, sort_keys=True)
        except OSError:
            log.exception("Could not persist the per-host site-cookies User-Agent")
    _invalidate()


def host_user_agent_for(url: str) -> str:
    """The harvested UA registered for this URL's host, matching parent domains."""
    try:
        host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return ""
    if not host:
        return ""
    mapping = _load_host_user_agents()
    # Longest (most specific) suffix wins, so a rule for forum.example.com
    # beats one for example.com.
    best = ""
    for candidate in mapping:
        if host == candidate or host.endswith("." + candidate):
            if len(candidate) > len(best):
                best = candidate
    return mapping.get(best, "")


def has_clearance_for(url: str, *, now: float | None = None) -> bool:
    """True when the jar holds a bot-check clearance cookie for this URL."""
    return any(_is_harvestable(name) for name in cookies_for(url, now=now))


def user_agent_for(url: str, *, now: float | None = None) -> str:
    """The browser UA these cookies belong to, or "" when none should be forced.

    Two separate cases, and conflating them broke unrelated requests:

    * A UA recorded for *this host* (harvested, or read from the profile that
      supplied its clearance) always applies — it was captured deliberately and
      a clearance is only valid for the exact UA that earned it.
    * The user's single global UA is a fallback, and only for hosts that
      actually have a clearance cookie. It used to apply to any host with any
      cookie at all, so a full manual jar import made every GitHub API call go
      out with a Firefox User-Agent and the user's github cookies attached.
      An ordinary login cookie is not fingerprint-bound and needs no UA pin.
    """
    host_ua = host_user_agent_for(url)
    if host_ua:
        return host_ua if cookies_for(url, now=now) else ""
    if not has_clearance_for(url, now=now):
        return ""
    return get_user_agent()


# ---------------------------------------------------------------------------
# Direct browser import (Firefox family)
#
# Firefox-based browsers keep cookies in an UNENCRYPTED profile SQLite
# (cookies.sqlite), so they can be read directly. Chromium browsers on
# Windows use App-Bound Encryption since v127 — unreadable from outside the
# browser — which is why the dialog points Chrome users at the
# "Get cookies.txt LOCALLY" extension instead.
# ---------------------------------------------------------------------------

def _firefox_like_roots():
    """[(browser label, root dir)] for every Firefox-family browser we know."""
    roots = []
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            roots = [
                ("Firefox", os.path.join(appdata, "Mozilla", "Firefox")),
                ("LibreWolf", os.path.join(appdata, "librewolf")),
                ("Waterfox", os.path.join(appdata, "Waterfox")),
                ("Floorp", os.path.join(appdata, "Floorp")),
                ("Zen Browser", os.path.join(appdata, "zen")),
                ("Pale Moon", os.path.join(appdata, "Moonchild Productions", "Pale Moon")),
                ("Thunderbird", os.path.join(appdata, "Thunderbird")),
            ]
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
        roots = [
            ("Firefox", os.path.join(base, "Firefox")),
            ("LibreWolf", os.path.join(base, "librewolf")),
            ("Waterfox", os.path.join(base, "Waterfox")),
            ("Floorp", os.path.join(base, "Floorp")),
            ("Zen Browser", os.path.join(base, "zen")),
        ]
    else:
        home = os.path.expanduser("~")
        roots = [
            ("Firefox", os.path.join(home, ".mozilla", "firefox")),
            ("Firefox (Flatpak)", os.path.join(home, ".var", "app", "org.mozilla.firefox", ".mozilla", "firefox")),
            ("Firefox (Snap)", os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox")),
            ("LibreWolf", os.path.join(home, ".librewolf")),
            ("Waterfox", os.path.join(home, ".waterfox")),
            ("Floorp", os.path.join(home, ".floorp")),
        ]
    return [(label, root) for label, root in roots if os.path.isdir(root)]


def list_browser_profiles():
    """Importable browser profiles, newest cookie database first.

    Returns ``[{"browser", "profile", "path", "mtime"}]`` where ``path`` is
    the profile directory containing cookies.sqlite.
    """
    found = []
    seen = set()
    for label, root in _firefox_like_roots():
        candidates = glob_mod.glob(os.path.join(root, "Profiles", "*", "cookies.sqlite"))
        candidates += glob_mod.glob(os.path.join(root, "*", "cookies.sqlite"))
        for db in candidates:
            profile_dir = os.path.dirname(os.path.abspath(db))
            if profile_dir.lower() in seen:
                continue
            seen.add(profile_dir.lower())
            try:
                mtime = os.path.getmtime(db)
            except OSError:
                continue
            found.append({
                "browser": label,
                "profile": os.path.basename(profile_dir),
                "path": profile_dir,
                "mtime": mtime,
            })
    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found


def _read_firefox_cookies(profile_dir: str):
    """moz_cookies rows as (host, path, secure, http_only, expiry, name, value).

    The live database is locked (and WAL-buffered) while the browser runs, so
    the db + sidecar files are copied to a temp dir and read from the copy.
    """
    src = os.path.join(profile_dir, "cookies.sqlite")
    if not os.path.isfile(src):
        raise OSError("cookies.sqlite not found")
    tmp_dir = tempfile.mkdtemp(prefix="blindrss-cookies-")
    try:
        dst = os.path.join(tmp_dir, "cookies.sqlite")
        shutil.copyfile(src, dst)
        for suffix in ("-wal", "-shm"):
            side = src + suffix
            if os.path.isfile(side):
                try:
                    shutil.copyfile(side, dst + suffix)
                except OSError:
                    pass
        conn = sqlite3.connect(dst)
        try:
            rows = conn.execute(
                "SELECT host, path, isSecure, isHttpOnly, expiry, name, value "
                "FROM moz_cookies"
            ).fetchall()
        finally:
            conn.close()
        out = []
        for host, path, secure, http_only, expiry, name, value in rows:
            host = str(host or "").strip()
            name = str(name or "")
            if host and name:
                out.append((host, str(path or "/"), bool(secure), bool(http_only),
                            int(expiry or 0), name, str(value or "")))
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def firefox_profile_user_agent(profile_dir: str) -> str:
    """A User-Agent string matching the profile's browser version, or "".

    Gecko UAs are fully derivable from the major version in the profile's
    compatibility.ini, and Cloudflare needs the UA to match the session the
    cookies came from.
    """
    ini = os.path.join(profile_dir, "compatibility.ini")
    version = ""
    try:
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        raw = parser.get("Compatibility", "LastVersion", fallback="")
        version = raw.split("_", 1)[0].split(".", 1)[0].strip()
    except Exception:
        version = ""
    if not version.isdigit():
        return ""
    if sys.platform.startswith("win"):
        platform_token = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        platform_token = "Macintosh; Intel Mac OS X 10.15"
    else:
        platform_token = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform_token}; rv:{version}.0) "
        f"Gecko/20100101 Firefox/{version}.0"
    )


def _jar_records():
    """Raw (domain_field, flag, path, secure, expiry, name, value) rows of the managed jar."""
    text = _read_text(jar_path()) or ""
    records = []
    for fields in _iter_cookie_records(text):
        records.append(tuple(fields[:7]))
    return records


def _record_key(fields):
    domain_field = str(fields[0])
    key_domain = domain_field.replace("#HttpOnly_", "", 1).lstrip(".").lower()
    return (key_domain, fields[2], fields[5])


def _merge_records_into_jar(new_records) -> None:
    """Write the managed jar as (existing records) overridden by new_records.

    Existing entries for the same (domain, path, name) are replaced;
    everything else is kept, so importing from a second browser or for a
    second site never wipes an earlier import.
    """
    dest = jar_path()
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)
    temp_path = ""
    with _write_lock:
        merged = {}
        for fields in _jar_records():
            merged[_record_key(fields)] = fields
        for fields in new_records:
            merged[_record_key(fields)] = fields
        fd, temp_path = tempfile.mkstemp(prefix="site-cookies-", suffix=".tmp", dir=dest_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("# Netscape HTTP Cookie File\n")
                fh.write("# Imported by BlindRSS (Import Site Cookies)\n\n")
                for record in merged.values():
                    fh.write("\t".join(str(f) for f in record) + "\n")
            os.replace(temp_path, dest)
            temp_path = ""
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
    _invalidate()


def merge_records_into_jar(records) -> int:
    """Merge raw Netscape 7-field records into the managed site jar.

    Public counterpart to ``_merge_records_into_jar`` for importers outside this
    module (e.g. ``core.chromium_cookies``). Existing entries for the same
    (domain, path, name) are replaced; everything else is kept.
    """
    records = list(records or [])
    if records:
        _merge_records_into_jar(records)
    return len(records)


def merge_jar_file(src_path: str) -> int:
    """Merge a Netscape cookies.txt export into the managed jar.

    Returns the number of records read from the export. Raises ValueError for
    files that are not a cookie jar.
    """
    ok, message = validate_jar_file(src_path)
    if not ok:
        raise ValueError(message)
    text = _read_text(src_path) or ""
    new_records = [tuple(fields[:7]) for fields in _iter_cookie_records(text)]
    _merge_records_into_jar(new_records)
    return len(new_records)


def import_from_browser_profile(profile_dir: str) -> int:
    """Merge a Firefox-family profile's cookies into the managed jar.

    Returns the number of cookies read from the browser.
    """
    rows = _read_firefox_cookies(profile_dir)
    new_records = []
    for host, path, secure, http_only, expiry, name, value in rows:
        domain_field = ("#HttpOnly_" + host) if http_only else host
        flag = "TRUE" if host.startswith(".") else "FALSE"
        new_records.append((
            domain_field, flag, path,
            "TRUE" if secure else "FALSE",
            str(int(expiry)), name, value,
        ))
    _merge_records_into_jar(new_records)
    return len(rows)


def import_clearance_from_browser_profile(profile_dir: str, user_agent: str = "") -> int:
    """Copy only the bot-check clearance cookies out of a browser profile.

    The automatic counterpart to `import_from_browser_profile`. That one is
    user-initiated and takes the whole jar; this runs unattended in the
    background, so it takes only what a bot check needs and leaves the user's
    logins in their browser. Copying every site's session cookie into a
    plaintext file in the app data dir is not a thing to do without being asked.

    `user_agent` is recorded per host for the sites this profile had clearance
    for, because a clearance is only valid for the UA that earned it.
    """
    candidates = _clearance_candidates(profile_dir, user_agent)
    if not candidates:
        return 0
    _merge_records_into_jar([record for record, _expiry, _host, _ua in candidates])
    if user_agent:
        for _record, _expiry, host, _ua in candidates:
            set_host_user_agent(host, user_agent)
    return len(candidates)


def _clearance_candidates(profile_dir: str, user_agent: str):
    """[(jar record, expiry, host, ua)] for the unexpired clearance cookies in a profile."""
    out = []
    now = time.time()
    for host, path, secure, http_only, expiry, name, value in _read_firefox_cookies(profile_dir):
        if not _is_harvestable(name):
            continue
        try:
            expiry_f = float(expiry or 0)
        except (TypeError, ValueError):
            expiry_f = 0.0
        if expiry_f and expiry_f < now:
            continue
        domain_field = ("#HttpOnly_" + host) if http_only else host
        record = (
            domain_field,
            "TRUE" if host.startswith(".") else "FALSE",
            path,
            "TRUE" if secure else "FALSE",
            str(int(expiry_f)),
            name,
            value,
        )
        out.append((record, expiry_f, str(host).lstrip(".").lower(), user_agent))
    return out


_REFRESH_MIN_INTERVAL_S = 20.0
_last_forced_refresh = {}
_forced_refresh_lock = threading.Lock()


_REDDIT_AUTH_COOKIE_NAMES = {
    "reddit_session",
    "token_v2",
    "csrf_token",
    "session_tracker",
}

_GROUPS_IO_AUTH_COOKIE_NAMES = {
    "groupsio",
    "groupsio_session",
    "session",
    "sessionid",
}


def refresh_groups_io_cookies_from_browsers(url: str) -> bool:
    """Import only Groups.io cookies from the best Firefox-family profile.

    This is intentionally site-scoped.  It supports signed-in/member archives
    without copying unrelated browser logins into BlindRSS's managed jar.
    Chromium's Windows cookie encryption is not bypassed; those users can use
    the existing Import Site Cookies cookies.txt workflow instead.
    """
    try:
        request_host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return False
    if not (request_host == "groups.io" or request_host.endswith(".groups.io")):
        return False

    refresh_key = "groupsio-login:" + request_host
    now_mono = time.monotonic()
    with _forced_refresh_lock:
        if now_mono - _last_forced_refresh.get(refresh_key, 0.0) < _REFRESH_MIN_INTERVAL_S:
            return bool(cookies_for(url))
        _last_forced_refresh[refresh_key] = now_mono

    try:
        profiles = list_browser_profiles()
    except Exception:
        return bool(cookies_for(url))

    now = time.time()
    choices = []
    for profile in profiles or []:
        profile_dir = str(profile.get("path", "") or "")
        if not profile_dir:
            continue
        try:
            browser_rows = _read_firefox_cookies(profile_dir)
        except Exception:
            continue
        matching = []
        auth_count = 0
        newest_expiry = 0.0
        for host, path, secure, http_only, expiry, name, value in browser_rows:
            cookie_host = str(host or "").lower().lstrip(".")
            if not (cookie_host == "groups.io" or cookie_host.endswith(".groups.io")):
                continue
            try:
                expiry_f = float(expiry or 0)
            except (TypeError, ValueError):
                expiry_f = 0.0
            if expiry_f and expiry_f < now:
                continue
            matching.append((host, path, secure, http_only, expiry_f, name, value))
            lower_name = str(name or "").lower()
            if value and (lower_name in _GROUPS_IO_AUTH_COOKIE_NAMES or "session" in lower_name):
                auth_count += 1
            newest_expiry = max(newest_expiry, expiry_f)
        if matching:
            choices.append(((bool(auth_count), auth_count, newest_expiry, len(matching)), profile, matching))

    if not choices:
        return bool(cookies_for(url))
    _score, chosen, browser_rows = max(choices, key=lambda item: item[0])
    records = []
    for host, path, secure, http_only, expiry, name, value in browser_rows:
        domain_field = ("#HttpOnly_" + host) if http_only else host
        records.append((
            domain_field,
            "TRUE" if str(host).startswith(".") else "FALSE",
            path or "/",
            "TRUE" if secure else "FALSE",
            str(int(expiry or 0)),
            name,
            value,
        ))
    _merge_records_into_jar(records)
    try:
        ua = firefox_profile_user_agent(str(chosen.get("path", "") or ""))
    except Exception:
        ua = ""
    if ua:
        set_host_user_agent("groups.io", ua)
    log.info(
        "Refreshed %d Groups.io cookie(s) from %s (%s)",
        len(records), chosen.get("browser", "browser"), chosen.get("profile", ""),
    )
    return bool(cookies_for(url))


def refresh_reddit_cookies_from_browsers(url: str) -> bool:
    """Import only Reddit cookies from the best Firefox-family profile.

    Reddit increasingly returns a logged-out block/rate-limit page to ordinary
    HTTP clients while the same thread is available in the user's signed-in
    browser.  Unlike the automatic clearance-cookie watcher, this function is
    deliberately site-scoped: it never copies another site's login.  Among the
    readable Firefox-family profiles it prefers one carrying a Reddit auth
    cookie, then the freshest/most complete Reddit cookie set.

    Returns True when usable Reddit cookies are available after the refresh.
    Calls are rate-limited per host because copying a live Firefox SQLite file
    for every reader repaint would be wasteful.
    """
    try:
        request_host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return False
    if not (request_host == "reddit.com" or request_host.endswith(".reddit.com")):
        return False

    refresh_key = "reddit-login:" + request_host
    now_mono = time.monotonic()
    with _forced_refresh_lock:
        if now_mono - _last_forced_refresh.get(refresh_key, 0.0) < _REFRESH_MIN_INTERVAL_S:
            return bool(cookies_for(url))
        _last_forced_refresh[refresh_key] = now_mono

    try:
        profiles = list_browser_profiles()
    except Exception:
        return bool(cookies_for(url))

    now = time.time()
    choices = []
    for profile in profiles or []:
        profile_dir = str(profile.get("path", "") or "")
        if not profile_dir:
            continue
        try:
            rows = _read_firefox_cookies(profile_dir)
        except Exception:
            continue
        matching = []
        auth_count = 0
        newest_expiry = 0.0
        for host, path, secure, http_only, expiry, name, value in rows:
            cookie_host = str(host or "").lower().lstrip(".")
            if not (
                cookie_host == "reddit.com"
                or cookie_host.endswith(".reddit.com")
            ):
                continue
            try:
                expiry_f = float(expiry or 0)
            except (TypeError, ValueError):
                expiry_f = 0.0
            if expiry_f and expiry_f < now:
                continue
            matching.append((host, path, secure, http_only, expiry_f, name, value))
            if str(name or "").lower() in _REDDIT_AUTH_COOKIE_NAMES and value:
                auth_count += 1
            newest_expiry = max(newest_expiry, expiry_f)
        if matching:
            # Authenticated beats anonymous; freshness and cookie count break ties.
            choices.append(((bool(auth_count), auth_count, newest_expiry, len(matching)), profile, matching))

    if not choices:
        return bool(cookies_for(url))
    _score, chosen, rows = max(choices, key=lambda item: item[0])
    records = []
    for host, path, secure, http_only, expiry, name, value in rows:
        domain_field = ("#HttpOnly_" + host) if http_only else host
        records.append((
            domain_field,
            "TRUE" if str(host).startswith(".") else "FALSE",
            path or "/",
            "TRUE" if secure else "FALSE",
            str(int(expiry or 0)),
            name,
            value,
        ))
    _merge_records_into_jar(records)
    try:
        ua = firefox_profile_user_agent(str(chosen.get("path", "") or ""))
    except Exception:
        ua = ""
    if ua:
        set_host_user_agent("reddit.com", ua)
    log.info(
        "Refreshed %d Reddit cookie(s) from %s (%s)",
        len(records),
        chosen.get("browser", "browser"),
        chosen.get("profile", ""),
    )
    return bool(cookies_for(url))


def refresh_clearance_from_browsers(url: str) -> bool:
    """Re-read the browser profiles right now; True if this URL's clearance changed.

    Cloudflare hands out short-lived clearances (audiogames.net's lapse in well
    under an hour), so the usual answer to a gate on a site we have a session
    for is simply that the user has since re-visited it in their browser and we
    are still holding the old token. Checking costs one SQLite copy; the
    alternative is the whole fallback chain including a serialized Chromium
    launch, for a page a fresh cookie would have fetched outright.

    Ignores the mtime markers on purpose — this is the path for "the cookie we
    have does not work", where the marker is exactly what is in the way. Rate
    limited per host so a site that is simply blocked cannot make every fetch
    re-read every profile.
    """
    try:
        host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    now = time.monotonic()
    with _forced_refresh_lock:
        if now - _last_forced_refresh.get(host, 0.0) < _REFRESH_MIN_INTERVAL_S:
            return False
        _last_forced_refresh[host] = now

    before = cookies_for(url)
    try:
        profiles = list_browser_profiles()
    except Exception:
        return False
    best = {}
    for profile in profiles or []:
        path = str(profile.get("path", "") or "")
        if not path:
            continue
        try:
            ua = firefox_profile_user_agent(path)
        except Exception:
            ua = ""
        try:
            candidates = _clearance_candidates(path, ua)
        except Exception:
            continue
        for record, expiry, cookie_host, cookie_ua in candidates:
            slot = _record_key(record)
            if slot not in best or expiry > best[slot][1]:
                best[slot] = (record, expiry, cookie_host, cookie_ua)
    if not best:
        return False
    _merge_records_into_jar([entry[0] for entry in best.values()])
    for _record, _expiry, cookie_host, cookie_ua in best.values():
        if cookie_ua:
            set_host_user_agent(cookie_host, cookie_ua)
    changed = cookies_for(url) != before
    if changed:
        log.info("Refreshed clearance cookies for %s from the browser", host)
    return changed


def auto_import_browser_profiles(config_manager, *, profiles=None) -> int:
    """Refresh clearance cookies from every browser profile we can read.

    Runs on the CookieImportWatcher thread. Only profiles whose cookie database
    changed since the last pass are re-read, because each read copies and parses
    the whole database — doing that for every profile on every tick would be
    real disk work for nothing.

    Firefox-family profiles are readable because their cookie store is plain
    SQLite. Chromium browsers on Windows encrypt theirs with App-Bound
    Encryption (unreadable outside the browser), so those users still need the
    "Get cookies.txt LOCALLY" export the Downloads watcher picks up.

    Gated by `auto_import_browser_cookies`, the same consent as the other
    automatic import. Returns the number of cookies stored.
    """
    try:
        if not bool(config_manager.get("auto_import_browser_cookies", True)):
            return 0
    except Exception:
        return 0

    try:
        seen = dict(config_manager.get("site_cookies_profile_mtimes", {}) or {})
    except Exception:
        seen = {}
    if not isinstance(seen, dict):
        seen = {}

    if profiles is None:
        try:
            profiles = list_browser_profiles()
        except Exception:
            log.debug("Could not enumerate browser profiles", exc_info=True)
            return 0

    # Collected across every profile first, then reduced, because several
    # browsers can hold a clearance for the same site and only the newest one
    # still works. A plain last-writer-wins merge picked whichever profile
    # happened to be read last: a 24-day-old audiogames.net token beat one
    # issued twelve minutes earlier, and the request 403'd.
    best = {}
    changed = False
    for profile in profiles or []:
        path = str(profile.get("path", "") or "")
        if not path:
            continue
        key = os.path.abspath(path).lower()
        try:
            mtime = float(profile.get("mtime", 0) or 0)
        except (TypeError, ValueError):
            mtime = 0.0
        try:
            if mtime and mtime <= float(seen.get(key, 0) or 0):
                continue
        except (TypeError, ValueError):
            pass
        try:
            ua = firefox_profile_user_agent(path)
        except Exception:
            ua = ""
        try:
            candidates = _clearance_candidates(path, ua)
        except Exception:
            # A locked or corrupt profile must not stop the others, and must not
            # advance the marker — retry it on the next tick.
            log.debug("Could not read clearance cookies from %s", path, exc_info=True)
            continue
        seen[key] = mtime
        changed = True
        for record, expiry, host, cookie_ua in candidates:
            slot = _record_key(record)
            if slot not in best or expiry > best[slot][1]:
                best[slot] = (record, expiry, host, cookie_ua)
        if candidates:
            log.info(
                "Read %d clearance cookie(s) from %s (%s)",
                len(candidates), profile.get("browser", "browser"), profile.get("profile", ""),
            )

    if best:
        _merge_records_into_jar([entry[0] for entry in best.values()])
        # The UA is set from the profile whose cookie won, so the pair the site
        # will actually see stays the pair that earned the clearance.
        for _record, _expiry, host, cookie_ua in best.values():
            if cookie_ua:
                set_host_user_agent(host, cookie_ua)

    if changed:
        try:
            config_manager.set("site_cookies_profile_mtimes", seen)
        except Exception:
            log.exception("Failed to persist browser-profile cookie import state")
    return len(best)


# Cookies worth keeping from a solved challenge. A browser session carries
# analytics and ad identifiers too; storing those would leak the user's
# browsing into every later request for no benefit. cf_clearance is the whole
# point (Cloudflare), the rest cover the other WAFs the app already detects.
_HARVEST_COOKIE_NAMES = (
    "cf_clearance",
    "__cf_bm",
    "datadome",
    "reese84",
    "incap_ses",
    "visid_incap",
    "_px3",
    "_pxvid",
    "bm_sz",
    "ak_bmsc",
)


def _is_harvestable(name: str) -> bool:
    low = str(name or "").strip().lower()
    return any(low == want or low.startswith(want) for want in _HARVEST_COOKIE_NAMES)


def record_browser_session(url: str, cookies, user_agent: str = "") -> int:
    """Store clearance cookies won by the headless browser, with their UA.

    The headless browser can solve an interactive challenge that no HTTP client
    can (forum.audiogames.net answers `cf-mitigated: challenge` to every plain
    and curl_cffi request regardless of headers). Keeping the resulting
    clearance means later fetches for that site go over cheap HTTP until the
    token lapses, instead of paying a serialized Chromium launch every time.

    `cookies` is any iterable of objects or mappings with name/value/domain and
    optional path/expires/secure/http_only. Returns the number stored.

    The UA is recorded per host, not globally: a clearance is only valid for the
    exact User-Agent that earned it, and overwriting the global entry would
    invalidate a session the user imported by hand for a different site.
    """
    try:
        request_host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        request_host = ""
    if not request_host:
        return 0

    def _field(cookie, *names):
        for name in names:
            if isinstance(cookie, dict):
                if name in cookie:
                    return cookie[name]
            else:
                value = getattr(cookie, name, None)
                if value is not None:
                    return value
        return None

    records = []
    for cookie in cookies or []:
        name = str(_field(cookie, "name") or "")
        if not name or not _is_harvestable(name):
            continue
        value = str(_field(cookie, "value") or "")
        domain = str(_field(cookie, "domain") or "").strip().lower()
        if not domain:
            domain = request_host
        # Only keep cookies that actually apply to the site we fetched, so a
        # third-party cookie picked up while loading the page is not stored.
        bare = domain.lstrip(".")
        if not (request_host == bare or request_host.endswith("." + bare)):
            continue
        path = str(_field(cookie, "path") or "/") or "/"
        secure = bool(_field(cookie, "secure") or False)
        http_only = bool(_field(cookie, "http_only", "httpOnly", "httponly") or False)
        try:
            expires = int(float(_field(cookie, "expires", "expiry") or 0))
        except (TypeError, ValueError):
            expires = 0
        # A session cookie has no expiry; give it a bounded life rather than 0,
        # which cookies_for() treats as "never expires".
        if expires <= 0:
            expires = int(time.time()) + 3600
        domain_field = ("#HttpOnly_" + domain) if http_only else domain
        records.append((
            domain_field,
            "TRUE" if domain.startswith(".") else "FALSE",
            path,
            "TRUE" if secure else "FALSE",
            str(expires),
            name,
            value,
        ))

    if not records:
        return 0
    _merge_records_into_jar(records)
    if user_agent:
        set_host_user_agent(request_host, user_agent)
    log.info(
        "Stored %d clearance cookie(s) from the automated browser for %s",
        len(records), request_host,
    )
    return len(records)


def auto_import_downloads(config_manager, *, search_dirs=None, now=None):
    """Auto-import Netscape cookies.txt exports from Downloads (hands-free).

    On the first scan, every valid export already present in Downloads is
    eligible regardless of age. Later scans merge only files newer than the
    persisted marker. This makes an existing export available as soon as the
    app starts while still preventing re-import loops. Multiple pending exports
    are merged oldest-to-newest so no site's cookies are skipped.

    Returns the newest imported source path, or None. Gated by the same
    ``auto_import_browser_cookies`` setting as the YouTube flow, and by a
    persisted mtime (``site_cookies_last_import_mtime``).
    """
    from core import cookies_import

    try:
        if not bool(config_manager.get("auto_import_browser_cookies", True)):
            return None
    except Exception:
        return None
    try:
        last_mtime = float(config_manager.get("site_cookies_last_import_mtime", 0) or 0)
    except (TypeError, ValueError):
        last_mtime = 0.0

    # ``now`` remains accepted for caller/test API compatibility, although site
    # imports intentionally have no first-scan age cutoff. The YouTube-specific
    # importer retains its recency safeguard.
    cutoff = last_mtime
    if search_dirs is not None:
        dirs = search_dirs
    else:
        home = os.path.abspath(os.path.expanduser("~"))
        dirs = [
            path for path in cookies_import.default_download_dirs()
            if os.path.abspath(path) != home
        ]

    managed = {os.path.abspath(jar_path()).lower()}
    candidates = []
    for d in dirs or []:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".txt"):
                continue
            if name.lower() == cookies_import.IMPORTED_COOKIE_FILENAME.lower():
                continue
            path = os.path.join(d, name)
            if os.path.abspath(path).lower() in managed:
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime <= cutoff:
                continue
            ok, _msg = validate_jar_file(path)
            if ok:
                candidates.append((mtime, path))
    if not candidates:
        return None

    imported = []
    for mtime, path in sorted(candidates):
        try:
            merge_jar_file(path)
        except (ValueError, OSError) as exc:
            # Do not advance past a failed candidate; retry it next tick.
            log.debug("Site cookie auto-import stopped at %s: %s", path, exc)
            break
        imported.append((mtime, path))
    if not imported:
        return None
    newest_mtime, newest_path = imported[-1]
    try:
        config_manager.set("site_cookies_last_import_mtime", newest_mtime)
    except Exception:
        log.exception("Failed to persist site cookie auto-import state")
        return None
    log.info("Auto-imported site cookies from %d export(s); newest: %s", len(imported), newest_path)
    return newest_path


# Markers that identify a bot-verification interstitial rather than content.
_CHALLENGE_MARKERS = (
    "challenges.cloudflare.com",
    "cf-mitigated",
    "Just a moment...",
    "_cf_chl_opt",
    "Performing security verification",
)


def looks_like_challenge_response(status_code: int, body: str) -> bool:
    """True when a response is a bot-check interstitial, not real content."""
    if status_code not in (401, 403, 503):
        return False
    text = str(body or "")[:20000]
    return any(marker in text for marker in _CHALLENGE_MARKERS)


# ---------------------------------------------------------------------------
# Full-cookie import from every installed browser (issue: Chromium v20)
# ---------------------------------------------------------------------------

# Netscape cookie records whose domain is a YouTube/Google login, so the yt-dlp
# cookie file gets what it needs without carrying every unrelated session.
_YOUTUBE_DOMAINS = ("youtube.com", "google.com")


def _is_youtube_record(domain_field: str) -> bool:
    domain = str(domain_field or "").replace("#HttpOnly_", "", 1).lstrip(".").lower()
    return any(domain == d or domain.endswith("." + d) for d in _YOUTUBE_DOMAINS)


def merge_youtube_cookies(records, config_manager) -> int:
    """Merge YouTube/Google records into the managed yt-dlp cookie file.

    Returns the number of records in the resulting jar. Points yt-dlp's
    ``ytdlp_cookies_file`` at the managed jar unless the user configured their
    own file, so restricted YouTube playback works automatically.
    """
    from core.cookies_import import IMPORTED_COOKIE_FILENAME, _iter_cookie_records

    data_dir = config_mod.get_data_dir()
    dest = os.path.join(data_dir, IMPORTED_COOKIE_FILENAME)

    merged = {}
    try:
        with open(dest, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for fields in _iter_cookie_records(text):
            merged[_record_key(tuple(fields[:7]))] = tuple(fields[:7])
    except OSError:
        pass

    for record in records or []:
        merged[_record_key(tuple(record))] = tuple(record)

    os.makedirs(data_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="youtube-cookies-", suffix=".tmp", dir=data_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("# Netscape HTTP Cookie File\n")
            fh.write("# Harvested from installed browsers by BlindRSS\n\n")
            for record in merged.values():
                fh.write("\t".join(str(f) for f in record) + "\n")
        os.replace(tmp, dest)
        tmp = ""
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass

    current = str(config_manager.get("ytdlp_cookies_file", "") or "").strip()
    if not current or os.path.abspath(current) == os.path.abspath(dest):
        try:
            config_manager.set("ytdlp_cookies_file", dest)
        except Exception:
            log.exception("Failed to persist the harvested yt-dlp cookie path")
    return len(merged)


def auto_import_installed_browser_cookies(
    config_manager, *, profiles=None, chromium_profiles=None
) -> dict:
    """Full-cookie import from every installed browser (Firefox + Chromium).

    Gated by the ``auto_import_installed_browser_cookies`` consent (default on).
    Unlike the clearance-only watcher this copies the user's *session* cookies
    — the whole point of the feature: YouTube login and any other site. Firefox
    profiles are read directly (plain SQLite); Chromium cookies are decrypted
    (v10 via user DPAPI, v20 via a one-time UAC elevation whose master key is
    then cached, so later runs are silent).

    Unchanged profiles are skipped via the persisted ``site_cookies_full_profile_mtimes``
    markers, so the watcher does not re-read every cookie DB every tick.

    Runs on the CookieImportWatcher thread. Returns a stats dict.
    """
    stats = {"firefox": 0, "chromium": 0, "cookies": 0, "youtube": 0, "elevated": 0, "vss": 0}
    try:
        if not bool(config_manager.get("auto_import_installed_browser_cookies", True)):
            return stats
    except Exception:
        return stats

    try:
        seen = dict(config_manager.get("site_cookies_full_profile_mtimes", {}) or {})
    except Exception:
        seen = {}
    if not isinstance(seen, dict):
        seen = {}

    changed = False
    youtube_records = []

    # --- Firefox family: full jar (plain SQLite, no encryption) --------------
    try:
        ff_profiles = profiles if profiles is not None else list_browser_profiles()
    except Exception:
        ff_profiles = []
    for profile in ff_profiles or []:
        profile_dir = str(profile.get("path", "") or "")
        if not profile_dir:
            continue
        key = os.path.abspath(profile_dir).lower()
        try:
            mtime = float(profile.get("mtime", 0) or 0)
        except (TypeError, ValueError):
            mtime = 0.0
        try:
            if mtime and mtime <= float(seen.get(key, 0) or 0):
                continue
        except (TypeError, ValueError):
            pass
        try:
            rows = _read_firefox_cookies(profile_dir)
        except Exception:
            log.debug("Could not read Firefox cookies from %s", profile_dir, exc_info=True)
            continue
        seen[key] = mtime
        changed = True
        records = []
        # A clearance cookie is only valid for the exact browser identity that
        # earned it; pin the profile's Firefox UA for any host whose clearance
        # we import (mirrors the matched-triple rule the clearance-only import
        # already follows).
        clearance_ua = ""
        clearance_hosts = set()
        now = int(time.time())
        for host, path, secure, http_only, expiry, name, value in rows:
            try:
                expiry_i = int(expiry or 0)
            except (TypeError, ValueError):
                expiry_i = 0
            # Firefox ``expiry`` is already Unix seconds; drop expired cookies.
            if expiry_i and expiry_i < now:
                continue
            domain_field = ("#HttpOnly_" + host) if http_only else host
            record = (
                domain_field,
                "TRUE" if host.startswith(".") else "FALSE",
                path or "/",
                "TRUE" if secure else "FALSE",
                str(expiry_i),
                name,
                value,
            )
            records.append(record)
            if _is_youtube_record(domain_field):
                youtube_records.append(record)
            if _is_harvestable(str(name or "")):
                clearance_hosts.add(str(host or "").strip().lstrip(".").lower())
        if records:
            _merge_records_into_jar(records)
            stats["cookies"] += len(records)
        if clearance_hosts:
            if not clearance_ua:
                try:
                    clearance_ua = firefox_profile_user_agent(profile_dir)
                except Exception:
                    clearance_ua = ""
            if clearance_ua:
                for host in clearance_hosts:
                    try:
                        set_host_user_agent(host, clearance_ua)
                    except Exception:
                        log.debug("Could not pin UA for %s", host, exc_info=True)
    stats["firefox"] = len([p for p in (ff_profiles or []) if p.get("path")])

    # --- Chromium family: v10 + v20 (one-time elevation for v20) ------------
    try:
        from core import chromium_cookies

        if chromium_profiles is not None:
            cprofiles = chromium_profiles
        else:
            cprofiles = chromium_cookies.list_chromium_profiles()
        # Skip unchanged cookie DBs via the same marker set.
        filtered = []
        for profile in cprofiles or []:
            db = str(profile.get("cookie_db", "") or "")
            if not db:
                continue
            key = os.path.abspath(db).lower()
            try:
                mtime = float(profile.get("mtime", 0) or 0)
            except (TypeError, ValueError):
                mtime = 0.0
            try:
                if mtime and mtime <= float(seen.get(key, 0) or 0):
                    continue
            except (TypeError, ValueError):
                pass
            filtered.append(profile)
            seen[key] = mtime
            changed = True
        cstats = chromium_cookies.import_chromium_cookies(
            config_manager, profiles=filtered, elevate=True
        )
    except Exception:
        log.exception("Chromium cookie import failed")
        cstats = {}
    stats["chromium"] = int(cstats.get("profiles", 0) or 0)
    stats["cookies"] += int(cstats.get("cookies", 0) or 0)
    stats["elevated"] = int(cstats.get("elevated", 0) or 0)
    stats["youtube"] = int(cstats.get("youtube", 0) or 0)
    stats["vss"] = int(cstats.get("vss", 0) or 0)

    # --- Firefox YouTube cookies -> yt-dlp jar -------------------------------
    if youtube_records:
        try:
            stats["youtube"] += merge_youtube_cookies(youtube_records, config_manager)
        except Exception:
            log.exception("Failed to persist harvested Firefox YouTube cookies")

    if changed:
        try:
            config_manager.set("site_cookies_full_profile_mtimes", seen)
        except Exception:
            log.exception("Failed to persist full-browser cookie import state")
    return stats

