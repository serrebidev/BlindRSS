# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The refresh path persists the feed's declared <language> (issue #72).

Drives the real LocalRSSProvider._refresh_single_feed with the network stubbed
at utils.safe_requests_get, so the feedparser handling and the feeds UPDATE are
the code that actually runs -- the DB column is only useful if refresh fills it.
"""

import os
import sys
import tempfile
import threading
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import db, utils
import providers.local as local


def _rss(language_element: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>News</title><link>https://example.com</link>"
        f"{language_element}"
        "<item><title>First</title><link>https://example.com/a</link>"
        "<guid>https://example.com/a</guid>"
        "<description>Body text.</description>"
        "<pubDate>Mon, 14 Jul 2026 10:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )


class _Resp:
    def __init__(self, body: str):
        self.content = body.encode("utf-8")
        self.text = body
        self.status_code = 200
        self.headers = {"Content-Type": "application/rss+xml"}
        self.url = "https://example.com/rss"
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        pass


@pytest.fixture
def provider(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(db, "DB_FILE", os.path.join(tmpdir, "rss.db"))
    db.init_db()
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO feeds (id, title, url, category) VALUES (?,?,?,?)",
        ("f1", "News", "https://example.com/rss", "News"),
    )
    conn.commit()
    conn.close()
    return local.LocalProvider({})


def _feed_language():
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT language FROM feeds WHERE id='f1'").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


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
        # Mirrors what refresh_feeds builds: a per-host concurrency limiter.
        host_limits=defaultdict(lambda: threading.Semaphore(4)),
        feed_timeout=15,
        retries=0,
        progress_cb=None,
        force=True,
    )


def test_refresh_stores_the_declared_language(provider, monkeypatch):
    _refresh(provider, monkeypatch, _rss("<language>ru</language>"))
    assert _feed_language() == "ru"


def test_refresh_normalizes_the_declared_language(provider, monkeypatch):
    _refresh(provider, monkeypatch, _rss("<language>pt-br</language>"))
    assert _feed_language() == "pt-BR"


def test_feed_without_language_stays_null(provider, monkeypatch):
    _refresh(provider, monkeypatch, _rss(""))
    assert _feed_language() is None


def test_junk_language_is_not_stored(provider, monkeypatch):
    """A meaningless declaration must not become a bad lang attribute."""
    _refresh(provider, monkeypatch, _rss("<language>unknown</language>"))
    assert _feed_language() is None


def test_a_later_refresh_without_language_keeps_the_known_one(provider, monkeypatch):
    """COALESCE guard: a conditional GET or a transiently language-less parse
    must not erase a language the publisher already declared."""
    _refresh(provider, monkeypatch, _rss("<language>ru</language>"))
    assert _feed_language() == "ru"

    _refresh(provider, monkeypatch, _rss(""))
    assert _feed_language() == "ru"


def test_a_changed_language_is_picked_up(provider, monkeypatch):
    _refresh(provider, monkeypatch, _rss("<language>ru</language>"))
    _refresh(provider, monkeypatch, _rss("<language>de</language>"))
    assert _feed_language() == "de"


def test_get_feeds_exposes_the_language(provider, monkeypatch):
    _refresh(provider, monkeypatch, _rss("<language>ru</language>"))
    feeds = {f.id: f for f in provider.get_feeds()}
    assert feeds["f1"].language == "ru"
