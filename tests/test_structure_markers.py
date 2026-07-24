# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for opt-in article structure markers (headings/lists/quotes) and the
block-aware HTML-to-text conversion (issue: preserve rich formatting)."""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import utils
from core import article_extractor


ALL_ON = {"tables": True, "headings": True, "lists": True, "quotes": True, "links": True}


class StructureOptionState(unittest.TestCase):
    def tearDown(self):
        utils.set_article_structure_options(None)


class BlockTextRenderingTests(StructureOptionState):
    def test_inline_tags_do_not_split_paragraphs(self):
        # Regression: get_text(separator="\n\n") used to shred a paragraph at
        # every link/bold/italic boundary.
        html = "<p>Hello <b>world</b> again <a href='x'>a link</a>, done.</p><p>Second.</p>"
        out = utils.html_to_text(html)
        self.assertIn("Hello world again a link, done.", out)
        self.assertIn("Second.", out)
        self.assertEqual(out.count("\n\n"), 1)

    def test_source_newlines_collapse_to_spaces(self):
        html = "<p>Line one\ncontinues here.</p>"
        self.assertEqual(utils.html_to_text(html), "Line one continues here.")

    def test_br_breaks_line_within_paragraph(self):
        html = "<p>First line.<br>Second line.</p>"
        out = utils.html_to_text(html)
        self.assertIn("First line.\nSecond line.", out)

    def test_scripts_and_styles_dropped(self):
        html = "<p>Visible.</p><script>var x=1;</script><style>p{}</style>"
        out = utils.html_to_text(html)
        self.assertEqual(out, "Visible.")


class HeadingMarkerTests(StructureOptionState):
    HTML = "<h2>Why it <em>matters</em></h2><p>Because.</p>"

    def test_heading_marker_when_enabled(self):
        out = utils.html_to_text(self.HTML, structure=ALL_ON)
        self.assertIn("Heading level 2: Why it matters", out)

    def test_heading_marker_off_by_default(self):
        out = utils.html_to_text(self.HTML)
        self.assertIn("Why it matters", out)
        self.assertNotIn("Heading level", out)

    def test_empty_heading_ignored(self):
        out = utils.html_to_text("<h3> </h3><p>Body.</p>", structure=ALL_ON)
        self.assertNotIn("Heading level", out)


class ListMarkerTests(StructureOptionState):
    def test_unordered_bullets(self):
        html = "<ul><li>Alpha</li><li>Beta</li></ul>"
        out = utils.html_to_text(html, structure=ALL_ON)
        self.assertIn("• Alpha", out)
        self.assertIn("• Beta", out)

    def test_ordered_numbering(self):
        html = "<ol><li>First</li><li>Second</li></ol>"
        out = utils.html_to_text(html, structure=ALL_ON)
        self.assertIn("1. First", out)
        self.assertIn("2. Second", out)

    def test_nested_list_items_all_marked(self):
        html = "<ul><li>Outer<ul><li>Inner</li></ul></li></ul>"
        out = utils.html_to_text(html, structure=ALL_ON)
        self.assertIn("• Outer", out)
        self.assertIn("• Inner", out)

    def test_lists_plain_when_disabled(self):
        html = "<ul><li>Alpha</li></ul>"
        out = utils.html_to_text(html)
        self.assertIn("Alpha", out)
        self.assertNotIn("•", out)


class QuoteMarkerTests(StructureOptionState):
    HTML = "<p>Intro.</p><blockquote><p>Wise words.</p></blockquote><p>After.</p>"

    def test_quote_envelope_when_enabled(self):
        out = utils.html_to_text(self.HTML, structure=ALL_ON)
        self.assertLess(out.index("Quote:"), out.index("Wise words."))
        self.assertLess(out.index("Wise words."), out.index("End of quote."))

    def test_quotes_plain_when_disabled(self):
        out = utils.html_to_text(self.HTML)
        self.assertIn("Wise words.", out)
        self.assertNotIn("Quote:", out)

    def test_empty_blockquote_ignored(self):
        out = utils.html_to_text("<blockquote> </blockquote><p>Body.</p>", structure=ALL_ON)
        self.assertNotIn("Quote:", out)


class ModuleOptionTests(StructureOptionState):
    def test_set_options_applies_to_conversion(self):
        utils.set_article_structure_options({"headings": True})
        out = utils.html_to_text("<h2>Topic</h2>")
        self.assertIn("Heading level 2: Topic", out)

    def test_apply_from_config_get(self):
        cfg = {"article_structure_headings": True, "article_structure_tables": False}
        utils.apply_article_structure_config(lambda k, d=None: cfg.get(k, d))
        opts = utils.get_article_structure_options()
        self.assertTrue(opts["headings"])
        self.assertFalse(opts["tables"])
        self.assertFalse(opts["lists"])

    def test_defaults_keep_current_behavior(self):
        utils.set_article_structure_options(None)
        opts = utils.get_article_structure_options()
        self.assertEqual(
            opts,
            {
                "tables": True,
                "headings": False,
                "lists": False,
                "quotes": False,
                "links": False,
            },
        )


class LinkMarkerTests(StructureOptionState):
    def test_link_target_shown_inline_when_enabled(self):
        html = '<p>Read the <a href="https://example.com/report">full report</a> here.</p>'
        out = utils.html_to_text(html, structure=ALL_ON)
        self.assertIn("full report (https://example.com/report)", out)

    def test_links_plain_when_disabled(self):
        html = '<p>Read the <a href="https://example.com/report">full report</a> here.</p>'
        out = utils.html_to_text(html)
        self.assertIn("full report", out)
        self.assertNotIn("https://example.com/report", out)

    def test_bare_link_shows_url_once(self):
        html = '<p>See <a href="https://example.com/x">https://example.com/x</a>.</p>'
        out = utils.html_to_text(html, structure=ALL_ON)
        self.assertEqual(out.count("https://example.com/x"), 1)

    def test_relative_and_non_http_links_left_alone(self):
        html = (
            '<p><a href="/local/page">relative</a> and '
            '<a href="mailto:a@b.com">mail</a>.</p>'
        )
        out = utils.html_to_text(html, structure=ALL_ON)
        self.assertNotIn("(/local/page)", out)
        self.assertNotIn("mailto:", out)
        self.assertIn("relative", out)

    def test_link_url_survives_extraction_when_enabled(self):
        utils.set_article_structure_options({"links": True})
        html = (
            "<html><body><article>"
            "<p>This is the opening paragraph of the article body, long enough to matter, "
            'and it links to the <a href="https://example.com/source">source document</a> '
            "for the reader to open.</p>"
            "<p>This is the closing paragraph of the article body with enough text too.</p>"
            "</article></body></html>"
        )
        text = article_extractor._extract_text_any(html, "https://example.com/a")
        self.assertIn("https://example.com/source", text)

    def test_extraction_has_no_urls_when_disabled(self):
        utils.set_article_structure_options(None)
        html = (
            "<html><body><article>"
            "<p>This is the opening paragraph of the article body, long enough to matter, "
            'and it links to the <a href="https://example.com/source">source document</a> '
            "for the reader to open.</p>"
            "<p>This is the closing paragraph of the article body with enough text too.</p>"
            "</article></body></html>"
        )
        text = article_extractor._extract_text_any(html, "https://example.com/a")
        self.assertNotIn("https://example.com/source", text)
        self.assertIn("source document", text)


class ExtractionPipelineTests(StructureOptionState):
    HTML = (
        "<html><body><article>"
        "<h2>The setup</h2>"
        "<p>This is the first paragraph of the article body with enough text to matter.</p>"
        "<ul><li>Point one is here</li><li>Point two is here</li></ul>"
        "<blockquote><p>An important quotation appears in this block element.</p></blockquote>"
        "<p>This is the closing paragraph of the article body with enough text too.</p>"
        "</article></body></html>"
    )

    def test_markers_survive_extraction_when_enabled(self):
        utils.set_article_structure_options(ALL_ON)
        text = article_extractor._extract_text_any(self.HTML, "https://example.com/a")
        self.assertIn("Heading level 2: The setup", text)
        self.assertIn("• Point one is here", text)
        self.assertIn("Quote:", text)
        self.assertIn("End of quote.", text)

    def test_extraction_unchanged_when_disabled(self):
        utils.set_article_structure_options(None)
        text = article_extractor._extract_text_any(self.HTML, "https://example.com/a")
        self.assertNotIn("Heading level", text)
        self.assertNotIn("• ", text)
        self.assertNotIn("End of quote.", text)
        self.assertIn("first paragraph of the article body", text)


class MergeAndGuardTests(StructureOptionState):
    def test_merge_keeps_short_marker_lines(self):
        text = "\n".join(
            [
                "Heading level 2: Intro",
                "• Alpha",
                "1. First",
                "Quote:",
                "Short quote.",
                "End of quote.",
                "This is a normal paragraph that is clearly long enough to survive merging.",
            ]
        )
        merged = article_extractor._merge_texts([text])
        self.assertIn("Heading level 2: Intro", merged)
        self.assertIn("• Alpha", merged)
        self.assertIn("1. First", merged)
        self.assertIn("Quote:", merged)
        self.assertIn("End of quote.", merged)

    def test_repeated_quote_markers_not_deduped(self):
        text = "\n".join(
            [
                "Quote:",
                "This is the first quotation and it is reasonably long as quotes go.",
                "End of quote.",
                "Quote:",
                "This is the second quotation and it is also reasonably long as quotes go.",
                "End of quote.",
            ]
        )
        merged = article_extractor._merge_texts([text])
        self.assertEqual(merged.count("Quote:"), 2)
        self.assertEqual(merged.count("End of quote."), 2)

    def test_marker_heavy_article_is_not_a_link_list(self):
        lines = ["• item number %d" % i for i in range(12)]
        lines.insert(0, "Heading level 2: A real list")
        self.assertFalse(article_extractor._looks_like_link_list("\n".join(lines)))


if __name__ == "__main__":
    unittest.main()
