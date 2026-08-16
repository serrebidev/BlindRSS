# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Full-cookie import from installed browsers (site_cookies integration)."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import site_cookies
from core import chromium_cookies


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def _make_firefox_profile(profile_dir, cookies):
    os.makedirs(profile_dir, exist_ok=True)
    db = os.path.join(profile_dir, "cookies.sqlite")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, host TEXT, path TEXT, "
        "isSecure INTEGER, isHttpOnly INTEGER, expiry INTEGER, name TEXT, value TEXT)"
    )
    for host, path, secure, http_only, expiry, name, value in cookies:
        conn.execute(
            "INSERT INTO moz_cookies (host, path, isSecure, isHttpOnly, expiry, name, value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (host, path, int(secure), int(http_only), expiry, name, value),
        )
    conn.commit()
    conn.close()
    return profile_dir


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(site_cookies.config_mod, "get_data_dir", lambda: str(tmp_path))
    site_cookies._invalidate()
    yield tmp_path
    site_cookies._invalidate()


def _no_chromium(monkeypatch):
    monkeypatch.setattr(chromium_cookies, "list_chromium_profiles", lambda: [])
    monkeypatch.setattr(
        chromium_cookies,
        "import_chromium_cookies",
        lambda config_manager, profiles=None, elevate=True: {
            "profiles": 0,
            "cookies": 0,
            "elevated": 0,
            "youtube": 0,
            "vss": 0,
            "elevation_failed": 0,
        },
    )


def test_merge_youtube_cookies_writes_jar_and_sets_config(tmp_path):
    records = [
        (".youtube.com", "TRUE", "/", "TRUE", "0", "LOGIN_INFO", "token-value"),
        ("news.example", "FALSE", "/", "FALSE", "0", "sess", "nope"),
    ]
    cfg = _FakeConfig()
    count = site_cookies.merge_youtube_cookies(records, cfg)
    # The yt-dlp jar carries the YouTube/Google login only (issue #101).
    assert count == 1
    jar = tmp_path / "youtube_cookies.txt"
    assert jar.is_file()
    text = jar.read_text(encoding="utf-8")
    assert "LOGIN_INFO" in text and "token-value" in text
    assert "news.example" not in text
    assert cfg.get("ytdlp_cookies_file") == str(jar)


def test_merge_youtube_cookies_drops_existing_unrelated_records(tmp_path):
    """A jar polluted by the old import loop is cleaned on the next write."""
    jar = tmp_path / "youtube_cookies.txt"
    jar.write_text(
        "# Netscape HTTP Cookie File\n"
        "# Imported by BlindRSS (Import Site Cookies)\n\n"
        "bank.example\tFALSE\t/\tTRUE\t0\tsession\tsecret\n"
        ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\told\n",
        encoding="utf-8",
    )
    cfg = _FakeConfig()
    site_cookies.merge_youtube_cookies(
        [(".youtube.com", "TRUE", "/", "TRUE", "0", "SID", "new")], cfg
    )
    text = jar.read_text(encoding="utf-8")
    assert "bank.example" not in text
    assert "secret" not in text
    assert "new" in text


def test_merge_youtube_cookies_respects_user_configured_file(tmp_path):
    records = [(".youtube.com", "TRUE", "/", "TRUE", "0", "A", "B")]
    cfg = _FakeConfig({"ytdlp_cookies_file": "C:/my/cookies.txt"})
    site_cookies.merge_youtube_cookies(records, cfg)
    assert cfg.get("ytdlp_cookies_file") == "C:/my/cookies.txt"


