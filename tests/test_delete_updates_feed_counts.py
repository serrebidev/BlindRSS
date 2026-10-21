# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Deleting articles must update the feed tree counts immediately.

Regression: the per-feed "(N)" unread label (and the category total and
tray total derived from the same feed_map counts) only changed at the next
refresh, so a feed emptied by hand kept showing e.g. "NVDA (126)" until a
Refresh Feed / Refresh All. _post_delete_articles now aggregates the unread
removals per feed and applies them through the same helper the mark-read
path uses (_update_feed_unread_count_ui via _note_articles_removed_from_feeds).

Follows the stand-in pattern of test_status_bar_activity.py: a plain host
object borrows the real unbound MainFrame methods, with fake tree/list/tray
controls recording what the real ones would show.
"""

import os
import sys
import threading
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _FakeNode:
    def IsOk(self):
        return True


class _FakeTree:
    def __init__(self):
        self.labels = {}

    def SetItemText(self, node, label):
        self.labels[node] = label

    def GetItemText(self, node):
        return self.labels.get(node, "")


class _FakeListCtrl:
    def Freeze(self):
        pass

    def Thaw(self):
        pass

    def DeleteItem(self, idx):
        pass

    def Select(self, idx):
        pass

    def Focus(self, idx):
        pass

    def EnsureVisible(self, idx):
        pass


class _FakeTray:
    def __init__(self):
        self.updates = []

    def update_status_label(self, unread_count=0, activity=""):
        self.updates.append(unread_count)
        return True


class _PlainProvider:
    """No _resolve_delete_behavior: every delete is a removal."""


class _MoveProvider:
    def _resolve_delete_behavior(self, feed_id):
        return "category:Archive"


class _DeleteHost:
    _post_delete_articles = mainframe.MainFrame._post_delete_articles
    _note_articles_removed_from_feeds = mainframe.MainFrame._note_articles_removed_from_feeds
    _update_feed_unread_count_ui = mainframe.MainFrame._update_feed_unread_count_ui
    _update_category_unread_chain_ui = mainframe.MainFrame._update_category_unread_chain_ui
    _total_unread_count_for_tray = mainframe.MainFrame._total_unread_count_for_tray
    _update_tray_status_label = mainframe.MainFrame._update_tray_status_label
    _is_deleted_view = mainframe.MainFrame._is_deleted_view
    _article_cache_id = mainframe.MainFrame._article_cache_id
    _remove_article_from_current_list = mainframe.MainFrame._remove_article_from_current_list
    _remove_article_from_cached_views = mainframe.MainFrame._remove_article_from_cached_views

    def __init__(self, provider=None):
        self.provider = provider if provider is not None else _PlainProvider()
        self.tree = _FakeTree()
        self.list_ctrl = _FakeListCtrl()
        self.tray_icon = _FakeTray()
        self._tray_activity_label = ""
        self._fulltext_cache = {}
        self._fulltext_cache_source = {}
        self.view_cache = {}
        self._view_cache_lock = threading.Lock()
        self.current_feed_id = "feed1"
        self._base_view_id = "feed1"
        self.empty_state_shown = False

        feed_node = _FakeNode()
        cat_node = _FakeNode()
        self.feed = SimpleNamespace(
            id="feed1", title="NVDA", category="Tech", unread_count=3
        )
        self.feed_map = {"feed1": self.feed}
        self.feed_nodes = {"feed1": feed_node}
        self.feed_node = feed_node
        self.cat_nodes = {"Tech": cat_node}
        self.cat_node = cat_node
        self.category_unread_totals = {"Tech": 3}
        self.category_base_labels = {"Tech": "Tech"}
        self._category_hierarchy = {}
        self.tree.labels[feed_node] = "NVDA (3)"
        self.tree.labels[cat_node] = "Tech (3)"

        self.articles = [
            SimpleNamespace(id="a1", cache_id="a1", feed_id="feed1", is_read=False, title="One"),
            SimpleNamespace(id="a2", cache_id="a2", feed_id="feed1", is_read=False, title="Two"),
            SimpleNamespace(id="a3", cache_id="a3", feed_id="feed1", is_read=True, title="Three"),
        ]
        self.current_articles = list(self.articles)
        self._base_articles = list(self.articles)

    def _clear_list_selection(self):
        pass

    def _show_empty_articles_state(self):
        self.empty_state_shown = True

    def feed_label(self):
        return self.tree.labels[self.feed_node]

    def cat_label(self):
        return self.tree.labels[self.cat_node]


def _results(host, articles, ok=True):
    return [(a.id, a.cache_id, f"key-{a.id}", ok, "") for a in articles]


def test_delete_unread_articles_drops_feed_category_and_tray_counts():
    host = _DeleteHost()
    # Delete the two unread articles; the read one stays.
    host._post_delete_articles(_results(host, host.articles[:2]), anchor_idx=0)
    assert host.feed.unread_count == 1
    assert host.feed_label() == "NVDA (1)"
    assert host.cat_label() == "Tech (1)"
    assert host.tray_icon.updates[-1] == 1


def test_delete_read_article_keeps_unread_count():
    host = _DeleteHost()
    host._post_delete_articles(_results(host, host.articles[2:]), anchor_idx=2)
    assert host.feed.unread_count == 3
    assert host.feed_label() == "NVDA (3)"
    assert host.cat_label() == "Tech (3)"


def test_delete_until_empty_clears_the_count_label():
    host = _DeleteHost()
    host.feed.unread_count = 2
    host.category_unread_totals["Tech"] = 2
    host.tree.labels[host.feed_node] = "NVDA (2)"
    host.tree.labels[host.cat_node] = "Tech (2)"
    arts = host.articles[:2]
    host.current_articles = list(arts)
    host._base_articles = list(arts)
    host._post_delete_articles(_results(host, arts), anchor_idx=0)
    assert host.empty_state_shown is True
    assert host.feed.unread_count == 0
    assert host.feed_label() == "NVDA"
    assert host.cat_label() == "Tech"
    assert host.tray_icon.updates[-1] == 0


def test_move_to_category_delete_keeps_feed_count():
    host = _DeleteHost(provider=_MoveProvider())
    host._post_delete_articles(_results(host, host.articles[:1]), anchor_idx=0)
    assert host.feed.unread_count == 3
    assert host.feed_label() == "NVDA (3)"


def test_purge_from_deleted_view_keeps_feed_count():
    host = _DeleteHost()
    host.current_feed_id = "deleted:all"
    host._post_delete_articles(_results(host, host.articles[:2]), anchor_idx=0)
    assert host.feed.unread_count == 3
    assert host.feed_label() == "NVDA (3)"


def test_failed_deletes_keep_feed_count():
    host = _DeleteHost()
    host._post_delete_articles(_results(host, host.articles[:2], ok=False), anchor_idx=0)
    assert host.feed.unread_count == 3
    assert host.feed_label() == "NVDA (3)"
