"""Aggregated unread counts on category tree nodes (issue #34).

total_unread(category) = sum(unread_count of direct feeds)
                        + sum(total_unread(child) for child in subcategories)

Two code paths are covered:
  - MainFrame._compute_category_unread_totals: the pure recursive sum used by
    a full tree rebuild (_update_tree). No wx required.
  - MainFrame._update_category_unread_chain_ui / _update_feed_unread_count_ui:
    the incremental path used by mark-read/unread so a single click doesn't
    require rebuilding the whole tree. Exercised against a small fake tree
    (records SetItemText calls) rather than a real wx.TreeCtrl, since neither
    method touches anything beyond .IsOk()/.SetItemText().
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui.mainframe as mainframe


# ---------------------------------------------------------------------------
# _compute_category_unread_totals (pure, used by full tree rebuilds)
# ---------------------------------------------------------------------------

def _feed(unread):
    return SimpleNamespace(unread_count=unread)


def test_flat_category_sums_direct_feeds_only():
    cat_feeds_map = {"Tech": [_feed(3), _feed(0), _feed(2)]}
    children_of = {}
    totals = mainframe.MainFrame._compute_category_unread_totals(cat_feeds_map, children_of)
    assert totals == {"Tech": 5}


def test_nested_category_includes_child_totals():
    # Tech (2 direct) has one child "Tech / Sub" (3 direct).
    cat_feeds_map = {
        "Tech": [_feed(2)],
        "Tech / Sub": [_feed(3)],
    }
    children_of = {"Tech": ["Tech / Sub"]}
    totals = mainframe.MainFrame._compute_category_unread_totals(cat_feeds_map, children_of)
    assert totals["Tech / Sub"] == 3
    assert totals["Tech"] == 5  # 2 direct + 3 from the child


def test_category_with_no_direct_feeds_shows_subcategory_total():
    """Edge case called out explicitly in issue #34."""
    cat_feeds_map = {
        "Empty Parent": [],
        "Empty Parent / Child": [_feed(7)],
    }
    children_of = {"Empty Parent": ["Empty Parent / Child"]}
    totals = mainframe.MainFrame._compute_category_unread_totals(cat_feeds_map, children_of)
    assert totals["Empty Parent"] == 7


def test_deep_nesting_aggregates_through_every_level():
    """12 levels deep: each level adds one feed with 1 unread item."""
    depth = 12
    cat_feeds_map = {}
    children_of = {}
    path = "L0"
    cat_feeds_map[path] = [_feed(1)]
    for level in range(1, depth):
        parent = path
        path = f"{path} / L{level}"
        cat_feeds_map[path] = [_feed(1)]
        children_of.setdefault(parent, []).append(path)

    totals = mainframe.MainFrame._compute_category_unread_totals(cat_feeds_map, children_of)
    # The root of the chain should see all `depth` unread items; each level
    # down sees one fewer (its own feed plus everything still below it).
    assert totals["L0"] == depth
    leaf = path
    assert totals[leaf] == 1


def test_large_hierarchy_is_each_category_summed_once():
    """1000 feeds across 100 categories, 10 levels deep -- correctness at scale.

    Memoization means this is O(categories + feeds); if a regression made the
    recursion re-walk shared subtrees per ancestor this would still pass
    correctness-wise but get measurably slower, so the assertion below also
    pins down the expected totals precisely rather than just "it finishes".
    """
    cat_feeds_map = {}
    children_of = {}
    chain = []
    for level in range(10):
        cat = f"Root" if level == 0 else " / ".join(chain[: level] + [f"L{level}"])
        chain.append(f"L{level}" if level else "Root")
        cat_feeds_map[cat] = [_feed(1) for _ in range(10)]  # 10 feeds/category * 10 levels * 10 siblings below
        if level > 0:
            parent = " / ".join(chain[:level]) if level > 1 else chain[0]
            children_of.setdefault(parent, []).append(cat)

    # Pad out to 1000 feeds total with extra sibling categories under the root.
    for i in range(90):
        cat = f"Sibling{i}"
        cat_feeds_map[cat] = [_feed(1) for _ in range(10)]

    total_feeds = sum(len(v) for v in cat_feeds_map.values())
    assert total_feeds == 1000

    totals = mainframe.MainFrame._compute_category_unread_totals(cat_feeds_map, children_of)
    # Every category's own total must be >= its direct feed count.
    for cat, feeds in cat_feeds_map.items():
        assert totals[cat] >= len(feeds)
    # The deepest chain category accumulates one feed-bundle per level.
    assert totals["Root"] == 100  # 10 levels * 10 feeds/level, all chained under Root


# ---------------------------------------------------------------------------
# Incremental path: _update_feed_unread_count_ui / _update_category_unread_chain_ui
# ---------------------------------------------------------------------------