def test_full_import_firefox_and_gate(tmp_path, monkeypatch):
    profile = _make_firefox_profile(
        str(tmp_path / "profile.default"),
        [
            (".youtube.com", "/", 1, 1, 4102444800, "SID", "yt-session"),
            ("news.example", "/", 0, 0, 4102444800, "sess", "abc"),
        ],
    )
    monkeypatch.setattr(
        site_cookies, "list_browser_profiles",
        lambda: [{"browser": "Firefox", "profile": "default", "path": profile, "mtime": 2000.0}],
    )
    _no_chromium(monkeypatch)

    cfg = _FakeConfig({"installed_browser_cookie_import_enabled": True})
    stats = site_cookies.auto_import_installed_browser_cookies(cfg)
    assert stats["cookies"] == 2
    assert stats["youtube"] > 0
    # Site jar got both cookies.
    assert "sess=abc" in site_cookies.cookie_header_for("https://news.example/", now=4000000000)
    # YouTube jar got the Google/YouTube cookie and was pointed at yt-dlp.
    jar = tmp_path / "youtube_cookies.txt"
    assert "SID" in jar.read_text(encoding="utf-8")
    assert cfg.get("ytdlp_cookies_file") == str(jar)


def test_full_import_requires_new_explicit_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(site_cookies, "list_browser_profiles", lambda: [])
    _no_chromium(monkeypatch)
    cfg = _FakeConfig({"auto_import_installed_browser_cookies": True})
    stats = site_cookies.auto_import_installed_browser_cookies(cfg)
    assert stats == {
        "firefox": 0,
        "chromium": 0,
        "cookies": 0,
        "new": 0,
        "youtube": 0,
        "elevated": 0,
        "vss": 0,
        "elevation_failed": 0,
    }


def test_full_import_skips_unchanged_profiles(tmp_path, monkeypatch):
    profile = _make_firefox_profile(
        str(tmp_path / "profile.default"),
        [("news.example", "/", 0, 0, 4102444800, "sess", "abc")],
    )
    monkeypatch.setattr(
        site_cookies, "list_browser_profiles",
        lambda: [{"browser": "Firefox", "profile": "default", "path": profile, "mtime": 2000.0}],
    )
    _no_chromium(monkeypatch)

    cfg = _FakeConfig({
        "installed_browser_cookie_import_enabled": True,
        "site_cookies_full_profile_mtimes": {os.path.abspath(profile).lower(): 2000.0},
    })
    stats = site_cookies.auto_import_installed_browser_cookies(cfg)
    assert stats["cookies"] == 0  # mtime marker matched -> skipped


def test_elevation_failure_revokes_consent_and_prevents_retry(monkeypatch):
    monkeypatch.setattr(site_cookies, "list_browser_profiles", lambda: [])
    profile = {"cookie_db": "C:/browser/Cookies", "mtime": 2000.0}
    monkeypatch.setattr(chromium_cookies, "list_chromium_profiles", lambda: [profile])
    calls = []

    def failed_import(config_manager, profiles=None, elevate=True):
        calls.append(list(profiles or []))
        return {
            "profiles": 0,
            "cookies": 0,
            "elevated": 0,
            "youtube": 0,
            "vss": 0,
            "elevation_failed": 1,
        }

    monkeypatch.setattr(chromium_cookies, "import_chromium_cookies", failed_import)
    cfg = _FakeConfig({"installed_browser_cookie_import_enabled": True})

    first = site_cookies.auto_import_installed_browser_cookies(cfg)
    # Clear the cadence marker so the second call is blocked by the revoked
    # consent rather than by the harvest interval.
    cfg.set("site_cookies_full_import_last_run", 0)
    second = site_cookies.auto_import_installed_browser_cookies(cfg)

    assert first["elevation_failed"] == 1
    assert cfg.get("installed_browser_cookie_import_enabled") is False
    assert second["elevation_failed"] == 0
    assert len(calls) == 1


# --- issue #101: the harvest must not swamp the machine or the Cookie header --

