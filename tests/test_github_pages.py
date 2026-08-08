# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""GitHub pull request / issue / commit pages rebuilt from the REST API.

The reported bug: the reader showed only the server-rendered diff table, losing
the description and the whole conversation. These tests pin the rebuilt document
through BOTH readers — classic full text and the rich WebView cleaner.
"""

import json

import pytest

from bs4 import BeautifulSoup

from core import article_extractor, article_html, github_source, utils


PULL_URL = "https://github.com/serrebi/BlindRSS/pull/42"


class _Response:
    def __init__(self, payload, url, status=200):
        self.status_code = status
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")
        self.encoding = "utf-8"

    def json(self):
        return json.loads(self.text)


_PULL = {
    "number": 42,
    "title": "Restore the article footer",
    "state": "open",
    "draft": False,
    "user": {"login": "reporter"},
    "created_at": "2026-08-01T09:00:00Z",
    "body_html": "<p>This fixes the missing footer.</p>",
    "additions": 12,
    "deletions": 3,
    "changed_files": 1,
    "commits": 1,
    "base": {"ref": "main"},
    "head": {"ref": "fix-footer", "label": "reporter:fix-footer"},
    "labels": [{"name": "bug"}],
    "assignees": [{"login": "maintainer"}],
}

_ROUTES = {
    "/repos/serrebi/BlindRSS/pulls/42": _PULL,
    "/repos/serrebi/BlindRSS/pulls/42/commits": [
        {
            "sha": "abcdef1234567890",
            "commit": {"message": "Restore the footer\n\nDetails here", "author": {"name": "Reporter"}},
            "author": {"login": "reporter"},
        }
    ],
    "/repos/serrebi/BlindRSS/issues/42/comments": [
        {
            "user": {"login": "maintainer"},
            "created_at": "2026-08-02T10:00:00Z",
            "body_html": "<p>Thanks, could you add a test?</p>",
        }
    ],
    "/repos/serrebi/BlindRSS/pulls/42/reviews": [
        {
            "user": {"login": "maintainer"},
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-08-03T11:00:00Z",
            "body_html": "<p>Almost there.</p>",
        },
        {"user": {"login": "bot"}, "state": "COMMENTED", "submitted_at": "2026-08-03T11:05:00Z", "body": ""},
    ],
    "/repos/serrebi/BlindRSS/pulls/42/comments": [
        {
            "user": {"login": "maintainer"},
            "created_at": "2026-08-03T11:01:00Z",
            "path": "core/sky.py",
            "line": 88,
            "diff_hunk": "@@ -80,6 +80,9 @@\n context line\n+added line",
            "body_html": "<p>Use the shared helper here.</p>",
        }
    ],
    "/repos/serrebi/BlindRSS/pulls/42/files": [
        {
            "filename": "core/sky.py",
            "status": "modified",
            "additions": 12,
            "deletions": 3,
            "patch": "@@ -80,6 +80,9 @@\n-  removed = True\n+  added = True\n   window.addEventListener('load', () => {\n     console.log('x')\n   })",
        }
    ],
}


def _install_api(monkeypatch, routes=None, status=200):
    """Serve the fake API and record every path requested."""
    seen = []
    table = _ROUTES if routes is None else routes

    def fake_get(url, **kwargs):
        assert url.startswith("https://api.github.com/")
        assert kwargs.get("site_cookies") is False
        path = url[len("https://api.github.com"):].split("?")[0]
        seen.append(path)
        if status != 200:
            return _Response({"message": "rate limited"}, url, status=status)
        payload = table.get(path)
        if payload is None:
            return _Response({"message": "Not Found"}, url, status=404)
        return _Response(payload, url)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setattr(github_source, "_token", lambda: "")
    return seen


@pytest.mark.parametrize(
    "url,kind,ref",
    [
        (PULL_URL, "pull", "42"),
        (PULL_URL + "/files", "pull", "42"),
        (PULL_URL + "/commits", "pull", "42"),
        ("https://github.com/serrebi/BlindRSS/issues/79", "issue", "79"),
        ("https://github.com/serrebi/BlindRSS/commit/d95c9c6", "commit", "d95c9c6"),
        ("https://github.com/serrebi/BlindRSS/releases/tag/v1.127.11", "release", "v1.127.11"),
    ],
)
def test_supported_github_pages_are_recognized(url, kind, ref):
    target = github_source.parse_target(url)
    assert target is not None
    assert (target.kind, target.owner, target.repo, target.ref) == (kind, "serrebi", "BlindRSS", ref)
    assert article_extractor._is_github_page_url(url) is True
    assert article_extractor._is_forum_thread_host(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/serrebi/BlindRSS",
        "https://github.com/serrebi/BlindRSS/discussions/4",
        "https://github.com/orgs/serrebi/issues/4",
        "https://example.com/serrebi/BlindRSS/pull/42",
        "",
    ],
)
def test_unsupported_urls_fall_through_to_normal_extraction(url):
    assert github_source.parse_target(url) is None
    assert article_extractor._is_github_page_url(url) is False


def test_pull_request_text_view_keeps_description_comments_reviews_and_diff(monkeypatch):
    _install_api(monkeypatch)
    page = github_source.download_page_html(PULL_URL, timeout=5)
    assert page

    text = article_extractor._extract_forum_thread_text(page, PULL_URL)
    for expected in (
        "This fixes the missing footer.",          # description — was lost
        "Thanks, could you add a test?",           # conversation comment — was lost
        "Almost there.",                           # review body — was lost
        "Use the shared helper here.",             # inline review comment — was lost
        "Restore the footer",                      # commit list
        "core/sky.py — modified, 12 added, 3 removed",
        # The diff is still there. Interior runs of spaces collapse in the plain-text
        # reader (as they do for every other code block it renders), but the +/- markers
        # that carry the meaning survive; the rich reader keeps the indentation.
        "+ added = True",
    ):
        assert expected in text, expected

    # Ordering: the discussion comes before the diff, and events are chronological.
    assert text.index("Thanks, could you add a test?") < text.index("Almost there.")
    assert text.index("Almost there.") < text.index("+ added = True")
    # A bodyless "commented" review is only a container for inline comments.
    assert "by bot" not in text
    # Diff lines stay on their own lines instead of collapsing into one run.
    assert "\n+ added = True" in text


def test_pull_request_diff_survives_the_leaked_script_stripper(monkeypatch):
    _install_api(monkeypatch)
    page = github_source.download_page_html(PULL_URL, timeout=5)
    text = article_extractor._postprocess_extracted_text(
        article_extractor._extract_text_any(page, PULL_URL), PULL_URL
    )
    # The patch is JavaScript-shaped (addEventListener, arrow function, console.log),
    # exactly what _strip_embedded_script_code drops as leaked <script> source.
    assert "window.addEventListener('load', () => {" in text
    assert "console.log('x')" in text


def test_pull_request_rich_view_renders_every_section(monkeypatch):
    _install_api(monkeypatch)
    page = github_source.download_page_html(PULL_URL, timeout=5)

    rich = article_html.clean_article_html(page, PULL_URL)
    soup = BeautifulSoup(rich, "html.parser")
    headings = [node.get_text(" ", strip=True) for node in soup.find_all("h2")]
    assert headings[0].startswith("#1 Pull request opened by reporter")
    assert any(h.startswith("#3 Comment by maintainer") for h in headings)
    assert any("Review comment by maintainer on core/sky.py line 88" in h for h in headings)
    assert any(h.startswith("#6 Changed files") for h in headings)
    assert any("Diff: core/sky.py" in h for h in headings)

    body = soup.get_text(" ", strip=True)
    for expected in (
        "This fixes the missing footer.",
        "Thanks, could you add a test?",
        "Almost there.",
        "Use the shared helper here.",
        "added = True",
    ):
        assert expected in body, expected
    # Review comments carry the code they are attached to.
    assert soup.find("pre") is not None


def test_fetch_page_uses_the_reconstruction_for_both_readers(monkeypatch):
    _install_api(monkeypatch)
    result = article_extractor._fetch_page(PULL_URL, timeout=5)
    assert result.html
    assert "blindrss-github-post" in result.html
    assert "Restore the article footer (serrebi/BlindRSS#42)" in result.html


def test_rich_reader_renders_the_page_end_to_end(monkeypatch):
    _install_api(monkeypatch)
    fragment = article_html.render_full_article_html(
        PULL_URL, fallback_title="Restore the article footer", timeout=5
    )
    assert fragment
    soup = BeautifulSoup(fragment, "html.parser")
    body = soup.get_text(" ", strip=True)
    for expected in (
        "Restore the article footer",
        "This fixes the missing footer.",
        "Thanks, could you add a test?",
        "Almost there.",
        "Use the shared helper here.",
        "added = True",
    ):
        assert expected in body, expected


def test_long_feed_content_never_replaces_the_rebuilt_page(monkeypatch):
    # A pull-request description long enough to trip the generic "feed content is
    # probably full text" rule must not skip the fetch — the conversation only
    # exists on the page.
    feed_html = "<p>" + ("The description repeated. " * 200) + "</p>"
    assert article_extractor._should_prefer_feed_content(PULL_URL, feed_html) is False

    _install_api(monkeypatch)
    rendered = article_extractor.render_full_article(PULL_URL, fallback_html=feed_html, timeout=5) or ""
    assert "Thanks, could you add a test?" in rendered

    fragment = article_html.render_full_article_html(
        PULL_URL, fallback_html=feed_html, fallback_title="Restore the article footer", timeout=5
    ) or ""
    assert "Thanks, could you add a test?" in fragment


def test_small_pull_request_is_not_rejected_as_a_link_list(monkeypatch):
    # Short lines with no sentence punctuation (diff rows, file lists, metadata
    # bullets) are what the navigation-stack guard rejects; a rebuilt page is exempt,
    # or a one-line pull request would come back as "no readable article text".
    routes = dict(_ROUTES)
    routes["/repos/serrebi/BlindRSS/issues/42/comments"] = []
    routes["/repos/serrebi/BlindRSS/pulls/42/reviews"] = []
    routes["/repos/serrebi/BlindRSS/pulls/42/comments"] = []
    routes["/repos/serrebi/BlindRSS/pulls/42"] = dict(_PULL, body_html="<p>Small fix.</p>")
    _install_api(monkeypatch, routes=routes)
    article = article_extractor.extract_full_article(PULL_URL, timeout=5)
    assert article is not None
    assert "Small fix." in article.text


def test_no_pagination_is_followed_out_of_a_rebuilt_github_page(monkeypatch):
    _install_api(monkeypatch)
    page = github_source.download_page_html(PULL_URL, timeout=5)
    assert article_extractor._find_next_page(page, PULL_URL) is None


def test_rate_limited_api_falls_back_to_the_ordinary_page_fetch(monkeypatch):
    _install_api(monkeypatch, status=403)
    assert github_source.download_page_html(PULL_URL, timeout=5) == ""


def test_issue_url_serving_a_pull_request_renders_the_pull_request(monkeypatch):
    routes = dict(_ROUTES)
    routes["/repos/serrebi/BlindRSS/issues/42"] = dict(
        _PULL, pull_request={"url": "https://api.github.com/repos/serrebi/BlindRSS/pulls/42"}
    )
    _install_api(monkeypatch, routes=routes)
    page = github_source.download_page_html(
        "https://github.com/serrebi/BlindRSS/issues/42", timeout=5
    )
    assert "Pull request opened by reporter" in page
    assert "Use the shared helper here." in page


def test_issue_page_keeps_body_and_every_comment(monkeypatch):
    routes = {
        "/repos/serrebi/BlindRSS/issues/79": {
            "number": 79,
            "title": "Cloudflare interstitials",
            "state": "closed",
            "user": {"login": "reporter"},
            "created_at": "2026-07-01T09:00:00Z",
            "closed_at": "2026-07-09T09:00:00Z",
            "body_html": "<p>Feed fetch hits a challenge page.</p>",
            "labels": [{"name": "bug"}],
        },
        "/repos/serrebi/BlindRSS/issues/79/comments": [
            {
                "user": {"login": "maintainer"},
                "created_at": "2026-07-02T10:00:00Z",
                "body_html": "<p>Import the browser cookies.</p>",
            },
            {
                "user": {"login": "reporter"},
                "created_at": "2026-07-03T10:00:00Z",
                "body": "Works now, thanks.",
            },
        ],
    }
    _install_api(monkeypatch, routes=routes)
    page = github_source.download_page_html("https://github.com/serrebi/BlindRSS/issues/79", timeout=5)
    text = article_extractor._extract_forum_thread_text(
        page, "https://github.com/serrebi/BlindRSS/issues/79"
    )
    assert "Feed fetch hits a challenge page." in text
    assert "Import the browser cookies." in text
    assert "Works now, thanks." in text          # plain body, no body_html
    assert "#1 Issue opened by reporter" in text
    assert "Closed" in text


def test_commit_page_keeps_message_stats_and_diff(monkeypatch):
    routes = {
        "/repos/serrebi/BlindRSS/commits/d95c9c6": {
            "sha": "d95c9c6aaaabbbbcccc",
            "commit": {
                "message": "Release v1.127.11\n\nBundles the Sky News table fix.",
                "author": {"name": "admin", "date": "2026-08-05T12:00:00Z"},
            },
            "author": {"login": "serrebi"},
            "stats": {"additions": 5, "deletions": 2},
            "parents": [{"sha": "2d8f915abc"}],
            "files": [
                {
                    "filename": "core/version.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "patch": "@@ -1 +1 @@\n-VERSION = \"1.127.10\"\n+VERSION = \"1.127.11\"",
                }
            ],
        },
        "/repos/serrebi/BlindRSS/commits/d95c9c6/comments": [],
    }
    _install_api(monkeypatch, routes=routes)
    page = github_source.download_page_html(
        "https://github.com/serrebi/BlindRSS/commit/d95c9c6", timeout=5
    )
    text = article_extractor._extract_forum_thread_text(
        page, "https://github.com/serrebi/BlindRSS/commit/d95c9c6"
    )
    assert "Bundles the Sky News table fix." in text
    assert "5 additions, 2 deletions" in text
    assert '+VERSION = "1.127.11"' in text


def test_release_page_keeps_notes_and_assets(monkeypatch):
    routes = {
        "/repos/serrebi/BlindRSS/releases/tags/v1.127.11": {
            "tag_name": "v1.127.11",
            "name": "BlindRSS 1.127.11",
            "user": {"login": "serrebi"},
            "published_at": "2026-08-05T13:00:00Z",
            "body_html": "<ul><li>Restores Sky News tables.</li></ul>",
            "assets": [
                {
                    "name": "BlindRSS-Setup.exe",
                    "browser_download_url": "https://github.com/serrebi/BlindRSS/releases/download/v1.127.11/BlindRSS-Setup.exe",
                    "download_count": 17,
                }
            ],
        }
    }
    _install_api(monkeypatch, routes=routes)
    page = github_source.download_page_html(
        "https://github.com/serrebi/BlindRSS/releases/tag/v1.127.11", timeout=5
    )
    text = article_extractor._extract_forum_thread_text(
        page, "https://github.com/serrebi/BlindRSS/releases/tag/v1.127.11"
    )
    assert "Restores Sky News tables." in text
    assert "BlindRSS-Setup.exe (17 downloads)" in text


def test_huge_diffs_are_bounded_and_say_so(monkeypatch):
    patch = "\n".join(f"+line {n}" for n in range(1200))
    routes = dict(_ROUTES)
    routes["/repos/serrebi/BlindRSS/pulls/42/files"] = [
        {"filename": "big.py", "status": "modified", "additions": 1200, "deletions": 0, "patch": patch}
    ]
    _install_api(monkeypatch, routes=routes)
    page = github_source.download_page_html(PULL_URL, timeout=5)
    assert "Diff truncated" in page
    assert page.count("<br>+line ") < 1200


def test_dropped_diffs_are_reported_instead_of_silently_omitted(monkeypatch):
    routes = dict(_ROUTES)
    routes["/repos/serrebi/BlindRSS/pulls/42/files"] = [
        {
            "filename": f"module_{n}.py",
            "status": "modified",
            "additions": 500,
            "deletions": 0,
            "patch": "\n".join(f"+line {i}" for i in range(500)),
        }
        for n in range(40)
    ]
    _install_api(monkeypatch, routes=routes)
    page = github_source.download_page_html(PULL_URL, timeout=5)
    assert "Remaining diffs not shown" in page
    assert "more changed files are not included here" in page
    # The summary still lists every changed file, so nothing disappears unannounced.
    assert "module_39.py" in page


def test_api_token_is_sent_when_configured(monkeypatch):
    headers_seen = {}

    def fake_get(url, **kwargs):
        headers_seen.update(kwargs.get("headers") or {})
        return _Response(_PULL, url)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    monkeypatch.setenv("BLINDRSS_GITHUB_TOKEN", "secret-token")
    github_source._api_get("/repos/serrebi/BlindRSS/pulls/42", timeout=5)
    assert headers_seen.get("Authorization") == "Bearer secret-token"
    assert headers_seen.get("Accept") == "application/vnd.github.full+json"
