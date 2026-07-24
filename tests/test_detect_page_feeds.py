# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Issue #76: detect feeds on a webpage via <link rel="alternate"> scanning."""

import types

import pytest

import core.discovery as discovery
import core.utils as utils


PAGE = """<!doctype html>
<html><head>
<title>Example Site</title>
<link rel="alternate" type="application/rss+xml" title="Example News" href="/feeds/news.xml">
<link rel="alternate" type="application/atom+xml" href="https://example.com/atom.xml">
<link rel="alternate" type="application/feed+json" title="JSON Feed" href="/feed.json">
<link rel="alternate" type="text/html" title="Not a feed" href="/mobile">
<link rel="stylesheet" type="application/rss+xml" href="/styles.css">
<link rel="alternate" type="application/rss+xml" href="">
<link rel="alternate" type="application/rss+xml" href="/feeds/news.xml">
</head><body><p>hello</p></body></html>
"""


def _resp(status_code, body, content_type="text/html; charset=utf-8", url="https://example.com/page"):
    data = body if isinstance(body, bytes) else body.encode("utf-8")
    return types.SimpleNamespace(
        status_code=status_code,
        content=data,
        text=data.decode("utf-8", "replace"),
        headers={"Content-Type": content_type},
        url=url,
    )


def test_detects_feed_links_with_titles_and_fallbacks(monkeypatch):
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(200, PAGE))
    feeds = discovery.detect_page_feeds("https://example.com/page")
    assert [(f["title"], f["url"]) for f in feeds] == [
        ("Example News", "https://example.com/feeds/news.xml"),
        ("", "https://example.com/atom.xml"),
        ("JSON Feed", "https://example.com/feed.json"),
    ]


def test_no_feeds_returns_empty_list(monkeypatch):
    monkeypatch.setattr(
        utils, "safe_requests_get",
        lambda url, **kw: _resp(200, "<html><head><title>x</title></head><body>plain</body></html>"),
    )
    assert discovery.detect_page_feeds("https://example.com/") == []


def test_fetch_failure_raises_page_fetch_error(monkeypatch):
    def boom(url, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(utils, "safe_requests_get", boom)
    monkeypatch.setattr(discovery, "_impersonated_discovery_retry", lambda url, t: None)
    with pytest.raises(discovery.PageFetchError):
        discovery.detect_page_feeds("https://example.com/", browser_fallback_enabled=False)


def test_http_error_raises_page_fetch_error(monkeypatch):
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(404, "not found"))
    monkeypatch.setattr(discovery, "_impersonated_discovery_retry", lambda url, t: None)
    with pytest.raises(discovery.PageFetchError):
        discovery.detect_page_feeds(
            "https://example.com/missing", browser_fallback_enabled=False
        )


def test_feed_url_input_returns_itself(monkeypatch):
    rss = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'
    monkeypatch.setattr(
        utils, "safe_requests_get",
        lambda url, **kw: _resp(200, rss, content_type="application/rss+xml", url="https://example.com/rss"),
    )
    feeds = discovery.detect_page_feeds("https://example.com/rss")
    assert feeds == [{"title": "", "url": "https://example.com/rss"}]


def test_scheme_is_added_when_missing(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen["url"] = url
        return _resp(200, PAGE)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    discovery.detect_page_feeds("example.com/page")
    assert seen["url"].startswith("https://")


def test_cloudflare_error_uses_browser_page_and_finds_all_feeds(monkeypatch):
    challenged = _resp(
        403,
        "<html><title>Just a moment...</title><script>_cf_chl_opt={}</script></html>",
        url="https://forum.example/",
    )
    page = """<html><head>
    <link rel="alternate" type="application/rss+xml" title="Topics RSS" href="/feed/rss/">
    <link rel="alternate" type="application/atom+xml" title="Topics Atom" href="/feed/atom/">
    <link rel="alternate" type="application/rss+xml" title="Posts RSS" href="/posts_feed/rss/">
    <link rel="alternate" type="application/atom+xml" title="Posts Atom" href="/posts_feed/atom/">
    </head><body></body></html>"""
    browser_calls = []

    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: challenged)
    monkeypatch.setattr(discovery, "_impersonated_discovery_retry", lambda url, t: None)
    from core import browser_feed

    monkeypatch.setattr(
        browser_feed,
        "fetch_page",
        lambda url, **kwargs: browser_calls.append((url, kwargs))
        or browser_feed.BrowserPageResponse(page, "https://forum.example/"),
    )

    feeds = discovery.detect_page_feeds("https://forum.example", browser_timeout=47)

    assert [feed["url"] for feed in feeds] == [
        "https://forum.example/feed/rss/",
        "https://forum.example/feed/atom/",
        "https://forum.example/posts_feed/rss/",
        "https://forum.example/posts_feed/atom/",
    ]
    assert browser_calls == [("https://forum.example", {"timeout_s": 47.0})]


