# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _FakeMenuItem:
    def __init__(self, item_id: int, label: str):
        self._id = int(item_id)
        self.label = str(label)
        self.enabled = True

    def GetId(self):
        return int(self._id)

    def Enable(self, enabled=True):
        self.enabled = bool(enabled)


class _FakeMenu:
    def __init__(self):
        self._next_id = 100
        self.items = {}
        self._order = []
        self.bindings = []

    def Append(self, item_id, label, help_text=""):
        _ = help_text
        if int(item_id) == int(mainframe.wx.ID_ANY):
            item_id = self._next_id
            self._next_id += 1
        item = _FakeMenuItem(int(item_id), str(label))
        self.items[int(item_id)] = item
        self._order.append(int(item_id))
        return item

    def AppendSeparator(self):
        return self.Append(mainframe.wx.ID_ANY, "---")

    def Delete(self, item_id):
        item_id = int(item_id)
        self.items.pop(item_id, None)
        try:
            self._order.remove(item_id)
        except ValueError:
            pass

    def Bind(self, evt, handler, item):
        self.bindings.append((evt, int(item.GetId()), handler))

    def Unbind(self, evt, id=None):
        if id is None:
            return False
        target = int(id)
        before = len(self.bindings)
        self.bindings = [
            b for b in self.bindings if not (b[0] is evt and b[1] == target)
        ]
        return before != len(self.bindings)

    def GetMenuItems(self):
        return [self.items[item_id] for item_id in self._order if item_id in self.items]


class _PlayerStub:
    def __init__(self, chapters, active_idx=0):
        self.current_chapters = list(chapters or [])
        self._active_idx = int(active_idx)
        self.calls = []

    def get_active_chapter_index(self):
        return int(self._active_idx)

    def show_chapters_menu(self):
        self.calls.append(("show", None))

    def prev_chapter(self):
        self.calls.append(("prev", None))

    def next_chapter(self):
        self.calls.append(("next", None))

    def jump_to_chapter(self, idx):
        self.calls.append(("jump", int(idx)))


class _DummyMain:
    _format_chapter_timestamp = mainframe.MainFrame._format_chapter_timestamp
    _format_player_chapter_menu_label = mainframe.MainFrame._format_player_chapter_menu_label
    _clear_menu_items = mainframe.MainFrame._clear_menu_items
    _refresh_player_chapters_submenu = mainframe.MainFrame._refresh_player_chapters_submenu
    _player_chapters_signature = mainframe.MainFrame._player_chapters_signature
    _unbind_player_chapter_items = mainframe.MainFrame._unbind_player_chapter_items
    _shortcut_menu_label = mainframe.MainFrame._shortcut_menu_label
    on_player_show_chapters = mainframe.MainFrame.on_player_show_chapters
    on_player_prev_chapter = mainframe.MainFrame.on_player_prev_chapter
    on_player_next_chapter = mainframe.MainFrame.on_player_next_chapter
    on_player_chapter_jump = mainframe.MainFrame.on_player_chapter_jump

    def binding_label(self, command_id):
        # These tests assert on base labels, so report every command unbound.
        return ""

    def __init__(self, chapters, active_idx=0):
        self.player_window = _PlayerStub(chapters, active_idx=active_idx)
        self._player_chapters_submenu = _FakeMenu()
        self._player_chapters_show_item = None
        self._player_chapters_prev_item = None
        self._player_chapters_next_item = None
        self._player_chapter_dynamic_item_ids = []
        self._player_chapter_static_item_ids = []
        self.bound = []

    def Bind(self, evt, handler, item):
        self.bound.append((evt, handler, int(item.GetId())))

    def Unbind(self, evt, id=None):
        if id is None:
            return False
        target = int(id)
        before = len(self.bound)
        self.bound = [b for b in self.bound if not (b[0] is evt and b[2] == target)]
        return before != len(self.bound)


def test_refresh_player_chapters_submenu_populates_dynamic_entries():
    host = _DummyMain(
        chapters=[
            {"start": 0.0, "title": "Intro"},
            {"start": 15.0, "title": "News"},
        ],
        active_idx=1,
    )

    host._refresh_player_chapters_submenu()

    assert host._player_chapters_show_item.enabled is True
    assert host._player_chapters_prev_item.enabled is True
    assert host._player_chapters_next_item.enabled is False
    assert len(host._player_chapter_dynamic_item_ids) == 2
    labels = [host._player_chapters_submenu.items[i].label for i in host._player_chapter_dynamic_item_ids]
    assert labels[0] == "00:00, Intro"
    assert labels[1] == "Current chapter, 00:15, News"
    ordered_labels = [item.label for item in host._player_chapters_submenu.GetMenuItems()]
    assert ordered_labels[0] == "00:00, Intro"
    assert ordered_labels[1] == "Current chapter, 00:15, News"
    assert "Show Chapters..." in ordered_labels
    assert "Previous Chapter (Ctrl+Shift+Left)" in ordered_labels
    assert "Next Chapter (Ctrl+Shift+Right)" in ordered_labels


