# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Pure-logic tests for the Filter Rules categorization engine (core.filters).

These exercise the pipeline evaluation, action normalization, and delete-behavior
resolution without any database — see test_filter_pipeline_db.py for the wired,
DB-backed behavior.
"""
from core import filters
from core import smart_folders as sf


def _rule(rid, condition, actions, *, enabled=True, stop=False):
    return {"id": rid, "rule": condition, "actions": actions, "enabled": enabled, "stop": stop}


def _contains(field, value):
    return {"match": "all", "conditions": [{"field": field, "op": "contains", "value": value}]}


# ── normalize / describe / empties ───────────────────────────────────────────

def test_normalize_actions_coerces_types_and_blanks():
    a = filters.normalize_actions({"move": "  Tech  ", "label": "", "mark_read": "yes", "delete": 0})
    assert a["move"] == "Tech"
    assert a["label"] is None
    assert a["mark_read"] is True
    assert a["delete"] is False
    assert a["mark_favorite"] is False
    assert a["skip_notification"] is False


def test_actions_are_empty():
    assert filters.actions_are_empty({}) is True
    assert filters.actions_are_empty({"move": "", "mark_read": False}) is True
    assert filters.actions_are_empty({"mark_read": True}) is False
    assert filters.actions_are_empty({"label": "News"}) is False


def test_describe_actions_is_readable():
    text = filters.describe_actions({"move": "Tech", "mark_read": True, "skip_notification": True})
    assert 'move to "Tech"' in text
    assert "mark as read" in text
    assert "skip notification" in text
    assert filters.describe_actions({}) == "do nothing"


# ── evaluate_pipeline ────────────────────────────────────────────────────────

def _article(**over):
    base = {
        "title": "", "content": "", "description": "", "author": "",
        "feed": "", "url": "", "tag": "",
        "read": False, "favorite": False, "opened": False, "updated": False,
    }
    base.update(over)
    return base


def test_pipeline_no_rules_matches_nothing():
    agg = filters.evaluate_pipeline([], _article(title="hello"))
    assert agg["matched_rule_ids"] == []
    assert agg["move"] is None and agg["labels"] == []


def test_pipeline_applies_matching_rule_actions():
    rules = [_rule("r1", _contains("author", "sagan"), {"move": "Science", "mark_read": True})]
    agg = filters.evaluate_pipeline(rules, _article(author="Carl Sagan"))
    assert agg["matched_rule_ids"] == ["r1"]
    assert agg["move"] == "Science"
    assert agg["mark_read"] is True


def test_pipeline_skips_disabled_rules():
    rules = [_rule("r1", _contains("title", "x"), {"mark_read": True}, enabled=False)]
    agg = filters.evaluate_pipeline(rules, _article(title="xylophone"))
    assert agg["matched_rule_ids"] == []


def test_pipeline_stop_flag_halts_later_rules():
    rules = [
        _rule("r1", _contains("title", "news"), {"label": "A"}, stop=True),
        _rule("r2", _contains("title", "news"), {"label": "B"}),
    ]
    agg = filters.evaluate_pipeline(rules, _article(title="news today"))
    assert agg["matched_rule_ids"] == ["r1"]
    assert agg["labels"] == ["A"]  # r2 never runs


def test_pipeline_move_last_wins_labels_union_bools_or():
    rules = [
        _rule("r1", _contains("title", "a"), {"move": "First", "label": "L1", "mark_read": True}),
        _rule("r2", _contains("title", "a"), {"move": "Second", "label": "L2", "mark_favorite": True}),
        _rule("r3", _contains("title", "a"), {"label": "L1"}),  # duplicate label ignored
    ]
    agg = filters.evaluate_pipeline(rules, _article(title="aardvark"))
    assert agg["matched_rule_ids"] == ["r1", "r2", "r3"]
    assert agg["move"] == "Second"          # last matching move wins
    assert agg["labels"] == ["L1", "L2"]    # union, first-seen order, deduped
    assert agg["mark_read"] is True and agg["mark_favorite"] is True


def test_pipeline_matches_on_site_tag():
    rules = [_rule("r1", _contains("tag", "python"), {"label": "Dev"})]
    agg = filters.evaluate_pipeline(rules, _article(tag="Python\nProgramming"))
    assert agg["labels"] == ["Dev"]


# ── delete behavior ──────────────────────────────────────────────────────────

def test_parse_delete_behavior():
    assert filters.parse_delete_behavior(None) == ("deleted", None)
    assert filters.parse_delete_behavior("") == ("deleted", None)
    assert filters.parse_delete_behavior("deleted") == ("deleted", None)
    assert filters.parse_delete_behavior("purge") == ("purge", None)
    assert filters.parse_delete_behavior("category:Tech / News") == ("category", "Tech / News")
    assert filters.parse_delete_behavior("category:") == ("deleted", None)  # empty target
    assert filters.parse_delete_behavior("nonsense") == ("deleted", None)


def test_resolve_effective_soft_delete_default():
    agg = {"delete": True}
    eff = filters.resolve_effective_actions(agg, "deleted")
    assert eff["remove"] is True and eff["purge"] is False
    assert filters.effective_removes_article(eff) is True


def test_resolve_effective_purge():
    eff = filters.resolve_effective_actions({"delete": True}, "purge")
    assert eff["purge"] is True and eff["remove"] is False


def test_resolve_effective_delete_to_category_becomes_move():
    # A rule that deletes, under a "move to category" behavior, refiles instead
    # of removing — and delete-to-category overrides an explicit move.
    eff = filters.resolve_effective_actions({"delete": True, "move": "Ignored"}, "category:Archive")
    assert eff["move"] == "Archive"
    assert eff["remove"] is False and eff["purge"] is False
    assert filters.effective_removes_article(eff) is False


def test_resolve_effective_without_delete_passes_through():
    eff = filters.resolve_effective_actions({"move": "Tech", "labels": ["L1"], "mark_read": True}, "purge")
    assert eff["move"] == "Tech" and eff["labels"] == ["L1"]
    assert eff["remove"] is False and eff["purge"] is False


# ── smart_folders tag field integration ──────────────────────────────────────

def test_smart_folders_build_where_supports_tag_column():
    sql, params = sf.build_where(_contains("tag", "python"))
    assert "a.tags" in sql
    assert params == ["%python%"]


def test_smart_folders_rule_matches_tag():
    assert sf.rule_matches(_contains("tag", "python"), {"tags": "Python", "tag": "Python"}) is True
