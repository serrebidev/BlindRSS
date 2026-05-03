"""Tests for subcategory (nested category) support."""

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.db as db_mod
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
            hierarchy = db_mod.get_category_hierarchy()
            assert hierarchy.get("Child") == "Parent"
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
            provider.add_category("Child", parent_title="Parent")

            provider.delete_category("Parent")

            hierarchy = db_mod.get_category_hierarchy()
            # Child should now be under Grandparent
            assert hierarchy.get("Child") == "Grandparent"
            assert "Parent" not in hierarchy
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
            # Child should now be top-level (no parent)
            assert hierarchy.get("Child") is None
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
                      (feed2_id, "http://example.com/tech", "Tech News Feed", "Tech News"))
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
                      (feed2_id, "http://example.com/tech", "Tech", "Tech"))
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


# ── Provider base hierarchy method ────────────────────────────────────────


def test_provider_get_category_hierarchy():
    """Base provider get_category_hierarchy() reads from local DB."""
    with tempfile.TemporaryDirectory() as tmp:
        orig = _setup_db(tmp)
        try:
            provider = _make_provider(tmp)
            provider.add_category("A")
            provider.add_category("B", parent_title="A")
            h = provider.get_category_hierarchy()
            assert h.get("B") == "A"
            assert h.get("A") is None
        finally:
            _restore_db(orig)
