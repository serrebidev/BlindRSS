# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""GUI-free tests for the off-UI-thread article row annotation precompute.

Large-category lag fix: first-time computation of the description preview
(HTML->text parse) and media label (yt-dlp extractor URL matching) is too slow
for the list-render loop, so the loader threads warm both memos via
_precompute_article_row_annotations before handing articles to wx.CallAfter.
These tests pin that the precompute fills the per-Article memos and that the
render-path helpers then serve from cache without recomputing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe
from core import article_columns


class _Article:
    def __init__(self, **kw):
        self.title = kw.get("title", "t")
        self.url = kw.get("url", "https://example.com/news/story")
        self.media_url = kw.get("media_url", "")
        self.media_type = kw.get("media_type", "")
        self.description = kw.get("description", "<p>Hello   <b>world</b></p>")
        self.content = kw.get("content", "")
        self.feed_id = kw.get("feed_id", "f1")
        self.id = kw.get("id", 1)


class _Host:
    _precompute_article_row_annotations = mainframe.MainFrame._precompute_article_row_annotations
    _article_description_preview = mainframe.MainFrame._article_description_preview
    _article_description_text = mainframe.MainFrame._article_description_text
    _raw_article_description = mainframe.MainFrame._raw_article_description
    _strip_html = mainframe.MainFrame._strip_html
    _article_media_label = mainframe.MainFrame._article_media_label
    _should_play_in_player = mainframe.MainFrame._should_play_in_player
    _playback_state_for_article = mainframe.MainFrame._playback_state_for_article
    _playback_time_annotation = mainframe.MainFrame._playback_time_annotation
    _format_media_time = staticmethod(mainframe.MainFrame._format_media_time)
    _update_live_media_annotation = mainframe.MainFrame._update_live_media_annotation
    _invalidate_article_media_label = staticmethod(mainframe.MainFrame._invalidate_article_media_label)
    _refresh_article_in_list = mainframe.MainFrame._refresh_article_in_list
    _update_cached_views_for_article = mainframe.MainFrame._update_cached_views_for_article
    _next_articles_request_id = mainframe.MainFrame._next_articles_request_id
    _is_articles_load_current = mainframe.MainFrame._is_articles_load_current
    # Column layout (article list columns): media-column writes resolve their index through
    # _col, so the host needs the default key->index map.
    _col = mainframe.MainFrame._col
    _set_col = mainframe.MainFrame._set_col
    _column_index = {key: i for i, key in enumerate(article_columns.DEFAULT_ORDER)}
    _column_keys = list(article_columns.DEFAULT_ORDER)


def test_precompute_fills_both_memos():
    h = _Host()
    articles = [
        _Article(),
        _Article(url="https://www.youtube.com/watch?v=abc123"),
        _Article(media_url="https://cdn.example.com/e.mp3", media_type="audio/mpeg"),
    ]
    h._precompute_article_row_annotations(articles)
    for a in articles:
        assert getattr(a, "_desc_preview_240", None) is not None
        assert getattr(a, "_media_label_cached", None) is not None


def test_render_path_uses_memo_without_recompute(monkeypatch):
    h = _Host()
    a = _Article()
    h._precompute_article_row_annotations([a])
    preview = a._desc_preview_240
    label = a._media_label_cached
    assert "Hello world" in preview

    # After precompute the render-loop calls must be pure cache reads: poison
    # the recompute paths and make sure the memoized values are still served.
    def _preview_boom(*_a, **_k):
        raise AssertionError("description preview recomputed on render path")
    monkeypatch.setattr(mainframe.utils, "html_to_text_preview", _preview_boom)
    def _boom(*_a, **_k):
        raise AssertionError("media label recomputed on render path")
    h._should_play_in_player = _boom

    assert h._article_description_preview(a) == preview
    assert h._article_media_label(a) == label


def test_preview_cache_survives_article_object_rebuilds(monkeypatch):
    """Refresh reload storms build NEW Article objects each cycle; the
    second-level LRU (keyed by article id + content hash) must serve them
    without re-parsing, or every refresh cycle costs ~1.5s of loader-thread
    CPU and starves the UI via the GIL."""
    h = _Host()
    h._article_cache_id = lambda a: "id-1"

    parses = []
    orig_preview = mainframe.utils.html_to_text_preview
    def counting_preview(html, max_chars=320):
        parses.append(1)
        return orig_preview(html, max_chars=max_chars)
    monkeypatch.setattr(mainframe.utils, "html_to_text_preview", counting_preview)

    first = _Article()
    h._precompute_article_row_annotations([first])
    assert len(parses) == 1

    # Same article id + identical content, but a brand-new object (as built by
    # the next refresh cycle): must be a cache hit, not a re-parse.
    rebuilt = _Article()
    h._precompute_article_row_annotations([rebuilt])
    assert len(parses) == 1
    assert rebuilt._desc_preview_240 == first._desc_preview_240

    # Changed content -> re-parse (cache key includes the content hash).
    changed = _Article(description="<p>Different</p>")
    h._precompute_article_row_annotations([changed])
    assert len(parses) == 2


def test_precompute_survives_broken_articles():
    h = _Host()
    class _Broken:
        # attribute access raising must not abort the batch
        def __getattr__(self, name):
            raise RuntimeError("nope")
    ok = _Article()
    h._precompute_article_row_annotations([_Broken(), ok])
    assert getattr(ok, "_media_label_cached", None) is not None


