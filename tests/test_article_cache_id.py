# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import unittest

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.models import Article


class ArticleCacheIdTests(unittest.TestCase):
    def test_cache_id_prefixes_feed_once(self):
        article = Article(
            id="item-1",
            title="Title",
            url="http://example.com/item-1",
            content="",
            date="2026-01-27 00:00:00",
            author="Author",
            feed_id="feed/123",
        )
        self.assertEqual(article.cache_id, "feed/123:item-1")

    def test_cache_id_does_not_double_prefix(self):
        article = Article(
            id="feed/123:item-1",
            title="Title",
            url="http://example.com/item-1",
            content="",
            date="2026-01-27 00:00:00",
            author="Author",
            feed_id="feed/123",
        )
        self.assertEqual(article.cache_id, "feed/123:item-1")

    def test_cache_id_falls_back_to_id(self):
        article = Article(
            id="item-2",
            title="Title",
            url="http://example.com/item-2",
            content="",
            date="2026-01-27 00:00:00",
            author="Author",
            feed_id="",
        )
        self.assertEqual(article.cache_id, "item-2")


if __name__ == "__main__":
    unittest.main()
