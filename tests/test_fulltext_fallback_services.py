# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for the full-text fetch fallback services (Jina -> Smry.ai -> Wayback Machine).

Live proxies are tried before the Wayback Machine because the user wants the CURRENT page text;
the archive is the last resort for dead links. Services verified dead/unusable (Archive.today
CAPTCHA, Google Cache, 12ft.io) must NOT be part of the chain.
"""

import json
import types

import core.article_extractor as article_extractor
import core.utils as utils


ARTICLE_HTML = (
    "<html><head><title>Roundcube Intrusions</title></head><body><article>"
    "<p>" + ("Researchers observed intrusions against university mail servers this week. " * 30) + "</p>"
    "</article></body></html>"
)

GATE_HTML = (
    "<html><head><title>Attention Required! | Cloudflare</title></head><body>"
    "<div class='cf-browser-verification'>Checking your browser before accessing example.com</div>"
    "</body></html>"
)

SMRY_ARTICLE_SSE = (
    "event: article\n"
    "data: " + json.dumps({
        "source": "smry-fast",
        "article": {
            "title": "Roundcube Intrusions",
            "byline": "Jane Reporter",
            "content": "<p>" + ("Smry recovered the live article body for this page. " * 20) + "</p>",
            "textContent": ("Smry recovered the live article body for this page. " * 20),
        },
    }) + "\n\n"
)

SMRY_ERROR_SSE = (
    "event: error\n"
    'data: {"error":"Failed to fetch from all sources","type":"ALL_SOURCES_FAILED"}\n\n'
)

WAYBACK_AVAILABLE_JSON = json.dumps({
    "url": "https://example.com/story",
    "archived_snapshots": {
        "closest": {
            "status": "200",
            "available": True,
            "url": "http://web.archive.org/web/20260101000000/https://example.com/story",
        }
    },
})

WAYBACK_EMPTY_JSON = json.dumps({"url": "https://example.com/story", "archived_snapshots": {}})


def _resp(status_code, text, url=""):
    return types.SimpleNamespace(status_code=status_code, text=text, encoding="utf-8", url=url)


def _install_fake_get(monkeypatch, handlers):
    """handlers: list of (substring, response_or_callable); first match wins."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        for marker, resp in handlers:
            if marker in url:
                return resp(url) if callable(resp) else resp
        return _resp(404, "")

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    return calls


NEOWIN_VERIFICATION_MD = (
    "![Image 1: Icon for www.neowin.net](https://www.neowin.net/favicon.ico)\n"
    "## Performing security verification\n"
    "This website uses a security service to protect against malicious bots. "
    "This page is displayed while the website verifies you are not a bot.\n"
)


def test_neowin_security_verification_detected_as_gate():
    # Both the raw page and the read-proxy markdown rendering must be treated as a gate.
    assert article_extractor._looks_like_bot_interstitial(NEOWIN_VERIFICATION_MD) is True
    assert article_extractor._looks_like_bot_interstitial(
        "<html><body><h2>Performing security verification</h2></body></html>"
    ) is True


def test_gate_recovered_by_impersonated_refetch(monkeypatch):
    # The impersonated (real browser fingerprint) refetch is the FIRST fallback: it returns the
    # live page, so no proxy or archive should be consulted when it succeeds.
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if kwargs.get("impersonate"):
            return _resp(200, ARTICLE_HTML)
        return _resp(200, GATE_HTML)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    res = article_extractor._fetch_page("https://www.neowin.net/news/story/")
    assert res.blocked is False
    assert "university mail servers" in (res.html or "")
    assert len(calls) == 2
    assert not any("r.jina.ai" in c or "smry.ai" in c or "archive.org" in c for c in calls)


