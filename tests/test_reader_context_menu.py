# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Reader context menu key handling (issue #73).

The reader is a TE_RICH2 control, and on MSW the native rich-edit raises its own
English menu straight from the Win32 layer without wx ever delivering
EVT_CONTEXT_MENU. That is why v1.107.0's handler, which was correct, never ran.
The menu is therefore driven from EVT_KEY_DOWN / EVT_RIGHT_UP instead, and those
handlers must NOT Skip() -- skipping is what lets the native menu back in.
"""

from types import SimpleNamespace

import wx

from gui import mainframe


class _KeyEvent:
    def __init__(self, code, shift=False, ctrl=False, alt=False):
        self._code = code
        self._shift = shift
        self._ctrl = ctrl
        self._alt = alt
        self.skipped = False

    def GetKeyCode(self):
        return self._code

    def ShiftDown(self):
        return self._shift

    def ControlDown(self):
        return self._ctrl

    def AltDown(self):
        return self._alt

    def Skip(self):
        self.skipped = True


def _host():
    shown = []
    host = SimpleNamespace(
        _is_context_menu_key=mainframe.MainFrame._is_context_menu_key,
        _show_content_context_menu=lambda: shown.append("shown"),
    )
    host.shown = shown
    return host


def test_shift_f10_shows_our_menu_and_does_not_skip():
    host = _host()
    event = _KeyEvent(wx.WXK_F10, shift=True)

    mainframe.MainFrame.on_content_key_down(host, event)

    assert host.shown == ["shown"]
    # Skipping here would hand the key to the native rich-edit, which is the
    # whole bug: the English menu would appear on top of ours.
    assert event.skipped is False


def test_menu_key_shows_our_menu_and_does_not_skip():
    host = _host()
    event = _KeyEvent(wx.WXK_WINDOWS_MENU)

    mainframe.MainFrame.on_content_key_down(host, event)

    assert host.shown == ["shown"]
    assert event.skipped is False


def test_right_click_shows_our_menu():
    host = _host()

    mainframe.MainFrame.on_content_right_up(host, _KeyEvent(0))

    assert host.shown == ["shown"]


def test_plain_f10_is_left_alone():
    """Bare F10 is the menu-bar key, not a context menu request."""
    host = _host()
    event = _KeyEvent(wx.WXK_F10)

    mainframe.MainFrame.on_content_key_down(host, event)

    assert host.shown == []
    assert event.skipped is True


def test_modified_shift_f10_is_left_alone():
    for kwargs in ({"ctrl": True}, {"alt": True}):
        host = _host()
        event = _KeyEvent(wx.WXK_F10, shift=True, **kwargs)

        mainframe.MainFrame.on_content_key_down(host, event)

        assert host.shown == []
        assert event.skipped is True


def test_ordinary_keys_are_skipped_so_reading_keys_still_work():
    host = _host()
    event = _KeyEvent(ord("A"))

    mainframe.MainFrame.on_content_key_down(host, event)

    assert host.shown == []
    assert event.skipped is True
