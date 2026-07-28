# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Direct podcast enclosures expose bounded embedded show notes to both readers."""

from io import BytesIO

from mutagen.id3 import ID3, TIT2, TPE1, USLT

from core import article_extractor, article_html, utils


PODTRAC_URL = (
    "https://www.podtrac.com/pts/redirect.mp3/pdst.fm/e/pscrb.fm/rss/p/"
    "mgln.ai/e/257/traffic.megaphone.fm/VMP1047667987.mp3"
)
SHOW_NOTES = (
    "<p>A complete episode summary for screen-reader users.</p>"
    '<p><a href="https://example.com/source">Read the source</a></p>'
)


def _id3_bytes():
    tag = ID3()
    tag.add(TIT2(encoding=3, text=["An embedded episode title"]))
    tag.add(TPE1(encoding=3, text=["The Podcast Author"]))
    tag.add(USLT(encoding=3, lang="eng", desc="", text=SHOW_NOTES))
    output = BytesIO()
    tag.save(output, v2_version=3)
    return output.getvalue()


def test_embedded_id3_metadata_reads_only_declared_remote_tag(monkeypatch):
    raw = _id3_bytes()
    calls = []

    def fake_read(_url, *, headers, max_bytes, timeout_s):
        calls.append((headers["Range"], max_bytes, timeout_s))
        return raw[:max_bytes]

    monkeypatch.setattr(utils, "_read_prefix_bytes", fake_read)

    metadata = utils.embedded_id3_metadata(PODTRAC_URL)

    assert metadata == {
        "title": "An embedded episode title",
        "author": "The Podcast Author",
        "content": SHOW_NOTES,
    }
    assert calls[0] == ("bytes=0-9", 10, 6)
    declared_total = max_bytes = calls[1][1]
    assert calls[1] == (f"bytes=0-{declared_total - 1}", max_bytes, 12)
    assert declared_total == len(raw)


def test_classic_fulltext_uses_embedded_id3_show_notes(monkeypatch):
    monkeypatch.setattr(
        utils,
        "embedded_id3_metadata",
        lambda _url: {
            "title": "An embedded episode title",
            "author": "The Podcast Author",
            "content": SHOW_NOTES,
        },
    )

    article = article_extractor.extract_full_article(PODTRAC_URL)
    rendered = article_extractor.render_full_article(PODTRAC_URL)

    assert article.title == "An embedded episode title"
    assert article.author == "The Podcast Author"
    assert "complete episode summary" in article.text
    assert "Read the source" in article.text
    assert "Title: An embedded episode title" in rendered
    assert "Author: The Podcast Author" in rendered


def test_only_mp3_media_is_an_extractable_fulltext_target():
    assert article_extractor.is_extractable_fulltext_url(PODTRAC_URL) is True
    assert article_extractor.is_extractable_fulltext_url("https://example.com/story") is True
    assert article_extractor.is_extractable_fulltext_url("https://example.com/photo.jpg") is False
    assert article_extractor.is_extractable_fulltext_url("https://example.com/video.mp4") is False


def test_rich_view_preserves_embedded_show_note_links(monkeypatch):
    monkeypatch.setattr(
        utils,
        "embedded_id3_metadata",
        lambda _url: {
            "title": "An embedded episode title",
            "author": "The Podcast Author",
            "content": SHOW_NOTES,
        },
    )

    rendered = article_html.render_full_article_html(PODTRAC_URL)

    assert "An embedded episode title" in rendered
    assert "complete episode summary" in rendered
    assert 'href="https://example.com/source"' in rendered


def test_feed_content_still_wins_for_media_enclosure(monkeypatch):
    monkeypatch.setattr(
        utils,
        "embedded_id3_metadata",
        lambda _url: (_ for _ in ()).throw(AssertionError("ID3 should not be fetched")),
    )

    rendered = article_extractor.render_full_article(
        PODTRAC_URL,
        fallback_html="<p>Feed-authored show notes.</p>",
        fallback_title="Feed title",
    )

    assert "Feed-authored show notes." in rendered
    assert "Title: Feed title" in rendered
