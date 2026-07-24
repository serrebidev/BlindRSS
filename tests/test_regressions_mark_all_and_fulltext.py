# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import types
from unittest.mock import MagicMock, patch

import core.article_extractor as article_extractor
import core.utils as utils
import gui.mainframe as mainframe
from providers.miniflux import MinifluxProvider


def test_mark_all_read_prefers_provider_direct(monkeypatch):
    class Provider:
        def __init__(self):
            self.mark_read_batch = MagicMock()

        def mark_all_read(self, feed_id):
            return True

    dummy = types.SimpleNamespace()
    dummy.provider = Provider()
    dummy._collect_unread_ids_current_view = lambda _fid: ["a1", "a2"]
    dummy._collect_unread_ids = lambda _fid: ["a1", "a2", "a3"]
    dummy._should_mark_all_view = lambda _fid: True
    dummy._is_global_mark_all_view = lambda _fid: False

    results = {}

    def _post(feed_id, ok, unread_ids, err="", used_direct=False):
        results["feed_id"] = feed_id
        results["ok"] = ok
        results["unread_ids"] = unread_ids
        results["used_direct"] = used_direct

    dummy._post_mark_all_read = _post
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    mainframe.MainFrame._mark_all_read_thread(dummy, "feed-1")

    assert results["feed_id"] == "feed-1"
    assert results["used_direct"] is True
    assert results["unread_ids"] == ["a1", "a2"]
    assert dummy.provider.mark_read_batch.call_count == 0


def test_mark_all_read_falls_back_to_batch(monkeypatch):
    class Provider:
        def __init__(self):
            self.mark_read_batch = MagicMock(return_value=True)

        def mark_all_read(self, feed_id):
            return False

    dummy = types.SimpleNamespace()
    dummy.provider = Provider()
    dummy._collect_unread_ids_current_view = lambda _fid: ["a1"]
    dummy._collect_unread_ids = lambda _fid: ["a1", "a2", "a3"]
    dummy._should_mark_all_view = lambda _fid: True
    dummy._is_global_mark_all_view = lambda _fid: False

    results = {}

    def _post(feed_id, ok, unread_ids, err="", used_direct=False):
        results["feed_id"] = feed_id
        results["ok"] = ok
        results["unread_ids"] = unread_ids
        results["used_direct"] = used_direct

    dummy._post_mark_all_read = _post
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    mainframe.MainFrame._mark_all_read_thread(dummy, "feed-2")

    dummy.provider.mark_read_batch.assert_called_once()
    assert dummy.provider.mark_read_batch.call_args[0][0] == ["a1", "a2", "a3"]
    assert results["used_direct"] is False
    assert results["unread_ids"] == ["a1", "a2", "a3"]


def test_miniflux_mark_all_read_feed():
    provider = MinifluxProvider({"providers": {"miniflux": {"url": "https://example.com", "api_key": "t"}}})
    with patch.object(provider._session, "put") as put:
        put.return_value.status_code = 204
        ok = provider.mark_all_read("123")
        assert ok is True
        assert put.call_count == 1
        assert put.call_args[0][0] == "https://example.com/v1/feeds/123/mark-all-as-read"


def test_miniflux_mark_all_read_category():
    provider = MinifluxProvider({"providers": {"miniflux": {"url": "https://example.com", "api_key": "t"}}})
    provider._req = MagicMock(return_value=[{"id": 12, "title": "Tech"}])
    with patch.object(provider._session, "put") as put:
        put.return_value.status_code = 204
        ok = provider.mark_all_read("category:Tech")
        assert ok is True
        assert put.call_args[0][0] == "https://example.com/v1/categories/12/mark-all-as-read"


def test_miniflux_mark_all_read_unsupported_view():
    provider = MinifluxProvider({"providers": {"miniflux": {"url": "https://example.com", "api_key": "t"}}})
    with patch.object(provider._session, "put") as put:
        assert provider.mark_all_read("favorites:all") is False
        assert provider.mark_all_read("all") is False
        assert put.call_count == 0


def test_miniflux_delete_article_sets_removed_status():
    provider = MinifluxProvider({"providers": {"miniflux": {"url": "https://example.com", "api_key": "t"}}})
    with patch.object(provider._session, "put") as put:
        put.return_value.status_code = 204
        assert provider.supports_article_delete() is True
        assert provider.delete_article("123") is True
        assert put.call_count == 1
        assert put.call_args.kwargs["json"] == {"entry_ids": [123], "status": "removed"}




def test_download_html_cloudflare_fallback(monkeypatch):
    def _resp(status_code, text):
        return types.SimpleNamespace(status_code=status_code, text=text, encoding="utf-8")

    def fake_get(url, **kwargs):
        if "r.jina.ai" in url:
            return _resp(200, "Markdown Content:\nHello world")
        return _resp(403, "<title>Attention Required! | Cloudflare</title>")

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    html = article_extractor._download_html("https://www.techrepublic.com/article/test/")
    assert "Hello world" in html


def test_should_prefer_feed_content_skips_placeholder():
    html = "unable to retrieve full-text content" + ("x" * 3000)
    assert article_extractor._should_prefer_feed_content("https://www.techrepublic.com/article/test/", html) is False


def test_full_rss_wins_for_shortened_fraser_valley_pages():
    full_feed = "<p>" + ("Complete syndicated report. " * 40) + "</p>"
    assert article_extractor._should_prefer_feed_content(
        "https://fraservalleytoday.ca/2026/07/10/story/", full_feed
    ) is True
    assert article_extractor._should_prefer_feed_content(
        "https://fvcurrent.com/p/newsletter", full_feed
    ) is True


def test_miniflux_placeholder_entries_skipped():
    provider = MinifluxProvider({"providers": {"miniflux": {"url": "https://example.com", "api_key": "t"}}})
    entries = [
        {"id": 1, "feed_id": 10, "title": "[unable to retrieve full-text content]", "url": "http://www.techrepublic.com/rssfeeds/blogs/", "content": "<p><em>[unable to retrieve full-text content]</em></p>", "status": "read"},
        {"id": 2, "feed_id": 10, "title": "Real Entry", "url": "https://example.com/real", "content": "<p>Hi</p>", "status": "unread"},
    ]
    with patch("providers.miniflux.utils.get_chapters_batch", return_value={}):
        articles = provider._entries_to_articles(entries)
    assert len(articles) == 1
    assert articles[0].title == "Real Entry"


def test_render_full_article_falls_back_when_prefer_feed_disabled():
    calls = []

    def fake_extract(url, max_pages=6, timeout=20):
        calls.append(("extract", url))
        raise article_extractor.ExtractionError("blocked")

    def fake_fallback(html, source_url="", title="", author=""):
        calls.append(("fallback", len(html)))
        return article_extractor.FullArticle(url=source_url, title=title or "T", author=author or "A", text="Body")

    orig_extract = article_extractor.extract_full_article
    orig_fallback = article_extractor.extract_from_html
    try:
        article_extractor.extract_full_article = fake_extract
        article_extractor.extract_from_html = fake_fallback
        rendered = article_extractor.render_full_article(
            "http://example.com",
            fallback_html="<p>x</p>",
            fallback_title="T",
            fallback_author="A",
            prefer_feed_content=False,
        )
    finally:
        article_extractor.extract_full_article = orig_extract
        article_extractor.extract_from_html = orig_fallback

    assert "Title: T" in (rendered or "")
    assert calls and calls[0][0] == "extract"
    assert any(c[0] == "fallback" for c in calls)
