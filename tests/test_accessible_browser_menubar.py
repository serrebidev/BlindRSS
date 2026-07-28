# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Menu bar + article actions on the macOS accessible browser.

The accessible window had no menu bar, so VoiceOver users could not reach
Settings, the player dialogs, or app-level tools. These tests verify the menu
bar exists and that its items delegate to the shared MainFrame handlers (and
that article-scoped items act on THIS window's selected article).
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


class _StubMainFrame(wx.Frame):
    article_page_size = 400

    def __init__(self):
        super().__init__(None, title="StubMainFrame")
        self.feed_map = {}
        self._accessible_view_entries = []
        self.current_feed_id = "all"
        self.config_manager = _Config({"full_text_rich_view": False})
        self.calls = []
        self.provider = SimpleNamespace(
            get_articles_page=lambda *a, **k: ([], 0),
            mark_read=lambda _id: None,
            mark_unread=lambda _id: None,
        )

    # recorders for delegated handlers
    def _rec(self, name):
        def _f(*a, **k):
            self.calls.append((name, a))
        return _f

    def __getattr__(self, name):
        # Any on_* handler the menu delegates to is recorded. (Called only for
        # attributes not found normally, so real methods below still win.)
        if name.startswith("on_") or name == "toggle_player_visibility":
            return self._rec(name)
        raise AttributeError(name)

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

    def _confirm_and_mark_all_read(self, view_id, prompt):
        self.calls.append(("_confirm_and_mark_all_read", (view_id, prompt)))


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


def _menu_titles(mb):
    return [mb.GetMenuLabelText(i) for i in range(mb.GetMenuCount())]


def test_menu_bar_exists_with_expected_menus(wxapp):
    mf, frame = _make(wxapp)
    try:
        mb = frame.GetMenuBar()
        assert mb is not None
        titles = _menu_titles(mb)
        for want in ("File", "Article", "Player", "Tools", "Help"):
            assert want in titles
    finally:
        _destroy(mf, frame)


def test_delegate_calls_mainframe_handler(wxapp):
    mf, frame = _make(wxapp)
    try:
        frame._delegate("on_settings")
        frame._delegate("on_open_equalizer")
        frame._delegate("toggle_player_visibility")
        names = [c[0] for c in mf.calls]
        assert "on_settings" in names
        assert "on_open_equalizer" in names
        assert "toggle_player_visibility" in names
    finally:
        _destroy(mf, frame)


def test_delegate_missing_handler_is_safe(wxapp):
    mf, frame = _make(wxapp)
    try:
        # No exception even if the method truly doesn't exist.
        frame._delegate("definitely_not_a_real_handler_zzz")
    finally:
        _destroy(mf, frame)


def test_copy_link_uses_selected_article(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        art = SimpleNamespace(url="https://example.com/story", media_url="https://cdn/x.mp3", content="<p>hi</p>")
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        copied = []
        monkeypatch.setattr(accessibility, "copy_text_to_clipboard", lambda t: copied.append(t) or True)
        frame.on_menu_copy_link(None)
        frame.on_menu_copy_media_link(None)
        assert "https://example.com/story" in copied
        assert "https://cdn/x.mp3" in copied
    finally:
        _destroy(mf, frame)


def test_detect_audio_delegates_with_article(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        art = SimpleNamespace(url="https://e.com/p")
        monkeypatch.setattr(frame, "_selected_article", lambda: (0, art))
        frame.on_menu_detect_audio(None)
        assert ("on_detect_audio", (art,)) in mf.calls
    finally:
        _destroy(mf, frame)


def test_mark_view_read_uses_current_view_id(wxapp):
    mf, frame = _make(wxapp)
    try:
        frame.current_view_id = "feed-123"
        frame.on_menu_mark_view_read(None)
        assert any(c[0] == "_confirm_and_mark_all_read" and c[1][0] == "feed-123" for c in mf.calls)
    finally:
        _destroy(mf, frame)
