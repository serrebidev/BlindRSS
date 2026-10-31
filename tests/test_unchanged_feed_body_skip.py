# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""A feed body unchanged since the last stored refresh is handled like a 304.

YouTube channel feeds send no ETag/Last-Modified, so with a large subscription
list, mostly YouTube channels, every refresh cycle got full 200s and re-ran
parse + store although only the view counters (media:statistics/starRating)
had moved.
"""

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

from core import browser_feed, db, discovery, utils
import providers.local as local


FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UC0123456789abcdefghijkl"
# Yesterday: inside any retention window and not "dated in the future".
DAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
CHALLENGE_HTML = (
    "<!doctype html><html><head><title>Just a moment...</title>"
    '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
    "</head><body>Verifying you are human.</body></html>"
)


class _Resp:
    def __init__(self, body: str, content_type: str = "application/atom+xml", headers=None):
        self.content = body.encode("utf-8")
        self.text = body
        self.status_code = 200
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.url = FEED_URL
        self.history = []
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        pass


def _entry(index: int, views: int, published: str = f"{DAY}T08:15:00+00:00") -> str:
    return (
        f"<entry><id>yt:video:vid{index}</id><title>Video {index}</title>"
        f'<link rel="alternate" href="https://www.youtube.com/watch?v=vid{index}"/>'
        f"<published>{published}</published><updated>{published}</updated>"
        "<media:group><media:description>Body</media:description>"
        f'<media:community><media:starRating count="{views // 10}" average="5.00" min="1" max="5"/>'
        f'<media:statistics views="{views}"/></media:community></media:group></entry>'
    )


def _feed(*entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">'
        "<title>Channel</title>" + "".join(entries) + "</feed>"
    )


@pytest.fixture
def provider(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO feeds (id, title, url, category) VALUES (?,?,?,?)",
        ("f1", "Channel", FEED_URL, "YouTube"),
    )
    conn.commit()
    conn.close()
    # The #109 history listing (yt-dlp) only runs where a test asks for it.
    monkeypatch.setattr(local, "youtube_history_due", lambda *_a, **_k: False)
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", False)
    return local.LocalProvider({"browser_feed_fallback_enabled": True, "feed_retry_attempts": 0})


def _refresh(provider, monkeypatch, body, *, force: bool = False) -> str:
    response = body if isinstance(body, _Resp) else _Resp(body)
    monkeypatch.setattr(utils, "safe_requests_get", lambda *a, **k: response)
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT id, url, title, category, etag, last_modified, "
            "COALESCE(title_is_custom, 0), COALESCE(upstream_title, '') FROM feeds WHERE id='f1'"
        ).fetchone()
    finally:
        conn.close()
    states = []
    provider._refresh_single_feed(
        row,
        host_limits=defaultdict(lambda: threading.Semaphore(4)),
        feed_timeout=15,
        retries=0,
        progress_cb=states.append,
        force=force,
    )
    return states[-1]["status"]


def _query(sql: str):
    conn = db.get_connection()
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _count_parses(monkeypatch):
    parses = []
    real_parse = local._parse_feed_document

    def counting_parse(*args, **kwargs):
        parses.append(1)
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(local, "_parse_feed_document", counting_parse)
    return parses


def test_unchanged_body_skips_parse_and_store(provider, monkeypatch):
    parses = _count_parses(monkeypatch)

    assert _refresh(provider, monkeypatch, _feed(_entry(1, 100), _entry(2, 200))) == "ok"
    assert len(parses) == 1 and len(_query("SELECT id FROM articles")) == 2

    # Only the view/rating counters moved: no parse, no store.
    assert _refresh(provider, monkeypatch, _feed(_entry(1, 150), _entry(2, 260))) == "not_modified"
    assert len(parses) == 1

    # A forced refresh always parses and stores.
    assert _refresh(provider, monkeypatch, _feed(_entry(1, 150), _entry(2, 260)), force=True) == "ok"
    assert len(parses) == 2

    # A changed non-counter field of an existing video is processed.
    moved = f"{DAY}T08:40:00+00:00"
    assert _refresh(provider, monkeypatch, _feed(_entry(1, 150, published=moved), _entry(2, 260))) == "ok"
    assert len(parses) == 3
    assert any(date.endswith("08:40:00") for (date,) in _query("SELECT date FROM articles"))

    # A new video is processed.
    body = _feed(_entry(3, 5), _entry(1, 150, published=moved), _entry(2, 260))
    assert _refresh(provider, monkeypatch, body) == "ok"
    assert len(parses) == 4 and len(_query("SELECT id FROM articles")) == 3


def test_skip_still_saves_new_validators(provider, monkeypatch):
    body = _feed(_entry(1, 100))
    assert _refresh(provider, monkeypatch, body) == "ok"
    assert _refresh(provider, monkeypatch, _Resp(body, headers={"ETag": '"v2"'})) == "not_modified"
    assert _query("SELECT etag FROM feeds WHERE id='f1'") == [('"v2"',)]


def test_body_is_remembered_only_after_a_successful_store(provider, monkeypatch):
    body = _feed(_entry(1, 100))
    real_parse = local._parse_feed_document
    calls = []

    def failing_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("broken parse")
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(local, "_parse_feed_document", failing_once)

    assert _refresh(provider, monkeypatch, body) == "error"
    assert _refresh(provider, monkeypatch, body) == "ok"
    assert len(calls) == 2 and len(_query("SELECT id FROM articles")) == 1


def test_body_replaced_by_browser_fallback_is_not_remembered(provider, monkeypatch):
    # The direct response is a static bot wall; the browser fetches the feed.
    # Remembering the wall's digest skipped the fallback on every later cycle.
    served = [_feed(_entry(1, 100))]
    monkeypatch.setattr(
        local.browser_feed_mod,
        "fetch_feed",
        lambda url, **_k: browser_feed.BrowserFeedResponse(served[0], url),
    )
    wall = _Resp(CHALLENGE_HTML, content_type="text/html")

    assert _refresh(provider, monkeypatch, wall) == "ok"
    served[0] = _feed(_entry(2, 5), _entry(1, 100))
    assert _refresh(provider, monkeypatch, wall) == "ok"
    assert len(_query("SELECT id FROM articles")) == 2


def test_youtube_listing_write_forces_the_next_rss_store(provider, monkeypatch):
    # The #109 history listing has day-only dates; the RSS body stored next
    # restores the exact time, so it must not be skipped as unchanged.
    body = _feed(_entry(1, 100))
    assert _refresh(provider, monkeypatch, body) == "ok"
    assert _query("SELECT date FROM articles")[0][0].endswith("08:15:00")

    monkeypatch.setattr(local, "youtube_history_due", lambda *_a, **_k: True)
    monkeypatch.setattr(
        discovery,
        "fetch_youtube_channel_items",
        lambda *_a, **_k: (
            "Channel",
            [discovery.YoutubeSearchItem(url="https://www.youtube.com/watch?v=vid1", title="Video 1",
                                         published=DAY)],
        ),
    )
    assert _refresh(provider, monkeypatch, body) == "ok"
    assert _query("SELECT date FROM articles")[0][0].endswith("08:15:00")


def test_feed_url_change_forgets_the_body(provider, monkeypatch):
    body = _feed(_entry(1, 100))
    assert _refresh(provider, monkeypatch, body) == "ok"
    assert provider.update_feed("f1", url=FEED_URL + "&x=1") is True
    assert "f1" not in provider._stored_feed_body_digests
