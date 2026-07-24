# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Access-key assignment: every item gets a unique-in-menu mnemonic."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui import menu_mnemonics as mn


class _Item:
    def __init__(self, label, separator=False, submenu=None):
        self._label = label
        self._separator = separator
        self._submenu = submenu

    def IsSeparator(self):
        return self._separator

    def GetItemLabel(self):
        return self._label

    def SetItemLabel(self, label):
        self._label = label

    def GetSubMenu(self):
        return self._submenu


class _Menu:
    def __init__(self, items):
        self._items = list(items)

    def GetMenuItems(self):
        return list(self._items)


def _labels(menu):
    return [i.GetItemLabel() for i in menu.GetMenuItems() if not i.IsSeparator()]


def _mnemonics(menu):
    return [mn._existing_mnemonic(lbl.split("\t")[0]) for lbl in _labels(menu)]


def test_assigns_missing_and_keeps_existing():
    menu = _Menu([_Item("&Add Feed"), _Item("Copy Link"), _Item("Copy Text")])
    mn.apply_menu_mnemonics(menu)
    keys = [k.lower() for k in _mnemonics(menu)]
    assert keys[0] == "a"
    assert None not in _mnemonics(menu)
    assert len(set(keys)) == 3


def test_duplicate_hand_placed_keys_are_reassigned():
    # Historically "&Refresh Feeds" and "&Remove Feed" shared R, which makes
    # Windows cycle the highlight instead of activating.
    menu = _Menu([_Item("&Remove Feed"), _Item("&Refresh Feeds"), _Item("&Read Only")])
    mn.apply_menu_mnemonics(menu)
    keys = [k.lower() for k in _mnemonics(menu)]
    assert keys[0] == "r"
    assert len(set(keys)) == 3


def test_accelerator_suffix_is_preserved():
    menu = _Menu([_Item("Delete Article\tDel")])
    mn.apply_menu_mnemonics(menu)
    label = menu.GetMenuItems()[0].GetItemLabel()
    assert label.endswith("\tDel")
    assert mn._existing_mnemonic(label.split("\t")[0]) is not None


def test_literal_ampersands_stay_doubled():
    menu = _Menu([_Item("Feeds && Articles")])
    mn.apply_menu_mnemonics(menu)
    label = menu.GetMenuItems()[0].GetItemLabel()
    assert "&&" in label


def test_cjk_labels_get_suffix_key():
    menu = _Menu([_Item("設定"), _Item("終了")])
    mn.apply_menu_mnemonics(menu)
    for label in _labels(menu):
        assert mn._existing_mnemonic(label) is not None
    keys = {k.lower() for k in _mnemonics(menu)}
    assert len(keys) == 2


def test_recurses_into_submenus_with_fresh_scope():
    sub = _Menu([_Item("Alpha"), _Item("Beta")])
    menu = _Menu([_Item("Alpha"), _Item("Sub", submenu=sub)])
    mn.apply_menu_mnemonics(menu)
    assert None not in _mnemonics(menu)
    assert None not in _mnemonics(sub)
    # Submenu scope is independent: "Alpha" can use &A in both menus.
    assert _mnemonics(sub)[0].lower() == "a"
