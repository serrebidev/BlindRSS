# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for subcategory (nested category) support."""

import os
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.db as db_mod
from core import utils
from core.models import Feed
from providers.local import LocalProvider


def _setup_db(tmp_dir):
    orig = db_mod.DB_FILE
    db_mod.DB_FILE = os.path.join(tmp_dir, "rss.db")
    db_mod.init_db()
    conn = db_mod.get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM chapters")
        c.execute("DELETE FROM articles")
        c.execute("DELETE FROM feeds")
        c.execute("DELETE FROM categories")
        conn.commit()
    finally:
        conn.close()
    return orig


def _restore_db(orig):
    db_mod.DB_FILE = orig


# ── DB helper tests ──────────────────────────────────────────────────────


def test_init_db_creates_parent_id_column():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            conn = db_mod.get_connection()
            c = conn.cursor()
            c.execute("PRAGMA table_info(categories)")
            cols = {row[1] for row in c.fetchall()}
            conn.close()
            assert "parent_id" in cols
        finally:
            _restore_db(orig)


def test_sync_categories_inserts_missing():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            db_mod.sync_categories(["Alpha", "Beta"])
            conn = db_mod.get_connection()
            c = conn.cursor()
            c.execute("SELECT title FROM categories ORDER BY title")
            titles = [r[0] for r in c.fetchall()]
            conn.close()
            assert "Alpha" in titles
            assert "Beta" in titles
        finally:
            _restore_db(orig)


def test_sync_categories_does_not_duplicate():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            db_mod.sync_categories(["Alpha"])
            db_mod.sync_categories(["Alpha", "Beta"])
            conn = db_mod.get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM categories WHERE title = 'Alpha'")
            assert c.fetchone()[0] == 1
            conn.close()
        finally:
            _restore_db(orig)


def test_set_and_get_category_hierarchy():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            db_mod.sync_categories(["Parent", "Child"])
            db_mod.set_category_parent("Child", "Parent")
            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Child") == "Parent"
            assert hierarchy.get("Parent") is None
        finally:
            _restore_db(orig)


def test_get_subcategory_titles_recursive():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            db_mod.sync_categories(["Root", "Mid", "Leaf"])
            db_mod.set_category_parent("Mid", "Root")
            db_mod.set_category_parent("Leaf", "Mid")
            subs = db_mod.get_subcategory_titles("Root")
            assert set(subs) == {"Mid", "Leaf"}
        finally:
            _restore_db(orig)


def test_get_subcategory_titles_empty_for_leaf():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            db_mod.sync_categories(["Root", "Child"])
            db_mod.set_category_parent("Child", "Root")
            subs = db_mod.get_subcategory_titles("Child")
            assert subs == []
        finally:
            _restore_db(orig)


def test_get_subcategory_titles_nonexistent_category():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            subs = db_mod.get_subcategory_titles("NoSuchCategory")
            assert subs == []
        finally:
            _restore_db(orig)


# ── Local provider tests ─────────────────────────────────────────────────


def _make_provider(tmp_dir):
    return LocalProvider({
        "providers": {"local": {}},
        "max_concurrent_refreshes": 1,
        "per_host_max_connections": 1,
        "feed_timeout_seconds": 10,
        "feed_retry_attempts": 0,
    })


def test_local_add_category_with_parent():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Parent")
            provider.add_category("Child", parent_title="Parent")
            # Nested categories are identified by their full path.
            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Parent / Child") == "Parent"
            assert "Child" not in hierarchy
        finally:
            _restore_db(orig)


def test_local_add_category_without_parent():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("TopLevel")
            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("TopLevel") is None
        finally:
            _restore_db(orig)


def test_local_delete_category_reparents_children():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Grandparent")
            provider.add_category("Parent", parent_title="Grandparent")
            provider.add_category("Child", parent_title="Grandparent / Parent")

            provider.delete_category("Grandparent / Parent")

            hierarchy = db_mod.get_category_hierarchy()
            # Child should now be directly under Grandparent (path shortened).
            assert hierarchy.get("Grandparent / Child") == "Grandparent"
            assert "Grandparent / Parent" not in hierarchy
            assert "Grandparent / Parent / Child" not in hierarchy
        finally:
            _restore_db(orig)


