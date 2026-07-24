# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regression: MacRumors full text must not merge the next-article teaser (issue: full-text
view showed the real article followed by text from OTHER articles).

MacRumors article pages carry a "Next Article" teaser in the sidebar whose anchor text is the
NEXT STORY'S HEADLINE (e.g. "Next Year's iPhone Air 2 to Feature Four Key Upgrades"). The old
pagination heuristic in _find_next_page matched "next" as a substring anywhere in anchor text,
so that teaser was treated as page 2 of the current article and the unrelated story's full body
was fetched and appended.

The fixture is a real MacRumors article page (2026-07-08, "Apple to Drop Support for Encrypted
Mac OS Extended Drives Next Year"), stripped of scripts/styles/nav but keeping the article body,
the JSON-LD block, the Popular Stories / Top Rated Comments blocks, and BOTH next-article
anchors (the data-track="next-article" one and the plain headline-text one). No network is used.
"""

import os
import sys

import pytest

sys.path.append(os.getcwd())

from core import article_extractor

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "macrumors_article.html")

ARTICLE_URL = "https://www.macrumors.com/2026/07/08/apple-to-drop-support-for-encrypted-mac-os-extended/"
NEXT_STORY_URL = "https://www.macrumors.com/2026/07/08/iphone-air-2-four-key-upgrades/"

# A sentence from the real article body in the fixture.
REAL_BODY_SNIPPET = "encrypted Mac OS Extended (HFS+) volumes"
REAL_BODY_TAIL = "does not apply to encrypted Time Machine backup disks"

# Marker used for the (unrelated) next story a regressed extractor would fetch and merge.
UNRELATED_MARKER = "UNRELATED NEXT STORY BODY MARKER"


@pytest.fixture(scope="module")
def fixture_html():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return f.read()


def test_next_article_teaser_is_not_pagination(fixture_html):
    """The next-story teaser must not be reported as a pagination 'next page' URL."""
    assert article_extractor._find_next_page(fixture_html, ARTICLE_URL) is None


def test_extract_full_article_does_not_merge_next_story(fixture_html, monkeypatch):
    """End-to-end (offline): extraction returns the real body only.

    The fake fetcher serves the fixture for the article URL and an unrelated story for the
    next-article URL. If the pagination heuristic regresses and follows the teaser again,
    the unrelated marker text would show up in the merged output.
    """
    next_story_html = f"""
    <html><head><title>Next Year's iPhone Air 2 to Feature Four Key Upgrades</title></head>
    <body><article>
    <p>{UNRELATED_MARKER}. A report says the second-generation iPhone Air will gain a second
    rear camera, joining the existing Wide lens on the device next spring.</p>
    <p>{UNRELATED_MARKER}. The device is also expected to use an A20 chip built on the new
    2nm process, which should help battery life regardless of capacity changes.</p>
    </article></body></html>
    """

    def fake_fetch_page(url, timeout=20):
        if url == ARTICLE_URL:
            return article_extractor._FetchResult(html=fixture_html)
        if url == NEXT_STORY_URL:
            return article_extractor._FetchResult(html=next_story_html)
        return article_extractor._FetchResult()

    monkeypatch.setattr(article_extractor, "_fetch_page", fake_fetch_page)

    art = article_extractor.extract_full_article(ARTICLE_URL, timeout=5)
    assert art is not None

    # The real article body is present, through to its final paragraph.
    assert REAL_BODY_SNIPPET in art.text
    assert REAL_BODY_TAIL in art.text

    # No unrelated next-story content merged in.
    assert UNRELATED_MARKER not in art.text
    assert "iPhone Air" not in art.text

    # No sidebar/related boilerplate from the page either.
    assert "Top Rated Comments" not in art.text
    assert "Popular Stories" not in art.text
    assert "Next Article" not in art.text


def test_headline_containing_next_is_not_pagination():
    """Anchor text that merely CONTAINS 'next' (a headline) is not a pagination control."""
    html = (
        "<html><body><p>Body text.</p>"
        '<a href="/2026/07/08/iphone-air-2-four-key-upgrades/">'
        "Next Year's iPhone Air 2 to Feature Four Key Upgrades</a>"
        "</body></html>"
    )
    assert article_extractor._find_next_page(html, "https://example.com/a") is None


def test_data_track_next_article_is_skipped_even_with_next_class():
    """data-* next-article markers veto the anchor even when class/aria look pagination-y."""
    html = (
        "<html><body>"
        '<a data-track="next-article" class="next" href="/other-story/">Read this</a>'
        "</body></html>"
    )
    assert article_extractor._find_next_page(html, "https://example.com/a") is None


def test_genuine_pagination_labels_still_work():
    for label in ("Next", "Next Page", "Older", "&raquo;"):
        html = f'<html><body><a href="/p2">{label}</a></body></html>'
        assert (
            article_extractor._find_next_page(html, "https://example.com/a")
            == "https://example.com/p2"
        ), label


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
