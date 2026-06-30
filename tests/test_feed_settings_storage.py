"""Tests for per-feed HTTP override storage (issue #29)."""

import os
import sys
import tempfile
import uuid

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db as db


def _with_temp_db(fn):
    with tempfile.TemporaryDirectory() as tmp:
        orig = db.DB_FILE
        db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            db.init_db()
            fn()
        finally:
            db.DB_FILE = orig


def _insert_feed():
    feed_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (feed_id, "https://example.com/feed", "T", "C"),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def test_migration_adds_feed_settings_column():
    def _check():
        conn = db.get_connection()
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(feeds)").fetchall()]
        finally:
            conn.close()
        assert "feed_settings" in cols

    _with_temp_db(_check)


def test_roundtrip_empty_partial_and_full():
    def _check():
        feed_id = _insert_feed()
        # Unset -> {}
        assert db.get_feed_settings(feed_id) == {}

        # Empty dict roundtrips.
        assert db.set_feed_settings(feed_id, {}) is True
        assert db.get_feed_settings(feed_id) == {}

        # Partial.
        db.set_feed_settings(feed_id, {"timeout_seconds": 30})
        assert db.get_feed_settings(feed_id) == {"timeout_seconds": 30}

        # Full.
        full = {
            "custom_headers": {"X-Token": "abc", "Referer": "https://x/"},
            "timeout_seconds": 45,
            "impersonate": "always",
        }
        db.set_feed_settings(feed_id, full)
        assert db.get_feed_settings(feed_id) == full

    _with_temp_db(_check)


def test_unknown_feed_returns_empty_dict():
    def _check():
        assert db.get_feed_settings("does-not-exist") == {}
        assert db.get_feed_settings("") == {}
        assert db.get_feed_settings(None) == {}

    _with_temp_db(_check)


def test_null_and_malformed_json_tolerated():
    def _check():
        feed_id = _insert_feed()
        # NULL value.
        assert db.get_feed_settings(feed_id) == {}
        # Malformed JSON stored directly.
        conn = db.get_connection()
        try:
            conn.execute("UPDATE feeds SET feed_settings = ? WHERE id = ?", ("{not json", feed_id))
            conn.commit()
        finally:
            conn.close()
        assert db.get_feed_settings(feed_id) == {}
        # A JSON value that isn't an object also degrades to {}.
        conn = db.get_connection()
        try:
            conn.execute("UPDATE feeds SET feed_settings = ? WHERE id = ?", ("[1,2,3]", feed_id))
            conn.commit()
        finally:
            conn.close()
        assert db.get_feed_settings(feed_id) == {}

    _with_temp_db(_check)
