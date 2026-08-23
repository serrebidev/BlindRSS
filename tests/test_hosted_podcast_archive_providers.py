# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock

import pytest

from core import db
from core.models import Article
from providers.bazqux import BazQuxProvider
from providers.hosted_podcast_archive import HostedPodcastArchiveMixin
from providers.inoreader import InoreaderProvider
from providers.theoldreader import TheOldReaderProvider


FEED_ID = "feed/https://example.com/podcast.xml"
FEED_URL = "https://example.com/podcast.xml"


def _inoreader():
    return InoreaderProvider({
        "providers": {
            "inoreader": {
                "app_id": "app",
                "app_key": "secret",
                "token": "token",
                "refresh_token": "stable-account",
            },
        },
        "podcast_archive_enabled": True,
    })


def _bazqux():
    return BazQuxProvider({
        "providers": {"bazqux": {"email": "reader@example.com", "password": "secret"}},
        "podcast_archive_enabled": True,
    })


def _old_reader():
    return TheOldReaderProvider({
        "providers": {"theoldreader": {"email": "reader@example.com", "password": "secret"}},
        "podcast_archive_enabled": True,
    })


@pytest.mark.parametrize("factory", [_inoreader, _bazqux, _old_reader])
def test_every_google_reader_provider_uses_hosted_archive_mixin(factory):
    provider = factory()
    assert isinstance(provider, HostedPodcastArchiveMixin)
    assert provider.podcast_source_url(FEED_ID, "https://example.com/site") == FEED_URL
    assert callable(provider.refresh_podcast_archive)


def test_inoreader_existing_feeds_queue_true_subscription_url(monkeypatch):
    provider = _inoreader()
    monkeypatch.setattr(provider, "_has_required_auth", lambda: True)
    monkeypatch.setattr(provider, "_get_cached_feeds", lambda **_kwargs: None)
    response = MagicMock()
    response.json.return_value = {
        "subscriptions": [{
            "id": FEED_ID,
            "title": "Podcast",
            "url": "https://example.com/site",
            "categories": [],
        }],
    }
    monkeypatch.setattr(provider, "_request", lambda *_args, **_kwargs: response)
    queued = []
    monkeypatch.setattr(provider, "_queue_podcast_archive_scans", queued.append)

    feeds = provider.get_feeds()

    assert feeds[0].source_url == FEED_URL
    assert queued == [feeds]


def test_bazqux_existing_feeds_queue_true_subscription_url(monkeypatch):
    provider = _bazqux()
    monkeypatch.setattr(provider, "_login", lambda: True)
    subscriptions = MagicMock()
    subscriptions.json.return_value = {
        "subscriptions": [{
            "id": FEED_ID,
            "title": "Podcast",
            "url": "https://example.com/site",
            "categories": [],
        }],
    }
    subscriptions.raise_for_status.return_value = None
    counts = MagicMock()
    counts.ok = True
    counts.json.return_value = {"unreadcounts": []}
    responses = iter([subscriptions, counts])
    monkeypatch.setattr(provider.session, "get", lambda *_args, **_kwargs: next(responses))
    queued = []
    monkeypatch.setattr(provider, "_queue_podcast_archive_scans", queued.append)

    feeds = provider.get_feeds()

    assert feeds[0].source_url == FEED_URL
    assert queued == [feeds]


def test_theoldreader_existing_feeds_queue_true_subscription_url(monkeypatch):
    provider = _old_reader()
    monkeypatch.setattr(provider, "_login", lambda: True)
    subscriptions = MagicMock()
    subscriptions.json.return_value = {
        "subscriptions": [{
            "id": FEED_ID,
            "title": "Podcast",
            "url": "https://example.com/site",
            "categories": [],
        }],
    }
    subscriptions.raise_for_status.return_value = None
    counts = MagicMock()
    counts.ok = True
    counts.json.return_value = {"unreadcounts": []}
    responses = iter([subscriptions, counts])
    monkeypatch.setattr(
        "providers.theoldreader.requests.get",
        lambda *_args, **_kwargs: next(responses),
    )
    queued = []
    monkeypatch.setattr(provider, "_queue_podcast_archive_scans", queued.append)

    feeds = provider.get_feeds()

    assert feeds[0].source_url == FEED_URL
    assert queued == [feeds]


@pytest.mark.parametrize("factory", [_inoreader, _bazqux, _old_reader])
def test_every_hosted_provider_merges_sidecar_into_direct_feed(
    factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "all-hosted-providers.db"))
    db.init_db()
    provider = factory()
    db.replace_hosted_podcast_archive_entries(
        provider._podcast_archive_scope(),
        FEED_ID,
        [{
            "episode_key": "old-episode",
            "title": "Recovered episode",
            "url": "https://example.com/old",
            "content": "Archived notes",
            "date": "2010-01-01 00:00:00",
            "author": "Host",
            "media_url": "https://cdn.example.com/old.mp3",
            "media_type": "audio/mpeg",
        }],
    )
    live = Article(
        id="live",
        feed_id=FEED_ID,
        title="Current episode",
        url="https://example.com/current",
        content="Current notes",
        date="2026-01-01 00:00:00",
        author="Host",
        media_url="https://cdn.example.com/current.mp3",
        media_type="audio/mpeg",
    )

    merged = provider._merge_hosted_archive_articles(FEED_ID, [live])

    assert [article.title for article in merged] == [
        "Current episode",
        "Recovered episode",
    ]
    assert merged[1].is_read is True

    # Exercise each provider's public article path, not just the shared merge
    # helper, so a future provider refactor cannot silently drop the overlay.
    if isinstance(provider, InoreaderProvider):
        monkeypatch.setattr(provider, "_has_required_auth", lambda: True)
        monkeypatch.setattr(
            provider,
            "_get_articles_page_cached",
            lambda *_args, **_kwargs: ([live], 1),
        )
        public_articles, total = provider.get_articles_page(FEED_ID, 0, 20)
        assert total == 2
    elif isinstance(provider, BazQuxProvider):
        monkeypatch.setattr(
            provider,
            "_fetch_articles",
            lambda *_args, **_kwargs: [live],
        )
        public_articles = provider.get_articles(FEED_ID)
    else:
        monkeypatch.setattr(provider, "_get_remote_articles", lambda _feed_id: [live])
        public_articles = provider.get_articles(FEED_ID)
    assert [article.title for article in public_articles] == [
        "Current episode",
        "Recovered episode",
    ]
