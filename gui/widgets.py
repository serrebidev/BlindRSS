# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Shared accessible custom controls.

CheckListCtrl exists because wx.CheckListBox is invisible to screen readers on
Windows: wxMSW implements it as an owner-drawn ListBox whose checkboxes are
only painted, so MSAA/UIA report a plain list with no checkable state and NVDA
users hear "selected" instead of "checked"/"not checked" (nvaccess/nvda#7325 —
the NVDA project itself replaced wx.CheckListBox for the same reason). A
wx.ListCtrl with native checkboxes is the ListView control Windows Disk
Cleanup uses: NVDA reports the check state per item, announces changes, and
Space toggles the focused item natively.
"""
import sys
from typing import Callable, Optional

import wx


def force_ltr_reading(ctrl) -> None:
    """Reset a Windows RichEdit control to left-to-right reading order.

    RichEdit has a built-in gesture — pressing the RIGHT Ctrl+Shift — that
    flips the current paragraph (and the control's reading order) to
    right-to-left. BlindRSS binds several Ctrl+Shift shortcuts, so NVDA users
    hit the gesture by accident and the whole article suddenly reads
    right-to-left with no way to see why. Clearing the RTL paragraph effect
    and the RTL/right-aligned window styles after each render keeps the
    reader deterministically LTR. No-op off Windows or on failure.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        hwnd = int(ctrl.GetHandle())
        if not hwnd:
            return
        user32 = ctypes.windll.user32

        # Clear WS_EX_RTLREADING / WS_EX_RIGHT / WS_EX_LEFTSCROLLBAR.
        GWL_EXSTYLE = -20
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        cleared = ex & ~(0x2000 | 0x1000 | 0x4000)
        if cleared != ex:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cleared)

        class PARAFORMAT2(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("dwMask", ctypes.c_uint32),
                ("wNumbering", ctypes.c_ushort),
                ("wEffects", ctypes.c_ushort),
                ("dxStartIndent", ctypes.c_int32),
                ("dxRightIndent", ctypes.c_int32),
                ("dxOffset", ctypes.c_int32),
                ("wAlignment", ctypes.c_ushort),
                ("cTabCount", ctypes.c_short),
                ("rgxTabs", ctypes.c_int32 * 32),
                ("dySpaceBefore", ctypes.c_int32),
                ("dySpaceAfter", ctypes.c_int32),
                ("dyLineSpacing", ctypes.c_int32),
                ("sStyle", ctypes.c_short),
                ("bLineSpacingRule", ctypes.c_ubyte),
                ("bOutlineLevel", ctypes.c_ubyte),
                ("wShadingWeight", ctypes.c_ushort),
                ("wShadingStyle", ctypes.c_ushort),
                ("wNumberingStart", ctypes.c_ushort),
                ("wNumberingStyle", ctypes.c_ushort),
                ("wNumberingTab", ctypes.c_ushort),
                ("wBorderSpace", ctypes.c_ushort),
                ("wBorderWidth", ctypes.c_ushort),
                ("wBorders", ctypes.c_ushort),
            ]

        EM_SETSEL = 0x00B1
        EM_GETSEL = 0x00B0
        EM_SETPARAFORMAT = 0x0447  # WM_USER + 71
        PFM_RTLPARA = 0x00010000
        PFM_ALIGNMENT = 0x00000008
        PFA_LEFT = 1

        start = ctypes.c_uint32(0)
        end = ctypes.c_uint32(0)
        user32.SendMessageW(hwnd, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))

        pf = PARAFORMAT2()
        pf.cbSize = ctypes.sizeof(PARAFORMAT2)
        pf.dwMask = PFM_RTLPARA | PFM_ALIGNMENT
        pf.wEffects = 0
        pf.wAlignment = PFA_LEFT

        user32.SendMessageW(hwnd, EM_SETSEL, 0, -1)
        user32.SendMessageW(hwnd, EM_SETPARAFORMAT, 0, ctypes.byref(pf))
        user32.SendMessageW(hwnd, EM_SETSEL, int(start.value), int(end.value))
    except Exception:
        pass


class CheckListCtrl(wx.ListCtrl):
    """Single-column checkable list with a CheckListBox-like API.

    Set ``on_user_check`` to a ``callable(index, checked)``; it fires only for
    user-initiated toggles (Space or a checkbox click), never for programmatic
    ``Check()``/``Set()`` calls, so consumers can update their model without
    re-entrancy guards.
    """

    def __init__(self, parent):
        super().__init__(
            parent,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER,
        )
        self.InsertColumn(0, "")
        self.EnableCheckBoxes(True)
        self.on_user_check: Optional[Callable[[int, bool], None]] = None
        self._programmatic = 0
        self.Bind(wx.EVT_LIST_ITEM_CHECKED, lambda e: self._on_check_event(e, True))
        self.Bind(wx.EVT_LIST_ITEM_UNCHECKED, lambda e: self._on_check_event(e, False))
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, event):
        event.Skip()
        # The single column tracks the control width so labels aren't clipped
        # at the ListCtrl's tiny default column width.
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, max(40, width - 4))

    def _on_check_event(self, event, checked: bool) -> None:
        if self._programmatic:
            return
        callback = self.on_user_check
        if callback is None:
            return
        index = int(event.GetIndex())
        if 0 <= index < self.GetItemCount():
            callback(index, bool(checked))

    # -- CheckListBox-compatible surface ---------------------------------

    def Set(self, labels) -> None:
        """Replace all rows (all unchecked; selection is cleared)."""
        self._programmatic += 1
        try:
            self.DeleteAllItems()
            for i, label in enumerate(list(labels or [])):
                self.InsertItem(i, str(label))
        finally:
            self._programmatic -= 1

    def GetCount(self) -> int:
        return self.GetItemCount()

    def Check(self, index: int, check: bool = True) -> None:
        self._programmatic += 1
        try:
            self.CheckItem(int(index), bool(check))
        finally:
            self._programmatic -= 1

    def IsChecked(self, index: int) -> bool:
        return bool(self.IsItemChecked(int(index)))

    def GetSelection(self) -> int:
        return int(self.GetFirstSelected())

    def SetSelection(self, index: int) -> None:
        index = int(index)
        if 0 <= index < self.GetItemCount():
            self.Select(index)
            self.Focus(index)

    def SetString(self, index: int, label: str) -> None:
        self.SetItemText(int(index), str(label))
