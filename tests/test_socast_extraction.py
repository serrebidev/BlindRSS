# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import article_extractor as ae
from core import article_html as ah
from core import utils

# Real socast/Pattison-portals layout: the body is split across TWO
# <article class="mainArticle"> blocks (lead w/ header image, then a continuation),
# with related-post / newsletter / ad widgets and an author line interleaved.
SOCAST_HTML = """<!doctype html><html><head><title>Story Headline | Site</title>
<meta property="og:title" content="Story Headline"></head><body>
<main><div class="site_width"><div class="sc-sidebar-wrapper"><div class="sc-content">
<article class="mainArticle">
  <section class="entry-header">
    <div class="aspect-ratio-content">
      <img src="https://media-cdn.socastsrm.com/lead.jpg" alt="Lead photo of the scene"/>
    </div>
    <div class="wp-caption-text">Caption describing the lead photo in detail here.</div>
    <h1>Story Headline</h1>
  </section>
  <div class="wpb-content-wrapper">
    <p>LEAD_ONE This is the first lead paragraph of the story body content here.</p>
    <p>LEAD_TWO This is the second lead paragraph continuing the story body content.</p>
    <div class="wpb_raw_code wpb_raw_html wpb_content_element"><div class="wpb_wrapper">
      <script>showAd('sidebar');</script></div></div>
    <div class="wpb_raw_code wpb_raw_html"><div class="pp-btn-container scWidgetContainer">
      <a href="/newsletter/">Join Our Daily Email</a></div></div>
  </div>
</article>
<div class="parallax-breakout"><script>adbutler();</script></div>
<article class="mainArticle"><div>
  <p>CONT_ONE The continuation paragraph appears after the mid-article ad break here.</p>
  <div class="posts items-wrapper">
    <a href="/other-story/" class="bnl-pp-happening item"><div class="bnl-info">
      <div class="highlight-text">Charges laid</div>
      <div class="bnl-title text-h4">RELATEDJUNK unrelated related-post headline</div>
      <div class="bnl-content"><span class="sc-time sc-item-detail">41m ago</span></div>
    </div></a>
  </div>
  <p>CONT_TWO The final body paragraph wraps the whole story up neatly at the end.</p>
  <div class="pp-more-wrapper"></div>
</div>
<div>by <span class="sc-author">The Canadian Press</span></div>
<footer class="entry-footer"></footer>
</article>
</div></div></div></main></body></html>"""

# Variant: lead lives in a plain content-feature article, continuation in mainArticle.
SOCAST_VARIANT = SOCAST_HTML.replace(
    '<article class="mainArticle">\n  <section class="entry-header">',
    '<article class="content-feature">\n  <section class="entry-header">',
    1,
)

URL = "https://fraservalleytoday.ca/2026/07/15/story-headline/"


def test_detection():
    assert ae._is_socast_page(SOCAST_HTML)
    assert ah._looks_socast(SOCAST_HTML)


def _assert_full_clean(text):
    for token in ("LEAD_ONE", "LEAD_TWO", "CONT_ONE", "CONT_TWO"):
        assert token in text, f"missing body token {token}"
    # Interleaved widgets / author / newsletter must be stripped.
    assert "RELATEDJUNK" not in text
    assert "Join Our Daily Email" not in text
    assert "The Canadian Press" not in text
    assert "41m ago" not in text


def test_text_extraction_gets_whole_split_body():
    text = ae._extract_text_any(SOCAST_HTML, URL)
    _assert_full_clean(text)
    # Order preserved: lead before continuation.
    assert text.index("LEAD_ONE") < text.index("CONT_ONE") < text.index("CONT_TWO")


def test_text_extraction_variant_layout():
    _assert_full_clean(ae._extract_text_any(SOCAST_VARIANT, URL))


def test_rich_extraction_gets_whole_split_body_with_image():
    html = ah.clean_article_html(SOCAST_HTML, URL)
    assert "<img" in html and "lead.jpg" in html  # header image preserved
    _assert_full_clean(utils.html_to_text(html))


def test_rich_extraction_variant_layout():
    html = ah.clean_article_html(SOCAST_VARIANT, URL)
    assert "lead.jpg" in html
    _assert_full_clean(utils.html_to_text(html))


def test_non_socast_page_unaffected():
    plain = """<html><body><article><h1>T</h1>
    <p>Just an ordinary article paragraph with enough length to be picked up fine.</p>
    <p>A second ordinary paragraph so the extractor has a real body to work with here.</p>
    </article></body></html>"""
    assert not ae._is_socast_page(plain)
    assert not ah._looks_socast(plain)
    text = ae._extract_text_any(plain, "https://example.com/x")
    assert "ordinary article paragraph" in text
