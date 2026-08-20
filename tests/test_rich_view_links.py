# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Rich-view link handling: link clicks leave, iframes stay (issue #102)."""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gui import rich_view_links


class _Event:
    """Stand-in for wx.html2.WebViewEvent."""

    def __init__(self, url, *, main_frame=True, target=""):
        self._url = url
        self._main_frame = main_frame
        self._target = target
        self.vetoed = False

    def GetURL(self):
        return self._url

    def IsTargetMainFrame(self):
        return self._main_frame

    def GetTarget(self):
        return self._target

    def Veto(self):
        self.vetoed = True


class _OldEvent(_Event):
    """wxWidgets < 3.3: no IsTargetMainFrame(), only a target frame name."""

    def __getattribute__(self, name):
        if name == "IsTargetMainFrame":
            raise AttributeError(name)
        return super().__getattribute__(name)


def _run(event):
    opened = []
    rich_view_links.make_navigating_handler(opened.append)(event)
    return opened


def test_iframe_navigation_stays_in_the_webview():
    event = _Event("https://www.youtube.com/embed/abc123", main_frame=False)
    assert _run(event) == []
    assert not event.vetoed


def test_link_click_opens_in_the_system_browser():
    event = _Event("https://example.com/story")
    assert _run(event) == ["https://example.com/story"]
    assert event.vetoed


def test_initial_page_load_is_left_alone():
    event = _Event("about:blank")
    assert _run(event) == []
    assert not event.vetoed


def test_unsafe_urls_are_never_handed_to_the_os():
    for url in ("file:///C:/Windows/system32/calc.exe", "javascript:alert(1)", ""):
        event = _Event(url)
        assert _run(event) == [], url
        assert not event.vetoed


def test_old_wx_falls_back_to_the_target_name():
    assert _run(_OldEvent("https://example.com/story")) == ["https://example.com/story"]
    assert _run(_OldEvent("https://example.com/embed", target="player")) == []


def test_popups_open_externally_without_a_veto():
    opened = []
    event = _Event("https://www.youtube.com/watch?v=abc123")
    rich_view_links.make_new_window_handler(opened.append)(event)
    assert opened == ["https://www.youtube.com/watch?v=abc123"]
    assert not event.vetoed


def test_a_failing_opener_does_not_escape():
    def _boom(url):
        raise RuntimeError(f"no browser for {url}")

    event = _Event("https://example.com/story")
    rich_view_links.make_navigating_handler(_boom)(event)
    assert event.vetoed
