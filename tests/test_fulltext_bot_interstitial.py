# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for graceful degradation when a page is an anti-bot / verification interstitial.

We never try to defeat these gates; we only detect them so the UI falls back to the feed snippet
plus the original link instead of saving the block-page text as the article body.
"""

import types

import core.article_extractor as article_extractor
import core.utils as utils


# Real-world Bloomberg "unusual activity" gate, served with HTTP 200.
BLOOMBERG_GATE = (
    "<html><head><title>Bloomberg - Are you a robot?</title></head><body>"
    "<h1>We've detected unusual activity from your computer network</h1>"
    "<p>To continue, please click the box below to let us know you're not a robot.</p>"
    "<p>Please make sure your browser supports JavaScript and cookies and that you are not "
    "blocking them from loading.</p>"
    "<p>Block reference ID: fc161a0a-5b85-11f1-b321-4a9f0ea8fa1e</p>"
    "</body></html>"
)

CLOUDFLARE_GATE = (
    "<html><head><title>Attention Required! | Cloudflare</title></head><body>"
    "<div class='cf-browser-verification'>Checking your browser before accessing example.com</div>"
    "</body></html>"
)

REAL_ARTICLE = (
    "<html><head><title>Anthropic Valuation</title></head><body><article>"
    "<p>" + ("Anthropic reportedly closed a funding round at a valuation that edged past its rival. " * 30) + "</p>"
    "</article></body></html>"
)


def _resp(status_code, text):
    return types.SimpleNamespace(status_code=status_code, text=text, encoding="utf-8")


def test_detects_bloomberg_unusual_activity_gate():
    assert article_extractor._looks_like_bot_interstitial(BLOOMBERG_GATE) is True


def test_detects_cloudflare_challenge():
    assert article_extractor._looks_like_bot_interstitial(CLOUDFLARE_GATE) is True


def test_detects_sky_news_bare_akamai_gate():
    body = "Powered and protected by Akamai Privacy"
    assert article_extractor._looks_like_bot_interstitial(body) is True


def test_detects_sky_news_footer_without_akamai_name_inside_large_html_shell():
    body = (
        "<html><head><style>" + (".placeholder{display:none}" * 150) + "</style></head>"
        "<body><footer><span>Powered and protected by</span><a>Privacy</a></footer></body></html>"
    )

    assert len(body) > 2000
    assert article_extractor._looks_like_bot_interstitial(body) is True


def test_detects_gate_with_curly_apostrophe():
    # Bloomberg renders the smart apostrophe in "you're"; detection must normalize it.
    body = "To continue, please click the box below to let us know you’re not a robot."
    assert article_extractor._looks_like_bot_interstitial(body) is True


def test_real_article_is_not_flagged():
    assert article_extractor._looks_like_bot_interstitial(REAL_ARTICLE) is False
    assert article_extractor._looks_like_bot_interstitial("") is False


def test_fetch_page_reports_blocked_for_http200_gate(monkeypatch):
    # Bloomberg serves the gate with a 200, and the read-proxy fallback also returns a gate.
    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, "Markdown Content:\n" + BLOOMBERG_GATE)
        return _resp(200, BLOOMBERG_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    # This covers the HTTP-level gate logic; the browser escalation is a real
    # Chromium launch and must never run from the test suite.
    monkeypatch.setattr(article_extractor, "_download_via_browser", lambda url, timeout: None)
    res = article_extractor._fetch_page("https://www.bloomberg.com/news/articles/x")
    assert res.blocked is True
    assert res.html is None


def test_fetch_page_returns_clean_page(monkeypatch):
    def fake_get(url, **kwargs):
        return _resp(200, REAL_ARTICLE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    res = article_extractor._fetch_page("https://example.com/x")
    assert res.blocked is False
    assert res.html and "Anthropic" in res.html


def test_fetch_page_proxy_recovers_blocked_page(monkeypatch):
    # Existing read-proxy fallback still works when the proxy returns real content.
    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, "Markdown Content:\nHello world recovered content.")
        return _resp(403, CLOUDFLARE_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    res = article_extractor._fetch_page("https://www.example.com/x")
    assert res.blocked is False
    assert "Hello world recovered content." in (res.html or "")


def test_bloomberg_fetch_tries_impersonation_first(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("impersonate")))
        if kwargs.get("impersonate"):
            return _resp(200, REAL_ARTICLE)
        return _resp(403, BLOOMBERG_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    res = article_extractor._fetch_page("https://www.bloomberg.com/news/articles/x")

    assert res.blocked is False
    assert "Anthropic" in (res.html or "")
    assert calls[0][1] is True


def test_bloomberg_video_gate_skips_slow_reader_fallbacks(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _resp(403, BLOOMBERG_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    res = article_extractor._fetch_page("https://www.bloomberg.com/news/videos/2026-07-09/example")

    assert res.blocked is True
    assert res.html is None
    assert not any("r.jina.ai" in url or "smry.ai" in url or "archive.org" in url for url in calls)


def test_extract_full_article_raises_blocked_message(monkeypatch):
    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, "Markdown Content:\n" + BLOOMBERG_GATE)
        return _resp(200, BLOOMBERG_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    try:
        article_extractor.extract_full_article("https://www.bloomberg.com/news/articles/x")
        assert False, "expected ExtractionError"
    except article_extractor.ExtractionError as e:
        assert "browser" in str(e).lower()


def test_gate_text_is_not_saved_as_article_body(monkeypatch):
    # The block page must never become the rendered article body.
    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, "Markdown Content:\n" + BLOOMBERG_GATE)
        return _resp(200, BLOOMBERG_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    try:
        article_extractor.extract_full_article("https://www.bloomberg.com/news/articles/x")
        assert False, "expected ExtractionError"
    except article_extractor.ExtractionError as e:
        assert "unusual activity" not in str(e).lower()


def test_render_falls_back_to_feed_snippet_when_blocked(monkeypatch):
    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, "Markdown Content:\n" + BLOOMBERG_GATE)
        return _resp(200, BLOOMBERG_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    feed_html = "<p>" + ("Anthropic's valuation reportedly passed its rival's in a new round. " * 4) + "</p>"
    rendered = article_extractor.render_full_article(
        "https://www.bloomberg.com/news/articles/x",
        fallback_html=feed_html,
        fallback_title="Anthropic Valuation Passes Rival",
        prefer_feed_content=False,
    )
    assert rendered is not None
    assert "Anthropic" in rendered
    assert "unusual activity" not in rendered.lower()


def test_render_reraises_blocked_message_without_feed_content(monkeypatch):
    # With no feed fallback, the block reason must reach the caller (the GUI shows it as the note).
    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, "Markdown Content:\n" + BLOOMBERG_GATE)
        return _resp(200, BLOOMBERG_GATE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    try:
        article_extractor.render_full_article(
            "https://www.bloomberg.com/news/articles/x",
            fallback_html="",
            prefer_feed_content=False,
        )
        assert False, "expected ExtractionError"
    except article_extractor.ExtractionError as e:
        assert "browser" in str(e).lower()
