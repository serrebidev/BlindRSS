# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Unread/Read filter must drop rows whose status changed (issue #96).

The View > Article Filter is applied by the provider when a page is fetched
(the view id carries an "unread:"/"read:" prefix), so a row the user reads
afterwards stays in the loaded list. Refreshing feeds only merged *new*
entries in, and re-selecting a view rendered the cached list verbatim, so the
read article kept showing under an Unread Only filter.

These tests bind the real merge/render methods onto a lightweight host with a
fake ListCtrl (the pattern from tests/test_article_list_render.py) so no
wx.App is needed.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe
from gui.mainframe import ARTICLE_COL_TITLE


class _FakeConfig:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeListCtrl:
    def __init__(self):
        self.rows = []
        self.freeze_depth = 0
        self.focused = -1
        self.selected = -1
        self.top = 0
        self.columns = []

    def DeleteAllItems(self):
        self.rows = []

    def DeleteAllColumns(self):
        self.columns = []

    def InsertColumn(self, index, label, width=0):
        self.columns.insert(index, label)
        return index

    def InsertItem(self, index, label):
        index = max(0, min(int(index), len(self.rows)))
        self.rows.insert(index, {ARTICLE_COL_TITLE: label})
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

    def titles(self):
        return [r.get(ARTICLE_COL_TITLE, "") for r in self.rows]


class _MergeHost:
    # Filter helpers under test.
    _read_filter_mode_for_view = mainframe.MainFrame._read_filter_mode_for_view
    _apply_read_filter = mainframe.MainFrame._apply_read_filter
    _has_stale_read_filter_rows = mainframe.MainFrame._has_stale_read_filter_rows
    _apply_media_filter = mainframe.MainFrame._apply_media_filter
    _sort_articles_for_display = mainframe.MainFrame._sort_articles_for_display
    _article_sort_primary_key = mainframe.MainFrame._article_sort_primary_key

    # Merge/render path.
    _quick_merge_articles = mainframe.MainFrame._quick_merge_articles
    _plan_incremental_list_update = mainframe.MainFrame._plan_incremental_list_update
    _capture_top_article_for_restore = mainframe.MainFrame._capture_top_article_for_restore
    _ensure_view_state = mainframe.MainFrame._ensure_view_state
    _set_base_articles = mainframe.MainFrame._set_base_articles
    _article_cache_id = mainframe.MainFrame._article_cache_id
    _sync_read_flag_in_cached_views = mainframe.MainFrame._sync_read_flag_in_cached_views
    _is_search_active = mainframe.MainFrame._is_search_active
    _should_play_in_player = mainframe.MainFrame._should_play_in_player

    # Rendering.
    _render_articles_list = mainframe.MainFrame._render_articles_list
    _render_articles_batch = mainframe.MainFrame._render_articles_batch
    _render_batch_delay_ms = mainframe.MainFrame._render_batch_delay_ms
    _insert_article_row = mainframe.MainFrame._insert_article_row
    _article_media_label = mainframe.MainFrame._article_media_label
    _article_description_preview = mainframe.MainFrame._article_description_preview
    _article_description_text = mainframe.MainFrame._article_description_text
    _raw_article_description = mainframe.MainFrame._raw_article_description
    _get_display_title = mainframe.MainFrame._get_display_title
    _defer_restore_during_render = mainframe.MainFrame._defer_restore_during_render
    _reassert_load_more_placeholder_last = mainframe.MainFrame._reassert_load_more_placeholder_last
    _add_loading_more_placeholder = mainframe.MainFrame._add_loading_more_placeholder
    _remove_loading_more_placeholder = mainframe.MainFrame._remove_loading_more_placeholder
    _update_loading_placeholder = mainframe.MainFrame._update_loading_placeholder
    _is_load_more_row = mainframe.MainFrame._is_load_more_row
    _apply_column_layout = mainframe.MainFrame._apply_column_layout
    _resolve_column_layout = mainframe.MainFrame._resolve_column_layout
    _global_column_layout = mainframe.MainFrame._global_column_layout
    _feed_column_override = mainframe.MainFrame._feed_column_override
    _col = mainframe.MainFrame._col
    _set_col = mainframe.MainFrame._set_col
    _clear_non_title_cells = mainframe.MainFrame._clear_non_title_cells

    def __init__(self, view_id):
        self.list_ctrl = _FakeListCtrl()
        self.feed_map = {}
        self.config_manager = _FakeConfig()
        self.current_feed_id = view_id
        self.current_request_id = 1
        self.article_page_size = 200
        self.max_cached_views = 15
        self.view_cache = {}
        self._view_cache_lock = threading.Lock()
        self.current_articles = []
        self._base_articles = []
        self._base_view_id = None
        self.selected_article_id = None
        self._search_active = False
        self._search_query = ""
        self._article_read_filter = "all"
        self._article_media_filter = "all"
        self._article_sort_by = "date"
        self._article_sort_ascending = False
        self._updating_list = False
        self._article_render_inflight = False
        self._refresh_ui_batch_active = False
        self._loading_more_placeholder = False
        self._load_more_label = "Load more items (Enter)"
        self._loading_label = "Loading more..."
        self._render_generation = 0
        self._render_first_chunk = 60
        self._render_batch_size = 60
        self._column_keys = []
        self._column_index = {}
        self._applied_column_keys = None
        self._apply_column_layout(self._resolve_column_layout(None))

    # Stubs for collaborators the merge path only notifies.
    def _queue_fulltext_prefetch(self, articles):
        pass

    def _restore_list_view(self, *args, **kwargs):
        pass

    def _restore_load_more_focus(self, *args, **kwargs):
        pass

    def _populate_articles(self, *args, **kwargs):
        pass

    def _show_images_for_feed(self, feed_id):
        return False


