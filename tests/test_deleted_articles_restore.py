# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Deleted Articles view + restore (local provider).

Covers the snapshot-on-delete tombstone, the 'deleted:all' virtual view, and the
restore round-trip that moves an article back into the live table.
"""
import pytest

from core import db
from providers.local import LocalProvider


FEED_ID = "feed-del"
ART_ID = "article-del-1"
ART_URL = "https://example.com/posts/1"


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    local = LocalProvider({"feed_timeout_seconds": 1, "feed_retry_attempts": 0})

    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (FEED_ID, "https://example.com/feed.xml", "Del Feed", "Uncategorized"),
        )
        conn.execute(
            "INSERT INTO articles (id, feed_id, title, url, content, description, date, author, is_read, is_favorite) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ART_ID,
                FEED_ID,
                "Original Title",
                ART_URL,
                "Full body content about pumpkins.",
                "Short summary.",
                "2026-06-24 12:00:00",
                "Jane Author",
                0,
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return local


def test_supports_restore_deleted(provider):
    assert provider.supports_restore_deleted() is True


def test_delete_snapshots_article_and_removes_row(provider):
    assert provider.delete_article(ART_ID) is True

    # Row is gone from the live table...
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM articles WHERE id=?", (ART_ID,)).fetchone()[0] == 0
    finally:
        conn.close()

    # ...but the tombstone still suppresses re-creation on refresh.
    ids, urls = db.deleted_article_tombstones_for_feed(FEED_ID)
    assert ART_ID in ids
    assert ART_URL in urls


def test_deleted_view_lists_snapshot(provider):
    provider.delete_article(ART_ID)

    page, total = provider.get_articles_page("deleted:all", offset=0, limit=50)
    assert total == 1
    assert len(page) == 1
    a = page[0]
    assert a.id == ART_ID
    assert a.title == "Original Title"
    assert a.content == "Full body content about pumpkins."
    assert a.author == "Jane Author"
    assert a.url == ART_URL

    # get_articles() (unpaged) mirrors the page contents.
    assert [x.id for x in provider.get_articles("deleted:all")] == [ART_ID]


def test_restore_puts_article_back_and_clears_tombstone(provider):
    provider.delete_article(ART_ID)
    assert provider.restore_article(ART_ID) is True

    # Article is back in the live table with its content intact.
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT title, content, author FROM articles WHERE id=?", (ART_ID,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "Original Title"
    assert row[1] == "Full body content about pumpkins."
    assert row[2] == "Jane Author"

    # Tombstone cleared: no longer suppressed, no longer in the deleted view.
    ids, _urls = db.deleted_article_tombstones_for_feed(FEED_ID)
    assert ART_ID not in ids
    _page, total = provider.get_articles_page("deleted:all", offset=0, limit=50)
    assert total == 0


def test_restore_uses_feed_id_when_deleted_ids_collide(provider):
    other_feed = "feed-other"
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (other_feed, "https://example.com/other.xml", "Other", "Uncategorized"),
        )
        conn.commit()
    finally:
        conn.close()

    provider.delete_article(ART_ID)
    db.remember_deleted_article(
        other_feed,
        ART_ID,
        "https://example.com/other-post",
        deleted_at=999.0,
        snapshot={"title": "Other deleted article", "content": "Other body"},
    )

    assert provider.restore_article(ART_ID, feed_id=FEED_ID) is True

    rows, total = db.list_deleted_articles()
    assert total == 1
    assert rows[0]["feed_id"] == other_feed
    assert rows[0]["article_id"] == ART_ID


def test_restore_without_feed_id_refuses_ambiguous_tombstone(provider):
    other_feed = "feed-other"
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (other_feed, "https://example.com/other.xml", "Other", "Uncategorized"),
        )
        conn.commit()
    finally:
        conn.close()

    provider.delete_article(ART_ID)
    db.remember_deleted_article(other_feed, ART_ID, "https://example.com/other-post")

    assert provider.restore_article(ART_ID) is False
    _rows, total = db.list_deleted_articles()
    assert total == 2


def test_restore_missing_returns_false(provider):
    assert provider.restore_article("no-such-article") is False


def test_supports_purge_deleted(provider):
    assert provider.supports_purge_deleted() is True


def test_purge_removes_from_deleted_view_but_keeps_tombstone(provider):
    provider.delete_article(ART_ID)
    assert provider.purge_deleted_article(ART_ID, FEED_ID) is True

    # Gone from the Deleted Articles view...
    _page, total = provider.get_articles_page("deleted:all", offset=0, limit=50)
    assert total == 0
    rows, total = db.list_deleted_articles()
    assert total == 0
    assert rows == []

    # ...but the tombstone identity still suppresses re-creation on refresh.
    ids, urls = db.deleted_article_tombstones_for_feed(FEED_ID)
    assert ART_ID in ids
    assert ART_URL in urls

    # The snapshot content is actually dropped from the row.
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT title, content, purged FROM deleted_articles WHERE feed_id=? AND article_id=?",
            (FEED_ID, ART_ID),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] is None
    assert row[1] is None
    assert row[2] == 1


def test_purged_article_cannot_be_restored(provider):
    provider.delete_article(ART_ID)
    assert provider.purge_deleted_article(ART_ID, FEED_ID) is True
    assert provider.restore_article(ART_ID, feed_id=FEED_ID) is False


def test_purge_twice_returns_false(provider):
    provider.delete_article(ART_ID)
    assert provider.purge_deleted_article(ART_ID, FEED_ID) is True
    assert provider.purge_deleted_article(ART_ID, FEED_ID) is False


def test_purge_missing_returns_false(provider):
    assert provider.purge_deleted_article("no-such-article", FEED_ID) is False


def test_purge_without_feed_id_refuses_ambiguous_tombstone(provider):
    other_feed = "feed-other"
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (other_feed, "https://example.com/other.xml", "Other", "Uncategorized"),
        )
        conn.commit()
    finally:
        conn.close()

    provider.delete_article(ART_ID)
    db.remember_deleted_article(other_feed, ART_ID, "https://example.com/other-post")

    assert provider.purge_deleted_article(ART_ID) is False
    _rows, total = db.list_deleted_articles()
    assert total == 2


def test_old_tombstone_without_snapshot_degrades_gracefully(provider, tmp_path):
    # A pre-migration tombstone (identity only, NULL snapshot) should still appear
    # in the deleted view with a placeholder/URL title and be restorable.
    db.remember_deleted_article(FEED_ID, "legacy-1", "https://example.com/legacy")

    page, total = provider.get_articles_page("deleted:all", offset=0, limit=50)
    ids = {a.id: a for a in page}
    assert "legacy-1" in ids
    # Falls back to the URL as the display title when no snapshot title exists.
    assert ids["legacy-1"].title == "https://example.com/legacy"
    assert total >= 1

    assert provider.restore_article("legacy-1") is True
