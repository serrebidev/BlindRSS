"""Regression tests for the accessible browser Download button (issue #24)."""

from types import SimpleNamespace

import pytest

wx = pytest.importorskip("wx")

from gui.accessibility import AccessibleBrowserFrame


class _StubMainFrame(wx.Frame):
    """Minimal stand-in for MainFrame so the accessible browser can be built.

    AccessibleBrowserFrame passes its `mainframe` argument as the wx.Window
    parent, so the stub must be a real wx.Frame.
    """

    article_page_size = 400

    def __init__(self):
        super().__init__(None, title="StubMainFrame")
        self.feed_map = {}
        self._accessible_view_entries = []
        self.current_feed_id = "all"
        self.download_calls = []
        self.provider = SimpleNamespace(
            get_articles_page=lambda *args, **kwargs: ([], 0),
            mark_read=lambda _id: None,
            mark_unread=lambda _id: None,
        )

    def _filter_articles(self, articles, _query):
        return list(articles or [])

    def _sort_articles_for_display(self, articles):
        return list(articles or [])

    def _get_display_title(self, article):
        return str(getattr(article, "title", "") or "")

    def _strip_html(self, html):
        return str(html or "")

    def _article_cache_id(self, article):
        return getattr(article, "id", id(article))

    def on_download_article(self, article):
        self.download_calls.append(article)


@pytest.fixture(scope="module")
def wxapp():
    app = wx.App(False)
    yield app
    try:
        app.Destroy()
    except Exception:
        pass


def _make_browser(wxapp):
    mainframe = _StubMainFrame()
    frame = AccessibleBrowserFrame(mainframe)
    return mainframe, frame


def _destroy(mainframe, frame):
    try:
        frame.Destroy()
    finally:
        mainframe.Destroy()


def test_download_button_exists_and_starts_disabled(wxapp):
    mainframe, frame = _make_browser(wxapp)
    try:
        assert hasattr(frame, "download_btn")
        assert frame.download_btn.GetLabel() == "Download"
        # No article selected yet — button must be disabled.
        assert frame.download_btn.IsEnabled() is False
    finally:
        _destroy(mainframe, frame)


def test_download_button_enables_for_article_with_media_url(wxapp):
    mainframe, frame = _make_browser(wxapp)
    try:
        with_media = SimpleNamespace(
            id="a1", title="Pod Episode", url="https://example.com/ep1",
            content="", media_url="https://example.com/ep1.mp3",
            date="", author="", is_read=False, timestamp=0.0,
        )
        without_media = SimpleNamespace(
            id="a2", title="Article", url="https://example.com/text",
            content="", media_url=None,
            date="", author="", is_read=False, timestamp=0.0,
        )

        frame._current_articles = [with_media, without_media]
        frame.article_list.Set([
            frame._article_label(with_media),
            frame._article_label(without_media),
        ])

        frame.article_list.SetSelection(0)
        frame._show_article_at_index(0)
        assert frame.download_btn.IsEnabled() is True

        frame.article_list.SetSelection(1)
        frame._show_article_at_index(1)
        assert frame.download_btn.IsEnabled() is False
    finally:
        _destroy(mainframe, frame)


def test_download_button_routes_through_mainframe(wxapp):
    mainframe, frame = _make_browser(wxapp)
    try:
        article = SimpleNamespace(
            id="yt1", title="YouTube Video", url="https://www.youtube.com/watch?v=abc",
            content="", media_url="https://www.youtube.com/watch?v=abc",
            date="", author="", is_read=False, timestamp=0.0,
        )
        frame._current_articles = [article]
        frame.article_list.Set([frame._article_label(article)])
        frame.article_list.SetSelection(0)
        frame._show_article_at_index(0)

        frame.on_download_article(None)

        assert mainframe.download_calls == [article]
    finally:
        _destroy(mainframe, frame)


def test_download_handler_no_selection_does_not_call_mainframe(wxapp):
    mainframe, frame = _make_browser(wxapp)
    try:
        frame._current_articles = []
        frame.article_list.Set([])
        frame.on_download_article(None)
        assert mainframe.download_calls == []
    finally:
        _destroy(mainframe, frame)
