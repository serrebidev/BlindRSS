# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock

import feedparser

from core import db, podcast_archive
from core import utils
from providers.local import LocalProvider


def _rss(items, *, title="Long Running Show", new_feed_url=""):
    migration = (
        '<itunes:new-feed-url xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">'
        f"{new_feed_url}</itunes:new-feed-url>"
        if new_feed_url else ""
    )
    rows = []
    for item in items:
        rows.append(
            f"""
            <item>
              <guid>{item['guid']}</guid>
              <title>{item['title']}</title>
              <link>{item.get('link', 'https://show.example/episodes/' + item['guid'])}</link>
              <pubDate>{item.get('date', 'Wed, 24 Jun 2020 12:00:00 GMT')}</pubDate>
              <description>{item.get('description', item['title'] + ' notes')}</description>
              <enclosure url="{item['media']}" type="audio/mpeg" />
            </item>
            """
        )
    return (
        "<?xml version='1.0'?><rss version='2.0'><channel>"
        f"<title>{title}</title><link>https://show.example/</link>{migration}"
        + "".join(rows)
        + "</channel></rss>"
    ).encode()


class _Response:
    def __init__(self, *, content=b"", payload=None, url="", status=200):
        self.content = content
        self._payload = payload
        self.url = url
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_deduplicate_episodes_uses_guid_media_and_title_date():
    first = podcast_archive.ArchiveEpisode(
        title="Episode 10",
        guid="episode-10",
        media_url="https://cdn.example/audio/10.mp3?utm_source=feed",
        published="2020-06-24 12:00:00",
    )
    corrected = podcast_archive.ArchiveEpisode(
        title="Episode 10 (corrected)",
        guid="episode-10",
        media_url="https://cdn.example/audio/10.mp3?token=changed",
        published="2020-06-24 12:00:00",
        description="Complete notes",
    )
    first.identity_keys = podcast_archive._episode_identity_keys(first)
    corrected.identity_keys = podcast_archive._episode_identity_keys(corrected)

    result = podcast_archive.deduplicate_episodes([first, corrected])

    assert result == [first]
    assert first.description == "Complete notes"


def test_media_dedup_keeps_episode_identifying_query_values():
    one = podcast_archive.ArchiveEpisode(
        title="One", media_url="https://cdn.example/download?episode=1&token=old"
    )
    two = podcast_archive.ArchiveEpisode(
        title="Two", media_url="https://cdn.example/download?episode=2&token=new"
    )
    one.identity_keys = podcast_archive._episode_identity_keys(one)
    two.identity_keys = podcast_archive._episode_identity_keys(two)

    assert len(podcast_archive.deduplicate_episodes([one, two])) == 2


def test_scan_follows_feed_migration_and_recovers_archive_only_items():
    old_url = "https://example.com/feed.xml"
    new_url = "https://example.org/podcast.rss"
    current = _rss(
        [{"guid": "ep-3", "title": "Episode 3", "media": "https://new.example/3.mp3"}],
        new_feed_url=new_url,
    )
    old_snapshot = _rss([
        {"guid": "ep-1", "title": "Episode 1", "media": "https://old.example/1.mp3"},
        {"guid": "ep-2", "title": "Episode 2", "media": "https://old.example/2.mp3"},
        # Same GUID as the current item, with an obsolete enclosure.
        {"guid": "ep-3", "title": "Episode 3", "media": "https://old.example/3.mp3"},
    ])
    new_current = _rss(
        [{"guid": "ep-3", "title": "Episode 3", "media": "https://new.example/3.mp3"}]
    )

    def fetcher(url, **_kwargs):
        if url.startswith(podcast_archive.CDX_ENDPOINT):
            requested = parse_qs(urlsplit(url).query)["url"][0]
            if requested == old_url:
                return _Response(payload=[
                    ["timestamp", "original", "digest", "statuscode", "mimetype"],
                    ["20200102030405", old_url, "digest-1", "200", "application/rss+xml"],
                ])
            return _Response(payload=[
                ["timestamp", "original", "digest", "statuscode", "mimetype"],
            ])
        if "20200102030405id_" in url:
            return _Response(content=old_snapshot, url=url)
        if url == new_url:
            return _Response(content=new_current, url=new_url)
        raise AssertionError(f"Unexpected URL: {url}")

    result = podcast_archive.scan_podcast_archive(
        old_url,
        current_document=current,
        fetcher=fetcher,
        max_snapshots=20,
    )

    assert result.feed_urls == [old_url, new_url]
    assert result.snapshots_loaded == 1
    assert {episode.guid for episode in result.episodes} == {"ep-1", "ep-2", "ep-3"}
    current_ep = next(episode for episode in result.episodes if episode.guid == "ep-3")
    assert current_ep.media_url == "https://new.example/3.mp3"

    recovered = podcast_archive.archive_only_entries(result, current)
    assert {entry.id for entry in recovered} == {"ep-1", "ep-2"}


