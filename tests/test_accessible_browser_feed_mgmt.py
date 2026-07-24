# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Feed/category management, Deleted view, and restore in the macOS accessible
browser — the view-list context menu and the deleted-articles workflow.
"""

from types import SimpleNamespace

import pytest

wx = pytest.importorskip("wx")

from gui.accessibility import AccessibleBrowserFrame


class _Config:
    def __init__(self, v=None):
        self._v = dict(v or {})

    def get(self, key, default=None):
        return self._v.get(key, default)

    def set(self, key, value):
        self._v[key] = value


class _Provider:
    def __init__(self):
        self.deleted_categories = []
        self.restored = []

    def get_articles_page(self, *a, **k):
        return ([], 0)

    def mark_read(self, _id):
        pass

    def mark_unread(self, _id):
        pass

    def delete_category(self, cat_id):
        self.deleted_categories.append(cat_id)
        return True

    def restore_article(self, article_id, feed_id=None):
        self.restored.append((article_id, feed_id))
        return True


class _StubMainFrame(wx.Frame):
    article_page_size = 400

    def __init__(self, supports_restore=True):
        super().__init__(None, title="StubMainFrame")
        self.feed_map = {"f1": SimpleNamespace(id="f1", title="My Feed", url="https://feed.example/rss")}
        self._accessible_view_entries = []
        self.current_feed_id = "all"
        self.config_manager = _Config({"full_text_rich_view": False})
        self.provider = _Provider()
        self._supports_restore = supports_restore
        self.calls = []
        self.notif_state = {"f1": True}

    # recorders
    def _refresh_single_feed_thread(self, feed_id):
        self.calls.append(("refresh_feed", feed_id))

    def _confirm_and_mark_all_read(self, view_id, prompt):
        self.calls.append(("mark_all", view_id))

    def _is_feed_notifications_enabled(self, feed_id):
        return self.notif_state.get(feed_id, True)

    def _set_feed_notifications_enabled(self, feed_id, enabled):
        self.notif_state[feed_id] = enabled
        self.calls.append(("set_notif", feed_id, enabled))

    def remove_feed_by_id(self, feed_id, feed_title=None):
        self.calls.append(("remove_feed", feed_id))

    def _get_feed_title(self, feed_id):
        return "My Feed"

    def refresh_feeds(self):
        self.calls.append(("refresh_feeds",))

    def on_refresh_category(self, event=None, category_title=None):
        self.calls.append(("refresh_category", category_title))

    def on_edit_category(self, old_title):
        self.calls.append(("edit_category", old_title))

    def edit_feed_by_id(self, feed_id):
        self.calls.append(("edit_feed_by_id", feed_id))

    def on_add_subcategory(self, parent):
        self.calls.append(("add_subcategory", parent))

    def on_new_smart_folder(self):
        self.calls.append(("new_smart_folder",))

    def on_set_feed_images(self, feed_id, value):
        self.calls.append(("set_images", feed_id, value))

    def _supports_restore_deleted(self):
        return self._supports_restore

    def _supports_favorites(self):
        return False

    def _is_deleted_view(self, view_id):
        return str(view_id or "").startswith("deleted:")

    # required for construction
    def _filter_articles(self, articles, _q):
        return list(articles or [])

    def _sort_articles_for_display(self, articles):
        return list(articles or [])

    def _get_display_title(self, article):
        return str(getattr(article, "title", "") or "")

    def _strip_html(self, html):
        return str(html or "")

    def _article_cache_id(self, article):
        return getattr(article, "id", id(article))

    def _feed_language_for(self, feed_id):
        return None

    def _announce_event(self, *a, **k):
        pass


@pytest.fixture(scope="module")
def wxapp():
    app = wx.App(False)
    yield app
    try:
        app.Destroy()
    except Exception:
        pass


def _make(wxapp, supports_restore=True):
    mf = _StubMainFrame(supports_restore=supports_restore)
    frame = AccessibleBrowserFrame(mf)
    return mf, frame


def _destroy(mf, frame):
    try:
        frame.Destroy()
    finally:
        mf.Destroy()


def test_deleted_view_present_when_supported(wxapp):
    mf, frame = _make(wxapp, supports_restore=True)
    try:
        ids = [str(e.get("view_id")) for e in frame._view_entries]
        assert "deleted:all" in ids
    finally:
        _destroy(mf, frame)


def test_deleted_view_absent_when_unsupported(wxapp):
    mf, frame = _make(wxapp, supports_restore=False)
    try:
        ids = [str(e.get("view_id")) for e in frame._view_entries]
        assert "deleted:all" not in ids
    finally:
        _destroy(mf, frame)


def test_ctx_refresh_and_copy_and_notifications(wxapp):
    mf, frame = _make(wxapp)
    try:
        frame._ctx_refresh_feed("f1")
        assert ("refresh_feed", "f1") in mf.calls

        import gui.accessibility as acc
        copied = []
        orig = acc.copy_text_to_clipboard
        acc.copy_text_to_clipboard = lambda t: copied.append(t) or True
        try:
            frame._ctx_copy_feed_url("f1")
        finally:
            acc.copy_text_to_clipboard = orig
        assert "https://feed.example/rss" in copied

        frame._ctx_toggle_notifications("f1")  # was True -> False
        assert ("set_notif", "f1", False) in mf.calls
    finally:
        _destroy(mf, frame)


def test_ctx_remove_feed_confirmed(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        monkeypatch.setattr("gui.accessibility.wx.MessageBox", lambda *a, **k: wx.YES)
        frame._ctx_remove_feed("f1")
        assert ("remove_feed", "f1") in mf.calls
    finally:
        _destroy(mf, frame)


def test_ctx_remove_category_confirmed(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        monkeypatch.setattr("gui.accessibility.wx.MessageBox", lambda *a, **k: wx.YES)
        frame._ctx_remove_category("News")
        assert "News" in mf.provider.deleted_categories
        assert ("refresh_feeds",) in mf.calls
    finally:
        _destroy(mf, frame)


def test_ctx_remove_uncategorized_blocked(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        from core.categories import UNCATEGORIZED
        monkeypatch.setattr("gui.accessibility.wx.MessageBox", lambda *a, **k: wx.OK)
        frame._ctx_remove_category(UNCATEGORIZED)
        assert UNCATEGORIZED not in mf.provider.deleted_categories
    finally:
        _destroy(mf, frame)


def test_category_delegations(wxapp):
    mf, frame = _make(wxapp)
    try:
        frame._delegate("on_refresh_category", None, "News")
        frame._delegate("on_edit_category", "News")
        frame._delegate("on_add_subcategory", "News")
        frame._ctx_new_smart_folder()
        assert ("refresh_category", "News") in mf.calls
        assert ("edit_category", "News") in mf.calls
        assert ("add_subcategory", "News") in mf.calls
        assert ("new_smart_folder",) in mf.calls
    finally:
        _destroy(mf, frame)


def test_restore_article_calls_provider(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        frame.current_view_id = "deleted:all"
        art = SimpleNamespace(id="x1", feed_id="f1")
        frame._base_articles = [art]
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        assert frame._in_deleted_view() is True
        frame.on_restore_article()
        import time
        for _ in range(50):
            if mf.provider.restored:
                break
            time.sleep(0.01)
        assert ("x1", "f1") in mf.provider.restored
    finally:
        _destroy(mf, frame)


def test_view_context_menu_builds(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        monkeypatch.setattr(frame.view_list, "PopupMenu", lambda menu: None)
        monkeypatch.setattr(frame, "_selected_view_entry", lambda: {"kind": "feed", "view_id": "f1"})
        frame.on_view_context_menu(None)
        monkeypatch.setattr(frame, "_selected_view_entry", lambda: {"kind": "category", "view_id": "category:News", "cat_name": "News"})
        frame.on_view_context_menu(None)
    finally:
        _destroy(mf, frame)


def test_f2_opens_properties_for_the_selected_view_entry(wxapp, monkeypatch):
    """This window had no F2 handler at all, so the key did nothing here even
    after the main window's tree gained Category Properties (issue #86)."""
    mf, frame = _make(wxapp)
    try:
        monkeypatch.setattr(
            frame, "_selected_view_entry",
            lambda: {"kind": "category", "view_id": "category:News", "cat_name": "News"},
        )
        assert frame._edit_selected_view_entry() is True
        assert ("edit_category", "News") in mf.calls

        monkeypatch.setattr(
            frame, "_selected_view_entry", lambda: {"kind": "feed", "view_id": "f1"}
        )
        assert frame._edit_selected_view_entry() is True
        assert ("edit_feed_by_id", "f1") in mf.calls
    finally:
        _destroy(mf, frame)


def test_f2_ignores_entries_that_are_neither_feed_nor_category(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        monkeypatch.setattr(
            frame, "_selected_view_entry", lambda: {"kind": "special", "view_id": "deleted:all"}
        )
        assert frame._edit_selected_view_entry() is False
        assert mf.calls == []
    finally:
        _destroy(mf, frame)


def test_f2_key_event_reaches_the_editor_and_is_not_skipped(wxapp, monkeypatch):
    """Exercise on_view_list_key_down itself: the helper working is no use if
    the key never routes to it."""
    mf, frame = _make(wxapp)
    try:
        monkeypatch.setattr(
            frame, "_selected_view_entry",
            lambda: {"kind": "category", "view_id": "category:News", "cat_name": "News"},
        )
        evt = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        evt.SetKeyCode(wx.WXK_F2)
        skipped = []
        monkeypatch.setattr(evt, "Skip", lambda *a: skipped.append(True))

        frame.on_view_list_key_down(evt)

        assert ("edit_category", "News") in mf.calls
        assert skipped == []
    finally:
        _destroy(mf, frame)
