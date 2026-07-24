# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import unittest
import tempfile

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.miniflux import MinifluxProvider
from providers.inoreader import InoreaderProvider
from providers.bazqux import BazQuxProvider
from providers.theoldreader import TheOldReaderProvider
from core.db import init_db


class ProviderCacheIdTests(unittest.TestCase):
    def test_miniflux_cache_id_fallback_feed(self):
        provider = MinifluxProvider({"providers": {"miniflux": {"url": "http://example.com"}}})
        entries = [{"id": 42, "title": "t", "url": "http://example.com/1"}]
        import core.db
        orig_db = core.db.DB_FILE
        with tempfile.TemporaryDirectory() as tmpdir:
            core.db.DB_FILE = os.path.join(tmpdir, "rss.db")
            init_db()
            articles = provider._entries_to_articles(entries, fallback_feed_id="feed-123")
        core.db.DB_FILE = orig_db
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].feed_id, "feed-123")
        self.assertTrue(articles[0].cache_id.startswith("Miniflux:feed-123:"))

    def test_inoreader_cache_id_fallback_feed(self):
        provider = InoreaderProvider({"providers": {"inoreader": {}}})
        item = {"id": "item-1"}
        feed_id = provider._resolve_item_feed_id(item, "feed/http://example.com")
        cache_id = provider._build_item_cache_id(item, "feed/http://example.com")
        self.assertEqual(feed_id, "feed/http://example.com")
        self.assertEqual(cache_id, "Inoreader:feed/http://example.com:item-1")

    def test_bazqux_cache_id_fallback_feed(self):
        provider = BazQuxProvider({"providers": {"bazqux": {"email": "", "password": ""}}})
        item = {"id": "item-2"}
        feed_id = provider._resolve_item_feed_id(item, "feed/http://example.com")
        cache_id = provider._build_item_cache_id(item, "feed/http://example.com")
        self.assertEqual(feed_id, "feed/http://example.com")
        self.assertEqual(cache_id, "BazQux:feed/http://example.com:item-2")

    def test_theoldreader_cache_id_fallback_feed(self):
        provider = TheOldReaderProvider({"providers": {"theoldreader": {"email": "", "password": ""}}})
        item = {"id": "item-3"}
        feed_id = provider._resolve_item_feed_id(item, "feed/http://example.com")
        cache_id = provider._build_item_cache_id(item, "feed/http://example.com")
        self.assertEqual(feed_id, "feed/http://example.com")
        self.assertEqual(cache_id, "TheOldReader:feed/http://example.com:item-3")


if __name__ == "__main__":
    unittest.main()