CHANNEL_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCbwQ-rcQimbVHnJ6EXMjUHw"


@pytest.mark.parametrize(
    "page_url",
    [
        "https://www.youtube.com/@rezanajarzadeh/featured",
        "https://www.youtube.com/@rezanajarzadeh",
        "https://www.youtube.com/@rezanajarzadeh/videos",
        "https://www.youtube.com/c/SomeChannel",
        "https://www.youtube.com/user/SomeUser",
        "https://www.youtube.com/channel/UCbwQ-rcQimbVHnJ6EXMjUHw",
    ],
)
def test_youtube_channel_pages_resolve_to_native_feed(monkeypatch, page_url):
    """Channel URLs must not depend on YouTube serving the RSS <link> tag."""

    def unexpected_get(url, **kw):
        raise AssertionError(f"channel detection must not fetch the page: {url}")

    monkeypatch.setattr(utils, "safe_requests_get", unexpected_get)
    monkeypatch.setattr(discovery, "get_ytdlp_feed_url", lambda url: CHANNEL_FEED)

    assert discovery.detect_page_feeds(page_url) == [{"title": "", "url": CHANNEL_FEED}]


def test_youtube_playlist_page_resolves_to_native_feed(monkeypatch):
    playlist_feed = "https://www.youtube.com/feeds/videos.xml?playlist_id=PL123"
    monkeypatch.setattr(
        utils, "safe_requests_get",
        lambda url, **kw: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )
    monkeypatch.setattr(discovery, "get_ytdlp_feed_url", lambda url: playlist_feed)
    feeds = discovery.detect_page_feeds("https://www.youtube.com/playlist?list=PL123")
    assert feeds == [{"title": "", "url": playlist_feed}]


@pytest.mark.parametrize(
    "page_url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/results?search_query=news",
    ],
)
def test_youtube_non_channel_pages_still_scrape_html(monkeypatch, page_url):
    """A single video or a search page has no channel feed: fall through."""
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(200, PAGE))
    monkeypatch.setattr(
        discovery, "get_ytdlp_feed_url",
        lambda url: (_ for _ in ()).throw(AssertionError("must not resolve a channel")),
    )
    feeds = discovery.detect_page_feeds(page_url)
    assert [f["url"] for f in feeds] == [
        "https://example.com/feeds/news.xml",
        "https://example.com/atom.xml",
        "https://example.com/feed.json",
    ]


def test_unresolvable_youtube_channel_falls_back_to_page_scan(monkeypatch):
    """yt-dlp failing must not turn Detect Feeds into a dead end."""
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(200, PAGE))
    monkeypatch.setattr(discovery, "get_ytdlp_feed_url", lambda url: None)
    feeds = discovery.detect_page_feeds("https://www.youtube.com/@nobody")
    assert [f["url"] for f in feeds] == [
        "https://example.com/feeds/news.xml",
        "https://example.com/atom.xml",
        "https://example.com/feed.json",
    ]


def test_non_ascii_titles_survive_missing_charset_header(monkeypatch):
    page = ('<html><head><meta charset="windows-1251">'
            '<link rel="alternate" type="application/rss+xml" title="Новости" href="/rss">'
            "</head><body></body></html>").encode("cp1251")
    monkeypatch.setattr(
        utils, "safe_requests_get",
        lambda url, **kw: _resp(200, page, content_type="text/html"),
    )
    feeds = discovery.detect_page_feeds("https://example.com/")
    assert feeds and feeds[0]["title"] == "Новости"
