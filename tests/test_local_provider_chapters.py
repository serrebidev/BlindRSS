from unittest.mock import MagicMock

import pytest

from core import db, npr as npr_mod, utils
from providers.local import LocalProvider


FEED_ID = "feed-chapters"
FEED_URL = "https://example.com/feed.xml"
ITEM_ID = "episode-1"
ITEM_URL = "https://example.com/episodes/1"


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    local = LocalProvider({"feed_timeout_seconds": 1, "feed_retry_attempts": 0})

    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (FEED_ID, FEED_URL, "Chapter Feed", "Uncategorized"),
        )
        conn.commit()
    finally:
        conn.close()
    return local


def _feed_xml(
    chapter_markup="",
    enclosure_url="https://cdn.example.com/episode.mp3",
    enclosure_type="audio/mpeg",
    item_url=ITEM_URL,
):
    enclosure = ""
    if enclosure_url:
        enclosure = f'<enclosure url="{enclosure_url}" type="{enclosure_type}" />'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Chapter Feed</title>
    <link>https://example.com/</link>
    <description>Tests</description>
    <item>
      <guid isPermaLink="false">{ITEM_ID}</guid>
      <title>Episode One</title>
      <link>{item_url}</link>
      <pubDate>Wed, 24 Jun 2026 12:00:00 GMT</pubDate>
      <description>Episode description</description>
      {enclosure}
      {chapter_markup}
    </item>
  </channel>
