# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for the link-list junk guard: video-only/index pages extract as a stack of
navigation and related-story headlines, which must not be shown as the article body.
The extractor raises so the UI falls back to the feed snippet plus the original link.
"""

import types

import pytest

import core.article_extractor as article_extractor
import core.utils as utils


# Real-world extraction output from a WDBJ7 (Gray Television) video-only page reached
# through a Google News RSS redirect: no article body, only sidebar/nav headlines.
WDBJ7_VIDEO_PAGE_JUNK = "\n".join(
    [
        "Noticias de la Cuidad Estrella",
        "Birthdays and Anniversaries",
        "Hometown Veterans: Honoring our Heroes",
        "Maple Ridge Apartment Fire (Courtesy of Lynchburg Fire Department)",
        "Published: Feb. 13, 2026 at 7:09 PM EST",
        "Add as a preferred source on Google",
        "Botetourt County Planning Commission Discusses Water Issues",
        "Salem Red Sox Announce Promotional Schedule For The Season",
        "Crash Closes Route 460 In Bedford County Early Monday",
    ]
)

REAL_SHORT_ARTICLE = "\n".join(
    [
        "The city council approved the new budget on Tuesday after a lengthy debate.",
        "Council members said the plan preserves funding for libraries and transit.",
        "The mayor praised the compromise as a model for future negotiations.",
        "Residents at the meeting were divided, but most welcomed the outcome.",
    ]
)

# Real extraction output for an NPR "Wait Wait...Don't Tell Me!" episode page
# (feeds.npr.org/35/rss.xml). The episode rundown is a stack of short bold segment
# names interleaved with prose blurbs, so it is 72% link-like by line but only 36%
# by character mass. The line test alone rejected it and the reader showed the
# "video-only page" fallback instead of the whole rundown.
NPR_WAIT_WAIT_EPISODE = "\n".join(
    [
        "'Wait Wait' for July 25, 2026: With Not My Job guest Tyler James Williams",
        "This week's show was recorded in Chicago with host Peter Sagal, judge and "
        "scorekeeper Alzo Slade, Not My Job guest Tyler James Williams and panelists "
        "Josh Gondelman, Hari Kondabolu, and Faith Salie. Click the audio link above "
        "to hear the whole show.",
        "Who's Alzo This Time",
        "What A Long Strange Trip; It's Time For Lyme; A Summer Fashion Tip/Warning",
        "Panel Questions",
        "We All Scream for This Easy Recipe",
        "Bluff The Listener",
        "Our panelists tell three stories about books in the news, only one of which is true",
        "Not My Job: Abbott Elementary's Tyler James Williams on growing up on TV and "
        "being too handsome to play Chris Rock",
        "Peter talks to Tyler James Williams, one of the stars of the Abbott Elementary "
        'and Everyone Hates Chris. Tyler plays our game called, "Everyone Loves These '
        'Chrises" Three questions about the Hollywood A-list Chrises: Pratt, Evans and '
        "Hemsworth.",
        "Panel Questions",
        "The Big Day Parlay; Rest Easy But Not Cheaply; A Candid And Stinky Camera",
        "Limericks",
        "Alzo Slade reads three news-related limericks: Fruity Air Conditioners; A "
        "Hi-Tech Solution for Mosquitoes; Ruining Dessert on Purpose",
        "Lightning Fill In The Blank",
        "All the news we couldn't fit anywhere else",
        "Predictions",
        "Our panelists predict, after the success of The Odyssey, what will be the next "
        "classic piece of literature made into a movie?",
    ]
)


def _resp(status_code, text):
    return types.SimpleNamespace(status_code=status_code, text=text, encoding="utf-8")


def test_detects_video_page_headline_stack():
    assert article_extractor._looks_like_link_list(WDBJ7_VIDEO_PAGE_JUNK) is True


def test_npr_episode_rundown_is_not_flagged():
    # The segment-title stack outnumbers the prose lines, but the prose carries most of
    # the characters, so the page is a real article and must be shown.
    assert article_extractor._looks_like_link_list(NPR_WAIT_WAIT_EPISODE) is False


def test_npr_episode_rundown_is_mostly_linky_by_line():
    # Guards the premise of the fix: if this stopped tripping the line test, the
    # character-mass test would no longer be what saves the page.
    lines = [line for line in NPR_WAIT_WAIT_EPISODE.splitlines() if line.strip()]
    linky = [
        line
        for line in lines
        if len(line) <= article_extractor._LINK_LIST_MAX_LINE_LEN
        and not article_extractor._LINK_LIST_SENTENCE_END_RE.search(line)
    ]
    assert len(linky) / len(lines) >= article_extractor._LINK_LIST_MIN_FRACTION
    linky_chars = sum(len(line) for line in linky)
    total_chars = sum(len(line) for line in lines)
    assert linky_chars / total_chars < article_extractor._LINK_LIST_MIN_CHAR_FRACTION


def test_video_page_junk_is_linky_by_both_measures():
    # The junk page stays caught because it is a link stack by character mass too.
    lines = [line for line in WDBJ7_VIDEO_PAGE_JUNK.splitlines() if line.strip()]
    linky = [
        line
        for line in lines
        if len(line) <= article_extractor._LINK_LIST_MAX_LINE_LEN
        and not article_extractor._LINK_LIST_SENTENCE_END_RE.search(line)
    ]
    linky_chars = sum(len(line) for line in linky)
    total_chars = sum(len(line) for line in lines)
    assert linky_chars / total_chars >= article_extractor._LINK_LIST_MIN_CHAR_FRACTION


def test_real_sentences_are_not_flagged():
    assert article_extractor._looks_like_link_list(REAL_SHORT_ARTICLE) is False
    assert article_extractor._looks_like_link_list("") is False


def test_long_text_with_headline_lines_is_not_flagged():
    # A long article that happens to contain a related-story list must never be discarded.
    long_text = REAL_SHORT_ARTICLE * 10 + "\n" + WDBJ7_VIDEO_PAGE_JUNK
    assert len(long_text) > article_extractor._LINK_LIST_MAX_BODY_LEN
    assert article_extractor._looks_like_link_list(long_text) is False


def test_too_few_lines_are_not_flagged():
    # Short program pages (e.g. NPR daily episode pages) can be 2-3 terse lines; keep them.
    text = "\n".join(
        [
            "All Things Considered for July 6, 2026",
            "Hear the All Things Considered program for July 6, 2026",
            "Browse archive or search npr.org",
        ]
    )
    assert article_extractor._looks_like_link_list(text) is False


def test_mixed_page_below_threshold_is_not_flagged():
    # Half sentences, half headlines: below the 60% threshold, so it is kept.
    mixed = "\n".join(
        REAL_SHORT_ARTICLE.splitlines() + WDBJ7_VIDEO_PAGE_JUNK.splitlines()[:4]
    )
    assert article_extractor._looks_like_link_list(mixed) is False


def test_extract_full_article_raises_for_link_list_page(monkeypatch):
    def fake_get(url, **kwargs):
        return _resp(200, "<html><body><main>video player</main></body></html>")

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(
        article_extractor, "_extract_text_any", lambda html, url: WDBJ7_VIDEO_PAGE_JUNK
    )
    with pytest.raises(article_extractor.ExtractionError) as exc:
        article_extractor.extract_full_article(
            "https://www.wdbj7.com/video/2026/02/14/maple-ridge-apartment-fire/"
        )
    assert "no readable article text" in str(exc.value)


def test_render_falls_back_to_feed_snippet_for_link_list_page(monkeypatch):
    def fake_get(url, **kwargs):
        return _resp(200, "<html><body><main>video player</main></body></html>")

    # Only the fetched video page extracts to junk; the feed fallback must keep real extraction.
    orig_extract = article_extractor._extract_text_any

    def fake_extract(html, url):
        if "video player" in (html or ""):
            return WDBJ7_VIDEO_PAGE_JUNK
        return orig_extract(html, url)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(article_extractor, "_extract_text_any", fake_extract)
    feed_html = "<p>" + (
        "Fire crews responded to an apartment fire at Maple Ridge on Friday evening. "
        "No injuries were reported, officials said. The cause remains under investigation. "
        * 4
    ) + "</p>"
    rendered = article_extractor.render_full_article(
        "https://www.wdbj7.com/video/2026/02/14/maple-ridge-apartment-fire/",
        fallback_html=feed_html,
        fallback_title="Maple Ridge Apartment Fire",
        prefer_feed_content=False,
    )
    assert rendered is not None
    assert "Fire crews responded" in rendered
    assert "Birthdays and Anniversaries" not in rendered


def test_render_reraises_link_list_message_without_feed_content(monkeypatch):
    def fake_get(url, **kwargs):
        return _resp(200, "<html><body><main>video player</main></body></html>")

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(
        article_extractor, "_extract_text_any", lambda html, url: WDBJ7_VIDEO_PAGE_JUNK
    )
    with pytest.raises(article_extractor.ExtractionError) as exc:
        article_extractor.render_full_article(
            "https://www.wdbj7.com/video/2026/02/14/maple-ridge-apartment-fire/",
            fallback_html="",
            prefer_feed_content=False,
        )
    assert "no readable article text" in str(exc.value)
