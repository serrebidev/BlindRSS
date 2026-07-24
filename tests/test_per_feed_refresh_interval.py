# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for per-feed refresh interval overrides (feed properties dialog)."""

import os
import sys
import tempfile
import uuid

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db as db
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


def _insert_feed():
    feed_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (feed_id, f"https://example.com/{feed_id}", "T", "C"),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _feed_row(feed_id):
    # Shape matches the SELECT in LocalProvider.refresh().
    return (feed_id, "https://example.com/feed", "T", "C", None, None, 0, None)


def test_get_feed_refresh_interval_overrides():
    def _check():
        with_override = _insert_feed()
        manual_only = _insert_feed()
        no_override = _insert_feed()
        other_settings_only = _insert_feed()
        malformed = _insert_feed()

        db.set_feed_settings(with_override, {"refresh_interval_seconds": 60})
        db.set_feed_settings(manual_only, {"refresh_interval_seconds": 0})
        db.set_feed_settings(other_settings_only, {"timeout_seconds": 30, "refresh_interval_seconds": None})
        conn = db.get_connection()
        try:
            conn.execute(
                "UPDATE feeds SET feed_settings = ? WHERE id = ?", ("{not json", malformed)
            )
            conn.commit()
        finally:
            conn.close()

        overrides = db.get_feed_refresh_interval_overrides()
        assert overrides == {with_override: 60, manual_only: 0}
        assert no_override not in overrides

    _with_temp_db(_check)


def test_overrides_ignore_bool_and_negative_values():
    def _check():
        bool_feed = _insert_feed()
        negative_feed = _insert_feed()
        db.set_feed_settings(bool_feed, {"refresh_interval_seconds": True})
        db.set_feed_settings(negative_feed, {"refresh_interval_seconds": -5})

        overrides = db.get_feed_refresh_interval_overrides()
        assert bool_feed not in overrides
        assert overrides.get(negative_feed) == 0

    _with_temp_db(_check)


def test_scheduled_refresh_tick_uses_fastest_feed():
    def _check():
        provider = LocalProvider({"refresh_interval": 300})

        # No overrides: tick equals global interval.
        assert provider.scheduled_refresh_tick(300) == 300

        fast = _insert_feed()
        db.set_feed_settings(fast, {"refresh_interval_seconds": 60})
        assert provider.scheduled_refresh_tick(300) == 60

        # A manual-only feed (0) never shortens the tick.
        manual = _insert_feed()
        db.set_feed_settings(manual, {"refresh_interval_seconds": 0})
        assert provider.scheduled_refresh_tick(300) == 60

        # Overrides keep the loop alive even when the global setting is "Never".
        assert provider.scheduled_refresh_tick(0) == 60

    _with_temp_db(_check)


def test_filter_scheduled_due_rows():
    def _check():
        provider = LocalProvider({"refresh_interval": 300})

        plain = _insert_feed()
        fast = _insert_feed()
        slow = _insert_feed()
        manual = _insert_feed()
        db.set_feed_settings(fast, {"refresh_interval_seconds": 60})
        db.set_feed_settings(slow, {"refresh_interval_seconds": 600})
        db.set_feed_settings(manual, {"refresh_interval_seconds": 0})

        rows = [_feed_row(plain), _feed_row(fast), _feed_row(slow), _feed_row(manual)]

        # Never attempted: everything except manual-only feeds is due.
        due_ids = [r[0] for r in provider._filter_scheduled_due_rows(rows)]
        assert due_ids == [plain, fast, slow]

        # Simulate a refresh of everything just now.
        for row in rows:
            provider._note_scheduled_refresh_attempt(row[0])

        assert provider._filter_scheduled_due_rows(rows) == []

        # 90 (simulated) seconds later only the 60s feed is due again.
        import time as _time

        base = _time.monotonic()
        with provider._scheduled_refresh_last_attempt_lock:
            for fid in list(provider._scheduled_refresh_last_attempt):
                provider._scheduled_refresh_last_attempt[fid] = base - 90.0
        due_ids = [r[0] for r in provider._filter_scheduled_due_rows(rows)]
        assert due_ids == [fast]

        # 350 seconds later the global-interval feed is due as well, but not the 600s one.
        with provider._scheduled_refresh_last_attempt_lock:
            for fid in list(provider._scheduled_refresh_last_attempt):
                provider._scheduled_refresh_last_attempt[fid] = base - 350.0
        due_ids = [r[0] for r in provider._filter_scheduled_due_rows(rows)]
        assert due_ids == [plain, fast]

    _with_temp_db(_check)


def test_filter_is_passthrough_without_overrides():
    def _check():
        provider = LocalProvider({"refresh_interval": 300})
        plain = _insert_feed()
        rows = [_feed_row(plain)]
        provider._note_scheduled_refresh_attempt(plain)
        # No overrides configured: scheduled refreshes keep the legacy
        # behavior of refreshing every feed on every tick.
        assert provider._filter_scheduled_due_rows(rows) == rows

    _with_temp_db(_check)
