# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Per-site cookie jar for challenge-protected sites (issue #79)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import site_cookies


_JAR = (
    "# Netscape HTTP Cookie File\n"
    ".forum.audiogames.net\tTRUE\t/\tTRUE\t9999999999\tcf_clearance\tabc.123\n"
    "#HttpOnly_.forum.audiogames.net\tTRUE\t/\tTRUE\t9999999999\t__cfsid\txyz\n"
    "forum.audiogames.net\tFALSE\t/\tFALSE\t0\tphpbb_sess\tzzz\n"
    ".expired.example\tTRUE\t/\tTRUE\t1000000000\told\tgone\n"
    ".other.example\tTRUE\t/api\tTRUE\t9999999999\tscoped\tpathy\n"
)


@pytest.fixture(autouse=True)
def _jar(tmp_path, monkeypatch):
    jar = tmp_path / site_cookies.JAR_FILENAME
    jar.write_text(_JAR, encoding="utf-8")
    monkeypatch.setattr(site_cookies.config_mod, "get_data_dir", lambda: str(tmp_path))
    site_cookies._invalidate()
    yield tmp_path
    site_cookies._invalidate()


def test_cookie_header_matches_domain_and_subdomains():
    header = site_cookies.cookie_header_for(
        "https://forum.audiogames.net/feed/rss/", now=2000000000
    )
    assert "cf_clearance=abc.123" in header
    assert "__cfsid=xyz" in header
    assert "phpbb_sess=zzz" in header


def test_no_cookies_for_unrelated_host():
    assert site_cookies.cookie_header_for("https://example.com/", now=2000000000) == ""
    # audiogames.net (parent of the cookie domain) must NOT match either.
    assert site_cookies.cookie_header_for("https://audiogames.net/", now=2000000000) == ""


def test_expired_cookies_are_dropped():
    assert site_cookies.cookie_header_for("https://expired.example/", now=2000000000) == ""


def test_path_scoping():
    assert site_cookies.cookie_header_for("https://other.example/", now=2000000000) == ""
    assert "scoped=pathy" in site_cookies.cookie_header_for(
        "https://other.example/api/things", now=2000000000
    )


def test_user_agent_only_for_cookie_domains(tmp_path):
    site_cookies.set_user_agent("Mozilla/5.0 TestBrowser")
    assert site_cookies.user_agent_for("https://forum.audiogames.net/x", now=2000000000) == "Mozilla/5.0 TestBrowser"
    assert site_cookies.user_agent_for("https://example.com/", now=2000000000) == ""
    site_cookies.set_user_agent("")
    assert site_cookies.user_agent_for("https://forum.audiogames.net/x", now=2000000000) == ""


def test_challenge_detection():
    body = '<title>Just a moment...</title><script src="https://challenges.cloudflare.com/x"></script>'
    assert site_cookies.looks_like_challenge_response(403, body)
    assert not site_cookies.looks_like_challenge_response(200, body)
    assert not site_cookies.looks_like_challenge_response(403, "<html>plain forbidden</html>")


