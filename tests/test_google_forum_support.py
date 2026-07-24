# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import json
from types import SimpleNamespace

from bs4 import BeautifulSoup

from core import article_extractor, article_html, discovery, forum_sources
from providers.local import LocalProvider


GOOGLE_GROUP = "https://groups.google.com/g/eyes-free"
GOOGLE_GROUP_THREAD = "https://groups.google.com/g/eyes-free/c/conversation_1"
GOOGLE_SUPPORT_THREAD = (
    "https://support.google.com/pixelphone/thread/341355051/"
    "talkback-is-a-disaster?hl=en"
)
DISCOURSE_THREAD = "https://discuss.google.dev/t/accessible-topic/77"


class _Response:
    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.status_code = 200

    def raise_for_status(self):
        return None


def test_google_groups_email_and_legacy_urls_normalize_to_synthetic_subscription():
    assert forum_sources.google_group_subscription_url("eyes-free@googlegroups.com") == GOOGLE_GROUP
    assert forum_sources.google_group_subscription_url(
        "https://groups.google.com/forum/#!forum/eyes-free"
    ) == GOOGLE_GROUP
    assert forum_sources.normalize_google_groups_url(
        "https://groups.google.com/forum/#!topic/eyes-free/conversation_1"
    ) == GOOGLE_GROUP_THREAD
    assert discovery.get_social_feed_url("eyes-free@googlegroups.com") == GOOGLE_GROUP

    provider = object.__new__(LocalProvider)
    assert provider._resolve_feed_url(
        "eyes-free@googlegroups.com", allow_network=False
    ) == GOOGLE_GROUP


def test_google_group_listing_becomes_feed_items(monkeypatch):
    page = """
    <html><head><title>Eyes Free - Google Groups</title></head><body>
      <div role="row" data-rowid="conversation_1">
        <div class="VWSb7b"><span class="z0zUgf">Alice</span><div class="tRlaM">Jul 21</div></div>
        <a href="./g/eyes-free/c/conversation_1">
          <div class="t17a0d"><span class="o1DPKc">Accessible Android</span></div>
          <div class="WzoK">The newest message snippet.</div>
        </a>
      </div>
      <div role="row" data-rowid="conversation_2">
        <div class="VWSb7b"><span class="z0zUgf">Bob</span><div class="tRlaM">Jul 20</div></div>
        <a href="./g/eyes-free/c/conversation_2">
          <div class="t17a0d"><span class="o1DPKc">Screen reader tips</span></div>
          <div class="WzoK">Another message.</div>
        </a>
      </div>
    </body></html>
    """
    monkeypatch.setattr(
        forum_sources,
        "_google_request",
        lambda *args, **kwargs: _Response(page, GOOGLE_GROUP + "?hl=en"),
    )

    title, items = forum_sources.fetch_google_group_items(GOOGLE_GROUP, max_items=10)
    assert title == "Eyes Free"
    assert [item.id for item in items] == ["conversation_1", "conversation_2"]
    assert items[0].url == GOOGLE_GROUP_THREAD
    assert items[0].author == "Alice"
    assert items[0].content == "The newest message snippet."


def test_google_group_private_page_explains_cookie_import(monkeypatch):
    page = "<html><body><p>You don't have permission to access this content</p></body></html>"
    monkeypatch.setattr(
        forum_sources,
        "_google_request",
        lambda *args, **kwargs: _Response(page, "https://groups.google.com/access-error"),
    )
    try:
        forum_sources.fetch_google_group_items(GOOGLE_GROUP)
    except PermissionError as exc:
        assert "Import Site Cookies" in str(exc)
    else:
        raise AssertionError("private Google Group did not report that sign-in is required")


def test_google_groups_thread_is_attributed_in_classic_and_rich_readers(monkeypatch):
    page = """
    <html><head><title>TalkBack discussion - Google Groups</title></head><body>
      <div class="eH2Xlc">
        <h3 id="post1">Alice</h3><span class="zX2W9c">Jul 21, 2026</span>
        <div data-message-id="message1"></div>
        <div class="ptW7te" role="region" aria-labelledby="post1">
          <p>Opening post body.</p>
          <div class="gmail_quote">Quoted older mail should not repeat.</div>
        </div>
      </div>
      <div class="eH2Xlc">
        <h3 id="post2">Bob</h3><span class="zX2W9c">Jul 22, 2026</span>
        <div data-message-id="message2"></div>
        <div class="ptW7te" role="region" aria-labelledby="post2"><p>Complete reply.</p></div>
      </div>
    </body></html>
    """
    monkeypatch.setattr(
        forum_sources,
        "_google_request",
        lambda *args, **kwargs: _Response(page, GOOGLE_GROUP_THREAD),
    )
    document = forum_sources.download_google_groups_thread_html(GOOGLE_GROUP_THREAD)
    plain = article_extractor._extract_forum_thread_text(document, GOOGLE_GROUP_THREAD)
    assert "#1 Posted by Alice" in plain
    assert "Opening post body." in plain
    assert "#2 Message by Bob" in plain
    assert "Complete reply." in plain
    assert "Quoted older mail" not in plain

    rich = BeautifulSoup(article_html.clean_article_html(document, GOOGLE_GROUP_THREAD), "html.parser")
    assert len(rich.select("h2")) == 2
    assert "Complete reply." in rich.get_text(" ", strip=True)


