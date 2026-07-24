# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""DB-backed tests for the categorization feature: filter-rule storage, article
labels/moves, configurable delete behavior, and category-view membership."""
import pytest

from core import db
from core import filters
from providers.local import LocalProvider


FEED_ID = "feed-cat"
FEED2_ID = "feed-cat-2"


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    local = LocalProvider({"feed_timeout_seconds": 1, "feed_retry_attempts": 0, "delete_behavior": "deleted"})
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                     (FEED_ID, "https://example.com/a.xml", "Feed A", "News"))
        conn.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                     (FEED2_ID, "https://example.com/b.xml", "Feed B", "Tech"))
        for i in range(1, 4):
            conn.execute(
                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)",
                (f"a{i}", FEED_ID, f"Article {i}", f"https://example.com/a/{i}",
                 "body", f"2026-06-2{i} 10:00:00", "Author", "python" if i == 1 else ""),
            )
        conn.commit()
    finally:
        conn.close()
    return local


# ── filter_rules CRUD ────────────────────────────────────────────────────────

def test_filter_rule_crud_and_order(provider):
    r1 = db.create_filter_rule("First", {"match": "all", "conditions": []}, {"mark_read": True})
    r2 = db.create_filter_rule("Second", {"match": "all", "conditions": []}, {"label": "X"})

    rules = db.list_filter_rules()
    assert [r["id"] for r in rules] == [r1, r2]
    assert rules[0]["actions"]["mark_read"] is True

    db.update_filter_rule(r1, enabled=False, name="First-renamed")
    assert db.list_filter_rules(enabled_only=True) == [r for r in db.list_filter_rules() if r["id"] == r2]
    assert db.get_filter_rule(r1)["name"] == "First-renamed"

    db.reorder_filter_rules([r2, r1])
    assert [r["id"] for r in db.list_filter_rules()] == [r2, r1]

    assert db.delete_filter_rule(r1) is True
    assert db.get_filter_rule(r1) is None


# ── labels + category override ───────────────────────────────────────────────

def test_article_labels_roundtrip(provider):
    assert db.add_article_label("a2", "Tech / News") is True
    assert db.add_article_label("a2", "Tech / News") is True  # idempotent
    assert db.get_article_labels("a2") == ["Tech / News"]
    assert db.remove_article_label("a2", "Tech / News") is True
    assert db.get_article_labels("a2") == []


def test_category_override_moves_article_between_category_views(provider):
    # a1 lives in Feed A (category "News"). Move it to "Tech".
    assert db.set_article_category_override("a1", "Tech") is True

    news_ids = {a.id for a in provider.get_articles("category:News")}
    tech_ids = {a.id for a in provider.get_articles("category:Tech")}

    assert "a1" not in news_ids          # moved away from its feed's category
    assert "a1" in tech_ids              # now shows under Tech
    assert "a2" in news_ids and "a3" in news_ids


def test_label_adds_article_to_extra_category_view(provider):
    # a2 stays in News, but is ALSO labeled into Tech.
    db.add_article_label("a2", "Tech")
    news_ids = {a.id for a in provider.get_articles("category:News")}
    tech_ids = {a.id for a in provider.get_articles("category:Tech")}
    assert "a2" in news_ids   # still in its home category
    assert "a2" in tech_ids   # and appears under the label category


def test_category_page_count_matches_membership(provider):
    db.set_article_category_override("a1", "Tech")
    _page, total = provider.get_articles_page("category:News", 0, 50)
    assert total == 2  # a2, a3 (a1 moved out)


# ── delete behavior ──────────────────────────────────────────────────────────

def test_delete_behavior_purge_hides_from_deleted_view(provider):
    assert provider.delete_article("a1", behavior="purge") is True
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM articles WHERE id='a1'").fetchone()[0] == 0
        purged = conn.execute("SELECT purged FROM deleted_articles WHERE article_id='a1'").fetchone()[0]
        assert purged == 1  # tombstone kept (no resurrection) but hidden from Deleted view
    finally:
        conn.close()


def test_delete_behavior_category_moves_instead_of_removing(provider):
    assert provider.delete_article("a1", behavior="category:Archive") is True
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT category_override FROM articles WHERE id='a1'").fetchone()
        assert row is not None and row[0] == "Archive"   # still present, just refiled
        assert conn.execute("SELECT COUNT(*) FROM deleted_articles WHERE article_id='a1'").fetchone()[0] == 0
    finally:
        conn.close()
    assert "a1" in {a.id for a in provider.get_articles("category:Archive")}


def test_delete_behavior_resolves_per_feed_override(provider):
    db.set_feed_delete_behavior(FEED_ID, "purge")
    # No explicit behavior passed → provider resolves the per-feed override.
    assert provider.delete_article("a2") is True
    conn = db.get_connection()
    try:
        purged = conn.execute("SELECT purged FROM deleted_articles WHERE article_id='a2'").fetchone()[0]
        assert purged == 1
    finally:
        conn.close()


# ── apply_effective_actions against a real row ───────────────────────────────

def test_apply_effective_actions_writes_all_side_effects(provider):
    conn = db.get_connection()
    try:
        c = conn.cursor()
        eff = filters.resolve_effective_actions(
            {"move": "Moved", "labels": ["L1", "L2"], "mark_read": True, "mark_favorite": True},
            "deleted",
        )
        removed = filters.apply_effective_actions(c, "a3", eff)
        conn.commit()
        assert removed is False
        row = c.execute("SELECT is_read, is_favorite, category_override FROM articles WHERE id='a3'").fetchone()
        assert row == (1, 1, "Moved")
    finally:
        conn.close()
    assert set(db.get_article_labels("a3")) == {"L1", "L2"}


def test_apply_effective_actions_remove_tombstones_and_deletes(provider):
    conn = db.get_connection()
    try:
        c = conn.cursor()
        eff = filters.resolve_effective_actions({"delete": True}, "deleted")
        removed = filters.apply_effective_actions(c, "a1", eff, feed_id=FEED_ID)
        conn.commit()
        assert removed is True
        assert c.execute("SELECT COUNT(*) FROM articles WHERE id='a1'").fetchone()[0] == 0
    finally:
        conn.close()
    ids, _urls = db.deleted_article_tombstones_for_feed(FEED_ID)
    assert "a1" in ids  # refresh will not resurrect it
