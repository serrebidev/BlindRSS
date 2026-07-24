# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT


import pytest
import time
import os
import sys
import sqlite3
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers import local as local_provider
from providers.local import LocalProvider, _load_current_feed_articles_for_entries
from core.db import init_db, get_connection

# Mock feedparser response
class MockDict(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(name)

class MockEntry(MockDict):
    def __init__(self, i, chapter_url=None):
        self['id'] = f"item-{i}"
        self['title'] = f"Title {i}"
        self['link'] = f"http://example.com/item-{i}"
        self['published'] = "2023-01-01 12:00:00"
        self['content'] = [MockDict({"value": "Content"})]
        self['enclosures'] = []
        if chapter_url:
            self["podcast_chapters"] = MockDict({"href": chapter_url})
        # No need to manually set attributes due to __getattr__

class MockFeed:
    def __init__(self, count=100, chapter_url=None):
        self.entries = [MockEntry(i, chapter_url=chapter_url if i == 0 else None) for i in range(count)]
        self.feed = {"title": "Mock Feed"}
        self.bozo = False


def _add_test_feed(provider):
    provider.add_feed("http://example.com/feed.xml")
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM feeds")
    feed_id = c.fetchone()[0]
    c.execute("UPDATE feeds SET url = ? WHERE id = ?", ("http://example.com/feed.xml", feed_id))
    conn.commit()
    conn.close()
    return feed_id

@pytest.fixture
def provider(tmp_path):
    # Setup temporary DB
    db_path = tmp_path / "rss.db"
    with patch("core.db.DB_FILE", str(db_path)):
        # Initialize DB
        init_db()
        config = {"feed_timeout_seconds": 1, "feed_retry_attempts": 0}
        p = LocalProvider(config)
        yield p

def test_refresh_performance(provider):
    feed_id = _add_test_feed(provider)

    # Mock fetching
    with patch("core.utils.safe_requests_get") as mock_get, \
         patch("feedparser.parse") as mock_parse, \
         patch("core.utils.fetch_and_store_chapters") as mock_chapters:
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"xml"
        mock_resp.text = "xml"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp
        
        mock_parse.return_value = MockFeed()
        
        # Run refresh
        start_time = time.time()
        provider.refresh_feed(feed_id)
        duration = time.time() - start_time
        
        print(f"Refresh took {duration:.4f}s")
        
        # Verify articles inserted
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles")
        count = c.fetchone()[0]
        conn.close()
        
        assert count == 100
        
        # No chapter URL in the mock feed => chapter fetch path should be skipped.
        assert mock_chapters.call_count == 0


def test_refresh_existing_article_lookup_reads_only_current_feed_candidates():
    """A short feed response must not hydrate years of retained history into Python."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE articles (id TEXT PRIMARY KEY, feed_id TEXT, date TEXT, chapter_url TEXT, "
            "media_url TEXT, media_type TEXT, url TEXT, description TEXT)"
        )
        conn.executemany(
            "INSERT INTO articles (id, feed_id, date, chapter_url, media_url, media_type, url, description) "
            "VALUES (?, ?, '', NULL, NULL, NULL, '', '')",
            [(f"old-{index}", "feed-1") for index in range(2000)]
            + [
                ("current", "feed-1"),
                ("feed-1:collision", "feed-1"),
                ("other-feed-current", "feed-2"),
            ],
        )
        statements = []
        conn.set_trace_callback(statements.append)

        existing = _load_current_feed_articles_for_entries(
            conn.cursor(),
            "feed-1",
            ["current", "collision", "missing"],
        )

        assert set(existing) == {"current", "feed-1:collision"}
        article_queries = [statement for statement in statements if "FROM articles" in statement]
        assert len(article_queries) == 1
        assert "feed_id = 'feed-1' AND id IN" in article_queries[0]
    finally:
        conn.close()


def test_identical_refresh_skips_noop_existing_article_updates(provider, monkeypatch):
    """Forced refreshes still check version history, but do not rewrite unchanged article rows."""
    feed_id = _add_test_feed(provider)
    statements = []

    class RecordingCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def execute(self, statement, parameters=()):
            statements.append(str(statement))
            self._cursor.execute(statement, parameters)
            return self

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class RecordingConnection:
        def __init__(self, connection):
            self._connection = connection

        def cursor(self):
            return RecordingCursor(self._connection.cursor())

        def __getattr__(self, name):
            return getattr(self._connection, name)

    with patch("core.utils.safe_requests_get") as mock_get, patch("feedparser.parse") as mock_parse:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"xml"
        mock_resp.text = "xml"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp
        mock_parse.return_value = MockFeed(count=3)

        provider.refresh_feed(feed_id)

        original_get_connection = local_provider.get_connection
        monkeypatch.setattr(
            local_provider,
            "get_connection",
            lambda: RecordingConnection(original_get_connection()),
        )
        provider.refresh_feed(feed_id)

    assert not any("UPDATE articles SET date" in statement for statement in statements)


def test_progress_state_reuses_worker_unread_count_without_opening_another_connection(provider, monkeypatch):
    monkeypatch.setattr(
        local_provider,
        "get_connection",
        lambda: (_ for _ in ()).throw(AssertionError("must reuse the worker count")),
    )

    state = provider._collect_feed_state(
        "feed-1",
        "Feed title",
        "News",
        "ok",
        0,
        None,
        known_unread_count=7,
    )

    assert state["title"] == "Feed title"
    assert state["category"] == "News"
    assert state["unread_count"] == 7


def test_refresh_defers_chapter_fetch_when_chapter_url_present(provider):
    feed_id = _add_test_feed(provider)

    with patch("core.utils.safe_requests_get") as mock_get, \
         patch("feedparser.parse") as mock_parse, \
         patch("core.utils.fetch_and_store_chapters") as mock_chapters:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"xml"
        mock_resp.text = "<rss><channel><item><podcast:chapters href='https://example.com/chapters.json'/></item></channel></rss>"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        chapter_url = "https://example.com/chapters.json"
        mock_parse.return_value = MockFeed(count=5, chapter_url=chapter_url)

        provider.refresh_feed(feed_id)

        assert mock_chapters.call_count == 0

        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT chapter_url FROM articles ORDER BY id LIMIT 1")
            row = c.fetchone()
        finally:
            conn.close()

        assert row is not None
        assert row[0] == chapter_url


def test_get_article_chapters_fetches_stored_chapter_url_on_demand(provider):
    feed_id = _add_test_feed(provider)

    with patch("core.utils.safe_requests_get") as mock_get, \
         patch("feedparser.parse") as mock_parse, \
         patch("core.utils.fetch_and_store_chapters") as mock_chapters:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"xml"
        mock_resp.text = "<rss><channel><item><podcast:chapters href='https://example.com/chapters.json'/></item></channel></rss>"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        chapter_url = "https://example.com/chapters.json"
        mock_parse.return_value = MockFeed(count=1, chapter_url=chapter_url)
        mock_chapters.return_value = [{"start": 0.0, "title": "Intro", "href": None}]

        provider.refresh_feed(feed_id)

        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT id FROM articles ORDER BY id LIMIT 1")
            article_id = c.fetchone()[0]
        finally:
            conn.close()

        chapters = provider.get_article_chapters(article_id)

        assert chapters == [{"start": 0.0, "title": "Intro", "href": None}]
        assert mock_chapters.call_count == 1
        args, kwargs = mock_chapters.call_args
        assert args[0] == article_id
        assert kwargs == {"chapter_url": chapter_url}

if __name__ == "__main__":
    # Manually run if executed as script
    pass
