# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.clipboard_utils as clipboard_utils
import gui.mainframe as mainframe


class _FakeTextDataObject:
    def __init__(self, text=""):
        self.text = text

    def GetText(self):
        return self.text


class _FakeClipboard:
    def __init__(self, text=""):
        self.text = text
        self.opened = 0
        self.closed = 0
        self.flushed = 0
        self.set_texts = []

    def Open(self):
        self.opened += 1
        return True

    def Close(self):
        self.closed += 1

    def SetData(self, data):
        self.text = data.GetText()
        self.set_texts.append(self.text)
        return True

    def GetData(self, data):
        data.text = self.text
        return True

    def Flush(self):
        self.flushed += 1
        return True


class _FakeContentCtrl:
    def __init__(self, selection):
        self.selection = selection

    def GetStringSelection(self):
        return self.selection


class _CopyEvent:
    def __init__(self):
        self.skipped = False

    def Skip(self):
        self.skipped = True


class _Config:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _StopEvent:
    def __init__(self, calls):
        self.calls = calls

    def set(self):
        self.calls.append("stop")


def _fake_wx(fake_clipboard):
    return SimpleNamespace(
        TheClipboard=fake_clipboard,
        TextDataObject=_FakeTextDataObject,
    )


def test_textctrl_copy_uses_flushed_clipboard(monkeypatch):
    fake_clipboard = _FakeClipboard()
    monkeypatch.setattr(clipboard_utils, "wx", _fake_wx(fake_clipboard))

    ok = clipboard_utils.copy_textctrl_selection_to_clipboard(_FakeContentCtrl("copied article text"))

    assert ok is True
    assert fake_clipboard.set_texts == ["copied article text"]
    assert fake_clipboard.flushed == 1
    assert fake_clipboard.closed == 1


def test_persist_owned_text_clipboard_reflushes_existing_text(monkeypatch):
    fake_clipboard = _FakeClipboard("selected article text")
    monkeypatch.setattr(clipboard_utils, "wx", _fake_wx(fake_clipboard))
    monkeypatch.setattr(
        clipboard_utils,
        "_windows_clipboard_owner_belongs_to_current_process",
        lambda: True,
    )

    ok = clipboard_utils.persist_owned_text_clipboard()

    assert ok is True
    assert fake_clipboard.set_texts == ["selected article text"]
    assert fake_clipboard.flushed == 1
    assert fake_clipboard.closed == 1


def test_content_copy_handler_consumes_event_when_selection_was_copied(monkeypatch):
    host = SimpleNamespace(
        content_ctrl=object(),
        on_content_copy=mainframe.MainFrame.on_content_copy,
    )
    monkeypatch.setattr(mainframe, "copy_textctrl_selection_to_clipboard", lambda ctrl: ctrl is host.content_ctrl)
    event = _CopyEvent()

    host.on_content_copy(host, event)

    assert event.skipped is False


def test_content_copy_handler_skips_event_without_selection(monkeypatch):
    host = SimpleNamespace(
        content_ctrl=object(),
        on_content_copy=mainframe.MainFrame.on_content_copy,
    )
    monkeypatch.setattr(mainframe, "copy_textctrl_selection_to_clipboard", lambda ctrl: False)
    event = _CopyEvent()

    host.on_content_copy(host, event)

    assert event.skipped is True


def test_close_persists_clipboard_before_forced_exit(monkeypatch):
    calls = []

    class _Host:
        on_close = mainframe.MainFrame.on_close

        def __init__(self):
            self.config_manager = _Config({"close_to_tray": False})
            self.player_window = None
            self._media_hotkeys = None
            self._accessible_browser = None
            self.tray_icon = None
            self.stop_event = _StopEvent(calls)

        def Destroy(self):
            calls.append("destroy")

    def _persist():
        calls.append("persist")
        return True

    def _exit(code):
        calls.append(("exit", code))
        raise SystemExit(code)

    monkeypatch.setattr(mainframe, "persist_owned_text_clipboard", _persist)
    monkeypatch.setattr(mainframe.os, "_exit", _exit)

    try:
        _Host().on_close(None)
    except SystemExit:
        pass

    assert calls == ["persist", "stop", "destroy", ("exit", 0)]
