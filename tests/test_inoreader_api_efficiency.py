import os
import sys

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.models import Feed
from providers.inoreader import InoreaderProvider


def test_inoreader_refresh_skips_when_metadata_cache_is_fresh():
    provider = InoreaderProvider(
        {
            "providers": {
                "inoreader": {
                    "app_id": "app",
                    "app_key": "key",
                    "token": "token",
                    "metadata_cache_ttl_seconds": 3600,
                }
            }
        }
    )

    provider._set_feed_cache([Feed(id="feed/http://example.com/rss", title="Example", url="http://example.com/rss")])

    # Auto refresh should not trigger a feed/category re-fetch when metadata cache is still fresh.
    assert provider.refresh(force=False) is False

    # Manual refresh should still invalidate caches and force a UI reload.
    assert provider.refresh(force=True) is True


def test_inoreader_targeted_refresh_invalidates_article_cache_and_emits_progress(monkeypatch):
    provider = InoreaderProvider(
        {
            "providers": {
                "inoreader": {
                    "app_id": "app",
                    "app_key": "key",
                    "token": "token",
                    "metadata_cache_ttl_seconds": 3600,
                }
            }
        }
    )
    feed = Feed(id="feed/http://example.com/rss", title="Example", url="http://example.com/rss", category="Podcasts")
    feed.unread_count = 4
    provider._article_view_cache["all"] = {"articles": [object()], "updated_at": 1.0}
    calls = {"get_feeds": 0}

    monkeypatch.setattr(provider, "_has_required_auth", lambda: True)

    def _fake_get_feeds():
        calls["get_feeds"] += 1
        return [feed]

    monkeypatch.setattr(provider, "get_feeds", _fake_get_feeds)
    states = []

    assert provider.refresh_feeds_by_ids(
        ["feed/http://example.com/rss", "feed/http://example.com/rss"],
        progress_cb=states.append,
    ) is True

    assert calls["get_feeds"] == 1
    assert provider._article_view_cache == {}
    assert states == [
        {
            "id": "feed/http://example.com/rss",
            "title": "Example",
            "category": "Podcasts",
            "unread_count": 4,
            "status": "ok",
            "new_items": None,
            "error": None,
        }
    ]


def test_inoreader_get_articles_page_reuses_cache_and_continuation(monkeypatch):
    provider = InoreaderProvider(
        {
            "providers": {
                "inoreader": {
                    "app_id": "app",
                    "app_key": "key",
                    "token": "token",
                    "article_cache_ttl_seconds": 300,
                    "article_request_page_size": 2,
                }
            }
        }
    )

    monkeypatch.setattr("providers.inoreader.utils.get_chapters_batch", lambda ids: {})
    monkeypatch.setattr("providers.inoreader.utils.normalize_date", lambda raw, title, content, url: "2024-01-01T00:00:00Z")

    calls = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.headers = {}
            self.ok = True

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    payloads = [
        {
            "items": [
                {
                    "id": "a1",
                    "title": "A1",
                    "published": 1,
                    "alternate": [{"href": "https://example.com/a1"}],
                    "categories": [],
                },
                {
                    "id": "a2",
                    "title": "A2",
                    "published": 2,
                    "alternate": [{"href": "https://example.com/a2"}],
                    "categories": [],
                },
            ],
            "continuation": "c1",
        },
        {
            "items": [
                {
                    "id": "a3",
                    "title": "A3",
                    "published": 3,
                    "alternate": [{"href": "https://example.com/a3"}],
                    "categories": [],
                },
                {
                    "id": "a4",
                    "title": "A4",
                    "published": 4,
                    "alternate": [{"href": "https://example.com/a4"}],
                    "categories": [],
                },
            ],
        },
    ]

    def _fake_request(method, url, *, params=None, data=None, **kwargs):
        calls.append({"method": method, "url": url, "params": dict(params or {})})
        idx = len(calls) - 1
        return _Resp(payloads[idx])

    monkeypatch.setattr(provider, "_request", _fake_request)

    page1, total1 = provider.get_articles_page("all", offset=0, limit=2)
    assert [a.id for a in page1] == ["a1", "a2"]
    assert total1 is None
    assert len(calls) == 1
    assert calls[0]["params"].get("n") >= 2
    assert "c" not in calls[0]["params"]

    # Repeat the same page; should be served from cache with no new API call.
    page1_repeat, total1_repeat = provider.get_articles_page("all", offset=0, limit=2)
    assert [a.id for a in page1_repeat] == ["a1", "a2"]
    assert total1_repeat is None
    assert len(calls) == 1

    # Next page should fetch exactly one more API page using the saved continuation token.
    page2, total2 = provider.get_articles_page("all", offset=2, limit=2)
    assert [a.id for a in page2] == ["a3", "a4"]
    assert total2 == 4
    assert len(calls) == 2
    assert calls[1]["params"].get("c") == "c1"
