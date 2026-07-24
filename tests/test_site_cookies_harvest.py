# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Storing challenge clearance won by the headless browser (core/site_cookies.py)."""

import time

import pytest

from core import site_cookies


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Point the managed jar at a temp dir so tests never touch the real one."""
    monkeypatch.setattr(site_cookies.config_mod, "get_data_dir", lambda: str(tmp_path))
    site_cookies._invalidate()
    yield tmp_path
    site_cookies._invalidate()


class Cookie:
    """Stands in for a mycdp cookie object (attribute access, snake_case)."""

    def __init__(self, name, value, domain, path="/", expires: float = 0, secure=True, http_only=False):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.expires = expires
        self.secure = secure
        self.http_only = http_only


URL = "https://forum.audiogames.net/topic/59831/some-thread/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"


def test_clearance_cookie_is_stored_and_returned_for_the_site():
    stored = site_cookies.record_browser_session(
        URL,
        [Cookie("cf_clearance", "token-abc", ".audiogames.net", expires=time.time() + 3600)],
        UA,
    )
    assert stored == 1
    assert site_cookies.cookies_for(URL)["cf_clearance"] == "token-abc"


def test_harvested_ua_is_paired_with_the_cookie():
    # A clearance is only valid for the exact UA that earned it.
    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "t", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    assert site_cookies.user_agent_for(URL) == UA


def test_harvested_ua_does_not_leak_to_other_sites():
    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "t", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    site_cookies.set_user_agent("Manual/1.0")
    site_cookies.record_browser_session(
        "https://example.com/x",
        [Cookie("cf_clearance", "other", ".example.com", expires=time.time() + 3600)],
        "",
    )
    # audiogames keeps its harvested UA; example.com falls back to the manual one.
    assert site_cookies.user_agent_for(URL) == UA
    assert site_cookies.user_agent_for("https://example.com/x") == "Manual/1.0"


def test_harvest_does_not_overwrite_the_manual_global_ua():
    site_cookies.set_user_agent("Manual/1.0")
    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "t", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    assert site_cookies.get_user_agent() == "Manual/1.0"


def test_more_specific_host_rule_wins():
    site_cookies.record_browser_session(
        "https://audiogames.net/", [Cookie("cf_clearance", "a", ".audiogames.net")], "Parent/1.0"
    )
    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "b", ".audiogames.net")], "Child/1.0"
    )
    assert site_cookies.user_agent_for(URL) == "Child/1.0"


def test_tracking_cookies_are_not_stored():
    # A real session carries analytics and ad identifiers; keeping those would
    # leak the user's browsing into every later request for no benefit.
    stored = site_cookies.record_browser_session(
        URL,
        [
            Cookie("cf_clearance", "keep", ".audiogames.net"),
            Cookie("_ga", "GA1.2.999", ".audiogames.net"),
            Cookie("punbb_cookie", "session-value", ".audiogames.net"),
        ],
        UA,
    )
    assert stored == 1
    names = site_cookies.cookies_for(URL)
    assert "cf_clearance" in names
    assert "_ga" not in names
    assert "punbb_cookie" not in names


def test_third_party_cookies_from_the_page_are_ignored():
    stored = site_cookies.record_browser_session(
        URL,
        [
            Cookie("cf_clearance", "mine", ".audiogames.net"),
            Cookie("cf_clearance", "theirs", ".some-cdn.example"),
        ],
        UA,
    )
    assert stored == 1
    assert site_cookies.cookies_for(URL)["cf_clearance"] == "mine"


def test_session_cookies_get_a_bounded_life_not_an_eternal_one():
    # expires=0 means "session cookie" in the browser but "never expires" to
    # cookies_for(), which would serve a dead token forever.
    site_cookies.record_browser_session(
        URL, [Cookie("__cf_bm", "t", ".audiogames.net", expires=0)], UA
    )
    assert site_cookies.cookies_for(URL, now=time.time() + 86400) == {}
    assert "__cf_bm" in site_cookies.cookies_for(URL)


def test_dict_shaped_cookies_are_accepted():
    # Selenium's get_cookies() returns dicts with camelCase httpOnly.
    stored = site_cookies.record_browser_session(
        URL,
        [{
            "name": "cf_clearance",
            "value": "t",
            "domain": ".audiogames.net",
            "path": "/",
            "expiry": time.time() + 3600,
            "secure": True,
            "httpOnly": True,
        }],
        UA,
    )
    assert stored == 1
    assert site_cookies.cookies_for(URL)["cf_clearance"] == "t"


def test_harvest_merges_rather_than_replacing_an_earlier_import():
    site_cookies.record_browser_session(
        "https://example.com/", [Cookie("cf_clearance", "first", ".example.com")], "A/1"
    )
    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "second", ".audiogames.net")], "B/1"
    )
    assert site_cookies.cookies_for("https://example.com/")["cf_clearance"] == "first"
    assert site_cookies.cookies_for(URL)["cf_clearance"] == "second"


def test_refreshing_a_clearance_replaces_the_stale_one():
    site_cookies.record_browser_session(URL, [Cookie("cf_clearance", "old", ".audiogames.net")], UA)
    site_cookies.record_browser_session(URL, [Cookie("cf_clearance", "new", ".audiogames.net")], UA)
    assert site_cookies.cookies_for(URL)["cf_clearance"] == "new"


def test_nothing_harvestable_stores_nothing():
    assert site_cookies.record_browser_session(URL, [Cookie("_ga", "x", ".audiogames.net")], UA) == 0
    assert site_cookies.host_user_agent_for(URL) == ""


def test_bad_url_is_ignored():
    assert site_cookies.record_browser_session("", [Cookie("cf_clearance", "t", ".x.net")], UA) == 0


def test_utils_sends_the_harvested_pair_together():
    from core import utils

    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "token", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    headers = utils._apply_site_cookies(URL, {"User-Agent": "BlindRSS/1.0"})
    assert "cf_clearance=token" in headers["Cookie"]
    assert headers["User-Agent"] == UA


def test_caller_supplied_cookie_header_is_left_alone():
    from core import utils

    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "token", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    headers = utils._apply_site_cookies(URL, {"Cookie": "mine=1", "User-Agent": "BlindRSS/1.0"})
    assert headers["Cookie"] == "mine=1"
    assert headers["User-Agent"] == "BlindRSS/1.0"


def test_firefox_session_requests_the_firefox_handshake():
    # A clearance cookie is validated against the TLS/HTTP handshake too:
    # measured on forum.audiogames.net, the same fresh cookie 403'd on plain
    # requests and on curl_cffi's Chrome hello, and returned the article on
    # its Firefox one.
    from core import user_agents, utils

    site_cookies.record_browser_session(
        URL,
        [Cookie("cf_clearance", "t", ".audiogames.net", expires=time.time() + 3600)],
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    )
    assert user_agents.impersonate_target_for_ua("... Firefox/152.0") == "firefox"
    if utils.CURL_CFFI_AVAILABLE:
        assert utils._site_cookie_impersonation(URL) == "firefox"


def test_chromium_session_requests_the_chrome_handshake():
    from core import user_agents

    assert user_agents.impersonate_target_for_ua("... Chrome/150.0.0.0 Safari/537.36") == "chrome"
    assert user_agents.impersonate_target_for_ua("... Chrome/150.0.0.0 Edg/150.0.0.0") == "chrome"


def test_site_without_a_stored_session_is_not_forced_to_impersonate():
    from core import utils

    assert utils._site_cookie_impersonation("https://example.org/no-session") == ""


def test_ordinary_login_cookies_do_not_pin_a_ua_or_force_impersonation():
    # Regression: a full manual jar import put github's login cookies in the
    # jar, and the global UA then applied to every host with ANY cookie. Every
    # api.github.com call went out with a Firefox User-Agent, the user's github
    # cookies, and a forced curl_cffi handshake.
    from core import utils

    site_cookies.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0")
    site_cookies._merge_records_into_jar([
        (".github.com", "TRUE", "/", "TRUE", str(int(time.time()) + 86400), "logged_in", "yes"),
    ])
    url = "https://api.github.com/repos/x/y"
    assert site_cookies.cookies_for(url)          # the cookie is still sent
    assert not site_cookies.has_clearance_for(url)
    assert site_cookies.user_agent_for(url) == ""  # but no UA is forced
    assert utils._site_cookie_impersonation(url) == ""


def test_global_ua_still_applies_to_a_site_with_a_clearance():
    manual = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    site_cookies.set_user_agent(manual)
    site_cookies._merge_records_into_jar([
        (".audiogames.net", "TRUE", "/", "TRUE", str(int(time.time()) + 3600), "cf_clearance", "t"),
    ])
    assert site_cookies.has_clearance_for(URL)
    assert site_cookies.user_agent_for(URL) == manual


def test_host_ua_is_dropped_once_its_cookies_are_gone():
    # A pinned UA outliving its cookies would keep changing the fingerprint of
    # a site the jar no longer has anything for.
    site_cookies.set_host_user_agent("audiogames.net", "Firefox/152.0")
    assert site_cookies.user_agent_for(URL) == ""


def test_clearance_site_skips_the_chromium_fallback(monkeypatch):
    # Every article on a session-gated site is a new URL, so browser_feed's
    # per-URL cooldown never kicked in and each one paid a fresh ~40s Chromium
    # launch to fail. The site wants a browser session the automated browser
    # has been measured unable to win; a current cookie is the only fix.
    from core import article_extractor as ae

    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "t", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    assert ae._has_stored_clearance(URL) is True
    assert ae._has_stored_clearance("https://www.nytimes.com/some-article") is False


def test_blocked_message_names_a_readable_browser_for_a_clearance_site(monkeypatch):
    from core import article_extractor as ae

    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "t", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    monkeypatch.setattr(ae, "_readable_browser_names", lambda: ["Firefox"])
    message = ae._blocked_interstitial_message(URL)
    assert "Firefox" in message
    assert "expired" in message


def test_blocked_message_stays_generic_without_a_stored_session(monkeypatch):
    from core import article_extractor as ae

    monkeypatch.setattr(ae, "_readable_browser_names", lambda: ["Firefox"])
    message = ae._blocked_interstitial_message("https://www.nytimes.com/some-article")
    assert "Firefox" not in message
    assert "Open the original link" in message


def test_blocked_message_stays_generic_with_no_readable_browser(monkeypatch):
    # A Chromium-only machine has nothing to point the user at.
    from core import article_extractor as ae

    site_cookies.record_browser_session(
        URL, [Cookie("cf_clearance", "t", ".audiogames.net", expires=time.time() + 3600)], UA
    )
    monkeypatch.setattr(ae, "_readable_browser_names", lambda: [])
    assert "Open the original link" in ae._blocked_interstitial_message(URL)
