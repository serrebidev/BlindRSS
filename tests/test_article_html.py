# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for the embed-preserving rich-reader HTML cleaner (core.article_html)."""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from bs4 import BeautifulSoup

from core import article_html


ARTICLE = """
<html><body>
<header class="site-header"><nav><a href="/">Home</a></nav></header>
<aside class="sidebar"><ul>
<li><a href="/promo1">Trending one</a></li>
<li><a href="/promo2">Trending two</a></li>
</ul></aside>
<article>
<h1>The big story</h1>
<p>This is the opening paragraph with a <a href="/report">relative link</a> and
enough prose to be a real article body worth keeping in the cleaned output.</p>
<figure class="video">
<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?rel=0" allowfullscreen></iframe>
</figure>
<p>Closing paragraph, also with an <img src="/pics/x.jpg" alt="a chart"> image.</p>
<div class="newsletter-signup"><p>Subscribe to our newsletter!</p></div>
</article>
<div class="ticker">Live ticker: markets up ...</div>
<footer class="site-footer">Copyright</footer>
</body></html>
"""


class CleanArticleHtmlTests(unittest.TestCase):
    def setUp(self):
        self.out = article_html.clean_article_html(ARTICLE, "https://news.example.com/story")
        self.soup = BeautifulSoup(self.out, "html.parser")

    def test_keeps_article_prose(self):
        self.assertIn("opening paragraph", self.out)
        self.assertIn("Closing paragraph", self.out)

    def test_drops_sidebar_and_ticker_and_footer(self):
        self.assertNotIn("Trending one", self.out)
        self.assertNotIn("Live ticker", self.out)
        self.assertNotIn("Copyright", self.out)

    def test_drops_chrome_by_class(self):
        self.assertNotIn("newsletter", self.out.lower())

    def test_preserves_youtube_iframe_normalized(self):
        iframe = self.soup.find("iframe")
        self.assertIsNotNone(iframe)
        self.assertEqual(iframe["src"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_absolutizes_relative_link_and_image(self):
        a = self.soup.find("a", string="relative link")
        self.assertEqual(a["href"], "https://news.example.com/report")
        img = self.soup.find("img")
        self.assertEqual(img["src"], "https://news.example.com/pics/x.jpg")

    def test_strips_event_handlers_and_classes(self):
        self.assertNotIn("onclick", self.out.lower())
        self.assertNotIn("class=", self.out.lower())

    def test_empty_input_returns_empty(self):
        self.assertEqual(article_html.clean_article_html("", "u"), "")
        self.assertEqual(article_html.clean_article_html(None, "u"), "")


class EmbedNormalizationTests(unittest.TestCase):
    def test_protocol_relative_and_vimeo(self):
        html = (
            "<article><p>Body text long enough to be kept as the article body here.</p>"
            '<iframe src="//player.vimeo.com/video/12345"></iframe></article>'
        )
        out = article_html.clean_article_html(html, "https://x.example.com/a")
        self.assertIn('src="https://vimeo.com/12345"', out)

    def test_script_tags_removed(self):
        html = (
            "<article><p>Body text that is long enough to be kept as an article.</p>"
            '<script>evil()</script></article>'
        )
        out = article_html.clean_article_html(html, "https://x.example.com/a")
        self.assertNotIn("evil()", out)
        self.assertNotIn("<script", out.lower())


class SocialEmbedTests(unittest.TestCase):
    def _clean(self, body):
        html = f"<article><p>Body prose long enough to be kept as the article.</p>{body}</article>"
        return article_html.clean_article_html(html, "https://news.example.com/a")

    def test_twitter_becomes_platform_iframe(self):
        out = self._clean(
            '<blockquote class="twitter-tweet"><p>hi</p>'
            '<a href="https://twitter.com/jack/status/20">link</a></blockquote>'
        )
        self.assertIn('src="https://platform.twitter.com/embed/Tweet.html?id=20"', out)

    def test_x_domain_link(self):
        out = self._clean(
            '<blockquote class="twitter-tweet">'
            '<a href="https://x.com/user/status/1799999999999999999">t</a></blockquote>'
        )
        self.assertIn("platform.twitter.com/embed/Tweet.html?id=1799999999999999999", out)

    def test_instagram_embed(self):
        out = self._clean(
            '<blockquote class="instagram-media" '
            'data-instgrm-permalink="https://www.instagram.com/p/ABC123/"></blockquote>'
        )
        self.assertIn("instagram.com/p/ABC123/embed", out)

    def test_tiktok_embed(self):
        out = self._clean(
            '<blockquote class="tiktok-embed" '
            'cite="https://www.tiktok.com/@user/video/6718335390845095173"></blockquote>'
        )
        self.assertIn("tiktok.com/embed/v2/6718335390845095173", out)

    def test_bluesky_at_uri_embed(self):
        out = self._clean(
            '<blockquote class="bluesky-embed" '
            'data-bluesky-uri="at://did:plc:abc123/app.bsky.feed.post/xyz789">'
            '<a href="https://bsky.app/profile/user.bsky.social/post/xyz789">p</a></blockquote>'
        )
        self.assertIn("embed.bsky.app/embed/did:plc:abc123/app.bsky.feed.post/xyz789", out)

    def test_facebook_plugin_iframe(self):
        out = self._clean(
            '<div class="fb-post" data-href="https://www.facebook.com/user/posts/12345"></div>'
        )
        self.assertIn("facebook.com/plugins/post.php?href=", out)
        self.assertIn("12345", out)

    def test_mastodon_iframe_kept(self):
        out = self._clean(
            '<iframe src="https://mastodon.social/@user/109999999999999999/embed"></iframe>'
        )
        self.assertIn("mastodon.social/@user/109999999999999999/embed", out)

    def test_bluesky_handle_only_falls_back_to_link(self):
        out = self._clean(
            '<blockquote class="bluesky-embed">'
            '<a href="https://bsky.app/profile/user.bsky.social/post/xyz789">post</a></blockquote>'
        )
        # No DID available, so no iframe — but the permalink stays clickable.
        self.assertNotIn("embed.bsky.app", out)
        self.assertIn('href="https://bsky.app/profile/user.bsky.social/post/xyz789"', out)

    def test_social_wrapper_class_does_not_eat_iframe(self):
        out = self._clean(
            '<div class="social-embed twitter">'
            '<blockquote class="twitter-tweet">'
            '<a href="https://twitter.com/jack/status/20">t</a></blockquote></div>'
        )
        self.assertIn("platform.twitter.com/embed/Tweet.html?id=20", out)


class PickMainNodeTests(unittest.TestCase):
    """Sites with no <article>/<main> must still isolate the content node so
    sibling chrome (recent-articles lists, tag boxes, sponsor promos) is dropped."""

    def test_entry_class_isolates_body_and_drops_sibling_chrome(self):
        # Mirrors simonwillison.net: div.entry body with recent-articles + metabox siblings.
        html = (
            "<html><body>"
            '<div id="sponsored-banner"><a>Sponsored by SomeCo</a></div>'
            '<div id="primary">'
            '<div class="entry entryPage"><h2>Grok build</h2>'
            "<p>This is the real article body with plenty of prose so the cleaner keeps "
            "it as the main content and returns it in full to the reader.</p>"
            "<p>A second real paragraph continues the story with several more sentences "
            "of detail so the entry node comfortably clears the minimum-length bar and "
            "is chosen over the whole page body.</p></div>"
            '<div class="recent-articles"><h2>Recent articles</h2>'
            '<ul><li><a href="/x">Other unrelated story one</a> - 9th July 2026</li></ul>'
            "</div></div>"
            '<div id="secondary"><div class="metabox"><h3>Monthly briefing</h3>'
            "<p>Sponsor me for ten dollars a month.</p></div></div>"
            "</body></html>"
        )
        out = article_html.clean_article_html(html, "https://simonwillison.net/2026/Jul/15/grok-build/")
        text = BeautifulSoup(out, "html.parser").get_text(" ", strip=True)
        self.assertIn("real article body", text)
        self.assertNotIn("Recent articles", text)
        self.assertNotIn("Other unrelated story one", text)
        self.assertNotIn("Monthly briefing", text)

    def test_zero_width_characters_are_stripped(self):
        # Reuters injects zero-width spaces between words; the cleaned body must not carry them.
        html = (
            "<article><h1>T</h1><p>Amazon veteran Dave\u200bBrown is leaving after "
            "nineteen\u2060years, according to an internal\u200cmemo from the company.</p></article>"
        )
        out = article_html.clean_article_html(html, "https://www.reuters.com/x/")
        for ch in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
            self.assertNotIn(ch, out)
        self.assertIn("DaveBrown", BeautifulSoup(out, "html.parser").get_text())


class RenderFullArticleHtmlTests(unittest.TestCase):
    def test_falls_back_to_feed_content_when_no_url(self):
        feed = "<p>Feed body paragraph with enough words to render in the reader.</p>"
        out = article_html.render_full_article_html(
            "", fallback_html=feed, fallback_title="A title"
        )
        self.assertIsNotNone(out)
        self.assertIn("Feed body paragraph", out)
        self.assertIn("<h1>A title</h1>", out)

    def test_returns_none_when_nothing_to_show(self):
        out = article_html.render_full_article_html("", fallback_html="")
        self.assertIsNone(out)

    def test_follows_pagination_and_merges_pages(self):
        # A multi-page review (GSM Arena style): each page carries a "Next page"
        # link to the following page. The rich reader must render every page,
        # not just the first, matching the classic full-text view.
        from unittest import mock

        from core import article_extractor as ae

        pages = {
            "https://www.gsmarena.com/phone_review.php": (
                "<html><body><article>"
                "<h1>Phone review</h1>"
                "<p>Page one covers the design and the in-hand feel of the device at length.</p>"
                '<a class="pages-next" href="phone_review-p2.php">Next page</a>'
                "</article></body></html>"
            ),
            "https://www.gsmarena.com/phone_review-p2.php": (
                "<html><body><article>"
                "<p>Page two covers the display quality and its outdoor brightness in detail.</p>"
                '<a class="pages-next" href="phone_review-p3.php">Next page</a>'
                "</article></body></html>"
            ),
            "https://www.gsmarena.com/phone_review-p3.php": (
                "<html><body><article>"
                "<p>Page three covers battery life and the overall verdict for this phone.</p>"
                "</article></body></html>"
            ),
        }
        fetched = []

        def fake_fetch(url, timeout=20, encoding_override=""):
            fetched.append(url)
            return ae._FetchResult(html=pages.get(url, ""))

        with mock.patch.object(ae, "_fetch_page", side_effect=fake_fetch):
            out = article_html.render_full_article_html(
                "https://www.gsmarena.com/phone_review.php"
            )

        self.assertIsNotNone(out)
        text = BeautifulSoup(out, "html.parser").get_text(" ", strip=True)
        self.assertIn("Page one covers the design", text)
        self.assertIn("Page two covers the display", text)
        self.assertIn("Page three covers battery life", text)
        # All three pages were actually fetched by following the "Next page" links.
        self.assertEqual(len(fetched), 3)

    def test_pagination_stops_on_repeated_content(self):
        # If a "next" control loops back to already-seen content, the page must
        # not be appended twice.
        from unittest import mock

        from core import article_extractor as ae

        body = (
            "<html><body><article>"
            "<p>The single page of this article repeats its own next link forever here.</p>"
            '<a class="pages-next" href="loop-p2.php">Next page</a>'
            "</article></body></html>"
        )

        def fake_fetch(url, timeout=20, encoding_override=""):
            # Every URL returns the same body (a self-referential "next" loop).
            return ae._FetchResult(html=body)

        with mock.patch.object(ae, "_fetch_page", side_effect=fake_fetch):
            out = article_html.render_full_article_html(
                "https://example.com/loop.php"
            )

        self.assertIsNotNone(out)
        text = BeautifulSoup(out, "html.parser").get_text(" ", strip=True)
        self.assertEqual(text.count("The single page of this article repeats"), 1)


if __name__ == "__main__":
    unittest.main()
