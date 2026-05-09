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
    <title>Retry Test Feed</title>
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

_CLOUDFLARE_CHALLENGE_HTML = """
<!doctype html>
<html><head><title>Just a moment...</title></head>
<body><script src="https://challenges.cloudflare.com/test"></script></body></html>
"""


class _DummyResp:
    def __init__(
        self,
        text: str,
        *,
        status_code: int = 200,
        content_type: str = "application/rss+xml",
        headers: dict | None = None,
    ) -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)
        self.response = self

    def raise_for_status(self) -> None:
        if int(self.status_code or 0) >= 400:
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


def _insert_feed(feed_url: str) -> str:
    feed_id = str(uuid.uuid4())
    conn = core.db.get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM chapters")
        c.execute("DELETE FROM articles")
        c.execute("DELETE FROM feeds")
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, feed_url, "Retry Test", "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def test_refresh_http_403_does_not_retry(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 5,
                }
            )
            feed_id = _insert_feed("https://example.com/feed.xml")
            calls = []
            sleeps = []
            states = []

            def _fake_get(url, **kwargs):
                calls.append((url, dict(kwargs or {})))
                return _DummyResp("forbidden", status_code=403, content_type="text/html; charset=utf-8")

            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)
            monkeypatch.setattr(local_mod.time, "sleep", lambda seconds: sleeps.append(seconds))

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True

            assert len(calls) == 1
            assert sleeps == []
            assert states[-1]["status"] == "error"
            assert "HTTP 403" in str(states[-1]["error"])
        finally:
            core.db.DB_FILE = orig_db_file


def test_refresh_retries_challenged_wordpress_feed_with_trailing_slash(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )
            feed_url = "https://www.alexjoneslive.com/feed"
            feed_id = _insert_feed(feed_url)
            calls = []

            def _fake_get(url, **kwargs):
                calls.append((url, dict(kwargs or {})))
                if url.endswith("/feed"):
                    return _DummyResp(
                        _CLOUDFLARE_CHALLENGE_HTML,
                        status_code=403,
                        content_type="text/html; charset=utf-8",
                        headers={"Cf-Mitigated": "challenge"},
                    )
                if url.endswith("/feed/"):
                    return _DummyResp(_RSS_XML)
                raise AssertionError(f"unexpected URL: {url}")

            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)

            assert provider.refresh_feed(feed_id) is True

            assert [url for url, _kwargs in calls] == [
                "https://www.alexjoneslive.com/feed",
                "https://www.alexjoneslive.com/feed/",
            ]
            articles = provider.get_articles(feed_id=feed_id)
            assert len(articles) == 1
            assert articles[0].title == "Episode 1"

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute("SELECT url FROM feeds WHERE id = ?", (feed_id,))
                assert c.fetchone()[0] == "https://www.alexjoneslive.com/feed/"
            finally:
                conn.close()
        finally:
            core.db.DB_FILE = orig_db_file


def test_add_feed_stores_challenged_wordpress_feed_trailing_slash(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )
            calls = []

            def _fake_get(url, **kwargs):
                calls.append((url, dict(kwargs or {})))
                if url.endswith("/feed"):
                    return _DummyResp(
                        _CLOUDFLARE_CHALLENGE_HTML,
                        status_code=403,
                        content_type="text/html; charset=utf-8",
                        headers={"Cf-Mitigated": "challenge"},
                    )
                if url.endswith("/feed/"):
                    return _DummyResp(_RSS_XML)
                raise AssertionError(f"unexpected URL: {url}")

            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)

            assert provider.add_feed("https://www.alexjoneslive.com/feed", "Tests") is True

            assert [url for url, _kwargs in calls] == [
                "https://www.alexjoneslive.com/feed",
                "https://www.alexjoneslive.com/feed/",
            ]
            feeds = provider.get_feeds()
            assert len(feeds) == 1
            assert feeds[0].url == "https://www.alexjoneslive.com/feed/"
            assert feeds[0].title == "Retry Test Feed"
        finally:
            core.db.DB_FILE = orig_db_file


def test_refresh_timeout_retries_once_then_succeeds(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 1,
                }
            )
            feed_id = _insert_feed("https://example.com/feed.xml")
            call_count = {"value": 0}
            sleeps = []

            def _fake_get(_url, **_kwargs):
                call_count["value"] += 1
                if call_count["value"] == 1:
                    raise requests.exceptions.Timeout("slow feed")
                return _DummyResp(_RSS_XML)

            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)
            monkeypatch.setattr(local_mod.time, "sleep", lambda seconds: sleeps.append(seconds))

            assert provider.refresh_feed(feed_id) is True

            articles = provider.get_articles(feed_id=feed_id)
            assert call_count["value"] == 2
            assert sleeps == [1.0]
            assert len(articles) == 1
            assert articles[0].title == "Episode 1"
        finally:
            core.db.DB_FILE = orig_db_file


def test_refresh_unresolved_homepage_uses_single_short_probe_and_caches_discovery_failure(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 15,
                    "feed_retry_attempts": 5,
                }
            )
            feed_id = _insert_feed("https://example.com/home")
            get_calls = []
            discover_calls = []
            states = []

            def _fake_discover(_url, request_timeout=10.0, probe_timeout=5.0):
                discover_calls.append((request_timeout, probe_timeout))
                return None

            def _fake_get(url, **kwargs):
                get_calls.append((url, dict(kwargs or {})))
                return _DummyResp("<html><body>Homepage</body></html>", content_type="text/html; charset=utf-8")

            monkeypatch.setattr(local_mod, "discover_feed", _fake_discover)
            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)
            monkeypatch.setattr(local_mod.time, "sleep", lambda _seconds: None)

            assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
            assert provider.refresh_feed(feed_id) is True

            assert len(discover_calls) == 1
            assert len(get_calls) == 2
            assert float(get_calls[0][1]["timeout"]) == 4.0
            assert states[-1]["status"] == "error"
            assert "Feed discovery failed" in str(states[-1]["error"])
            assert provider.get_articles(feed_id=feed_id) == []
        finally:
            core.db.DB_FILE = orig_db_file


def test_forced_full_refresh_bypasses_recent_failure_cooldown(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "max_concurrent_refreshes": 1,
                    "per_host_max_connections": 1,
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )
            feed_id = _insert_feed("https://example.com/feed.xml")
            calls = []
            states = []

            def _fake_get(url, **kwargs):
                calls.append((url, dict(kwargs or {})))
                return _DummyResp("forbidden", status_code=403, content_type="text/html; charset=utf-8")

            monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)

            assert provider.refresh_feed(feed_id) is True
            assert len(calls) == 1

            assert provider.refresh(progress_cb=states.append, force=True) is True

            assert len(calls) == 2
            assert states[-1]["id"] == feed_id
            assert states[-1]["status"] == "error"

            assert provider.refresh(progress_cb=states.append, force=False) is True
            assert len(calls) == 2
            assert states[-1]["status"] == "cooldown"
        finally:
            core.db.DB_FILE = orig_db_file
