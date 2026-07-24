# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Global All/Unread/Read filter and category-tree pruning (issue #36).

The View > Article Filter setting must wrap every article view id with the
matching unread:/read: prefix and hide tree branches with no matching
articles — while leaving "all" mode byte-for-byte identical to the old
unfiltered tree.
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
    _tree_content_signatures = mainframe.MainFrame._tree_content_signatures
    _patch_tree_unread_labels = mainframe.MainFrame._patch_tree_unread_labels
    _apply_tree_expansion = mainframe.MainFrame._apply_tree_expansion
    _resolve_category_expanded = staticmethod(mainframe.MainFrame._resolve_category_expanded)
    _compute_category_unread_totals = staticmethod(mainframe.MainFrame._compute_category_unread_totals)
    _wrap_view_id_with_filter = mainframe.MainFrame._wrap_view_id_with_filter

    def __init__(self):
        super().__init__(None)
        self.provider = SimpleNamespace(get_feed_read_counts=lambda: self.read_counts)
        self.read_counts = {}
        self.config_manager = SimpleNamespace(get=lambda key, default=None: default)
        self.tree = wx.TreeCtrl(self, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT)
        self.root = self.tree.AddRoot("Root")
        self.all_feeds_node = self.tree.AppendItem(self.root, "All Articles")
        self._article_read_filter = "all"
        self._is_first_tree_load = True
        self._tree_structural_sig = None
        self._tree_counts_sig = None
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

    def _sync_unread_filter_menu_check(self):
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


FEEDS = [
    _feed("f1", "Busy Feed", "Tech", 2),
    _feed("f2", "Quiet Feed", "Tech", 0),
    _feed("f3", "Deep Feed", "Tech / Sub", 0),
    _feed("f4", "News Feed", "News", 0),
]
CATS = ["Tech", "Tech / Sub", "News", "Empty"]
HIERARCHY = {"Tech / Sub": "Tech"}


def test_all_mode_shows_everything_and_special_nodes_are_gone(host):
    host._update_tree(list(FEEDS), list(CATS), dict(HIERARCHY))

    assert set(host.feed_nodes) == {"f1", "f2", "f3", "f4"}
    assert set(host.cat_nodes) == {"Tech", "Tech / Sub", "News", "Empty"}

    # Dedicated Unread/Read Articles nodes were removed (issue #36).
    labels = []
    item, cookie = host.tree.GetFirstChild(host.root)
    while item.IsOk():
        labels.append(host.tree.GetItemText(item))
        item, cookie = host.tree.GetNextChild(host.root, cookie)
    assert "Unread Articles" not in labels
    assert "Read Articles" not in labels


def test_unread_mode_hides_feeds_and_categories_without_unread(host):
    host._article_read_filter = "unread"
    host._update_tree(list(FEEDS), list(CATS), dict(HIERARCHY))

    # Only the feed with unread articles remains; branches without unread
    # (News, Empty, the Tech / Sub subtree) are hidden.
    assert set(host.feed_nodes) == {"f1"}
    assert set(host.cat_nodes) == {"Tech"}


def test_read_mode_uses_provider_read_counts(host):
    host._article_read_filter = "read"
    host.read_counts = {"f3": 5, "f4": 1}
    host._update_tree(list(FEEDS), list(CATS), dict(HIERARCHY))

    assert set(host.feed_nodes) == {"f3", "f4"}
    # Tech stays visible because its subtree (Tech / Sub) has read articles.
    assert set(host.cat_nodes) == {"Tech", "Tech / Sub", "News"}


def test_read_mode_without_provider_support_shows_everything(host):
    host._article_read_filter = "read"
    host.provider = SimpleNamespace()  # no get_feed_read_counts
    host._update_tree(list(FEEDS), list(CATS), dict(HIERARCHY))

    assert set(host.feed_nodes) == {"f1", "f2", "f3", "f4"}


def test_wrap_view_id_applies_filter_prefix(host):
    host._article_read_filter = "all"
    assert host._wrap_view_id_with_filter("category:Tech") == "category:Tech"

    host._article_read_filter = "unread"
    assert host._wrap_view_id_with_filter("all") == "unread:all"
    assert host._wrap_view_id_with_filter("category:Tech") == "unread:category:Tech"
    assert host._wrap_view_id_with_filter("favorites:all") == "unread:favorites:all"
    # Smart Folders and the Deleted view keep their own semantics.
    assert host._wrap_view_id_with_filter("smart:abc") == "smart:abc"
    assert host._wrap_view_id_with_filter("deleted:all") == "deleted:all"
    # Never double-wrap.
    assert host._wrap_view_id_with_filter("unread:all") == "unread:all"

    host._article_read_filter = "read"
    assert host._wrap_view_id_with_filter("f1") == "read:f1"
    assert host._wrap_view_id_with_filter("read:all") == "read:all"


def test_unread_filter_compat_property():
    # Old code paths and tests still flip _unread_filter_enabled as a bool.
    host = SimpleNamespace(_article_read_filter="all")
    prop = mainframe.MainFrame._unread_filter_enabled
    assert prop.fget(host) is False
    prop.fset(host, True)
    assert host._article_read_filter == "unread"
    assert prop.fget(host) is True
    prop.fset(host, False)
    assert host._article_read_filter == "all"
