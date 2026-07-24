# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from types import SimpleNamespace

from bs4 import BeautifulSoup

from core import article_extractor, article_html, discovery, utils


THREAD_URL = "https://rblind.com/post/26660244"


def _post_payload(post_id=26660244):
    return {
        "post_view": {
            "post": {
                "id": post_id,
                "name": "Accessible discussion",
                "body": "Opening **post** with [a link](https://example.com).",
                "url": "https://webaim.org/example",
                "published": "2026-07-06T07:51:18Z",
                "deleted": False,
                "removed": False,
                "ap_id": THREAD_URL,
            },
            "creator": {"name": "op", "display_name": "Opening Author"},
        }
    }


def _comment(comment_id, path, content, author):
    return {
        "comment": {
            "id": comment_id,
            "path": path,
            "content": content,
            "published": "2026-07-06T13:08:23Z",
            "deleted": False,
            "removed": False,
        },
        "creator": {"name": author},
    }


def test_lemmy_community_and_user_pages_normalize_to_native_feeds():
    assert discovery.get_social_feed_url("https://rblind.com/c/main") == (
        "https://rblind.com/feeds/c/main.xml"
    )
    assert discovery.get_social_feed_url("https://lemmy.world/u/test_user/") == (
        "https://lemmy.world/feeds/u/test_user.xml"
    )
    assert discovery.get_social_feed_url(THREAD_URL) is None


def test_lemmy_root_uses_its_advertised_all_posts_feed(monkeypatch):
    class Response:
        status_code = 200
        url = "https://rblind.com/"
        text = (
            '<html><head><link rel="alternate" type="application/atom+xml" '
            'href="/feeds/all.xml?sort=Active"></head></html>'
        )
        headers = {"Content-Type": "text/html"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(utils, "safe_requests_get", lambda *args, **kwargs: Response())
    assert discovery.discover_feed("https://rblind.com/") == (
        "https://rblind.com/feeds/all.xml?sort=Active"
    )


def test_lemmy_v3_thread_fetches_every_comment_page(monkeypatch):
    first_page = [
        _comment(i, f"0.{i}", f"Root comment {i}", f"author{i}")
        for i in range(1, 51)
    ]
    nested = _comment(51, "0.1.51", "Nested final reply", "nested_author")
    calls = []

    def fake_json(url, *, timeout, params=None):
        calls.append((url, dict(params or {})))
        if url.endswith("/post"):
            return _post_payload()
        return {"comments": first_page if params["page"] == 1 else [nested]}

    monkeypatch.setattr(article_extractor, "_lemmy_request_json", fake_json)
    page = article_extractor._download_lemmy_thread_html(THREAD_URL, timeout=5)

    assert page
    assert [call[1]["page"] for call in calls if call[0].endswith("comment/list")] == [1, 2]
    text = article_extractor._extract_forum_thread_text(page, THREAD_URL)
    assert "Opening post with a link" in text
    assert "Root comment 50" in text
    assert "Nested final reply" in text
    assert "Reply level 2" in text

    rich = BeautifulSoup(article_html.clean_article_html(page, THREAD_URL), "html.parser")
    headings = [node.get_text(" ", strip=True) for node in rich.find_all("h2")]
    assert len(headings) == 52
    assert headings[0].startswith("#1 Posted by @Opening Author")
    assert headings[-1].startswith("#52 Comment by @nested_author")
    assert rich.find("a", href="https://example.com") is not None


def test_lemmy_v4_cursor_pagination(monkeypatch):
    calls = []

    def fake_json(url, *, timeout, params=None):
        calls.append((url, dict(params or {})))
        if "/api/v3/" in url:
            return None
        if url.endswith("/post"):
            return _post_payload()
        if not params.get("page_cursor"):
            return {
                "comments": [_comment(1, "0.1", "First", "one")],
                "next_page": "cursor-2",
            }
        return {"comments": [_comment(2, "0.2", "Second", "two")], "next_page": None}

    monkeypatch.setattr(article_extractor, "_lemmy_request_json", fake_json)
    page = article_extractor._download_lemmy_thread_html(THREAD_URL, timeout=5)
    assert "First" in page and "Second" in page
    v4_comment_calls = [params for url, params in calls if "/api/v4/comment/list" in url]
    assert v4_comment_calls[0].get("page_cursor") is None
    assert v4_comment_calls[1]["page_cursor"] == "cursor-2"


def test_lemmy_semantic_document_flows_through_fulltext_and_rich_renderers(monkeypatch):
    page = article_extractor._lemmy_thread_document(
        _post_payload()["post_view"],
        [_comment(1, "0.1", "Complete comment", "reply_author")],
    )
    monkeypatch.setattr(
        article_extractor,
        "_fetch_page",
        lambda url, timeout=20: article_extractor._FetchResult(html=page),
    )

    plain = article_extractor.extract_full_article(THREAD_URL, max_pages=1, timeout=5)
    assert plain.title == "Accessible discussion"
    assert "Opening post" in plain.text
    assert "Complete comment" in plain.text

    rich = article_html.render_full_article_html(THREAD_URL, max_pages=1, timeout=5)
    rich_text = BeautifulSoup(rich, "html.parser").get_text(" ", strip=True)
    assert "Accessible discussion" in rich_text
    assert "Opening post" in rich_text
    assert "Complete comment" in rich_text


def test_non_lemmy_numeric_post_route_falls_back_to_normal_fetch(monkeypatch):
    monkeypatch.setattr(article_extractor, "_download_lemmy_thread_html", lambda *a, **k: "")

    response = SimpleNamespace(
        status_code=200,
        url="https://example.com/post/123",
        text="<html><body><article>Ordinary article</article></body></html>",
        headers={"Content-Type": "text/html"},
        encoding="utf-8",
        apparent_encoding="utf-8",
    )
    monkeypatch.setattr(utils, "safe_requests_get", lambda *a, **k: response)
    result = article_extractor._fetch_page("https://example.com/post/123", timeout=5)
    assert "Ordinary article" in result.html
