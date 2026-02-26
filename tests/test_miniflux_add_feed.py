import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.miniflux import MinifluxProvider


class MinifluxAddFeedTests(unittest.TestCase):
    def _provider(self) -> MinifluxProvider:
        return MinifluxProvider(
            {
                "providers": {
                    "miniflux": {
                        "url": "https://example.com",
                        "api_key": "test-token",
                    }
                }
            }
        )

    def test_add_feed_duplicate_is_treated_as_success(self) -> None:
        provider = self._provider()
        input_url = "https://www.youtube.com/watch?v=nO3PKBfEfLs&list=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU"
        converted_url = "https://www.youtube.com/feeds/videos.xml?playlist_id=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU"
        captured_post_payload = {}

        def fake_req(method, endpoint, json=None, params=None):
            method_upper = str(method or "").upper()
            if method_upper == "GET" and endpoint == "/v1/categories":
                provider._last_request_info = {
                    "ok": True,
                    "used_cache": False,
                    "status_code": 200,
                    "endpoint": endpoint,
                    "method": method_upper,
                    "error_body": None,
                }
                return [{"id": 1, "title": "YouTube"}]

            if method_upper == "POST" and endpoint == "/v1/feeds":
                captured_post_payload.update(json or {})
                provider._last_request_info = {
                    "ok": False,
                    "used_cache": False,
                    "status_code": 400,
                    "endpoint": endpoint,
                    "method": method_upper,
                    "error_body": '{"error_message":"This feed already exists."}',
                }
                return None

            if method_upper == "GET" and endpoint == "/v1/feeds":
                provider._last_request_info = {
                    "ok": True,
                    "used_cache": False,
                    "status_code": 200,
                    "endpoint": endpoint,
                    "method": method_upper,
                    "error_body": None,
                }
                return [
                    {
                        "id": 52,
                        "title": "Crow Pro",
                        "feed_url": converted_url,
                        "site_url": "https://www.youtube.com/playlist?list=PLiJ1MgXwrS8pbiQpg0-1ZOZLlZvi6ALgU",
                        "category": {"title": "YouTube"},
                    }
                ]

            self.fail(f"Unexpected request: {method_upper} {endpoint}")

        with patch("core.discovery.get_ytdlp_feed_url", return_value=converted_url), patch(
            "core.discovery.discover_feed", return_value=None
        ), patch.object(provider, "_req", side_effect=fake_req):
            ok = provider.add_feed(input_url, "YouTube")

        self.assertTrue(ok)
        self.assertEqual(captured_post_payload.get("feed_url"), converted_url)
        self.assertEqual(captured_post_payload.get("category_id"), 1)
        self.assertTrue(provider._last_add_feed_result.get("duplicate"))
        self.assertEqual(provider._last_add_feed_result.get("feed_id"), "52")
        self.assertEqual(provider._last_add_feed_result.get("feed_url"), converted_url)


if __name__ == "__main__":
    unittest.main()
