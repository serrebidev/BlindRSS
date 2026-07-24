# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from types import SimpleNamespace

from bs4 import BeautifulSoup

from core import article_extractor, article_html, discovery, site_cookies, utils


THREAD_URL = (
    "https://old.reddit.com/r/Blind/comments/1v3v1uo/"
    "anyone_else_here_deafblind_and_have_any_tips_on/"
)


def _listing(children):
    return {"kind": "Listing", "data": {"children": children}}


def _comment(comment_id, parent_id, author, body, *, replies=None, depth=0):
    return {
        "kind": "t1",
        "data": {
            "id": comment_id,
            "name": f"t1_{comment_id}",
            "parent_id": parent_id,
            "author": author,
            "body": body,
            "body_html": f'<div class="md"><p>{body}</p></div>',
            "created_utc": 1_784_758_621 + depth,
            "depth": depth,
            "replies": _listing(replies or []) if replies else "",
        },
    }


def _thread_payload():
    post = {
        "kind": "t3",
        "data": {
            "id": "1v3v1uo",
            "name": "t3_1v3v1uo",
            "title": "Accessible alarms",
            "author": "thread_author",
            "created_utc": 1_784_758_000,
            "selftext": "Opening post body",
            "selftext_html": '<div class="md"><p>Opening post body</p></div>',
            "num_comments": 5,
        },
    }
    nested = _comment("nested", "t1_first", "nested_author", "Nested reply", depth=1)
    first = _comment("first", "t3_1v3v1uo", "first_author", "First comment", replies=[nested])
    more = {
        "kind": "more",
        "data": {"children": ["later", "deep"], "parent_id": "t3_1v3v1uo"},
    }
    return [_listing([post]), _listing([first, more])]


class _Response:
    def __init__(self, payload, url):
        import json

        self.status_code = 200
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")
        self.encoding = "utf-8"


def test_subreddit_pages_normalize_to_native_reddit_rss():
    expected = "https://www.reddit.com/r/Rogers/.rss"
    assert discovery.get_social_feed_url("https://reddit.com/r/Rogers") == expected
    assert discovery.get_social_feed_url("https://old.reddit.com/r/Rogers/") == expected
    assert discovery.discover_feed("https://www.reddit.com/r/Rogers/") == expected


def test_reddit_threads_are_not_mistaken_for_subreddit_subscriptions():
    assert discovery.get_social_feed_url(THREAD_URL) is None
    assert article_extractor._is_reddit_thread_url(THREAD_URL) is True
    assert article_extractor._is_reddit_thread_url("https://reddit.com/r/Blind/") is False


def test_reddit_thread_expands_morechildren_for_text_and_rich_views(monkeypatch):
    calls = []
    more_calls = 0

    def fake_get(url, **kwargs):
        nonlocal more_calls
        calls.append((url, kwargs.get("params") or {}))
        if "/api/morechildren" not in url:
            return _Response(_thread_payload(), url)
        more_calls += 1
        if more_calls == 1:
            payload = {
                "json": {
                    "data": {
                        "things": [
                            _comment("later", "t3_1v3v1uo", "later_author", "Later comment"),
                            _comment("deep", "t1_later", "deep_author", "Deep reply", depth=1),
                            {"kind": "more", "data": {"children": ["last"]}},
                        ]
                    }
                }
            }
        else:
            payload = {
                "json": {
                    "data": {
                        "things": [
                            _comment("last", "t3_1v3v1uo", "last_author", "Last comment")
                        ]
                    }
                }
            }
        return _Response(payload, url)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", False)
    monkeypatch.setattr(site_cookies, "refresh_reddit_cookies_from_browsers", lambda url: False)
    monkeypatch.setattr(utils, "_site_cookie_impersonation", lambda url: "")

    page = article_extractor._download_reddit_thread_html(THREAD_URL, timeout=5)
    assert page
    assert more_calls == 2
    assert calls[0][1]["limit"] == "500"
    assert calls[1][1]["children"] == "later,deep"
    assert calls[2][1]["children"] == "last"

    text = article_extractor._extract_forum_thread_text(page, THREAD_URL)
    for expected in (
        "Opening post body",
        "First comment",
        "Nested reply",
        "Later comment",
        "Deep reply",
        "Last comment",
    ):
        assert expected in text
    assert text.index("First comment") < text.index("Nested reply")
    assert text.index("Later comment") < text.index("Deep reply")
    assert "Reply level 2" in text

    rich = article_html.clean_article_html(page, THREAD_URL)
    soup = BeautifulSoup(rich, "html.parser")
    headings = [node.get_text(" ", strip=True) for node in soup.find_all("h2")]
    assert len(headings) == 6
    assert headings[0].startswith("#1 Posted by u/thread_author")
    assert headings[-1].startswith("#6 Comment by u/last_author")
    assert all(value in soup.get_text(" ", strip=True) for value in (
        "Opening post body", "First comment", "Nested reply", "Later comment", "Deep reply", "Last comment"
    ))


