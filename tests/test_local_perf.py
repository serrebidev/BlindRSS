
import pytest
import time
import os
import sys
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.local import LocalProvider
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


def test_refresh_fetches_chapters_when_chapter_url_present(provider):
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

        assert mock_chapters.call_count == 1
        args, kwargs = mock_chapters.call_args
        assert args[3] == chapter_url
        assert kwargs["cursor"] is not None

if __name__ == "__main__":
    # Manually run if executed as script
    pass
