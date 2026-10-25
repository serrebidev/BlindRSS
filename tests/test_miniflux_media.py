# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Miniflux media: enclosure choice, NPR audio NPR's program feeds omit, Detect Audio."""

import time

import pytest

import core.db
from core import npr
from providers.miniflux import MinifluxProvider

NPR_URL = "https://www.npr.org/2026/10/23/nx-s1-6012247/u-s-and-israel-are-planning"
NPR_MP3 = "https://ondemand.npr.org/anon.npr-mp3/npr/me/2026/10/20261023_me_01.mp3"


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(core.db, "DB_FILE", str(tmp_path / "rss.db"))
    core.db.init_db()
    return MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://reader.example", "api_key": "x"}}}
    )


def _entry(entry_id="1", url="https://example.com/a", enclosures=None):
    return {"id": entry_id, "feed_id": "9", "title": "T", "url": url,
            "content": "<p>x</p>", "enclosures": enclosures or []}


def test_enclosure_choice_skips_cover_images_and_chapters():
    from core.utils import playable_enclosure
    image = {"url": "https://cdn.example/cover.jpg", "mime_type": "image/jpeg"}
    chapters = {"url": "https://cdn.example/ch.json", "mime_type": "application/json+chapters"}
    audio = {"url": "https://cdn.example/ep.mp3?x=1", "mime_type": ""}
    assert playable_enclosure([image, chapters, audio]) == ("https://cdn.example/ep.mp3?x=1", "audio/mpeg")
    assert playable_enclosure([image]) == (None, None)
    unknown = {"url": "https://track.example/r/abc", "mime_type": "application/octet-stream"}
    assert playable_enclosure([unknown])[0] == "https://track.example/r/abc"


def test_npr_story_without_enclosure_gets_player_audio_once(provider, monkeypatch):
    calls = []

    def fake_extract(url, timeout_s=10.0):
        calls.append(url)
        return NPR_MP3, "audio/mpeg"

    monkeypatch.setattr(npr, "extract_npr_audio", fake_extract)
    [article] = provider._entries_to_articles([_entry(url=NPR_URL)])
    assert (article.media_url, article.media_type) == (NPR_MP3, "audio/mpeg")

    # Stored: a reload must not fetch NPR again.
    [again] = provider._entries_to_articles([_entry(url=NPR_URL)])
    assert again.media_url == NPR_MP3
    assert calls == [NPR_URL]


def test_npr_miss_is_not_refetched_until_retry_window(provider, monkeypatch):
    calls = []
    monkeypatch.setattr(npr, "extract_npr_audio", lambda url, timeout_s=10.0: calls.append(url) or (None, None))
    provider._entries_to_articles([_entry(url=NPR_URL)])
    provider._entries_to_articles([_entry(url=NPR_URL)])
    assert len(calls) == 1

    real_time = time.time
    monkeypatch.setattr(npr.time, "time", lambda: real_time() + npr._MISS_RETRY_S + 1)
    provider._entries_to_articles([_entry(url=NPR_URL)])
    assert len(calls) == 2


def test_non_npr_entries_make_no_requests(provider, monkeypatch):
    monkeypatch.setattr(npr, "extract_npr_audio", lambda *a, **k: pytest.fail("network"))
    [article] = provider._entries_to_articles([_entry()])
    assert article.media_url is None


def test_detect_audio_result_persists_for_hosted_entries(provider):
    assert provider.update_article_media("1", "https://cdn.example/found.mp3", "audio/mpeg")
    [article] = provider._entries_to_articles([_entry()])
    assert article.media_url == "https://cdn.example/found.mp3"


def test_mark_all_read_all_uses_user_endpoint(provider, monkeypatch):
    class _Resp:
        status_code = 204

    puts = []
    monkeypatch.setattr(provider, "_req", lambda method, endpoint, **kw: {"id": 7} if endpoint == "/v1/me" else None)
    monkeypatch.setattr(provider._session, "put", lambda url, **kw: puts.append(url) or _Resp())
    assert provider.mark_all_read("unread:all") is True
    assert puts == ["https://reader.example/v1/users/7/mark-all-as-read"]


def test_google_reader_providers_share_hosted_media(provider, monkeypatch):
    from providers.bazqux import BazQuxProvider
    from providers.base import HostedArticleMediaMixin
    from providers.inoreader import InoreaderProvider
    from providers.theoldreader import TheOldReaderProvider

    for cls in (BazQuxProvider, InoreaderProvider, TheOldReaderProvider):
        assert issubclass(cls, HostedArticleMediaMixin)

    monkeypatch.setattr(npr, "extract_npr_audio", lambda url, timeout_s=10.0: (NPR_MP3, "audio/mpeg"))
    ino = InoreaderProvider({"providers": {"inoreader": {"app_id": "id", "app_key": "key", "token": "t"}}})
    items = [
        {"id": "a", "title": "NPR", "alternate": [{"href": NPR_URL}]},
        {"id": "b", "title": "Pod", "alternate": [{"href": "https://example.com/p"}],
         "enclosure": [{"href": "https://cdn.example/cover.png", "type": "image/png"},
                       {"href": "https://cdn.example/ep.m4a", "type": "audio/x-m4a"}]},
    ]
    npr_article, pod = ino._items_to_articles(items, "feed/1")
    assert npr_article.media_url == NPR_MP3
    assert pod.media_url == "https://cdn.example/ep.m4a"
