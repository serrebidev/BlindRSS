# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Smart Folders: rule engine (pure predicate), SQL compilation via the local
provider against a real SQLite DB, and folder CRUD."""
import pytest

from core import db
from core.smart_folders import rule_matches, build_where, describe_rule
from gui.mainframe import SmartFolderDialog
from providers.local import LocalProvider


# --------------------------------------------------------------------------
# Pure-Python predicate (rule_matches)
# --------------------------------------------------------------------------

def _art(**over):
    base = {
        "title": "", "content": "", "description": "", "author": "", "feed": "", "url": "",
        "read": False, "favorite": False, "opened": False, "updated": False,
    }
    base.update(over)
    return base


def test_empty_rule_matches_all():
    assert rule_matches({"match": "all", "conditions": []}, _art()) is True


def test_empty_any_group_matches_none():
    assert rule_matches({"match": "any", "conditions": []}, _art()) is False


def test_and_requires_all_conditions():
    rule = {"match": "all", "conditions": [
        {"field": "read", "op": "is", "value": False},
        {"field": "title", "op": "contains", "value": "python"},
    ]}
    assert rule_matches(rule, _art(title="Python News", read=False)) is True
    assert rule_matches(rule, _art(title="Python News", read=True)) is False
    assert rule_matches(rule, _art(title="Rust News", read=False)) is False


def test_or_requires_any_condition():
    rule = {"match": "any", "conditions": [
        {"field": "author", "op": "contains", "value": "alice"},
        {"field": "favorite", "op": "is", "value": True},
    ]}
    assert rule_matches(rule, _art(author="Alice Smith")) is True
    assert rule_matches(rule, _art(favorite=True)) is True
    assert rule_matches(rule, _art(author="Bob", favorite=False)) is False


def test_nested_and_or_groups():
    # (author = alice AND unread) OR (title contains rust)
    rule = {"match": "any", "conditions": [
        {"match": "all", "conditions": [
            {"field": "author", "op": "equals", "value": "alice"},
            {"field": "read", "op": "is", "value": False},
        ]},
        {"field": "title", "op": "contains", "value": "rust"},
    ]}
    assert rule_matches(rule, _art(author="alice", read=False)) is True   # left group
    assert rule_matches(rule, _art(title="Rust 101")) is True             # right leaf
    assert rule_matches(rule, _art(author="alice", read=True)) is False   # neither


def test_text_ops():
    assert rule_matches({"match": "all", "conditions": [{"field": "title", "op": "not_contains", "value": "ad"}]}, _art(title="News")) is True
    assert rule_matches({"match": "all", "conditions": [{"field": "title", "op": "not_contains", "value": "ad"}]}, _art(title="Advert")) is False
    assert rule_matches({"match": "all", "conditions": [{"field": "title", "op": "starts_with", "value": "the"}]}, _art(title="The Verge")) is True
    assert rule_matches({"match": "all", "conditions": [{"field": "author", "op": "equals", "value": "bob"}]}, _art(author="Bob")) is True


def test_unknown_field_is_skipped_not_matched():
    # An unknown leaf must be neutral in BOTH all and any (skipped), so an OR of
    # only-unknown conditions matches nothing.
    assert rule_matches({"match": "any", "conditions": [{"field": "bogus", "op": "is", "value": True}]}, _art()) is False
    # ...and an AND with a real + unknown condition depends only on the real one.
    rule = {"match": "all", "conditions": [
        {"field": "favorite", "op": "is", "value": True},
        {"field": "bogus", "op": "x", "value": 1},
    ]}
    assert rule_matches(rule, _art(favorite=True)) is True


def test_describe_rule_is_human_readable():
    rule = {"match": "any", "conditions": [
        {"field": "read", "op": "is", "value": False},
        {"field": "title", "op": "contains", "value": "python"},
    ]}
    text = describe_rule(rule)
    assert "unread" in text and "python" in text and " OR " in text


def test_smart_folder_dialog_uses_rule_engine_constants():
    assert SmartFolderDialog._TEXT_FIELDS == ("title", "content", "description", "author", "feed", "url", "tag")
    assert SmartFolderDialog._BOOL_MAP["opened_yes"] == ("opened", True)
    assert SmartFolderDialog._BOOL_MAP["updated_no"] == ("updated", False)


def test_build_where_shapes():
    sql, params = build_where({"match": "all", "conditions": [
        {"field": "read", "op": "is", "value": False},
        {"field": "favorite", "op": "is", "value": True},
    ]})
    assert "a.is_read = ?" in sql and "a.is_favorite = ?" in sql and " AND " in sql
    assert params == [0, 1]


# --------------------------------------------------------------------------
# SQL compilation validated end-to-end via the local provider + real SQLite
# --------------------------------------------------------------------------

@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    local = LocalProvider({"feed_timeout_seconds": 1, "feed_retry_attempts": 0})

    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO feeds (id, url, title, category) VALUES (?,?,?,?)", ("tech", "u1", "TechFeed", "Uncategorized"))
        conn.execute("INSERT INTO feeds (id, url, title, category) VALUES (?,?,?,?)", ("food", "u2", "FoodFeed", "Uncategorized"))
        rows = [
            # id, feed, title, author, is_read, is_favorite
            ("a1", "tech", "Python News", "Alice", 0, 0),
            ("a2", "tech", "Rust News", "Bob", 1, 1),
            ("a3", "food", "Cooking Tips", "Alice", 0, 0),
        ]
        for aid, feed, title, author, is_read, is_fav in rows:
            conn.execute(
                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (aid, feed, title, f"https://x/{aid}", "body", "2026-06-24 12:00:00", author, is_read, is_fav),
            )
        conn.commit()
    finally:
        conn.close()

    # a2 has been opened and updated (2 versions); a1/a3 have a single version.
    db.mark_article_opened("a2", opened_at=1000.0)
    db.record_article_version("a1", "Python News", "body")
    db.record_article_version("a3", "Cooking Tips", "body")
    db.record_article_version("a2", "Rust News", "body")
    db.record_article_version("a2", "Rust News", "body EDITED")
    return local


def _ids(provider, rule):
    fid = db.create_smart_folder("F", rule)
    page, total = provider.get_articles_page(f"smart:{fid}", offset=0, limit=100)
    assert total == len(page)
    return sorted(a.id for a in page)


def test_smart_query_title_contains(provider):
    assert _ids(provider, {"match": "all", "conditions": [{"field": "title", "op": "contains", "value": "news"}]}) == ["a1", "a2"]


def test_smart_query_unread(provider):
    assert _ids(provider, {"match": "all", "conditions": [{"field": "read", "op": "is", "value": False}]}) == ["a1", "a3"]


def test_smart_query_or_author_or_favorite(provider):
    rule = {"match": "any", "conditions": [
        {"field": "author", "op": "equals", "value": "bob"},
        {"field": "favorite", "op": "is", "value": True},
    ]}
    assert _ids(provider, rule) == ["a2"]


def test_smart_query_updated(provider):
    assert _ids(provider, {"match": "all", "conditions": [{"field": "updated", "op": "is", "value": True}]}) == ["a2"]


def test_smart_query_opened(provider):
    assert _ids(provider, {"match": "all", "conditions": [{"field": "opened", "op": "is", "value": True}]}) == ["a2"]


def test_smart_query_feed_equals(provider):
    assert _ids(provider, {"match": "all", "conditions": [{"field": "feed", "op": "equals", "value": "foodfeed"}]}) == ["a3"]


def test_smart_query_nested(provider):
    # (author = alice AND unread) OR (title contains rust) -> a1, a3, a2
    rule = {"match": "any", "conditions": [
        {"match": "all", "conditions": [
            {"field": "author", "op": "equals", "value": "alice"},
            {"field": "read", "op": "is", "value": False},
        ]},
        {"field": "title", "op": "contains", "value": "rust"},
    ]}
    assert _ids(provider, rule) == ["a1", "a2", "a3"]


def test_smart_query_not_contains_includes_null_and_empty(provider):
    # not_contains must include rows whose column is NULL/empty (no 'z' anywhere).
    assert _ids(provider, {"match": "all", "conditions": [{"field": "title", "op": "not_contains", "value": "zzz"}]}) == ["a1", "a2", "a3"]


def test_smart_query_text_match_is_unicode_case_insensitive(provider):
    # SQLite's built-in LOWER() only folds ASCII; the SQL path must use the
    # Unicode-aware py_lower so "ärger" matches "ÄRGER" like rule_matches does.
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("a4", "tech", "ÄRGER über alles", "https://x/a4", "body", "2026-06-24 12:00:00", "Über Author", 0, 0),
        )
        conn.commit()
    finally:
        conn.close()

    rule = {"match": "all", "conditions": [{"field": "title", "op": "contains", "value": "ärger"}]}
    assert _ids(provider, rule) == ["a4"]
    # The pure-Python mirror must agree.
    assert rule_matches(rule, _art(title="ÄRGER über alles")) is True

    rule_eq = {"match": "all", "conditions": [{"field": "author", "op": "equals", "value": "über author"}]}
    assert _ids(provider, rule_eq) == ["a4"]

    rule_sw = {"match": "all", "conditions": [{"field": "title", "op": "starts_with", "value": "ärger"}]}
    assert _ids(provider, rule_sw) == ["a4"]


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------

def test_smart_folder_crud(provider):
    fid = provider.create_smart_folder("Unread Python", {"match": "all", "conditions": [{"field": "title", "op": "contains", "value": "python"}]})
    folders = provider.get_smart_folders()
    assert any(f["id"] == fid and f["name"] == "Unread Python" for f in folders)

    assert provider.update_smart_folder(fid, name="Renamed") is True
    assert db.get_smart_folder(fid)["name"] == "Renamed"

    assert provider.delete_smart_folder(fid) is True
    assert db.get_smart_folder(fid) is None