def test_full_import_is_rate_limited_between_runs(tmp_path, monkeypatch):
    """A running browser rewrites its cookie DB constantly; the harvest (which
    shadow-copies locked databases through an elevated helper) must not re-run
    on every watcher tick because of it."""
    profile = _make_firefox_profile(
        str(tmp_path / "profile.default"),
        [("news.example", "/", 0, 0, 4102444800, "sess", "abc")],
    )
    mtimes = iter([2000.0, 3000.0])
    monkeypatch.setattr(
        site_cookies, "list_browser_profiles",
        lambda: [{"browser": "Firefox", "profile": "default",
                  "path": profile, "mtime": next(mtimes)}],
    )
    _no_chromium(monkeypatch)

    cfg = _FakeConfig({"installed_browser_cookie_import_enabled": True})
    assert site_cookies.auto_import_installed_browser_cookies(cfg)["cookies"] == 1
    # Second tick: the profile changed, but the interval has not elapsed.
    assert site_cookies.auto_import_installed_browser_cookies(cfg)["cookies"] == 0

    cfg.set(
        "site_cookies_full_import_last_run",
        cfg.get("site_cookies_full_import_last_run") - site_cookies.FULL_IMPORT_MIN_INTERVAL_S - 1,
    )
    assert site_cookies.auto_import_installed_browser_cookies(cfg)["cookies"] == 1


def test_full_import_reports_only_newly_changed_cookies(tmp_path, monkeypatch):
    """`new` drives the "cookies updated" notification, so re-reading the same
    cookies must report zero."""
    profile = _make_firefox_profile(
        str(tmp_path / "profile.default"),
        [("news.example", "/", 0, 0, 4102444800, "sess", "abc")],
    )
    monkeypatch.setattr(
        site_cookies, "list_browser_profiles",
        lambda: [{"browser": "Firefox", "profile": "default", "path": profile, "mtime": 2000.0}],
    )
    _no_chromium(monkeypatch)

    cfg = _FakeConfig({"installed_browser_cookie_import_enabled": True})
    assert site_cookies.auto_import_installed_browser_cookies(cfg)["new"] == 1

    cfg.set("site_cookies_full_import_last_run", 0)
    cfg.set("site_cookies_full_profile_mtimes", {})
    assert site_cookies.auto_import_installed_browser_cookies(cfg)["new"] == 0


def test_youtube_session_tokens_never_enter_the_jar(tmp_path, monkeypatch):
    """YouTube's ST-* tokens all have unique names, so they accumulate forever."""
    profile = _make_firefox_profile(
        str(tmp_path / "profile.default"),
        [
            (".youtube.com", "/", 1, 0, 4102444800, "ST-abcdef", "x" * 900),
            (".youtube.com", "/", 1, 0, 4102444800, "SID", "real-session"),
        ],
    )
    monkeypatch.setattr(
        site_cookies, "list_browser_profiles",
        lambda: [{"browser": "Firefox", "profile": "default", "path": profile, "mtime": 2000.0}],
    )
    _no_chromium(monkeypatch)

    cfg = _FakeConfig({"installed_browser_cookie_import_enabled": True})
    site_cookies.auto_import_installed_browser_cookies(cfg)
    header = site_cookies.cookie_header_for("https://www.youtube.com/feeds/videos.xml", now=4000000000)
    assert "SID=real-session" in header
    assert "ST-abcdef" not in header


def test_cookie_header_stays_within_the_size_budget(tmp_path):
    """Past ~50 KB of Cookie header YouTube answers 413 and the feed reads as
    empty; keep every request inside the smallest common server limit."""
    records = [
        (".big.example", "TRUE", "/", "FALSE", "0", f"pad{i}", "v" * 1500)
        for i in range(20)
    ]
    records.append((".big.example", "TRUE", "/", "FALSE", "0", "cf_clearance", "clear.1"))
    site_cookies.merge_records_into_jar(records)

    header = site_cookies.cookie_header_for("https://big.example/feed", now=2000000000)
    assert len(header) <= site_cookies.MAX_COOKIE_HEADER_BYTES
    # The clearance cookie is the reason the jar exists; it is never the one dropped.
    assert "cf_clearance=clear.1" in header
