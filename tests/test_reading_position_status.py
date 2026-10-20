# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The status bar shows the reading position only while the reader has focus."""

import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import wx

import gui.mainframe as mainframe

MF = mainframe.MainFrame


def _fake(seen):
    fake = SimpleNamespace(
        _reading_status_field=3,
        SetStatusText=lambda text, field: seen.__setitem__(field, text),
    )
    fake._set_reading_status = lambda text: MF._set_reading_status(fake, text)
    return fake


def test_classic_reader_reports_line_of_total_and_clears_on_leave(monkeypatch):
    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None, size=(600, 300))
    try:
        ctrl = wx.TextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        ctrl.SetValue("\n".join(f"line {n}" for n in range(1, 11)))
        ctrl.SetInsertionPoint(ctrl.XYToPosition(0, 2))
        seen = {}
        fake = _fake(seen)
        fake.content_ctrl = ctrl

        monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: ctrl))
        MF._update_reading_position(fake)
        assert seen[3] == "Line 3 of 10"

        # Not focused: never write a position for a reader the user left.
        seen.clear()
        monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
        MF._update_reading_position(fake)
        assert seen == {}

        event = SimpleNamespace(Skip=lambda: None)
        MF._on_content_kill_focus(fake, event)
        assert seen[3] == ""
    finally:
        frame.Destroy()
    del app


def test_rich_reader_reports_scroll_percent_and_clears_on_blur():
    seen = {}
    fake = _fake(seen)
    MF._on_rich_view_message(fake, {"type": "__reading_pos", "percent": 35})
    assert seen[3] == "35% read"
    # An article that fits without scrolling has no position to report.
    MF._on_rich_view_message(fake, {"type": "__reading_pos", "percent": -1})
    assert seen[3] == ""
    MF._on_rich_view_message(fake, {"type": "__reading_pos", "percent": 80})
    MF._on_rich_view_message(fake, {"type": "__reader_blur"})
    assert seen[3] == ""
