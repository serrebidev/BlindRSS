"""Provider-level tests for impersonation escalation and per-feed HTTP overrides (issue #29)."""

import os
import sys
import tempfile
import uuid

import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db
import providers.local as local_mod
from providers.local import LocalProvider


_RSS_XML = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Impersonation Test Feed</title>
    <item>
      <guid>episode-1</guid>
      <title>Episode 1</title>
      <link>https://example.com/episode-1</link>
      <description>Test item</description>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class _DummyResp:
    def __init__(self, text, *, status_code=200, content_type="application/rss+xml", headers=None):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)
        self.url = "https://example.com/feed.xml"
        self.response = self

    def raise_for_status(self):
        if int(self.status_code or 0) >= 400:
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


def _insert_feed(feed_url, settings=None):
    feed_id = str(uuid.uuid4())
    conn = core.db.get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM articles")
        c.execute("DELETE FROM feeds")
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, feed_url, "Impersonation Test", "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    if settings is not None:
        core.db.set_feed_settings(feed_id, settings)
    return feed_id


def _provider(retries=1):
    return LocalProvider(
        {
            "providers": {"local": {}},
            "feed_timeout_seconds": 15,
            "feed_retry_attempts": retries,
        }
    )


def test_auto_mode_escalates_to_impersonation_after_reset(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(retries=1)
            feed_id = _insert_feed("https://example.com/feed.xml")
            calls = []

            def _fake_get(url, **kwargs):
                impersonated = bool(kwargs.get("impersonate"))
                calls.append(impersonated)
                # Plain requests always reset; only the impersonated attempt succeeds.
                if not impersonated:
                    raise requests.exceptions.ConnectionError("Connection aborted. ConnectionResetError(10054)")
                return _DummyResp(_RSS_XML)

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", True)
            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)
            monkeypatch.setattr(local_mod.time, "sleep", lambda *_a: None)

            assert provider.refresh_feed(feed_id) is True
            # Plain attempts (full budget) reset first, then one last-resort impersonated
            # attempt succeeds.
            assert calls[-1] is True
            assert calls[:-1] and not any(calls[:-1])
            assert len(provider.get_articles(feed_id=feed_id)) == 1
        finally:
            core.db.DB_FILE = orig


def test_always_mode_impersonates_first_attempt(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(retries=1)
            feed_id = _insert_feed("https://example.com/feed.xml", settings={"impersonate": "always"})
            calls = []

            def _fake_get(url, **kwargs):
                calls.append(bool(kwargs.get("impersonate")))
                return _DummyResp(_RSS_XML)

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", True)
            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)

            assert provider.refresh_feed(feed_id) is True
            assert calls == [True]
        finally:
            core.db.DB_FILE = orig


def test_never_mode_does_not_impersonate(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(retries=1)
            feed_id = _insert_feed("https://example.com/feed.xml", settings={"impersonate": "never"})
            calls = []
            states = []

            def _fake_get(url, **kwargs):
                calls.append(bool(kwargs.get("impersonate")))
                raise requests.exceptions.ConnectionError("Connection reset")

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", True)
            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)
            monkeypatch.setattr(local_mod.time, "sleep", lambda *_a: None)

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert calls and not any(calls)  # never impersonated
            assert states[-1]["status"] == "error"
        finally:
            core.db.DB_FILE = orig


def test_per_feed_custom_headers_timeout_and_referer_applied(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(retries=0)
            feed_id = _insert_feed(
                "https://news.example.com/rss",
                settings={"custom_headers": {"X-Test": "1"}, "timeout_seconds": 42},
            )
            seen = {}

            def _fake_get(url, **kwargs):
                seen["headers"] = dict(kwargs.get("headers") or {})
                seen["timeout"] = kwargs.get("timeout")
                return _DummyResp(_RSS_XML)

            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)

            assert provider.refresh_feed(feed_id) is True
            assert seen["headers"].get("X-Test") == "1"
            assert seen["headers"].get("Referer") == "https://news.example.com/"
            assert float(seen["timeout"]) == 42.0
        finally:
            core.db.DB_FILE = orig


_HTML_BLOCK = "<!doctype html><html><head><title>Access denied</title></head><body>Blocked</body></html>"


def test_block_response_escalates_to_impersonation(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(retries=1)
            feed_id = _insert_feed("https://example.com/feed.xml")
            calls = []

            def _fake_get(url, **kwargs):
                impersonated = bool(kwargs.get("impersonate"))
                calls.append(impersonated)
                if not impersonated:
                    # 200 OK HTML interstitial (a "soft" anti-bot block).
                    return _DummyResp(_HTML_BLOCK, content_type="text/html; charset=utf-8")
                return _DummyResp(_RSS_XML)

            monkeypatch.setattr(local_mod.utils, "CURL_CFFI_AVAILABLE", True)
            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)
            monkeypatch.setattr(local_mod.time, "sleep", lambda *_a: None)

            assert provider.refresh_feed(feed_id) is True
            # Plain attempt got the HTML block; impersonation got the real feed.
            assert calls[-1] is True
            assert calls[:-1] and not any(calls[:-1])
            assert len(provider.get_articles(feed_id=feed_id)) == 1
        finally:
            core.db.DB_FILE = orig


def test_per_feed_proxy_passed_to_both_transports(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = _provider(retries=0)
            feed_id = _insert_feed(
                "https://news.example.com/rss",
                settings={"proxy": "http://127.0.0.1:8888"},
            )
            seen = {}

            def _fake_get(url, **kwargs):
                seen["proxies"] = kwargs.get("proxies")
                return _DummyResp(_RSS_XML)

            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)

            assert provider.refresh_feed(feed_id) is True
            assert seen["proxies"] == {
                "http": "http://127.0.0.1:8888",
                "https": "http://127.0.0.1:8888",
            }
        finally:
            core.db.DB_FILE = orig


def test_response_looks_blocked_classification():
    # Cloudflare challenge -> blocked.
    cf = _DummyResp("just a moment", status_code=403, content_type="text/html",
                    headers={"Cf-Mitigated": "challenge"})
    assert local_mod._response_looks_blocked(cf) is True
    # 200 OK HTML interstitial -> blocked.
    html = _DummyResp(_HTML_BLOCK, status_code=200, content_type="text/html")
    assert local_mod._response_looks_blocked(html) is True
    # A real feed -> not blocked.
    feed = _DummyResp(_RSS_XML, status_code=200, content_type="application/rss+xml")
    assert local_mod._response_looks_blocked(feed) is False
    # A plain 403 (no challenge) -> not treated as a block (avoid needless retries).
    forbidden = _DummyResp("forbidden", status_code=403, content_type="text/plain")
    assert local_mod._response_looks_blocked(forbidden) is False
