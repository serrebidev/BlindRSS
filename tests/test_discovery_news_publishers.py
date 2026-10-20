# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import discovery


OPML = """<?xml version="1.0"?>
<opml version="1.0"><body>
<outline text="Canada" title="Canada">
<outline text="CBC Top Stories" title="CBC Top Stories" description="News" xmlUrl="https://www.cbc.ca/webfeed/rss/rss-topstories" type="rss"/>
<outline text="CTV News" title="CTV News" xmlUrl="https://www.ctvnews.ca/rss/ctvnews" type="rss"/>
</outline>
</body></opml>"""


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {"Content-Type": "application/xml"}

    def raise_for_status(self):
        return None


class GoogleNewsUrlTests(unittest.TestCase):
    def test_headlines_ca(self):
        self.assertEqual(
            discovery.google_news_url("headlines", country="CA", language="en"),
            "https://news.google.com/rss?hl=en-CA&gl=CA&ceid=CA:en",
        )

    def test_search_encodes_query(self):
        url = discovery.google_news_url("search", "Maple Ridge BC", country="CA", language="en")
        self.assertIn("q=Maple+Ridge+BC", url)
        self.assertIn("ceid=CA:en", url)

    def test_topic_url(self):
        url = discovery.google_news_url("topic", country="CA", language="fr", topic="TECHNOLOGY")
        self.assertIn("/headlines/section/topic/TECHNOLOGY?hl=fr-CA&gl=CA&ceid=CA:fr", url)

    def test_localized_results_include_local_and_national(self):
        with patch.object(discovery, "_discovery_setting", side_effect=lambda k, d="": {"discovery_country": "CA", "discovery_language": "en", "discovery_city": "Maple Ridge", "discovery_region": "BC"}.get(k, d)):
            results = discovery.search_google_news_localized("technology")
        urls = [r["url"] for r in results]
        self.assertTrue(any("Maple+Ridge" in u for u in urls))
        self.assertTrue(any(u.endswith("ceid=CA:en") and "/rss?" in u for u in urls))


class AwesomeCatalogueTests(unittest.TestCase):
    def test_parse_opml_outlines(self):
        out = discovery._parse_opml_outlines(OPML, country="Canada")
        self.assertEqual(2, len(out))
        self.assertEqual("CBC Top Stories", out[0]["title"])
        self.assertEqual("Canada", out[0]["category"])

    def test_search_uses_cache_and_filters(self):
        cached = [
            {"title": "CBC Top Stories", "detail": "News", "url": "https://www.cbc.ca/rss", "category": "Canada", "country": "Canada"},
            {"title": "BBC News", "detail": "News", "url": "https://www.bbc.com/rss", "category": "UK", "country": "United Kingdom"},
        ]
        with patch.object(discovery, "load_awesome_rss_catalogue", return_value=cached):
            self.assertEqual(["CBC Top Stories"], [r["title"] for r in discovery.search_awesome_rss_feeds("cbc")])
            self.assertEqual(2, len(discovery.search_awesome_rss_feeds("")))


class NewsApiPublisherTests(unittest.TestCase):
    def test_no_keys_returns_empty_without_network(self):
        with patch.object(discovery, "_discovery_setting", return_value=""):
            with patch("core.discovery.utils.safe_requests_get", side_effect=AssertionError("network should not be called")):
                self.assertEqual([], discovery.search_newsapi_publishers("cbc"))


if __name__ == "__main__":
    unittest.main()
