# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _MenuItem:
    def __init__(self, checked):
        self._checked = checked

    def IsChecked(self):
        return self._checked

    def Check(self, val):
        self._checked = bool(val)


class _Config:
    def __init__(self, rich):
        self.values = {"full_text_rich_view": rich}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _ListCtrl:
    def GetFirstSelected(self):
        return 0


class _Host:
    on_toggle_rich_view = mainframe.MainFrame.on_toggle_rich_view
    _rich_view_enabled = mainframe.MainFrame._rich_view_enabled
    _sync_rich_view_menu_item = mainframe.MainFrame._sync_rich_view_menu_item

    def __init__(self, *, rich_before, reading):
        # The menu item's check state already reflects the requested value by the
        # time the event fires, so it is the inverse of the current setting.
        self._rich_view_menu_item = _MenuItem(not rich_before)
        self.config_manager = _Config(rich_before)
        self.list_ctrl = _ListCtrl()
        self._fulltext_token = 0
        self._reading = reading
        self.applied = 0
        self.updated = []
        self.focused = 0

    def _reader_surface_focused(self):
        return self._reading

    def _apply_reader_mode(self):
        self.applied += 1
        return self.config_manager.get("full_text_rich_view", False)

    def _update_content_view(self, idx):
        self.updated.append(idx)

    def _focus_reader_surface(self):
        self.focused += 1


def _toggle(monkeypatch, *, rich_before, reading):
    host = _Host(rich_before=rich_before, reading=reading)
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    host.on_toggle_rich_view()
    return host


def test_disabling_rich_view_while_reading_refocuses_the_plain_reader(monkeypatch):
    # The reported bug: turning the rich view off from inside the article text
    # left focus on the hidden WebView, so the screen reader kept reading the
    # rich view until the user tabbed to the list and back.
    host = _toggle(monkeypatch, rich_before=True, reading=True)
    assert host.config_manager.get("full_text_rich_view") is False
    assert host.applied == 1
    assert host.updated == [0]
    assert host.focused == 1


def test_enabling_rich_view_while_reading_refocuses_the_rich_reader(monkeypatch):
    host = _toggle(monkeypatch, rich_before=False, reading=True)
    assert host.config_manager.get("full_text_rich_view") is True
    assert host.focused == 1


def test_toggling_from_outside_the_reader_leaves_focus_alone(monkeypatch):
    # Flipping the setting while the article list has focus must not steal it.
    host = _toggle(monkeypatch, rich_before=True, reading=False)
    assert host.config_manager.get("full_text_rich_view") is False
    assert host.updated == [0]
    assert host.focused == 0


def test_accelerator_path_toggles_even_without_preflipped_menu_item(monkeypatch):
    # Ctrl+Shift+H (menu accelerator or WebView bridge) does not pre-flip the
    # check item the way a menu click does; the toggle must not depend on it.
    host = _Host(rich_before=True, reading=False)
    host._rich_view_menu_item = _MenuItem(True)  # still shows the CURRENT state
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    host.on_toggle_rich_view()
    assert host.config_manager.get("full_text_rich_view") is False
    # And the check item was re-synced to the new value.
    assert host._rich_view_menu_item.IsChecked() is False


def test_webview_bridge_message_toggles_rich_view(monkeypatch):
    # Ctrl+Shift+H inside the WebView arrives as a bridged '__toggle_rich'
    # message (wx never sees the keystroke there).
    host = _Host(rich_before=True, reading=False)
    host._on_rich_view_message = mainframe.MainFrame._on_rich_view_message.__get__(host)
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    host._on_rich_view_message({"type": "__toggle_rich"})
    assert host.config_manager.get("full_text_rich_view") is False


def test_rich_view_key_bridge_script_covers_ctrl_shift_h():
    # The JS injected into the rich reader must bridge Ctrl+Shift+H out, or the
    # shortcut silently dies whenever focus is inside the WebView.
    js = mainframe.MainFrame._RICH_VIEW_KEYS_JS
    assert "__toggle_rich" in js
    assert "KeyH" in js
