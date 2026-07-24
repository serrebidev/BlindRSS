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


def test_tab_titles_and_order_are_unchanged(parent):
    """Tab order is muscle memory and what a screen reader announces."""
    dlg = _dialog(parent)
    try:
        titles = [dlg.notebook.GetPageText(i) for i in range(dlg.notebook.GetPageCount())]
        assert titles == [
            "General",
            # Literal ampersands stay doubled; wx eats a lone '&' as a mnemonic
            # (issue #66), and GetPageText returns the stored text.
            "Feeds && Articles",
            "Downloads",
            "Startup && Tray",
            "YouTube",
            "Groups.io",
            "Media Player",
            "Provider",
            "Sounds",
            "Notifications",
            "Announcements",
            "Translate",
            "List Headers",
            "Advanced",
        ]
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
