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
            "profiles": 0, "cookies": 0, "elevated": 0, "youtube": 0,
        },
    )


def test_merge_youtube_cookies_writes_jar_and_sets_config(tmp_path):
    records = [
        (".youtube.com", "TRUE", "/", "TRUE", "0", "LOGIN_INFO", "token-value"),
        ("news.example", "FALSE", "/", "FALSE", "0", "sess", "nope"),
    ]
    cfg = _FakeConfig()
    count = site_cookies.merge_youtube_cookies(records, cfg)
    assert count == 2
    jar = tmp_path / "youtube_cookies.txt"
    assert jar.is_file()
    text = jar.read_text(encoding="utf-8")
    assert "LOGIN_INFO" in text and "token-value" in text
    assert cfg.get("ytdlp_cookies_file") == str(jar)


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

    cfg = _FakeConfig()
    stats = site_cookies.auto_import_installed_browser_cookies(cfg)
    assert stats["cookies"] == 2
    assert stats["youtube"] > 0
    # Site jar got both cookies.
    assert "sess=abc" in site_cookies.cookie_header_for("https://news.example/", now=4000000000)
    # YouTube jar got the Google/YouTube cookie and was pointed at yt-dlp.
    jar = tmp_path / "youtube_cookies.txt"
    assert "SID" in jar.read_text(encoding="utf-8")
    assert cfg.get("ytdlp_cookies_file") == str(jar)


def test_full_import_disabled_by_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(site_cookies, "list_browser_profiles", lambda: [])
    _no_chromium(monkeypatch)
    cfg = _FakeConfig({"auto_import_installed_browser_cookies": False})
    stats = site_cookies.auto_import_installed_browser_cookies(cfg)
    assert stats == {"firefox": 0, "chromium": 0, "cookies": 0, "youtube": 0, "elevated": 0}


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

    cfg = _FakeConfig({"site_cookies_full_profile_mtimes": {os.path.abspath(profile).lower(): 2000.0}})
    stats = site_cookies.auto_import_installed_browser_cookies(cfg)
    assert stats["cookies"] == 0  # mtime marker matched -> skipped