def test_local_delete_toplevel_category_children_become_toplevel():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Parent")
            provider.add_category("Child", parent_title="Parent")

            provider.delete_category("Parent")

            hierarchy = db_mod.get_category_hierarchy()
            # Child should now be top-level: its path collapses to just "Child".
            assert "Child" in hierarchy
            assert hierarchy.get("Child") is None
            assert "Parent / Child" not in hierarchy
        finally:
            _restore_db(orig)


def test_local_articles_include_subcategory_feeds():
    """When viewing a parent category, articles from subcategory feeds should be included."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("News")
            provider.add_category("Tech News", parent_title="News")

            conn = db_mod.get_connection()
            c = conn.cursor()
            # Insert feeds in parent and child categories
            feed1_id = str(uuid.uuid4())
            feed2_id = str(uuid.uuid4())
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (feed1_id, "http://example.com/news", "General News", "News"))
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (feed2_id, "http://example.com/tech", "Tech News Feed", "News / Tech News"))
            # Insert articles
            c.execute("INSERT INTO articles (id, feed_id, title, url, date) VALUES (?, ?, ?, ?, ?)",
                      ("a1", feed1_id, "News Article", "http://example.com/1", "2025-01-01 00:00:00"))
            c.execute("INSERT INTO articles (id, feed_id, title, url, date) VALUES (?, ?, ?, ?, ?)",
                      ("a2", feed2_id, "Tech Article", "http://example.com/2", "2025-01-02 00:00:00"))
            conn.commit()
            conn.close()

            # Viewing "News" category should include both articles
            articles, total = provider.get_articles_page("category:News")
            titles = {a.title for a in articles}
            assert "News Article" in titles
            assert "Tech Article" in titles
            assert total == 2
        finally:
            _restore_db(orig)


def test_local_articles_only_direct_feeds_when_no_children():
    """A category with no subcategories should only show its own feeds."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("News")
            provider.add_category("Sports")

            conn = db_mod.get_connection()
            c = conn.cursor()
            feed1_id = str(uuid.uuid4())
            feed2_id = str(uuid.uuid4())
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (feed1_id, "http://example.com/news", "News Feed", "News"))
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (feed2_id, "http://example.com/sports", "Sports Feed", "Sports"))
            c.execute("INSERT INTO articles (id, feed_id, title, url, date) VALUES (?, ?, ?, ?, ?)",
                      ("a1", feed1_id, "News Article", "http://example.com/1", "2025-01-01 00:00:00"))
            c.execute("INSERT INTO articles (id, feed_id, title, url, date) VALUES (?, ?, ?, ?, ?)",
                      ("a2", feed2_id, "Sports Article", "http://example.com/2", "2025-01-02 00:00:00"))
            conn.commit()
            conn.close()

            articles, total = provider.get_articles_page("category:News")
            assert total == 1
            assert articles[0].title == "News Article"
        finally:
            _restore_db(orig)