def _google_support_page():
    data = [None] * 46
    topic = [None] * 13
    topic[0] = [341355051, "1746000567795888"]
    topic[8] = "TalkBack help"
    topic[12] = "<p>Opening support question.</p>"
    data[1] = topic
    data[3] = [["Opening Author"]]

    post = [None] * 17
    post[0] = [9001, "1748594943571687"]
    post[3] = "<p>Recommended accessible answer.</p>"
    wrapper = [post, None, [["Product Expert"]]]
    data[39] = [[wrapper]]
    encoded = json.dumps(data).replace('"', r"\x22")
    return f"<html><script>(function(){{var thread_view='{encoded}';}})();</script></html>"


def test_google_support_embedded_thread_data_is_decoded(monkeypatch):
    monkeypatch.setattr(
        forum_sources,
        "_google_request",
        lambda *args, **kwargs: _Response(_google_support_page(), GOOGLE_SUPPORT_THREAD),
    )
    document = forum_sources.download_google_support_thread_html(GOOGLE_SUPPORT_THREAD)
    text = article_extractor._extract_forum_thread_text(document, GOOGLE_SUPPORT_THREAD)
    assert "#1 Posted by Opening Author" in text
    assert "Opening support question." in text
    assert "#2 Message by Product Expert" in text
    assert "Recommended accessible answer." in text


def test_discourse_google_developer_feeds_and_complete_topic(monkeypatch):
    assert discovery.get_social_feed_url("https://discuss.google.dev/") == (
        "https://discuss.google.dev/latest.rss?order=created"
    )
    assert discovery.get_social_feed_url(DISCOURSE_THREAD) == (
        "https://discuss.google.dev/t/-/77.rss"
    )

    calls = []
    first = {
        "title": "Accessible developer topic",
        "post_stream": {
            "stream": [1, 2],
            "posts": [
                {
                    "id": 1,
                    "post_number": 1,
                    "name": "Alice",
                    "username": "alice",
                    "created_at": "2026-07-21T12:00:00Z",
                    "cooked": "<p>Opening developer question.</p>",
                }
            ],
        },
    }
    second = {
        "post_stream": {
            "posts": [
                {
                    "id": 2,
                    "post_number": 2,
                    "username": "bob",
                    "created_at": "2026-07-22T12:00:00Z",
                    "reply_to_post_number": 1,
                    "cooked": "<p>Complete developer answer.</p>",
                }
            ]
        }
    }

    def fake_json(url, *, timeout, params=None):
        calls.append((url, params))
        return second if url.endswith("/posts.json") else first

    monkeypatch.setattr(forum_sources, "_discourse_json", fake_json)
    document = forum_sources.download_discourse_thread_html(DISCOURSE_THREAD)
    text = article_extractor._extract_forum_thread_text(document, DISCOURSE_THREAD)
    assert "Opening developer question." in text
    assert "Complete developer answer." in text
    assert "Reply to #1" in text
    assert calls[1][1] == [("post_ids[]", "2")]


def test_structured_forum_fetch_runs_before_generic_article_fetch(monkeypatch):
    document = forum_sources._render_thread_document(
        "Support topic",
        [{"id": "1", "author": "Alice", "body": "<p>Whole thread.</p>"}],
        GOOGLE_SUPPORT_THREAD,
        source_label="Google Support",
        css_prefix="googlesupport",
    )
    monkeypatch.setattr(
        forum_sources, "download_google_support_thread_html", lambda *args, **kwargs: document
    )
    result = article_extractor._fetch_page(GOOGLE_SUPPORT_THREAD, timeout=5)
    assert "Whole thread." in result.html
    assert article_extractor._is_forum_thread_host(GOOGLE_SUPPORT_THREAD) is True
    assert article_extractor._is_forum_thread_host(DISCOURSE_THREAD) is True
