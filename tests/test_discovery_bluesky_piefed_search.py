import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import discovery


class BlueskyAndPieFedDiscoveryTests(unittest.TestCase):
    def test_bluesky_profile_url_to_rss(self) -> None:
        self.assertEqual(
            discovery._bluesky_profile_url_to_rss("https://bsky.app/profile/python.org"),
            "https://bsky.app/profile/python.org/rss",
        )

    def test_bluesky_post_url_converts_to_profile_rss(self) -> None:
        self.assertEqual(
            discovery._bluesky_profile_url_to_rss(
                "https://bsky.app/profile/python.org/post/3l5abcxyz"
            ),
            "https://bsky.app/profile/python.org/rss",
        )

    def test_get_social_feed_url_handles_bluesky_and_piefed(self) -> None:
        self.assertEqual(
            discovery.get_social_feed_url("https://bsky.app/profile/python.org"),
            "https://bsky.app/profile/python.org/rss",
        )
        self.assertEqual(
            discovery.get_social_feed_url("https://piefed.social/u/rimu"),
            "https://piefed.social/u/rimu/feed",
        )
        self.assertEqual(
            discovery.get_social_feed_url("https://piefed.social/c/flask"),
            "https://piefed.social/community/flask/feed",
        )

    def test_discover_feed_handles_bluesky_profile(self) -> None:
        self.assertEqual(
            discovery.discover_feed("https://bsky.app/profile/python.org"),
            "https://bsky.app/profile/python.org/rss",
        )

    def test_bluesky_search_response_to_feeds_includes_user_and_tag(self) -> None:
        payload = {
            "actors": [
                {
                    "handle": "python.org",
                    "displayName": "Python Software Foundation",
                    "did": "did:plc:sfrl4dmvaxeq4lqgaucotygo",
                }
            ]
        }

        out = discovery._bluesky_search_response_to_feeds(payload, query="python", limit=10)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["url"], "https://bsky.app/profile/python.org/rss")
        self.assertIn("Bluesky user", out[0]["detail"])
        self.assertEqual(out[1]["title"], "#python")
        self.assertIn("openrss.org", out[1]["url"])
        self.assertIn("Bluesky tag", out[1]["detail"])

    def test_search_bluesky_feeds_uses_public_actor_search(self) -> None:
        payload = {"actors": [{"handle": "python.org", "displayName": "Python"}]}
        fake_resp = SimpleNamespace(status_code=200, json=lambda: payload)

        with patch("core.discovery.utils.safe_requests_get", return_value=fake_resp) as mock_get:
            out = discovery.search_bluesky_feeds("python", limit=5, timeout=9)

        self.assertGreaterEqual(len(out), 1)
        self.assertEqual(out[0]["url"], "https://bsky.app/profile/python.org/rss")
        self.assertIn("app.bsky.actor.searchActorsTypeahead", mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs["timeout"], 9)
        self.assertEqual(mock_get.call_args.kwargs["params"]["q"], "python")

    def test_federated_actor_url_to_feed_url_handles_piefed_and_lemmy(self) -> None:
        self.assertEqual(
            discovery._federated_actor_url_to_feed_url("https://piefed.social/c/flask", source="piefed"),
            "https://piefed.social/community/flask/feed",
        )
        self.assertEqual(
            discovery._federated_actor_url_to_feed_url("https://piefed.social/u/rimu", source="piefed"),
            "https://piefed.social/u/rimu/feed",
        )
        self.assertEqual(
            discovery._federated_actor_url_to_feed_url("https://lemmy.world/c/news", source="piefed"),
            "https://lemmy.world/feeds/c/news.xml",
        )
        self.assertEqual(
            discovery._federated_actor_url_to_feed_url("https://lemmy.world/u/ruud", source="piefed"),
            "https://lemmy.world/feeds/u/ruud.xml",
        )

    def test_piefed_search_response_to_feeds_includes_community_and_user(self) -> None:
        payload = {
            "communities": [
                {
                    "community": {
                        "actor_id": "https://piefed.social/c/flask",
                        "title": "flask - the python framework",
                        "name": "flask",
                        "ap_domain": "piefed.social",
                    },
                    "counts": {"subscriptions_count": 12},
                }
            ],
            "users": [
                {
                    "person": {
                        "actor_id": "https://piefed.social/u/rimu",
                        "title": "Rimu",
                        "user_name": "rimu",
                    },
                    "counts": {"post_count": 7, "comment_count": 11},
                }
            ],
        }

        out = discovery._piefed_search_response_to_feeds(payload, limit=10)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["url"], "https://piefed.social/community/flask/feed")
        self.assertIn("PieFed community", out[0]["detail"])
        self.assertEqual(out[1]["url"], "https://piefed.social/u/rimu/feed")
        self.assertIn("Fediverse user", out[1]["detail"])

    def test_search_piefed_feeds_merges_communities_and_users(self) -> None:
        community_payload = {
            "communities": [
                {
                    "community": {
                        "actor_id": "https://piefed.social/c/flask",
                        "title": "Flask",
                        "name": "flask",
                        "ap_domain": "piefed.social",
                    },
                    "counts": {"subscriptions_count": 12},
                }
            ]
        }
        users_payload = {
            "users": [
                {
                    "person": {
                        "actor_id": "https://piefed.social/u/rimu",
                        "title": "Rimu",
                        "user_name": "rimu",
                    },
                    "counts": {"post_count": 0, "comment_count": 1},
                }
            ]
        }

        def fake_get(url, **kwargs):
            params = kwargs.get("params", {}) or {}
            t = params.get("type_")
            payload = community_payload if t == "Communities" else users_payload
            return SimpleNamespace(status_code=200, json=lambda payload=payload: payload)

        with patch("core.discovery.utils.safe_requests_get", side_effect=fake_get) as mock_get:
            out = discovery.search_piefed_feeds("python", limit=10, timeout=8)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["url"], "https://piefed.social/community/flask/feed")
        self.assertEqual(out[1]["url"], "https://piefed.social/u/rimu/feed")
        self.assertEqual(mock_get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