def test_archive_episode_converts_to_local_provider_entry():
    episode = podcast_archive.ArchiveEpisode(
        title="Recovered",
        guid="old-guid",
        media_url="https://cdn.example/recovered.m4a",
        media_type="audio/mp4",
        published="2020-01-02 03:04:05",
        description="Archived notes",
    )
    entry = episode.as_feedparser_entry()

    assert entry.id == "old-guid"
    assert entry.enclosures[0].href == "https://cdn.example/recovered.m4a"
    assert entry.enclosures[0].type == "audio/mp4"


def test_archive_scan_state_claims_once_and_respects_retry_window(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "archive-state.db"))
    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            ("feed-1", "https://example.com/feed.xml", "Show", "Uncategorized"),
        )
        conn.commit()
    finally:
        conn.close()

    assert db.claim_podcast_archive_scan("feed-1", "https://example.com/feed.xml", now=1000)
    assert not db.claim_podcast_archive_scan("feed-1", "https://example.com/feed.xml", now=1001)

    db.finish_podcast_archive_scan(
        "feed-1", snapshot_count=12, episode_count=300, now=1100
    )
    state = db.get_podcast_archive_state("feed-1")
    assert state["status"] == "complete"
    assert state["snapshot_count"] == 12
    assert state["episode_count"] == 300
    assert not db.claim_podcast_archive_scan(
        "feed-1", "https://example.com/feed.xml", now=1200, rescan_seconds=3600
    )
    assert db.claim_podcast_archive_scan(
        "feed-1", "https://example.com/feed.xml", now=5000, rescan_seconds=3600
    )


def test_local_podcast_refresh_inserts_recovered_history_automatically(tmp_path, monkeypatch):
    feed_id = "automatic-podcast"
    feed_url = "https://example.com/podcast.xml"
    current = _rss([
        {"guid": "current", "title": "Current episode", "media": "https://cdn.example/current.mp3"},
    ])
    _title, current_episodes, _lineage = podcast_archive.parse_feed_document(current, feed_url)
    archived = podcast_archive.ArchiveEpisode(
        title="Recovered old episode",
        guid="archived",
        media_url="https://cdn.example/archived.mp3",
        media_type="audio/mpeg",
        published="2019-01-02 03:04:05",
        source_feed_url=feed_url,
    )
    archived.identity_keys = podcast_archive._episode_identity_keys(archived)
    archive_result = podcast_archive.PodcastArchiveResult(
        feed_title="Long Running Show",
        episodes=[*current_episodes, archived],
        feed_urls=[feed_url],
        snapshots_found=1,
        snapshots_loaded=1,
    )

    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "automatic.db"))
    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (feed_id, feed_url, "Long Running Show", "Uncategorized"),
        )
        conn.commit()
    finally:
        conn.close()

    response = MagicMock()
    response.status_code = 200
    response.content = current
    response.text = current.decode()
    response.headers = {}
    response.url = feed_url
    response.raise_for_status.return_value = None
    monkeypatch.setattr(utils, "safe_requests_get", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        podcast_archive,
        "scan_podcast_archive",
        lambda *_args, **_kwargs: archive_result,
    )
    queued_jobs = []
    monkeypatch.setattr(podcast_archive, "enqueue_archive_job", queued_jobs.append)

    provider = LocalProvider({
        "feed_timeout_seconds": 1,
        "feed_retry_attempts": 0,
        "podcast_archive_enabled": True,
    })
    progress = []
    assert provider.refresh_feed(feed_id, progress_cb=progress.append)
    assert {article.id for article in provider.get_articles(feed_id)} == {"current"}
    assert len(queued_jobs) == 1

    # The expensive Wayback walk starts only after the live episode committed.
    queued_jobs[0]()

    articles = provider.get_articles(feed_id)
    assert {article.id for article in articles} == {"current", "archived"}
    assert db.get_podcast_archive_state(feed_id)["status"] == "complete"
    # Only the genuinely current item is announced as new; recovering years of
    # history must not produce an alert storm.
    assert sum(int(state.get("new_items") or 0) for state in progress) == 1