def test_local_mark_all_read_includes_subcategories():
    """mark_all_read on a parent category should mark subcategory articles too."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("News")
            provider.add_category("Tech", parent_title="News")

            conn = db_mod.get_connection()
            c = conn.cursor()
            feed1_id = str(uuid.uuid4())
            feed2_id = str(uuid.uuid4())
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (feed1_id, "http://example.com/news", "News", "News"))
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (feed2_id, "http://example.com/tech", "Tech", "News / Tech"))
            c.execute("INSERT INTO articles (id, feed_id, title, url, date, is_read) VALUES (?, ?, ?, ?, ?, 0)",
                      ("a1", feed1_id, "News Art", "http://example.com/1", "2025-01-01 00:00:00"))
            c.execute("INSERT INTO articles (id, feed_id, title, url, date, is_read) VALUES (?, ?, ?, ?, ?, 0)",
                      ("a2", feed2_id, "Tech Art", "http://example.com/2", "2025-01-02 00:00:00"))
            conn.commit()
            conn.close()

            provider.mark_all_read("category:News")

            conn = db_mod.get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM articles WHERE is_read = 0")
            unread = c.fetchone()[0]
            conn.close()
            assert unread == 0
        finally:
            _restore_db(orig)


# ── OPML export with subcategories ────────────────────────────────────────


def test_collect_category_feeds_for_export_includes_subcategory_feeds():
    """OPML category export should include feeds from subcategories."""
    import gui.mainframe as mainframe

    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            db_mod.sync_categories(["Podcasts", "Tech Pods"])
            db_mod.set_category_parent("Tech Pods", "Podcasts")

            class _ProviderStub:
                def get_feeds(self):
                    return [
                        Feed(id="1", title="P1", url="http://a.xml", category="Podcasts"),
                        Feed(id="2", title="T1", url="http://b.xml", category="Tech Pods"),
                        Feed(id="3", title="N1", url="http://c.xml", category="News"),
                    ]

            class _Host:
                _normalize_category_title_for_export = mainframe.MainFrame._normalize_category_title_for_export
                _collect_category_feeds_for_export = mainframe.MainFrame._collect_category_feeds_for_export

                def __init__(self):
                    self.provider = _ProviderStub()

            host = _Host()
            feeds = host._collect_category_feeds_for_export("Podcasts")
            ids = {f.id for f in feeds}
            assert ids == {"1", "2"}
        finally:
            _restore_db(orig)


def test_local_import_opml_preserves_nested_category_paths():
    """Issue #28: standard nested OPML outlines should import as nested categories."""
    opml = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="GitHub">
      <outline text="BlindRSS">
        <outline text="Commits" xmlUrl="https://github.com/serrebidev/BlindRSS/commits/main.atom" />
        <outline text="Releases" xmlUrl="https://github.com/serrebidev/BlindRSS/releases.atom" />
        <outline text="Tags" xmlUrl="https://github.com/serrebidev/BlindRSS/tags.atom" />
      </outline>
    </outline>
  </body>
</opml>
"""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            opml_path = os.path.join(tmp, "feeds.opml")
            with open(opml_path, "w", encoding="utf-8") as f:
                f.write(opml)

            assert provider.import_opml(opml_path) is True

            feeds = sorted(provider.get_feeds(), key=lambda feed: feed.title)
            assert [feed.title for feed in feeds] == ["Commits", "Releases", "Tags"]
            assert {feed.category for feed in feeds} == {"GitHub / BlindRSS"}

            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("GitHub") is None
            assert hierarchy.get("GitHub / BlindRSS") == "GitHub"
            assert "BlindRSS" not in hierarchy
        finally:
            _restore_db(orig)


def test_local_import_opml_keeps_duplicate_leaf_folders_isolated():
    """Issue #28: duplicate leaf folder names under different parents must not collide."""
    opml = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="Podcasts">
      <outline text="Others">
        <outline text="Pod Feed" xmlUrl="https://example.com/pod.xml" />
      </outline>
    </outline>
    <outline text="RSS">
      <outline text="Others">
        <outline text="RSS Feed" xmlUrl="https://example.com/rss.xml" />
      </outline>
    </outline>
  </body>
