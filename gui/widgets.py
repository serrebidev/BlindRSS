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

# Status-bar style without any wx.STB_ELLIPSIZE_* flag (the default has END).
# With ellipsizing, wxMSW stores a shortened copy ("Playing: Title gr...") in
# the native control and that copy is all NVDA's read-status-bar command gets,
# so the playback time at the end was never spoken. Without it the full text
# stays readable; only the drawing is clipped.
STATUS_BAR_STYLE = wx.STB_SIZEGRIP | wx.STB_SHOW_TIPS | wx.FULL_REPAINT_ON_RESIZE


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


_msaa_name_api = None


def _get_msaa_name_api():
    """ctypes GUIDs and COM method prototypes for ``set_msaa_name``, built once.

    ctypes caches every WINFUNCTYPE prototype by its argument types for the
    life of the process, so declaring them (and a fresh GUID class) per call
    added a cache entry on every call.
    """
    global _msaa_name_api
    if _msaa_name_api is None:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        def guid(text):
            value = GUID()
            ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(value))
            return value

        _msaa_name_api = (
            guid("{b5f8350b-0548-48b1-a6ee-88bd00b4a5e7}"),  # CLSID_AccPropServices
            guid("{6e26e776-04f0-495d-80e4-3330352e3169}"),  # IID_IAccPropServices
            guid("{608d3df8-8128-4aa7-a428-f55e49267291}"),  # PROPID_ACC_NAME
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p),  # IUnknown::Release
            ctypes.WINFUNCTYPE(  # IAccPropServices::SetHwndPropStr
                ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, wintypes.DWORD, wintypes.DWORD, GUID, wintypes.LPCWSTR
            ),
        )
    return _msaa_name_api


def set_msaa_name(ctrl) -> None:
    """Make a control's wx name (``SetName``) reach NVDA/JAWS on Windows.

    wx's ``SetName`` only sets wx's own name and MSAA never sees it, so NVDA
    announced the feed tree, search box, article list and reader with no
    name at all. This annotates the name on the control's HWND
    (MSAA Direct Annotation: ``IAccPropServices::SetHwndPropStr`` for
    OBJID_CLIENT/CHILDID_SELF). Only the name changes; role, states, value and
    the tree/list items still come from the native control.

    Do not use ``wx.Window.SetAccessibleName`` (wx 3.3) or any other
    ``wx.Accessible`` for this: it replaces the native object with a
    ``wx.Accessible``, so the RichEdit reader becomes a generic "client" role
    and loses its value and read-only state, and a ComboBox's dropdown list
    child changes role and takes the combo's name.

    ``wx.SearchCtrl`` is a composite on Windows whose inner Edit takes the
    focus, so that Edit is named too. Call again after each ``SetName``.
    No-op off Windows or on failure.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        clsid, iid, name_prop, release_type, set_hwnd_prop_str_type = _get_msaa_name_api()
        services = ctypes.c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(
            ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(services)  # 1 = CLSCTX_INPROC_SERVER
        )
        vtable = ctypes.cast(services, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        try:
            text = str(ctrl.GetName())
            windows = [ctrl]
            if isinstance(ctrl, wx.SearchCtrl):
                windows += [c for c in ctrl.GetChildren() if isinstance(c, wx.TextCtrl)]
            for window in windows:
                # 0xFFFFFFFC = OBJID_CLIENT, 0 = CHILDID_SELF
                set_hwnd_prop_str_type(vtable[7])(services, int(window.GetHandle()), 0xFFFFFFFC, 0, name_prop, text)
        finally:
            release_type(vtable[2])(services)
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
