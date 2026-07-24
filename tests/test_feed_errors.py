# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Persistent per-feed update error tracking and the Feeds with Errors view (issue #32).

Feeds break over time (dead URLs, HTTP 404/500, timeouts, anti-bot blocks,
invalid feed formats). These tests cover the DB layer that records the outcome
of each update attempt so the "Feeds with Errors" view can show which feeds
failed, when, why, and how many times in a row.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import core.db as db  # noqa: E402
from providers.base import RSSProvider  # noqa: E402


def _fresh_db(tmp):
    db.DB_FILE = os.path.join(tmp, "rss.db")
    db.init_db()


def _insert_feed(feed_id, title="Feed", url="https://example.com/feed", category="News"):
    conn = db.get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, url, title, category, ""),
        )
        conn.commit()
    finally:
        conn.close()


def _feed_columns():
    conn = db.get_connection()
    try:
        c = conn.cursor()
        c.execute("PRAGMA table_info(feeds)")
        return {row[1] for row in c.fetchall()}
    finally:
        conn.close()


def test_migration_adds_error_columns():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _fresh_db(tmp)
            cols = _feed_columns()
            assert {"last_error", "last_error_at", "last_success_at", "consecutive_failures"} <= cols
        finally:
            db.DB_FILE = orig


def test_record_feed_error_populates_view():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _fresh_db(tmp)
            _insert_feed("f1", title="Broken Feed", url="https://x/feed", category="Tech")
            assert db.get_feed_errors() == []

            assert db.record_feed_error("f1", "HTTP 404: Not Found", when=1000.0) is True
            errors = db.get_feed_errors()
            assert len(errors) == 1
            e = errors[0]
            assert e["id"] == "f1"
            assert e["title"] == "Broken Feed"
            assert e["url"] == "https://x/feed"
            assert e["category"] == "Tech"
            assert e["last_error"] == "HTTP 404: Not Found"
            assert e["last_error_at"] == 1000.0
            assert e["consecutive_failures"] == 1
        finally:
            db.DB_FILE = orig


def test_consecutive_failures_increment():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _fresh_db(tmp)
            _insert_feed("f1")
            db.record_feed_error("f1", "timeout", when=1.0)
            db.record_feed_error("f1", "timeout again", when=2.0)
            db.record_feed_error("f1", "still down", when=3.0)
            e = db.get_feed_errors()[0]
            assert e["consecutive_failures"] == 3
            # The most recent message/time wins.
            assert e["last_error"] == "still down"
            assert e["last_error_at"] == 3.0
        finally:
            db.DB_FILE = orig


def test_clear_feed_error_removes_from_view():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _fresh_db(tmp)
            _insert_feed("f1")
            db.record_feed_error("f1", "boom", when=1.0)
            db.record_feed_error("f1", "boom", when=2.0)
            assert len(db.get_feed_errors()) == 1

            assert db.clear_feed_error("f1", when=50.0) is True
            assert db.get_feed_errors() == []

            # Success state is persisted: counter reset, last_success_at stamped.
            conn = db.get_connection()
            try:
                c = conn.cursor()
                c.execute(
                    "SELECT last_error, last_error_at, last_success_at, consecutive_failures FROM feeds WHERE id = ?",
                    ("f1",),
                )
                row = c.fetchone()
            finally:
                conn.close()
            assert row[0] is None
            assert row[1] is None
            assert row[2] == 50.0
            assert row[3] == 0
        finally:
            db.DB_FILE = orig


def test_get_feed_errors_ordered_most_recent_first():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _fresh_db(tmp)
            _insert_feed("old", title="Old")
            _insert_feed("new", title="New")
            _insert_feed("ok", title="Healthy")
            db.record_feed_error("old", "old error", when=100.0)
            db.record_feed_error("new", "new error", when=900.0)
            errors = db.get_feed_errors()
            assert [e["id"] for e in errors] == ["new", "old"]  # healthy feed excluded
        finally:
            db.DB_FILE = orig


def test_blank_error_message_falls_back_and_is_listed():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _fresh_db(tmp)
            _insert_feed("f1")
            db.record_feed_error("f1", "   ", when=1.0)
            errors = db.get_feed_errors()
            assert len(errors) == 1
            assert errors[0]["last_error"] == "Unknown error"
        finally:
            db.DB_FILE = orig


def test_record_unknown_feed_is_noop():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _fresh_db(tmp)
            # No such feed row; the UPDATE simply affects nothing.
            assert db.record_feed_error("does-not-exist", "boom", when=1.0) is True
            assert db.get_feed_errors() == []
        finally:
            db.DB_FILE = orig


def test_base_provider_returns_no_errors():
    """Providers without per-feed client-side tracking report an empty list."""

    class _StubProvider(RSSProvider):
        def get_name(self):
            return "stub"

        def refresh(self, progress_cb=None, force=False):
            return True

        def get_feeds(self):
            return []

        def get_articles(self, feed_id):
            return []

        def mark_read(self, article_id):
            return True

        def mark_unread(self, article_id):
            return True

        def add_feed(self, url, category=None):
            return True

        def remove_feed(self, feed_id):
            return True

        def get_categories(self):
            return []

        def add_category(self, title, parent_title=None):
            return True

        def rename_category(self, old_title, new_title):
            return True

        def delete_category(self, title):
            return True

    assert _StubProvider({}).get_feed_errors() == []


def test_local_provider_get_feed_errors_delegates_to_db():
    orig = db.DB_FILE
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_FILE = os.path.join(tmp, "rss.db")
            from providers.local import LocalProvider

            provider = LocalProvider({})  # init_db() runs against the temp DB
            _insert_feed("f1", title="Broken")
            db.record_feed_error("f1", "HTTP 500: Server Error", when=42.0)

            errors = provider.get_feed_errors()
            assert len(errors) == 1
            assert errors[0]["id"] == "f1"
            assert errors[0]["last_error"] == "HTTP 500: Server Error"
        finally:
            db.DB_FILE = orig
