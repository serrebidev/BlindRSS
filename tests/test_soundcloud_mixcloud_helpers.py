# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Offline tests for SoundCloud/Mixcloud URL classifiers and site registration."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import discovery as d


def test_soundcloud_url_and_kind():
    assert d.is_soundcloud_url("https://soundcloud.com/lofi_girl") is True
    assert d.is_soundcloud_url("https://m.soundcloud.com/x") is True
    assert d.is_soundcloud_url("https://example.com/x") is False

    # feeds.soundcloud.com serves podcast RSS (what iTunes returns for a
    # SoundCloud-hosted show); it must NOT be treated as a SoundCloud web-app URL,
    # or it would be misrouted into the yt-dlp/api-v2 listing path and show no
    # episodes instead of parsing as ordinary RSS.
    assert d.is_soundcloud_url(
        "https://feeds.soundcloud.com/users/soundcloud:users:686761388/sounds.rss"
    ) is False
    assert d.soundcloud_listing_kind(
        "https://feeds.soundcloud.com/users/soundcloud:users:686761388/sounds.rss"
    ) == ""

    assert d.soundcloud_listing_kind("https://soundcloud.com/lofi_girl") == "user"
    assert d.soundcloud_listing_kind("https://soundcloud.com/lofi_girl/sets/chill") == "playlist"
    assert d.soundcloud_listing_kind("https://soundcloud.com/lofi_girl/some-track") == "track"
    # Reserved sections are not user profiles.
    assert d.soundcloud_listing_kind("https://soundcloud.com/discover") == ""
    assert d.soundcloud_listing_kind("https://soundcloud.com/you") == ""


def test_mixcloud_url_and_kind():
    assert d.is_mixcloud_url("https://www.mixcloud.com/8ballradio/") is True
    assert d.is_mixcloud_url("https://example.com/") is False

    assert d.mixcloud_listing_kind("https://www.mixcloud.com/8ballradio/") == "user"
    assert d.mixcloud_listing_kind("https://www.mixcloud.com/8ballradio/playlists/mix/") == "playlist"
    assert d.mixcloud_listing_kind("https://www.mixcloud.com/8ballradio/some-show/") == "cloudcast"


def test_mixcloud_registered_as_search_site_and_dispatches(monkeypatch):
    sites = d.get_ytdlp_searchable_sites(include_adult=False)
    ids = {s["id"] for s in sites}
    assert "mixcloud" in ids
    mix = next(s for s in sites if s["id"] == "mixcloud")
    assert mix.get("search_provider") == "mixcloud"

    called = {}

    def _fake(term, limit=30, timeout=15):
        called["term"] = term
        return [{"title": "x", "url": "https://www.mixcloud.com/u/c/", "site": "Mixcloud",
                 "site_id": "mixcloud", "kind": "media", "play_count": None,
                 "_title_is_fallback": False, "native_subscribe_url": "", "source_subscribe_url": ""}]

    monkeypatch.setattr(d, "search_mixcloud_media", _fake)
    out = d.search_ytdlp_site("cats", mix, limit=5, timeout=10)
    assert called.get("term") == "cats"
    assert len(out) == 1 and out[0]["site_id"] == "mixcloud"


def test_soundcloud_listing_uses_api_dates(monkeypatch):
    """User listings come from api-v2 with real publish dates (not dateless yt-dlp)."""

    def _fake_api(path, params, timeout=15.0, _retry=True):
        if path == "/resolve":
            return {"id": 42, "username": "SmartLife Tech Cast"}
        if path == "/users/42/tracks":
            return {
                "collection": [
                    {"kind": "track", "title": "Ep 2", "permalink_url": "https://soundcloud.com/x/ep2",
                     "created_at": "2019-12-17T14:55:47Z", "user": {"username": "SmartLife Tech Cast"}},
                    {"kind": "track", "title": "Ep 1", "permalink_url": "https://soundcloud.com/x/ep1",
                     "created_at": "2019-12-03T17:08:16Z", "user": {"username": "SmartLife Tech Cast"}},
                ],
                "next_href": "",
            }
        return None

    def _boom(*a, **k):
        raise AssertionError("yt-dlp fallback should not run when the API succeeds")

    monkeypatch.setattr(d, "_soundcloud_api_v2_get", _fake_api)
    monkeypatch.setattr(d, "_run_ytdlp_flat_listing", _boom)

    title, items = d.fetch_soundcloud_listing("https://soundcloud.com/smartlifetechcast", max_items=10)
    assert title == "SmartLife Tech Cast"
    assert [i.url for i in items] == ["https://soundcloud.com/x/ep2", "https://soundcloud.com/x/ep1"]
    assert items[0].published == "2019-12-17T14:55:47Z"
    assert items[1].published == "2019-12-03T17:08:16Z"
    assert all(i.author == "SmartLife Tech Cast" for i in items)


def test_soundcloud_listing_falls_back_to_ytdlp(monkeypatch):
    """When api-v2 is unavailable (no client_id), enumeration falls back to yt-dlp."""

    monkeypatch.setattr(d, "_soundcloud_api_v2_get", lambda *a, **k: None)

    called = {}

    def _fake_flat(url, max_items=60, timeout=30.0):
        called["url"] = url
        return "Fallback", [d.MediaListingItem(url="https://soundcloud.com/x/only", title="Only", author=None, published="")]

    monkeypatch.setattr(d, "_run_ytdlp_flat_listing", _fake_flat)

    title, items = d.fetch_soundcloud_listing("https://soundcloud.com/smartlifetechcast", max_items=5)
    assert called.get("url") == "https://soundcloud.com/smartlifetechcast"
    assert title == "Fallback"
    assert len(items) == 1


def test_soundcloud_client_id_cached(monkeypatch):
    calls = {"n": 0}

    def _fake_fetch(timeout=15.0):
        calls["n"] += 1
        return "CID_ABC"

    monkeypatch.setattr(d, "_fetch_soundcloud_client_id", _fake_fetch)
    monkeypatch.setattr(d, "_SOUNDCLOUD_CLIENT_ID", None)
    a = d._get_soundcloud_client_id()
    b = d._get_soundcloud_client_id()
    assert a == b == "CID_ABC"
    assert calls["n"] == 1  # cached after first fetch
