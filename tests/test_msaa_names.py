# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Control names must reach MSAA, which NVDA and JAWS read on Windows.

wx's ``SetName`` only sets wx's own name, which MSAA never sees, so NVDA
announced the feed tree, search box, article list, reader and playback
speed box with no name. ``widgets.set_msaa_name`` annotates the name on the
HWND. The check asks MSAA exactly as a screen reader does, on controls in a
frame that is never shown, and proves that only the name changed: role,
state, value and the tree/list items stay what the native control reports.
"""

import ctypes
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

wx = pytest.importorskip("wx")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.widgets import set_msaa_name  # noqa: E402


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _VariantData(ctypes.Union):
    _fields_ = [("lVal", ctypes.c_long), ("ptr", ctypes.c_void_p), ("pad", ctypes.c_void_p * 2)]


class _VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3), ("data", _VariantData)]


def _msaa(window):
    """(name, role, state, value) of the window's client object and first 3 children."""
    iid_iaccessible = _GUID(
        0x618736E0, 0x3C3D, 0x11CF, (ctypes.c_ubyte * 8)(0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71)
    )
    acc = ctypes.c_void_p()
    hr = ctypes.WinDLL("oleacc").AccessibleObjectFromWindow(
        ctypes.c_void_p(int(window.GetHandle())),
        ctypes.c_uint32(0xFFFFFFFC),  # OBJID_CLIENT
        ctypes.byref(iid_iaccessible),
        ctypes.byref(acc),
    )
    assert hr == 0 and acc.value
    vtable = ctypes.cast(acc, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

    def method(index, *argtypes):
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])

    def child(n):
        var = _VARIANT()
        var.vt = 3  # VT_I4
        var.data.lVal = n
        return var

    def text(index, n):  # get_accName / get_accValue
        out = ctypes.c_void_p()
        method(index, _VARIANT, ctypes.POINTER(ctypes.c_void_p))(acc, child(n), ctypes.byref(out))
        if not out.value:
            return None
        value = ctypes.wstring_at(out.value)
        ctypes.WinDLL("oleaut32").SysFreeString(ctypes.c_void_p(out.value))
        return value

    def number(index, n):  # get_accRole / get_accState
        out = _VARIANT()
        method(index, _VARIANT, ctypes.POINTER(_VARIANT))(acc, child(n), ctypes.byref(out))
        return out.data.lVal

    try:
        count = ctypes.c_long()
        method(8, ctypes.POINTER(ctypes.c_long))(acc, ctypes.byref(count))  # get_accChildCount
        return [(text(10, n), number(13, n), number(14, n), text(11, n)) for n in range(min(count.value, 3) + 1)]
    finally:
        method(2)(acc)  # Release


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="MSAA is Windows-only")
def test_set_msaa_name_names_only_the_control_itself():
    # A fresh process: once an earlier test has destroyed its wx.App with a
    # WebView2 rich view in it, annotations set later in that process never
    # show up in accName (the running app is not affected).
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def check_names():
    app = wx.App(False)
    frame = wx.Frame(None)  # never shown
    try:
        panel = wx.Panel(frame)
        tree = wx.TreeCtrl(panel, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS)
        root = tree.AddRoot("Root")
        tree.AppendItem(root, "All Articles")
        tree.AppendItem(root, "Favorites")
        search = wx.SearchCtrl(panel, style=wx.TE_PROCESS_ENTER)
        articles = wx.ListCtrl(panel, style=wx.LC_REPORT)
        articles.InsertColumn(0, "Title")
        articles.InsertItem(0, "First")
        articles.InsertItem(1, "Second")
        articles.Select(0)
        reader = wx.TextCtrl(panel, value="Body", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        rewind = wx.Button(panel, label="-10s")
        speed = wx.ComboBox(panel, choices=["1.0x", "1.5x"], style=wx.CB_READONLY)
        speed.SetSelection(1)
        names = {
            tree: "Feeds and folders",
            search: "Search articles",
            articles: "Articles",
            reader: "Article text",
            rewind: "Rewind 10 seconds",
            speed: "Playback Speed",
        }
        # The search box is a composite on Windows; its inner Edit takes focus.
        focused = {ctrl: ctrl for ctrl in names}
        focused[search] = next(c for c in search.GetChildren() if isinstance(c, wx.TextCtrl))
        before = {ctrl: _msaa(focused[ctrl]) for ctrl in names}
        assert before[tree][1][0] == "All Articles"
        assert before[articles][1][0] == "First"
        assert before[tree][0][0] is None and before[articles][0][0] is None

        for ctrl, name in names.items():
            ctrl.SetName(name)
            set_msaa_name(ctrl)

        for ctrl, name in names.items():
            after = _msaa(focused[ctrl])
            assert after[0][0] == name
            assert after[0][1:] == before[ctrl][0][1:], "role/state/value must not change"
            assert after[1:] == before[ctrl][1:], "tree/list items must not change"

        # Every reader swap names a new control; repeated calls must not grow
        # ctypes' process-wide prototype cache.
        cache = getattr(ctypes, "_win_functype_cache", None)
        if cache is not None:
            size = len(cache)
            for _ in range(20):
                set_msaa_name(reader)
            assert len(cache) == size
    finally:
        frame.Destroy()
        app.Destroy()


def test_main_window_and_player_controls_are_named_for_msaa():
    import gui.mainframe as mainframe
    import gui.player as player

    main_ui = inspect.getsource(mainframe.MainFrame.init_ui)
    for ctrl in ("self.tree", "self.search_ctrl", "self.list_ctrl"):
        assert f"set_msaa_name({ctrl})" in main_ui
    assert "set_msaa_name(ctrl)" in inspect.getsource(mainframe.MainFrame._create_article_text_control)
    player_ui = inspect.getsource(player.PlayerFrame.init_ui)
    for ctrl in (
        "self.slider",
        "self.time_info_ctrl",
        "rewind_btn",
        "forward_btn",
        "self.speed_combo",
        "self.chapters_btn",
        "self.chapter_choice",
    ):
        assert f"set_msaa_name({ctrl})" in player_ui
    # The longer chapter names set later are not annotated: they would repeat
    # the current chapter, which NVDA already reads as the combo's value.
    assert "set_msaa_name" not in inspect.getsource(player.PlayerFrame._update_chapter_accessibility_label)


if __name__ == "__main__":
    check_names()
