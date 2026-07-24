# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""wx <-> canonical accelerator-string bridge for the shortcut registry.

Keeps all wx-specific keycode knowledge in one place so ``core.shortcuts``
stays pure. Used by the global char-hook to turn a live key event into a
canonical accel string (for dispatch) and by the Keyboard Shortcuts dialog to
capture a keystroke the user presses.
"""
from __future__ import annotations

from typing import Optional

import wx

from core import shortcuts as _sc


# Canonical key token -> the wx keycode we emit when formatting.
# (Matching is done via KEYCODE_TO_TOKEN, which is more permissive.)
def _build_keycode_to_token():
    m = {
        wx.WXK_SPACE: "Space",
        wx.WXK_LEFT: "Left", wx.WXK_RIGHT: "Right",
        wx.WXK_UP: "Up", wx.WXK_DOWN: "Down",
        wx.WXK_HOME: "Home", wx.WXK_END: "End",
        wx.WXK_PAGEUP: "PageUp", wx.WXK_PAGEDOWN: "PageDown",
        wx.WXK_INSERT: "Insert", wx.WXK_DELETE: "Delete",
        wx.WXK_BACK: "Backspace",
        wx.WXK_RETURN: "Enter", wx.WXK_NUMPAD_ENTER: "Enter",
        wx.WXK_TAB: "Tab",
        wx.WXK_ESCAPE: "Escape",
    }
    for n in range(1, 25):
        code = getattr(wx, "WXK_F%d" % n, None)
        if code is not None:
            m[code] = "F" + str(n)
    # Letters (char-hook reports uppercase codes).
    for c in range(ord("A"), ord("Z") + 1):
        m[c] = chr(c)
    for c in range(ord("a"), ord("z") + 1):
        m[c] = chr(c).upper()
    # Digits — numpad included so a "Ctrl+1" binding matches both digit rows
    # (parity with the old hard-coded Ctrl+<digit> filter shortcuts).
    for c in range(ord("0"), ord("9") + 1):
        m[c] = chr(c)
    for n in range(10):
        code = getattr(wx, "WXK_NUMPAD%d" % n, None)
        if code is not None:
            m[code] = str(n)
    # Punctuation, incl. shifted variants that some platforms report so a
    # binding like "Ctrl+Shift+," still matches whether the OS gives us ',' or '<'.
    punct = {
        ord(","): ",", ord("<"): ",",
        ord("."): ".", ord(">"): ".",
        ord("/"): "/", ord("?"): "/",
        ord("-"): "-", ord("_"): "-",
        ord("="): "=", ord("+"): "=",
        ord(";"): ";", ord(":"): ";",
        ord("'"): "'", ord('"'): "'",
        ord("["): "[", ord("{"): "[",
        ord("]"): "]", ord("}"): "]",
        ord("\\"): "\\", ord("|"): "\\",
        ord("`"): "`", ord("~"): "`",
    }
    m.update(punct)
    return m


KEYCODE_TO_TOKEN = _build_keycode_to_token()

# Bare modifier keycodes we never treat as a "key".
_MODIFIER_KEYCODES = {
    wx.WXK_CONTROL, wx.WXK_ALT, wx.WXK_SHIFT,
    getattr(wx, "WXK_RAW_CONTROL", -991),
    getattr(wx, "WXK_WINDOWS_LEFT", -992),
    getattr(wx, "WXK_WINDOWS_RIGHT", -993),
    getattr(wx, "WXK_COMMAND", -994),
}


def _event_mods(event: wx.KeyEvent):
    mods = []
    try:
        if event.ControlDown():
            mods.append("Ctrl")
    except Exception:
        pass
    try:
        if event.AltDown():
            mods.append("Alt")
    except Exception:
        pass
    try:
        if event.ShiftDown():
            mods.append("Shift")
    except Exception:
        pass
    try:
        if event.MetaDown():
            mods.append("Cmd")
    except Exception:
        pass
    return mods


def event_to_accel(event: wx.KeyEvent, *, require_modifier: bool = True) -> Optional[str]:
    """Return the canonical accel string for a key event, or None.

    When ``require_modifier`` is True (dispatch), events with no modifier (or a
    bare modifier key) yield None so plain typing/navigation is never captured.
    Bare function keys are the exception — F2/F5-style bindings never collide
    with typing, so they dispatch unmodified. The capture dialog passes False
    so any single key can be recorded too.
    """
    try:
        key = int(event.GetKeyCode())
    except Exception:
        return None
    if key in _MODIFIER_KEYCODES:
        return None
    token = KEYCODE_TO_TOKEN.get(key)
    if token is None:
        return None
    mods = _event_mods(event)
    is_function_key = len(token) >= 2 and token[0] == "F" and token[1:].isdigit()
    if require_modifier and not mods and not is_function_key:
        return None
    return _sc.format_accel(mods, token)
