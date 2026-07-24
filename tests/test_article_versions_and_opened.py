# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Change-history versions + opened/viewed activity tracking (DB layer)."""
import pytest

from core import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    c = db.get_connection()
    try:
        c.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            ("feed-1", "https://example.com/feed.xml", "Feed", "Uncategorized"),
        )
        c.execute(
            "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            ("art-1", "feed-1", "Title", "https://example.com/1", "Body v1", "2026-06-24 12:00:00", "Auth"),
        )
        c.commit()
    finally:
        c.close()
    yield


# --- opened/viewed ---------------------------------------------------------

def test_mark_article_opened_sets_timestamp(conn):
    assert db.mark_article_opened("art-1", opened_at=1000.0) is True
    c = db.get_connection()
    try:
        row = c.execute("SELECT opened_at FROM articles WHERE id=?", ("art-1",)).fetchone()
    finally:
        c.close()
    assert row[0] == 1000.0


def test_mark_article_opened_updates_to_latest(conn):
    db.mark_article_opened("art-1", opened_at=1000.0)
    db.mark_article_opened("art-1", opened_at=2000.0)
    c = db.get_connection()
    try:
        row = c.execute("SELECT opened_at FROM articles WHERE id=?", ("art-1",)).fetchone()
    finally:
        c.close()
    assert row[0] == 2000.0


def test_mark_article_opened_unknown_id_is_noop(conn):
    # No matching row -> harmless no-op (returns True, nothing updated).
    assert db.mark_article_opened("nope") is True


def test_mark_article_opened_with_feed_id_does_not_touch_wrong_feed(conn):
    assert db.mark_article_opened("art-1", opened_at=1000.0, feed_id="other-feed") is True
    c = db.get_connection()
    try:
        row = c.execute("SELECT opened_at FROM articles WHERE id=?", ("art-1",)).fetchone()
    finally:
        c.close()
    assert row[0] is None


# --- change history --------------------------------------------------------

def test_record_version_dedups_identical_content(conn):
    assert db.record_article_version("art-1", "Title", "Body v1", captured_at=1.0) is True
    # Same (title, content) again -> no new version.
    assert db.record_article_version("art-1", "Title", "Body v1", captured_at=2.0) is False
    assert db.count_article_versions("art-1") == 1


def test_record_version_appends_on_change(conn):
    db.record_article_version("art-1", "Title", "Body v1", captured_at=1.0)
    assert db.record_article_version("art-1", "Title", "Body v2 changed", captured_at=2.0) is True
    assert db.record_article_version("art-1", "Title changed", "Body v2 changed", captured_at=3.0) is True
    assert db.count_article_versions("art-1") == 3


def test_get_versions_newest_first(conn):
    db.record_article_version("art-1", "T", "one", captured_at=1.0)
    db.record_article_version("art-1", "T", "two", captured_at=2.0)
    versions = db.get_article_versions("art-1")
    assert [v["content"] for v in versions] == ["two", "one"]
    assert versions[0]["captured_at"] == 2.0


def test_updated_detection_by_version_count(conn):
    # An article is "updated" when it has more than one distinct version.
    db.record_article_version("art-1", "T", "orig", captured_at=1.0)
    assert db.count_article_versions("art-1") == 1  # not updated yet
    db.record_article_version("art-1", "T", "edited", captured_at=2.0)
    assert db.count_article_versions("art-1") > 1  # now updated
