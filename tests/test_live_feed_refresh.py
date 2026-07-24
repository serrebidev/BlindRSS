# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import json
import os
import sys
import uuid

import feedparser
import pytest

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db as db_mod
from core import utils
from providers.local import LocalProvider
from providers.miniflux import MinifluxProvider


LIVE_SIMPLECAST_FEED = "https://feeds.simplecast.com/MhX_XZQZ"
LIVE_NPR_FEED = "https://feeds.npr.org/510289/podcast.xml"
LIVE_FLAG = "BLINDRSS_LIVE_FEED_TESTS"


pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_FLAG) != "1",
    reason=f"Set {LIVE_FLAG}=1 to run live network refresh tests.",
)


def _max_date_for_feed(feed_id: str) -> str:
    conn = db_mod.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM articles WHERE feed_id = ?", (feed_id,))
        row = cur.fetchone()
        return (row[0] or "").strip()
    finally:
        conn.close()


@pytest.mark.parametrize("feed_url", [LIVE_SIMPLECAST_FEED, LIVE_NPR_FEED])
def test_local_provider_live_refresh_for_real_feeds(monkeypatch, tmp_path, feed_url):
    test_db = tmp_path / "rss.db"
    monkeypatch.setattr(db_mod, "DB_FILE", str(test_db))
    db_mod.init_db()

    feed_id = str(uuid.uuid4())
    conn = db_mod.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url, etag, last_modified) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (feed_id, feed_url, feed_url, "Live", "", None, None),
        )
        conn.commit()
    finally:
        conn.close()

    provider = LocalProvider(
        {
            "providers": {"local": {}},
            "max_concurrent_refreshes": 2,
            "per_host_max_connections": 1,
            "feed_timeout_seconds": 15,
            "feed_retry_attempts": 1,
        }
    )
    assert provider.refresh(force=True) is True

    conn = db_mod.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (feed_id,))
        count = int(cur.fetchone()[0] or 0)
    finally:
        conn.close()

    assert count > 0
    assert _max_date_for_feed(feed_id) not in ("", "0001-01-01 00:00:00")


def test_miniflux_force_refresh_pulls_latest_simplecast_episode():
    with open(os.path.join(REPO_ROOT, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)

    mconf = (cfg.get("providers") or {}).get("miniflux") or {}
    if not mconf.get("url") or not mconf.get("api_key"):
        pytest.skip("Miniflux credentials are not configured in config.json")

    provider = MinifluxProvider(
        {
            "feed_timeout_seconds": max(10, int(cfg.get("feed_timeout_seconds", 15) or 15)),
            "providers": {"miniflux": mconf},
        }
    )

    feeds = provider._req("GET", "/v1/feeds") or []
    feed = next((f for f in feeds if str(f.get("feed_url") or "").strip() == LIVE_SIMPLECAST_FEED), None)
    if not feed:
        pytest.skip(f"Simplecast feed is not subscribed in Miniflux: {LIVE_SIMPLECAST_FEED}")

    upstream = utils.safe_requests_get(LIVE_SIMPLECAST_FEED, timeout=30)
    upstream.raise_for_status()
    parsed = feedparser.parse(upstream.content)
    latest_title = (parsed.entries[0].get("title") if parsed.entries else None) or ""
    if not latest_title:
        pytest.skip("Could not determine latest upstream Simplecast title")

    assert provider.refresh(force=True) is True

    feed_id = str(feed.get("id"))
    entries_data = provider._req(
        "GET",
        f"/v1/feeds/{feed_id}/entries",
        params={"direction": "desc", "order": "published_at", "status": ["unread", "read"], "limit": 20, "offset": 0},
    ) or {}
    entries = entries_data.get("entries") or []
    titles = [str(e.get("title") or "") for e in entries]
    assert latest_title in titles
