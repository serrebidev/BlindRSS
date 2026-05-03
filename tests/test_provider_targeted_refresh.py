import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.models import Feed
from providers.bazqux import BazQuxProvider
from providers.base import RSSProvider
from providers.theoldreader import TheOldReaderProvider


class _MinimalProvider(RSSProvider):
    def __init__(self):
        super().__init__({})
        self.calls = []

    def get_name(self):
        return "Minimal"

    def refresh(self, progress_cb=None, force: bool = False):
        return True

    def refresh_feed(self, feed_id: str, progress_cb=None):
        self.calls.append(str(feed_id))
        if callable(progress_cb):
            progress_cb({"id": str(feed_id), "status": "ok"})
        return str(feed_id) != "bad"

    def get_feeds(self):
        return []

    def get_articles(self, feed_id: str):
        return []

    def mark_read(self, article_id: str):
        return True

    def mark_unread(self, article_id: str):
        return True

    def add_feed(self, url: str, category: str = None):
        return True

    def remove_feed(self, feed_id: str):
        return True

    def get_categories(self):
        return []

    def add_category(self, title: str, parent_title: str = None):
        return True

    def rename_category(self, old_title: str, new_title: str):
        return True

    def delete_category(self, title: str):
        return True


def _feed(feed_id, title="Feed", category="Podcasts", unread=0):
    feed = Feed(id=feed_id, title=title, url=f"https://example.com/{feed_id}.xml", category=category)
    feed.unread_count = unread
    return feed


def test_base_batch_refresh_dedupes_and_reports_failures():
    provider = _MinimalProvider()
    states = []

    ok = provider.refresh_feeds_by_ids(["one", "one", "", "bad"], progress_cb=states.append)

    assert ok is False
    assert provider.calls == ["one", "bad"]
    assert states == [{"id": "one", "status": "ok"}, {"id": "bad", "status": "ok"}]


def test_theoldreader_targeted_refresh_emits_feed_state(monkeypatch):
    provider = TheOldReaderProvider({"providers": {"theoldreader": {"email": "user", "password": "pw"}}})
    feed = _feed("feed/https://example.com/rss", title="Reader Feed", category="News", unread=3)
    states = []

    monkeypatch.setattr(provider, "_login", lambda: True)
    monkeypatch.setattr(provider, "get_feeds", lambda: [feed])

    assert provider.refresh_feed("feed/https://example.com/rss", progress_cb=states.append) is True

    assert states == [
        {
            "id": "feed/https://example.com/rss",
            "title": "Reader Feed",
            "category": "News",
            "unread_count": 3,
            "status": "ok",
            "new_items": None,
            "error": None,
        }
    ]


def test_bazqux_targeted_refresh_emits_feed_state(monkeypatch):
    provider = BazQuxProvider({"providers": {"bazqux": {"email": "user", "password": "pw"}}})
    feed = _feed("feed/https://example.com/rss", title="BazQux Feed", category="Tech", unread=2)
    states = []

    monkeypatch.setattr(provider, "_login", lambda: True)
    monkeypatch.setattr(provider, "get_feeds", lambda: [feed])

    assert provider.refresh_feeds_by_ids(["feed/https://example.com/rss"], progress_cb=states.append) is True

    assert states == [
        {
            "id": "feed/https://example.com/rss",
            "title": "BazQux Feed",
            "category": "Tech",
            "unread_count": 2,
            "status": "ok",
            "new_items": None,
            "error": None,
        }
    ]
