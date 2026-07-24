# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Retention sweep (cleanup_old_articles): old articles are removed, but
articles whose date could not be parsed (sentinel/empty date) must never be
deleted — their real age is unknown and they may have arrived seconds ago."""
import pytest

from core import db
from core.utils import normalize_date


FEED_ID = "feed-retention"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (FEED_ID, "https://example.com/feed.xml", "Retention Feed", "Uncategorized"),
        )
        conn.commit()
    finally:
        conn.close()


def _insert(article_id, date, is_favorite=0):
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (article_id, FEED_ID, f"Title {article_id}", f"https://x/{article_id}", "body", date, "", 0, is_favorite),
        )
        conn.commit()
    finally:
        conn.close()


def _remaining_ids():
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT id FROM articles ORDER BY id").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def test_cleanup_removes_old_keeps_recent(fresh_db):
    _insert("old", "2020-01-01 00:00:00")
    _insert("recent", "2999-01-01 00:00:00")
    db.cleanup_old_articles(days=30)
    assert _remaining_ids() == ["recent"]


def test_cleanup_keeps_undated_sentinel_articles(fresh_db):
    # normalize_date falls back to this sentinel when no date is parseable.
    sentinel = normalize_date("", "no date anywhere", "", "https://x/undated")
    assert sentinel == "0001-01-01 00:00:00"
    _insert("undated", sentinel)
    _insert("empty-date", "")
    _insert("old", "2020-01-01 00:00:00")
    db.cleanup_old_articles(days=30)
    # Only the genuinely old article is swept; undated ones are kept.
    assert _remaining_ids() == ["empty-date", "undated"]


def test_cleanup_keeps_old_favorites(fresh_db):
    _insert("old-fav", "2020-01-01 00:00:00", is_favorite=1)
    _insert("old", "2020-01-01 00:00:00")
    db.cleanup_old_articles(days=30, keep_favorites=True)
    assert _remaining_ids() == ["old-fav"]
