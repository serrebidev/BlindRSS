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

APKMIRROR_WORDPRESS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Download Android Accessibility Suite APKs for Android - APKMirror</title>
    <link>https://www.apkmirror.com/apk/google-inc/android-accessibility-suite/</link>
    <description>APKMirror feed</description>
    <item>
      <title>Android Accessibility Suite 17.0.1.926549743 by Google LLC</title>
      <link>https://www.apkmirror.com/apk/google-inc/android-accessibility-suite/android-accessibility-suite-17-0-1-926549743-release/</link>
      <guid isPermaLink="false">http://www.apkmirror.com/?p=14231923</guid>
      <dc:creator><![CDATA[APKMirror]]></dc:creator>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
      <description><![CDATA[The Android Accessibility Suite APK appeared first on APKMirror.]]></description>
      <content:encoded><![CDATA[The Android Accessibility Suite 17.0.1.926549743 by Google LLC APK appeared first on APKMirror. Introducing APKMirror PREMIUM.]]></content:encoded>
    </item>
  </channel>
</rss>
"""

GRAV_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
  <channel>
    <title>My Feed Title</title>
    <link>https://getgrav.org/blog</link>
    <atom:link href="https://getgrav.org/blog.rss" rel="self" type="application/rss+xml" />
    <description>Grav Blog</description>
    <item>
      <title>Grav 2.0 Released!</title>
      <link>https://getgrav.org/blog/grav-2-stable-released</link>
      <guid isPermaLink="true">https://getgrav.org/blog/grav-2-stable-released</guid>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
      <description><![CDATA[Today, Grav 2.0 is stable. This is the biggest release in the project's history.]]></description>
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

JSON_FEED_11 = """{
  "version": "https://jsonfeed.org/version/1.1",
  "title": "JSON Feed",
  "home_page_url": "https://example.com/",
  "feed_url": "https://example.com/feed.json",
  "authors": [
    {"name": "Feed Author"}
  ],
  "items": [
    {
      "id": "json-entry-1",
      "url": "https://example.com/json-entry-1",
      "title": "JSON Feed Item",
      "content_html": "<p>JSON feed body</p>",
      "summary": "JSON summary",
      "date_published": "2026-01-02T03:04:05Z",
      "authors": [
        {"name": "Item Author"}
      ],
      "attachments": [
        {
          "url": "https://example.com/audio.mp3",
          "mime_type": "audio/mpeg",
          "title": "Episode audio"
        }
      ]
    }
  ]
}
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


def test_local_provider_extracts_articles_from_json_feed(provider, monkeypatch):
    feed_id = _insert_feed("https://example.com/feed.json")
    monkeypatch.setattr(
        local_mod.utils,
        "safe_requests_get",
        lambda *args, **kwargs: _DummyResp(JSON_FEED_11, content_type="application/feed+json"),
    )

    assert provider.refresh_feed(feed_id) is True

    articles = provider.get_articles(feed_id=feed_id)
    assert len(articles) == 1
    article = articles[0]
    assert article.id == "json-entry-1"
    assert article.title == "JSON Feed Item"
    assert article.url == "https://example.com/json-entry-1"
    assert "JSON feed body" in article.content
    assert article.author == "Item Author"
    assert article.media_url == "https://example.com/audio.mp3"
    assert article.media_type == "audio/mpeg"


def test_local_provider_extracts_apkmirror_wordpress_rss_shape(provider, monkeypatch):
    feed_id = _insert_feed("https://www.apkmirror.com/apk/google-inc/android-accessibility-suite/feed/")
    monkeypatch.setattr(
        local_mod.utils,
        "safe_requests_get",
        lambda *args, **kwargs: _DummyResp(
            APKMIRROR_WORDPRESS_RSS,
            content_type="text/xml; charset=UTF-8",
        ),
    )

    assert provider.refresh_feed(feed_id) is True

    rows = _article_rows(feed_id)
    assert len(rows) == 1
    article_id, title, url, content = rows[0]
    assert article_id == "http://www.apkmirror.com/?p=14231923"
    assert title == "Android Accessibility Suite 17.0.1.926549743 by Google LLC"
    assert url.endswith("/android-accessibility-suite-17-0-1-926549743-release/")
    assert "Introducing APKMirror PREMIUM" in content


def test_local_provider_extracts_grav_rss_shape(provider, monkeypatch):
    feed_id = _insert_feed("https://getgrav.org/blog.rss")
    monkeypatch.setattr(
        local_mod.utils,
        "safe_requests_get",
        lambda *args, **kwargs: _DummyResp(
            GRAV_RSS,
            content_type="application/rss+xml; charset=utf-8",
        ),
    )

    assert provider.refresh_feed(feed_id) is True

    rows = _article_rows(feed_id)
    assert len(rows) == 1
    article_id, title, url, content = rows[0]
    assert article_id == "https://getgrav.org/blog/grav-2-stable-released"
    assert title == "Grav 2.0 Released!"
    assert url == "https://getgrav.org/blog/grav-2-stable-released"
    assert "Today, Grav 2.0 is stable" in content


def test_add_feed_uses_json_feed_title(provider, monkeypatch):
    monkeypatch.setattr(provider, "_resolve_feed_url", lambda url: url)
    monkeypatch.setattr(
        local_mod.utils,
        "safe_requests_get",
        lambda *args, **kwargs: _DummyResp(JSON_FEED_11, content_type="application/feed+json"),
    )

    assert provider.add_feed("https://example.com/feed.json", "Tests") is True

    feeds = provider.get_feeds()
    assert len(feeds) == 1
    assert feeds[0].url == "https://example.com/feed.json"
    assert feeds[0].title == "JSON Feed"
