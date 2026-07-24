# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for the article-list column layout model (article list columns).

Covers the normalization contract (what survives round-tripping through config
or a feed_settings row), the Title pin, and the global-vs-per-feed resolution
that mirrors the per-feed refresh-interval override.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import article_columns as ac


def _keys(layout):
    return [e["key"] for e in layout]


def test_default_layout_matches_declared_order():
    assert _keys(ac.default_layout()) == list(ac.DEFAULT_ORDER)
    assert all(e["visible"] for e in ac.default_layout())


def test_normalize_drops_unknown_and_duplicate_keys():
    layout = ac.normalize_layout([
        {"key": "title", "visible": True},
        {"key": "feed", "visible": True},
        {"key": "feed", "visible": False},   # duplicate: first wins
        {"key": "bogus", "visible": True},   # unknown: dropped
    ])
    assert _keys(layout)[:2] == ["title", "feed"]
    assert "bogus" not in _keys(layout)
    assert _keys(layout).count("feed") == 1


def test_normalize_appends_columns_missing_from_a_stored_layout():
    """A layout saved before a column existed must gain it, not lose it."""
    layout = ac.normalize_layout([{"key": "title"}, {"key": "date"}])
    assert set(_keys(layout)) == set(ac.DEFAULT_ORDER)
    # The remembered part keeps its order; the rest follow in default order.
    assert _keys(layout)[:2] == ["title", "date"]


def test_normalize_rescues_garbage_input():
    for junk in (None, "nonsense", 42, [], [None, 7], {}):
        assert _keys(ac.normalize_layout(junk)) == list(ac.DEFAULT_ORDER)


def test_title_is_pinned_first_and_always_visible():
    layout = ac.normalize_layout([
        {"key": "feed", "visible": True},
        {"key": "title", "visible": False},  # tries to hide + demote Title
    ])
    assert layout[0]["key"] == "title"
    assert layout[0]["visible"] is True


def test_set_visible_hides_a_column_but_never_title():
    layout = ac.set_visible(ac.default_layout(), "media", False)
    assert "media" not in ac.visible_keys(layout)
    assert "media" in _keys(layout)  # still present, just not shown

    layout = ac.set_visible(layout, "title", False)
    assert "title" in ac.visible_keys(layout)


def test_move_key_reorders_and_clamps():
    # The user's case: hear the feed title before the author.
    layout = ac.move_key(ac.default_layout(), "feed", -3)
    assert _keys(layout).index("feed") < _keys(layout).index("author")

    # Cannot displace the pinned Title column at index 0.
    layout = ac.move_key(ac.default_layout(), "author", -5)
    assert _keys(layout)[0] == "title"
    assert _keys(layout)[1] == "author"

    # Clamps at the end rather than wrapping or raising.
    layout = ac.move_key(ac.default_layout(), "author", 99)
    assert _keys(layout)[-1] == "author"

    # Title itself never moves.
    assert _keys(ac.move_key(ac.default_layout(), "title", 3))[0] == "title"


def test_visible_keys_reflects_order_and_visibility():
    layout = ac.set_visible(ac.move_key(ac.default_layout(), "feed", -3), "media", False)
    keys = ac.visible_keys(layout)
    assert "media" not in keys
    assert keys.index("feed") < keys.index("author")
    assert keys[0] == "title"


def test_resolve_prefers_feed_override_and_falls_back_to_global():
    global_layout = ac.set_visible(ac.default_layout(), "description", False)
    feed_layout = ac.set_visible(ac.default_layout(), "media", False)

    # No override -> the global layout applies.
    assert ac.visible_keys(ac.resolve_layout(global_layout, None)) == ac.visible_keys(global_layout)
    # Override -> the feed's own layout wins outright (not merged).
    resolved = ac.resolve_layout(global_layout, feed_layout)
    assert "media" not in ac.visible_keys(resolved)
    assert "description" in ac.visible_keys(resolved)


def test_feed_layout_from_settings_reads_the_override_channel():
    # Absent / explicit-None / empty all mean "inherit the global layout".
    assert ac.feed_layout_from_settings({}) is None
    assert ac.feed_layout_from_settings({"columns": None}) is None
    assert ac.feed_layout_from_settings({"columns": []}) is None
    assert ac.feed_layout_from_settings(None) is None
    # A real override is normalized on the way out.
    layout = ac.feed_layout_from_settings({"columns": [{"key": "title"}, {"key": "feed"}]})
    assert _keys(layout)[:2] == ["title", "feed"]


def test_is_default_detects_an_untouched_layout():
    assert ac.is_default(ac.default_layout())
    assert ac.is_default(None)
    assert not ac.is_default(ac.set_visible(ac.default_layout(), "media", False))
