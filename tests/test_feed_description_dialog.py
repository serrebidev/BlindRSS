# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Feed Description dialog behavior (issue #30 follow-up).

The dialog opened by "View Feed Description..." must close on Escape, not
just via the Close button -- a screen-reader user expects Escape to dismiss
any modal dialog. These tests construct the real dialog headlessly (like
tests/test_a11y_dialogs.py) and dispatch a real wx EVT_CHAR_HOOK key event
through wx's own event-processing machinery, rather than calling the bound
handler function directly, so the test fails if the handler is ever
unbound or the event type changes.

ShowModal()/EndModal() require an active native modal loop that pytest
cannot provide, so they are monkeypatched per-test: the fake ShowModal
dispatches the key event then returns immediately, and the fake EndModal
just records what it was called with.
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

wx = pytest.importorskip("wx")

import gui.mainframe as mainframe  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    """A module-scoped wx.App, skipping the whole module if it can't start."""
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app


class _DescriptionHost(wx.Frame):
    """Minimal stand-in for MainFrame: real wx.Frame (it is used as the
    dialog's parent) plus the one real bound method under test."""

    on_view_feed_description = mainframe.MainFrame.on_view_feed_description

    def __init__(self):
        super().__init__(None)
        self.current_articles = [SimpleNamespace(title="Episode 1")]
        self.selected_idx = 0

    def _get_selected_article_index(self):
        return self.selected_idx

    def _article_description_text(self, article):
        return "Some description text."

    def _copy_to_clipboard(self, text):
        pass


@pytest.fixture
def host(wx_app):
    frame = _DescriptionHost()
    yield frame
    try:
        frame.Destroy()
    except Exception:
        pass


def _show_modal_sending_key(keycode):
    """Build a fake ShowModal that dispatches one EVT_CHAR_HOOK key press."""

    def fake_show_modal(dlg):
        evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        evt.SetKeyCode(keycode)
        evt.SetEventObject(dlg)
        dlg.ProcessWindowEvent(evt)
        return wx.ID_CLOSE

    return fake_show_modal


def test_escape_closes_feed_description_dialog(host, monkeypatch):
    end_modal_calls = []
    monkeypatch.setattr(wx.Dialog, "EndModal", lambda self, retCode: end_modal_calls.append(retCode))
    monkeypatch.setattr(wx.Dialog, "ShowModal", _show_modal_sending_key(wx.WXK_ESCAPE))

    host.on_view_feed_description(idx=0)

    assert end_modal_calls == [wx.ID_CLOSE]


def test_other_keys_do_not_close_feed_description_dialog(host, monkeypatch):
    end_modal_calls = []
    monkeypatch.setattr(wx.Dialog, "EndModal", lambda self, retCode: end_modal_calls.append(retCode))
    monkeypatch.setattr(wx.Dialog, "ShowModal", _show_modal_sending_key(ord("A")))

    host.on_view_feed_description(idx=0)

    assert end_modal_calls == []
