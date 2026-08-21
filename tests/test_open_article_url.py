# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""File > Open Article: read any web page in the BlindRSS article reader.

Feeds only carry what a publisher syndicates, so an article that arrives as a
bare link -- or one whose own site is unreadable behind cookie banners and
infinite scroll -- had nowhere to go. These tests cover the GUI-free half
(core.open_article: which renderer runs, and what a failure returns) and the
routing in gui.mainframe. The failure cases matter most: an empty reader is
indistinguishable from a broken app to a screen-reader user, so every refusal
has to come back as readable content in the shape the chosen reader expects.
"""

import os
import sys
import time

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import article_extractor  # noqa: E402
from core import open_article  # noqa: E402
import gui.mainframe as mainframe  # noqa: E402


STORY = "https://example.com/news/a-story"
RICH_BODY = '<article lang="en"><h1>A Story</h1><p>The body.</p></article>'
PLAIN_BODY = "Title: A Story\nAuthor: Someone\n\nThe body.\n"


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if a test reaches a renderer it did not stub."""

    def _forbidden(*args, **kwargs):
        raise AssertionError("the renderer was called")

    monkeypatch.setattr(open_article.article_html, "render_full_article_html", _forbidden)
    monkeypatch.setattr(open_article.article_extractor, "render_full_article", _forbidden)


def _stub(monkeypatch, *, rich_result=None, plain_result=None):
    calls = {}

    def _rich(url, **kwargs):
        calls["rich"] = (url, kwargs)
        if isinstance(rich_result, Exception):
            raise rich_result
        return rich_result

    def _plain(url, **kwargs):
        calls["plain"] = (url, kwargs)
        if isinstance(plain_result, Exception):
            raise plain_result
        return plain_result

    monkeypatch.setattr(open_article.article_html, "render_full_article_html", _rich)
    monkeypatch.setattr(open_article.article_extractor, "render_full_article", _plain)
    return calls


# --- core.open_article -----------------------------------------------------


def test_a_pasted_address_is_cleaned_the_same_way_media_urls_are():
    assert open_article.normalize_article_url("  <" + STORY + ">  ") == STORY
    assert open_article.normalize_article_url("www.example.com/story") == (
        "https://www.example.com/story"
    )
    assert open_article.normalize_article_url("how to bake bread") == ""
    assert open_article.normalize_article_url("mailto:someone@example.com") == ""


def test_the_html_view_renders_the_page_as_html(monkeypatch):
    calls = _stub(monkeypatch, rich_result=RICH_BODY)

    result = open_article.load_article(STORY, rich=True)

    assert calls["rich"][0] == STORY
    assert "plain" not in calls
    assert (result.ok, result.rich, result.content) == (True, True, RICH_BODY)
    # The window's caption comes from the heading the renderer wrote.
    assert result.title == "A Story"


def test_full_text_mode_renders_the_page_as_text(monkeypatch):
    calls = _stub(monkeypatch, plain_result=PLAIN_BODY)

    result = open_article.load_article(STORY, rich=False)

    assert calls["plain"][0] == STORY
    assert "rich" not in calls
    assert (result.ok, result.rich, result.content) == (True, False, PLAIN_BODY)
    assert result.title == "A Story"


def test_full_text_mode_does_not_prefer_feed_content(monkeypatch):
    # There is no feed item behind this URL, so the feed-content shortcut has
    # nothing to offer and would only skip the fetch that is the whole point.
    calls = _stub(monkeypatch, plain_result=PLAIN_BODY)

    open_article.load_article(STORY, rich=False)

    assert calls["plain"][1]["prefer_feed_content"] is False


def test_a_page_with_no_title_still_loads(monkeypatch):
    _stub(monkeypatch, plain_result="Title: (unknown)\nAuthor: (unknown)\n\nBody.\n")

    result = open_article.load_article(STORY, rich=False)

    # "(unknown)" is the renderer's placeholder, not a title to show in the
    # window caption; the caller falls back to the address.
    assert result.ok is True
    assert result.title == ""


def test_a_non_url_is_refused_before_anything_is_fetched(no_network):
    result = open_article.load_article("how to bake bread", rich=False)

    assert result.ok is False
    assert "web address" in result.content


def test_a_blocked_page_keeps_the_extractors_own_explanation(monkeypatch):
    _stub(
        monkeypatch,
        plain_result=article_extractor.ExtractionError(
            "This site is showing a bot check instead of the article."
        ),
    )

    result = open_article.load_article(STORY, rich=False)

    assert result.ok is False
    # The extractor's guidance is what tells the user what to do about it;
    # replacing it with a generic message throws that away.
    assert "bot check" in result.content
    assert STORY in result.content


def test_a_failure_never_leaves_the_reader_empty(monkeypatch):
    _stub(monkeypatch, plain_result=None, rich_result=None)

    plain = open_article.load_article(STORY, rich=False)
    rich = open_article.load_article(STORY, rich=True)

    assert plain.ok is False and plain.content.strip()
    assert rich.ok is False and rich.content.strip()
    # Each failure has to arrive in the shape its reader can display.
    assert "<" not in plain.content
    assert rich.content.startswith("<article>") and "<h1>" in rich.content


def test_an_endless_error_message_cannot_become_the_whole_window(monkeypatch):
    _stub(monkeypatch, plain_result=RuntimeError("x" * 5000))

    result = open_article.load_article(STORY, rich=False)

    assert len(result.content) < 1000
    assert result.content.rstrip().endswith(
        "Tools > Import Site Cookies if it is behind a check."
    )


# --- gui.mainframe routing -------------------------------------------------


class _FakeWindow:
    instances = []

    def __init__(self, parent, url, rich=False, translate=None):
        self.parent = parent
        self.url = url
        self.rich = rich
        self.translate = translate
        _FakeWindow.instances.append(self)


