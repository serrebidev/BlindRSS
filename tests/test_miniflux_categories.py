# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Miniflux category management (issue #86).

On Miniflux every feed must have a category, so "Uncategorized" is a real,
server-managed category rather than the virtual "no category" bucket other
providers use. It must therefore be deletable/renamable, and delete_category
must report the server's actual outcome instead of a phantom success.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import RSSProvider
from providers.miniflux import MinifluxProvider


def _provider() -> MinifluxProvider:
    return MinifluxProvider(
        {"providers": {"miniflux": {"url": "https://example.com", "api_key": "t"}}}
    )


class MinifluxUncategorizedTests(unittest.TestCase):
    def test_uncategorized_is_a_real_category_on_miniflux(self):
        self.assertTrue(_provider().uncategorized_is_real_category())

    def test_uncategorized_is_virtual_by_default(self):
        # The base contract: every other provider treats it as the protected
        # "no category" sentinel.
        self.assertFalse(RSSProvider.uncategorized_is_real_category(object()))

    def test_delete_category_reports_server_refusal(self):
        """Miniflux refuses to delete a category that still has feeds (HTTP 400).
        delete_category used to return True regardless, so BlindRSS reported a
        phantom success and left the category in place."""
        provider = _provider()

        def fake_req(method, endpoint, json=None, params=None):
            if method == "GET" and endpoint == "/v1/categories":
                return [{"id": 12, "title": "Uncategorized"}]
            if method == "DELETE":
                # 400 -> _req returns None and records the failure.
                provider._last_request_info = {"ok": False, "status_code": 400}
                return None
            return None

        with patch.object(provider, "_req", side_effect=fake_req):
            self.assertFalse(provider.delete_category("Uncategorized"))

    def test_delete_category_succeeds_on_204(self):
        provider = _provider()

        def fake_req(method, endpoint, json=None, params=None):
            if method == "GET" and endpoint == "/v1/categories":
                return [{"id": 12, "title": "Uncategorized"}]
            if method == "DELETE":
                # 204 No Content -> _req returns None but records success.
                provider._last_request_info = {"ok": True, "status_code": 204}
                return None
            return None

        with patch.object(provider, "_req", side_effect=fake_req):
            self.assertTrue(provider.delete_category("Uncategorized"))

    def test_delete_category_unknown_title_is_false(self):
        provider = _provider()

        def fake_req(method, endpoint, json=None, params=None):
            if method == "GET" and endpoint == "/v1/categories":
                return [{"id": 2, "title": "News"}]
            return None

        with patch.object(provider, "_req", side_effect=fake_req):
            self.assertFalse(provider.delete_category("Nope"))


if __name__ == "__main__":
    unittest.main()
