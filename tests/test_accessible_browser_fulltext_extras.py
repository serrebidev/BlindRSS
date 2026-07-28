# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Peripheral full-text features in the macOS accessible browser: per-feed
encoding override (issue #75), automatic translation, and structured-metadata
enrichment — parity with the main window's reader pipeline.
"""

from types import SimpleNamespace

import pytest

from core import article_extractor
from gui.accessibility import extract_article_body


# --------------------------------------------------------------------------- #
# GUI-free extractor threading
# --------------------------------------------------------------------------- #

def test_encoding_is_threaded_to_extractor(monkeypatch):
    seen = {}

    def _capture(url, **kw):
        seen.update(kw)
        return SimpleNamespace(text="WEB BODY " * 100)

    monkeypatch.setattr(article_extractor, "extract_full_article", _capture)
    article = SimpleNamespace(url="https://example.com/p", content="<p>snip</p>", title="T", author="A")
    extract_article_body(article, encoding="windows-1251")
    assert seen.get("encoding") == "windows-1251"


def test_metadata_sink_is_threaded_to_extractor(monkeypatch):
    seen = {}

    def _capture(url, **kw):
        seen.update(kw)
        return SimpleNamespace(text="WEB BODY " * 100)

    monkeypatch.setattr(article_extractor, "extract_full_article", _capture)
    sink = lambda html, page_url: None
    article = SimpleNamespace(url="https://example.com/p", content="<p>snip</p>", title="T", author="A")
    extract_article_body(article, metadata_sink=sink)
    assert seen.get("metadata_sink") is sink


def test_no_encoding_or_sink_omits_kwargs(monkeypatch):
    # Lean test doubles that don't accept these kwargs must keep working: they are
    # only passed when set.
    seen = {}

    def _capture(url, max_pages=6, timeout=20):
        seen["called"] = True
        return SimpleNamespace(text="WEB BODY " * 100)

    monkeypatch.setattr(article_extractor, "extract_full_article", _capture)
    article = SimpleNamespace(url="https://example.com/p", content="<p>snip</p>", title="T", author="A")
    body, _ = extract_article_body(article)
    assert seen.get("called") is True
    assert body.startswith("WEB BODY")


# --------------------------------------------------------------------------- #
# Frame helpers
# --------------------------------------------------------------------------- #

wx = pytest.importorskip("wx")
from gui.accessibility import AccessibleBrowserFrame  # noqa: E402


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
        self.translated = []
        self.provider = SimpleNamespace(
            get_articles_page=lambda *a, **k: ([], 0),
            mark_read=lambda _id: None,
            mark_unread=lambda _id: None,
        )

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

    def _translate_rendered_text_if_enabled(self, rendered):
        self.translated.append(rendered)
        return "[TR] " + str(rendered)


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


def test_maybe_translate_delegates_to_mainframe(wxapp):
    mf, frame = _make(wxapp)
    try:
        assert frame._maybe_translate("hello") == "[TR] hello"
        assert mf.translated == ["hello"]
        # Empty stays empty and is not sent to the translator.
        assert frame._maybe_translate("") == ""
    finally:
        _destroy(mf, frame)


def test_feed_fulltext_encoding_reads_db(wxapp, monkeypatch):
    mf, frame = _make(wxapp)
    try:
        from core import db
        monkeypatch.setattr(db, "get_feed_settings", lambda fid: {"fulltext_encoding": "shift_jis"} if fid == "f9" else {})
        assert frame._feed_fulltext_encoding("f9") == "shift_jis"
        assert frame._feed_fulltext_encoding("other") == ""
        assert frame._feed_fulltext_encoding(None) == ""
    finally:
        _destroy(mf, frame)


def test_metadata_sink_none_without_id(wxapp):
    mf, frame = _make(wxapp)
    try:
        assert frame._metadata_sink_for(SimpleNamespace()) is None
        assert callable(frame._metadata_sink_for(SimpleNamespace(id="42")))
    finally:
        _destroy(mf, frame)
