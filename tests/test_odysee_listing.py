# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import odysee as odysee_mod


class OdyseeListingTests(unittest.TestCase):
    def test_is_odysee_url(self) -> None:
        self.assertTrue(odysee_mod.is_odysee_url("https://odysee.com/@Odysee:8"))
        self.assertTrue(odysee_mod.is_odysee_url("https://lbry.tv/@Odysee:8"))
        self.assertTrue(odysee_mod.is_odysee_url("lbry://@Odysee#8"))
        self.assertFalse(odysee_mod.is_odysee_url("https://example.com/video"))

    def test_normalize_odysee_url_strips_query_and_fragment(self) -> None:
        self.assertEqual(
            odysee_mod.normalize_odysee_url("https://odysee.com/Future:abc?src=share#comments"),
            "https://odysee.com/Future:abc",
        )

    def test_extract_listing_items_from_playlist_info(self) -> None:
        info = {
            "_type": "playlist",
            "title": "My Channel",
            "channel": "Author Name",
            "entries": [
                {
                    "url": "https://odysee.com/Video:111?utm=1",
                    "title": "First",
                    "timestamp": 1700000000,
                    "channel": "Author Name",
                },
                {
                    "url": "https://odysee.com/Video:111?utm=2",
                    "title": "First (dup url after normalize)",
                    "timestamp": 1700000001,
                    "channel": "Author Name",
                },
                {
                    "url": "https://odysee.com/Video:222",
                    "title": "Second",
                    "upload_date": "2025-12-30 12:00:00",
                },
            ],
        }
        title, items = odysee_mod._extract_listing_from_info(info)
        self.assertEqual(title, "My Channel")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].url, "https://odysee.com/Video:111")
        self.assertEqual(items[0].published, "1700000000")
        self.assertEqual(items[1].url, "https://odysee.com/Video:222")
        self.assertEqual(items[1].published, "2025-12-30 12:00:00")

    def test_extract_single_item_from_video_info(self) -> None:
        info = {
            "title": "A Video",
            "webpage_url": "https://odysee.com/Some:abc?src=share",
            "timestamp": 1700000000,
            "uploader": "Uploader",
        }
        title, items = odysee_mod._extract_listing_from_info(info)
        self.assertEqual(title, "A Video")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://odysee.com/Some:abc")


if __name__ == "__main__":
    unittest.main()