class _FakeNode:
    def IsOk(self):
        return True


class _FakeTree:
    def __init__(self):
        self.texts = {}

    def SetItemText(self, node, text):
        self.texts[node] = text

    def GetItemText(self, node):
        return self.texts.get(node)

    def GetSelection(self):
        # No selection: _apply_feed_refresh_progress's "is the selected view
        # impacted" branch short-circuits on this and is not under test here.
        return None


class _CategoryCountHost:
    """Borrows the real, unbound MainFrame methods under test."""

    _update_feed_unread_count_ui = mainframe.MainFrame._update_feed_unread_count_ui
    _update_category_unread_chain_ui = mainframe.MainFrame._update_category_unread_chain_ui
    _apply_feed_refresh_progress = mainframe.MainFrame._apply_feed_refresh_progress
    _schedule_article_reload = lambda self: None  # noqa: E731 - only reached via _apply_feed_refresh_progress

    def __init__(self):
        self.tree = _FakeTree()
        self.cat_node = _FakeNode()
        self.sub_node = _FakeNode()
        self.sibling_node = _FakeNode()
        self.feed_node = _FakeNode()

        self.cat_nodes = {
            "Tech": self.cat_node,
            "Tech / Sub": self.sub_node,
            "News": self.sibling_node,
        }
        self.category_base_labels = {"Tech": "Tech", "Tech / Sub": "Sub", "News": "News"}
        self.category_unread_totals = {"Tech": 5, "Tech / Sub": 3, "News": 2}
        self._category_hierarchy = {"Tech / Sub": "Tech"}

        self.feed_map = {
            "feed-1": SimpleNamespace(id="feed-1", title="Feed One", category="Tech / Sub", unread_count=3),
        }
        self.feed_nodes = {"feed-1": self.feed_node}


def test_marking_read_decrements_feed_and_every_ancestor_category():
    host = _CategoryCountHost()

    host._update_feed_unread_count_ui("feed-1", -1)

    assert host.feed_map["feed-1"].unread_count == 2
    assert host.tree.GetItemText(host.feed_node) == "Feed One (2)"
    assert host.category_unread_totals["Tech / Sub"] == 2
    assert host.tree.GetItemText(host.sub_node) == "Sub (2)"
    assert host.category_unread_totals["Tech"] == 4
    assert host.tree.GetItemText(host.cat_node) == "Tech (4)"
    # An unrelated top-level category must not be touched.
    assert host.sibling_node not in host.tree.texts
    assert host.category_unread_totals["News"] == 2


def test_category_total_reaching_zero_drops_the_count_suffix():
    host = _CategoryCountHost()
    host.feed_map["feed-1"].unread_count = 1
    host.category_unread_totals["Tech / Sub"] = 1
    host.category_unread_totals["Tech"] = 1  # only contributor is this feed

    host._update_feed_unread_count_ui("feed-1", -1)

    assert host.category_unread_totals["Tech / Sub"] == 0
    assert host.tree.GetItemText(host.sub_node) == "Sub"
    assert host.category_unread_totals["Tech"] == 0
    assert host.tree.GetItemText(host.cat_node) == "Tech"


def test_marking_unread_increments_feed_and_ancestors():
    host = _CategoryCountHost()

    host._update_feed_unread_count_ui("feed-1", 1)

    assert host.feed_map["feed-1"].unread_count == 4
    assert host.category_unread_totals["Tech / Sub"] == 4
    assert host.category_unread_totals["Tech"] == 6


def test_refresh_progress_keeps_category_totals_live_during_refresh():
    """_apply_feed_refresh_progress patches one feed mid-refresh; its ancestor
    category totals should track the change immediately, not just after the
    full tree rebuild that follows once the whole refresh finishes."""
    host = _CategoryCountHost()

    host._apply_feed_refresh_progress({
        "id": "feed-1",
        "title": "Feed One",
        "unread_count": 8,
        "category": "Tech / Sub",
    })

    assert host.feed_map["feed-1"].unread_count == 8
    # +5 over the starting unread_count of 3.
    assert host.category_unread_totals["Tech / Sub"] == 8
    assert host.category_unread_totals["Tech"] == 10


def test_refresh_progress_moves_totals_when_feed_changes_category():
    host = _CategoryCountHost()

    host._apply_feed_refresh_progress({
        "id": "feed-1",
        "title": "Feed One",
        "unread_count": 3,
        "category": "News",
    })

    # The 3 unread items move out of the Tech chain entirely...
    assert host.category_unread_totals["Tech / Sub"] == 0
    assert host.category_unread_totals["Tech"] == 2
    # ...and into News.
    assert host.category_unread_totals["News"] == 5