def test_reddit_thread_expands_continue_thread_nodes(monkeypatch):
    payload = _thread_payload()
    first = payload[1]["data"]["children"][0]
    first["data"]["replies"] = _listing([
        {
            "kind": "more",
            "data": {"id": "_", "children": ["_"], "parent_id": "t1_first"},
        }
    ])
    payload[1]["data"]["children"] = [first]
    continuation_child = _comment(
        "continued", "t1_first", "continued_author", "Deep continued reply", depth=10
    )
    continuation = [
        _listing(payload[0]["data"]["children"]),
        _listing([_comment(
            "first", "t3_1v3v1uo", "first_author", "First comment",
            replies=[continuation_child]
        )]),
    ]
    calls = []

    def fake_json(url, **kwargs):
        calls.append(url)
        return continuation

    monkeypatch.setattr(article_extractor, "_reddit_request_json", fake_json)
    page = article_extractor._reddit_json_to_thread_html(
        payload, thread_url=THREAD_URL, timeout=5
    )
    assert "Deep continued reply" in page
    assert calls == [
        "https://www.reddit.com/r/Blind/comments/1v3v1uo/_/first.json"
    ]


def test_reddit_semantic_document_flows_through_fulltext_and_rich_renderers(monkeypatch):
    page = article_extractor._reddit_json_to_thread_html(
        _thread_payload(), thread_url=THREAD_URL, timeout=5
    )
    monkeypatch.setattr(
        article_extractor,
        "_fetch_page",
        lambda url, timeout=20: article_extractor._FetchResult(html=page),
    )

    plain = article_extractor.extract_full_article(THREAD_URL, max_pages=1, timeout=5)
    assert plain.title == "Accessible alarms"
    assert "Opening post body" in plain.text
    assert "First comment" in plain.text
    assert "Nested reply" in plain.text

    rich = article_html.render_full_article_html(THREAD_URL, max_pages=1, timeout=5)
    rich_text = BeautifulSoup(rich, "html.parser").get_text(" ", strip=True)
    assert "Accessible alarms" in rich_text
    assert "Opening post body" in rich_text
    assert "First comment" in rich_text
    assert "Nested reply" in rich_text


def test_reddit_fetch_prefers_refreshed_firefox_cookies(monkeypatch):
    events = []

    monkeypatch.setattr(
        site_cookies,
        "refresh_reddit_cookies_from_browsers",
        lambda url: events.append(("refresh", url)) or True,
    )

    def fake_get(url, **kwargs):
        events.append(("get", url))
        return _Response({}, url)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    response = article_extractor._reddit_get(
        "https://www.reddit.com/comments/example.json", timeout=5
    )
    assert response.status_code == 200
    assert [event[0] for event in events] == ["refresh", "get"]


def test_firefox_reddit_refresh_is_site_scoped_and_prefers_login(monkeypatch):
    site_cookies._last_forced_refresh.clear()
    profiles = [
        {"path": "anonymous", "browser": "Firefox", "profile": "Anonymous"},
        {"path": "signed", "browser": "Firefox", "profile": "Signed in"},
    ]
    rows = {
        "anonymous": [
            (".reddit.com", "/", True, True, 9_999_999_999, "loid", "anon"),
        ],
        "signed": [
            (".reddit.com", "/", True, True, 9_999_999_999, "reddit_session", "secret"),
            (".reddit.com", "/", True, False, 9_999_999_999, "loid", "signed-loid"),
            (".example.com", "/", True, True, 9_999_999_999, "session", "must-not-copy"),
        ],
    }
    merged = []
    uas = []
    monkeypatch.setattr(site_cookies, "list_browser_profiles", lambda: profiles)
    monkeypatch.setattr(site_cookies, "_read_firefox_cookies", lambda path: rows[path])
    monkeypatch.setattr(site_cookies, "_merge_records_into_jar", lambda records: merged.extend(records))
    monkeypatch.setattr(site_cookies, "firefox_profile_user_agent", lambda path: "Firefox Test UA")
    monkeypatch.setattr(site_cookies, "set_host_user_agent", lambda host, ua: uas.append((host, ua)))
    monkeypatch.setattr(
        site_cookies,
        "cookies_for",
        lambda url: {"reddit_session": "secret"} if merged else {},
    )

    assert site_cookies.refresh_reddit_cookies_from_browsers(THREAD_URL) is True
    assert {record[5] for record in merged} == {"reddit_session", "loid"}
    assert all("example.com" not in record[0] for record in merged)
    assert uas == [("reddit.com", "Firefox Test UA")]


def test_forum_eager_load_detection_includes_reddit_threads():
    import gui.mainframe as mainframe

    host = SimpleNamespace()
    method = mainframe.MainFrame._is_forum_thread_article
    assert method(host, SimpleNamespace(url=THREAD_URL)) is True
