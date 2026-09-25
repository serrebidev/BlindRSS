# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for subscribing to YouTube and Rumble search results as feeds."""

import json
import os
import sys
import tempfile
import types
import unittest
import subprocess
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.discovery as discovery
import core.rumble as rumble


class YoutubeSearchDetectionTests(unittest.TestCase):
    def test_detects_search_url(self):
        self.assertTrue(discovery.is_youtube_search_url("https://www.youtube.com/results?search_query=clownfishtv"))
        self.assertEqual(discovery.youtube_search_query("https://www.youtube.com/results?search_query=clownfishtv"), "clownfishtv")

    def test_non_search_urls(self):
        self.assertFalse(discovery.is_youtube_search_url("https://www.youtube.com/watch?v=abc"))
        self.assertFalse(discovery.is_youtube_search_url("https://www.youtube.com/@ClownfishTV"))
        self.assertFalse(discovery.is_youtube_search_url("https://rumble.com/c/ClownfishTV"))
        self.assertFalse(discovery.is_youtube_search_url("https://notyoutube.com/results?search_query=test"))
        self.assertIsNone(discovery.youtube_search_query("https://www.youtube.com/watch?q=not-a-search"))

    def test_search_url_has_no_native_feed(self):
        # Must stay as-is so the search-listing path runs on refresh.
        self.assertIsNone(discovery.get_ytdlp_feed_url("https://www.youtube.com/results?search_query=clownfishtv"))


