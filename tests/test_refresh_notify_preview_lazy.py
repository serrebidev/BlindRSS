# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The new-article notification preview must be computed lazily.

The preview is a full HTML->text parse of an entry's body and is only used
for articles that turn out to be NEW. Computing it for every entry (the old
behavior) made each steady-state refresh burn substantial worker CPU per
feed on text that was then thrown away -- a major contributor to the UI
thread starving during refreshes, because that worker CPU is GIL-bound.
These tests pin: known entries cost zero preview parses, and new articles
still arrive with a correct plain-text preview.
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
from providers.local import LocalProvider


_RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Preview Feed</title><link>https://example.com/</link><description>d</description>
<item><guid>g1</guid><title>One</title><link>https://example.com/1</link>
<content:encoded>&lt;p&gt;First &lt;b&gt;body&lt;/b&gt; text.&lt;/p&gt;</content:encoded></item>
<item><guid>g2</guid><title>Two</title><link>https://example.com/2</link>
<content:encoded>&lt;p&gt;Second body text.&lt;/p&gt;</content:encoded></item>
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
    monkeypatch.setattr(
        local_mod.utils, "safe_requests_get", lambda *a, **k: _Resp(_RSS)
    )
    return LocalProvider(
        {
            "providers": {"local": {}},
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
            "max_concurrent_refreshes": 1,
            "per_host_max_connections": 1,
        }
    )


def _insert_feed() -> str:
    feed_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, "https://example.com/feed.xml", "Preview Feed", "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _counting_preview(monkeypatch):
    calls = []
    original = local_mod._plain_text_preview

    def spy(raw_text, limit=None):
        calls.append(raw_text)
        return original(raw_text, limit=limit)

    monkeypatch.setattr(local_mod, "_plain_text_preview", spy)
    return calls


def test_new_articles_still_get_previews(provider, monkeypatch):
    calls = _counting_preview(monkeypatch)
    feed_id = _insert_feed()
    states = []
    assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
    new_articles = [a for s in states for a in (s.get("new_articles") or [])]
    assert len(new_articles) == 2
    previews = {a["title"]: a["preview"] for a in new_articles}
    assert previews["One"] == "First body text."
    assert previews["Two"] == "Second body text."
    # One preview parse per genuinely new article.
    assert len(calls) == 2


def test_steady_state_refresh_computes_no_previews(provider, monkeypatch):
    feed_id = _insert_feed()
    assert provider.refresh_feed(feed_id) is True
    calls = _counting_preview(monkeypatch)
    states = []
    assert provider.refresh_feed(feed_id, progress_cb=states.append) is True
    new_articles = [a for s in states for a in (s.get("new_articles") or [])]
    assert new_articles == []
    # Every entry was already known: no preview may be parsed at all.
    assert calls == []
