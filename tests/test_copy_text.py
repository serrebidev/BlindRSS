import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _Host:
    on_copy_text = mainframe.MainFrame.on_copy_text
    _compose_article_copy_text = mainframe.MainFrame._compose_article_copy_text
    _compose_article_reader_text = mainframe.MainFrame._compose_article_reader_text
    _format_article_chapters_text = mainframe.MainFrame._format_article_chapters_text
    _format_chapter_timestamp = mainframe.MainFrame._format_chapter_timestamp
    _fulltext_cache_key_for_article = mainframe.MainFrame._fulltext_cache_key_for_article

    def __init__(self, articles, cache=None):
        self.current_articles = articles
        self._fulltext_cache = cache or {}
        self.copied = []

    # Stubs for the helpers _compose_article_copy_text depends on.
    def _translation_fulltext_cache_suffix(self):
        return ""

    def _show_images_for_feed(self, feed_id):
        return False

    def _strip_html(self, html, include_images=None):
        return f"BODY:{html}"

    def _copy_to_clipboard(self, text):
        self.copied.append(text)


def _article(**kw):
    base = dict(
        id="a1",
        url="https://example.com/article-1",
        title="My Headline",
        author="Jane Doe",
        date="2026-05-31T00:00:00Z",
        content="<p>short feed body</p>",
        feed_id="f1",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_copy_text_prefers_extracted_full_text():
    # Full text already extracted (e.g. on focus or via prefetch) and cached
    # under the article's URL key.
    article = _article()
    cached = "Title: My Headline\nAuthor: Jane Doe\n\nThe entire extracted article body, paragraphs and all."
    host = _Host([article], cache={article.url: cached})

    text = host._compose_article_copy_text(article, 0)

    assert text == cached


def test_copy_text_falls_back_to_feed_content_with_header():
    # No extracted full text yet: include the title/author/link header the
    # reading pane shows before extraction, plus the cleaned feed body.
    article = _article()
    host = _Host([article])

    text = host._compose_article_copy_text(article, 0)

    assert text.startswith("My Headline\n")
    assert "Author: Jane Doe" in text
    assert "Link: https://example.com/article-1" in text
    assert "BODY:<p>short feed body</p>" in text


def test_copy_text_handler_copies_full_text_to_clipboard():
    article = _article()
    cached = "Title: My Headline\nAuthor: Jane Doe\n\nFull body here."
    host = _Host([article], cache={article.url: cached})

    host.on_copy_text(0)

    assert host.copied == [cached]


def test_copy_text_handler_ignores_out_of_range_index():
    host = _Host([_article()])

    host.on_copy_text(9)

    assert host.copied == []


def test_copy_text_blank_cache_falls_back_to_feed_content():
    # A blank/whitespace cache entry must not be used as the copied text.
    article = _article()
    host = _Host([article], cache={article.url: "   \n  "})

    text = host._compose_article_copy_text(article, 0)

    assert "BODY:<p>short feed body</p>" in text


def test_copy_text_includes_chapters_with_cached_full_text():
    chapters = [
        {
            "start": 65,
            "title": "Details",
            "href": "https://example.com/details",
        }
    ]
    article = _article(chapters=chapters)
    cached = "Title: My Headline\nAuthor: Jane Doe\n\nFull body here."
    host = _Host([article], cache={article.url: cached})

    text = host._compose_article_copy_text(article, 0)

    assert text.startswith(cached)
    assert "Chapters (1):" in text
    assert "01:05, Details. Link: https://example.com/details" in text
