# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Classic full-text view must keep short standalone lines (issue: Android Authority).

_merge_texts had a sub-25-char paragraph floor that ran on EVERY extraction,
not just read-proxy markdown. On HTML-extracted text it silently ate plain
short headings — e.g. the "FootballGPT" and "Sofascore" h3 lines in Android
Authority's World Cup AI roundup — while both names still appeared inside body
sentences, which made naive substring checks pass. The floor is now opt-in
(drop_short_paragraphs) and only the proxy-markdown path uses it.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import article_extractor


LONG_A = "This is a normal paragraph that is clearly long enough to survive merging."
LONG_B = "Another perfectly ordinary sentence with more than enough characters in it."


class MergeShortLineTests(unittest.TestCase):
    def test_short_heading_lines_survive_html_merge(self):
        text = "\n".join(["Sofascore", LONG_A, "FootballGPT", LONG_B])
        merged = article_extractor._merge_texts([text])
        lines = merged.splitlines()
        self.assertIn("Sofascore", lines)
        self.assertIn("FootballGPT", lines)

    def test_repeated_short_headings_all_kept(self):
        # Review roundups repeat "Pros"/"Cons" per product: repeats are content.
        text = "\n".join(["Pros", LONG_A, "Cons", LONG_B, "Pros", LONG_A + " More.", "Cons", LONG_B + " More."])
        merged = article_extractor._merge_texts([text])
        self.assertEqual(merged.splitlines().count("Pros"), 2)
        self.assertEqual(merged.splitlines().count("Cons"), 2)

    def test_proxy_markdown_path_still_drops_short_nav_lines(self):
        text = "\n".join(["Home", "News", LONG_A, "Contact"])
        merged = article_extractor._merge_texts([text], drop_short_paragraphs=True)
        lines = merged.splitlines()
        self.assertEqual(lines, [LONG_A])

    def test_long_paragraphs_still_deduped_across_pages(self):
        merged = article_extractor._merge_texts([LONG_A, LONG_A])
        self.assertEqual(merged.count(LONG_A), 1)


class ExtractFullArticleHeadingTests(unittest.TestCase):
    """End-to-end through extract_full_article with a stubbed page fetch."""

    PAGE = (
        "<html><head><title>Roundup</title></head><body><article>"
        "<h1>World Cup AI roundup</h1>"
        "<p>Predicd uses artificial intelligence to forecast the winners and losers "
        "of the tournament, and it has plenty of interesting things to say today.</p>"
        "<p>There are plenty of other great new AI apps and services out there, "
        "including the following two that caught our attention this week.</p>"
        "<h3>FootballGPT</h3>"
        "<p>FootballGPT is a useful little tool for coaches who want to create "
        "drills, refine strategies, and implement them on the field this season.</p>"
        "<h3>Sofascore</h3>"
        "<p>Sofascore is my pocket sports update app, which I use to track results "
        "across Formula 1, tennis, cricket, and rugby throughout the whole year.</p>"
        "</article></body></html>"
    )

    def test_short_h3_headings_survive_as_standalone_lines(self):
        with mock.patch.object(
            article_extractor,
            "_fetch_page",
            return_value=article_extractor._FetchResult(html=self.PAGE),
        ):
            art = article_extractor.extract_full_article("https://example.com/roundup/")
        self.assertIsNotNone(art)
        lines = art.text.splitlines()
        self.assertIn("FootballGPT", lines, art.text)
        self.assertIn("Sofascore", lines, art.text)


if __name__ == "__main__":
    unittest.main()
