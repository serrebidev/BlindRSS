# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Runtime access-key (mnemonic) assignment for menus.

Every menu item should carry an access key — the underlined letter that
activates the item while its menu is open, which NVDA announces after the
label. Hand-placing ``&`` in every msgid would force all translators to pick
letters too (and most translations simply drop them), so instead the keys are
assigned here at menu-build time from the *translated* labels: items that
already carry a hand-picked ``&`` keep it, everything else gets the first
letter that is still unique within its menu. Labels with no usable ASCII
character (e.g. CJK translations) get a Windows-style ``label (&K)`` suffix.

Assignment is deterministic for a given menu (items are scanned in order), so
labels rebuilt by ``SetItemLabel`` re-acquire the same keys when the menu is
re-processed.
"""
import string

import wx

# Candidate keys for the appended-suffix form, in preference order.
_SUFFIX_POOL = string.ascii_uppercase + string.digits


def _existing_mnemonic(visible: str):
    """The letter already marked with a lone '&', or None ('&&' is literal)."""
    i = 0
    while i < len(visible):
        if visible[i] == "&":
            if i + 1 < len(visible):
                if visible[i + 1] == "&":
                    i += 2
                    continue
                return visible[i + 1]
            return None
        i += 1
    return None


def _strip_mnemonic(visible: str) -> str:
    """Remove the lone '&' marker, keeping literal '&&' pairs intact."""
    out = []
    i = 0
    stripped = False
    while i < len(visible):
        ch = visible[i]
        if ch == "&" and not stripped:
            if i + 1 < len(visible) and visible[i + 1] == "&":
                out.append("&&")
                i += 2
                continue
            stripped = True
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _candidate_positions(visible: str):
    """Indices to try for '&' insertion: word starts first, then the rest."""
    word_starts = []
    others = []
    prev_is_space = True
    i = 0
    while i < len(visible):
        ch = visible[i]
        if ch == "&" and i + 1 < len(visible) and visible[i + 1] == "&":
            # Literal ampersand: skip the pair, it separates words visually.
            prev_is_space = True
            i += 2
            continue
        if ch.isascii() and ch.isalnum():
            (word_starts if prev_is_space else others).append(i)
        prev_is_space = not ch.isalnum()
        i += 1
    return word_starts + others


def _assign_mnemonic(visible: str, used: set) -> str:
    """Return `visible` with an access key added, or unchanged if impossible."""
    for pos in _candidate_positions(visible):
        letter = visible[pos].lower()
        if letter not in used:
            used.add(letter)
            return visible[:pos] + "&" + visible[pos:]
    # No assignable character inside the label (all taken, or a non-ASCII
    # script): append a "(&K)" suffix, the Windows convention for CJK menus.
    for letter in _SUFFIX_POOL:
        if letter.lower() not in used:
            used.add(letter.lower())
            return f"{visible} (&{letter})"
    return visible


def apply_menu_mnemonics(menu) -> None:
    """Give every item in `menu` (and its submenus) a unique access key."""
    if menu is None:
        return
    try:
        items = list(menu.GetMenuItems())
    except Exception:
        return

    def _is_separator(item) -> bool:
        try:
            return bool(item.IsSeparator())
        except Exception:
            return False

    def _item_label(item):
        try:
            return str(item.GetItemLabel())
        except Exception:
            return None

    used = set()
    # Single ordered pass: a hand-placed key is honored on first claim; a
    # DUPLICATE hand-placed key is reassigned (duplicates make Windows cycle
    # the highlight instead of activating the item, defeating the point of an
    # access key). Items without a key get the first free letter.
    for item in items:
        if _is_separator(item):
            continue
        label = _item_label(item)
        if label is None:
            continue
        visible, sep, accel = label.partition("\t")
        existing = _existing_mnemonic(visible)
        new_visible = visible
        if existing is not None:
            if existing.lower() in used:
                new_visible = _assign_mnemonic(_strip_mnemonic(visible), used)
            else:
                used.add(existing.lower())
        else:
            new_visible = _assign_mnemonic(visible, used)
        if new_visible != visible:
            try:
                item.SetItemLabel(new_visible + (sep + accel if sep else ""))
            except Exception:
                pass
        try:
            submenu = item.GetSubMenu()
        except Exception:
            submenu = None
        if submenu is not None:
            apply_menu_mnemonics(submenu)


def apply_menubar_mnemonics(menubar: "wx.MenuBar") -> None:
    """Apply access keys to every menu of a menu bar (titles keep their own)."""
    if menubar is None:
        return
    try:
        count = int(menubar.GetMenuCount())
    except Exception:
        return
    for i in range(count):
        try:
            apply_menu_mnemonics(menubar.GetMenu(i))
        except Exception:
            pass