class _Host:
    """The Open Article surface of MainFrame, without wx."""

    open_article_url = mainframe.MainFrame.open_article_url

    def _translate_rendered_text_if_enabled(self, rendered):
        return rendered


@pytest.fixture
def fake_window(monkeypatch):
    import gui.article_window as article_window

    _FakeWindow.instances = []
    monkeypatch.setattr(article_window, "ArticleWindow", _FakeWindow)
    return _FakeWindow


def test_open_article_url_opens_one_window_per_page(fake_window):
    host = _Host()

    window = host.open_article_url("  " + STORY + "  ", rich=True)

    assert window is fake_window.instances[0]
    assert (window.url, window.rich) == (STORY, True)
    assert window.parent is host


def test_open_article_url_passes_the_translator_through(fake_window):
    host = _Host()

    window = host.open_article_url(STORY)

    # Translation is a reading setting, so an opened page honors it the same
    # way an article from a feed does.
    assert window.translate("some text") == "some text"
    assert window.rich is False


def test_open_article_url_refuses_a_non_url_without_opening_a_window(fake_window):
    host = _Host()

    assert host.open_article_url("how to bake bread") is None
    assert fake_window.instances == []


def test_the_command_is_in_the_shortcut_registry():
    from core import shortcuts

    # Every menu command is bindable from Tools > Keyboard Shortcuts; one that
    # is missing from the registry cannot be given a key at all.
    assert any(c.id == "article.open_url" for c in shortcuts.COMMANDS)
    assert "article.open_url" in shortcuts.default_bindings()


# --- gui.article_window ----------------------------------------------------

wx = pytest.importorskip("wx")


@pytest.fixture(scope="module")
def wx_app():
    """A module-scoped wx.App, skipping these tests if it cannot start."""
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app


@pytest.fixture
def parent(wx_app):
    frame = wx.Frame(None)
    yield frame
    try:
        frame.Destroy()
    except Exception:
        pass


def _loaded(*, ok=True, title="A Story", content=PLAIN_BODY, rich=False):
    return open_article.LoadedArticle(
        url=STORY, rich=rich, ok=ok, title=title, content=content
    )


@pytest.fixture
def canned(monkeypatch):
    """Replace the loader with an instant one that counts its calls."""
    import gui.article_window as article_window

    state = {"calls": 0, "result": _loaded()}

    def _load(url, rich=True, timeout=None):
        state["calls"] += 1
        return state["result"]

    monkeypatch.setattr(article_window.open_article, "load_article", _load)
    return state


def _pump(predicate):
    """Drain wx's pending-event queue until *predicate* holds (or we give up).

    ``ProcessPendingEvents``, not ``wx.Yield``: the loader hands its result
    back with ``wx.CallAfter``, and a nested event loop on Windows makes COM
    complain (RPC_E_CANTCALLOUT_ININPUTSYNCCALL) about the focus and
    accessibility calls the reader makes while it renders.
    """
    app = wx.GetApp()
    for _ in range(400):
        if predicate():
            return True
        app.ProcessPendingEvents()
        time.sleep(0.005)
    return predicate()


def _open(parent, canned, **kwargs):
    """Open the window and wait for the (instant) load to land."""
    import gui.article_window as article_window

    window = article_window.ArticleWindow(parent, STORY, **kwargs)
    _pump(lambda: bool(window._loaded))
    return window


def test_the_article_window_shows_what_the_loader_returned(parent, canned):
    window = _open(parent, canned)
    try:
        assert window.content_ctrl.GetValue().startswith("Title: A Story")
        # The caption names the article, not the address: it is what a screen
        # reader reads when the window takes focus.
        assert window.GetTitle() == "A Story"
        assert window.GetStatusBar().GetStatusText() == "Article loaded."
    finally:
        window.Destroy()


def test_an_untitled_page_falls_back_to_its_address(parent, canned):
    canned["result"] = _loaded(title="")
    window = _open(parent, canned)
    try:
        assert window.GetTitle() == STORY
    finally:
        window.Destroy()


def test_a_failed_load_still_puts_words_in_the_reader(parent, canned):
    canned["result"] = _loaded(
        ok=False, title="", content=open_article.failure_text(STORY, "Blocked.")
    )
    window = _open(parent, canned)
    try:
        # An empty reader is indistinguishable from a broken app.
        assert "could not be read" in window.content_ctrl.GetValue()
        assert window.GetStatusBar().GetStatusText() == "This page could not be read."
    finally:
        window.Destroy()


def test_the_finished_load_is_announced(parent, canned):
    heard = []
    parent._announce_event = lambda event_id, message: heard.append((event_id, message))

    window = _open(parent, canned)
    try:
        # Nothing moves when the text is swapped in under the reader, so a
        # screen reader gives no cue of its own; without this there is no way
        # to tell "still loading" from "arrived".
        assert heard == [("general", "Article loaded.")]
    finally:
        window.Destroy()


def test_a_failure_is_announced_as_a_failure(parent, canned):
    heard = []
    parent._announce_event = lambda event_id, message: heard.append(message)
    canned["result"] = _loaded(ok=False, content="nope")

    window = _open(parent, canned)
    try:
        assert heard == ["This page could not be read."]
    finally:
        window.Destroy()


def test_switching_back_to_a_loaded_reader_does_not_fetch_again(parent, canned):
    window = _open(parent, canned)
    try:
        assert canned["calls"] == 1
        window.start_load()
        assert canned["calls"] == 1
    finally:
        window.Destroy()


def test_reload_fetches_the_page_again(parent, canned):
    window = _open(parent, canned)
    try:
        window.on_reload()
        _pump(lambda: canned["calls"] > 1)
        assert canned["calls"] == 2
    finally:
        window.Destroy()
