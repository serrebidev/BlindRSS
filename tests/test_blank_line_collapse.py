# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Reader bodies read one paragraph per line, with no blank lines between them.

Reported against the Axios feed: when full-text extraction fails and the reader
falls back to the feed's own content, a blank line appeared between every
paragraph, so a screen-reader user arrowed through twice as many lines as a
successful extraction produced. The extraction paths disagreed on the paragraph
separator; these tests pin the single convention.
"""

import unittest

from core import article_extractor, article_html, utils


class TestCollapseBlankLines(unittest.TestCase):
    def test_blank_lines_between_paragraphs_are_removed(self):
        self.assertEqual(
            utils.collapse_blank_lines("One\n\nTwo\n\n\nThree"),
            "One\nTwo\nThree",
        )

    def test_whitespace_only_lines_count_as_blank(self):
        self.assertEqual(utils.collapse_blank_lines("One\n   \nTwo"), "One\nTwo")

    def test_single_newline_layout_is_left_alone(self):
        self.assertEqual(utils.collapse_blank_lines("One\nTwo"), "One\nTwo")

    def test_empty_input(self):
        self.assertEqual(utils.collapse_blank_lines(""), "")
        self.assertEqual(utils.collapse_blank_lines(None), "")

    def test_html_to_text_output_collapses_to_one_line_per_paragraph(self):
        text = utils.collapse_blank_lines(
            utils.html_to_text("<p>First para.</p><p>Second para.</p><ul><li>Item</li></ul>")
        )
        self.assertEqual(text, "First para.\nSecond para.\nItem")


class TestRenderedFullArticleHasNoBlankLines(unittest.TestCase):
    def _render(self, url, html):
        return article_extractor.render_full_article(
            url,
            fallback_html=html,
            fallback_title="Some Title",
            fallback_author="Some Author",
        )

    def test_feed_content_fallback_body_has_no_blank_lines(self):
        html = "".join(f"<p>Paragraph number {i} with enough words to survive.</p>" for i in range(6))
        rendered = self._render("", html)
        self.assertIsNotNone(rendered)
        # Line 0/1 are the Title/Author header, line 2 is its blank separator.
        body = (rendered or "").rstrip("\n").split("\n")[3:]
        self.assertEqual([ln for ln in body if not ln.strip()], [])
        self.assertGreaterEqual(len(body), 5)

    def test_header_keeps_its_blank_separator(self):
        rendered = self._render("", "<p>Only paragraph here, long enough to keep.</p>")
        lines = (rendered or "").split("\n")
        self.assertTrue(lines[0].endswith("Some Title"))
        self.assertEqual(lines[2], "")

    def test_site_stripper_rejoin_no_longer_inserts_blank_lines(self):
        # Axios has a boilerplate stripper that rebuilds the body from
        # paragraphs; that rebuild is what used to introduce the blank lines.
        html = "".join(
            f"<p>Axios paragraph {i} with enough words in it to be kept.</p>" for i in range(5)
        )
        rendered = self._render("https://www.axios.com/2026/07/21/story", html)
        self.assertIsNotNone(rendered)
        body = "\n".join((rendered or "").split("\n")[3:]).strip()
        self.assertNotIn("\n\n", body)


class TestRichViewBlankLines(unittest.TestCase):
    def test_consecutive_brs_collapse_to_one(self):
        out = article_html.clean_article_html(
            "<div><p>Lead paragraph.</p>Second<br><br>Third<br><br><br>Fourth</div>",
            "https://example.test/a",
        )
        self.assertNotIn("<br/><br/>", out.replace(" ", ""))
        self.assertIn("Third", out)
        self.assertIn("Fourth", out)

    def test_leading_and_trailing_brs_are_dropped(self):
        out = article_html.clean_article_html(
            "<div><br><p>Body text that is real content.</p><br></div>",
            "https://example.test/a",
        )
        self.assertNotIn("<br", out)
        self.assertIn("Body text that is real content.", out)


if __name__ == "__main__":
    unittest.main()