def _article(idx, *, read=False, ts=None):
    a = mainframe.Article(
        title=f"Title {idx}",
        url=f"https://example.com/{idx}",
        content="",
        date="",
        author=f"Author {idx}",
        feed_id="feed-1",
        id=f"article-{idx}",
        is_read=read,
    )
    a.timestamp = float(ts if ts is not None else 1000 - idx)
    return a


def _install_sync_call_after(monkeypatch):
    """Run wx.CallAfter/CallLater callbacks immediately (deterministic tests)."""
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda cb, *a, **k: cb(*a, **k))
    monkeypatch.setattr(mainframe.wx, "CallLater", lambda _ms, cb, *a, **k: cb(*a, **k))


def _load(host, articles):
    host.current_articles = host._sort_articles_for_display(articles)
    host._set_base_articles(articles, host.current_feed_id)
    host._render_articles_list(host.current_articles)


def test_read_filter_mode_comes_from_the_view_id():
    host = _MergeHost("unread:all")
    assert host._read_filter_mode_for_view() == "unread"
    assert host._read_filter_mode_for_view("read:category:Tech") == "read"
    # Views the filter never wraps stay unfiltered.
    assert host._read_filter_mode_for_view("all") is None
    assert host._read_filter_mode_for_view("smart:abc") is None
    assert host._read_filter_mode_for_view("deleted:all") is None


def test_apply_read_filter_only_touches_filtered_views():
    articles = [_article(0), _article(1, read=True)]

    unfiltered = _MergeHost("all")
    assert unfiltered._apply_read_filter(articles) == articles

    unread_view = _MergeHost("unread:all")
    assert unread_view._apply_read_filter(articles) == [articles[0]]

    read_view = _MergeHost("read:all")
    assert read_view._apply_read_filter(articles) == [articles[1]]


def test_refresh_drops_an_article_read_since_the_last_load(monkeypatch):
    """Issue #96 repro: mark read in Unread Only, refresh, row must go."""
    _install_sync_call_after(monkeypatch)
    host = _MergeHost("unread:all")
    articles = [_article(0), _article(1), _article(2)]
    _load(host, articles)
    assert host.list_ctrl.titles() == ["Title 0", "Title 1", "Title 2"]

    # The user reads the middle article (mark_article_read's model update).
    articles[1].is_read = True

    # A refresh top-up returns the same page with nothing new.
    host._quick_merge_articles([_article(0), _article(2)], host.current_request_id, "unread:all")

    assert host.list_ctrl.titles() == ["Title 0", "Title 2"]
    assert [a.id for a in host.current_articles] == ["article-0", "article-2"]


def test_refresh_with_an_empty_top_up_page_still_drops_read_rows(monkeypatch):
    _install_sync_call_after(monkeypatch)
    host = _MergeHost("unread:all")
    articles = [_article(0)]
    _load(host, articles)
    articles[0].is_read = True

    # Every unread entry was read, so the server's newest page comes back empty.
    host._quick_merge_articles([], host.current_request_id, "unread:all")

    assert host.current_articles == []
    assert host.list_ctrl.titles() == ["No articles found."]


