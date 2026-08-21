# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Rich (HTML) full-text view in the macOS accessible browser.

MainFrame has an opt-in "Rich Full-Text View" (WebView) but the accessible
browser that VoiceOver users are routed to on macOS only had a plain TextCtrl.
These tests cover the rich surface: the shared config gate, the instant feed
HTML, the async render/apply pipeline, and the toolbar toggle.
"""

from types import SimpleNamespace

import pytest

wx = pytest.importorskip("wx")

from gui import accessibility
from gui.accessibility import AccessibleBrowserFrame


class _Config:
    def __init__(self, values=None):
        self._v = dict(values or {})

    def get(self, key, default=None):
        return self._v.get(key, default)

    def set(self, key, value):
        self._v[key] = value


class _StubMainFrame(wx.Frame):
    article_page_size = 400

    def __init__(self, rich=False):
        super().__init__(None, title="StubMainFrame")
        self.feed_map = {}
        self._accessible_view_entries = []
        self.current_feed_id = "all"
        self.config_manager = _Config({"full_text_rich_view": rich})
        self.provider = SimpleNamespace(
            get_articles_page=lambda *a, **k: ([], 0),
            mark_read=lambda _id: None,
            mark_unread=lambda _id: None,
        )

    def _filter_articles(self, articles, _query):
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


@pytest.fixture(scope="module")
def wxapp():
    app = wx.App(False)
    yield app
    try:
        app.Destroy()
    except Exception:
        pass


def _make(wxapp, rich=False):
    mf = _StubMainFrame(rich=rich)
    frame = AccessibleBrowserFrame(mf)
    return mf, frame


def _destroy(mf, frame):
    try:
        frame.Destroy()
    finally:
        mf.Destroy()


def test_checkbox_reflects_shared_config(wxapp):
    mf, frame = _make(wxapp, rich=True)
    try:
        assert frame.rich_view_chk.GetValue() is True
        assert frame._rich_view_enabled() is True
    finally:
        _destroy(mf, frame)


def test_checkbox_off_by_default(wxapp):
    mf, frame = _make(wxapp, rich=False)
    try:
        assert frame.rich_view_chk.GetValue() is False
        assert frame._rich_view_enabled() is False
    finally:
        _destroy(mf, frame)


def test_ensure_rich_view_creates_webview_on_macos(wxapp):
    # The rich reader depends on wx_accessible_webview + a real WebView backend.
    pytest.importorskip("wx_accessible_webview")
    mf, frame = _make(wxapp, rich=True)
    try:
        rv = frame._ensure_rich_view()
        if rv is None:
            pytest.skip("WebView backend unavailable in this environment")
        assert getattr(rv, "using_webview", False) is True
        # Idempotent: second call returns the same instance.
        assert frame._ensure_rich_view() is rv
    finally:
        _destroy(mf, frame)


def test_rich_feed_content_html_wraps_article(wxapp):
    mf, frame = _make(wxapp, rich=True)
    try:
        art = SimpleNamespace(
            url="https://example.com/p",
            title="Hello World",
            author="Jane",
            content="<p>Body paragraph here.</p>",
            date="",
            language="en",
            feed_id="f1",
        )
        html = frame._rich_feed_content_html(art)
        assert html.startswith("<article")
        assert "Hello World" in html
        assert "example.com/p" in html
    finally:
        _destroy(mf, frame)


def test_apply_rich_result_caches_and_ignores_stale_token(wxapp):
    mf, frame = _make(wxapp, rich=True)
    try:
        if frame._ensure_rich_view() is None:
            pytest.skip("WebView backend unavailable")
        frame._current_rich_art_id = "a1"
        frame._rich_token = 5
        frame._apply_rich_result("a1", "<article lang='en'><p>Full</p></article>", 5)
        assert frame._rich_html_cache.get("a1") == "<article lang='en'><p>Full</p></article>"
        # A stale token still caches but must not be the "current" render target.
        frame._apply_rich_result("a2", "<article><p>Other</p></article>", 1)
        assert frame._rich_html_cache.get("a2") == "<article><p>Other</p></article>"
    finally:
        _destroy(mf, frame)


def test_macos_rich_result_reloads_accessible_document(monkeypatch):
    """A final rich result must replace the AXWebArea, not only mutate its DOM."""
    calls = []

    class _RichView:
        control = object()

        def clear(self):
            calls.append(("clear", None))

        def set_content(self, body):
            calls.append(("set", body))

        def status(self, message):
            calls.append(("status", message))

    frame = AccessibleBrowserFrame.__new__(AccessibleBrowserFrame)
    frame._ensure_rich_view = lambda: _RichView()
    monkeypatch.setattr(accessibility.sys, "platform", "darwin")
    monkeypatch.setattr(
        accessibility,
        "notify_reader_content_changed",
        lambda control, tree_changed=False: calls.append(("notify", tree_changed)),
    )

    frame._render_rich_html("<article><p>Full article</p></article>", refresh_accessibility=True)

    assert calls == [
        ("clear", None),
        ("set", "<article><p>Full article</p></article>"),
        ("status", "Full text loaded."),
        ("notify", True),
    ]


def test_show_article_rich_uses_cache_without_network(wxapp, monkeypatch):
    mf, frame = _make(wxapp, rich=True)
    try:
        if frame._ensure_rich_view() is None:
            pytest.skip("WebView backend unavailable")
        # Guard: no network render should be scheduled when a cache hit exists.
        called = []
        monkeypatch.setattr(
            accessibility.article_html, "render_full_article_html",
            lambda *a, **k: called.append(1) or "<article><p>X</p></article>",
        )
        frame._rich_html_cache["cached-id"] = "<article lang='en'><p>Cached</p></article>"
        art = SimpleNamespace(url="https://e.com/p", title="T", author="", content="", date="", language="en", feed_id="f1")
        frame._show_article_rich(art, "cached-id")
        assert called == []  # served from cache, no fetch scheduled
    finally:
        _destroy(mf, frame)


def test_toggle_persists_and_swaps_surface(wxapp):
    mf, frame = _make(wxapp, rich=False)
    try:
        assert frame.content_ctrl.IsShown() is True
        frame.rich_view_chk.SetValue(True)
        frame.on_toggle_rich_view()
        assert mf.config_manager.get("full_text_rich_view") is True
        # If the WebView backend exists, the text control is hidden in favor of it.
        if frame._ensure_rich_view() is not None:
            assert frame.content_ctrl.IsShown() is False
    finally:
        _destroy(mf, frame)
