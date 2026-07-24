# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


# Reference string used by the pure-logic tests.  Two occurrences of "hello":
#   index 0-5  ("hello") and index 12-17 ("hello").
TEXT = "hello world hello"


class _DummyKeyEvent:
    def __init__(self, key, *, ctrl=False, shift=False, alt=False, meta=False):
        self._key = int(key)
        self._ctrl = bool(ctrl)
        self._shift = bool(shift)
        self._alt = bool(alt)
        self._meta = bool(meta)
        self.skipped = False

    def GetKeyCode(self):
        return int(self._key)

    def ControlDown(self):
        return bool(self._ctrl)

    def ShiftDown(self):
        return bool(self._shift)

    def AltDown(self):
        return bool(self._alt)

    def MetaDown(self):
        return bool(self._meta)

    def Skip(self):
        self.skipped = True


class _FindRoutingHost:
    """Minimal host that borrows on_char_hook (and its backspace helpers) from
    MainFrame so we can exercise the find-in-article key routing without a real
    wx frame.  on_find_* are stubs that just record the call."""

    on_char_hook = mainframe.MainFrame.on_char_hook
    _is_backspace_key = mainframe.MainFrame._is_backspace_key
    _is_plain_backspace_event = mainframe.MainFrame._is_plain_backspace_event
    _is_editable_text_input_focused = mainframe.MainFrame._is_editable_text_input_focused

    def __init__(self):
        self.content_ctrl = object()
        self.list_ctrl = object()
        self.tree = object()
        self.player_window = None
        self._media_hotkeys = None
        self.calls = []
        self._focus = self.content_ctrl

    def _get_focused_window(self):
        return self._focus

    def on_find_in_article(self, event=None):
        self.calls.append("on_find_in_article")

    def on_find_next_in_article(self, event=None):
        self.calls.append("on_find_next_in_article")

    def on_find_prev_in_article(self, event=None):
        self.calls.append("on_find_prev_in_article")


# ---------------------------------------------------------------------------
# A) Pure-logic tests for MainFrame._find_in_text
# ---------------------------------------------------------------------------

def test_forward_find_from_zero_is_case_insensitive():
    # "Hello" (capitalized) matches the lowercase text at the first occurrence.
    assert mainframe.MainFrame._find_in_text(TEXT, "Hello", 0) == (0, 5)


def test_forward_find_after_first_match_returns_second():
    # Starting just after the end of the first match yields the SECOND match.
    assert mainframe.MainFrame._find_in_text(TEXT, "hello", 5) == (12, 17)


def test_forward_find_wraps_to_first():
    # Starting past the last match wraps around to the first occurrence.
    assert mainframe.MainFrame._find_in_text(
        TEXT, "hello", len(TEXT), forward=True, wrap=True
    ) == (0, 5)


def test_backward_find_returns_previous_match():
    # From the start of the second match, searching backward finds the first.
    assert mainframe.MainFrame._find_in_text(
        TEXT, "hello", 12, forward=False
    ) == (0, 5)


def test_backward_find_wraps_to_last():
    # Starting before the first match wraps around to the last occurrence.
    assert mainframe.MainFrame._find_in_text(
        TEXT, "hello", 0, forward=False, wrap=True
    ) == (12, 17)


def test_forward_find_does_not_wrap_when_disabled():
    # F3 uses wrap=False: past the last match there is no result (no jump back
    # to the top of the article).
    assert mainframe.MainFrame._find_in_text(
        TEXT, "hello", len(TEXT), forward=True, wrap=False
    ) is None


def test_backward_find_does_not_wrap_when_disabled():
    # Shift+F3 uses wrap=False: before the first match there is no result.
    assert mainframe.MainFrame._find_in_text(
        TEXT, "hello", 0, forward=False, wrap=False
    ) is None


def test_absent_term_returns_none():
    assert mainframe.MainFrame._find_in_text(TEXT, "xyz", 0) is None


def test_empty_text_returns_none():
    assert mainframe.MainFrame._find_in_text("", "hello", 0) is None


def test_empty_term_returns_none():
    assert mainframe.MainFrame._find_in_text("hello", "", 0) is None


# ---------------------------------------------------------------------------
# B) Routing tests for on_char_hook (find keys are gated on content_ctrl focus)
# ---------------------------------------------------------------------------

def test_ctrl_f_opens_find_when_content_focused():
    host = _FindRoutingHost()
    host._focus = host.content_ctrl
    evt = _DummyKeyEvent(ord("F"), ctrl=True)

    host.on_char_hook(evt)

    assert host.calls == ["on_find_in_article"]
    assert evt.skipped is False


def test_f3_finds_next_when_content_focused():
    host = _FindRoutingHost()
    host._focus = host.content_ctrl
    evt = _DummyKeyEvent(mainframe.wx.WXK_F3)

    host.on_char_hook(evt)

    assert host.calls == ["on_find_next_in_article"]
    assert evt.skipped is False


def test_shift_f3_finds_prev_when_content_focused():
    host = _FindRoutingHost()
    host._focus = host.content_ctrl
    evt = _DummyKeyEvent(mainframe.wx.WXK_F3, shift=True)

    host.on_char_hook(evt)

    assert host.calls == ["on_find_prev_in_article"]
    assert evt.skipped is False


