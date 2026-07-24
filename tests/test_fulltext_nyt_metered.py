# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""New York Times (DataDome + metered paywall) full-text and rich-view regressions.

NYT refuses every plain and TLS-impersonated request with a DataDome 403 and is
refused outright by the read-proxies, so the invisible-browser escalation is the
only way the reader ever sees the page. Once fetched, two more things used to go
wrong: the rich view deleted the whole article, and a truncated free preview was
shown as if it were the complete story.
"""

import types

import core.article_extractor as article_extractor
import core.article_html as article_html
import core.utils as utils


# DataDome's block document: HTTP 403, no human-readable gate sentence beyond the
# ad-blocker line, everything else is its CAPTCHA loader.
DATADOME_BLOCK = (
    '<html lang="en"><head><title>nytimes.com</title></head><body style="margin:0">'
    '<p id="cmsg">Please enable JS and disable any ad blocker</p>'
    "<script data-cfasync=\"false\">var dd={'rt':'i','cid':'AHrlqAAA',"
    "'host':'geo.captcha-delivery.com'}</script>"
    '<script data-cfasync="false" src="https://ct.captcha-delivery.com/i.js"></script>'
    "</body></html>"
)

# NYT's article body wrapper. `meteredContent` is the real class name on the
# element that holds the prose.
_PARAGRAPHS = (
    "<p>Government authorities in Guyana said on Monday night that the bodies of at "
    "least 27 people, including four children, had been found after a ferry thought "
    "to be overloaded capsized over the weekend.</p>"
    "<p>The ferry capsized late Saturday night while on a regularly scheduled route "
    "from Georgetown, the capital, to the remote gold-mining outpost of Port Kaituma, "
    "in northwestern Guyana.</p>"
    "<p>The ferry is thought to have been carrying 179 people, including crew members, "
    "according to Guyanese authorities, but the official manifest for the state-run "
    "ferry showed only 133 people aboard.</p>"
)

_CUTOFF_NOTE = (
    '<p aria-live="polite" role="note">'
    '<a href="https://www.nytimes.com/subscription">Subscribe to The Times</a>'
    " to read as many articles as you like.</p>"
)


def _nyt_page(*, truncated: bool) -> str:
    return (
        '<html lang="en"><head><title>At Least 27 Dead in Guyana - The New York Times</title>'
        '<meta name="byl" content="By Simon Romero">'
        '<meta property="article:author" content="https://www.nytimes.com/by/simon-romero">'
        '</head><body>'
        '<main id="site-content" data-paywall-inert="" inert="" aria-hidden="true"></main>'
        '<article id="story"><section name="articleBody">'
        '<div class="meteredContent css-6wov7h">'
        + _PARAGRAPHS
        + (_CUTOFF_NOTE if truncated else "")
        + "</div></section></article></body></html>"
    )


NYT_TRUNCATED = _nyt_page(truncated=True)
NYT_COMPLETE = _nyt_page(truncated=False)

NYT_URL = "https://www.nytimes.com/2026/07/20/world/americas/guyana-ferry-sinking-barima.html"


def _resp(status_code, text):
    return types.SimpleNamespace(status_code=status_code, text=text, encoding="utf-8")


def test_datadome_block_is_recognized_as_a_gate():
    # Nothing in the body matches the Cloudflare/Akamai wording, so without the
    # DataDome markers a 200-served block would be stored as article text.
    assert article_extractor._looks_like_bot_interstitial(DATADOME_BLOCK) is True


def test_fetch_page_escalates_to_the_browser_when_http_is_gated(monkeypatch):
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(403, DATADOME_BLOCK))
    for name in (
        "_download_via_impersonation",
        "_download_via_jina",
        "_download_via_smry",
        "_download_via_wayback",
    ):
        monkeypatch.setattr(article_extractor, name, lambda url, timeout: None)
    monkeypatch.setattr(
        article_extractor, "_download_via_browser", lambda url, timeout: NYT_TRUNCATED
    )

    res = article_extractor._fetch_page(NYT_URL)

    assert res.blocked is False
    assert res.html == NYT_TRUNCATED


def test_browser_escalation_is_skipped_when_no_gate_was_seen(monkeypatch):
    # A plain connection failure must never pay for a Chromium launch.
    def fail(url, **kw):
        raise OSError("connection reset")

    monkeypatch.setattr(utils, "safe_requests_get", fail)
    for name in (
        "_download_via_impersonation",
        "_download_via_jina",
        "_download_via_smry",
        "_download_via_wayback",
    ):
        monkeypatch.setattr(article_extractor, name, lambda url, timeout: None)

    launched = []

    def spy(url, timeout):
        launched.append(url)
        return NYT_TRUNCATED

    monkeypatch.setattr(article_extractor, "_download_via_browser", spy)

    res = article_extractor._fetch_page(NYT_URL)

    assert launched == []
    assert res.html is None


def test_rich_view_keeps_the_metered_content_body():
    # `meteredContent` used to match the _CHROME_RE `meter` token, which deleted
    # the entire article and left the rich reader with nothing to show.
    body = article_html.clean_article_html(NYT_COMPLETE, NYT_URL)

    assert "bodies of at least 27 people" in body
    assert "official manifest" in body


def test_byline_meta_is_read_when_trafilatura_finds_no_author():
    _, author = article_extractor._extract_title_author_from_meta(NYT_COMPLETE, NYT_URL)

    # "By " prefix stripped, and the article:author profile URL never used as a name.
    assert author == "Simon Romero"


def test_truncated_preview_is_detected_but_the_full_render_is_not():
    assert article_extractor._looks_like_metered_preview(NYT_TRUNCATED) is True
    # The full render still carries `data-paywall-inert`, so keying on that
    # attribute would mislabel a complete article as a preview.
    assert "data-paywall-inert" in NYT_COMPLETE
    assert article_extractor._looks_like_metered_preview(NYT_COMPLETE) is False


def test_truncated_preview_text_explains_why_it_stops(monkeypatch):
    monkeypatch.setattr(
        article_extractor,
        "_fetch_page",
        lambda url, timeout=20: article_extractor._FetchResult(html=NYT_TRUNCATED),
    )

    article = article_extractor.extract_full_article(NYT_URL)

    assert "official manifest" in article.text
    assert article.text.rstrip().endswith(article_extractor.metered_preview_notice())


def test_complete_article_text_gets_no_preview_notice(monkeypatch):
    monkeypatch.setattr(
        article_extractor,
        "_fetch_page",
        lambda url, timeout=20: article_extractor._FetchResult(html=NYT_COMPLETE),
    )

    article = article_extractor.extract_full_article(NYT_URL)

    assert article_extractor.metered_preview_notice() not in article.text
