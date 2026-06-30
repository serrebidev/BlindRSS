"""End-to-end check that MainFrame._update_tree renders aggregated category
unread counts correctly (issue #34) through the real wx.TreeCtrl widget.

tests/test_category_unread_counts.py covers the recursive-sum logic and the
incremental mark-read/unread path against fakes; this file exists to catch
wiring bugs between them -- e.g. the totals dict not actually reaching
_add_category_node, or the wrong label being stored as the base label --
that isolated unit tests using hand-built dicts would not notice.
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

wx = pytest.importorskip("wx")

import gui.mainframe as mainframe  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app


class _TreeHost(wx.Frame):
    _update_tree = mainframe.MainFrame._update_tree
    _apply_tree_expansion = mainframe.MainFrame._apply_tree_expansion
    _resolve_category_expanded = staticmethod(mainframe.MainFrame._resolve_category_expanded)
    _compute_category_unread_totals = staticmethod(mainframe.MainFrame._compute_category_unread_totals)
    _update_feed_unread_count_ui = mainframe.MainFrame._update_feed_unread_count_ui
    _update_category_unread_chain_ui = mainframe.MainFrame._update_category_unread_chain_ui

    def __init__(self):
        super().__init__(None)
        self.provider = None
        self.config_manager = SimpleNamespace(get=lambda key, default=None: default)
        self.tree = wx.TreeCtrl(self, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT)
        self.root = self.tree.AddRoot("Root")
        self.all_feeds_node = self.tree.AppendItem(self.root, "All Articles")
        self._is_first_tree_load = True
        self._expanded_categories = set()
        self._collapsed_categories = set()
        self._selection_hint = None
        self._updating_tree = False
        self._accessible_browser = None
        self.feed_map = {}
        self.feed_nodes = {}
        self.cat_nodes = {}
        self.category_base_labels = {}
        self.category_unread_totals = {}
        self._category_hierarchy = {}

    def _reload_selected_articles(self):
        pass


@pytest.fixture
def host(wx_app):
    frame = _TreeHost()
    yield frame
    try:
        frame.Destroy()
    except Exception:
        pass


def _feed(feed_id, title, category, unread):
    return SimpleNamespace(id=feed_id, title=title, url="", category=category, unread_count=unread, icon_url=None)


def test_update_tree_renders_recursive_totals_through_real_tree(host):
    feeds = [
        _feed("f1", "Tech Feed", "Tech", 2),
        _feed("f2", "Sub Feed", "Tech / Sub", 3),
        _feed("f3", "Deep Feed", "Tech / Sub / Deep", 1),
        _feed("f4", "Quiet Feed", "News", 0),
    ]
    all_cats = ["Tech", "Tech / Sub", "Tech / Sub / Deep", "News"]
    hierarchy = {
        "Tech / Sub": "Tech",
        "Tech / Sub / Deep": "Tech / Sub",
    }

    host._update_tree(feeds, all_cats, hierarchy)

    assert host.tree.GetItemText(host.cat_nodes["Tech / Sub / Deep"]) == "Deep (1)"
    assert host.tree.GetItemText(host.cat_nodes["Tech / Sub"]) == "Sub (4)"
    assert host.tree.GetItemText(host.cat_nodes["Tech"]) == "Tech (6)"
    # Zero-total category shows the bare label, same as a feed with 0 unread.
    assert host.tree.GetItemText(host.cat_nodes["News"]) == "News"

    # Supporting state needed by the incremental mark-read/unread path must
    # be populated from this same rebuild.
    assert host.category_unread_totals["Tech"] == 6
    assert host._category_hierarchy == hierarchy
    assert host.category_base_labels["Tech / Sub"] == "Sub"


def test_update_tree_then_incremental_mark_read_stay_consistent(host):
    """A full rebuild followed by the incremental path must agree -- this is
    what a real refresh-then-click sequence looks like in the app."""
    feeds = [
        _feed("f1", "Tech Feed", "Tech", 2),
        _feed("f2", "Sub Feed", "Tech / Sub", 3),
    ]
    all_cats = ["Tech", "Tech / Sub"]
    hierarchy = {"Tech / Sub": "Tech"}
    host._update_tree(feeds, all_cats, hierarchy)
    assert host.tree.GetItemText(host.cat_nodes["Tech"]) == "Tech (5)"

    host._update_feed_unread_count_ui("f2", -1)

    assert host.tree.GetItemText(host.feed_nodes["f2"]) == "Sub Feed (2)"
    assert host.tree.GetItemText(host.cat_nodes["Tech / Sub"]) == "Sub (2)"
    assert host.tree.GetItemText(host.cat_nodes["Tech"]) == "Tech (4)"
