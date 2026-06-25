import os
import sys
import unittest
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import discovery


class YouTubeSearchConversionTests(unittest.TestCase):
    def test_youtube_search_query_variants_build_token_drop_fallbacks(self) -> None:
        variants = discovery._youtube_search_query_variants("Let's Play RimWorld by Liam Urvin", max_variants=6)
        self.assertGreaterEqual(len(variants), 2)
        self.assertEqual(variants[0], "Let's Play RimWorld by Liam Urvin")
        self.assertIn("let's play rimworld by liam", variants)

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

    def test_youtube_hostname_matching_rejects_lookalike_domains(self) -> None:
        self.assertIsNone(discovery.get_ytdlp_feed_url("https://notyoutube.com/channel/UCFAKE"))
        self.assertEqual(discovery._youtube_playlist_id_from_url("https://youtube.com.evil.test/?list=PLFAKE"), "")
        self.assertEqual(discovery._youtube_handle_from_url("https://notyoutube.com/@Fake"), "")
        self.assertFalse(discovery._supports_quick_title_resolution("https://youtube.com.evil.test/watch?v=fake"))

    def test_youtube_hostname_matching_accepts_subdomains_and_ports(self) -> None:
        self.assertTrue(
            discovery.is_youtube_search_url(
                "https://www.youtube.com:8443/results?search_query=accessible"
            )
        )
        self.assertEqual(
            discovery._youtube_playlist_id_from_url(
                "https://m.youtube.com:8443/watch?v=abc&list=PLREAL"
            ),
            "PLREAL",
        )

    def test_handle_resolution_preserves_cookie_profile_and_falls_back(self) -> None:
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            if "--cookies-from-browser" not in cmd:
                return SimpleNamespace(returncode=1, stdout="")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"_type": "channel", "id": "UCREAL"}),
            )

        with patch(
            "core.discovery.get_ytdlp_cookie_sources",
            return_value=[("firefox", r"C:\Profiles\Accessible")],
        ), patch("core.discovery.subprocess.run", side_effect=fake_run):
            out = discovery.get_ytdlp_feed_url("https://www.youtube.com/@Example")

        self.assertEqual(out, "https://www.youtube.com/feeds/videos.xml?channel_id=UCREAL")
        self.assertNotIn("--cookies-from-browser", calls[0])
        self.assertEqual(calls[1][calls[1].index("--cookies-from-browser") + 1], r"firefox:C:\Profiles\Accessible")
        self.assertEqual(calls[1][-1], "https://www.youtube.com/@Example")

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

    def test_youtube_search_entries_to_channel_feeds_sorts_by_play_count(self) -> None:
        entries = [
            {
                "title": "Smaller channel",
                "channel": "Smaller channel",
                "channel_id": "UC0001",
                "channel_url": "https://www.youtube.com/channel/UC0001",
                "uploader_id": "@small",
                "url": "https://www.youtube.com/watch?v=small1",
                "view_count": 1200,
            },
            {
                "title": "Bigger channel",
                "channel": "Bigger channel",
                "channel_id": "UC0002",
                "channel_url": "https://www.youtube.com/channel/UC0002",
                "uploader_id": "@big",
                "url": "https://www.youtube.com/watch?v=big1",
                "view_count": 980000,
            },
        ]

        out = discovery._youtube_search_entries_to_channel_feeds(entries, limit=10)

        self.assertEqual(len(out), 2)
        self.assertIn("UC0002", out[0]["url"])
        self.assertIn("980,000 plays", out[0]["detail"])

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
        self.assertIn("Example Creator", out[0]["detail"])

    def test_youtube_search_entries_to_playlist_feeds_includes_channel_handle_from_uploader_id(self) -> None:
        entries = [
            {
                "id": "PLXYZ",
                "title": "let's Play RimWorld",
                "channel": "Liam Erven",
                "uploader_id": "liamerven",
                "url": "https://www.youtube.com/playlist?list=PLXYZ",
            }
        ]

        out = discovery._youtube_search_entries_to_playlist_feeds(entries, limit=10)

        self.assertEqual(len(out), 1)
        self.assertIn("Liam Erven", out[0]["detail"])
        self.assertIn("@liamerven", out[0]["detail"])

    def test_youtube_search_entries_to_playlist_feeds_handles_channel_url_fallback(self) -> None:
        entries = [
            {
                "id": "PLZZZ",
                "title": "Example Playlist",
                "channel_url": "https://www.youtube.com/@examplechannel",
                "url": "https://www.youtube.com/playlist?list=PLZZZ",
            }
        ]

        out = discovery._youtube_search_entries_to_playlist_feeds(entries, limit=10)

        self.assertEqual(len(out), 1)
        self.assertIn("@examplechannel", out[0]["detail"])

    def test_youtube_search_entries_to_playlist_feeds_uses_oembed_owner_fallback(self) -> None:
        entries = [
            {
                "id": "PLFALLBACK",
                "title": "let's Play RimWorld",
                "url": "https://www.youtube.com/playlist?list=PLFALLBACK",
            }
        ]

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "title": "let's Play RimWorld",
                    "author_name": "Liam Erven",
                    "author_url": "/@liamerven",
                }

        with patch("core.discovery.utils.safe_requests_get", return_value=_Resp()):
            out = discovery._youtube_search_entries_to_playlist_feeds(entries, limit=10)

        self.assertEqual(len(out), 1)
        self.assertIn("Liam Erven", out[0]["detail"])
        self.assertIn("@liamerven", out[0]["detail"])

    def test_youtube_search_entries_to_playlist_feeds_caps_oembed_owner_fallback_lookups(self) -> None:
        entries = [
            {
                "id": f"PLNOOWNER{idx:03d}",
                "title": f"Playlist {idx}",
                "url": f"https://www.youtube.com/playlist?list=PLNOOWNER{idx:03d}",
            }
            for idx in range(10)
        ]

        with patch("core.discovery._youtube_owner_label_from_oembed", return_value="") as mock_oembed:
            out = discovery._youtube_search_entries_to_playlist_feeds(entries, limit=10, query="rimworld")

        self.assertEqual(len(out), 10)
        self.assertEqual(
            mock_oembed.call_count,
            min(len(entries), discovery._YOUTUBE_PLAYLIST_OEMBED_LOOKUP_LIMIT),
        )

    def test_youtube_search_entries_to_playlist_feeds_prioritizes_query_match(self) -> None:
        entries = [
            {
                "id": "PLNOTMATCH",
                "title": "RimWorld Random Playlist",
                "url": "https://www.youtube.com/playlist?list=PLNOTMATCH",
            },
            {
                "id": "PLMATCH",
                "title": "let's Play RimWorld",
                "url": "https://www.youtube.com/playlist?list=PLMATCH",
            },
        ]

        out = discovery._youtube_search_entries_to_playlist_feeds(
            entries,
            limit=10,
            query="lets play rimworld",
        )

        self.assertEqual(len(out), 2)
        self.assertIn("PLMATCH", out[0]["url"])

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
        self.assertEqual(results[0]["url"], playlist_results[0]["url"])
        self.assertEqual(results[1]["url"], channel_results[0]["url"])

    def test_search_youtube_feeds_can_fill_up_to_100_results(self) -> None:
        channel_results = [
            {
                "title": f"Channel {idx}",
                "detail": "YouTube channel",
                "url": f"https://www.youtube.com/feeds/videos.xml?channel_id=UC{idx:04d}",
            }
            for idx in range(60)
        ]
        playlist_results = [
            {
                "title": f"Playlist {idx}",
                "detail": "YouTube playlist",
                "url": f"https://www.youtube.com/feeds/videos.xml?playlist_id=PL{idx:04d}",
            }
            for idx in range(60)
        ]

        with patch("core.discovery.search_youtube_channels", return_value=channel_results) as mock_channels, patch(
            "core.discovery._search_youtube_playlists", return_value=playlist_results
        ) as mock_playlists:
            results = discovery.search_youtube_feeds("example", limit=100, timeout=10)

        expected_channel_limit = max(
            1,
            min(100, int(round(100 * float(discovery._YOUTUBE_FEED_CHANNEL_LIMIT_RATIO)))),
        )
        mock_channels.assert_called_once_with("example", limit=expected_channel_limit, timeout=10)
        mock_playlists.assert_called_once_with("example", limit=100, timeout=10)
        self.assertEqual(len(results), 100)

    def test_search_youtube_feeds_retries_with_less_specific_query_when_initial_empty(self) -> None:
        fallback_query = "lets play rimworld liam"
        playlist_results = [
            {
                "title": "let's Play RimWorld",
                "detail": "YouTube playlist",
                "url": "https://www.youtube.com/feeds/videos.xml?playlist_id=PLdvFbaCu1RVgZtWw0_2PkdO-10zua4mLM",
            }
        ]

        def _fake_search_youtube_playlists(term: str, limit: int = 10, timeout: int = 15):
            if term == fallback_query:
                return list(playlist_results)
            return []

        with patch("core.discovery.search_youtube_channels", return_value=[]), patch(
            "core.discovery._search_youtube_playlists",
            side_effect=_fake_search_youtube_playlists,
        ) as mock_playlists:
            results = discovery.search_youtube_feeds("lets play rimworld liam urvin", limit=12, timeout=10)

        self.assertEqual(results, playlist_results)
        searched_terms = [call.args[0] for call in mock_playlists.call_args_list]
        self.assertIn("lets play rimworld liam urvin", searched_terms)
        self.assertIn(fallback_query, searched_terms)

    def test_search_youtube_feeds_uses_additional_variants_until_limit_is_filled(self) -> None:
        first_query = "lets play rimworld liam urvin"
        second_query = "lets play rimworld liam"
        first_batch = [
            {
                "title": f"First {idx}",
                "detail": "YouTube playlist",
                "url": f"https://www.youtube.com/feeds/videos.xml?playlist_id=PLFIRST{idx:04d}",
            }
            for idx in range(60)
        ]
        second_batch = [
            {
                "title": f"Second {idx}",
                "detail": "YouTube playlist",
                "url": f"https://www.youtube.com/feeds/videos.xml?playlist_id=PLSECOND{idx:04d}",
            }
            for idx in range(60)
        ]

        def _fake_search_youtube_playlists(term: str, limit: int = 10, timeout: int = 15):
            if term == first_query:
                return list(first_batch)
            if term == second_query:
                return list(second_batch)
            return []

        with patch("core.discovery.search_youtube_channels", return_value=[]), patch(
            "core.discovery._search_youtube_playlists",
            side_effect=_fake_search_youtube_playlists,
        ) as mock_playlists:
            results = discovery.search_youtube_feeds(first_query, limit=100, timeout=10)

        searched_terms = [call.args[0] for call in mock_playlists.call_args_list]
        self.assertIn(first_query, searched_terms)
        self.assertIn(second_query, searched_terms)
        self.assertEqual(len(results), 100)

    def test_search_youtube_feeds_runs_channel_and_playlist_searches_concurrently(self) -> None:
        call_times = {"channels_start": None, "playlists_start": None}

        def _fake_channels(term: str, limit: int = 10, timeout: int = 15):
            _ = (term, limit, timeout)
            call_times["channels_start"] = time.monotonic()
            time.sleep(0.25)
            return [
                {
                    "title": "Channel",
                    "detail": "YouTube channel",
                    "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCFAST",
                }
            ]

        def _fake_playlists(term: str, limit: int = 10, timeout: int = 15):
            _ = (term, limit, timeout)
            call_times["playlists_start"] = time.monotonic()
            time.sleep(0.25)
            return [
                {
                    "title": "Playlist",
                    "detail": "YouTube playlist",
                    "url": "https://www.youtube.com/feeds/videos.xml?playlist_id=PLFAST",
                }
            ]

        started = time.monotonic()
        with patch("core.discovery.search_youtube_channels", side_effect=_fake_channels), patch(
            "core.discovery._search_youtube_playlists", side_effect=_fake_playlists
        ):
            results = discovery.search_youtube_feeds("example", limit=2, timeout=10)
        elapsed = time.monotonic() - started

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(call_times["channels_start"])
        self.assertIsNotNone(call_times["playlists_start"])
        self.assertLess(abs(call_times["channels_start"] - call_times["playlists_start"]), 0.15)
        self.assertLess(elapsed, 0.4)

    def test_search_youtube_feeds_prioritizes_playlists_before_channels(self) -> None:
        channel_results = [
            {
                "title": "Some channel",
                "detail": "YouTube channel",
                "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCCHAN",
                "play_count": 4_500_000,
            }
        ]
        playlist_results = [
            {
                "title": "let's Play RimWorld",
                "detail": "YouTube playlist",
                "url": "https://www.youtube.com/feeds/videos.xml?playlist_id=PLdvFbaCu1RVgZtWw0_2PkdO-10zua4mLM",
                "play_count": 120_000,
            }
        ]

        with patch("core.discovery.search_youtube_channels", return_value=channel_results), patch(
            "core.discovery._search_youtube_playlists", return_value=playlist_results
        ):
            out = discovery.search_youtube_feeds("lets play rimworld", limit=1, timeout=10)

        self.assertEqual(len(out), 1)
        self.assertIn("playlist_id=PLdvFbaCu1RVgZtWw0_2PkdO-10zua4mLM", out[0]["url"])

    def test_search_youtube_feeds_reserves_playlist_headroom_when_channel_results_are_dense(self) -> None:
        channel_results = [
            {
                "title": f"Channel {idx}",
                "detail": "YouTube channel",
                "url": f"https://www.youtube.com/feeds/videos.xml?channel_id=UC{idx:03d}",
                "play_count": 10_000_000 - idx,
            }
            for idx in range(100)
        ]
        playlist_results = [
            {
                "title": "let's Play RimWorld",
                "detail": "YouTube playlist",
                "url": "https://www.youtube.com/feeds/videos.xml?playlist_id=PLdvFbaCu1RVgZtWw0_2PkdO-10zua4mLM",
                "play_count": None,
            }
        ] + [
            {
                "title": f"Playlist {idx}",
                "detail": "YouTube playlist",
                "url": f"https://www.youtube.com/feeds/videos.xml?playlist_id=PL{idx:03d}",
                "play_count": None,
            }
            for idx in range(1, 100)
        ]

        def _fake_channels(_term: str, limit: int = 10, timeout: int = 15):
            _ = timeout
            return list(channel_results[:limit])

        def _fake_playlists(_term: str, limit: int = 10, timeout: int = 15):
            _ = timeout
            return list(playlist_results[:limit])

        with patch("core.discovery.search_youtube_channels", side_effect=_fake_channels), patch(
            "core.discovery._search_youtube_playlists", side_effect=_fake_playlists
        ):
            out = discovery.search_youtube_feeds("lets play rimworld", limit=100, timeout=10)

        self.assertEqual(len(out), 100)
        self.assertTrue(any("playlist_id=PLdvFbaCu1RVgZtWw0_2PkdO-10zua4mLM" in str(it.get("url") or "") for it in out))


if __name__ == "__main__":
    unittest.main()