</opml>
"""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            opml_path = os.path.join(tmp, "feeds.opml")
            with open(opml_path, "w", encoding="utf-8") as f:
                f.write(opml)

            assert provider.import_opml(opml_path) is True

            categories = {feed.title: feed.category for feed in provider.get_feeds()}
            assert categories == {
                "Pod Feed": "Podcasts / Others",
                "RSS Feed": "RSS / Others",
            }
            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Podcasts / Others") == "Podcasts"
            assert hierarchy.get("RSS / Others") == "RSS"
            assert "Others" not in hierarchy
        finally:
            _restore_db(orig)


def test_local_export_opml_emits_nested_outlines():
    """Issue #28: local export should emit nested outlines, not merged path text."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            conn = db_mod.get_connection()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        "https://github.com/serrebidev/BlindRSS/commits/main.atom",
                        "Commits",
                        "GitHub / BlindRSS",
                    ),
                )
                c.execute(
                    "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        "https://github.com/serrebidev/BlindRSS/releases.atom",
                        "Releases",
                        "GitHub / BlindRSS",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            opml_path = os.path.join(tmp, "export.opml")
            assert provider.export_opml(opml_path) is True

            body = ET.parse(opml_path).getroot().find("body")
            github = body.find("./outline[@text='GitHub']")
            assert github is not None
            blindrss = github.find("./outline[@text='BlindRSS']")
            assert blindrss is not None
            assert body.find("./outline[@text='GitHub / BlindRSS']") is None
            exported = {
                child.attrib.get("text"): child.attrib.get("xmlUrl")
                for child in blindrss.findall("./outline")
            }
            assert exported == {
                "Commits": "https://github.com/serrebidev/BlindRSS/commits/main.atom",
                "Releases": "https://github.com/serrebidev/BlindRSS/releases.atom",
            }
        finally:
            _restore_db(orig)


def test_write_opml_emits_nested_outlines_for_category_paths(tmp_path):
    """The shared writer used by category export should preserve category paths."""
    feeds = [
        Feed(
            id="1",
            title="Tags",
            url="https://github.com/serrebidev/BlindRSS/tags.atom",
            category="GitHub / BlindRSS",
        )
    ]
    opml_path = tmp_path / "shared.opml"

    assert utils.write_opml(feeds, str(opml_path)) is True

    body = ET.parse(opml_path).getroot().find("body")
    github = body.find("./outline[@text='GitHub']")
    assert github is not None
    blindrss = github.find("./outline[@text='BlindRSS']")
    assert blindrss is not None
    assert body.find("./outline[@text='GitHub / BlindRSS']") is None
    tags = blindrss.find("./outline[@text='Tags']")
    assert tags is not None
    assert tags.attrib.get("xmlUrl") == "https://github.com/serrebidev/BlindRSS/tags.atom"


# ── Provider base hierarchy method ────────────────────────────────────────


def test_provider_get_category_hierarchy():
    """A nesting-capable provider's get_category_hierarchy() reads the local DB."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("A")
            provider.add_category("B", parent_title="A")
            h = provider.get_category_hierarchy()
            assert h.get("A / B") == "A"
            assert h.get("A") is None
        finally:
            _restore_db(orig)


# ── Issue #27: duplicate subcategory leaf names under different parents ────


def test_local_duplicate_subcategory_name_under_different_parents():
    """Issue #27: the same leaf can be a subcategory of two different parents."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Podcasts")
            provider.add_category("RSS")
            # Both additions must succeed (previously the second one failed).
            assert provider.add_category("Others", parent_title="Podcasts") is True
            assert provider.add_category("Others", parent_title="RSS") is True

            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Podcasts / Others") == "Podcasts"
            assert hierarchy.get("RSS / Others") == "RSS"

            # A duplicate under the SAME parent is still rejected.
            assert provider.add_category("Others", parent_title="Podcasts") is False
        finally:
            _restore_db(orig)


def test_local_duplicate_subcategory_feeds_stay_isolated():
    """Feeds in two same-named subcategories under different parents do not mix."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Podcasts")
            provider.add_category("RSS")
            provider.add_category("Others", parent_title="Podcasts")
            provider.add_category("Others", parent_title="RSS")

            conn = db_mod.get_connection()
            c = conn.cursor()
            pod_id = str(uuid.uuid4())
            rss_id = str(uuid.uuid4())
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (pod_id, "http://example.com/pod", "Pod Feed", "Podcasts / Others"))
            c.execute("INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
                      (rss_id, "http://example.com/rss", "RSS Feed", "RSS / Others"))
            c.execute("INSERT INTO articles (id, feed_id, title, url, date) VALUES (?, ?, ?, ?, ?)",
                      ("p1", pod_id, "Pod Article", "http://example.com/p1", "2025-01-01 00:00:00"))
            c.execute("INSERT INTO articles (id, feed_id, title, url, date) VALUES (?, ?, ?, ?, ?)",
                      ("r1", rss_id, "RSS Article", "http://example.com/r1", "2025-01-02 00:00:00"))
            conn.commit()
            conn.close()

            pod_articles, pod_total = provider.get_articles_page("category:Podcasts / Others")
            rss_articles, rss_total = provider.get_articles_page("category:RSS / Others")
            assert pod_total == 1 and {a.title for a in pod_articles} == {"Pod Article"}
            assert rss_total == 1 and {a.title for a in rss_articles} == {"RSS Article"}
        finally:
            _restore_db(orig)


def test_local_supports_subcategories():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            assert _make_provider(tmp).supports_subcategories() is True
        finally:
            _restore_db(orig)


def test_flat_provider_hierarchy_is_empty(monkeypatch):
    """A provider that does not support nesting reports a flat hierarchy even if
    stale parent rows exist locally."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("A")
            provider.add_category("B", parent_title="A")
            monkeypatch.setattr(provider, "supports_subcategories", lambda: False)
            assert provider.get_category_hierarchy() == {}
        finally:
            _restore_db(orig)


# ── Moving a category (issue #86) ────────────────────────────────────────


def _insert_feed(category, title="A Feed"):
    feed_id = str(uuid.uuid4())
    conn = db_mod.get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category) VALUES (?, ?, ?, ?)",
            (feed_id, "http://example.com/%s" % feed_id, title, category),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _feed_category(feed_id):
    conn = db_mod.get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT category FROM feeds WHERE id = ?", (feed_id,))
        row = c.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_local_move_category_under_a_new_parent():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Work")
            provider.add_category("Tech")
            feed_id = _insert_feed("Tech")

            assert provider.move_category("Tech", "Work") is True

            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Work / Tech") == "Work"
            assert "Tech" not in hierarchy
            # The feed's category is the path, so it moves with the folder.
            assert _feed_category(feed_id) == "Work / Tech"
        finally:
            _restore_db(orig)


