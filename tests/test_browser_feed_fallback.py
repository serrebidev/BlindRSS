# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Automated real-browser feed fallback tests."""

import os
import tempfile
import uuid

import requests

import core.db
from core import browser_feed
import providers.local as local_mod
from providers.local import LocalProvider


_RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Browser Fallback Feed</title>
    <item>
      <guid>browser-item-1</guid>
      <title>Recovered item</title>
      <link>https://example.com/recovered</link>
      <description>Recovered through the browser.</description>
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


class _Response:
    def __init__(self, text, status=200, content_type="text/html"):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.url = "https://example.com/feed.xml"
        self.history = []
        self.response = self

    def raise_for_status(self):
        if self.status_code >= 400:
            exc = requests.HTTPError(f"{self.status_code} error")
            exc.response = self
            raise exc


def _insert_feed(url="https://example.com/feed.xml"):
    feed_id = str(uuid.uuid4())
    conn = core.db.get_connection()
    try:
        conn.execute("DELETE FROM articles")
        conn.execute("DELETE FROM feeds")
        conn.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, url, "Browser fallback test", "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _provider(enabled=True):
    return LocalProvider(
        {
            "providers": {"local": {}},
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
            "browser_feed_fallback_enabled": enabled,
            "browser_feed_fallback_timeout_seconds": 45,
        }
    )


def test_extracts_chromium_pre_wrapped_rss():
    wrapped = (
        '<html><head></head><body><pre style="word-wrap: break-word">'
        + _RSS_XML.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</pre></body></html>"
    )
    assert browser_feed._feed_text_from_page_source(wrapped) == _RSS_XML


def test_feed_validation_accepts_json_feed_and_rejects_html():
    assert browser_feed._looks_like_feed_text(
        '{"version":"https://jsonfeed.org/version/1.1","items":[]}'
    )
    assert not browser_feed._looks_like_feed_text(_HTML)
    assert browser_feed._feed_text_from_page_source(
        "<html><body><pre>ordinary text</pre></body></html>"
    ) is None


def test_browser_options_are_fully_automatic_and_invisible(monkeypatch):
    monkeypatch.setattr(browser_feed, "_google_chrome_available", lambda: False)

    options = browser_feed._browser_options("profile", None)

    assert options["uc"] is True
    assert options["headless2"] is True
    assert options["test"] is False
    assert options["no_screenshot"] is True
    assert options["cft"] is True
    # We want the DOM, not the pixels: dropping images and returning at
    # DOMContentLoaded is what keeps the fallback from costing tens of seconds.
    assert options["block_images"] is True
    assert options["page_load_strategy"] == "eager"
    # ad_block_on unpacks its extension next to the process cwd, which is
    # Program Files in an installed build.
    assert "ad_block_on" not in options
    # Nothing per-call may leak into the options, or every fetch would build a
    # session of its own instead of reusing the warm one.
    assert "time_limit" not in options


def test_http_error_uses_browser_fallback_once(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            browser_calls = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_HTML, status=403),
            )

            def _browser_fetch(url, **kwargs):
                browser_calls.append((url, kwargs))
                return browser_feed.BrowserFeedResponse(_RSS_XML, url)

            monkeypatch.setattr(local_mod.browser_feed_mod, "fetch_feed", _browser_fetch)

            assert provider.refresh_feed(feed_id) is True
            assert len(browser_calls) == 1
            assert browser_calls[0][1]["timeout_s"] == 45
            articles = provider.get_articles(feed_id=feed_id)
            assert len(articles) == 1
            assert articles[0].title == "Recovered item"
        finally:
            core.db.DB_FILE = old_db


def test_challenge_interstitial_200_uses_browser_fallback(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            browser_calls = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_CHALLENGE_HTML, status=200),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda url, **_k: browser_calls.append(url)
                or browser_feed.BrowserFeedResponse(_RSS_XML, url),
            )

            assert provider.refresh_feed(feed_id) is True
            assert browser_calls == ["https://example.com/feed.xml"]
            assert len(provider.get_articles(feed_id=feed_id)) == 1
        finally:
            core.db.DB_FILE = old_db


def test_plain_html_response_skips_browser_fallback(monkeypatch):
    """A 200 webpage without challenge markers is not bot protection (issue #79
    follow-up: escalating those more than doubled large-collection refreshes)."""
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            states = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_HTML, status=200),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not launch")),
            )

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert states[-1]["status"] == "error"
        finally:
            core.db.DB_FILE = old_db


def test_malformed_feed_response_skips_browser_fallback(monkeypatch):
    """A truncated feed body is a broken feed, not bot protection."""
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            states = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(
                    "<rss><channel>",
                    status=200,
                    content_type="application/rss+xml",
                ),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not launch")),
            )

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert states[-1]["status"] == "error"
        finally:
            core.db.DB_FILE = old_db


def test_dead_feed_404_skips_browser_fallback(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            states = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_HTML, status=404),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not launch")),
            )

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert states[-1]["status"] == "error"
        finally:
            core.db.DB_FILE = old_db


def test_timeout_skips_browser_fallback(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            states = []

            def _timeout(*_a, **_k):
                raise requests.exceptions.ReadTimeout("Read timed out.")

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _timeout)
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not launch")),
            )

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert states[-1]["status"] == "error"
        finally:
            core.db.DB_FILE = old_db


def test_connection_reset_uses_browser_fallback(monkeypatch):
    """A WAF-style reset after all plain retries still escalates to the browser."""
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(enabled=True)
            feed_id = _insert_feed()
            browser_calls = []

            def _reset(*_a, **_k):
                raise requests.exceptions.ConnectionError(
                    "('Connection aborted.', ConnectionResetError(10054, 'reset'))"
                )

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _reset)
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda url, **_k: browser_calls.append(url)
                or browser_feed.BrowserFeedResponse(_RSS_XML, url),
            )

            assert provider.refresh_feed(feed_id) is True
            assert browser_calls == ["https://example.com/feed.xml"]
            assert len(provider.get_articles(feed_id=feed_id)) == 1
        finally:
            core.db.DB_FILE = old_db


def test_negative_cooldown_blocks_repeat_browser_attempts(monkeypatch):
    url = "https://cooldown.example/feed.xml"
    browser_feed._clear_negative_result(url)
    assert not browser_feed._negative_result_active(url)

    browser_feed._record_negative_result(url)
    assert browser_feed._negative_result_active(url)

    # fetch_feed must return before ever touching the browser lock.
    monkeypatch.setattr(
        browser_feed,
        "_acquire_fetch_lock",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not attempt")),
    )
    assert browser_feed.fetch_feed(url, timeout_s=15) is None

    browser_feed._clear_negative_result(url)
    assert not browser_feed._negative_result_active(url)


def test_partial_config_keeps_browser_fallback_disabled(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        old_db = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )
            feed_id = _insert_feed()
            states = []

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", False)
            monkeypatch.setattr(
                local_mod.utils,
                "safe_requests_get",
                lambda *_a, **_k: _Response(_HTML, status=403),
            )
            monkeypatch.setattr(
                local_mod.browser_feed_mod,
                "fetch_feed",
                lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not launch")),
            )

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert states[-1]["status"] == "error"
        finally:
            core.db.DB_FILE = old_db
