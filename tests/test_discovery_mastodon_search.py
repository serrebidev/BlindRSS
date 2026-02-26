import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import discovery


class MastodonSearchTests(unittest.TestCase):
    def test_mastodon_account_url_to_rss_handle_path(self) -> None:
        self.assertEqual(
            discovery._mastodon_account_url_to_rss("https://mastodon.social/@Gargron"),
            "https://mastodon.social/@Gargron.rss",
        )

    def test_mastodon_account_url_to_rss_users_path(self) -> None:
        self.assertEqual(
            discovery._mastodon_account_url_to_rss("https://example.social/users/alice"),
            "https://example.social/users/alice.rss",
        )

    def test_mastodon_tag_url_to_rss(self) -> None:
        self.assertEqual(
            discovery._mastodon_tag_url_to_rss("https://mastodon.social/tags/python"),
            "https://mastodon.social/tags/python.rss",
        )

    def test_mastodon_search_response_to_feeds_includes_accounts_and_tags(self) -> None:
        payload = {
            "accounts": [
                {
                    "display_name": "Gargron",
                    "acct": "Gargron@mastodon.social",
                    "url": "https://mastodon.social/@Gargron",
                    "followers_count": 123,
                }
            ],
            "hashtags": [
                {
                    "name": "python",
                    "url": "https://mastodon.social/tags/python",
                    "history": [{"uses": "7"}],
                }
            ],
        }

        out = discovery._mastodon_search_response_to_feeds(payload, "https://mastodon.social", limit=10)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["url"], "https://mastodon.social/@Gargron.rss")
        self.assertIn("Mastodon user", out[0]["detail"])
        self.assertEqual(out[1]["title"], "#python")
        self.assertEqual(out[1]["url"], "https://mastodon.social/tags/python.rss")
        self.assertIn("Mastodon tag", out[1]["detail"])

    def test_mastodon_search_response_to_feeds_dedupes_duplicate_urls(self) -> None:
        payload = {
            "accounts": [
                {
                    "display_name": "Alice",
                    "acct": "alice@example.social",
                    "url": "https://example.social/@alice",
                },
                {
                    "display_name": "Alice Duplicate",
                    "acct": "alice@example.social",
                    "url": "https://example.social/@alice",
                },
            ]
        }

        out = discovery._mastodon_search_response_to_feeds(payload, "https://mastodon.social", limit=10)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["url"], "https://example.social/@alice.rss")

    def test_search_mastodon_feeds_uses_api_and_normalizes_results(self) -> None:
        payload = {
            "accounts": [
                {
                    "display_name": "karpathy",
                    "acct": "karpathy@sigmoid.social",
                    "url": "https://sigmoid.social/@karpathy",
                    "followers_count": 2000,
                }
            ],
            "hashtags": [
                {
                    "name": "ai",
                    "url": "https://mastodon.social/tags/ai",
                    "history": [{"uses": "42"}],
                }
            ],
            "statuses": [],
        }
        fake_resp = SimpleNamespace(status_code=200, json=lambda: payload)

        with patch("core.discovery.utils.safe_requests_get", return_value=fake_resp) as mock_get:
            out = discovery.search_mastodon_feeds("ai", limit=10, timeout=10)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["url"], "https://sigmoid.social/@karpathy.rss")
        self.assertEqual(out[1]["url"], "https://mastodon.social/tags/ai.rss")
        self.assertIn("/api/v2/search", mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
