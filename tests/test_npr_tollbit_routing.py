# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""NPR's TollBit pay-per-crawl gate and the ungated routes around it.

npr.org answers story-page requests it does not recognize as a person's browser with
HTTP 402 and a TollBit JSON body, so the reader has to reach the story through NPR's
text-only edition and the audio through NPR's syndication player. All fixtures are
static — no network."""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import article_extractor, npr, utils


TOLLBIT_BODY = (
    '[{"message":"You are not authorized to access this content without a valid '
    'TollBit Token. Please follow this URL to find out more.","url":"https://tollbit.dev",'
    '"metadata":{"ak_ref_id":"18.44951eb8.1786599188.36b7547"}}]'
)

STORY_URL = (
    "https://www.npr.org/2026/08/12/nx-s1-5923944/"
    "budget-cuts-have-reduced-efforts-to-find-and-recover-vietnam-war-troops"
)

TEXT_ONLY_HTML = (
    "<!DOCTYPE html><html lang=\"en\"><head>"
    "<title>Budget cuts have reduced efforts to find and recover Vietnam War troops</title>"
    "</head><body>"
    '<header><p>Text-Only Version <a class="full-version-link" '
    'href="https://www.npr.org/nx-s1-5923944">Go To Full Site</a></p></header>'
    '<main><article><div class="story-container">'
    '<div class="story-head"><h1 class="story-title">Budget cuts have reduced efforts to '
    "find and recover Vietnam War troops</h1><p>By Jay Price</p></div>"
    '<div class="paragraphs-container"><h3>Transcript</h3>'
    "<p>JUANA SUMMERS, HOST: Budget cuts have sharply reduced the Defense Department's "
    "efforts to find and recover troops missing in previous conflicts, and the impact is "
    "hitting one group of families especially hard.<p>"
    "<p>JAY PRICE, BYLINE: Raymond Echevarria Jr. of Roxboro, North Carolina, was four "
    "years old in 1966 when his father was reported missing in Laos.<p>"
    "</div></div></article></main></body></html>"
)

# The embed player carries the on-demand MP3 inside a JSON blob, so its slashes arrive
# backslash-escaped and its query separators HTML-escaped.
EMBED_HTML = (
    '<!doctype html><html><body><script>window.NPR={"audio":{"audioUrl":'
    '"https:\\/\\/ondemand.npr.org\\/anon.npr-mp3\\/npr\\/atc\\/2026\\/08\\/'
    '20260812_atc_vietnam_mia_budget.mp3?t=progseg&amp;e=nx-s1-5911076&amp;p=2&amp;seg=6"'
    "}};</script></body></html>"
)

EXPECTED_MP3 = (
    "https://ondemand.npr.org/anon.npr-mp3/npr/atc/2026/08/"
    "20260812_atc_vietnam_mia_budget.mp3?t=progseg&e=nx-s1-5911076&p=2&seg=6"
)


class _Response:
    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.url = ""


class StoryIdTests(unittest.TestCase):
    def test_reads_the_id_from_every_url_shape_npr_publishes(self):
        cases = {
            STORY_URL: "nx-s1-5923944",
            # Edition suffix (an encore run of an earlier segment).
            "https://www.npr.org/2026/08/12/nx-s1-5921392-e1/months-after": "nx-s1-5921392-e1",
            "https://www.npr.org/sections/health-shots/2026/08/12/nx-s1-5929189/x": "nx-s1-5929189",
            # Legacy all-digit IDs.
            "https://www.npr.org/2023/05/01/1173000000/some-slug": "1173000000",
            "https://www.npr.org/nx-s1-5923944": "nx-s1-5923944",
            "https://www.npr.org/transcripts/nx-s1-5923944": "nx-s1-5923944",
            "https://www.npr.org/templates/story/story.php?storyId=nx-s1-5923944": "nx-s1-5923944",
        }
        for url, expected in cases.items():
            self.assertEqual(npr.story_id_from_url(url), expected, url)

    def test_refuses_urls_that_are_not_a_single_story(self):
        # Returning an ID for any of these would send the reader to an unrelated story,
        # or (for text.npr.org itself) route the fetch back into itself.
        for url in (
            "https://text.npr.org/nx-s1-5923944",
            "https://www.npr.org/sections/politics/",
            "https://www.npr.org/",
            "https://example.com/2026/08/12/nx-s1-5923944/x",
            "",
        ):
            self.assertEqual(npr.story_id_from_url(url), "", url)

    def test_text_only_url_is_built_from_the_id(self):
        self.assertEqual(npr.text_only_url(STORY_URL), "https://text.npr.org/nx-s1-5923944")
        self.assertEqual(npr.text_only_url("https://www.npr.org/sections/politics/"), "")


class TextOnlyRoutingTests(unittest.TestCase):
    def test_story_page_is_fetched_from_the_text_edition_not_the_gated_page(self):
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            if url.startswith("https://text.npr.org/"):
                return _Response(200, TEXT_ONLY_HTML)
            return _Response(402, TOLLBIT_BODY)

        original = utils.safe_requests_get
        utils.safe_requests_get = fake_get
        try:
            result = article_extractor._fetch_page(STORY_URL, timeout=5)
        finally:
            utils.safe_requests_get = original

        self.assertFalse(result.blocked)
        self.assertIn("JAY PRICE, BYLINE", result.html or "")
        self.assertEqual(requested, ["https://text.npr.org/nx-s1-5923944"])

    def test_extracted_body_keeps_the_transcript(self):
        text = article_extractor._extract_text_any(TEXT_ONLY_HTML, "https://text.npr.org/nx-s1-5923944")
        self.assertIn("Raymond Echevarria Jr.", text)
        self.assertIn("JUANA SUMMERS", text)
        # The extraction must not be mistaken for a nav stack or a gate, either of which
        # would make the reader fall back to the feed's one-line description.
        self.assertFalse(article_extractor._looks_like_link_list(text))
        self.assertFalse(article_extractor._looks_like_bot_interstitial(text))

    def test_falls_through_to_the_normal_chain_when_the_text_edition_has_no_story(self):
        # NPR serves the same shell for an unknown ID; treating that as the article would
        # show the reader an empty page instead of trying the ordinary fetch.
        def fake_get(url, **kwargs):
            if url.startswith("https://text.npr.org/"):
                return _Response(200, "<html><body><header>Text-Only Version</header></body></html>")
            return _Response(200, "<html><body><p>Live page body.</p></body></html>")

        original = utils.safe_requests_get
        utils.safe_requests_get = fake_get
        try:
            result = article_extractor._fetch_page(STORY_URL, timeout=5)
        finally:
            utils.safe_requests_get = original
        self.assertIn("Live page body.", result.html or "")

    def test_non_npr_urls_are_untouched(self):
        def fake_get(url, **kwargs):
            return _Response(200, "<html><body><p>Other site.</p></body></html>")

        original = utils.safe_requests_get
        utils.safe_requests_get = fake_get
        try:
            result = article_extractor._fetch_page("https://example.com/story", timeout=5)
        finally:
            utils.safe_requests_get = original
        self.assertIn("Other site.", result.html or "")


class GateClassificationTests(unittest.TestCase):
    def test_tollbit_body_is_recognised_as_a_gate(self):
        self.assertTrue(article_extractor._looks_like_bot_interstitial(TOLLBIT_BODY))

    def test_metering_and_rate_limit_codes_count_as_gates(self):
        # 402 is TollBit's; a gated response has to run the full fallback chain and report
        # itself as a block instead of "offline, or connection problem".
        for code in (402, 403, 429, 451, 503):
            self.assertIn(code, article_extractor._GATE_STATUS_CODES)
        # 401 is a real credential prompt - a headless browser launch cannot satisfy it.
        self.assertNotIn(401, article_extractor._GATE_STATUS_CODES)

    def test_a_402_page_reports_itself_as_blocked(self):
        def fake_get(url, **kwargs):
            return _Response(402, TOLLBIT_BODY)

        original = utils.safe_requests_get
        originals = {
            name: getattr(article_extractor, name)
            for name in (
                "_download_via_impersonation",
                "_download_via_jina",
                "_download_via_smry",
                "_download_via_wayback",
                "_download_via_browser",
            )
        }
        utils.safe_requests_get = fake_get
        for name in originals:
            setattr(article_extractor, name, lambda *a, **k: None)
        try:
            # A non-story npr.org URL skips the text-edition route, so this exercises the
            # generic gate handling rather than the NPR one.
            result = article_extractor._fetch_page("https://www.npr.org/sections/politics/", timeout=5)
        finally:
            utils.safe_requests_get = original
            for name, fn in originals.items():
                setattr(article_extractor, name, fn)
        self.assertTrue(result.blocked)


class AudioExtractionTests(unittest.TestCase):
    def test_audio_comes_from_the_embed_player_while_the_story_page_is_gated(self):
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            if "/player/embed/" in url:
                return _Response(200, EMBED_HTML)
            return _Response(402, TOLLBIT_BODY)

        original = utils.safe_requests_get
        utils.safe_requests_get = fake_get
        try:
            url, media_type = npr.extract_npr_audio(STORY_URL, timeout_s=5)
        finally:
            utils.safe_requests_get = original

        self.assertEqual(url, EXPECTED_MP3)
        self.assertEqual(media_type, "audio/mpeg")
        # Feed refresh calls this once per NPR article, so the common case must stay at
        # a single request.
        self.assertEqual(len(requested), 1)

    def test_falls_back_to_the_story_page_when_the_player_has_no_audio(self):
        story_html = (
            '<html><body><a class="audio-module-listen" '
            'href="https://ondemand.npr.org/anon.npr-mp3/npr/atc/x.mp3">Listen</a>'
            "</body></html>"
        )

        def fake_get(url, **kwargs):
            if "/player/embed/" in url:
                return _Response(200, "<html><body>no audio here</body></html>")
            return _Response(200, story_html)

        original = utils.safe_requests_get
        utils.safe_requests_get = fake_get
        try:
            url, media_type = npr.extract_npr_audio(STORY_URL, timeout_s=5)
        finally:
            utils.safe_requests_get = original
        self.assertEqual(url, "https://ondemand.npr.org/anon.npr-mp3/npr/atc/x.mp3")
        self.assertEqual(media_type, "audio/mpeg")

    def test_returns_nothing_rather_than_raising_when_every_route_is_gated(self):
        def fake_get(url, **kwargs):
            return _Response(402, TOLLBIT_BODY)

        original = utils.safe_requests_get
        utils.safe_requests_get = fake_get
        try:
            self.assertEqual(npr.extract_npr_audio(STORY_URL, timeout_s=5), (None, None))
        finally:
            utils.safe_requests_get = original


if __name__ == "__main__":
    unittest.main()