def test_refresh_player_chapters_submenu_shows_empty_state_when_no_chapters():
    host = _DummyMain(chapters=[], active_idx=-1)

    host._refresh_player_chapters_submenu()

    assert host._player_chapters_show_item.enabled is False
    assert host._player_chapters_prev_item.enabled is False
    assert host._player_chapters_next_item.enabled is False
    assert len(host._player_chapter_dynamic_item_ids) == 1
    only_id = host._player_chapter_dynamic_item_ids[0]
    assert host._player_chapters_submenu.items[only_id].label == "No chapters available"
    assert host._player_chapters_submenu.items[only_id].enabled is False


def test_player_chapters_handlers_dispatch_to_player_window():
    host = _DummyMain(chapters=[{"start": 0.0, "title": "Intro"}], active_idx=0)

    host.on_player_show_chapters(None)
    host.on_player_prev_chapter(None)
    host.on_player_next_chapter(None)
    host.on_player_chapter_jump(None, 3)

    assert host.player_window.calls == [
        ("show", None),
        ("prev", None),
        ("next", None),
        ("jump", 3),
    ]


def test_chapter_menu_formats_hours_and_invalid_timestamps_accessibly():
    host = _DummyMain(chapters=[])

    assert host._format_player_chapter_menu_label(
        {"start": 3723.9, "title": "Long episode"}
    ) == "1:02:03, Long episode"
    assert host._format_player_chapter_menu_label(
        {"start": float("nan"), "title": ""}
    ) == "00:00, Untitled chapter"


def test_chapter_menu_enables_only_available_direction():
    host = _DummyMain(
        chapters=[
            {"start": 0.0, "title": "Intro"},
            {"start": 15.0, "title": "News"},
        ],
        active_idx=0,
    )

    host._refresh_player_chapters_submenu()

    assert host._player_chapters_prev_item.enabled is False
    assert host._player_chapters_next_item.enabled is True


def test_repeat_open_does_not_touch_native_menu_when_nothing_changed():
    """A menu open with an unchanged chapter list must not rebuild the submenu.

    The rebuild runs from EVT_MENU_OPEN — inside WM_INITMENUPOPUP, while Windows is
    tracking the menu — and deletes and re-appends every item. Doing that on every
    open churned the window's menus for nothing and left the menu bar wedged after
    a long session: arrowing past Help or File stopped moving and the whole menu
    session went dead.
    """
    host = _DummyMain(
        chapters=[
            {"start": 0.0, "title": "Intro"},
            {"start": 15.0, "title": "News"},
        ],
        active_idx=0,
    )

    host._refresh_player_chapters_submenu()
    built_ids = list(host._player_chapters_submenu.items.keys())
    dynamic_ids = list(host._player_chapter_dynamic_item_ids)

    for _ in range(10):
        host._refresh_player_chapters_submenu()

    assert list(host._player_chapters_submenu.items.keys()) == built_ids
    assert list(host._player_chapter_dynamic_item_ids) == dynamic_ids


def test_rebuild_still_runs_when_the_active_chapter_moves_on():
    host = _DummyMain(
        chapters=[
            {"start": 0.0, "title": "Intro"},
            {"start": 15.0, "title": "News"},
        ],
        active_idx=0,
    )
    host._refresh_player_chapters_submenu()
    assert host._player_chapters_next_item.enabled is True
    assert host._player_chapters_prev_item.enabled is False

    host.player_window._active_idx = 1
    host._refresh_player_chapters_submenu()

    labels = [
        host._player_chapters_submenu.items[i].label
        for i in host._player_chapter_dynamic_item_ids
    ]
    assert labels[1] == "Current chapter, 00:15, News"
    assert host._player_chapters_prev_item.enabled is True
    assert host._player_chapters_next_item.enabled is False


def test_rebuild_runs_when_the_chapter_list_itself_changes():
    host = _DummyMain(chapters=[], active_idx=-1)
    host._refresh_player_chapters_submenu()
    assert len(host._player_chapter_dynamic_item_ids) == 1

    host.player_window.current_chapters = [
        {"start": 0.0, "title": "Intro"},
        {"start": 15.0, "title": "News"},
    ]
    host.player_window._active_idx = 0
    host._refresh_player_chapters_submenu()

    assert len(host._player_chapter_dynamic_item_ids) == 2


def test_rebuild_does_not_accumulate_handler_bindings():
    """Each rebuild binds fresh wx.ID_ANY handlers; the stale ones must go.

    Without unbinding, the event tables grew for the life of the process — a menu
    that had been rebuilt on every Player-menu open for hours.
    """
    host = _DummyMain(chapters=[{"start": 0.0, "title": "Intro"}], active_idx=0)
    host._refresh_player_chapters_submenu()
    submenu_bindings = len(host._player_chapters_submenu.bindings)
    frame_bindings = len(host.bound)

    for i in range(8):
        # Force a different signature each time so the rebuild really runs.
        host.player_window.current_chapters = [{"start": float(i), "title": f"Ch{i}"}]
        host._refresh_player_chapters_submenu()

    assert len(host._player_chapters_submenu.bindings) == submenu_bindings
    assert len(host.bound) == frame_bindings
