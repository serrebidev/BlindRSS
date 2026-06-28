import os
import sys
import uuid

import pytest
import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db as db
import providers.local as local_mod
from providers.local import LocalProvider


class _DummyResp:
    def __init__(self, text: str, *, status_code: int = 200, content_type: str = "application/rss+xml") -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.url = "https://example.com/feed.xml"
        self.response = self

    def raise_for_status(self) -> None:
        if int(self.status_code or 0) >= 400:
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    return LocalProvider(
        {
            "providers": {"local": {}},
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
            "max_concurrent_refreshes": 1,
            "per_host_max_connections": 1,
        }
    )


def _insert_feed(feed_url: str = "https://example.com/feed.xml") -> str:
    feed_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, feed_url, "Compatibility Feed", "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _article_rows(feed_id: str):
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT id, title, url, content FROM articles WHERE feed_id = ? ORDER BY title",
            (feed_id,),
        ).fetchall()
    finally:
        conn.close()


RSS_090 = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://my.netscape.com/rdf/simple/0.9/">
  <channel>
    <title>RSS 0.90 Feed</title>
    <link>https://example.com/</link>
    <description>Legacy RDF feed</description>
  </channel>
  <item>
    <title>RSS 0.90 Item</title>
    <link>https://example.com/rss090</link>
  </item>
</rdf:RDF>
"""

RSS_091_NO_ID_OR_LINK = """<?xml version="1.0"?>
<rss version="0.91">
  <channel>
    <title>RSS 0.91 Feed</title>
    <link>https://example.com/</link>
    <description>Old RSS feed</description>
    <item>
      <title>RSS 0.91 Item Without Link</title>
      <description>Body from an item that has neither guid nor link.</description>
    </item>
  </channel>
</rss>
"""

RSS_092 = """<?xml version="1.0"?>
<rss version="0.92">
  <channel>
    <title>RSS 0.92 Feed</title>
    <link>https://example.com/</link>
    <description>Old RSS feed</description>
    <item>
      <title>RSS 0.92 Item</title>
      <link>https://example.com/rss092</link>
      <description>RSS 0.92 body</description>
    </item>
  </channel>
</rss>
"""

RSS_093 = """<?xml version="1.0"?>
<rss version="0.93">
  <channel>
    <title>RSS 0.93 Feed</title>
    <link>https://example.com/</link>
    <description>Old RSS feed</description>
    <item>
      <title>RSS 0.93 Item</title>
      <link>https://example.com/rss093</link>
      <description>RSS 0.93 body</description>
    </item>
  </channel>
</rss>
"""

RSS_094 = """<?xml version="1.0"?>
<rss version="0.94">
  <channel>
    <title>RSS 0.94 Feed</title>
    <link>https://example.com/</link>
    <description>Old RSS feed</description>
    <item>
      <title>RSS 0.94 Item</title>
      <link>https://example.com/rss094</link>
      <description>RSS 0.94 body</description>
    </item>
  </channel>
</rss>
"""

RSS_10 = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
  <channel rdf:about="https://example.com/">
    <title>RSS 1.0 Feed</title>
    <link>https://example.com/</link>
    <description>RDF feed</description>
    <items>
      <rdf:Seq>
        <rdf:li rdf:resource="https://example.com/rss10" />
      </rdf:Seq>
    </items>
  </channel>
  <item rdf:about="https://example.com/rss10">
    <title>RSS 1.0 Item</title>
    <link>https://example.com/rss10</link>
    <description>RSS 1.0 body</description>
  </item>
</rdf:RDF>
"""

RSS_20 = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>RSS 2.0 Feed</title>
    <link>https://example.com/</link>
    <description>Modern RSS feed</description>
    <item>
      <guid isPermaLink="false">rss20-guid</guid>
      <title>RSS 2.0 Item</title>
      <link>https://example.com/rss20</link>
      <description>RSS 2.0 body</description>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_10 = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <id>https://example.com/atom</id>
  <updated>2026-01-01T00:00:00Z</updated>
  <entry>
    <id>https://example.com/atom-entry</id>
    <title>Atom 1.0 Item</title>
    <link href="https://example.com/atom-entry" rel="alternate" />
    <updated>2026-01-01T00:00:00Z</updated>
    <summary>Atom body</summary>
  </entry>
</feed>
"""


@pytest.mark.parametrize(
    ("xml", "expected_title", "expected_url"),
    [
        (RSS_090, "RSS 0.90 Item", "https://example.com/rss090"),
        (RSS_091_NO_ID_OR_LINK, "RSS 0.91 Item Without Link", ""),
        (RSS_092, "RSS 0.92 Item", "https://example.com/rss092"),
        (RSS_093, "RSS 0.93 Item", "https://example.com/rss093"),
        (RSS_094, "RSS 0.94 Item", "https://example.com/rss094"),
        (RSS_10, "RSS 1.0 Item", "https://example.com/rss10"),
        (RSS_20, "RSS 2.0 Item", "https://example.com/rss20"),
        (ATOM_10, "Atom 1.0 Item", "https://example.com/atom-entry"),
    ],
)
def test_local_provider_extracts_articles_from_common_rss_and_atom_formats(
    provider,
    monkeypatch,
    xml,
    expected_title,
    expected_url,
):
    feed_id = _insert_feed()
    monkeypatch.setattr(local_mod.utils, "safe_requests_get", lambda *args, **kwargs: _DummyResp(xml))

    assert provider.refresh_feed(feed_id) is True

    rows = _article_rows(feed_id)
    assert len(rows) == 1
    article_id, title, url, content = rows[0]
    assert article_id
    assert title == expected_title
    assert url == expected_url
    if "Without Link" in expected_title:
        assert article_id.startswith("blindrss:entry:")
        assert "neither guid nor link" in content


def test_local_provider_retries_http_406_with_generic_accept_header(provider, monkeypatch):
    feed_id = _insert_feed("https://gitlab.example.test/GNOME/orca/-/tags?format=atom")
    calls = []

    def _fake_get(url, **kwargs):
        calls.append((url, dict(kwargs or {})))
        headers = kwargs.get("headers") or {}
        if headers.get("Accept") == "*/*":
            return _DummyResp(ATOM_10, content_type="application/atom+xml")
        return _DummyResp("", status_code=406, content_type="text/plain")

    monkeypatch.setattr(local_mod.utils, "safe_requests_get", _fake_get)

    states = []
    assert provider.refresh_feed(feed_id, progress_cb=states.append) is True

    rows = _article_rows(feed_id)
    assert len(rows) == 1
    assert rows[0][1] == "Atom 1.0 Item"
    assert states[-1]["status"] == "ok"
    assert len(calls) == 2
    assert calls[0][1]["headers"].get("Accept") is None
    assert calls[1][1]["headers"]["Accept"] == "*/*"
    assert calls[1][1]["headers"]["User-Agent"] == "BlindRSS/1.0"
    assert "no-cache" in calls[1][1]["headers"]["Cache-Control"].lower()