class FetchYoutubeSearchItemsTests(unittest.TestCase):
    def test_parses_ytdlp_flat_dump(self):
        lines = "\n".join(
            json.dumps(e)
            for e in [
                {"id": "vid1", "title": "Newest Video", "uploader": "Clownfish TV", "upload_date": "20260524"},
                {"id": "vid2", "title": "Older Video", "channel": "Clownfish TV", "timestamp": 1_700_000_000},
                {"id": "vid2", "title": "Duplicate Video"},
                {"id": "PL123", "title": "Playlist", "_type": "playlist"},
                {"title": "no id, skipped"},
            ]
        )

        def fake_run(cmd, **kwargs):
            # Confirm we request a date-sorted search (sp=CAI%3D) for the query.
            joined = " ".join(str(a) for a in cmd)
            assert "sp=CAI%3D" in joined, cmd
            assert "search_query=clownfishtv" in joined, cmd
            return types.SimpleNamespace(returncode=0, stdout=lines, stderr="")

        orig = discovery.subprocess.run
        discovery.subprocess.run = fake_run
        try:
            title, items = discovery.fetch_youtube_search_items("clownfishtv", max_items=10)
        finally:
            discovery.subprocess.run = orig

        self.assertEqual(title, "YouTube: clownfishtv")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].url, "https://www.youtube.com/watch?v=vid1")
        self.assertEqual(items[0].title, "Newest Video")
        self.assertEqual(items[0].published, "2026-05-24")
        self.assertEqual(items[0].id, "https://www.youtube.com/watch?v=vid1")
        self.assertEqual(items[1].published, "2023-11-14")

    def test_empty_query(self):
        title, items = discovery.fetch_youtube_search_items("", max_items=10)
        self.assertIsNone(title)
        self.assertEqual(items, [])

    def test_public_channel_does_not_wait_for_configured_cookies(self):
        def fake_run(cmd, **kwargs):
            if "--cookies" in cmd or "--cookies-from-browser" in cmd:
                raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
            self.assertIn("--ignore-config", cmd)
            return types.SimpleNamespace(
                returncode=0, stdout=json.dumps({"id": "public", "title": "Public video"}), stderr=""
            )

        with patch("core.discovery.os.path.isfile", return_value=True), patch(
            "core.discovery.get_ytdlp_cookie_sources", return_value=[("firefox",)]
        ) as cookie_sources, patch("core.discovery.subprocess.run", side_effect=fake_run), patch(
            "core.discovery.time.monotonic", side_effect=[100.0, 100.0, 111.0, 111.0]
        ):
            _title, items = discovery.fetch_youtube_channel_items(
                "UCfKWQxY7aTUw7YTrHY4apTw", cookiefile="cookies.txt", timeout_s=10
            )
        self.assertEqual([item.title for item in items], ["Public video"])
        cookie_sources.assert_not_called()

    def test_configured_cookies_still_recover_authenticated_listing(self):
        def fake_run(cmd, **kwargs):
            if "--cookies" in cmd:
                self.assertEqual(cmd[cmd.index("--cookies") + 1], "cookies.txt")
                return types.SimpleNamespace(returncode=0, stdout=json.dumps({"id": "private"}), stderr="")
            return types.SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Sign in required")

        with patch("core.discovery.os.path.isfile", return_value=True), patch(
            "core.discovery.get_ytdlp_cookie_sources", return_value=[]
        ), patch("core.discovery.subprocess.run", side_effect=fake_run):
            _title, items = discovery.fetch_youtube_channel_items(
                "UCfKWQxY7aTUw7YTrHY4apTw", cookiefile="cookies.txt"
            )
        self.assertEqual([item.url for item in items], ["https://www.youtube.com/watch?v=private"])

    def test_failure_preserves_ytdlp_diagnostic(self):
        def fake_run(cmd, **kwargs):
            stderr = "ERROR: Unable to connect to proxy" if kwargs["stderr"] == subprocess.PIPE else None
            return types.SimpleNamespace(returncode=1, stdout="", stderr=stderr)

        with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]), patch(
            "core.discovery.subprocess.run", side_effect=fake_run
        ):
            with self.assertRaisesRegex(RuntimeError, "Unable to connect to proxy"):
                discovery.fetch_youtube_channel_items("UCfKWQxY7aTUw7YTrHY4apTw")

    def test_successful_empty_result_is_not_reported_as_failure(self):
        calls = {"count": 0}

        def fake_run(_cmd, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                return types.SimpleNamespace(returncode=0, stdout="")
            return types.SimpleNamespace(returncode=1, stdout="")

        with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[("firefox",)]), patch(
            "core.discovery.subprocess.run",
            side_effect=fake_run,
        ):
            title, items = discovery.fetch_youtube_search_items("nothing here", timeout_s=10)

        self.assertEqual(title, "YouTube: nothing here")
        self.assertEqual(items, [])

    def test_all_failed_attempts_raise_for_provider_retry(self):
        with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[("firefox",)]), patch(
            "core.discovery.subprocess.run",
            return_value=types.SimpleNamespace(returncode=1, stdout=""),
        ):
            with self.assertRaisesRegex(RuntimeError, "YouTube search failed"):
                discovery.fetch_youtube_search_items("retry me", timeout_s=10)

    def test_cookie_attempts_share_one_total_deadline(self):
        timeouts = []

        def fake_run(_cmd, **kwargs):
            timeouts.append(kwargs["timeout"])
            return types.SimpleNamespace(returncode=1, stdout="")

        with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[("firefox",)]), patch(
            "core.discovery.time.monotonic",
            side_effect=[100.0, 100.0, 102.0],
        ), patch("core.discovery.subprocess.run", side_effect=fake_run):
            with self.assertRaises(RuntimeError):
                discovery.fetch_youtube_search_items("deadline", timeout_s=10)

        self.assertEqual(timeouts, [10.0, 8.0])

    def test_timeout_attempts_raise_for_provider_retry(self):
        with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]), patch(
            "core.discovery.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=1),
        ):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                discovery.fetch_youtube_search_items("timeout", timeout_s=10)

    def test_completed_entries_survive_timeout_or_later_listing_error(self):
        output = json.dumps({"id": "complete", "title": "Already fetched"}) + '\n{"id": "incomplete'
        for timed_out in (True, False):
            with self.subTest(timed_out=timed_out):
                def fake_run(cmd, **kwargs):
                    if timed_out:
                        raise subprocess.TimeoutExpired(cmd, 10, output=output.encode("utf-8"))
                    return types.SimpleNamespace(returncode=1, stdout=output, stderr="ERROR: Next page failed")

                with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]), patch(
                    "core.discovery.subprocess.run", side_effect=fake_run
                ):
                    _title, items = discovery.fetch_youtube_channel_items("UCfKWQxY7aTUw7YTrHY4apTw")
                self.assertEqual([item.title for item in items], ["Already fetched"])

    def test_timeout_keeps_diagnostic_before_retries(self):
        with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]), patch(
            "core.discovery.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                ["yt-dlp"], 10, stderr=b"ERROR: Connection refused; retrying"
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "timed out.*Connection refused"):
                discovery.fetch_youtube_channel_items("UCfKWQxY7aTUw7YTrHY4apTw")


class RumbleSearchNormalizationTests(unittest.TestCase):
    def test_search_url_sorts_by_date(self):
        out = rumble.normalize_rumble_feed_url("https://rumble.com/search/all?q=technology")
        self.assertIn("q=technology", out)
        self.assertIn("sort=date", out)

    def test_existing_sort_preserved(self):
        out = rumble.normalize_rumble_feed_url("https://rumble.com/search/all?q=technology&sort=views")
        self.assertIn("sort=views", out)
        self.assertNotIn("sort=date", out)

    def test_channel_still_normalizes_to_videos(self):
        out = rumble.normalize_rumble_feed_url("https://rumble.com/c/ClownfishTV")
        self.assertTrue(out.endswith("/c/ClownfishTV/videos"))


class YoutubeSearchRefreshIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import core.db as db
        self.db = db
        self.orig = db.DB_FILE
        db.DB_FILE = os.path.join(self.tmp.name, "rss.db")
        db.init_db()

        from providers.local import LocalProvider
        self.provider = LocalProvider({"providers": {"local": {}}, "feed_timeout_seconds": 5, "feed_retry_attempts": 0})

        self.feed_id = "yt-search-feed"
        self.feed_url = "https://www.youtube.com/results?search_query=clownfishtv"
        conn = db.get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_id, self.feed_url, "YouTube: clownfishtv", "Tests", ""),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db.DB_FILE = self.orig
        self.tmp.cleanup()

    def test_refresh_inserts_video_articles(self):
        items = [
            discovery.YoutubeSearchItem(url="https://www.youtube.com/watch?v=vid1", title="Newest", author="Clownfish TV"),
            discovery.YoutubeSearchItem(url="https://www.youtube.com/watch?v=vid2", title="Older", author="Clownfish TV"),
        ]
        orig = discovery.fetch_youtube_search_items
        discovery.fetch_youtube_search_items = lambda q, max_items=30, timeout_s=30.0, cookiefile=None: ("YouTube: clownfishtv", items)
        try:
            self.provider.refresh(force=True)
        finally:
            discovery.fetch_youtube_search_items = orig

        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("SELECT title, url, media_url, media_type FROM articles WHERE feed_id = ? ORDER BY url", (self.feed_id,))
        rows = c.fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        for title, url, media_url, media_type in rows:
            self.assertTrue(url.startswith("https://www.youtube.com/watch?v="))
            self.assertEqual(media_url, url)
            self.assertEqual(media_type, "video/youtube")

    def test_overlapping_search_feeds_keep_separate_articles_and_refresh_metadata(self):
        second_feed_id = "yt-search-feed-two"
        conn = self.db.get_connection()
        conn.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (
                second_feed_id,
                "https://www.youtube.com/results?search_query=animation",
                "YouTube: animation",
                "Tests",
                "",
            ),
        )
        conn.commit()
        conn.close()

        calls = {"count": 0}

        def fake_fetch(query, max_items=30, timeout_s=30.0, cookiefile=None):
            calls["count"] += 1
            title = "Updated title" if calls["count"] > 2 else "Original title"
            return (
                f"YouTube: {query}",
                [
                    discovery.YoutubeSearchItem(
                        url="https://www.youtube.com/watch?v=shared",
                        title=title,
                        author="Shared Creator",
                    )
                ],
            )

        orig = discovery.fetch_youtube_search_items
        discovery.fetch_youtube_search_items = fake_fetch
        try:
            self.provider.refresh(force=True)
            self.provider.refresh(force=True)
        finally:
            discovery.fetch_youtube_search_items = orig

        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT feed_id, title FROM articles WHERE url = ? ORDER BY feed_id",
            ("https://www.youtube.com/watch?v=shared",),
        ).fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual({row[0] for row in rows}, {self.feed_id, second_feed_id})
        self.assertTrue(any(row[1] == "Updated title" for row in rows))