def test_read_only_view_drops_rows_marked_unread(monkeypatch):
    _install_sync_call_after(monkeypatch)
    host = _MergeHost("read:all")
    articles = [_article(0, read=True), _article(1, read=True)]
    _load(host, articles)
    articles[0].is_read = False

    host._quick_merge_articles([_article(1, read=True)], host.current_request_id, "read:all")

    assert [a.id for a in host.current_articles] == ["article-1"]


def test_unfiltered_view_keeps_read_articles(monkeypatch):
    _install_sync_call_after(monkeypatch)
    host = _MergeHost("all")
    articles = [_article(0), _article(1)]
    _load(host, articles)
    articles[1].is_read = True

    host._quick_merge_articles([_article(0), _article(1, read=True)], host.current_request_id, "all")

    # "All Articles" mode must never hide anything.
    assert host.list_ctrl.titles() == ["Title 0", "Title 1"]


def test_new_entries_still_merge_while_stale_rows_are_dropped(monkeypatch):
    _install_sync_call_after(monkeypatch)
    host = _MergeHost("unread:all")
    articles = [_article(1), _article(2)]
    _load(host, articles)
    articles[0].is_read = True  # article-1 read

    fresh = _article(0, ts=2000)  # newest, arrived during the refresh
    host._quick_merge_articles([fresh, _article(2)], host.current_request_id, "unread:all")

    assert [a.id for a in host.current_articles] == ["article-0", "article-2"]


class _RefreshEndHost:
    """Just enough of MainFrame to drive the end-of-refresh UI decision."""

    _maybe_finish_refresh_ui_batch = mainframe.MainFrame._maybe_finish_refresh_ui_batch
    _read_filter_mode_for_view = mainframe.MainFrame._read_filter_mode_for_view
    _has_stale_read_filter_rows = mainframe.MainFrame._has_stale_read_filter_rows

    def __init__(self, view_id, articles):
        self.current_feed_id = view_id
        self.current_articles = list(articles)
        self.feed_map = {"feed-1": object()}
        self._refresh_ui_batch_token = 1
        self._refresh_ui_batch_ending = True
        self._refresh_ui_batch_refresh_tree = True
        self._refresh_ui_batch_dirty = False  # nothing visible changed
        self._refresh_ui_batch_end_activity = False
        self._refresh_ui_batch_active = True
        self._article_refresh_dirty = False
        self._refresh_progress_lock = threading.Lock()
        self._refresh_progress_pending = {}
        self._refresh_progress_flush_scheduled = False
        self.calls = []

    def _end_refresh_activity(self):
        self.calls.append("end_activity")

    def _cancel_pending_article_reload(self):
        self.calls.append("cancel_reload")

    def refresh_feeds(self):
        self.calls.append("refresh_feeds")

    def _schedule_article_reload(self, delay_ms=None):
        self.calls.append("schedule_reload")

    def _refresh_articles_for_sort_change(self):
        self.calls.append("rerender")


def test_unchanged_refresh_still_rerenders_when_rows_went_stale():
    """A refresh that changes nothing must still drop rows read since load."""
    articles = [_article(0), _article(1, read=True)]
    host = _RefreshEndHost("unread:all", articles)

    host._maybe_finish_refresh_ui_batch(batch_token=1)

    assert host.calls == ["rerender"]


def test_unchanged_refresh_does_nothing_when_no_rows_are_stale():
    host = _RefreshEndHost("unread:all", [_article(0), _article(1)])

    host._maybe_finish_refresh_ui_batch(batch_token=1)

    assert host.calls == []


def test_read_state_syncs_into_other_cached_views():
    host = _MergeHost("unread:all")
    shared = _article(5)
    other_copy = _article(5)
    host.view_cache = {
        "unread:category:Tech": {"articles": [other_copy]},
        "unread:all": {"articles": [shared]},
    }

    # Cache ids are "<feed_id>:<article_id>" (see core.models.Article).
    host._sync_read_flag_in_cached_views(shared.cache_id, True)

    # The other view's own Article object must learn the new status, or the
    # filter would keep showing it there after a view switch.
    assert other_copy.is_read is True
    assert shared.is_read is True
