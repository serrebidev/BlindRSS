# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from __future__ import annotations

from types import SimpleNamespace

from bs4 import BeautifulSoup

from core import article_extractor, article_html, utils, youtube_fulltext


URL = "https://www.youtube.com/watch?v=abcDEF12345"


def _info():
    return {
        "id": "abcDEF12345",
        "title": "Accessible video",
        "channel": "Example Channel",
        "description": "The complete creator description.",
        "chapters": [
            {"start_time": 0, "title": "Opening"},
            {"start_time": 65, "title": "Demonstration"},
        ],
        "subtitles": {
            "en": [{"ext": "json3", "url": "https://subs.example/transcript"}],
        },
        # Deliberately place replies away from their parents. Rendering must
        # rebuild the tree instead of trusting the extractor's flat order.
        "comments": [
            {"id": "reply-two", "parent": "reply-one", "author": "Carol", "text": "Nested reply"},
            {"id": "root-two", "parent": "root", "author": "Dave", "text": "Second thread"},
            {"id": "reply-one", "parent": "root-one", "author": "Bob", "text": "First reply"},
            {"id": "root-one", "parent": "root", "author": "Alice", "text": "First thread"},
        ],
    }


class _SubtitleResponse:
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "events": [
                {"tStartMs": 0, "segs": [{"utf8": "First subtitle line"}]},
                {"tStartMs": 1500, "segs": [{"utf8": "Second subtitle line"}]},
            ]
        }


def test_youtube_url_detection_is_strict():
    assert youtube_fulltext.video_id_from_url(URL) == "abcDEF12345"
    assert youtube_fulltext.video_id_from_url("https://youtu.be/abcDEF12345") == "abcDEF12345"
    assert not youtube_fulltext.is_youtube_video_url("https://www.youtube.com/@example")
    assert not youtube_fulltext.is_youtube_video_url("https://example.com/watch?v=abcDEF12345")


def test_shared_document_orders_all_sections_and_nests_replies(monkeypatch):
    monkeypatch.setattr(utils, "safe_requests_get", lambda *args, **kwargs: _SubtitleResponse())
    fields = youtube_fulltext.article_fields_from_info(_info(), URL)
    text = fields["text"]

    assert text.index("Description") < text.index("Chapters") < text.index("Subtitles (en)") < text.index("Comments")
    assert "0:00 Opening" in text
    assert "1:05 Demonstration" in text
    assert "First subtitle line" in text
    assert "[0:00] First subtitle line" not in text
    assert "[0:01] Second subtitle line" not in text
    assert text.index("Comment by Alice") < text.index("Reply level 1 by Bob")
    assert text.index("Reply level 1 by Bob") < text.index("Reply level 2 by Carol")
    # Top-level threads retain YouTube's ordering; every descendant is still
    # moved beneath its own parent even when the flat input lists it elsewhere.
    assert text.index("Comment by Dave") < text.index("Comment by Alice")
    assert text.index("First thread") < text.index("First reply") < text.index("Nested reply")


def test_automatic_english_subtitles_beat_authored_non_english():
    info = {
        "subtitles": {"es": [{"ext": "vtt", "url": "https://subs.example/es"}]},
        "automatic_captions": {"en": [{"ext": "json3", "url": "https://subs.example/en"}]},
    }
    _kind, language, track = next(youtube_fulltext._subtitle_candidates(info))
    assert language == "en"
    assert track["url"].endswith("/en")


def test_subtitle_speaker_chevrons_are_not_spoken_as_greater():
    assert youtube_fulltext._clean_subtitle_text(">> Alice: Hello") == "Alice: Hello"
    assert youtube_fulltext._clean_subtitle_text("> Bob: Hi") == "Bob: Hi"
    assert youtube_fulltext._clean_subtitle_text("Value > 10") == "Value > 10"


def test_hosted_youtube_article_link_is_a_chapter_media_source():
    chapter_url, media_url, media_type = utils.chapter_source_and_media({
        "alternate": [{"href": URL, "type": "text/html"}],
    })
    assert chapter_url is None
    assert media_url == URL
    assert media_type == "video/youtube"


def test_plain_and_rich_views_share_youtube_reconstruction(monkeypatch):
    monkeypatch.setattr(utils, "safe_requests_get", lambda *args, **kwargs: _SubtitleResponse())
    monkeypatch.setattr(youtube_fulltext, "extract_video_info", lambda *args, **kwargs: _info())

    plain = article_extractor.extract_full_article(URL)
    rich = article_html.render_full_article_html(
        URL,
        fallback_title="Feed title",
        fallback_author="Feed author",
        fallback_html="<p>Short feed description</p>",
    )
    rich_text = BeautifulSoup(rich, "html.parser").get_text(" ", strip=True)

    assert plain.title == "Accessible video"
    for expected in (
        "The complete creator description.",
        "Demonstration",
        "Second subtitle line",
        "First thread",
        "Nested reply",
        "Second thread",
    ):
        assert expected in plain.text
        assert expected in rich_text
    assert "[0:00] First subtitle line" not in plain.text
    assert "[0:00] First subtitle line" not in rich_text
    soup = BeautifulSoup(rich, "html.parser")
    assert [heading.get_text(strip=True) for heading in soup.find_all("h2")] == [
        "Description",
        "Chapters",
        "Subtitles (en)",
        "Comments",
    ]
    sections = soup.select("div.awv-youtube-section")
    assert len(sections) >= 4
    assert not soup.find_all("h3")
    assert "Reply level 2 by Carol:" in sections[-1].get_text()
    assert sections[-1].get_text().index("First thread") < sections[-1].get_text().index("First reply")


def test_rich_youtube_sections_chunk_losslessly():
    source = "Description\n\n" + ("paragraph words\n\n" * 3000) + "TAIL"
    rendered = article_html._structured_youtube_text_html(source)
    soup = BeautifulSoup(rendered, "html.parser")
    chunks = soup.select("div.awv-youtube-section")

    assert len(chunks) > 1
    assert "".join(chunk.get_text() for chunk in chunks) == source.split("\n\n", 1)[1]
    assert max(len(chunk.get_text()) for chunk in chunks) <= article_html._YOUTUBE_ACCESSIBLE_CHUNK_CHARS


def test_youtube_chapters_use_the_normal_chapter_cache(monkeypatch):
    stored = {}
    monkeypatch.setattr(utils, "get_chapters_from_db", lambda *args, **kwargs: [])
    monkeypatch.setattr(youtube_fulltext, "extract_chapters", lambda url: [
        {"start": 0, "title": "Opening", "href": f"{url}&t=0s"},
        {"start": 65, "title": "Demonstration", "href": f"{url}&t=65s"},
    ])

    def _capture(article_id, chapters, **kwargs):
        stored["article_id"] = article_id
        stored["chapters"] = chapters

    monkeypatch.setattr(utils, "_replace_stored_chapters", _capture)
    chapters = utils.fetch_and_store_chapters("article-1", URL, "video/youtube")

    assert [chapter["title"] for chapter in chapters] == ["Opening", "Demonstration"]
    assert stored == {"article_id": "article-1", "chapters": chapters}
