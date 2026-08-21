# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Settings notebook pages build on first view (open time 1.2s -> ~0.3s).

The dangerous failure mode is not a slow dialog but a silent one: get_data()
reads controls from every page, so a page the user never opened must still be
realised before it is read. Otherwise those settings would be written back as
defaults and the user would lose them without any error.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

wx = pytest.importorskip("wx")

import gui.dialogs as dialogs  # noqa: E402
from core.config import ConfigManager  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app


@pytest.fixture
def parent(wx_app):
    frame = wx.Frame(None)
    yield frame
    try:
        frame.Destroy()
    except Exception:
        pass


def _dialog(parent):
    return dialogs.SettingsDialog(parent, ConfigManager().config, notification_feeds=[])


def test_pages_are_deferred_at_open(parent):
    dlg = _dialog(parent)
    try:
        assert dlg._lazy_pages, "expected some pages to be deferred"
    finally:
        dlg.Destroy()


def test_tab_titles_and_order(parent):
    """Tab order is muscle memory and what a screen reader announces.

    Five thin tabs became labelled groups on the page they belong to; the
    surviving tabs keep their previous relative order.
    """
    dlg = _dialog(parent)
    try:
        # wxMSW preserves escaped ampersands while wxOSX returns the rendered
        # label. Normalize both to what the screen reader announces.
        titles = [
            dlg.notebook.GetPageText(i).replace("&&", "&")
            for i in range(dlg.notebook.GetPageCount())
        ]
        assert titles == [
            "General",
            "Feeds & Articles",
            "YouTube",
            "Media Player",
            "Provider",
            "Notifications",
            "Translate",
            "List Headers",
            "Advanced",
            # Opt-in paid solver settings (tier-4 challenge escalation).
            # Appended last so no existing tab's Ctrl+Tab position moves.
            "CAPTCHA Solving",
        ]
    finally:
        dlg.Destroy()


def test_absorbed_sections_reuse_their_original_labels(parent):
    """Merged-away tabs survive as StaticBox groups under the SAME string.

    Reusing the existing msgid is what keeps this change free of translation
    debt: every locale already has these words.
    """
    dlg = _dialog(parent)
    try:
        dlg._ensure_all_pages_built()

        labels = set()

        def collect(window):
            for child in window.GetChildren():
                if isinstance(child, wx.StaticBox):
                    # wxMSW keeps the literal "&&"; wxOSX collapses it.
                    labels.add(child.GetLabel().replace("&&", "&"))
                collect(child)

        for i in range(dlg.notebook.GetPageCount()):
            collect(dlg.notebook.GetPage(i))

        for expected in ("Startup & Tray", "Downloads", "Sounds", "Announcements", "Groups.io"):
            assert expected in labels, f"missing group for absorbed tab: {expected}"
    finally:
        dlg.Destroy()


def test_get_data_builds_every_page_before_reading(parent):
    """The invariant that keeps lazy pages from silently resetting settings."""
    dlg = _dialog(parent)
    try:
        assert dlg._lazy_pages
        data = dlg.get_data()
        assert dlg._lazy_pages == {}, "get_data must leave no page unbuilt"
        assert data
    finally:
        dlg.Destroy()


def test_lazy_and_eager_get_data_agree(parent):
    """Deferring construction must not change a single saved value."""
    lazy_dlg = _dialog(parent)
    try:
        lazy = lazy_dlg.get_data()
    finally:
        lazy_dlg.Destroy()

    eager_dlg = _dialog(parent)
    try:
        eager_dlg._ensure_all_pages_built()
        eager = eager_dlg.get_data()
    finally:
        eager_dlg.Destroy()

    assert set(lazy) == set(eager)
    differing = {k: (lazy[k], eager[k]) for k in lazy if lazy[k] != eager[k]}
    assert differing == {}


def test_selecting_a_page_builds_it(parent):
    dlg = _dialog(parent)
    try:
        pending = len(dlg._lazy_pages)
        assert pending
        target = next(
            i for i in range(dlg.notebook.GetPageCount())
            if dlg.notebook.GetPage(i) in dlg._lazy_pages
        )
        dlg.notebook.SetSelection(target)
        # SetSelection fires EVT_NOTEBOOK_PAGE_CHANGED, which builds the page.
        assert len(dlg._lazy_pages) < pending
    finally:
        dlg.Destroy()


def test_opens_on_the_first_tab(parent):
    """Settings must open on General.

    It used to end up announcing the second tab: the notebook displayed page 0
    while __init__ focused self.refresh_ctrl, which lives on "Feeds &
    Articles". The notebook shows one thing, the screen reader says another.
    """
    dlg = _dialog(parent)
    try:
        assert dlg.notebook.GetSelection() == 0
        assert dlg.notebook.GetPageText(0) == "General"

        # Selection alone was never the bug - it was already 0. Focus is what a
        # screen reader follows, so assert where focus actually lands.
        dlg.Show()
        try:
            dlg._focus_notebook()
            for _ in range(10):
                wx.Yield()
            focused = wx.Window.FindFocus()
            pages = {dlg.notebook.GetPage(i): i for i in range(dlg.notebook.GetPageCount())}
            window, page = focused, None
            while window is not None:
                if window in pages:
                    page = pages[window]
                    break
                window = window.GetParent()
            # wxOSX reports no focused wx window when the test process itself
            # is not the active application. That is not an off-page focus.
            if focused is not None:
                assert focused is dlg.notebook or page == 0, (
                    f"focus landed on page {page} instead of General"
                )
        finally:
            dlg.Hide()
    finally:
        dlg.Destroy()


def test_no_notebook_child_is_missing_from_the_tabs(parent):
    """Every child of the notebook must be a real page.

    The Downloads panel is built before the page that hosts it exists; parenting
    it to the notebook put an untabbed panel in the page area and in focus
    traversal.
    """
    dlg = _dialog(parent)
    try:
        pages = {dlg.notebook.GetPage(i) for i in range(dlg.notebook.GetPageCount())}
        strays = [c for c in dlg.notebook.GetChildren() if c not in pages]
        assert strays == []
    finally:
        dlg.Destroy()


def test_prebuild_drains_the_pending_pages(parent):
    """OK must not pay to build pages the user never opened.

    Deferring construction moved ~870ms from opening the dialog to pressing OK.
    The prebuild pass fills them in beforehand; this drives it directly rather
    than waiting on timers.
    """
    dlg = _dialog(parent)
    try:
        assert dlg._lazy_pages
        guard = 0
        while dlg._lazy_pages and guard < 50:
            dlg._prebuild_pending_pages()
            guard += 1
        assert dlg._lazy_pages == {}
    finally:
        dlg.Destroy()


def test_focus_notebook_survives_a_destroyed_dialog(parent):
    """The deferred focus call must not raise after the dialog is gone."""
    dlg = _dialog(parent)
    dlg.Destroy()
    dlg._focus_notebook()  # must not raise RuntimeError


def test_a_failing_builder_is_retried_not_abandoned(parent):
    """A page that blew up once must not be left permanently blank."""
    dlg = _dialog(parent)
    try:
        panel = next(iter(dlg._lazy_pages))
        calls = {"n": 0}

        def boom(p, s):
            calls["n"] += 1
            raise RuntimeError("builder failed")

        dlg._lazy_pages[panel] = boom
        assert dlg._build_page_if_needed(panel) is False
        assert panel in dlg._lazy_pages, "failed page must stay pending for a retry"
        dlg._build_page_if_needed(panel)
        assert calls["n"] == 2
    finally:
        dlg.Destroy()
