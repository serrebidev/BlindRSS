# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""GUI-free tests for chunked + memoized article-list rendering.

These exercise MainFrame._render_articles_list and its helpers without a real
wx.App by binding the methods onto a lightweight host and driving a fake
ListCtrl. wx.CallAfter is monkeypatched so the deferred render batches can be
drained deterministically (mirroring the fake-object pattern used by
tests/test_mainframe_issue22_shortcuts.py).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe
from core import article_columns
from gui.mainframe import (
    ARTICLE_COL_TITLE,
    ARTICLE_COL_AUTHOR,
    ARTICLE_COL_DATE,
    ARTICLE_COL_FEED,
    ARTICLE_COL_DESCRIPTION,
    ARTICLE_COL_STATUS,
)


class _FakeFeed:
    def __init__(self, title):
        self.title = title


class _FakeConfig:
    """Stand-in for ConfigManager exposing just the get() the layout code uses."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeListCtrl:
    """Minimal non-virtual ListCtrl double that records rows as column dicts."""

    def __init__(self):
        self.rows = []  # list of {col_index: value}
        self.freeze_depth = 0
        self.delete_all_calls = 0
        self.focused = -1
        self.selected = -1
        self.top = 0
        self.columns = []  # list of header labels, in display order

    def DeleteAllItems(self):
        self.delete_all_calls += 1
        self.rows = []

    def DeleteAllColumns(self):
        self.columns = []

    def InsertColumn(self, index, label, width=0):
        self.columns.insert(index, label)
        return index

    def InsertItem(self, index, label):
        index = max(0, min(int(index), len(self.rows)))
        self.rows.insert(index, {ARTICLE_COL_TITLE: label})
        if self.focused >= index:
            self.focused += 1
        if self.selected >= index:
            self.selected += 1
        if self.top >= index and len(self.rows) > 1:
            self.top += 1
        return index

    def SetItem(self, index, col, value):
        self.rows[index][col] = value

    def GetItemCount(self):
        return len(self.rows)

    def GetItemText(self, index, col=ARTICLE_COL_TITLE):
        if 0 <= index < len(self.rows):
            return self.rows[index].get(col, "")
        return ""

    def DeleteItem(self, index):
        del self.rows[index]
        if self.focused > index:
            self.focused -= 1
        elif self.focused == index:
            self.focused = -1
        if self.selected > index:
            self.selected -= 1
        elif self.selected == index:
            self.selected = -1
        if self.top > index:
            self.top -= 1

    def GetFocusedItem(self):
        return self.focused

    def GetFirstSelected(self):
        return self.selected

    def GetTopItem(self):
        return self.top

    def Freeze(self):
        self.freeze_depth += 1

    def Thaw(self):
        self.freeze_depth -= 1

    # Test convenience.
    def col(self, index, col):
        return self.rows[index].get(col, "")

    def titles(self):
        return [self.rows[i].get(ARTICLE_COL_TITLE, "") for i in range(len(self.rows))]


class _RenderHost:
    # Methods under test.
    _render_articles_list = mainframe.MainFrame._render_articles_list
    _insert_article_row = mainframe.MainFrame._insert_article_row
    _article_media_label = mainframe.MainFrame._article_media_label
    _should_play_in_player = mainframe.MainFrame._should_play_in_player
    _render_articles_batch = mainframe.MainFrame._render_articles_batch
    _render_batch_delay_ms = mainframe.MainFrame._render_batch_delay_ms
    _reassert_load_more_placeholder_last = mainframe.MainFrame._reassert_load_more_placeholder_last
    _defer_restore_during_render = mainframe.MainFrame._defer_restore_during_render
    _article_description_preview = mainframe.MainFrame._article_description_preview
    _get_display_title = mainframe.MainFrame._get_display_title
    _add_loading_more_placeholder = mainframe.MainFrame._add_loading_more_placeholder
    _remove_loading_more_placeholder = mainframe.MainFrame._remove_loading_more_placeholder
    _update_loading_placeholder = mainframe.MainFrame._update_loading_placeholder
    _is_load_more_row = mainframe.MainFrame._is_load_more_row
    # Column layout (article list columns): the real methods, so renders exercise the same
    # key->index resolution the app uses.
    _apply_column_layout = mainframe.MainFrame._apply_column_layout
    _resolve_column_layout = mainframe.MainFrame._resolve_column_layout
    _global_column_layout = mainframe.MainFrame._global_column_layout
    _feed_column_override = mainframe.MainFrame._feed_column_override
    _col = mainframe.MainFrame._col
    _set_col = mainframe.MainFrame._set_col
    _clear_non_title_cells = mainframe.MainFrame._clear_non_title_cells

    def __init__(self, *, first_chunk=2, batch_size=2, feed_map=None, columns=None):
        self.list_ctrl = _FakeListCtrl()
        self.feed_map = feed_map or {}
        self.current_feed_id = "all"
        self.config_manager = _FakeConfig({"article_columns": columns})
        self._column_keys = []
        self._column_index = {}
        self._applied_column_keys = None
        self._apply_column_layout(self._resolve_column_layout(None))
        self._render_generation = 0
        self._render_first_chunk = first_chunk
        self._render_batch_size = batch_size
        self._article_render_inflight = False
        self._refresh_ui_batch_active = False
        self._loading_more_placeholder = False
        self._load_more_label = "Load more items (Enter)"
        self._loading_label = "Loading more..."
        # Spy: count builder calls per article id so memoization is observable.
        self.desc_text_calls = {}

    def _article_description_text(self, article, include_images=None):
        _ = include_images
        key = article.id
        self.desc_text_calls[key] = self.desc_text_calls.get(key, 0) + 1
        return f"Description for {article.title}"


def _make_article(idx, *, title=None, author=None, read=False):
    return mainframe.Article(
        title=title if title is not None else f"Title {idx}",
        url=f"https://example.com/{idx}",
        content="",
        date="",  # humanize_article_date("") -> "" (deterministic)
        author=author if author is not None else f"Author {idx}",
        feed_id="feed-1",
        id=f"article-{idx}",
        is_read=read,
    )


def _install_capturing_call_after(monkeypatch):
    captured = []

    def _fake_call_after(callback, *args, **kwargs):
        captured.append((callback, args, kwargs))

    def _fake_call_later(_ms, callback, *args, **kwargs):
        # Render batches chain via wx.CallLater(1, ...) so the real event loop
        # can interleave input between batches; for tests it drains the same.
        captured.append((callback, args, kwargs))

    monkeypatch.setattr(mainframe.wx, "CallAfter", _fake_call_after)
    monkeypatch.setattr(mainframe.wx, "CallLater", _fake_call_later)
    return captured


def _drain(captured):
    """Run queued callbacks FIFO; a callback may enqueue further batches."""
    guard = 0
    while captured:
        guard += 1
        assert guard < 10000, "runaway deferred-render queue"
        callback, args, kwargs = captured.pop(0)
        callback(*args, **kwargs)


def test_description_preview_memoized_across_renders(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    articles = [_make_article(i) for i in range(5)]
    preview_calls = []
    original_preview = mainframe.utils.html_to_text_preview

    def counting_preview(html, max_chars=320):
        preview_calls.append(html)
        return original_preview(html, max_chars=max_chars)

    monkeypatch.setattr(mainframe.utils, "html_to_text_preview", counting_preview)

    host._render_articles_list(articles)
    _drain(captured)
    # First full render builds each article's preview exactly once.
    assert len(preview_calls) == len(articles)

    host._render_articles_list(articles)
    _drain(captured)
    # Second render of the same articles reuses the memoized preview: no rebuilds.
    assert len(preview_calls) == len(articles)


def test_chunked_render_produces_one_row_per_article_in_order(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    feed_map = {"feed-1": _FakeFeed("My Feed")}
    host = _RenderHost(first_chunk=2, batch_size=2, feed_map=feed_map)
    articles = [_make_article(i, read=(i % 2 == 0)) for i in range(5)]

    host._render_articles_list(articles)
    # Only the synchronous first chunk is present immediately.
    assert host.list_ctrl.GetItemCount() == 2
    assert host._article_render_inflight is True
    assert len(captured) == 1

    _drain(captured)

    # Draining the deferred batches completes the list: one row per article,
    # input order preserved, no placeholder, correct column values.
    assert host.list_ctrl.GetItemCount() == 5
    assert host._article_render_inflight is False
    for i, a in enumerate(articles):
        assert host.list_ctrl.col(i, ARTICLE_COL_TITLE) == a.title
        assert host.list_ctrl.col(i, ARTICLE_COL_AUTHOR) == a.author
        assert host.list_ctrl.col(i, ARTICLE_COL_DATE) == ""
        assert host.list_ctrl.col(i, ARTICLE_COL_FEED) == "My Feed"
        assert host.list_ctrl.col(i, ARTICLE_COL_DESCRIPTION) == a._desc_preview_240
        assert host.list_ctrl.col(i, ARTICLE_COL_STATUS) == ("Read" if a.is_read else "Unread")


def test_superseded_generation_stops_stale_batches(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    first = [_make_article(i, title=f"A{i}") for i in range(5)]
    second = [_make_article(100 + i, title=f"B{i}") for i in range(3)]

    host._render_articles_list(first)  # renders A0,A1; queues a batch for A2..A4
    assert host.list_ctrl.titles() == ["A0", "A1"]
    assert len(captured) == 1

    # A new render (same feed) supersedes the first by bumping _render_generation.
    host._render_articles_list(second)
    assert host.list_ctrl.titles() == ["B0", "B1"]

    _drain(captured)

    # The stale first-render batch must add nothing; only the new view remains.
    assert host.list_ctrl.titles() == ["B0", "B1", "B2"]
    assert host._article_render_inflight is False


def test_view_switch_without_generation_bump_stops_batches(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    articles = [_make_article(i) for i in range(5)]

    host._render_articles_list(articles)  # gen=1, feed="all", batch queued
    assert host._article_render_inflight is True

    # Mirror _select_view's empty cached-view branch: swap the current view and
    # clear the list WITHOUT calling _render_articles_list (no generation bump).
    host.current_feed_id = "feed-9"
    host.list_ctrl.DeleteAllItems()
    host.list_ctrl.InsertItem(0, "No articles found.")

    _drain(captured)

    # The stale batch detects the view change and abandons instead of injecting
    # the old view's rows into the new (empty) view.
    assert host.list_ctrl.titles() == ["No articles found."]
    assert host._article_render_inflight is False


def test_empty_input_renders_single_empty_label(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost()

    host._render_articles_list([], empty_label="No articles found.")

    assert host.list_ctrl.GetItemCount() == 1
    assert host.list_ctrl.col(0, ARTICLE_COL_TITLE) == "No articles found."
    assert host._article_render_inflight is False
    assert captured == []


def test_async_batches_keep_load_more_placeholder_last(monkeypatch):
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=2, batch_size=2)
    articles = [_make_article(i) for i in range(5)]

    host._render_articles_list(articles)
    # Caller adds the placeholder synchronously right after render returns, like
    # _select_view / _populate_articles do. It lands right after the first chunk.
    host._add_loading_more_placeholder()
    assert host._loading_more_placeholder is True
    assert host.list_ctrl.GetItemCount() == 3
    assert host.list_ctrl.col(2, ARTICLE_COL_TITLE) == host._load_more_label

    _drain(captured)

    # All articles rendered in order and the placeholder remains the LAST row,
    # even though later batches appended rows above it.
    assert host.list_ctrl.GetItemCount() == 6
    for i, a in enumerate(articles):
        assert host.list_ctrl.col(i, ARTICLE_COL_TITLE) == a.title
    assert host.list_ctrl.col(5, ARTICLE_COL_TITLE) == host._load_more_label
    assert host._is_load_more_row(5) is True
    assert host._is_load_more_row(4) is False


def test_description_preview_long_max_len_is_not_memoized_short(monkeypatch):
    # The 4000-char sort path must never receive the 240-char list truncation.
    _install_capturing_call_after(monkeypatch)
    host = _RenderHost()
    article = _make_article(0)
    article.description = "word " * 200  # ~1000 chars of plain text

    # Provide the real text builder path for this one article via a stub that
    # returns the raw description so lengths are meaningful.
    host._article_description_text = lambda a, include_images=None: a.description

    short = host._article_description_preview(article)  # default max_len=240
    long = host._article_description_preview(article, max_len=4000)

    assert len(short) <= 240
    assert short.endswith("...")
    assert len(long) > 240  # full text, not the cached 240-char preview
    assert getattr(article, "_desc_preview_240") == short


def test_refresh_batch_uses_longer_gaps_between_native_render_chunks():
    host = _RenderHost()

    assert host._render_batch_delay_ms() == 1
    host._refresh_ui_batch_active = True
    assert host._render_batch_delay_ms() == 15


def test_incremental_plan_accepts_insert_plus_capped_oldest_suffix_trim():
    host = _RenderHost()
    host._article_cache_id = lambda article: article.cache_id
    old = [_make_article(i) for i in range(4)]
    fresh = _make_article(9)
    new = [fresh, *old[:3]]

    plan = mainframe.MainFrame._plan_incremental_list_update(
        host, old, new, {fresh.cache_id}
    )

    assert plan == ([(0, fresh)], 1)


def test_incremental_plan_rejects_middle_removal():
    host = _RenderHost()
    host._article_cache_id = lambda article: article.cache_id
    old = [_make_article(i) for i in range(4)]
    fresh = _make_article(9)
    new = [fresh, old[0], old[2], old[3]]

    plan = mainframe.MainFrame._plan_incremental_list_update(
        host, old, new, {fresh.cache_id}
    )

    assert plan is None


def test_quick_merge_updates_capped_page_without_full_native_rebuild():
    class _MergeHost(_RenderHost):
        _quick_merge_articles = mainframe.MainFrame._quick_merge_articles
        _plan_incremental_list_update = mainframe.MainFrame._plan_incremental_list_update
        _set_base_articles = mainframe.MainFrame._set_base_articles
        _capture_top_article_for_restore = mainframe.MainFrame._capture_top_article_for_restore
        _read_filter_mode_for_view = mainframe.MainFrame._read_filter_mode_for_view
        _has_stale_read_filter_rows = mainframe.MainFrame._has_stale_read_filter_rows

        def __init__(self):
            super().__init__(first_chunk=4, batch_size=4)
            self.article_page_size = 4
            self.current_feed_id = "all"
            self.current_request_id = 1
            self._base_view_id = "all"
            self._updating_list = False
            self._state = {"paged_offset": 4, "total": 10}

        def _article_cache_id(self, article):
            return article.cache_id

        def _ensure_view_state(self, _feed_id):
            return self._state

        def _is_search_active(self):
            return False

        def _sort_articles_for_display(self, articles):
            return sorted(
                articles,
                key=lambda article: (article.timestamp, article.cache_id),
                reverse=True,
            )

        def _queue_fulltext_prefetch(self, _articles):
            return None

        def _restore_list_view(self, *_args):
            raise AssertionError("incremental merge must not restore the whole list")

        def _restore_load_more_focus(self):
            raise AssertionError("incremental merge must not restore the placeholder")

    host = _MergeHost()
    old = [_make_article(i) for i in range(4)]
    for timestamp, article in zip((4, 3, 2, 1), old):
        article.timestamp = timestamp
    host._base_articles = list(old)
    host.current_articles = list(old)
    for idx, article in enumerate(old):
        host._insert_article_row(idx, article)
    host.list_ctrl.delete_all_calls = 0
    host.list_ctrl.focused = 1
    host.list_ctrl.selected = 1
    host.list_ctrl.top = 1

    fresh = _make_article(9)
    fresh.timestamp = 5
    host._quick_merge_articles([fresh, *old[:3]], 1, "all")

    assert host.list_ctrl.delete_all_calls == 0
    assert host.list_ctrl.titles()[:4] == [fresh.title, *(a.title for a in old[:3])]
    assert host.list_ctrl.titles()[4] == host._load_more_label
    assert host.list_ctrl.focused == 2
    assert host.list_ctrl.selected == 2


# --- Column layout (article list columns) ----------------------------------------------


def test_render_honors_a_custom_global_column_layout(monkeypatch):
    """Hiding Media and moving Feed ahead of Author must move the actual cells,
    not just the headers: a stale key->index map would write Author's text into
    whatever column now sits at index 1."""
    captured = _install_capturing_call_after(monkeypatch)
    feed_map = {"feed-1": _FakeFeed("My Feed")}
    layout = article_columns.set_visible(
        article_columns.move_key(article_columns.default_layout(), "feed", -3),
        "media",
        False,
    )
    host = _RenderHost(first_chunk=10, batch_size=10, feed_map=feed_map, columns=layout)
    article = _make_article(0)

    host._render_articles_list([article])
    _drain(captured)

    assert host.list_ctrl.columns == ["Title", "Feed", "Author", "Date", "Description", "Status"]
    row = host.list_ctrl.rows[0]
    assert row[0] == article.title
    assert row[1] == "My Feed"
    assert row[2] == article.author
    # The hidden Media column has no index at all -- nothing may be written past
    # the last real column.
    assert host._col("media") is None
    assert max(row.keys()) == len(host.list_ctrl.columns) - 1


def test_render_applies_per_feed_override_and_reverts_for_mixed_views(monkeypatch):
    """A single-feed view uses that feed's override; a category/All view (whose
    id is not a feed) falls back to the global layout."""
    captured = _install_capturing_call_after(monkeypatch)
    feed_map = {"feed-1": _FakeFeed("My Feed")}
    host = _RenderHost(first_chunk=10, batch_size=10, feed_map=feed_map)

    feed_layout = article_columns.set_visible(article_columns.default_layout(), "media", False)
    monkeypatch.setattr(
        host, "_feed_column_override",
        lambda view_id: feed_layout if view_id == "feed-1" else None,
    )

    host.current_feed_id = "feed-1"
    host._render_articles_list([_make_article(0)])
    _drain(captured)
    assert "Media" not in host.list_ctrl.columns

    host.current_feed_id = "all"
    host._render_articles_list([_make_article(1)])
    _drain(captured)
    assert "Media" in host.list_ctrl.columns


def test_repeat_render_does_not_rebuild_unchanged_columns(monkeypatch):
    """Column rebuilds clear the list, so the throttled mid-refresh reload path
    must not pay for one on every cycle."""
    captured = _install_capturing_call_after(monkeypatch)
    host = _RenderHost(first_chunk=10, batch_size=10, feed_map={"feed-1": _FakeFeed("My Feed")})

    assert host._apply_column_layout(host._resolve_column_layout(None)) is False
    before = list(host.list_ctrl.columns)
    host._render_articles_list([_make_article(0)])
    _drain(captured)
    assert host.list_ctrl.columns == before


def test_placeholder_rows_clear_cells_under_a_custom_layout(monkeypatch):
    """'No articles found.' must own column 0 whatever the layout, with no stale
    text in the remaining columns."""
    captured = _install_capturing_call_after(monkeypatch)
    layout = article_columns.set_visible(article_columns.default_layout(), "media", False)
    host = _RenderHost(first_chunk=10, batch_size=10, columns=layout)

    host._render_articles_list([])
    _drain(captured)
    assert host.list_ctrl.rows[0][0] == "No articles found."

    host._add_loading_more_placeholder()
    row = host.list_ctrl.rows[-1]
    assert row[0] == host._load_more_label
    assert all(row[i] == "" for i in range(1, len(host.list_ctrl.columns)))
