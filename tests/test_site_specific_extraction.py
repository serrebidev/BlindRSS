# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Site-specific full-text extraction: Reuters, simonwillison.net, and the
hard-paywall stub guard. All fixtures are static HTML/text — no network."""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import article_extractor


REUTERS_HTML = (
    "<html><body>"
    '<div data-testid="ArticleBody">'
    ' <div data-testid="paragraph-0"><p>SAN FRANCISCO, July 15 (Reuters) - Amazon '
    '<a data-testid="Link">(AMZN.O), opens new tab</a> veteran Dave​Brown, a '
    "senior vice president in AWS, is leaving the company after nineteen long years.</p></div>"
    ' <div data-testid="paragraph-1"><p>He is leaving for another job according to a memo '
    "from AWS CEO Matt Garman, who did not provide any specifics about the move.</p></div>"
    ' <div data-testid="SignOff">Reporting by Greg Bensinger, Editing by Nick Zieminski</div>'
    " <p>Our Standards: The Thomson Reuters Trust Principles.</p>"
    ' <div data-testid="AuthorBio"><h3 data-testid="Heading">Greg Bensinger</h3>'
    "<p>Greg Bensinger joined Reuters in 2022. Greg lives in San Francisco with his "
    "wife and two children.</p></div>"
    "</div>"
    '<div data-testid="ReadNextV2"><p>South Korea top financial regulator will announce '
    "new measures on single-stock leveraged ETFs soon.</p></div>"
    "</body></html>"
)


class ReutersExtractionTests(unittest.TestCase):
    def setUp(self):
        self.text = article_extractor._extract_site_specific_text(
            REUTERS_HTML, "https://www.reuters.com/technology/x-2026-07-15/"
        )

    def test_keeps_body_paragraphs(self):
        self.assertIn("senior vice president in AWS", self.text)
        self.assertIn("He is leaving for another job", self.text)

    def test_strips_opens_new_tab_link_label(self):
        self.assertNotIn("opens new tab", self.text)
        self.assertIn("(AMZN.O) veteran", self.text)

    def test_strips_zero_width_characters(self):
        for ch in ("​", "‌", "‍", "⁠", "﻿"):
            self.assertNotIn(ch, self.text)

    def test_drops_signoff_standards_bio_and_readnext(self):
        self.assertNotIn("Reporting by Greg Bensinger", self.text)
        self.assertNotIn("Our Standards", self.text)
        self.assertNotIn("two children", self.text)
        self.assertNotIn("South Korea", self.text)

    def test_absent_structure_falls_through_to_generic(self):
        # No ArticleBody -> return "" so the generic extractor still runs.
        self.assertEqual(
            article_extractor._extract_reuters_text("<html><body><p>hi</p></body></html>"),
            "",
        )


SIMON_HTML = (
    "<html><body>"
    '<div id="sponsored-banner"><a>Sponsored by SomeCo</a></div>'
    '<div id="primary">'
    '<div class="entry entryPage"><h2>Grok build</h2>'
    "<p>This is the real article body with plenty of words so that the extractor will "
    "happily treat it as the main content of the page and return it in full.</p>"
    "<p>A second real paragraph continues the story with more sentences and detail.</p></div>"
    '<div class="recent-articles"><h2>Recent articles</h2><ul class="bullets">'
    '<li><a href="/x">Other unrelated story one</a> - 9th July 2026</li>'
    '<li><a href="/y">Other unrelated story two</a> - 7th July 2026</li></ul></div>'
    "</div>"
    '<div id="secondary"><div class="metabox"><section><h3>Monthly briefing</h3>'
    "<p>Sponsor me for ten dollars a month and get a digest.</p></section></div></div>"
    '<div id="ft"><ul><li>footer link</li></ul></div>'
    "</body></html>"
)


class SimonWillisonExtractionTests(unittest.TestCase):
    def setUp(self):
        self.text = article_extractor._extract_site_specific_text(
            SIMON_HTML, "https://simonwillison.net/2026/Jul/15/grok-build/"
        )

    def test_keeps_entry_body(self):
        self.assertIn("real article body", self.text)
        self.assertIn("second real paragraph", self.text)

    def test_drops_recent_articles_list(self):
        self.assertNotIn("Recent articles", self.text)
        self.assertNotIn("Other unrelated story one", self.text)

    def test_drops_metabox_sponsor_promo(self):
        self.assertNotIn("Monthly briefing", self.text)
        self.assertNotIn("Sponsored by SomeCo", self.text)


class TopTechTidbitsExtractionTests(unittest.TestCase):
    def _issue_html(self):
        para = (
            "<p>This is a substantial newsletter paragraph with several real "
            "sentences describing an access technology news item in enough detail "
            "to be extracted as body content by the reader engine.</p>"
        )
        sections = "".join(
            f'<div id="border-container-{i}">{para * 3}</div>' for i in range(1, 6)
        )
        return (
            '<html><body><section class="main"><div class="post-container">'
            '<div class="post-byline">By Editor</div>'
            '<div class="post-content"><h2>Top Tech Tidbits</h2>'
            "<p>Section Jumper: News</p></div>"
            f"{sections}"
            '<div class="sd-content"><ul><li>Share on Facebook</li>'
            "<li>Share on X</li></ul></div>"
            '<div class="jp-relatedposts"><h3>Related</h3>'
            "<p>Some other unrelated newsletter issue</p></div>"
            "</div></section></body></html>"
        )

    def test_full_issue_body_is_extracted(self):
        # The issue body lives in border-container section divs the generic
        # extractor discards; the site handler must return the whole issue.
        text = article_extractor._extract_site_specific_text(
            self._issue_html(), "https://toptechtidbits.com/newsletter-01-01-2026/"
        )
        self.assertGreater(len(text), 2000)
        self.assertIn("access technology news item", text)

    def test_share_and_related_chrome_dropped(self):
        text = article_extractor._extract_site_specific_text(
            self._issue_html(), "https://toptechtidbits.com/newsletter-01-01-2026/"
        )
        self.assertNotIn("Share on Facebook", text)
        self.assertNotIn("other unrelated newsletter", text)

    def test_absent_structure_falls_through(self):
        self.assertEqual(
            article_extractor._extract_toptechtidbits_text(
                "<html><body><p>hi</p></body></html>", "https://toptechtidbits.com/x/"
            ),
            "",
        )


class PaywallStubGuardTests(unittest.TestCase):
    def test_subscribe_to_unlock_stub_is_detected(self):
        stub = (
            "Microsoft's New Security Chief Replaces Top Execs to Force an AI Overhaul "
            "By Aaron Holmes and Kevin McLaughlin Subscribe to unlock"
        )
        self.assertTrue(article_extractor._looks_like_paywall_stub(stub))

    def test_real_article_mentioning_subscribe_is_not_flagged(self):
        # A full article that merely discusses subscriptions must not be treated as a stub.
        body = (
            "The company announced a new subscription tier today. "
            "Subscribers will get extra features. " * 40
        )
        self.assertFalse(article_extractor._looks_like_paywall_stub(body))

    def test_short_normal_text_is_not_flagged(self):
        self.assertFalse(
            article_extractor._looks_like_paywall_stub("A short but complete update with no gate.")
        )


if __name__ == "__main__":
    unittest.main()
