# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The persistent-search dropdown menu must never be freed twice.

wx.SearchCtrl.SetMenu transfers ownership of the menu to the control: the
control frees the previous menu itself when a new one is set. Destroying an
attached menu from our side too caused a native double-free that killed the
whole app window when the saved-search dialog's OK rebuilt the menu.
"""

import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _FakeMenuItem:
    _next_id = 1000

    def __init__(self, label):
        self.label = label
        _FakeMenuItem._next_id += 1
        self._id = _FakeMenuItem._next_id

    def GetId(self):
        return self._id

    def Enable(self, enabled=True):
        return None


class _FakeMenu:
    instances = []

    def __init__(self):
        self.destroyed = False
        _FakeMenu.instances.append(self)

    def Append(self, _id, label):
        return _FakeMenuItem(label)

    def AppendSeparator(self):
        return None

    def Destroy(self):
        self.destroyed = True


class _FakeSearchCtrl:
    def __init__(self, fail=False):
        self.fail = fail
        self.menus = []

    def SetMenu(self, menu):
        if self.fail:
            raise RuntimeError("no native search control")
        self.menus.append(menu)

    def AutoComplete(self, _choices):
        return None


class _Host:
    _apply_persistent_search_menu = mainframe.MainFrame._apply_persistent_search_menu

    def __init__(self, search_ctrl):
        self._persistent_searches = ["python", "wxpython"]
        self._persistent_search_items = {}
        self.search_ctrl = search_ctrl

    def Bind(self, _event, _handler, _item=None):
        return None

    def on_persistent_search_select(self, _event):
        return None

    def on_configure_persistent_search(self, _event=None):
        return None


def test_attached_menu_is_never_destroyed_by_us(monkeypatch):
    _FakeMenu.instances = []
    monkeypatch.setattr(mainframe.wx, "Menu", _FakeMenu)
    ctrl = _FakeSearchCtrl()
    host = _Host(ctrl)

    host._apply_persistent_search_menu()
    host._apply_persistent_search_menu()

    first, second = _FakeMenu.instances
    # The control owns both menus once attached; freeing the first one here
    # would be the double-free that crashed the app on saved-search OK.
    assert ctrl.menus == [first, second]
    assert first.destroyed is False
    assert second.destroyed is False
    assert host._persistent_search_menu is second
    assert host._persistent_search_menu_attached is True


def test_unattached_menu_is_destroyed_on_rebuild(monkeypatch):
    _FakeMenu.instances = []
    monkeypatch.setattr(mainframe.wx, "Menu", _FakeMenu)
    host = _Host(_FakeSearchCtrl(fail=True))

    host._apply_persistent_search_menu()
    host._apply_persistent_search_menu()

    first, second = _FakeMenu.instances
    # SetMenu never took ownership, so we must free the replaced menu ourselves.
    assert first.destroyed is True
    assert second.destroyed is False
    assert host._persistent_search_menu_attached is False
