# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""NVDA's read-status-bar command must get the whole status text.

wx's default status-bar style ellipsizes: wxMSW stores "Playing: Title gr..."
in the native control, so NVDA never heard the playback time.
"""

import os
import sys
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import wx

import gui.mainframe as mainframe
from gui.widgets import STATUS_BAR_STYLE

LONG = "Playing: 1:23 / 45:00 (43:37 left) — " + "Freedom's Daughters: Journalist Celeste Headlee profiles her grandmother " * 3


def test_status_bar_style_never_ellipsizes():
    ellipsize = wx.STB_ELLIPSIZE_START | wx.STB_ELLIPSIZE_MIDDLE | wx.STB_ELLIPSIZE_END
    assert STATUS_BAR_STYLE & ellipsize == 0


@pytest.mark.skipif(sys.platform != "win32", reason="reads the native Win32 status bar")
def test_native_status_bar_keeps_full_text():
    import ctypes
    from ctypes import wintypes

    send = ctypes.windll.user32.SendMessageW
    send.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    send.restype = ctypes.c_ssize_t
    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None, size=(600, 300))
    try:
        frame.CreateStatusBar(3, style=STATUS_BAR_STYLE)
        frame.SetStatusWidths([-2, -1, -1])
        frame.Show()
        wx.SafeYield()
        frame.SetStatusText(LONG, 2)
        wx.SafeYield()
        hwnd = frame.GetStatusBar().GetHandle()
        n = send(hwnd, 0x40C, 2, 0) & 0xFFFF  # SB_GETTEXTLENGTHW
        buf = ctypes.create_unicode_buffer(n + 1)
        send(hwnd, 0x40D, 2, ctypes.addressof(buf))  # SB_GETTEXTW
        assert buf.value == LONG
    finally:
        frame.Destroy()
        wx.SafeYield()
    del app


def test_playback_status_puts_time_before_title():
    seen = {}
    fake = SimpleNamespace(
        _playback_status_field=2,
        _update_live_media_annotation=lambda info: None,
        _format_media_time=mainframe.MainFrame._format_media_time,
        SetStatusText=lambda text, field: seen.__setitem__(field, text),
    )
    info = {"has_media": True, "title": "A very long title", "playing": True,
            "position_ms": 83_000, "duration_ms": 2_700_000}
    mainframe.MainFrame._on_player_progress(fake, info)
    text = seen[2]
    assert text.startswith("Playing: 1:23")
    assert "left)" in text and text.endswith("A very long title")
