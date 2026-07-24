# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Automatic clearance import from readable browser profiles."""

import time

import pytest

from core import site_cookies


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(site_cookies.config_mod, "get_data_dir", lambda: str(tmp_path))
    site_cookies._invalidate()
    yield tmp_path
    site_cookies._invalidate()


class Config:
    def __init__(self, **values):
        self.values = {"auto_import_browser_cookies": True}
        self.values.update(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


FUTURE = int(time.time()) + 3600


def rows(*entries):
    """(host, path, secure, http_only, expiry, name, value) tuples."""
    return list(entries)


def fake_profile(path="/p/one", browser="Firefox", profile="default", mtime=100.0):
    return {"path": path, "browser": browser, "profile": profile, "mtime": mtime}


def patch_reader(monkeypatch, mapping, ua_map=None):
    monkeypatch.setattr(site_cookies, "_read_firefox_cookies", lambda p: mapping.get(p, []))
    monkeypatch.setattr(
        site_cookies, "firefox_profile_user_agent", lambda p: (ua_map or {}).get(p, "")
    )


def test_clearance_cookie_is_imported_without_an_export_step(monkeypatch):
    patch_reader(
        monkeypatch,
        {"/p/one": rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "tok"))},
        {"/p/one": "Firefox/152.0"},
    )
    cfg = Config()
    assert site_cookies.auto_import_browser_profiles(cfg, profiles=[fake_profile()]) == 1
    url = "https://forum.audiogames.net/x"
    assert site_cookies.cookies_for(url)["cf_clearance"] == "tok"
    assert site_cookies.user_agent_for(url) == "Firefox/152.0"


def test_logins_are_left_in_the_browser(monkeypatch):
    # The automatic path runs unattended, so it must not copy every site's
    # session cookie into a plaintext file in the app data dir.
    patch_reader(
        monkeypatch,
        {"/p/one": rows(
            (".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "tok"),
            (".audiogames.net", "/", True, True, FUTURE, "punbb_cookie", "login"),
            (".bank.example", "/", True, True, FUTURE, "SESSIONID", "secret"),
        )},
    )
    cfg = Config()
    assert site_cookies.auto_import_browser_profiles(cfg, profiles=[fake_profile()]) == 1
    assert "punbb_cookie" not in site_cookies.cookies_for("https://forum.audiogames.net/x")
    assert site_cookies.cookies_for("https://bank.example/") == {}


def test_expired_clearance_is_not_imported(monkeypatch):
    patch_reader(
        monkeypatch,
        {"/p/one": rows((".audiogames.net", "/", True, False, 1, "cf_clearance", "stale"))},
    )
    assert site_cookies.auto_import_browser_profiles(Config(), profiles=[fake_profile()]) == 0


def test_unchanged_profile_is_not_reread(monkeypatch):
    reads = []

    def reader(path):
        reads.append(path)
        return rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "tok"))

    monkeypatch.setattr(site_cookies, "_read_firefox_cookies", reader)
    monkeypatch.setattr(site_cookies, "firefox_profile_user_agent", lambda p: "")
    cfg = Config()
    profiles = [fake_profile(mtime=100.0)]
    site_cookies.auto_import_browser_profiles(cfg, profiles=profiles)
    site_cookies.auto_import_browser_profiles(cfg, profiles=profiles)
    assert len(reads) == 1


def test_changed_profile_is_reread(monkeypatch):
    store = {"/p/one": rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "old"))}
    patch_reader(monkeypatch, store)
    cfg = Config()
    site_cookies.auto_import_browser_profiles(cfg, profiles=[fake_profile(mtime=100.0)])
    store["/p/one"] = rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "new"))
    site_cookies.auto_import_browser_profiles(cfg, profiles=[fake_profile(mtime=200.0)])
    assert site_cookies.cookies_for("https://forum.audiogames.net/x")["cf_clearance"] == "new"


def test_one_unreadable_profile_does_not_block_the_others(monkeypatch):
    def reader(path):
        if path == "/p/locked":
            raise OSError("database is locked")
        return rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "tok"))

    monkeypatch.setattr(site_cookies, "_read_firefox_cookies", reader)
    monkeypatch.setattr(site_cookies, "firefox_profile_user_agent", lambda p: "")
    cfg = Config()
    imported = site_cookies.auto_import_browser_profiles(
        cfg, profiles=[fake_profile("/p/locked"), fake_profile("/p/ok")]
    )
    assert imported == 1
    # The failed profile keeps no marker, so the next tick retries it.
    markers = cfg.values.get("site_cookies_profile_mtimes") or {}
    assert not any("locked" in key for key in markers)
    assert any("ok" in key for key in markers)


