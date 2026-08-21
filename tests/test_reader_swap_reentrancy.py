# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regressions for the large-reader control swap (issue #91).

_swap_focused_large_reader hands NVDA a fully populated RichEdit by building a
replacement control and moving focus to it. That SetFocus() delivers
EVT_SET_FOCUS synchronously, and on_content_focus re-enters
_set_article_reader_text through the full-text cache-hit path, so the swap has
to survive being re-entered and has to undo itself completely if it fails.

Left unguarded the re-entry swapped again without bound, and the recursion
unwound through the exception handlers leaving the old control visible while
content_ctrl pointed at a new one: every later write went to a control the user
could not see, so the reader stayed frozen on one article until restart.
"""
import types

import pytest

import gui.mainframe as mainframe
from gui.reader_performance import LARGE_READER_TEXT_CHARS

MF = mainframe.MainFrame

BIG = "a line of extracted article text\n" * 1200
SMALL = "short feed description"


@pytest.fixture(autouse=True)
def _force_windows(monkeypatch):
    # The swap is a Win32/RichEdit path; exercise it on every platform.
    monkeypatch.setattr(mainframe.sys, "platform", "win32")


class _Ctrl:
    def __init__(self, registry, on_focus=None):
        self.value = ""
        self.insertion = 0
        self.selection = (0, 0)
        self.shown = True
        self.destroyed = False
        self.focused = False
        self._on_focus = on_focus
        registry.append(self)

    def GetLastPosition(self):
        return len(self.value)

    def GetSelection(self):
        return self.selection

    def GetInsertionPoint(self):
        return self.insertion

    def SetInsertionPoint(self, pos):
        self.insertion = pos
        self.selection = (pos, pos)

    def SetSelection(self, start, end):
        self.selection = (start, end)
        self.insertion = end

    def ChangeValue(self, value):
        self.value = value

    def SetValue(self, value):
        self.value = value

    def IsShown(self):
        return self.shown

    def Hide(self):
        self.shown = False

    def Show(self, shown=True):
        self.shown = shown

    def Destroy(self):
        self.destroyed = True

    def SetFocus(self):
        self.focused = True
        if self._on_focus is not None:
            self._on_focus(self)


class _Sizer:
    def __init__(self):
        self.replace_calls = []

    def Replace(self, old, new):
        self.replace_calls.append((old, new))
        return True


def _frame(monkeypatch, on_focus=None):
    controls = []
    d = types.SimpleNamespace()
    d._reader_sizer = _Sizer()
    d.reader_panel = types.SimpleNamespace(Layout=lambda: None)
    d.content_ctrl = _Ctrl(controls, on_focus=on_focus)
    d._controls = controls
    d._create_article_text_control = lambda: _Ctrl(controls, on_focus=on_focus)
    d._update_search_tab_order = lambda: None
    d._compose_article_reader_text = lambda text, article=None: text
    d._swap_focused_large_reader = lambda text, reset: MF._swap_focused_large_reader(d, text, reset)
    d._invalidate_reader_text_tracking = lambda: MF._invalidate_reader_text_tracking(d)

    focus = {"cur": d.content_ctrl}
    monkeypatch.setattr(mainframe.wx.Window, "FindFocus", staticmethod(lambda: focus["cur"]))
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **kw: None)
    d._focus = focus
    return d


def _set(d, text, reset_insertion=True):
    return MF._set_article_reader_text(d, object(), text, reset_insertion=reset_insertion)


def test_swap_survives_reentrant_focus_without_swapping_again(monkeypatch):
    """The focus handler re-enters with the same text; that must not re-swap."""
    assert len(BIG) > LARGE_READER_TEXT_CHARS
    state = {"reentries": 0}

    def on_focus(ctrl):
        d = state["frame"]
        d._focus["cur"] = ctrl
        state["reentries"] += 1
        if state["reentries"] > 8:
            raise AssertionError("runaway re-entrant swapping")
        # Mirrors on_content_focus -> cache hit -> _set_article_reader_text.
        _set(d, BIG)

    d = _frame(monkeypatch, on_focus=on_focus)
    state["frame"] = d

    _set(d, BIG)

    # Exactly one replacement control built: original + one new.
    assert len(d._controls) == 2
    assert state["reentries"] == 1
    assert d.content_ctrl is d._controls[1]
    assert d.content_ctrl.value == BIG
    assert d._reader_displayed_text == BIG
    visible = [c for c in d._controls if c.shown and not c.destroyed]
    assert visible == [d.content_ctrl]


def test_failed_swap_restores_the_previous_reader(monkeypatch):
    """A raising focus handler must leave exactly one usable, visible reader."""

    def on_focus(ctrl):
        raise RuntimeError("focus handler blew up")

    d = _frame(monkeypatch, on_focus=on_focus)
    original = d.content_ctrl

    result = _set(d, BIG)

    assert result == BIG
    # Rolled back: the control the user can see is the one we still write to.
    assert d.content_ctrl is original
    assert original.shown and not original.destroyed
    replacement = d._controls[1]
    assert replacement.destroyed
    visible = [c for c in d._controls if c.shown and not c.destroyed]
    assert visible == [original]
    # The swap is only an optimisation: when it fails the text still has to
    # reach the surviving control, and the memo must describe what it holds.
    assert original.value == BIG
    assert d._reader_displayed_text == BIG


def test_reentrancy_guard_clears_after_a_failed_swap(monkeypatch):
    """A failed swap must not wedge the guard and disable all later swaps."""
    calls = {"n": 0}

    def on_focus(ctrl):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first attempt fails")
        d._focus["cur"] = ctrl

    d = _frame(monkeypatch, on_focus=on_focus)
    _set(d, BIG)
    assert d._reader_swap_active is False

    # A later article of the same size must still get the swap treatment.
    other = BIG.replace("article", "ARTICLE")
    _set(d, other)
    assert d.content_ctrl.value == other
    assert d._reader_displayed_text == other


def test_direct_writes_invalidate_the_displayed_text_memo(monkeypatch):
    """Clearing/placeholder writes must not leave the memo claiming old text."""
    d = _frame(monkeypatch)

    _set(d, SMALL)
    assert d._reader_displayed_text == SMALL

    # What on_article_select does for immediate feedback.
    d.content_ctrl.SetValue("Loading...")
    d._invalidate_reader_text_tracking()
    assert d._reader_displayed_text is None

    # The same text must now be re-applied rather than skipped as "already shown".
    _set(d, SMALL)
    assert d.content_ctrl.value == SMALL


def test_small_text_skips_repeat_write_when_already_displayed(monkeypatch):
    """The memo still short-circuits genuine repeats (the optimisation works)."""
    d = _frame(monkeypatch)

    _set(d, SMALL)
    d.content_ctrl.value = SMALL
    d.content_ctrl.SetValue = lambda v: (_ for _ in ()).throw(
        AssertionError("must not rewrite identical text")
    )

    _set(d, SMALL)
    assert d._reader_displayed_text == SMALL


def test_focus_cache_hit_preserves_reader_caret_and_selection(monkeypatch):
    """Returning focus to unchanged full text must not jump back to its top."""
    d = _frame(monkeypatch)

    _set(d, SMALL)
    d.content_ctrl.SetSelection(6, 17)

    # on_content_focus requests the cached body with reset_insertion=True each
    # time Tab navigation or an NVDA dialog returns focus to the classic view.
    _set(d, SMALL, reset_insertion=True)

    assert d.content_ctrl.GetSelection() == (6, 17)
    assert d.content_ctrl.GetInsertionPoint() == 17


def test_macos_async_result_replaces_reader_even_when_list_has_focus(monkeypatch):
    monkeypatch.setattr(mainframe.sys, "platform", "darwin")
    monkeypatch.setattr(mainframe, "notify_reader_content_changed", lambda *a, **k: True)
    d = _frame(monkeypatch)
    original = d.content_ctrl
    d._focus["cur"] = object()

    assert MF._replace_macos_async_reader(d, SMALL) is True

    assert d.content_ctrl is not original
    assert d.content_ctrl.value == SMALL
    assert d.content_ctrl.GetInsertionPoint() == 0
    assert d.content_ctrl.shown is True
    assert original.shown is False