def test_ctrl_f_ignored_when_content_not_focused():
    host = _FindRoutingHost()
    host._focus = object()  # anything other than content_ctrl
    evt = _DummyKeyEvent(ord("F"), ctrl=True)

    host.on_char_hook(evt)

    assert "on_find_in_article" not in host.calls
    assert evt.skipped is True


# ---------------------------------------------------------------------------
# C) Find-failure feedback announces to the screen reader (no modal dialog)
# ---------------------------------------------------------------------------

class _AnnounceHost:
    """Borrows the real find-failure feedback methods plus _announce so we can
    verify they announce instead of popping a modal wx.MessageBox."""

    _content_find_not_found = mainframe.MainFrame._content_find_not_found
    _content_find_no_more = mainframe.MainFrame._content_find_no_more
    _announce = mainframe.MainFrame._announce

    def __init__(self):
        self.announced = []
        self.status = []
        self.uia = []

    # Stand-ins for the wx frame surface _announce touches.
    def SetStatusText(self, text, field=0):
        self.status.append((text, field))

    def _announce_via_uia(self, message):
        # Pretend the UIA notification succeeded so _announce does not ring the
        # fallback bell; record what would have been spoken.
        self.uia.append(message)
        return True


def test_not_found_announces_without_dialog(monkeypatch):
    calls = []
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(mainframe.sys, "platform", "win32")
    monkeypatch.setattr(mainframe.screen_reader_announce, "speak_status", lambda *a, **k: False)

    host = _AnnounceHost()
    host._content_find_not_found("hello")

    assert host.uia == ['"hello" was not found.']
    assert calls == []  # no modal dialog


def test_no_more_occurrences_announces_direction(monkeypatch):
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dialog shown")))
    monkeypatch.setattr(mainframe.sys, "platform", "win32")
    monkeypatch.setattr(mainframe.screen_reader_announce, "speak_status", lambda *a, **k: False)

    host = _AnnounceHost()
    host._content_find_no_more("hello", forward=True)
    host._content_find_no_more("hello", forward=False)

    assert host.uia == [
        'No more occurrences of "hello".',
        'No previous occurrences of "hello".',
    ]


def test_announce_falls_back_to_bell_off_windows(monkeypatch):
    bells = []
    monkeypatch.setattr(mainframe.sys, "platform", "linux")
    monkeypatch.setattr(mainframe.wx, "Bell", lambda: bells.append(True))

    host = _AnnounceHost()
    host._announce("nothing here")

    # Off Windows, UIA is skipped entirely and the soft bell cues the user.
    assert host.uia == []
    assert bells == [True]
    assert host.status[-1] == ("nothing here", 0)


def test_direct_screen_reader_speech_suppresses_uia_and_bell(monkeypatch):
    bells = []
    monkeypatch.setattr(mainframe.sys, "platform", "win32")
    monkeypatch.setattr(mainframe.screen_reader_announce, "speak_status", lambda message, interrupt=True: True)
    monkeypatch.setattr(mainframe.wx, "Bell", lambda: bells.append(True))

    host = _AnnounceHost()
    host._announce("nothing here")

    assert host.uia == []
    assert bells == []
    assert host.status[-1] == ("nothing here", 0)


class _FakeWindow:
    def __init__(self, hwnd):
        self.hwnd = int(hwnd)

    def GetHandle(self):
        return self.hwnd

    def __bool__(self):
        return bool(self.hwnd)


class _AnnounceHwndHost:
    _announcement_hwnds = mainframe.MainFrame._announcement_hwnds
    _announce_status_changed = mainframe.MainFrame._announce_status_changed

    def __init__(self):
        self.focus = _FakeWindow(111)
        self.content_ctrl = _FakeWindow(222)
        self.status_bar = _FakeWindow(333)
        self.frame = _FakeWindow(444)

    def _get_focused_window(self):
        return self.focus

    def GetStatusBar(self):
        return self.status_bar

    def GetHandle(self):
        return self.frame.GetHandle()


def test_uia_notification_sources_prefer_focus_content_status_then_frame():
    host = _AnnounceHwndHost()

    assert host._announcement_hwnds() == [111, 222, 333, 444]


def test_uia_notification_sources_deduplicate_handles():
    host = _AnnounceHwndHost()
    host.focus = host.content_ctrl
    host.status_bar = _FakeWindow(222)

    assert host._announcement_hwnds() == [222, 444]


def test_announce_status_changed_emits_msaa_events(monkeypatch):
    host = _AnnounceHwndHost()
    calls = []

    class FakeAccessible:
        @staticmethod
        def NotifyEvent(event_type, window, object_type, object_id):
            calls.append((event_type, window, object_type, object_id))

    monkeypatch.setattr(mainframe.wx, "Accessible", FakeAccessible)

    host._announce_status_changed()

    assert calls == [
        (mainframe.wx.ACC_EVENT_OBJECT_VALUECHANGE, host.status_bar, mainframe.wx.OBJID_CLIENT, mainframe.wx.ACC_SELF),
        (mainframe.wx.ACC_EVENT_OBJECT_NAMECHANGE, host.status_bar, mainframe.wx.OBJID_CLIENT, mainframe.wx.ACC_SELF),
        (mainframe.wx.ACC_EVENT_SYSTEM_ALERT, host.status_bar, mainframe.wx.OBJID_CLIENT, mainframe.wx.ACC_SELF),
    ]
