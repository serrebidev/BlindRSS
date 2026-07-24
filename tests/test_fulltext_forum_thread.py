# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Forum-thread full-text and rich-view regressions (FluxBB and Drupal).

A thread page is a flat list of sibling post/comment blocks with no single node
holding the conversation, so generic extraction picked one block and discarded the
rest: on audiogames.net a 20-reply topic came back as one short reply and the rich
reader showed only the last poster's signature; on applevis.com the replies ran
together with no way to tell who was speaking.
"""

from bs4 import BeautifulSoup

import core.article_extractor as article_extractor
import core.article_html as article_html
import core.utils as utils


FORUM_URL = "https://forum.audiogames.net/topic/59794/what-apps-do-you-guys-use/new/posts/"
APPLEVIS_URL = "https://www.applevis.com/forum/apple-beta-releases/iosipados-27-beta-4-megathread"


def _post(num, byline, when, body, *, sig=""):
    return (
        '<div class="post odd">'
        f'<div class="posthead" id="p{num}"><h3 class="hn post-ident">'
        f'<span class="post-num"><a class="permalink" href="#p{num}">#{num}</a></span>'
        f'<span class="post-byline"><span>{byline} by</span> '
        f'<a href="https://forum.audiogames.net/user/1/">{when[0]}</a></span>'
        f'<span class="post-link">{when[1]}</span>'
        "</h3></div>"
        '<div class="postbody">'
        '<div class="post-author"><ul class="author-ident">'
        f'<li class="username"><a href="#">{when[0]}</a></li>'
        '<li class="usertitle"><span>hero caller</span></li></ul>'
        '<ul class="author-info"><li><span>Registered: <strong>2014-05-25</strong></span></li>'
        '<li><span>Posts: <strong>302</strong></span></li></ul></div>'
        '<div class="post-entry"><div class="entry-content">'
        f"<p>{body}</p>"
        + (f'<div class="sig-content"><span class="sig-line"></span>{sig}</div>' if sig else "")
        + "</div></div></div>"
        '<div class="postfoot"><div class="post-options"><p class="post-actions">'
        '<span class="report-post"><a href="#">Quote<span>Post 1</span></a></span>'
        "</p></div></div>"
        "</div>"
    )


THREAD_HTML = (
    '<html lang="en"><head><title>What apps do you guys use? (Page 1) — AudioGames.net Forum</title>'
    "</head><body>"
    '<div id="brd-navlinks"><ul><li><a href="/">Index</a></li>'
    '<li><a href="/search/">Search</a></li></ul></div>'
    '<div id="brd-main">'
    '<p class="paging"><span class="pages">Pages</span> <strong>1</strong></p>'
    '<p class="posting">You must <a href="/login/">login</a> or '
    '<a href="/register/">register</a> to post a reply</p>'
    + _post(1, "Topic", ("Zayed", "2026-07-19 13:12:20"), "Which delivery apps do you use?")
    + _post(2, "Reply", ("Minionslayer", "2026-07-19 13:34:07"), "Deliveroo on iOS is my pick.")
    + _post(
        3,
        "Reply",
        ("Cornettoking", "Yesterday 18:24:00"),
        "It is called Lieferando here.",
        sig="Visit my soundcloud page where I upload silly songs.",
    )
    + "</div></body></html>"
)

# A single-post "here are the links" thread: FluxBB shortens the visible link text
# but keeps the href intact.
AMAZON_HREF = "https://www.amazon.com/dp/B0CKB9WK3F?ref_=ppx_hzsearch_conn_dt_b_fed_asin_title_1"
LINK_THREAD_HTML = (
    '<html lang="en"><head><title>Looking to sell a gaming headset — AudioGames.net Forum</title>'
    "</head><body><div id=\"brd-main\">"
    + _post(
        1,
        "Topic",
        ("austingrace", "Yesterday 18:50:34"),
        "Hello everyone. I am selling a headset and a fight stick. Here are amazon links."
        "<br>The controller<br>"
        f'<a href="{AMAZON_HREF}">https://www.amazon.com/dp/B0CKB9WK3F?re … in_title_1</a>'
        "<br>Thank you all for reading.",
    )
    + "</div></body></html>"
)


def test_every_post_is_extracted_with_attribution():
    text = article_extractor._extract_site_specific_text(THREAD_HTML, FORUM_URL)

    assert "#1 Topic by Zayed — 2026-07-19 13:12:20" in text
    assert "#2 Reply by Minionslayer — 2026-07-19 13:34:07" in text
    assert "#3 Reply by Cornettoking — Yesterday 18:24:00" in text
    for body in (
        "Which delivery apps do you use?",
        "Deliveroo on iOS is my pick.",
        "It is called Lieferando here.",
    ):
        assert body in text


def test_signatures_and_forum_chrome_are_dropped():
    text = article_extractor._extract_site_specific_text(THREAD_HTML, FORUM_URL)

    # A per-user signature repeats under every post that user makes.
    assert "soundcloud" not in text
    # Page furniture that framed the thread.
    assert "Pages" not in text
    assert "login" not in text
    assert "Registered" not in text
    assert "Quote" not in text


def test_truncated_link_text_is_replaced_with_the_real_url():
    text = article_extractor._extract_site_specific_text(LINK_THREAD_HTML, FORUM_URL)

    assert AMAZON_HREF in text
    assert "…" not in text


def test_short_link_heavy_thread_is_not_rejected_as_a_link_list():
    # The post header is short and punctuation-free by design; counting it as
    # evidence would tip a "here are the links" post over the rejection ratio.
    text = article_extractor._extract_site_specific_text(LINK_THREAD_HTML, FORUM_URL)

    assert article_extractor._looks_like_link_list(text) is False


def test_non_forum_page_falls_through_to_generic_extraction():
    # The handler must fail open on a forum index or error page.
    assert (
        article_extractor._extract_forum_thread_text(
            "<html><body><p>No posts here.</p></body></html>", FORUM_URL
        )
        == ""
    )


def test_rich_view_renders_every_post_under_its_own_heading():
    body = article_html.clean_article_html(THREAD_HTML, FORUM_URL)
    soup = BeautifulSoup(body, "html.parser")

    headings = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
    assert headings == [
        "#1 Topic by Zayed — 2026-07-19 13:12:20",
        "#2 Reply by Minionslayer — 2026-07-19 13:34:07",
        "#3 Reply by Cornettoking — Yesterday 18:24:00",
    ]
    assert "Deliveroo on iOS is my pick." in body


def test_rich_view_keeps_links_and_expands_truncated_text():
    body = article_html.clean_article_html(LINK_THREAD_HTML, FORUM_URL)
    soup = BeautifulSoup(body, "html.parser")

    anchors = [a for a in soup.find_all("a") if a.get("href") == AMAZON_HREF]
    assert anchors, "the amazon link must stay clickable in the rich reader"
    assert anchors[0].get_text(strip=True) == AMAZON_HREF


# --- Drupal comment threads (applevis.com) ----------------------------------


def _comment(cid, subject, author, when, body):
    return (
        f'<article class="comment js-comment comment--level-1" id="comment-{cid}" role="article">'
        f'<div class="comment__title"><h3><a class="permalink" href="/comment/{cid}">{subject}</a>'
        "</h3></div>"
        '<div class="comment__text-wrapper"><footer class="comment__meta">'
        f'<p class="comment__author">By <span>{author}</span> on {when}</p>'
        "</footer>"
        '<div class="comment__title comment__content">'
        '<div class="text-content field field--name-comment-body field--type-text-long '
        f'field__item comment__text-content"><p>{body}</p></div>'
        '<ul class="links inline comment__links"><li>Reply</li></ul>'
        "</div></div></article>"
    )


def _applevis_page(*comments):
    return (
        '<html lang="en"><head><title>iOS/iPadOS 27 Beta 4 Megathread | AppleVis</title></head>'
        "<body>"
        '<article class="node node--type-forum">'
        '<div class="node__meta"><p><span>By <span><span>AppleVis</span></span>, 20  July,  2026'
        "</span></p>"
        '<div class="node__content">'
        '<div class="field field--name-taxonomy-forums"><div class="field__label">Forum</div>'
        '<div class="field__item">Apple Beta Releases</div></div>'
        '<div class="text-content field field--name-body field__item">'
        "<p>Please use this megathread for any and all discussion related to beta 4.</p></div>"
        "</div></div></article>"
        + "".join(comments)
        + "</body></html>"
    )


APPLEVIS_HTML = _applevis_page(
    _comment(1, "Speech quality", "tunmi13", "Monday, July 20, 2026 - 18:46", "Cannot tell if fixed."),
    _comment(2, "not fixed", "Jokyboy129", "Monday, July 20, 2026 - 20:02", "It is definitely not fixed."),
    _comment(3, "Silence when unlocking", "peter", "Tuesday, July 21, 2026 - 04:04", "VoiceOver is silent."),
)

APPLEVIS_BLOG_HTML = _applevis_page()


def test_applevis_thread_keeps_the_topic_and_every_comment():
    text = article_extractor._extract_site_specific_text(APPLEVIS_HTML, APPLEVIS_URL)

    assert "#1 By AppleVis, 20 July, 2026" in text
    assert "Please use this megathread" in text
    for n, (subject, author, body) in enumerate(
        (
            ("Speech quality", "tunmi13", "Cannot tell if fixed."),
            ("not fixed", "Jokyboy129", "It is definitely not fixed."),
            ("Silence when unlocking", "peter", "VoiceOver is silent."),
        ),
        start=2,
    ):
        assert f"#{n} {subject} — By {author} on " in text
        assert body in text


def test_applevis_comment_chrome_is_dropped():
    text = article_extractor._extract_site_specific_text(APPLEVIS_HTML, APPLEVIS_URL)

    assert "Reply" not in text
    # The forum taxonomy label sits beside the body inside node__content.
    assert "Apple Beta Releases" not in text


def test_applevis_entry_without_comments_uses_generic_extraction():
    # A blog entry is the same Drupal node markup as a topic; with no replies to
    # interleave, this path has nothing to add and must not prefix a "#1" header.
    assert (
        article_extractor._extract_site_specific_text(APPLEVIS_BLOG_HTML, APPLEVIS_URL) == ""
    )


def test_applevis_rich_view_renders_a_heading_per_comment():
    body = article_html.clean_article_html(APPLEVIS_HTML, APPLEVIS_URL)
    soup = BeautifulSoup(body, "html.parser")

    headings = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
    assert len(headings) == 4
    assert headings[0] == "#1 By AppleVis, 20 July, 2026"
    assert headings[1].startswith("#2 Speech quality — By tunmi13 on ")
    # Drupal names the body "field--name-comment-body comment__text-content", which
    # the class-based chrome filter read as a comments widget and deleted, leaving
    # headings with no text under any of them.
    assert "It is definitely not fixed." in body


# --- Feed author field ------------------------------------------------------


def test_rss_author_shows_the_display_name_not_the_placeholder_address():
    # PunBB has no address to publish, so it ships "null@example.com (name)" and
    # the reader announced the whole string as the author.
    assert utils.normalize_author("null@example.com (sightlessHorseman)") == "sightlessHorseman"
    assert utils.normalize_author('"Jane Doe" <jane@example.com>') == "Jane Doe"


def test_plain_author_and_bare_address_pass_through():
    assert utils.normalize_author("Simon Romero") == "Simon Romero"
    # A bare address is at least identifying; inventing a name would be worse.
    assert utils.normalize_author("news@example.com") == "news@example.com"
    assert utils.normalize_author(None) == ""


# --- Forum threads auto-load the whole conversation on selection ------------
#
# audiogames and applevis syndicate only the opening post, so the feed-content
# view is a one-post stub and the rest of the thread appears only once the
# reader is focused. The reader loads the full thread on selection for these
# hosts so every post shows without a focus dance.

import sys
from types import SimpleNamespace

import gui.mainframe as mainframe


class _ReaderHost:
    _is_forum_thread_article = mainframe.MainFrame._is_forum_thread_article


def test_is_forum_thread_article_detects_discussion_hosts():
    host = _ReaderHost()
    assert host._is_forum_thread_article(SimpleNamespace(url=APPLEVIS_URL)) is True
    assert host._is_forum_thread_article(SimpleNamespace(url=FORUM_URL)) is True
    # An ordinary news article must not trigger an eager fetch.
    assert host._is_forum_thread_article(
        SimpleNamespace(url="https://www.macrumors.com/2026/07/09/story/")
    ) is False
    # No URL (e.g. a local/text item) is never a forum thread.
    assert host._is_forum_thread_article(SimpleNamespace(url="")) is False


class _SelectHost:
    """Borrows the on-select branch that decides whether to eager-load full text."""

    _is_forum_thread_article = mainframe.MainFrame._is_forum_thread_article
    _is_youtube_video_article = mainframe.MainFrame._is_youtube_video_article

    def __init__(self, rich_active=False):
        self._rich_active = rich_active
        self.fulltext_scheduled = []
        self.rich_scheduled = []

    def _rich_view_active(self):
        return self._rich_active

    def _schedule_fulltext_load_for_index(self, idx, force=False):
        self.fulltext_scheduled.append((idx, force))

    def _schedule_rich_load_for_index(self, idx, force=False):
        self.rich_scheduled.append((idx, force))

    # The exact decision block from _update_content_view.
    def maybe_autoload(self, idx, article):
        if (
            sys.platform == "darwin"
            or self._is_forum_thread_article(article)
            or self._is_youtube_video_article(article)
        ):
            if self._rich_view_active():
                self._schedule_rich_load_for_index(idx, force=False)
            else:
                self._schedule_fulltext_load_for_index(idx, force=False)


def test_selecting_a_forum_thread_schedules_a_classic_fulltext_load():
    host = _SelectHost(rich_active=False)
    host.maybe_autoload(3, SimpleNamespace(url=APPLEVIS_URL))
    assert host.fulltext_scheduled == [(3, False)]
    assert host.rich_scheduled == []


def test_selecting_a_forum_thread_schedules_a_rich_load_when_rich_active():
    host = _SelectHost(rich_active=True)
    host.maybe_autoload(2, SimpleNamespace(url=FORUM_URL))
    assert host.rich_scheduled == [(2, False)]
    assert host.fulltext_scheduled == []


def test_selecting_youtube_schedules_fulltext_before_reader_focus():
    article = SimpleNamespace(url="https://www.youtube.com/watch?v=abcDEF12345")
    classic = _SelectHost(rich_active=False)
    rich = _SelectHost(rich_active=True)

    classic.maybe_autoload(4, article)
    rich.maybe_autoload(4, article)

    assert classic.fulltext_scheduled == [(4, False)]
    assert rich.rich_scheduled == [(4, False)]


def test_selecting_an_ordinary_article_does_not_eager_load_off_mac():
    host = _SelectHost(rich_active=False)
    host.maybe_autoload(1, SimpleNamespace(url="https://www.macrumors.com/2026/07/09/story/"))
    if sys.platform != "darwin":
        assert host.fulltext_scheduled == []
        assert host.rich_scheduled == []
