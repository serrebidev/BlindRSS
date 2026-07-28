# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Article actions in the macOS accessible browser: favorites, delete, view
history, feed description, and find-in-article — parity with the main window's
per-article commands, driven from THIS window's selected article.
"""

from types import SimpleNamespace

import pytest

wx = pytest.importorskip("wx")

from gui import accessibility
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
        self.toggled = []
        self.deleted = []
        self._fav = True

    def get_articles_page(self, *a, **k):
        return ([], 0)

    def mark_read(self, _id):
        pass

    def mark_unread(self, _id):
        pass

    def toggle_favorite(self, article_id):
        self.toggled.append(article_id)
        self._fav = not self._fav
        return self._fav

    def delete_article(self, article_id):
        self.deleted.append(article_id)
        return True


class _StubMainFrame(wx.Frame):
    article_page_size = 400

    def __init__(self):
        super().__init__(None, title="StubMainFrame")
        self.feed_map = {}
        self._accessible_view_entries = []
        self.current_feed_id = "all"
        self.config_manager = _Config({"full_text_rich_view": False, "confirm_article_delete": False})
        self.provider = _Provider()
        self.history_calls = []
        self.desc_calls = []

    def _filter_articles(self, articles, _q):
        return list(articles or [])

    def _sort_articles_for_display(self, articles, view_id=None):
        return list(articles or [])

    def _get_display_title(self, article):
        return str(getattr(article, "title", "") or "")

    def _strip_html(self, html):
        return str(html or "")

    def _article_cache_id(self, article):
        return getattr(article, "id", id(article))

    def _feed_language_for(self, feed_id):
        return None

    def _supports_favorites(self):
        return True

    def _supports_article_delete(self):
        return True

    def _update_feed_unread_count_ui(self, *a, **k):
        pass

    def _announce_event(self, *a, **k):
        pass

    def _announce(self, *a, **k):
        pass

    def on_view_article_history(self, article):
        self.history_calls.append(article)

    def _article_description_text(self, article, **k):
        self.desc_calls.append(article)
        return "This is the feed description."


@pytest.fixture(scope="module")
def wxapp():
    app = wx.App(False)
    yield app
    try:
        app.Destroy()
    except Exception:
        pass


def _make(wxapp):
    mf = _StubMainFrame()
    frame = AccessibleBrowserFrame(mf)
    return mf, frame


def _destroy(mf, frame):
    try:
        frame.Destroy()
    finally:
        mf.Destroy()


def test_toggle_favorite_calls_provider_and_sets_flag(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        art = SimpleNamespace(id="a1", is_favorite=False)
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        frame.on_toggle_favorite()
        assert mf.provider.toggled == ["a1"]
        assert art.is_favorite is False  # provider._fav started True -> toggled to False
    finally:
        _destroy(mf, frame)


def test_delete_calls_provider_and_drops_local(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        art = SimpleNamespace(id="d1", is_read=False)
        frame._base_articles = [art]
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        # confirm_article_delete is False in config, so no dialog.
        frame.on_delete_selected_article()
        # Provider delete runs on a thread; give it a beat by flushing.
        import time
        for _ in range(50):
            if mf.provider.deleted:
                break
            time.sleep(0.01)
        assert mf.provider.deleted == ["d1"]
        assert all(getattr(a, "id", None) != "d1" for a in frame._base_articles)
    finally:
        _destroy(mf, frame)


def test_delete_respects_confirm_setting_no(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        mf.config_manager.set("confirm_article_delete", True)
        art = SimpleNamespace(id="d2", is_read=False)
        frame._base_articles = [art]
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        monkeypatch.setattr(accessibility.wx, "MessageBox", lambda *a, **k: wx.NO)
        frame.on_delete_selected_article()
        assert mf.provider.deleted == []  # user declined
    finally:
        _destroy(mf, frame)


def test_view_history_delegates_with_article(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        art = SimpleNamespace(id="h1")
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        frame.on_view_history()
        assert mf.history_calls == [art]
    finally:
        _destroy(mf, frame)


def test_feed_description_uses_mainframe_text(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        art = SimpleNamespace(id="f1")
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        shown = []
        monkeypatch.setattr(accessibility.wx, "MessageBox", lambda msg, *a, **k: shown.append(msg))
        frame.on_view_feed_description()
        assert mf.desc_calls == [art]
        assert shown and "feed description" in shown[0]
    finally:
        _destroy(mf, frame)


def test_find_in_article_selects_match(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        frame.content_ctrl.SetValue("alpha beta gamma beta delta")

        class _FakeDlg:
            def __init__(self, *a, **k):
                pass

            def ShowModal(self):
                return wx.ID_OK

            def GetValue(self):
                return "gamma"

            def Destroy(self):
                pass

        monkeypatch.setattr(accessibility.wx, "TextEntryDialog", _FakeDlg)
        frame.content_ctrl.SetInsertionPoint(0)
        frame.on_find_in_article()
        start, end = frame.content_ctrl.GetSelection()
        assert frame.content_ctrl.GetValue()[start:end] == "gamma"
    finally:
        _destroy(mf, frame)


def test_context_menu_builds_without_error(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        art = SimpleNamespace(id="c1", is_favorite=True, url="https://e.com")
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        # Don't actually pop the native menu in a headless test.
        monkeypatch.setattr(frame.article_list, "PopupMenu", lambda menu: None)
        frame.on_article_context_menu(None)
    finally:
        _destroy(mf, frame)
