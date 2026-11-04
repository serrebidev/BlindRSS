# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Arrowing over YouTube rows must not start yt-dlp for every row passed.

Each selection-triggered YouTube full-text load launches the yt-dlp CLI, whose
release binary unpacks itself to %TEMP% before doing anything (about 3 s and
4 CPU-seconds system-wide). At the generic 350 ms debounce every row a
screen-reader user paused on to hear its title paid that and NVDA's speech cut
out; the load was then killed on the next arrow.
"""

from types import SimpleNamespace

import pytest

from gui import mainframe

YOUTUBE = "https://www.youtube.com/watch?v=abcDEF1234{}"
ARTICLE = "https://example.com/story-{}"


class _Clock:
    """wx.CallLater on a virtual clock (milliseconds)."""

    def __init__(self):
        self.now = 0
        self.pending = []

    def call_later(self, ms, fn, *args):
        timer = SimpleNamespace(due=self.now + int(ms), fn=fn, args=args, stopped=False)
        timer.Stop = lambda: setattr(timer, "stopped", True)
        self.pending.append(timer)
        return timer

    def advance(self, ms):
        end = self.now + int(ms)
        while True:
            due = [t for t in self.pending if not t.stopped and t.due <= end]
            if not due:
                break
            timer = min(due, key=lambda t: t.due)
            self.pending.remove(timer)
            self.now = timer.due
            timer.fn(*timer.args)
        self.now = end


class _Host:
    """The reader-load scheduling of MainFrame, without its window."""

    _schedule_fulltext_load_for_index = mainframe.MainFrame._schedule_fulltext_load_for_index
    _schedule_rich_load_for_index = mainframe.MainFrame._schedule_rich_load_for_index
    _fulltext_debounce_ms_for = mainframe.MainFrame._fulltext_debounce_ms_for
    _is_youtube_video_article = mainframe.MainFrame._is_youtube_video_article
    _fulltext_cache_key_for_article = mainframe.MainFrame._fulltext_cache_key_for_article

    def __init__(self, urls, rich):
        self.current_articles = [SimpleNamespace(id=f"a{i}", url=url) for i, url in enumerate(urls)]
        self.rich = rich
        self._fulltext_cache = {}
        self._fulltext_html_cache = {}
        self._fulltext_token = 0
        self._fulltext_debounce_ms = 350
        self._youtube_fulltext_debounce_ms = mainframe._YOUTUBE_FULLTEXT_DEBOUNCE_MS
        self.started = []

    def _translation_fulltext_cache_suffix(self):
        return ""

    def _start_fulltext_load(self, idx, token):
        if token == self._fulltext_token:
            self.started.append(idx)

    def _start_rich_load(self, idx, token):
        if token == self._fulltext_token:
            self.started.append(idx)

    def schedule(self, idx, force=False):
        if self.rich:
            self._schedule_rich_load_for_index(idx, force=force)
        else:
            self._schedule_fulltext_load_for_index(idx, force=force)

    def select(self, idx):
        # What on_article_select/_update_content_view do for the reader load.
        self._fulltext_token += 1
        self.schedule(idx)


class _ViewHost(_Host):
    """Adds the view switch and the Load more row of MainFrame."""

    _select_view = mainframe.MainFrame._select_view
    on_article_select = mainframe.MainFrame.on_article_select

    def __init__(self, urls, rich):
        super().__init__(urls, rich)
        self._accessible_browser = None
        self.content_ctrl = SimpleNamespace(Clear=lambda: None)
        self.view_cache = {}
        self.current_feed_id = "a"
        self._updating_list = False

    def _invalidate_reader_text_tracking(self):
        pass

    def _begin_articles_load(self, feed_id, full_load=True, clear_list=True):
        pass

    def _flush_deferred_status_cells(self, except_idx=None):
        pass

    def _is_load_more_row(self, idx):
        return idx == len(self.current_articles)


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(mainframe.wx, "CallLater", clock.call_later)
    monkeypatch.setattr(mainframe.sys, "platform", "win32")
    return clock


@pytest.mark.parametrize("rich", [False, True], ids=["classic", "rich"])
def test_arrowing_over_youtube_rows_at_reading_pace_starts_no_load(clock, rich):
    host = _Host([YOUTUBE.format(i) for i in range(6)], rich)
    # The recorded session: the user stopped about 2.6 s on each row.
    for idx in range(6):
        host.select(idx)
        clock.advance(2600)
    assert host.started == []

    # Staying on the row starts the load once.
    clock.advance(400)
    assert host.started == [5]


@pytest.mark.parametrize("rich", [False, True], ids=["classic", "rich"])
def test_reader_focus_loads_a_youtube_row_at_once(clock, rich):
    host = _Host([YOUTUBE.format(0)], rich)
    host.select(0)
    clock.advance(500)
    host.schedule(0, force=True)  # the reader gained focus
    clock.advance(0)
    assert host.started == [0]

    # The pending selection load was replaced, not added.
    clock.advance(5000)
    assert host.started == [0]


@pytest.mark.parametrize("rich", [False, True], ids=["classic", "rich"])
def test_other_articles_keep_the_short_debounce(clock, rich):
    host = _Host([ARTICLE.format(0)], rich)
    host.select(0)
    clock.advance(349)
    assert host.started == []
    clock.advance(1)
    assert host.started == [0]


@pytest.mark.parametrize("rich", [False, True], ids=["classic", "rich"])
def test_macos_keeps_the_short_debounce_for_youtube(clock, monkeypatch, rich):
    # VoiceOver never focuses the reader: selection is the only trigger there.
    monkeypatch.setattr(mainframe.sys, "platform", "darwin")
    host = _Host([YOUTUBE.format(0)], rich)
    host.select(0)
    clock.advance(349)
    assert host.started == []
    clock.advance(1)
    assert host.started == [0]


@pytest.mark.parametrize("rich", [False, True], ids=["classic", "rich"])
def test_switching_feeds_during_the_wait_starts_no_load(clock, rich):
    host = _ViewHost([YOUTUBE.format(i) for i in range(3)], rich)
    host.select(2)
    clock.advance(1500)
    host._select_view("b")
    clock.advance(5000)
    assert host.started == []


@pytest.mark.parametrize("rich", [False, True], ids=["classic", "rich"])
def test_moving_to_load_more_during_the_wait_starts_no_load(clock, monkeypatch, rich):
    monkeypatch.setattr(mainframe, "replace_text_control_value", lambda *_a: None)
    host = _ViewHost([YOUTUBE.format(i) for i in range(3)], rich)
    host.select(2)
    clock.advance(1500)
    host.on_article_select(SimpleNamespace(GetIndex=lambda: 3))  # the Load more row
    clock.advance(5000)
    assert host.started == []
