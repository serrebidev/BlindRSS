# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Read articles must never come back as new after a refresh (issue #106).

Two independent mechanisms resurrected them, both driven here through the real
``LocalProvider._refresh_single_feed`` with only the network stubbed:

1. Retention deletes everything past its window, but a feed keeps serving those
   same entries, so the next refresh re-inserted every purged item as unread --
   on every update cycle, for as long as the feed listed them.
2. An entry with no ``<guid>``, ``<id>`` or ``<link>`` gets a synthesized
   identity that hashes its body, so a publisher editing the text minted a new
   article id and the item the user had already read reappeared as a duplicate.
"""

import os
import sys
import tempfile
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import db, utils
import providers.local as local


FEED_URL = "https://example.com/rss"


class _Resp:
    def __init__(self, body: str):
        self.content = body.encode("utf-8")
        self.text = body
        self.status_code = 200
        self.headers = {"Content-Type": "application/rss+xml"}
        self.url = FEED_URL
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        pass


def _channel(items: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<title>News</title><link>https://example.com</link>"
        f"{items}"
        "</channel></rss>"
    )


def _pub_date(days_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _item(index: int, days_ago: int) -> str:
    return (
        f"<item><title>Item {index}</title>"
        f"<link>https://example.com/{index}</link>"
        f"<guid>https://example.com/{index}</guid>"
        f"<description>Body {index}</description>"
        f"<pubDate>{_pub_date(days_ago)}</pubDate></item>"
    )


@pytest.fixture
def feed_db(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(db, "DB_FILE", os.path.join(tmpdir, "rss.db"))
    db.init_db()
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO feeds (id, title, url, category) VALUES (?,?,?,?)",
        ("f1", "News", FEED_URL, "News"),
    )
    conn.commit()
    conn.close()
    return tmpdir


def _refresh(provider, monkeypatch, body: str):
    monkeypatch.setattr(utils, "safe_requests_get", lambda *a, **k: _Resp(body))
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT id, url, title, category, etag, last_modified, "
            "COALESCE(title_is_custom, 0), COALESCE(upstream_title, '') FROM feeds WHERE id='f1'"
        ).fetchone()
    finally:
        conn.close()
    provider._refresh_single_feed(
        row,
        host_limits=defaultdict(lambda: threading.Semaphore(4)),
        feed_timeout=15,
        retries=0,
        progress_cb=None,
        force=True,
    )


def _counts():
    conn = db.get_connection()
    try:
        total, unread = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_read = 0), 0) FROM articles"
        ).fetchone()
        return total, unread
    finally:
        conn.close()


def test_retention_purged_entries_do_not_come_back_as_unread(feed_db, monkeypatch):
    """The resurrect/purge loop the issue reports: read items back as new."""
    body = _channel(
        "".join(_item(i, days_ago=30) for i in range(5))
        + "".join(_item(i, days_ago=1) for i in range(5, 8))
    )
    provider = local.LocalProvider({"article_retention": "1_week"})

    _refresh(provider, monkeypatch, body)
    # Nothing already past the retention window is imported: the very next
    # sweep would delete it again anyway.
    assert _counts() == (3, 3)

    assert provider.mark_all_read("f1") is True
    assert _counts() == (3, 0)

    # Two more cycles of exactly what the app does on every update.
    for _ in range(2):
        db.cleanup_old_articles(7)
        _refresh(provider, monkeypatch, body)
        assert _counts() == (3, 0)


def test_unlimited_retention_still_imports_the_whole_feed(feed_db, monkeypatch):
    """The guard must key off the user's setting, not shrink every feed."""
    body = _channel(
        "".join(_item(i, days_ago=400) for i in range(5))
        + "".join(_item(i, days_ago=1) for i in range(5, 8))
    )
    provider = local.LocalProvider({"article_retention": "unlimited"})

    _refresh(provider, monkeypatch, body)
    assert _counts() == (8, 8)


def test_undated_entries_survive_retention_filtering(feed_db, monkeypatch):
    """Undated articles carry a sentinel below every cutoff; keep importing them."""
    body = _channel(
        "<item><title>No date</title><link>https://example.com/x</link>"
        "<guid>https://example.com/x</guid><description>Body</description></item>"
    )
    provider = local.LocalProvider({"article_retention": "1_day"})

    _refresh(provider, monkeypatch, body)
    assert _counts() == (1, 1)


def _bodiless_item(description: str) -> str:
    # No <guid>, no <id>, no <link>: identity has to be synthesized.
    return (
        f"<item><title>Episode 1</title><description>{description}</description>"
        f"<pubDate>{_pub_date(2)}</pubDate></item>"
    )


def test_editing_an_identityless_entry_does_not_duplicate_it(feed_db, monkeypatch):
    provider = local.LocalProvider({})

    _refresh(provider, monkeypatch, _channel(_bodiless_item("Body v1")))
    assert _counts() == (1, 1)

    assert provider.mark_all_read("f1") is True

    _refresh(
        provider,
        monkeypatch,
        _channel(_bodiless_item("Body v2, after the publisher fixed a typo")),
    )
    assert _counts() == (1, 0)


def test_distinct_identityless_entries_are_still_separate_articles(feed_db, monkeypatch):
    """(title, date) matching must not collapse genuinely different entries."""
    items = (
        f"<item><title>Episode 1</title><description>One</description>"
        f"<pubDate>{_pub_date(3)}</pubDate></item>"
        f"<item><title>Episode 2</title><description>Two</description>"
        f"<pubDate>{_pub_date(2)}</pubDate></item>"
    )
    provider = local.LocalProvider({})

    _refresh(provider, monkeypatch, _channel(items))
    assert _counts() == (2, 2)

    _refresh(provider, monkeypatch, _channel(items))
    assert _counts() == (2, 2)


def test_guid_entries_are_not_matched_by_title_and_date(feed_db, monkeypatch):
    """A feed that reuses a title+date under new guids still gets two articles."""
    first = (
        "<item><title>Live blog</title><link>https://example.com/a</link>"
        f"<guid>https://example.com/a</guid><pubDate>{_pub_date(1)}</pubDate></item>"
    )
    second = (
        "<item><title>Live blog</title><link>https://example.com/b</link>"
        f"<guid>https://example.com/b</guid><pubDate>{_pub_date(1)}</pubDate></item>"
    )
    provider = local.LocalProvider({})

    _refresh(provider, monkeypatch, _channel(first))
    _refresh(provider, monkeypatch, _channel(first + second))
    assert _counts() == (2, 2)
