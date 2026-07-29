# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tier-3 pydoll challenge-escalation tests (offline; faked browsers)."""

import asyncio
import contextlib
import sys
import types

import pytest

from core import browser_feed
from core import site_cookies

# conftest stubs _fetch_browser_document suite-wide so mocked HTTP tests never
# launch a real browser. These tests exercise that function deliberately, so
# keep a reference to the real one (captured at import, before fixtures run).
_REAL_FETCH_BROWSER_DOCUMENT = browser_feed._fetch_browser_document


_RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Escalated Feed</title>
    <item>
      <guid>escalated-item-1</guid>
      <title>Recovered item</title>
      <link>https://example.com/recovered</link>
    </item>
  </channel>
</rss>
"""

_HTML = "<!doctype html><html><head><title>Blocked</title></head><body>No feed</body></html>"

_CHALLENGE_HTML = (
    "<!doctype html><html><head><title>Just a moment...</title>"
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
    "</head><body>Verifying you are human.</body></html>"
)


@pytest.fixture(autouse=True)
def _clean_state():
    browser_feed._negative_results.clear()
    browser_feed._pydoll_unavailable = False
    yield
    browser_feed._negative_results.clear()
    browser_feed._pydoll_unavailable = False


def _stub_uc_failure(monkeypatch, tmp_path, page_source):
    """Make the UC path run to completion and return no usable document."""
    monkeypatch.setattr(browser_feed, "_fetch_browser_document", _REAL_FETCH_BROWSER_DOCUMENT)
    monkeypatch.setattr(browser_feed.config_mod, "get_data_dir", lambda: str(tmp_path))
    fake_sb = types.SimpleNamespace(
        get_page_source=lambda: page_source,
        activate_cdp_mode=lambda url: None,
    )
    monkeypatch.setattr(browser_feed, "_session_locked", lambda SB, options: fake_sb)
    monkeypatch.setattr(browser_feed, "_settle_page", lambda *a, **k: None)


def test_no_escalation_without_challenge(monkeypatch, tmp_path):
    """A UC failure that is not a challenge page never pays a second launch."""
    _stub_uc_failure(monkeypatch, tmp_path, _HTML)
    calls = []
    monkeypatch.setattr(
        browser_feed,
        "_fetch_with_pydoll",
        lambda *a, **k: calls.append((a, k)) or None,
    )

    assert browser_feed.fetch_feed("https://no-challenge.example/feed.xml", timeout_s=15) is None
    assert calls == []


def test_escalation_on_challenge_returns_response(monkeypatch, tmp_path):
    _stub_uc_failure(monkeypatch, tmp_path, _CHALLENGE_HTML)
    url = "https://challenge.example/feed.xml"
    calls = []

    def _fake_pydoll(target, **kwargs):
        calls.append((target, kwargs))
        return browser_feed.BrowserFeedResponse(text=_RSS_XML, url=target)

    monkeypatch.setattr(browser_feed, "_fetch_with_pydoll", _fake_pydoll)

    response = browser_feed.fetch_feed(url, timeout_s=15)
    assert isinstance(response, browser_feed.BrowserFeedResponse)
    assert "Escalated Feed" in response.text
    assert calls and calls[0][0] == url
    assert calls[0][1]["feed_only"] is True
    # A successful escalation clears any recorded negative for the URL.
    assert not browser_feed._negative_result_active(url)


def test_escalation_failure_records_negative_result(monkeypatch, tmp_path):
    _stub_uc_failure(monkeypatch, tmp_path, _CHALLENGE_HTML)
    url = "https://still-blocked.example/feed.xml"
    monkeypatch.setattr(browser_feed, "_fetch_with_pydoll", lambda *a, **k: None)

    assert browser_feed.fetch_feed(url, timeout_s=15) is None
    assert browser_feed._negative_result_active(url)


def test_fetch_with_pydoll_fails_closed_without_pydoll(monkeypatch, tmp_path):
    """A missing pydoll install disables the tier for the process lifetime."""
    monkeypatch.setattr(browser_feed.config_mod, "get_data_dir", lambda: str(tmp_path))
    monkeypatch.setitem(sys.modules, "pydoll", None)

    assert (
        browser_feed._fetch_with_pydoll(
            "https://x.example/feed.xml",
            timeout_s=15,
            feed_only=True,
            cancel_event=None,
            proxy=None,
        )
        is None
    )
    assert browser_feed._pydoll_unavailable is True


def test_pydoll_binary_location_uses_cft_without_system_chrome(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_feed, "_google_chrome_available", lambda: False)
    assert browser_feed._pydoll_binary_location(str(tmp_path)) is None

    cft = tmp_path / "chrome-win64"
    cft.mkdir()
    binary = cft / "chrome.exe"
    binary.write_text("binary")
    assert browser_feed._pydoll_binary_location(str(tmp_path)) == str(binary)


def test_pydoll_binary_location_prefers_auto_detect_with_system_chrome(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_feed, "_google_chrome_available", lambda: True)
    cft = tmp_path / "chrome-win64"
    cft.mkdir()
    (cft / "chrome.exe").write_text("binary")
    assert browser_feed._pydoll_binary_location(str(tmp_path)) is None


class _FakeOptions:
    def __init__(self):
        self.headless = False
        self.binary_location = ""
        self.arguments = []

    def add_argument(self, argument):
        self.arguments.append(argument)


class _FakeTab:
    def __init__(self, pages):
        self._pages = list(pages)

    @contextlib.asynccontextmanager
    async def expect_and_bypass_cloudflare_captcha(self, **kwargs):
        yield

    async def go_to(self, url, timeout=300):
        self.url = url

    @property
    async def page_source(self):
        return self._pages.pop(0) if self._pages else _RSS_XML

    async def execute_script(self, script, **kwargs):
        value = "https://example.com/final" if "location.href" in script else "FakeChrome/1.0"
        return {"result": {"result": {"value": value}}}

    async def get_cookies(self):
        return [{"name": "cf_clearance", "value": "token", "domain": ".example.com"}]


class _FakeChrome:
    instances = []

    def __init__(self, options=None):
        self.options = options
        _FakeChrome.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def start(self):
        return _FakeTab([_CHALLENGE_HTML, _RSS_XML])


def _install_fake_pydoll(monkeypatch):
    chromium = types.ModuleType("pydoll.browser.chromium")
    chromium.Chrome = _FakeChrome
    options_mod = types.ModuleType("pydoll.browser.options")
    options_mod.ChromiumOptions = _FakeOptions
    browser_pkg = types.ModuleType("pydoll.browser")
    pydoll_pkg = types.ModuleType("pydoll")
    monkeypatch.setitem(sys.modules, "pydoll", pydoll_pkg)
    monkeypatch.setitem(sys.modules, "pydoll.browser", browser_pkg)
    monkeypatch.setitem(sys.modules, "pydoll.browser.chromium", chromium)
    monkeypatch.setitem(sys.modules, "pydoll.browser.options", options_mod)


def test_pydoll_attempt_settles_past_challenge_and_harvests(monkeypatch, tmp_path):
    _install_fake_pydoll(monkeypatch)
    monkeypatch.setattr(browser_feed.config_mod, "get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(browser_feed, "_google_chrome_available", lambda: True)
    recorded = []
    monkeypatch.setattr(
        site_cookies,
        "record_browser_session",
        lambda url, cookies, ua="": recorded.append((url, cookies, ua)),
    )

    response = browser_feed._fetch_with_pydoll(
        "https://example.com/feed.xml",
        timeout_s=20,
        feed_only=True,
        cancel_event=None,
        proxy=None,
    )

    assert isinstance(response, browser_feed.BrowserFeedResponse)
    assert "Escalated Feed" in response.text
    assert response.url == "https://example.com/final"
    # The browser must stay completely invisible, same rule as headless2.
    assert _FakeChrome.instances[-1].options.headless is True
    # The won clearance is handed to site_cookies with its exact UA.
    assert recorded
    url, cookies, ua = recorded[-1]
    assert url == "https://example.com/final"
    assert cookies[0]["name"] == "cf_clearance"
    assert ua == "FakeChrome/1.0"


def test_pydoll_attempt_returns_none_when_page_never_becomes_usable(monkeypatch, tmp_path):
    _install_fake_pydoll(monkeypatch)

    class _BlockedChrome(_FakeChrome):
        async def start(self):
            return _FakeTab([_CHALLENGE_HTML] * 100)

    chromium = sys.modules["pydoll.browser.chromium"]
    monkeypatch.setattr(chromium, "Chrome", _BlockedChrome)

    result = asyncio.run(
        browser_feed._pydoll_attempt(
            "https://example.com/feed.xml",
            budget_s=1.0,
            feed_only=True,
            cancel_event=None,
            proxy=None,
            profile_dir=str(tmp_path),
            runtime_dir=str(tmp_path),
        )
    )
    assert result is None