class YoutubeChannelFeedFallbackTests(YoutubeSearchRefreshIntegrationTests):
    """Issue #107: YouTube's channel RSS answers 404/500 at random."""

    def setUp(self):
        super().setUp()
        self.feed_url = "https://www.youtube.com/feeds/videos.xml?channel_id=UCNkETBwkARrGDx-G7P-jLJg"
        conn = self.db.get_connection()
        conn.execute("UPDATE feeds SET url = ?, title = ? WHERE id = ?", (self.feed_url, self.feed_url, self.feed_id))
        conn.commit()
        conn.close()
        # These tests cover the RSS failure fallback, not the issue #109 backfill.
        self.db.mark_youtube_history(self.feed_id, done=True)

    test_refresh_inserts_video_articles = None
    test_overlapping_search_feeds_keep_separate_articles_and_refresh_metadata = None

    def test_channel_id_detection(self):
        self.assertEqual(discovery.youtube_channel_id_from_feed_url(self.feed_url), "UCNkETBwkARrGDx-G7P-jLJg")
        self.assertIsNone(discovery.youtube_channel_id_from_feed_url("https://www.youtube.com/feeds/videos.xml?playlist_id=PL1"))
        self.assertIsNone(discovery.youtube_channel_id_from_feed_url("https://example.com/feeds/videos.xml?channel_id=UCNkETBwkARrGDx-G7P-jLJg"))

    def test_failed_channel_feed_falls_back_to_ytdlp_listing(self):
        import requests

        resp = requests.Response()
        resp.status_code = 500
        resp.url = self.feed_url
        items = [
            discovery.YoutubeSearchItem(
                url="https://www.youtube.com/watch?v=1Cl8fSsiMJ8", title="Family Feud", author="BUZZR", published="2026-09-23"
            )
        ]
        seen = []

        def fake_channel(channel_id, max_items=30, timeout_s=30.0, cookiefile=None):
            seen.append(channel_id)
            return ("BUZZR", items)

        with patch("providers.local.utils.safe_requests_get", return_value=resp), patch.object(
            discovery, "fetch_youtube_channel_items", fake_channel
        ):
            self.provider.refresh(force=True)

        conn = self.db.get_connection()
        rows = conn.execute("SELECT id, media_type FROM articles WHERE feed_id = ?", (self.feed_id,)).fetchall()
        title = conn.execute("SELECT title FROM feeds WHERE id = ?", (self.feed_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(seen, ["UCNkETBwkARrGDx-G7P-jLJg"])
        # The native RSS entry id, so a recovered feed does not duplicate it.
        self.assertEqual(rows, [("yt:video:1Cl8fSsiMJ8", "video/youtube")])
        self.assertEqual(title, "BUZZR")

    def test_fallback_failure_is_saved_in_feed_errors(self):
        import requests

        resp = requests.Response()
        resp.status_code = 404
        resp.url = self.feed_url
        with patch("providers.local.utils.safe_requests_get", return_value=resp), patch.object(
            discovery, "fetch_youtube_channel_items", side_effect=RuntimeError("yt-dlp listing timed out")
        ):
            self.provider.refresh(force=True)

        errors = self.db.get_feed_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("404", errors[0]["last_error"])
        self.assertIn("yt-dlp listing timed out", errors[0]["last_error"])


class YoutubeChannelHistoryTests(YoutubeChannelFeedFallbackTests):
    """Issue #109: channel RSS has only 15 videos; list the whole Videos tab once."""

    test_failed_channel_feed_falls_back_to_ytdlp_listing = None
    test_fallback_failure_is_saved_in_feed_errors = None

    def setUp(self):
        super().setUp()
        conn = self.db.get_connection()
        conn.execute("DELETE FROM youtube_history_state")
        conn.commit()
        conn.close()

    def _refresh(self, fake_channel):
        import requests

        resp = requests.Response()
        resp.status_code = 304
        resp.url = self.feed_url
        states = []
        with patch("providers.local.utils.safe_requests_get", return_value=resp), patch.object(
            discovery, "fetch_youtube_channel_items", fake_channel
        ):
            self.provider.refresh(progress_cb=states.append, force=True)
        return states

    def test_history_listed_once_without_notifications(self):
        calls = []

        def fake_channel(channel_id, max_items=30, timeout_s=30.0, cookiefile=None):
            calls.append(max_items)
            return ("Chan", [
                discovery.YoutubeSearchItem(
                    url=f"https://www.youtube.com/watch?v=vid{i:08d}", title=f"Old {i}", author="Chan", published="2024-01-01"
                )
                for i in range(150)
            ])

        states = self._refresh(fake_channel)
        self._refresh(fake_channel)

        conn = self.db.get_connection()
        count = conn.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(count, 150)
        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0], 100)
        mine = [s for s in states if s.get("id") == self.feed_id]
        self.assertTrue(mine and mine[-1]["content_changed"])
        self.assertEqual(mine[-1]["new_items"], 0)

    def test_failed_history_listing_is_retried_later(self):
        def failing(*_args, **_kwargs):
            raise RuntimeError("offline")

        self._refresh(failing)
        self.assertFalse(self.db.youtube_history_due(self.feed_id))
        self.assertTrue(self.db.youtube_history_due(self.feed_id, retry_after_s=0))

    def test_channel_listing_is_not_capped_at_100(self):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["end"] = cmd[cmd.index("--playlist-end") + 1]
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({"id": "x"}), stderr="")

        with patch("core.discovery.get_ytdlp_cookie_sources", return_value=[]), patch(
            "core.discovery.subprocess.run", side_effect=fake_run
        ):
            discovery.fetch_youtube_channel_items("UCNkETBwkARrGDx-G7P-jLJg", max_items=5000)
        self.assertEqual(seen["end"], "5000")


if __name__ == "__main__":
    unittest.main()
