import os
import sys
import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import discovery


class YouTubeSearchConversionTests(unittest.TestCase):
    def test_get_ytdlp_feed_url_prefers_playlist_when_watch_url_has_list_param(self) -> None:
        out = discovery.get_ytdlp_feed_url(
            "https://www.youtube.com/watch?v=nO3PKBfEfLs&list=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU"
        )
        self.assertEqual(
            out,
            "https://www.youtube.com/feeds/videos.xml?playlist_id=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU",
        )

    def test_discover_feed_handles_youtube_watch_playlist_url(self) -> None:
        out = discovery.discover_feed(
            "https://www.youtube.com/watch?v=nO3PKBfEfLs&list=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU"
        )
        self.assertEqual(
            out,
            "https://www.youtube.com/feeds/videos.xml?playlist_id=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU",
        )

    def test_discover_feeds_handles_youtube_watch_playlist_url(self) -> None:
        out = discovery.discover_feeds(
            "https://www.youtube.com/watch?v=nO3PKBfEfLs&list=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU"
        )
        self.assertEqual(
            out,
            ["https://www.youtube.com/feeds/videos.xml?playlist_id=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU"],
        )

    def test_youtube_search_entries_to_channel_feeds_dedupes_video_hits(self) -> None:
        entries = [
            {
                "id": "UC4gD0czpXVv_LpADTSU624g",
                "title": "Clownfish TV",
                "channel": "Clownfish TV",
                "channel_id": "UC4gD0czpXVv_LpADTSU624g",
                "channel_url": "https://www.youtube.com/channel/UC4gD0czpXVv_LpADTSU624g",
                "uploader_id": "@ClownfishTV",
                "url": "https://www.youtube.com/channel/UC4gD0czpXVv_LpADTSU624g",
            },
            {
                "id": "video-1",
                "title": "Some video",
                "channel": "Clownfish TV",
                "channel_id": "UC4gD0czpXVv_LpADTSU624g",
                "channel_url": "https://www.youtube.com/channel/UC4gD0czpXVv_LpADTSU624g",
                "uploader_id": "@ClownfishTV",
                "url": "https://www.youtube.com/watch?v=abc",
            },
        ]

        out = discovery._youtube_search_entries_to_channel_feeds(entries, limit=10)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Clownfish TV")
        self.assertEqual(
            out[0]["url"],
            "https://www.youtube.com/feeds/videos.xml?channel_id=UC4gD0czpXVv_LpADTSU624g",
        )
        self.assertIn("@ClownfishTV", out[0]["detail"])

    def test_youtube_search_entries_to_channel_feeds_uses_channel_url_fallback(self) -> None:
        entries = [
            {
                "title": "Example Creator",
                "channel": "Example Creator",
                "channel_url": "https://www.youtube.com/@ExampleCreator",
                "uploader_id": "@ExampleCreator",
                "url": "https://www.youtube.com/watch?v=xyz",
            }
        ]

        with patch(
            "core.discovery.get_ytdlp_feed_url",
            return_value="https://www.youtube.com/feeds/videos.xml?channel_id=UCEXAMPLE123",
        ) as mock_get_feed:
            out = discovery._youtube_search_entries_to_channel_feeds(entries, limit=10)

        mock_get_feed.assert_called_once_with("https://www.youtube.com/@ExampleCreator")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Example Creator")
        self.assertEqual(out[0]["url"], "https://www.youtube.com/feeds/videos.xml?channel_id=UCEXAMPLE123")

    def test_youtube_search_entries_to_playlist_feeds_converts_results(self) -> None:
        entries = [
            {
                "id": "PL1234567890ABCDEF",
                "title": "Example Playlist",
                "channel": "Example Creator",
                "url": "https://www.youtube.com/playlist?list=PL1234567890ABCDEF",
            },
            {
                "id": "PL1234567890ABCDEF",
                "title": "Duplicate Playlist Hit",
                "uploader": "Example Creator",
                "url": "https://www.youtube.com/watch?v=abc&list=PL1234567890ABCDEF",
            },
        ]

        out = discovery._youtube_search_entries_to_playlist_feeds(entries, limit=10)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Example Playlist")
        self.assertEqual(
            out[0]["url"],
            "https://www.youtube.com/feeds/videos.xml?playlist_id=PL1234567890ABCDEF",
        )
        self.assertIn("YouTube playlist", out[0]["detail"])

    def test_search_youtube_channels_accepts_zero_returncode(self) -> None:
        payload = {
            "entries": [
                {
                    "channel": "Clownfish TV",
                    "channel_id": "UC4gD0czpXVv_LpADTSU624g",
                    "channel_url": "https://www.youtube.com/channel/UC4gD0czpXVv_LpADTSU624g",
                    "uploader_id": "@ClownfishTV",
                    "url": "https://www.youtube.com/watch?v=abc",
                }
            ]
        }
        fake_proc = SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode("utf-8"))

        with patch("core.discovery.subprocess.run", return_value=fake_proc):
            results = discovery.search_youtube_channels("clownfishtv", limit=5, timeout=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Clownfish TV")
        self.assertIn("channel_id=UC4gD0czpXVv_LpADTSU624g", results[0]["url"])

    def test_search_youtube_playlists_accepts_zero_returncode(self) -> None:
        payload = {
            "entries": [
                {
                    "id": "PL1234567890ABCDEF",
                    "title": "Example Playlist",
                    "channel": "Example Creator",
                    "url": "https://www.youtube.com/playlist?list=PL1234567890ABCDEF",
                }
            ]
        }
        fake_proc = SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode("utf-8"))

        with patch("core.discovery.subprocess.run", return_value=fake_proc):
            results = discovery._search_youtube_playlists("example", limit=5, timeout=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Example Playlist")
        self.assertIn("playlist_id=PL1234567890ABCDEF", results[0]["url"])

    def test_search_youtube_feeds_combines_channels_and_playlists(self) -> None:
        channel_results = [
            {
                "title": "Example Creator",
                "detail": "YouTube channel (@ExampleCreator)",
                "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCEXAMPLE123",
            }
        ]
        playlist_results = [
            {
                "title": "Example Playlist",
                "detail": "YouTube playlist (Example Creator)",
                "url": "https://www.youtube.com/feeds/videos.xml?playlist_id=PL1234567890ABCDEF",
            }
        ]

        with patch("core.discovery.search_youtube_channels", return_value=channel_results), patch(
            "core.discovery._search_youtube_playlists", return_value=playlist_results
        ):
            results = discovery.search_youtube_feeds("example", limit=12, timeout=10)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["url"], channel_results[0]["url"])
        self.assertEqual(results[1]["url"], playlist_results[0]["url"])


if __name__ == "__main__":
    unittest.main()
