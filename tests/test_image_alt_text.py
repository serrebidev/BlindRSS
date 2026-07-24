# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for image alt-text surfacing and the per-feed show-images override."""

import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import utils


HTML_WITH_IMG = (
    "<p>Intro paragraph.</p>"
    "<img src='https://site/img/q2.png' alt='Chart of Q2 revenue'>"
    "<p>Closing paragraph.</p>"
)

HTML_IMG_NO_ALT = "<p>Hi</p><img src='https://site/a.jpg'>"
HTML_NO_IMG = "<p>Just text here.</p>"


class ImageAltTextTests(unittest.TestCase):
    def test_alt_text_included_when_enabled(self):
        out = utils.html_to_text(HTML_WITH_IMG, include_images=True)
        self.assertIn("[Image: Chart of Q2 revenue]", out)
        # The image URL must never appear in the body.
        self.assertNotIn("q2.png", out)
        self.assertIn("Intro paragraph.", out)
        self.assertIn("Closing paragraph.", out)

    def test_images_dropped_when_disabled(self):
        out = utils.html_to_text(HTML_WITH_IMG, include_images=False)
        self.assertNotIn("[Image", out)
        self.assertNotIn("q2.png", out)
        self.assertIn("Intro paragraph.", out)

    def test_image_without_alt_uses_generic_marker(self):
        out = utils.html_to_text(HTML_IMG_NO_ALT, include_images=True)
        self.assertIn("[Image]", out)
        self.assertNotIn("a.jpg", out)

    def test_no_images(self):
        self.assertFalse(utils.content_has_images(HTML_NO_IMG))
        self.assertIsNone(utils.first_image_url(HTML_NO_IMG))
        out = utils.html_to_text(HTML_NO_IMG, include_images=True)
        self.assertNotIn("[Image", out)

    def test_first_image_url_and_detection(self):
        self.assertTrue(utils.content_has_images(HTML_WITH_IMG))
        self.assertEqual(utils.first_image_url(HTML_WITH_IMG), "https://site/img/q2.png")

    def test_empty_input(self):
        self.assertEqual(utils.html_to_text("", include_images=True), "")
        self.assertEqual(utils.html_to_text(None, include_images=True), "")
        self.assertFalse(utils.content_has_images(None))


class FeedShowImagesOverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import core.db as db
        self.db = db
        self.orig = db.DB_FILE
        db.DB_FILE = os.path.join(self.tmp.name, "rss.db")
        db.init_db()
        conn = db.get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            ("f1", "http://x/feed", "Feed One", "Cat", ""),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db.DB_FILE = self.orig
        self.tmp.cleanup()

    def test_default_is_inherit_none(self):
        self.assertIsNone(self.db.get_feed_show_images("f1"))

    def test_set_and_get_override(self):
        self.assertTrue(self.db.set_feed_show_images("f1", True))
        self.assertIs(self.db.get_feed_show_images("f1"), True)
        self.assertTrue(self.db.set_feed_show_images("f1", False))
        self.assertIs(self.db.get_feed_show_images("f1"), False)
        self.assertTrue(self.db.set_feed_show_images("f1", None))
        self.assertIsNone(self.db.get_feed_show_images("f1"))

    def test_unknown_feed(self):
        self.assertIsNone(self.db.get_feed_show_images("nope"))


if __name__ == "__main__":
    unittest.main()
