# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Custom channel names must survive refreshes (issue #43).

The article list's Feed column reads the stored feed title, so the stored
title must always be the user's custom name when one exists. These tests pin
the refresh-time rules in providers.local._resolve_feed_title_update:
custom name -> original <title>, including renames made in builds that
predate the title_is_custom flag (stored title differs from the last-known
upstream title).
"""
import os
import sys
import uuid

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db as db
import providers.local as local_mod
from providers.local import LocalProvider, _resolve_feed_title_update


def _rss(title: str) -> str:
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>{title}</title>
<link>https://example.com/</link><description>d</description>
<item><guid>e1</guid><title>A</title><link>https://example.com/1</link><description>b</description></item>
</channel></rss>"""


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200
        self.headers = {"Content-Type": "application/rss+xml"}
        self.url = "https://example.com/feed.xml"

    def raise_for_status(self) -> None:
        pass


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


def _insert_feed(title: str, *, title_is_custom: int = 0, upstream_title=None) -> str:
    feed_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, title_is_custom, upstream_title, category, icon_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (feed_id, "https://example.com/feed.xml", title, title_is_custom, upstream_title, "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _stored_title(feed_id: str):
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT title, COALESCE(title_is_custom, 0), upstream_title FROM feeds WHERE id = ?",
            (feed_id,),
        ).fetchone()
    finally:
        conn.close()
    return row


def _serve(monkeypatch, feed_title: str) -> None:
    monkeypatch.setattr(
        local_mod.utils, "safe_requests_get", lambda *a, **k: _Resp(_rss(feed_title))
    )


def test_flagged_custom_title_survives_refresh(provider, monkeypatch):
    feed_id = _insert_feed("My Custom Name", title_is_custom=1)
    _serve(monkeypatch, "Original Upstream Title")

    assert provider.refresh_feed(feed_id) is True

    title, is_custom, upstream = _stored_title(feed_id)
    assert title == "My Custom Name"
    assert is_custom == 1
    assert upstream == "Original Upstream Title"


def test_legacy_rename_without_flag_survives_refresh(provider, monkeypatch):
    # Renamed in a build that predates title_is_custom: flag is 0 but the
    # stored title matches neither the URL nor any known upstream title.
    feed_id = _insert_feed("Legacy Custom Name", title_is_custom=0, upstream_title=None)
    _serve(monkeypatch, "Original Upstream Title")

    assert provider.refresh_feed(feed_id) is True

    title, is_custom, upstream = _stored_title(feed_id)
    assert title == "Legacy Custom Name"
    assert is_custom == 1  # self-healed
    assert upstream == "Original Upstream Title"


def test_refresh_managed_title_tracks_upstream_renames(provider, monkeypatch):
    feed_id = _insert_feed("Old Upstream Title", title_is_custom=0, upstream_title="Old Upstream Title")
    _serve(monkeypatch, "New Upstream Title")

    assert provider.refresh_feed(feed_id) is True

    title, is_custom, upstream = _stored_title(feed_id)
    assert title == "New Upstream Title"
    assert is_custom == 0
    assert upstream == "New Upstream Title"


def test_url_placeholder_title_adopts_upstream_title(provider, monkeypatch):
    feed_id = _insert_feed("https://example.com/feed.xml")
    _serve(monkeypatch, "Original Upstream Title")

    assert provider.refresh_feed(feed_id) is True

    title, is_custom, _ = _stored_title(feed_id)
    assert title == "Original Upstream Title"
    assert is_custom == 0


def test_reset_feed_title_restores_upstream_and_stays_managed(provider, monkeypatch):
    feed_id = _insert_feed("My Custom Name", title_is_custom=1, upstream_title="Original Upstream Title")

    assert provider.reset_feed_title(feed_id) is True
    title, is_custom, upstream = _stored_title(feed_id)
    assert title == "Original Upstream Title"
    assert is_custom == 0

    # A later refresh keeps tracking upstream renames instead of re-flagging
    # the old custom name.
    _serve(monkeypatch, "Renamed Upstream Title")
    assert provider.refresh_feed(feed_id) is True
    title, is_custom, upstream = _stored_title(feed_id)
    assert title == "Renamed Upstream Title"
    assert is_custom == 0
    assert upstream == "Renamed Upstream Title"


def test_rename_via_update_feed_then_refresh(provider, monkeypatch):
    feed_id = _insert_feed("Original Upstream Title", upstream_title="Original Upstream Title")
    provider.update_feed(feed_id, title="My Custom Name")
    _serve(monkeypatch, "Original Upstream Title")

    assert provider.refresh_feed(feed_id) is True

    title, is_custom, _ = _stored_title(feed_id)
    assert title == "My Custom Name"
    assert is_custom == 1


def test_resolve_helper_edge_cases():
    # Empty stored title adopts whatever the feed provides.
    assert _resolve_feed_title_update("", 0, None, "Feed Title", "https://u") == ("Feed Title", 0)
    # Nothing fetched: keep the stored value, don't flip the flag.
    assert _resolve_feed_title_update("Feed Title", 0, "Feed Title", "", "https://u") == ("Feed Title", 0)
    # Custom flag always wins.
    assert _resolve_feed_title_update("Mine", 1, "Theirs", "Theirs v2", "https://u") == ("Mine", 1)
