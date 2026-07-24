# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core import groups_io, discovery


def test_groups_io_urls_and_feed_normalization():
    group = "https://nvda.groups.io/g/nvda"
    search = group + "/search?q=%23adminnotice&ct=1"
    assert groups_io.is_groups_io_url(group)
    assert groups_io.group_feed_url(group).endswith("/g/nvda/rss")
    assert groups_io.is_group_search_url(search)
    assert groups_io.search_query(search) == "#adminnotice"
    assert discovery.get_social_feed_url(search).endswith("/g/nvda/rss")
    assert groups_io.topic_parts("https://nvda.groups.io/g/nvda/topic/119450416")[2] == 119450416
    assert groups_io.message_parts("https://nvda.groups.io/g/nvda/message/131967")[2] == 131967


def test_api_topic_reads_data_pages(monkeypatch):
    monkeypatch.setattr(groups_io, "_api_key", lambda: "test-key")
    pages = iter([
        {"object": "list", "data": [{"msg_num": 1, "subject": "T", "body": "one"}], "topic": {"subject": "T"}, "next_page_token": "next"},
        {"object": "list", "data": [{"msg_num": 2, "subject": "T", "body": "two"}], "next_page_token": ""},
    ])
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return next(pages)
    monkeypatch.setattr(groups_io.utils, "safe_requests_get", lambda *a, **k: Response())
    result = groups_io._api_topic(10)
    assert [m["msg_num"] for m in result["messages"]] == [1, 2]


def test_render_document_contains_every_message():
    html = groups_io._render_document("Topic", [{"msg_num": 1, "name": "A", "body": "<p>one</p>"}, {"msg_num": 2, "name": "B", "body": "<p>two</p>"}], "https://nvda.groups.io/g/nvda/topic/1")
    assert html.count("blindrss-groupsio-post") == 2
    assert "Message by A" in html and "Message by B" in html