def test_sky_gate_recovered_through_live_google_translate_route(monkeypatch):
    sky_url = "https://news.sky.com/story/example-world-report-13562675"
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if "news-sky-com.translate.goog" in url:
            return _resp(200, ARTICLE_HTML)
        return _resp(403, "<html><h1>Access Denied</h1></html>")

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    res = article_extractor._fetch_page(sky_url)

    assert res.blocked is False
    assert "university mail servers" in (res.html or "")
    assert calls[1].startswith(
        "https://news-sky-com.translate.goog/story/example-world-report-13562675?"
    )
    assert "_x_tr_tl=en" in calls[1]
    assert not any("r.jina.ai" in call or "archive.org" in call for call in calls)


def test_sky_large_footer_shell_without_akamai_name_uses_translate_route(monkeypatch):
    sky_url = "https://news.sky.com/story/example-world-report-13562675"
    shell = (
        "<html><head><script>" + ("window.blocked=true;" * 150) + "</script></head>"
        "<body><footer>Powered and protected by <a>Privacy</a></footer></body></html>"
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if "news-sky-com.translate.goog" in url:
            return _resp(200, ARTICLE_HTML)
        return _resp(200, shell)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    res = article_extractor._fetch_page(sky_url)

    assert res.blocked is False
    assert "university mail servers" in (res.html or "")
    assert calls[1].startswith("https://news-sky-com.translate.goog/")


def test_sky_translate_route_rejects_akamai_footer(monkeypatch):
    gate = "Powered and protected by Akamai Privacy"
    monkeypatch.setattr(
        utils,
        "safe_requests_get",
        lambda *args, **kwargs: _resp(200, gate),
    )

    assert article_extractor._download_sky_via_google_translate(
        "https://news.sky.com/story/example-13562675", 20
    ) is None
    assert article_extractor._download_sky_via_google_translate(
        "https://example.com/story", 20
    ) is None


def test_json_ld_article_body_html_is_rendered_as_plain_text():
    payload = json.dumps(
        {
            "@type": "NewsArticle",
            "articleBody": (
                "The opening sentence is readable. "
                "<p>The second paragraph has <strong>important</strong> details.</p>"
                "<p>The final paragraph contains enough reporting to qualify as an article, "
                "including additional verified context from police and witnesses at the scene.</p>"
            ),
        }
    )
    html = f'<html><script type="application/ld+json">{payload}</script></html>'

    text = article_extractor._extract_json_ld_text(html)

    assert "The opening sentence is readable." in text
    assert "important details" in text
    assert "<p>" not in text
    assert "<strong>" not in text


def test_normalize_whitespace_removes_invisible_word_break_characters():
    assert article_extractor._normalize_whitespace("the \u200barticle \u2060body") == "the article body"


def test_impersonation_falls_through_to_safari_fingerprint(monkeypatch):
    # Cloudflare-managed challenges can 403 curl_cffi's Chrome hello but pass Safari's
    # (seen live on neowin.net); the impersonated refetch must try both.
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", True, raising=False)
    targets = []

    def fake_get(url, **kwargs):
        targets.append(kwargs.get("impersonate_target"))
        if kwargs.get("impersonate_target") == "safari184":
            return _resp(200, ARTICLE_HTML)
        return _resp(403, GATE_HTML)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    html = article_extractor._download_via_impersonation("https://www.neowin.net/news/story/", 20)
    assert html is not None and "university mail servers" in html
    assert targets == [None, "safari184"]


def test_impersonation_single_attempt_without_curl_cffi(monkeypatch):
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", False, raising=False)
    calls = _install_fake_get(monkeypatch, [("neowin.net", _resp(403, GATE_HTML))])
    assert article_extractor._download_via_impersonation("https://www.neowin.net/news/story/", 20) is None
    assert len(calls) == 1


def test_theregister_picks_story_article_over_teaser_rail():
    # The Register's page opens with teaser <article> cards ("MOST POPULAR" rail); the real story
    # is the <article> with the most paragraph text. The generic path grabs the rail, so a
    # site-specific rule must win.
    body_paras = "".join(
        f"<p>Suspected intruders breached the university mail servers in a long campaign. Paragraph {i}.</p>"
        for i in range(8)
    )
    html = (
        "<html><body>"
        "<article><p>MOST POPULAR</p><p>Some teaser headline about ChatGPT banter</p></article>"
        "<article><p>Security</p>"
        "<p>Proofpoint researcher tells The Reg it was a few dozen targets.</p>"
        + body_paras +
        "</article>"
        "</body></html>"
    )
    text = article_extractor._extract_theregister_text(html)
    assert "Suspected intruders breached" in text
    assert "MOST POPULAR" not in text
    # Leading one-word section kicker is dropped.
    assert not text.lower().startswith("security")


def test_theregister_site_rule_wins_in_extract_text_any():
    body_paras = "".join(
        f"<p>The real Register story body continues across many paragraphs here. Line {i}.</p>"
        for i in range(8)
    )
    html = (
        "<html><body>"
        "<article><p>MOST POPULAR</p><p>OpenAI makes ChatGPT better at banter</p></article>"
        "<article><p>AI + ML</p>" + body_paras + "</article>"
        "</body></html>"
    )
    out = article_extractor._extract_text_any(html, "https://www.theregister.com/2026/07/08/story/")
    assert "The real Register story body" in out
    assert "MOST POPULAR" not in out


def test_neowin_next_link_not_followed_as_pagination():
    # Neowin abuses <link rel="next"> to point at the NEXT STORY, not a continuation of this one.
    # Following it merged an unrelated article's text onto the story, so it must be suppressed —
    # like wired.com and ning.com.
    html = (
        '<html><head><link rel="next" href="/science/unrelated-display-resolution-story/"></head>'
        "<body><article><p>The real report body.</p></article></body></html>"
    )
    assert article_extractor._find_next_page(
        html, "https://www.neowin.net/reports/xbox-brand-value/"
    ) is None


def test_generic_rel_next_pagination_still_followed():
    # The suppression is host-scoped: a normal multi-page article must still paginate.
    html = '<html><head><link rel="next" href="?page=2"></head><body><article><p>x</p></article></body></html>'
    assert article_extractor._find_next_page(
        html, "https://example.com/story/"
    ) == "https://example.com/story/?page=2"


def test_response_text_tolerates_curl_cffi_read_once_encoding():
    # curl_cffi raises if encoding is set after text is read; _response_text must not lose the body.
    class Curlish:
        encoding = None
        _accessed = False

        @property
        def text(self):
            type(self)._accessed = True
            return "<html>body</html>"

        def __setattr__(self, name, value):
            if name == "encoding" and type(self)._accessed:
                raise ValueError("Cannot set encoding after text has been accessed")
            object.__setattr__(self, name, value)

    r = Curlish()
    # Access text first (as the gate check does), then _response_text must still return it.
    _ = r.text
    assert article_extractor._response_text(r) == "<html>body</html>"


def test_techradar_trailing_boilerplate_stripped():
    # Trailing block: promo -> author bio -> two-line comment gate. All must go; body stays.
    body = (
        "The G6 is my pick for bright rooms this year.\n\n"
        "There is always a trade-off between reflection reduction and image accuracy.\n\n"
        "Follow TechRadar on Google News and add us as a preferred source to get our expert "
        "news, reviews, and opinion in your feeds.\n\n"
        "James is the TV Hardware Staff Writer at TechRadar. When not writing about TV tech, "
        "James can be found gaming, reading, or watching rugby.\n\n"
        "You must confirm your public display name before commenting\n\n"
        "Please logout and then login again, you will then be prompted to enter your display name."
    )
    out = article_extractor._postprocess_extracted_text(body, "https://www.techradar.com/televisions/x")
    assert "bright rooms this year" in out
    assert "trade-off between reflection" in out
    assert "Follow TechRadar" not in out
    assert "TV Hardware Staff Writer" not in out  # author bio
    assert "You must confirm" not in out
    assert "Please logout" not in out


def test_techradar_signup_promo_variant_stripped():
    # Some articles use "Sign up for breaking news ..." as the trailing promo instead of "Follow".
    body = (
        "The AirPods Max remain expensive but sound superb.\n\n"
        "Sign up for breaking news, reviews, opinion, top tech deals, and more.\n\n"
        "Max is a senior staff writer for TechRadar who covers home entertainment and audio.\n\n"
        "You must confirm your public display name before commenting\n\n"
        "Please logout and then login again, you will then be prompted to enter your display name."
    )
    out = article_extractor._postprocess_extracted_text(body, "https://www.techradar.com/audio/x")
    assert "sound superb" in out
    assert "Sign up for breaking news" not in out
    assert "senior staff writer for TechRadar" not in out  # author bio
    assert "You must confirm" not in out


def test_techradar_inline_signup_widget_removed_without_cutting_body():
    # The "Sign up ..." newsletter widget also appears INLINE mid-article; removing it must not
    # truncate the real paragraphs that follow it.
    body = (
        "Intro paragraph about the OLED comparison test.\n\n"
        "Sign up for breaking news, reviews, opinion, top tech deals, and more.\n\n"
        "On the G6, the shape of the light was still legible after the test.\n\n"
        "Even on a blank screen you could see reflected objects.\n\n"
        "James is the TV Hardware Staff Writer at TechRadar and can be found watching rugby.\n\n"
        "You must confirm your public display name before commenting\n\n"
        "Please logout and then login again, you will then be prompted to enter your display name."
    )
    out = article_extractor._postprocess_extracted_text(body, "https://www.techradar.com/televisions/x")
    assert "Intro paragraph about the OLED" in out
    assert "shape of the light was still legible" in out  # content AFTER the inline widget survives
    assert "Even on a blank screen" in out
    assert "Sign up for breaking news" not in out
    assert "TV Hardware Staff Writer" not in out  # author bio still stripped
    assert "You must confirm" not in out


def test_wsj_boilerplate_stripped():
    body = (
        "Jeff Bezos' space company is raising capital.\n\n"
        "Blue Origin is working on a $10 billion round.\n\n"
        "Copyright ©2026 Dow Jones & Company, Inc. All Rights Reserved. "
        "87990cbe856818d5eddac44c7b1cdeb8"
    )
    out = article_extractor._postprocess_extracted_text(body, "https://www.wsj.com/business/x")
    assert "Blue Origin" in out
    assert "Dow Jones" not in out
    assert "87990cbe" not in out


def test_wayback_raw_url_rewrite():
    raw = article_extractor._wayback_raw_url(
        "https://web.archive.org/web/20260101000000/https://example.com/story"
    )
    assert raw == "https://web.archive.org/web/20260101000000id_/https://example.com/story"
    # Already-raw and non-wayback URLs pass through unchanged.
    assert article_extractor._wayback_raw_url(raw) == raw
    assert article_extractor._wayback_raw_url("https://example.com/x") == "https://example.com/x"


def test_smry_parses_article_event(monkeypatch):
    _install_fake_get(monkeypatch, [("smry.ai/api/article", _resp(200, SMRY_ARTICLE_SSE))])
    html = article_extractor._download_via_smry("https://example.com/story", 20)
    assert html is not None
    assert "Smry recovered the live article body" in html
    assert "<title>Roundcube Intrusions</title>" in html
    assert 'content="Jane Reporter"' in html


def test_smry_error_event_returns_none(monkeypatch):
    _install_fake_get(monkeypatch, [("smry.ai/api/article", _resp(200, SMRY_ERROR_SSE))])
    assert article_extractor._download_via_smry("https://example.com/story", 20) is None


def test_smry_short_teaser_rejected(monkeypatch):
    sse = (
        "event: article\n"
        'data: {"article": {"title": "T", "content": "<p>Tiny teaser.</p>", "textContent": "Tiny teaser."}}\n\n'
    )
    _install_fake_get(monkeypatch, [("smry.ai/api/article", _resp(200, sse))])
    assert article_extractor._download_via_smry("https://example.com/story", 20) is None


def test_gate_falls_back_to_smry(monkeypatch):
    calls = _install_fake_get(monkeypatch, [
        ("r.jina.ai", _resp(500, "")),
        ("smry.ai/api/article", _resp(200, SMRY_ARTICLE_SSE)),
        ("example.com/story", _resp(200, GATE_HTML)),
    ])
    res = article_extractor._fetch_page("https://example.com/story")
    assert res.blocked is False
    assert "Smry recovered the live article body" in (res.html or "")
    # Live proxy order: jina before smry; wayback untouched once smry succeeds.
    assert any("r.jina.ai" in c for c in calls)
    assert not any("archive.org" in c for c in calls)


def test_dead_link_falls_back_to_wayback(monkeypatch):
    calls = _install_fake_get(monkeypatch, [
        ("smry.ai/api/article", _resp(200, SMRY_ERROR_SSE)),
        ("archive.org/wayback/available", _resp(200, WAYBACK_AVAILABLE_JSON)),
        ("web.archive.org/web/20260101000000id_/", _resp(200, ARTICLE_HTML)),
        ("example.com/story", _resp(404, "not found")),
    ])
    res = article_extractor._fetch_page("https://example.com/story")
    assert res.blocked is False
    assert "university mail servers" in (res.html or "")
    # Jina is reserved for anti-bot gates; a plain 404 must not hit it.
    assert not any("r.jina.ai" in c for c in calls)
    # The raw (id_) snapshot form was requested.
    assert any("id_/" in c for c in calls)


def test_gate_with_all_fallbacks_failing_reports_blocked(monkeypatch):
    _install_fake_get(monkeypatch, [
        ("r.jina.ai", _resp(200, "Markdown Content:\n" + GATE_HTML)),
        ("smry.ai/api/article", _resp(200, SMRY_ERROR_SSE)),
        ("archive.org/wayback/available", _resp(200, WAYBACK_EMPTY_JSON)),
        ("example.com/story", _resp(200, GATE_HTML)),
    ])
    res = article_extractor._fetch_page("https://example.com/story")
    assert res.blocked is True
    assert res.html is None


def test_plain_failure_with_all_fallbacks_failing_is_not_blocked(monkeypatch):
    _install_fake_get(monkeypatch, [
        ("smry.ai/api/article", _resp(500, "")),
        ("archive.org/wayback/available", _resp(200, WAYBACK_EMPTY_JSON)),
        ("example.com/story", _resp(404, "not found")),
    ])
    res = article_extractor._fetch_page("https://example.com/story")
    assert res.blocked is False
    assert res.html is None


def test_direct_success_skips_all_fallbacks(monkeypatch):
    calls = _install_fake_get(monkeypatch, [
        ("example.com/story", _resp(200, ARTICLE_HTML)),
    ])
    res = article_extractor._fetch_page("https://example.com/story")
    assert res.blocked is False
    assert "university mail servers" in (res.html or "")
    assert len(calls) == 1


def test_wayback_gate_snapshot_rejected(monkeypatch):
    # An archived copy of a Cloudflare gate must not be stored as article text.
    _install_fake_get(monkeypatch, [
        ("smry.ai/api/article", _resp(200, SMRY_ERROR_SSE)),
        ("archive.org/wayback/available", _resp(200, WAYBACK_AVAILABLE_JSON)),
        ("web.archive.org/web/", _resp(200, GATE_HTML)),
        ("example.com/story", _resp(404, "not found")),
    ])
    res = article_extractor._fetch_page("https://example.com/story")
    assert res.blocked is False
    assert res.html is None


def test_impersonation_does_not_contradict_a_pinned_session_fingerprint(monkeypatch):
    # A site we hold a browser session for pins that browser's User-Agent onto
    # every request. Cycling Chrome and Safari handshakes underneath a Firefox
    # UA is a self-contradicting fingerprint that cannot pass and reads as
    # forged, so only the matching handshake is sent.
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", True, raising=False)
    monkeypatch.setattr(utils, "_site_cookie_impersonation", lambda url: "firefox")
    targets = []

    def fake_get(url, **kwargs):
        targets.append(kwargs.get("impersonate_target"))
        return _resp(200, ARTICLE_HTML)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    article_extractor._download_via_impersonation("https://forum.audiogames.net/topic/1/x/", 20)
    assert targets == ["firefox"]