</rss>"""


def _refresh(provider, monkeypatch, xml):
    response = MagicMock()
    response.status_code = 200
    response.content = xml.encode("utf-8")
    response.text = xml
    response.headers = {}
    response.url = FEED_URL
    response.raise_for_status.return_value = None
    monkeypatch.setattr(utils, "safe_requests_get", lambda *args, **kwargs: response)
    assert provider.refresh_feed(FEED_ID) is True


@pytest.mark.parametrize(
    "chapter_markup",
    [
        '<vendor:chapters xmlns:vendor="urn:vendor-specific" url="https://cdn.example.com/chapters.json" />',
        '<chapters xmlns="urn:another-vendor" url="https://cdn.example.com/chapters.json" />',
        '<undeclared:chapters url="https://cdn.example.com/chapters.json" />',
    ],
)
def test_external_chapters_detection_ignores_prefix_and_namespace_uri(
    provider,
    monkeypatch,
    chapter_markup,
):
    _refresh(provider, monkeypatch, _feed_xml(chapter_markup))

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT chapter_url FROM articles WHERE id = ?",
            (ITEM_ID,),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("https://cdn.example.com/chapters.json",)


def test_inline_podlove_chapters_are_normalized_and_stored(provider, monkeypatch):
    chapter_markup = """
      <psc:chapters xmlns:psc="http://podlove.org/simple-chapters" version="1.2">
        <psc:chapter start="01:05.500" title="Discussion" href="https://example.com/discussion" />
        <psc:chapter start="00:00:00.000" title="Introduction" />
        <psc:chapter start="00:01:05.500" href="https://example.com/duplicate" />
        <psc:chapter start="00:99:00" title="Invalid" />
      </psc:chapters>
    """
    _refresh(provider, monkeypatch, _feed_xml(chapter_markup))

    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT start, title, href FROM chapters WHERE article_id = ? ORDER BY start",
            (ITEM_ID,),
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        (0.0, "Introduction", None),
        (65.5, "Discussion", "https://example.com/discussion"),
    ]


def test_refresh_updates_enclosure_and_chapter_url_without_losing_state_or_cached_chapters(
    provider,
    monkeypatch,
):
    old_chapters = (
        '<podcast:chapters xmlns:podcast="https://podcastindex.org/namespace/1.0" '
        'url="https://cdn.example.com/old-chapters.json" />'
    )
    _refresh(
        provider,
        monkeypatch,
        _feed_xml(old_chapters, "https://cdn.example.com/old.mp3", "audio/mpeg"),
    )

    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE articles SET is_read = 1, is_favorite = 1 WHERE id = ?",
            (ITEM_ID,),
        )
        conn.execute(
            "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
            ("old-chapter", ITEM_ID, 0.0, "Cached old chapter", None),
        )
        conn.commit()
    finally:
        conn.close()

    new_chapters = (
        '<unrelated:chapters xmlns:unrelated="urn:new-chapter-schema" '
        'url="https://cdn.example.com/new-chapters.json" />'
    )
    _refresh(
        provider,
        monkeypatch,
        _feed_xml(new_chapters, "https://cdn.example.com/new.m4a", "audio/mp4"),
    )

    conn = db.get_connection()
    try:
        article = conn.execute(
            "SELECT media_url, media_type, chapter_url, is_read, is_favorite "
            "FROM articles WHERE id = ?",
            (ITEM_ID,),
        ).fetchone()
        article_count = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE feed_id = ?",
            (FEED_ID,),
        ).fetchone()[0]
        chapter_count = conn.execute(
            "SELECT COUNT(*) FROM chapters WHERE article_id = ?",
            (ITEM_ID,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert article == (
        "https://cdn.example.com/new.m4a",
        "audio/mp4",
        "https://cdn.example.com/new-chapters.json",
        1,
        1,
    )
    assert article_count == 1
    assert chapter_count == 1


def test_changed_chapter_url_keeps_working_chapters_when_replacement_fetch_fails(
    provider,
    monkeypatch,
):
    old_url = "https://cdn.example.com/old-chapters.json"
    new_url = "https://cdn.example.com/new-chapters.json"
    old_markup = (
        '<podcast:chapters xmlns:podcast="https://podcastindex.org/namespace/1.0" '
        f'url="{old_url}" />'
    )
    _refresh(provider, monkeypatch, _feed_xml(old_markup))

    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
            ("cached-old", ITEM_ID, 0.0, "Working cached chapter", None),
        )
        utils._save_chapter_source(
            ITEM_ID,
            old_url,
            etag='"old-etag"',
            checked_at=1,
            fetched_at=1,
            cursor=conn.cursor(),
        )
        conn.commit()
    finally:
        conn.close()

    new_markup = (
        '<podcast:chapters xmlns:podcast="https://podcastindex.org/namespace/1.0" '
        f'url="{new_url}" />'
    )
    _refresh(provider, monkeypatch, _feed_xml(new_markup))
    monkeypatch.setattr(
        utils,
        "_fetch_chapter_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("replacement unavailable")),
    )

    assert provider.get_article_chapters(ITEM_ID) == [
        {"start": 0.0, "title": "Working cached chapter", "href": None}
    ]

    conn = db.get_connection()
    try:
        article_url = conn.execute(
            "SELECT chapter_url FROM articles WHERE id = ?",
            (ITEM_ID,),
        ).fetchone()[0]
        chapter_rows = conn.execute(
            "SELECT start, title, href FROM chapters WHERE article_id = ?",
            (ITEM_ID,),
        ).fetchall()
    finally:
        conn.close()

    assert article_url == new_url
    assert chapter_rows == [(0.0, "Working cached chapter", None)]
    assert utils.get_chapter_source_url(ITEM_ID) == old_url


def test_removed_enclosure_clears_stale_media(provider, monkeypatch):
    _refresh(
        provider,
        monkeypatch,
        _feed_xml(enclosure_url="https://cdn.example.com/removed.mp3"),
    )
    _refresh(provider, monkeypatch, _feed_xml(enclosure_url=None))

    conn = db.get_connection()
    try:
        media = conn.execute(
            "SELECT media_url, media_type FROM articles WHERE id = ?",
            (ITEM_ID,),
        ).fetchone()
    finally:
        conn.close()

    assert media == (None, None)


def test_removed_enclosure_is_not_retained_for_npr_without_confirmed_extraction(
    provider,
    monkeypatch,
):
    npr_url = "https://www.npr.org/2026/06/24/example-story"
    _refresh(
        provider,
        monkeypatch,
        _feed_xml(
            enclosure_url="https://cdn.example.com/removed-npr.mp3",
            item_url=npr_url,
        ),
    )
    monkeypatch.setattr(npr_mod, "extract_npr_audio", lambda *args, **kwargs: (None, None))
    _refresh(
        provider,
        monkeypatch,
        _feed_xml(enclosure_url=None, item_url=npr_url),
    )

    conn = db.get_connection()
    try:
        media = conn.execute(
            "SELECT media_url, media_type FROM articles WHERE id = ?",
            (ITEM_ID,),
        ).fetchone()
    finally:
        conn.close()

    assert media == (None, None)


def test_delete_and_recreate_article_clears_local_chapter_cache_metadata(
    provider,
    monkeypatch,
):
    chapter_url = "https://cdn.example.com/chapters.json"
    markup = (
        '<podcast:chapters xmlns:podcast="https://podcastindex.org/namespace/1.0" '
        f'url="{chapter_url}" />'
    )
    _refresh(provider, monkeypatch, _feed_xml(markup))

    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
            ("cached", ITEM_ID, 0.0, "Cached chapter", None),
        )
        utils._save_chapter_source(
            ITEM_ID,
            chapter_url,
            etag='"stale-etag"',
            checked_at=1,
            fetched_at=1,
            cursor=conn.cursor(),
        )
        conn.commit()
    finally:
        conn.close()

    assert provider.delete_article(ITEM_ID) is True
    assert utils.get_chapters_from_db(ITEM_ID) == []
    assert utils.get_chapter_source_url(ITEM_ID) is None

    _refresh(provider, monkeypatch, _feed_xml(markup))

    conn = db.get_connection()
    try:
        recreated = conn.execute(
            "SELECT chapter_url FROM articles WHERE id = ?",
            (ITEM_ID,),
        ).fetchone()
        chapter_count = conn.execute(
            "SELECT COUNT(*) FROM chapters WHERE article_id = ?",
            (ITEM_ID,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert recreated == (chapter_url,)
    assert chapter_count == 0
    assert utils.get_chapter_source_url(ITEM_ID) is None


def test_refresh_replaces_inline_chapters_for_existing_article(provider, monkeypatch):
    first_markup = """
      <psc:chapters xmlns:psc="http://podlove.org/simple-chapters">
        <psc:chapter start="00:00" title="Old intro" />
        <psc:chapter start="10:00" title="Old ending" />
      </psc:chapters>
    """
    _refresh(provider, monkeypatch, _feed_xml(first_markup))

    second_markup = """
      <custom:chapters xmlns:custom="urn:inline-chapters">
        <custom:chapter start="00:30" title="New intro" href="https://example.com/new-intro" />
      </custom:chapters>
    """
    _refresh(provider, monkeypatch, _feed_xml(second_markup))

    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT start, title, href FROM chapters WHERE article_id = ? ORDER BY start",
            (ITEM_ID,),
        ).fetchall()
    finally:
        conn.close()

    assert rows == [(30.0, "New intro", "https://example.com/new-intro")]
