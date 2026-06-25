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


if __name__ == "__main__":
    unittest.main()