def test_import_jar_validates(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello world", encoding="utf-8")
    with pytest.raises(ValueError):
        site_cookies.import_jar(str(bad))
    good = tmp_path / "export.txt"
    good.write_text(_JAR, encoding="utf-8")
    dest = site_cookies.import_jar(str(good))
    assert os.path.basename(dest) == site_cookies.JAR_FILENAME


def _make_firefox_profile(profile_dir, cookies, version="142.0.1_20250929"):
    import sqlite3

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
    with open(os.path.join(profile_dir, "compatibility.ini"), "w", encoding="utf-8") as fh:
        fh.write(f"[Compatibility]\nLastVersion={version}\n")
    return profile_dir


def test_import_from_browser_profile_merges_into_jar(tmp_path):
    profile = _make_firefox_profile(
        str(tmp_path / "profile.default"),
        [
            (".forum.audiogames.net", "/", 1, 1, 9999999999, "cf_clearance", "fresh.value"),
            ("news.example", "/", 0, 0, 9999999999, "sess", "abc"),
        ],
    )
    count = site_cookies.import_from_browser_profile(profile)
    assert count == 2
    header = site_cookies.cookie_header_for("https://forum.audiogames.net/feed/rss/", now=2000000000)
    # The browser's cf_clearance replaced the jar's old one; unrelated jar
    # cookies from the fixture survived the merge.
    assert "cf_clearance=fresh.value" in header
    assert "phpbb_sess=zzz" in header
    assert "sess=abc" in site_cookies.cookie_header_for("https://news.example/", now=2000000000)


def test_firefox_profile_user_agent(tmp_path):
    profile = _make_firefox_profile(str(tmp_path / "p2"), [])
    ua = site_cookies.firefox_profile_user_agent(profile)
    assert "rv:142.0" in ua
    assert "Firefox/142.0" in ua
    assert ua.startswith("Mozilla/5.0 (")


def test_list_browser_profiles_empty_when_no_roots(monkeypatch):
    monkeypatch.setattr(site_cookies, "_firefox_like_roots", lambda: [])
    assert site_cookies.list_browser_profiles() == []


def test_list_browser_profiles_finds_and_sorts(tmp_path, monkeypatch):
    root = tmp_path / "ff"
    old = _make_firefox_profile(str(root / "Profiles" / "old.default"), [])
    new = _make_firefox_profile(str(root / "Profiles" / "new.default"), [])
    os.utime(os.path.join(old, "cookies.sqlite"), (1000, 1000))
    os.utime(os.path.join(new, "cookies.sqlite"), (2000, 2000))
    monkeypatch.setattr(site_cookies, "_firefox_like_roots", lambda: [("Firefox", str(root))])
    profiles = site_cookies.list_browser_profiles()
    assert [p["profile"] for p in profiles] == ["new.default", "old.default"]
    assert profiles[0]["browser"] == "Firefox"


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


_EXPORT = (
    "# Netscape HTTP Cookie File\n"
    "# https://curl.haxx.se/rfc/cookie_spec.html\n"
    "# This is a generated file!  Do not edit.\n\n"
    ".challenge.example\tTRUE\t/\tTRUE\t9999999999\tcf_clearance\tdownloaded.value\n"
)


def test_auto_import_downloads_merges_fresh_export(tmp_path):
    import time as time_mod

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    export = downloads / "challenge.example_cookies.txt"
    export.write_text(_EXPORT, encoding="utf-8")
    now = time_mod.time()
    os.utime(export, (now, now))

    cfg = _FakeConfig()
    src = site_cookies.auto_import_downloads(cfg, search_dirs=[str(downloads)], now=now)
    assert src == str(export)
    header = site_cookies.cookie_header_for("https://challenge.example/", now=2000000000)
    assert "cf_clearance=downloaded.value" in header
    # Cookies imported earlier survive the merge.
    assert "phpbb_sess=zzz" in site_cookies.cookie_header_for(
        "https://forum.audiogames.net/feed/rss/", now=2000000000
    )
    # The same export is never merged twice.
    assert cfg.get("site_cookies_last_import_mtime") == os.path.getmtime(export)
    assert site_cookies.auto_import_downloads(cfg, search_dirs=[str(downloads)], now=now) is None


def test_auto_import_downloads_imports_existing_jar_on_first_scan(tmp_path):
    import time as time_mod

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    now = time_mod.time()
    stale = downloads / "old_cookies.txt"
    stale.write_text(_EXPORT, encoding="utf-8")
    os.utime(stale, (now - 3600, now - 3600))
    notes = downloads / "notes.txt"
    notes.write_text("just some text", encoding="utf-8")
    os.utime(notes, (now, now))

    cfg = _FakeConfig()
    assert site_cookies.auto_import_downloads(
        cfg, search_dirs=[str(downloads)], now=now
    ) == str(stale)
    assert "cf_clearance=downloaded.value" in site_cookies.cookie_header_for(
        "https://challenge.example/", now=2000000000
    )


def test_auto_import_downloads_merges_every_pending_export(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    first = downloads / "one_cookies.txt"
    second = downloads / "two_cookies.txt"
    first.write_text(_EXPORT, encoding="utf-8")
    second.write_text(
        _EXPORT.replace("challenge.example", "second.example")
        .replace("downloaded.value", "second.value"),
        encoding="utf-8",
    )
    os.utime(first, (1000, 1000))
    os.utime(second, (2000, 2000))

    cfg = _FakeConfig()
    assert site_cookies.auto_import_downloads(
        cfg, search_dirs=[str(downloads)], now=3000
    ) == str(second)
    assert "downloaded.value" in site_cookies.cookie_header_for(
        "https://challenge.example/", now=500
    )
    assert "second.value" in site_cookies.cookie_header_for(
        "https://second.example/", now=500
    )
    assert cfg.get("site_cookies_last_import_mtime") == 2000


def test_auto_import_downloads_respects_setting(tmp_path):
    import time as time_mod

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    export = downloads / "site_cookies_export.txt"
    export.write_text(_EXPORT, encoding="utf-8")
    now = time_mod.time()
    os.utime(export, (now, now))

    cfg = _FakeConfig({"auto_import_browser_cookies": False})
    assert site_cookies.auto_import_downloads(cfg, search_dirs=[str(downloads)], now=now) is None