def test_local_move_category_rewrites_descendant_paths_and_feeds():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Work")
            provider.add_category("Tech")
            provider.add_category("Phones", parent_title="Tech")
            provider.add_category("Android", parent_title="Tech / Phones")
            deep_feed = _insert_feed("Tech / Phones / Android")

            assert provider.move_category("Tech", "Work") is True

            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Work / Tech / Phones") == "Work / Tech"
            assert hierarchy.get("Work / Tech / Phones / Android") == "Work / Tech / Phones"
            assert _feed_category(deep_feed) == "Work / Tech / Phones / Android"
        finally:
            _restore_db(orig)


def test_local_move_category_to_top_level():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Work")
            provider.add_category("Tech", parent_title="Work")
            feed_id = _insert_feed("Work / Tech")

            assert provider.move_category("Work / Tech", None) is True

            hierarchy = db_mod.get_category_hierarchy()
            assert "Tech" in hierarchy
            assert hierarchy.get("Tech") is None
            assert "Work / Tech" not in hierarchy
            assert _feed_category(feed_id) == "Tech"
        finally:
            _restore_db(orig)


def test_local_move_category_rejects_moving_into_its_own_subtree():
    """A category cannot become its own ancestor: that would detach the subtree
    from the root and orphan every feed under it."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Tech")
            provider.add_category("Phones", parent_title="Tech")

            assert provider.move_category("Tech", "Tech / Phones") is False
            assert provider.move_category("Tech", "Tech") is False

            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Tech / Phones") == "Tech"
        finally:
            _restore_db(orig)


def test_local_move_category_rejects_name_taken_under_the_target_parent():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Work")
            provider.add_category("Tech", parent_title="Work")
            provider.add_category("Tech")

            assert provider.move_category("Tech", "Work") is False

            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Work / Tech") == "Work"
            assert hierarchy.get("Tech") is None
        finally:
            _restore_db(orig)


def test_local_move_category_rejects_unknown_parent_and_uncategorized():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Tech")

            assert provider.move_category("Tech", "No Such Folder") is False
            assert provider.move_category("Uncategorized", "Tech") is False
            assert provider.move_category("", "Tech") is False
        finally:
            _restore_db(orig)


def test_local_move_category_to_its_current_parent_is_a_no_op():
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("Work")
            provider.add_category("Tech", parent_title="Work")

            assert provider.move_category("Work / Tech", "Work") is True

            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Work / Tech") == "Work"
        finally:
            _restore_db(orig)


def test_flat_provider_refuses_to_move_categories():
    """Hosted providers are flat upstream; nesting is never simulated locally."""
    from providers.base import RSSProvider

    assert RSSProvider.move_category(object(), "Tech", "Work") is False
