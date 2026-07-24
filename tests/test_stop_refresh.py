# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for Stop Refresh: cooperative cancellation of an in-flight batch refresh."""

import os
import sys
import tempfile
import uuid

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db as db
from providers.base import RSSProvider
from providers.local import LocalProvider


def _with_temp_db(fn):
    with tempfile.TemporaryDirectory() as tmp:
        orig = db.DB_FILE
        db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            db.init_db()
            fn()
        finally:
            db.DB_FILE = orig


def _insert_feeds(count):
    ids = []
    conn = db.get_connection()
    try:
        for _ in range(count):
            feed_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                (feed_id, f"https://example.com/{feed_id}", "T", "C"),
            )
            ids.append(feed_id)
        conn.commit()
    finally:
        conn.close()
    return ids


def test_cancel_refresh_returns_false_when_idle():
    def _check():
        provider = LocalProvider({})
        assert provider.cancel_refresh() is False

    _with_temp_db(_check)


def test_cancel_refresh_skips_queued_feeds():
    def _check():
        # One worker so execution is sequential and deterministic.
        provider = LocalProvider({"max_concurrent_refreshes": 1, "per_host_max_connections": 1})
        _insert_feeds(5)
        refreshed = []
        stop_once = {"armed": True}

        def _fake_single_feed(feed_row, *args, **kwargs):
            refreshed.append(feed_row[0])
            # Simulate the user hitting Stop Refresh while the first feed is
            # still being fetched (once; later runs proceed normally).
            if stop_once["armed"]:
                stop_once["armed"] = False
                assert provider.cancel_refresh() is True

        provider._refresh_single_feed = _fake_single_feed

        assert provider.refresh() is True
        assert len(refreshed) == 1  # the in-flight feed finished; the rest were skipped

        # The per-run cancel event must not leak into later refreshes.
        assert provider._active_refresh_cancel is None
        assert provider.cancel_refresh() is False
        refreshed.clear()
        assert provider.refresh() is True
        assert len(refreshed) == 5

    _with_temp_db(_check)


def test_cancel_refresh_skips_queued_targeted_feeds():
    def _check():
        provider = LocalProvider({"max_concurrent_refreshes": 1, "per_host_max_connections": 1})
        feed_ids = _insert_feeds(4)
        refreshed = []
        stop_once = {"armed": True}

        def _fake_single_feed(feed_row, *args, **kwargs):
            refreshed.append(feed_row[0])
            if stop_once["armed"]:
                stop_once["armed"] = False
                assert provider.cancel_refresh() is True

        provider._refresh_single_feed = _fake_single_feed

        assert provider.refresh_feeds_by_ids(feed_ids) is True
        assert refreshed == [feed_ids[0]]
        assert provider._active_refresh_cancel is None
        assert provider.cancel_refresh() is False

    _with_temp_db(_check)


def test_cancel_refresh_applies_to_single_feed_refresh():
    def _check():
        provider = LocalProvider({"max_concurrent_refreshes": 1, "per_host_max_connections": 1})
        feed_id = _insert_feeds(1)[0]
        refreshed = []

        def _fake_single_feed(feed_row, *args, **kwargs):
            refreshed.append(feed_row[0])
            assert provider.cancel_refresh() is True

        provider._refresh_single_feed = _fake_single_feed

        assert provider.refresh_feed(feed_id) is True
        assert refreshed == [feed_id]
        assert provider._active_refresh_cancel is None
        assert provider.cancel_refresh() is False

    _with_temp_db(_check)


def test_cancel_refresh_base_default_returns_false():
    class _Minimal(RSSProvider):
        def get_name(self):
            return "x"

        def refresh(self, progress_cb=None, force=False, scheduled=False):
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

    assert _Minimal({}).cancel_refresh() is False


def test_base_targeted_refresh_cancellation_skips_remaining_ids():
    class _Minimal(RSSProvider):
        def __init__(self, config):
            super().__init__(config)
            self.calls = []

        def get_name(self):
            return "x"

        def refresh(self, progress_cb=None, force=False, scheduled=False):
            return True

        def refresh_feed(self, feed_id, progress_cb=None):
            self.calls.append(str(feed_id))
            assert self.cancel_refresh() is True
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

    provider = _Minimal({})

    assert provider.refresh_feeds_by_ids(["1", "2", "3"]) is True

    assert provider.calls == ["1"]
    assert provider.cancel_refresh() is False