def test_each_browsers_ua_is_scoped_to_the_hosts_it_supplied(monkeypatch):
    patch_reader(
        monkeypatch,
        {
            "/p/fx": rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "a")),
            "/p/lw": rows((".example.com", "/", True, False, FUTURE, "cf_clearance", "b")),
        },
        {"/p/fx": "Firefox/152.0", "/p/lw": "LibreWolf/151.0"},
    )
    site_cookies.auto_import_browser_profiles(
        Config(),
        profiles=[fake_profile("/p/fx"), fake_profile("/p/lw", mtime=101.0)],
    )
    assert site_cookies.user_agent_for("https://forum.audiogames.net/x") == "Firefox/152.0"
    assert site_cookies.user_agent_for("https://example.com/x") == "LibreWolf/151.0"


def test_respects_the_auto_import_setting(monkeypatch):
    patch_reader(
        monkeypatch,
        {"/p/one": rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "tok"))},
    )
    cfg = Config(auto_import_browser_cookies=False)
    assert site_cookies.auto_import_browser_profiles(cfg, profiles=[fake_profile()]) == 0
    assert site_cookies.cookies_for("https://forum.audiogames.net/x") == {}


def test_no_profiles_is_harmless(monkeypatch):
    assert site_cookies.auto_import_browser_profiles(Config(), profiles=[]) == 0


def test_manual_full_import_still_takes_everything(monkeypatch):
    # The user-initiated button is explicit consent and keeps its behavior.
    monkeypatch.setattr(
        site_cookies,
        "_read_firefox_cookies",
        lambda p: rows(
            (".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "tok"),
            (".audiogames.net", "/", True, True, FUTURE, "punbb_cookie", "login"),
        ),
    )
    assert site_cookies.import_from_browser_profile("/p/one") == 2
    assert "punbb_cookie" in site_cookies.cookies_for("https://forum.audiogames.net/x")


def test_freshest_clearance_wins_across_profiles(monkeypatch):
    # The bug this guards: profiles are read newest-database-first, so a plain
    # last-writer-wins merge let an OLD profile overwrite a new one. A 24-day-old
    # audiogames.net token beat one issued twelve minutes earlier, and 403'd.
    soon = int(time.time()) + 600
    later = int(time.time()) + 99999
    patch_reader(
        monkeypatch,
        {
            "/p/new": rows((".audiogames.net", "/", True, False, later, "cf_clearance", "fresh")),
            "/p/old": rows((".audiogames.net", "/", True, False, soon, "cf_clearance", "stale")),
        },
        {"/p/new": "Firefox/152.0", "/p/old": "Firefox/154.0"},
    )
    site_cookies.auto_import_browser_profiles(
        Config(),
        profiles=[fake_profile("/p/new", mtime=200.0), fake_profile("/p/old", mtime=100.0)],
    )
    url = "https://forum.audiogames.net/x"
    assert site_cookies.cookies_for(url)["cf_clearance"] == "fresh"
    # And the UA must be the one that earned the winning cookie, not the loser's.
    assert site_cookies.user_agent_for(url) == "Firefox/152.0"


def test_forced_refresh_ignores_the_mtime_marker(monkeypatch):
    # The marker is exactly what is in the way when the cookie we hold is dead,
    # so the "this one does not work" path must bypass it.
    store = {"/p/one": rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "old"))}
    patch_reader(monkeypatch, store)
    monkeypatch.setattr(site_cookies, "list_browser_profiles", lambda: [fake_profile()])
    cfg = Config()
    site_cookies.auto_import_browser_profiles(cfg, profiles=[fake_profile(mtime=100.0)])

    url = "https://forum.audiogames.net/x"
    store["/p/one"] = rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "new"))
    site_cookies._last_forced_refresh.clear()
    assert site_cookies.refresh_clearance_from_browsers(url) is True
    assert site_cookies.cookies_for(url)["cf_clearance"] == "new"


def test_forced_refresh_reports_no_change_when_the_browser_has_nothing_newer(monkeypatch):
    patch_reader(
        monkeypatch,
        {"/p/one": rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "same"))},
    )
    monkeypatch.setattr(site_cookies, "list_browser_profiles", lambda: [fake_profile()])
    url = "https://forum.audiogames.net/x"
    site_cookies._last_forced_refresh.clear()
    site_cookies.refresh_clearance_from_browsers(url)
    site_cookies._last_forced_refresh.clear()
    assert site_cookies.refresh_clearance_from_browsers(url) is False


def test_forced_refresh_is_rate_limited_per_host(monkeypatch):
    # A site that is simply blocked must not make every fetch re-read every
    # profile on the machine.
    reads = []

    def reader(path):
        reads.append(path)
        return rows((".audiogames.net", "/", True, False, FUTURE, "cf_clearance", "t"))

    monkeypatch.setattr(site_cookies, "_read_firefox_cookies", reader)
    monkeypatch.setattr(site_cookies, "firefox_profile_user_agent", lambda p: "")
    monkeypatch.setattr(site_cookies, "list_browser_profiles", lambda: [fake_profile()])
    url = "https://forum.audiogames.net/x"
    site_cookies._last_forced_refresh.clear()
    site_cookies.refresh_clearance_from_browsers(url)
    site_cookies.refresh_clearance_from_browsers(url)
    site_cookies.refresh_clearance_from_browsers(url)
    assert len(reads) == 1