def test_precompute_stops_when_navigation_supersedes_request():
    h = _Host()
    articles = [_Article(id=i) for i in range(10)]
    checks = 0

    def still_current():
        nonlocal checks
        checks += 1
        return checks < 3

    assert h._precompute_article_row_annotations(
        articles, should_continue=still_current
    ) is False
    assert getattr(articles[0], "_desc_preview_240", None) is not None
    assert getattr(articles[1], "_desc_preview_240", None) is not None
    assert getattr(articles[2], "_desc_preview_240", None) is None


def test_article_request_generations_are_unique_and_view_scoped():
    h = _Host()
    h.current_feed_id = "feed-a"
    first = h._next_articles_request_id()
    second = h._next_articles_request_id()

    assert second == first + 1
    assert not h._is_articles_load_current("feed-a", first)
    assert h._is_articles_load_current("feed-a", second)
    assert not h._is_articles_load_current("feed-b", second)


def test_stale_page_is_discarded_before_precompute():
    class _PageArticle:
        timestamp = 1
        id = 1

    class _Provider:
        def get_articles_page(self, *_args, **_kwargs):
            return [_PageArticle()], 1

    class _LoadHost:
        _load_articles_thread = mainframe.MainFrame._load_articles_thread
        _is_articles_load_current = mainframe.MainFrame._is_articles_load_current
        article_page_size = 400
        current_feed_id = "new-view"
        current_request_id = 2
        provider = _Provider()

        @staticmethod
        def _article_cache_id(article):
            return article.id

        @staticmethod
        def _precompute_article_row_annotations(*_args, **_kwargs):
            raise AssertionError("stale page should not be precomputed")

    _LoadHost()._load_articles_thread("old-view", 1)


def test_live_player_duration_refreshes_visible_media_column():
    class _List:
        def __init__(self):
            self.value = mainframe.ARTICLE_MEDIA_YES + ", not played"

        def GetItemCount(self):
            # See _MediaColList.GetItemCount: the live-annotation path
            # bounds-checks the row before writing the cell.
            return 1

        def GetItemText(self, _row, _col):
            return self.value

        def SetItem(self, _row, _col, value):
            self.value = value

    h = _Host()
    article = _Article(id=42, media_url="https://cdn.example.com/show.mp3", media_type="audio/mpeg")
    h.current_articles = [article]
    h.list_ctrl = _List()
    h._playback_states_cache = {}
    h._precompute_article_row_annotations([article])

    h._update_live_media_annotation({
        "has_media": True,
        "article_id": 42,
        "media_url": article.media_url,
        "position_ms": 2_000,
        "duration_ms": 125_000,
    })

    assert h.list_ctrl.value == "Contains audio, 2:05, played 0:02"


class _MediaColList:
    """Minimal list_ctrl capturing writes to the Media column."""

    def __init__(self, initial, item_count=1):
        self.value = initial
        self._item_count = item_count

    def GetItemCount(self):
        # The live-annotation path bounds-checks the row against this before
        # touching it (an out-of-range read makes wx raise an uncatchable
        # wxLogError modal). Without it the AttributeError is swallowed by that
        # path's except-clause and the cell write is silently skipped.
        return self._item_count

    def GetItemText(self, _row, _col):
        return self.value

    def SetItem(self, _row, col, value):
        if col == mainframe.ARTICLE_COL_MEDIA:
            self.value = value


def test_detect_audio_refresh_updates_stuck_no_audio_column():
    """Issue: article gains audio via Detect Audio (NPR pattern), but the
    memoized Media label kept the row stuck on 'No audio'. The refresh path
    must drop the memo and repaint the visible cell."""
    import threading

    h = _Host()
    article = _Article(id=7, url="https://www.npr.org/2026/07/11/story")
    h.current_articles = [article]
    h.list_ctrl = _MediaColList(mainframe.ARTICLE_MEDIA_NO)
    h._playback_states_cache = {}
    h._article_cache_id = lambda a: getattr(a, "id", None)
    h._view_cache_lock = threading.Lock()

    # Cached-view copy of the same article (user navigated away and back).
    cached_copy = _Article(id=7, url=article.url)
    h.view_cache = {"feed:f1": {"articles": [cached_copy]}}

    # Row rendered before audio existed: memo says "No audio".
    h._precompute_article_row_annotations([article, cached_copy])
    assert article._media_label_cached == mainframe.ARTICLE_MEDIA_NO

    # Detect Audio attaches the enclosure, then refreshes the row.
    article.media_url = "https://ondemand.npr.org/story.mp3"
    article.media_type = "audio/mpeg"
    h._invalidate_article_media_label(article)
    h._refresh_article_in_list(7)

    assert h.list_ctrl.value.startswith(mainframe.ARTICLE_MEDIA_YES)
    assert article._has_media_cached is True
    # The cached view got the media and lost its stale memo too.
    assert cached_copy.media_url == article.media_url
    assert getattr(cached_copy, "_media_label_cached", None) is None


def test_playing_article_corrects_stale_no_audio_label():
    """If the player is actively playing media for an article whose memoized
    label still says 'No audio', the live annotation pass must correct it."""
    h = _Host()
    article = _Article(id=9, url="https://www.npr.org/2026/07/11/other-story")
    h.current_articles = [article]
    h.list_ctrl = _MediaColList(mainframe.ARTICLE_MEDIA_NO)
    h._playback_states_cache = {}
    h._precompute_article_row_annotations([article])
    assert article._has_media_cached is False

    h._update_live_media_annotation({
        "has_media": True,
        "article_id": 9,
        "media_url": "https://ondemand.npr.org/other.mp3",
        "position_ms": 3_000,
        "duration_ms": 60_000,
    })

    assert article._has_media_cached is True
    assert h.list_ctrl.value.startswith(mainframe.ARTICLE_MEDIA_YES)
