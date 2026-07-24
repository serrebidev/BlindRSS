# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import sqlite3
import os
import logging
import time
import uuid
import json
import hashlib
from core.config import APP_DIR, USER_DATA_DIR, get_data_dir
from core.categories import UNCATEGORIZED

log = logging.getLogger(__name__)

DB_FILENAME = "rss.db"


def _db_path() -> str:
    data_dir = get_data_dir() or APP_DIR
    return os.path.join(data_dir, DB_FILENAME)


_DEFAULT_DB_FILE = _db_path()
DB_FILE = _DEFAULT_DB_FILE


def _normalized_path(path: str) -> str:
    try:
        return os.path.abspath(str(path or ""))
    except Exception:
        return str(path or "")


def _db_file_is_overridden() -> bool:
    current = globals().get("DB_FILE", "")
    return bool(current) and _normalized_path(current) != _normalized_path(_DEFAULT_DB_FILE)


def _active_db_path() -> str:
    if _db_file_is_overridden():
        return str(globals().get("DB_FILE"))
    return _db_path()


def _ensure_db_available() -> str:
    """
    Ensure rss.db exists at the active data dir. If it is missing there but
    present in the alternate location (APP_DIR vs USER_DATA_DIR), copy it so a
    data-location switch does not start the user with an empty database.
    """
    target = _active_db_path()
    if os.path.exists(target):
        return target

    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
    except Exception:
        log.exception("Could not create data dir for rss.db at %s", target)

    if _db_file_is_overridden():
        return target

    # Look for a DB at the other candidate location.
    candidates = [
        os.path.join(APP_DIR, DB_FILENAME),
        os.path.join(USER_DATA_DIR, DB_FILENAME),
    ]
    for src in candidates:
        try:
            if os.path.abspath(src) == os.path.abspath(target):
                continue
            if os.path.exists(src):
                _backup_database(src, target)
                log.info("Migrated rss.db from %s to %s", src, target)
                return target
        except Exception:
            log.exception("Failed while migrating rss.db from %s", src)
    return target


def _backup_database(source: str, target: str) -> None:
    """Create a consistent SQLite copy, including committed WAL contents."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temp_target = f"{target}.migrating-{os.getpid()}"
    try:
        source_conn = sqlite3.connect(source, timeout=30, check_same_thread=False)
        target_conn = sqlite3.connect(temp_target, timeout=30, check_same_thread=False)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
            source_conn.close()
        os.replace(temp_target, target)
    except Exception:
        try:
            if os.path.exists(temp_target):
                os.remove(temp_target)
        except Exception:
            pass
        raise


def _table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (name,),
    )
    return cursor.fetchone() is not None


def _chapters_fk_needs_migration(cursor: sqlite3.Cursor) -> bool:
    try:
        cursor.execute("PRAGMA foreign_key_list(chapters)")
        rows = cursor.fetchall()
    except sqlite3.Error:
        return False
    for row in rows:
        if len(row) <= 2:
            continue
        if row[2] == "old_articles":
            return True
        if row[2] == "articles":
            on_delete = str(row[6] if len(row) > 6 else "").upper()
            return on_delete != "CASCADE"
    return False


def _articles_id_is_unique(cursor: sqlite3.Cursor) -> bool:
    if not _table_exists(cursor, "articles"):
        return False

    try:
        cursor.execute("PRAGMA table_info(articles)")
        table_info = cursor.fetchall()
    except sqlite3.Error:
        return False

    pk_columns = [row[1] for row in table_info if row and len(row) > 5 and row[5]]
    if pk_columns == ["id"]:
        return True

    try:
        cursor.execute("PRAGMA index_list(articles)")
        index_list = cursor.fetchall()
    except sqlite3.Error:
        return False

    for row in index_list:
        if not row or len(row) < 3:
            continue
        index_name = row[1]
        is_unique = bool(row[2])
        if not is_unique:
            continue

        safe_index_name = str(index_name).replace('"', '""')
        try:
            cursor.execute(f'PRAGMA index_info("{safe_index_name}")')
            index_info = cursor.fetchall()
        except sqlite3.Error:
            continue

        if len(index_info) == 1 and len(index_info[0]) > 2 and index_info[0][2] == "id":
            return True

    return False


def _migrate_chapters_foreign_key(conn: sqlite3.Connection) -> None:
    """Repair legacy chapter foreign keys and add cascade-on-article-delete.

    Older databases used a `chapters.article_id -> old_articles(id)` foreign key.
    With foreign key enforcement enabled, deletes/updates on chapters can fail with:
        "no such table: main.old_articles"

    Other existing databases reference `articles(id)` without ON DELETE CASCADE.
    Prefer a cascading FK when articles.id is unique; otherwise drop the invalid FK.
    """

    cursor = conn.cursor()
    if not _table_exists(cursor, "chapters"):
        return

    if not _chapters_fk_needs_migration(cursor):
        return

    # PRAGMA foreign_keys is a no-op while a transaction is open, so it must be
    # flipped BEFORE the SAVEPOINT (and with no pending implicit transaction),
    # or FK enforcement stays on during the table rebuild below.
    prev_fk_setting = None
    try:
        conn.commit()
        cursor.execute("PRAGMA foreign_keys")
        row = cursor.fetchone()
        prev_fk_setting = int(row[0]) if row and row[0] is not None else None
        cursor.execute("PRAGMA foreign_keys=OFF")
    except sqlite3.Error:
        prev_fk_setting = None

    try:
        cursor.execute("SAVEPOINT migrate_chapters_fk")

        can_add_fk = _articles_id_is_unique(cursor)
        if not can_add_fk:
            try:
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_id_unique ON articles (id)"
                )
            except sqlite3.Error as e:
                log.debug("Could not create unique index on articles(id) during migration: %s", e)
            can_add_fk = _articles_id_is_unique(cursor)

        backup_name = "chapters_old"
        suffix = 0
        while _table_exists(cursor, backup_name):
            suffix += 1
            backup_name = f"chapters_old_{suffix}"

        log.warning(
            "Migrating chapters FK to %s with delete cascade (backup table: %s)",
            "articles(id)" if can_add_fk else "none",
            backup_name,
        )

        cursor.execute(f"ALTER TABLE chapters RENAME TO {backup_name}")

        if can_add_fk:
            cursor.execute(
                """
                CREATE TABLE chapters (
                    id TEXT PRIMARY KEY,
                    article_id TEXT,
                    start REAL,
                    title TEXT,
                    href TEXT,
                    FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                f"""
                INSERT INTO chapters (id, article_id, start, title, href)
                SELECT id, article_id, start, title, href
                FROM {backup_name}
                WHERE article_id IS NULL OR article_id IN (SELECT id FROM articles)
                """
            )
        else:
            cursor.execute(
                """
                CREATE TABLE chapters (
                    id TEXT PRIMARY KEY,
                    article_id TEXT,
                    start REAL,
                    title TEXT,
                    href TEXT
                )
                """
            )
            cursor.execute(
                f"""
                INSERT INTO chapters (id, article_id, start, title, href)
                SELECT id, article_id, start, title, href
                FROM {backup_name}
                """
            )

        cursor.execute(f"DROP TABLE {backup_name}")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_chapters_article_id_start ON chapters (article_id, start)"
        )

        cursor.execute("RELEASE SAVEPOINT migrate_chapters_fk")
    except sqlite3.Error:
        try:
            cursor.execute("ROLLBACK TO SAVEPOINT migrate_chapters_fk")
            cursor.execute("RELEASE SAVEPOINT migrate_chapters_fk")
        except sqlite3.Error:
            pass
        log.exception("Failed to migrate chapters foreign key; leaving schema unchanged")
    finally:
        # Restore FK enforcement outside the transaction (commit first so the
        # pragma actually applies).
        if prev_fk_setting is not None:
            try:
                conn.commit()
                cursor.execute(f"PRAGMA foreign_keys={prev_fk_setting}")
            except sqlite3.Error:
                pass


def init_db():
    db_path = _ensure_db_available()
    global DB_FILE
    DB_FILE = db_path
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    try:
        c = conn.cursor()
        # Improve concurrent writer/readers when refresh runs in multiple threads
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=60000")
            c.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            log.warning(f"Failed to set PRAGMAs: {e}")
        
        c.execute('''CREATE TABLE IF NOT EXISTS feeds (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            title_is_custom INTEGER DEFAULT 0,
            category TEXT,
            icon_url TEXT
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            feed_id TEXT,
            title TEXT,
            url TEXT,
            content TEXT,
            description TEXT,
            date TEXT,
            author TEXT,
            is_read INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            media_url TEXT,
            media_type TEXT,
            chapter_url TEXT,
            opened_at REAL,
            FOREIGN KEY(feed_id) REFERENCES feeds(id)
        )''')
        
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_feed_id ON articles (feed_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_is_read ON articles (is_read)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_date ON articles (date)")
        # Composite indexes to speed up common paging/count queries on larger databases.
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_is_read_feed_id ON articles (is_read, feed_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_date_id ON articles (date, id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_feed_id_date_id ON articles (feed_id, date, id)")

        # deleted_articles doubles as the tombstone list (so refresh never
        # recreates a user-deleted item) AND the backing store for the "Deleted
        # Articles" view: the snapshot columns preserve the full article so it can
        # be shown and restored. Older rows created before the snapshot migration
        # only have identity columns populated (NULL snapshot) and degrade
        # gracefully (shown with a URL/placeholder title, restorable as a stub).
        c.execute('''CREATE TABLE IF NOT EXISTS deleted_articles (
            feed_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            url TEXT,
            deleted_at REAL NOT NULL,
            title TEXT,
            content TEXT,
            description TEXT,
            date TEXT,
            author TEXT,
            media_url TEXT,
            media_type TEXT,
            chapter_url TEXT,
            is_read INTEGER,
            is_favorite INTEGER,
            purged INTEGER DEFAULT 0,
            PRIMARY KEY (feed_id, article_id),
            FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_deleted_articles_feed_id ON deleted_articles (feed_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_deleted_articles_feed_url ON deleted_articles (feed_id, url)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_deleted_articles_deleted_at ON deleted_articles (deleted_at)")

        c.execute('''CREATE TABLE IF NOT EXISTS chapters (
            id TEXT PRIMARY KEY,
            article_id TEXT,
            start REAL,
            title TEXT,
            href TEXT,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_chapters_article_id_start ON chapters (article_id, start)")

        _migrate_chapters_foreign_key(conn)

        # Hosted providers do not mirror their articles into the local `articles`
        # table, so their chapter rows cannot use the local article foreign key.
        # Keep a provider-scoped cache alongside the local chapter table instead.
        c.execute('''CREATE TABLE IF NOT EXISTS chapter_cache (
            id TEXT PRIMARY KEY,
            cache_key TEXT NOT NULL,
            start REAL,
            title TEXT,
            href TEXT
        )''')
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_chapter_cache_key_start "
            "ON chapter_cache (cache_key, start)"
        )
        c.execute('''CREATE TABLE IF NOT EXISTS chapter_sources (
            cache_key TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            etag TEXT,
            last_modified TEXT,
            checked_at REAL NOT NULL DEFAULT 0,
            fetched_at REAL NOT NULL DEFAULT 0
        )''')
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_chapter_sources_checked_at "
            "ON chapter_sources (checked_at)"
        )

        c.execute('''CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            title TEXT UNIQUE
        )''')

        c.execute(
            '''CREATE TABLE IF NOT EXISTS playback_state (
            id TEXT PRIMARY KEY,
            position_ms INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            updated_at INTEGER NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            seek_supported INTEGER,
            title TEXT
        )'''
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_playback_state_updated_at ON playback_state (updated_at)")

        # Full change history: each distinct (title, content) a local article has
        # shown over time becomes a row here. Version 1 is the original captured at
        # first fetch; a new row is appended only when the content hash changes, so
        # repeated refreshes of unchanged content do not accumulate duplicates. An
        # article with more than one version is "updated" (Smart Folders criterion).
        c.execute('''CREATE TABLE IF NOT EXISTS article_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT NOT NULL,
            captured_at REAL NOT NULL,
            content_hash TEXT NOT NULL,
            title TEXT,
            content TEXT
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_article_versions_article ON article_versions (article_id, captured_at)")

        # Smart Folders: user-defined rule-based virtual folders. `rule_json` is a
        # boolean rule tree (see core.smart_folders); `position` orders them in the
        # tree. Non-destructive -- articles are matched live, never moved.
        c.execute('''CREATE TABLE IF NOT EXISTS smart_folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            rule_json TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_smart_folders_position ON smart_folders (position)")

        # Filter Rules: an ordered pipeline of user-defined rules applied to
        # articles as they arrive (and retroactively when rules change).
        # `rule_json` reuses the Smart Folders boolean rule tree
        # (core.smart_folders); `actions_json` is the action set
        # (core.filters.normalize_actions). All matching enabled rules apply in
        # position order; a rule with stop=1 halts the pipeline for that article.
        c.execute('''CREATE TABLE IF NOT EXISTS filter_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            rule_json TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            stop INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_filter_rules_position ON filter_rules (position)")

        # Article labels: extra category memberships assigned by filter rules
        # ("label" action). A labeled article ALSO appears in `category`'s view
        # while staying in its normal place; contrast with
        # articles.category_override which MOVES it. `category` stores the full
        # category path string (same identity model as feeds.category).
        c.execute('''CREATE TABLE IF NOT EXISTS article_labels (
            article_id TEXT NOT NULL,
            category TEXT NOT NULL,
            PRIMARY KEY (article_id, category),
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_article_labels_category ON article_labels (category)")

        # Migration: Add columns if they don't exist
        try:
            c.execute("ALTER TABLE articles ADD COLUMN media_url TEXT")
        except sqlite3.OperationalError:
            pass
            
        try:
            c.execute("ALTER TABLE articles ADD COLUMN media_type TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE articles ADD COLUMN chapter_url TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE articles ADD COLUMN description TEXT")
        except sqlite3.OperationalError:
            pass

        # opened_at: epoch seconds when the user last opened/viewed the article
        # (distinct from is_read, which bulk actions also set). Powers the Smart
        # Folders "opened" activity criterion.
        try:
            c.execute("ALTER TABLE articles ADD COLUMN opened_at REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_articles_opened_at ON articles (opened_at)")
        except sqlite3.OperationalError:
            pass

        # tags: newline-separated tag/category strings the originating site
        # attached to the article (feedparser entry.tags terms, JSON Feed tags).
        # Stored for display and as a Filter Rules criterion ("tag" field).
        try:
            c.execute("ALTER TABLE articles ADD COLUMN tags TEXT")
        except sqlite3.OperationalError:
            pass

        # category_override: when a filter rule (or delete-to-category) MOVES an
        # article, this holds the target category path. The article then appears
        # only under this category, not its feed's category. NULL = no override.
        try:
            c.execute("ALTER TABLE articles ADD COLUMN category_override TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_articles_category_override ON articles (category_override)")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_articles_url ON articles (url)")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_articles_media_url ON articles (media_url)")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("ALTER TABLE articles ADD COLUMN is_favorite INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_articles_is_favorite ON articles (is_favorite)")
        except sqlite3.OperationalError:
            pass
            
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN etag TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN last_modified TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN title_is_custom INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        # Last feed-provided <title> seen on refresh (issue #43). Kept separate
        # from `title` so a user-renamed feed is detected even when
        # title_is_custom was never set (renames made in builds that predate
        # the flag): refresh only auto-updates `title` while it still matches
        # what the feed itself last reported (or the URL/empty placeholder).
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN upstream_title TEXT")
        except sqlite3.OperationalError:
            pass
        # Per-feed image-alt-text override: NULL = inherit global setting, 0 = off, 1 = on.
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN show_images INTEGER")
        except sqlite3.OperationalError:
            pass
        # Per-feed HTTP fetch overrides (issue #29): JSON blob with custom request
        # headers, timeout, and browser-impersonation mode. See get_feed_settings().
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN feed_settings TEXT")
        except sqlite3.OperationalError:
            pass

        # Language the feed declares for its content (RSS <language> / Atom
        # xml:lang), as a BCP-47 tag. NULL = the feed never said, which is a real
        # answer, not a default: the rich reader falls back to the UI language
        # rather than claiming a language the publisher never declared (issue #72).
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN language TEXT")
        except sqlite3.OperationalError:
            pass

        # Per-feed delete-behavior override: NULL = inherit the global
        # `delete_behavior` setting; otherwise "deleted" (tombstone/Deleted view),
        # "purge" (remove permanently), or "category:<path>" (move to a category).
        # Resolved by db.get_feed_delete_behavior / set by set_feed_delete_behavior.
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN delete_behavior TEXT")
        except sqlite3.OperationalError:
            pass

        # Per-feed update error tracking (issue #32): persist the most recent
        # failed update so the "Feeds with Errors" view can list broken feeds
        # across restarts. last_error is NULL when the most recent attempt
        # succeeded; consecutive_failures distinguishes one-off glitches from
        # persistently broken feeds. See record_feed_error()/get_feed_errors().
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN last_error TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN last_error_at REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN last_success_at REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE feeds ADD COLUMN consecutive_failures INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Migration: add parent_id to categories for subcategory support
        try:
            c.execute("ALTER TABLE categories ADD COLUMN parent_id TEXT")
        except sqlite3.OperationalError:
            pass

        # Migration: snapshot columns on deleted_articles so the Deleted Articles
        # view can display and restore items. Older tombstones only stored
        # identity (feed_id/article_id/url); these columns stay NULL for them.
        for _col, _decl in (
            ("title", "TEXT"),
            ("content", "TEXT"),
            ("description", "TEXT"),
            ("date", "TEXT"),
            ("author", "TEXT"),
            ("media_url", "TEXT"),
            ("media_type", "TEXT"),
            ("chapter_url", "TEXT"),
            ("is_read", "INTEGER"),
            ("is_favorite", "INTEGER"),
            # purged=1: permanently deleted from the Deleted Articles view. The
            # tombstone row is kept so refresh still never recreates the article.
            ("purged", "INTEGER DEFAULT 0"),
        ):
            try:
                c.execute(f"ALTER TABLE deleted_articles ADD COLUMN {_col} {_decl}")
            except sqlite3.OperationalError:
                pass
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_deleted_articles_deleted_at ON deleted_articles (deleted_at)")
        except sqlite3.OperationalError:
            pass

        # Seed categories from existing feeds if empty
        c.execute("SELECT count(*) FROM categories")
        if c.fetchone()[0] == 0:
            c.execute(
                "INSERT OR IGNORE INTO categories (id, title) "
                "SELECT lower(hex(randomblob(16))), category FROM feeds WHERE category IS NOT NULL AND category != ''"
            )
            # Ensure Uncategorized exists
            c.execute("INSERT OR IGNORE INTO categories (id, title) VALUES (?, ?)", ("uncategorized", UNCATEGORIZED))
        
        conn.commit()
    finally:
        conn.close()


def cleanup_old_articles(days: int, keep_favorites: bool = True):
    """
    Delete articles older than 'days' days.
    
    Args:
        days: Number of days to retain.
        keep_favorites: If True, do not delete favorited articles.
    """
    if days is None or days < 0:
        return
        
    conn = get_connection()
    try:
        # Calculate cutoff date
        # SQLite's 'now' is UTC. verify if we need 'localtime' or if normalization uses UTC.
        # core.utils.normalize_date produces 'YYYY-MM-DD HH:MM:SS' (usually UTC or naive).
        # We'll use SQLite's date modifier.
        cutoff_date_query = f"date('now', '-{days} days')"
        
        query = "DELETE FROM articles WHERE date < date('now', '-? days')"
        # Parameter substitution for days in modifiers is tricky in sqlite, constructing string is safer for modifier
        # provided 'days' is int.
        
        params = []
        where_clauses = [f"date < date('now', '-{int(days)} days')"]
        # Articles whose date could not be parsed carry the sentinel
        # "0001-01-01 00:00:00" (or an empty string). Those compare below any
        # real cutoff, so without this guard every undated article would be
        # deleted on each sweep no matter how recently it was fetched.
        where_clauses.append("date >= '0002'")

        if keep_favorites:
            where_clauses.append("is_favorite = 0")
            
        where_str = " AND ".join(where_clauses)
        
        # 1. Delete chapters for these articles first (no CASCADE support guaranteed)
        # We can use subquery: DELETE FROM chapters WHERE article_id IN (SELECT id FROM articles WHERE ...)
        
        subquery = f"SELECT id FROM articles WHERE {where_str}"
        
        c = conn.cursor()
        c.execute(f"DELETE FROM chapters WHERE article_id IN ({subquery})")
        # Also drop resume/playback positions for the articles being purged so
        # playback_state doesn't accumulate orphaned rows forever. The player keys
        # these as 'article:<id>' (see player._set_resume_ids), so match that form.
        # Favorited articles are excluded from {where_str}, so their resume
        # positions are preserved.
        c.execute(
            f"DELETE FROM playback_state WHERE id IN (SELECT 'article:' || id FROM articles WHERE {where_str})"
        )
        c.execute(f"DELETE FROM articles WHERE {where_str}")
        
        deleted = c.rowcount
        conn.commit()
        if deleted > 0:
            log.info(f"Cleaned up {deleted} old articles (retention: {days} days)")
            # VACUUM is heavy, maybe just auto_vacuum handles it or do it rarely.
            # c.execute("VACUUM") 
            
    except Exception as e:
        log.error(f"Error cleaning up old articles: {e}")
    finally:
        conn.close()


def _sql_py_lower(value):
    """Unicode-aware LOWER for SQL. SQLite's built-in LOWER() only folds
    ASCII A-Z, so queries that compare against Python-lowercased needles
    (Smart Folder text filters) miss accented/non-Latin matches without it."""
    return value.lower() if isinstance(value, str) else value


def get_connection():
    conn = sqlite3.connect(_active_db_path(), timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        log.warning(f"Failed to set PRAGMAs on connection: {e}")
    try:
        conn.create_function("py_lower", 1, _sql_py_lower, deterministic=True)
    except TypeError:
        conn.create_function("py_lower", 1, _sql_py_lower)
    except Exception as e:
        log.warning(f"Failed to register py_lower on connection: {e}")
    return conn


def _bool_or_none(value):
    if value is None:
        return None
    return 1 if value else 0


def remember_deleted_article(
    feed_id: str,
    article_id: str,
    url: str | None = None,
    *,
    deleted_at: float | None = None,
    snapshot: dict | None = None,
    purged: bool = False,
    cursor=None,
) -> bool:
    """Persist a local article deletion so refresh does not recreate it.

    When `snapshot` (a dict of the article's displayable fields) is supplied, the
    full article is preserved so the Deleted Articles view can show and restore
    it. Without a snapshot only the tombstone identity is stored.

    `purged=True` marks the tombstone as permanently deleted (hidden from the
    Deleted Articles view) — used when a filter rule deletes under a "remove
    completely" delete behavior. The tombstone row is still kept so refresh never
    resurrects the article.
    """
    fid = str(feed_id or "").strip()
    aid = str(article_id or "").strip()
    if not fid or not aid:
        return False
    clean_url = str(url or "").strip() or None
    timestamp = float(time.time() if deleted_at is None else deleted_at)
    snap = snapshot or {}
    purged_val = 1 if purged else 0

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO deleted_articles
                (feed_id, article_id, url, deleted_at, title, content, description,
                 date, author, media_url, media_type, chapter_url, is_read, is_favorite,
                 purged)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feed_id, article_id) DO UPDATE SET
                url = excluded.url,
                deleted_at = excluded.deleted_at,
                title = excluded.title,
                content = excluded.content,
                description = excluded.description,
                date = excluded.date,
                author = excluded.author,
                media_url = excluded.media_url,
                media_type = excluded.media_type,
                chapter_url = excluded.chapter_url,
                is_read = excluded.is_read,
                is_favorite = excluded.is_favorite,
                purged = excluded.purged
            """,
            (
                fid,
                aid,
                clean_url,
                timestamp,
                snap.get("title"),
                snap.get("content"),
                snap.get("description"),
                snap.get("date"),
                snap.get("author"),
                snap.get("media_url"),
                snap.get("media_type"),
                snap.get("chapter_url"),
                _bool_or_none(snap.get("is_read")),
                _bool_or_none(snap.get("is_favorite")),
                purged_val,
            ),
        )
        if conn is not None:
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def list_deleted_articles(offset: int = 0, limit: int | None = None, cursor=None):
    """Return (rows, total) of deleted-article snapshots, newest deletion first.

    Each row is a dict keyed by column name. `limit=None` returns all rows.
    """
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM deleted_articles WHERE COALESCE(purged, 0) = 0")
        total = int(c.fetchone()[0] or 0)

        sql = (
            "SELECT feed_id, article_id, url, deleted_at, title, content, description, "
            "date, author, media_url, media_type, chapter_url, is_read, is_favorite "
            "FROM deleted_articles WHERE COALESCE(purged, 0) = 0 "
            "ORDER BY deleted_at DESC, article_id DESC"
        )
        params: list = []
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [int(limit), int(max(0, offset))]
        c.execute(sql, tuple(params))
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, r)) for r in c.fetchall()]
        return rows, total
    finally:
        if conn is not None:
            conn.close()


def restore_deleted_article(article_id: str, feed_id: str | None = None, cursor=None):
    """Restore a deleted article: re-insert its snapshot into `articles` and drop
    the tombstone. Returns the article's feed_id on success, or None if the
    tombstone was not found. After restore, refresh treats the item normally
    again (the feed may update it if it is still present upstream).
    """
    aid = str(article_id or "").strip()
    if not aid:
        return None
    fid = str(feed_id or "").strip()

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        if fid:
            c.execute(
                "SELECT feed_id, url, title, content, description, date, author, "
                "media_url, media_type, chapter_url, is_read, is_favorite "
                "FROM deleted_articles WHERE feed_id = ? AND article_id = ? "
                "AND COALESCE(purged, 0) = 0 LIMIT 1",
                (fid, aid),
            )
        else:
            c.execute(
                "SELECT COUNT(*) FROM deleted_articles WHERE article_id = ? AND COALESCE(purged, 0) = 0",
                (aid,),
            )
            if int(c.fetchone()[0] or 0) != 1:
                return None
            c.execute(
                "SELECT feed_id, url, title, content, description, date, author, "
                "media_url, media_type, chapter_url, is_read, is_favorite "
                "FROM deleted_articles WHERE article_id = ? AND COALESCE(purged, 0) = 0 LIMIT 1",
                (aid,),
            )
        row = c.fetchone()
        if not row:
            return None
        (
            feed_id,
            url,
            title,
            content,
            description,
            date,
            author,
            media_url,
            media_type,
            chapter_url,
            is_read,
            is_favorite,
        ) = row
        c.execute(
            """
            INSERT OR REPLACE INTO articles
                (id, feed_id, title, url, content, description, date, author,
                 is_read, is_favorite, media_url, media_type, chapter_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aid,
                feed_id,
                title,
                url,
                content,
                description,
                date,
                author,
                int(is_read or 0),
                int(is_favorite or 0),
                media_url,
                media_type,
                chapter_url,
            ),
        )
        c.execute("DELETE FROM deleted_articles WHERE feed_id = ? AND article_id = ?", (feed_id, aid))
        if conn is not None:
            conn.commit()
        return str(feed_id or "")
    finally:
        if conn is not None:
            conn.close()


def purge_deleted_article(article_id: str, feed_id: str | None = None, cursor=None) -> bool:
    """Permanently delete an article from the Deleted Articles view.

    The snapshot content is dropped and the row is marked purged, but the
    tombstone identity is kept so refresh still never recreates the article.
    Without `feed_id`, only purges when the article_id is unambiguous across
    feeds. Returns True when a row was purged.
    """
    aid = str(article_id or "").strip()
    if not aid:
        return False
    fid = str(feed_id or "").strip()

    set_sql = (
        "UPDATE deleted_articles SET purged = 1, title = NULL, content = NULL, "
        "description = NULL, author = NULL, media_url = NULL, media_type = NULL, "
        "chapter_url = NULL"
    )
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        if fid:
            c.execute(
                set_sql + " WHERE feed_id = ? AND article_id = ? AND COALESCE(purged, 0) = 0",
                (fid, aid),
            )
        else:
            c.execute(
                "SELECT COUNT(*) FROM deleted_articles WHERE article_id = ? AND COALESCE(purged, 0) = 0",
                (aid,),
            )
            if int(c.fetchone()[0] or 0) != 1:
                return False
            c.execute(set_sql + " WHERE article_id = ? AND COALESCE(purged, 0) = 0", (aid,))
        purged = int(c.rowcount or 0) > 0
        if conn is not None:
            conn.commit()
        return purged
    finally:
        if conn is not None:
            conn.close()


def mark_article_opened(
    article_id: str,
    opened_at: float | None = None,
    *,
    feed_id: str | None = None,
    cursor=None,
) -> bool:
    """Record that the user opened/viewed an article (Smart Folders 'opened').

    Stores the most recent open time. When `feed_id` is supplied, the update is
    scoped to that local feed so hosted-provider or cross-feed article-id
    collisions cannot mark the wrong local row.
    """
    aid = str(article_id or "").strip()
    if not aid:
        return False
    fid = str(feed_id or "").strip()
    ts = float(time.time() if opened_at is None else opened_at)

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        if fid:
            c.execute("UPDATE articles SET opened_at = ? WHERE id = ? AND feed_id = ?", (ts, aid, fid))
        else:
            c.execute("UPDATE articles SET opened_at = ? WHERE id = ?", (ts, aid))
        if conn is not None:
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def _article_content_hash(title, content) -> str:
    h = hashlib.sha256()
    h.update((str(title or "")).encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update((str(content or "")).encode("utf-8", "replace"))
    return h.hexdigest()


def record_article_version(article_id, title, content, captured_at: float | None = None, cursor=None) -> bool:
    """Append a change-history version for an article, deduped by content hash.

    Records a new row only when (title, content) differs from the article's most
    recent recorded version, so repeated refreshes of unchanged content are
    no-ops. Returns True when a new version row was written.
    """
    aid = str(article_id or "").strip()
    if not aid:
        return False
    new_hash = _article_content_hash(title, content)
    ts = float(time.time() if captured_at is None else captured_at)

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(
            "SELECT content_hash FROM article_versions WHERE article_id = ? "
            "ORDER BY captured_at DESC, id DESC LIMIT 1",
            (aid,),
        )
        row = c.fetchone()
        if row is not None and str(row[0] or "") == new_hash:
            return False
        c.execute(
            "INSERT INTO article_versions (article_id, captured_at, content_hash, title, content) "
            "VALUES (?, ?, ?, ?, ?)",
            (aid, ts, new_hash, title, content),
        )
        if conn is not None:
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def get_article_versions(article_id: str, cursor=None):
    """Return an article's change history, newest first (list of dicts)."""
    aid = str(article_id or "").strip()
    if not aid:
        return []

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(
            "SELECT id, article_id, captured_at, content_hash, title, content "
            "FROM article_versions WHERE article_id = ? ORDER BY captured_at DESC, id DESC",
            (aid,),
        )
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, r)) for r in c.fetchall()]
    finally:
        if conn is not None:
            conn.close()


def count_article_versions(article_id: str, cursor=None) -> int:
    aid = str(article_id or "").strip()
    if not aid:
        return 0
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM article_versions WHERE article_id = ?", (aid,))
        return int(c.fetchone()[0] or 0)
    finally:
        if conn is not None:
            conn.close()


def _parse_rule_json(raw):
    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed


def create_smart_folder(name: str, rule: dict, cursor=None) -> str:
    """Create a Smart Folder and return its new id."""
    folder_id = uuid.uuid4().hex
    rule_json = json.dumps(rule or {"match": "all", "conditions": []})
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM smart_folders")
        position = int(c.fetchone()[0] or 0)
        c.execute(
            "INSERT INTO smart_folders (id, name, rule_json, position) VALUES (?, ?, ?, ?)",
            (folder_id, str(name or "").strip() or "Smart Folder", rule_json, position),
        )
        if conn is not None:
            conn.commit()
        return folder_id
    finally:
        if conn is not None:
            conn.close()


def update_smart_folder(folder_id: str, name: str | None = None, rule: dict | None = None, cursor=None) -> bool:
    fid = str(folder_id or "").strip()
    if not fid:
        return False
    sets = []
    params: list = []
    if name is not None:
        sets.append("name = ?")
        params.append(str(name or "").strip() or "Smart Folder")
    if rule is not None:
        sets.append("rule_json = ?")
        params.append(json.dumps(rule))
    if not sets:
        return False
    params.append(fid)

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(f"UPDATE smart_folders SET {', '.join(sets)} WHERE id = ?", tuple(params))
        changed = int(c.rowcount or 0)
        if conn is not None:
            conn.commit()
        return changed > 0
    finally:
        if conn is not None:
            conn.close()


def delete_smart_folder(folder_id: str, cursor=None) -> bool:
    fid = str(folder_id or "").strip()
    if not fid:
        return False
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("DELETE FROM smart_folders WHERE id = ?", (fid,))
        changed = int(c.rowcount or 0)
        if conn is not None:
            conn.commit()
        return changed > 0
    finally:
        if conn is not None:
            conn.close()


def get_smart_folder(folder_id: str, cursor=None):
    fid = str(folder_id or "").strip()
    if not fid:
        return None
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT id, name, rule_json, position FROM smart_folders WHERE id = ?", (fid,))
        row = c.fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "rule": _parse_rule_json(row[2]), "position": int(row[3] or 0)}
    finally:
        if conn is not None:
            conn.close()


def list_smart_folders(cursor=None):
    """Return all Smart Folders ordered by position then name."""
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT id, name, rule_json, position FROM smart_folders ORDER BY position ASC, name ASC")
        return [
            {"id": r[0], "name": r[1], "rule": _parse_rule_json(r[2]), "position": int(r[3] or 0)}
            for r in c.fetchall()
        ]
    finally:
        if conn is not None:
            conn.close()


# ── Filter Rules (categorization pipeline) ───────────────────────────────────
# An ordered list of rules applied to articles like email filters. Each rule has
# a Smart-Folders-style boolean rule tree (rule_json) and an action set
# (actions_json). See core.filters for the engine that evaluates and applies them.

def _parse_actions_json(raw):
    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _filter_rule_row(row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "rule": _parse_rule_json(row[2]),
        "actions": _parse_actions_json(row[3]),
        "enabled": bool(row[4]),
        "stop": bool(row[5]),
        "position": int(row[6] or 0),
    }


_FILTER_RULE_COLS = "id, name, rule_json, actions_json, enabled, stop, position"


def create_filter_rule(name, rule, actions, enabled=True, stop=False, cursor=None) -> str:
    """Create a filter rule and return its new id."""
    rule_id = uuid.uuid4().hex
    rule_json = json.dumps(rule or {"match": "all", "conditions": []})
    actions_json = json.dumps(actions or {})
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM filter_rules")
        position = int(c.fetchone()[0] or 0)
        c.execute(
            "INSERT INTO filter_rules (id, name, rule_json, actions_json, enabled, stop, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rule_id,
                str(name or "").strip() or "Filter",
                rule_json,
                actions_json,
                1 if enabled else 0,
                1 if stop else 0,
                position,
            ),
        )
        if conn is not None:
            conn.commit()
        return rule_id
    finally:
        if conn is not None:
            conn.close()


def update_filter_rule(
    rule_id, name=None, rule=None, actions=None, enabled=None, stop=None, cursor=None
) -> bool:
    rid = str(rule_id or "").strip()
    if not rid:
        return False
    sets = []
    params: list = []
    if name is not None:
        sets.append("name = ?")
        params.append(str(name or "").strip() or "Filter")
    if rule is not None:
        sets.append("rule_json = ?")
        params.append(json.dumps(rule))
    if actions is not None:
        sets.append("actions_json = ?")
        params.append(json.dumps(actions))
    if enabled is not None:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    if stop is not None:
        sets.append("stop = ?")
        params.append(1 if stop else 0)
    if not sets:
        return False
    params.append(rid)
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(f"UPDATE filter_rules SET {', '.join(sets)} WHERE id = ?", tuple(params))
        changed = int(c.rowcount or 0)
        if conn is not None:
            conn.commit()
        return changed > 0
    finally:
        if conn is not None:
            conn.close()


def delete_filter_rule(rule_id, cursor=None) -> bool:
    rid = str(rule_id or "").strip()
    if not rid:
        return False
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("DELETE FROM filter_rules WHERE id = ?", (rid,))
        changed = int(c.rowcount or 0)
        if conn is not None:
            conn.commit()
        return changed > 0
    finally:
        if conn is not None:
            conn.close()


def get_filter_rule(rule_id, cursor=None):
    rid = str(rule_id or "").strip()
    if not rid:
        return None
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(f"SELECT {_FILTER_RULE_COLS} FROM filter_rules WHERE id = ?", (rid,))
        row = c.fetchone()
        return _filter_rule_row(row) if row else None
    finally:
        if conn is not None:
            conn.close()


def list_filter_rules(enabled_only=False, cursor=None):
    """Return filter rules ordered by position (pipeline order)."""
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        sql = f"SELECT {_FILTER_RULE_COLS} FROM filter_rules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY position ASC, name ASC"
        c.execute(sql)
        return [_filter_rule_row(r) for r in c.fetchall()]
    finally:
        if conn is not None:
            conn.close()


def reorder_filter_rules(ordered_ids, cursor=None) -> bool:
    """Persist a new pipeline order given a list of rule ids top-to-bottom."""
    ids = [str(i or "").strip() for i in (ordered_ids or []) if str(i or "").strip()]
    if not ids:
        return False
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        for pos, rid in enumerate(ids):
            c.execute("UPDATE filter_rules SET position = ? WHERE id = ?", (pos, rid))
        if conn is not None:
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


# ── Article category assignment (move) and labels (also-show) ────────────────

def set_article_category_override(article_id, category, cursor=None) -> bool:
    """MOVE an article to `category` (full path string), or clear with None."""
    aid = str(article_id or "").strip()
    if not aid:
        return False
    value = str(category).strip() if category is not None else None
    if value == "":
        value = None
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("UPDATE articles SET category_override = ? WHERE id = ?", (value, aid))
        changed = int(c.rowcount or 0)
        if conn is not None:
            conn.commit()
        return changed > 0
    finally:
        if conn is not None:
            conn.close()


def add_article_label(article_id, category, cursor=None) -> bool:
    """LABEL an article with `category` so it ALSO appears under that category."""
    aid = str(article_id or "").strip()
    cat = str(category or "").strip()
    if not aid or not cat:
        return False
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(
            "INSERT OR IGNORE INTO article_labels (article_id, category) VALUES (?, ?)",
            (aid, cat),
        )
        if conn is not None:
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def remove_article_label(article_id, category, cursor=None) -> bool:
    aid = str(article_id or "").strip()
    cat = str(category or "").strip()
    if not aid or not cat:
        return False
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(
            "DELETE FROM article_labels WHERE article_id = ? AND category = ?",
            (aid, cat),
        )
        changed = int(c.rowcount or 0)
        if conn is not None:
            conn.commit()
        return changed > 0
    finally:
        if conn is not None:
            conn.close()


def get_article_labels(article_id, cursor=None) -> list:
    aid = str(article_id or "").strip()
    if not aid:
        return []
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(
            "SELECT category FROM article_labels WHERE article_id = ? ORDER BY category",
            (aid,),
        )
        return [r[0] for r in c.fetchall()]
    finally:
        if conn is not None:
            conn.close()


# ── Per-feed delete-behavior override ────────────────────────────────────────

def get_feed_delete_behavior(feed_id, cursor=None):
    """Return the per-feed delete-behavior override, or None to inherit global."""
    fid = str(feed_id or "").strip()
    if not fid:
        return None
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT delete_behavior FROM feeds WHERE id = ?", (fid,))
        row = c.fetchone()
        if not row:
            return None
        value = str(row[0]).strip() if row[0] is not None else ""
        return value or None
    finally:
        if conn is not None:
            conn.close()


def set_feed_delete_behavior(feed_id, behavior, cursor=None) -> bool:
    fid = str(feed_id or "").strip()
    if not fid:
        return False
    value = str(behavior).strip() if behavior is not None else None
    if value == "":
        value = None
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("UPDATE feeds SET delete_behavior = ? WHERE id = ?", (value, fid))
        changed = int(c.rowcount or 0)
        if conn is not None:
            conn.commit()
        return changed > 0
    finally:
        if conn is not None:
            conn.close()


def deleted_article_tombstones_for_feed(feed_id: str, cursor=None) -> tuple[set[str], set[str]]:
    """Return article IDs and URLs intentionally deleted for a local feed."""
    fid = str(feed_id or "").strip()
    if not fid:
        return set(), set()

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute("SELECT article_id, url FROM deleted_articles WHERE feed_id = ?", (fid,))
        ids: set[str] = set()
        urls: set[str] = set()
        for article_id, url in c.fetchall():
            aid = str(article_id or "").strip()
            if aid:
                ids.add(aid)
            clean_url = str(url or "").strip()
            if clean_url:
                urls.add(clean_url)
        return ids, urls
    finally:
        if conn is not None:
            conn.close()


def delete_hosted_chapter_cache(cache_keys, cursor=None) -> int:
    """Delete hosted chapter rows and source metadata for exact cache keys."""
    keys = []
    for key in cache_keys or []:
        if key is None:
            continue
        normalized = str(key).strip()
        if normalized and normalized not in keys:
            keys.append(normalized)
    if not keys:
        return 0

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    deleted = 0
    try:
        for start in range(0, len(keys), 900):
            chunk = keys[start:start + 900]
            placeholders = ",".join("?" for _ in chunk)
            c.execute(
                f"DELETE FROM chapter_cache WHERE cache_key IN ({placeholders})",
                chunk,
            )
            deleted += max(0, int(c.rowcount or 0))
            c.execute(
                f"DELETE FROM chapter_sources "
                f"WHERE cache_key IN ({placeholders}) AND cache_key NOT LIKE 'local:%'",
                chunk,
            )
        if conn is not None:
            conn.commit()
        return deleted
    finally:
        if conn is not None:
            conn.close()


def cleanup_hosted_chapter_cache(
    retention_days: int = 90,
    max_sources: int | None = 10_000,
    *,
    now: float | None = None,
) -> dict:
    """Bound hosted chapter cache growth without touching local FK-backed rows.

    Source records are the retention clock, including valid chapter documents
    whose chapter list is empty. Orphaned hosted rows with no source record are
    removed because they cannot be safely revalidated.
    """
    days = max(0, int(retention_days))
    limit = None if max_sources is None else max(0, int(max_sources))
    cutoff = float(time.time() if now is None else now) - (days * 86400)

    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SAVEPOINT cleanup_hosted_chapters")
        try:
            c.execute(
                "SELECT cache_key FROM chapter_sources "
                "WHERE cache_key NOT LIKE 'local:%' "
                "AND MAX(checked_at, fetched_at) < ?",
                (cutoff,),
            )
            keys = [row[0] for row in c.fetchall()]

            if limit is not None:
                c.execute(
                    "SELECT cache_key FROM chapter_sources "
                    "WHERE cache_key NOT LIKE 'local:%' "
                    "ORDER BY MAX(checked_at, fetched_at) DESC, cache_key "
                    "LIMIT -1 OFFSET ?",
                    (limit,),
                )
                keys.extend(row[0] for row in c.fetchall())

            unique_keys = list(dict.fromkeys(keys))
            deleted_rows = delete_hosted_chapter_cache(unique_keys, cursor=c)
            c.execute(
                "DELETE FROM chapter_cache "
                "WHERE cache_key NOT IN (SELECT cache_key FROM chapter_sources)"
            )
            orphan_rows = max(0, int(c.rowcount or 0))
            c.execute("RELEASE SAVEPOINT cleanup_hosted_chapters")
            conn.commit()
            return {
                "sources": len(unique_keys),
                "chapters": deleted_rows + orphan_rows,
                "orphans": orphan_rows,
            }
        except Exception:
            c.execute("ROLLBACK TO SAVEPOINT cleanup_hosted_chapters")
            c.execute("RELEASE SAVEPOINT cleanup_hosted_chapters")
            raise
    finally:
        conn.close()


def get_feed_show_images(feed_id):
    """Return the per-feed image-alt override: None (inherit global), True, or False."""
    if not feed_id:
        return None
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT show_images FROM feeds WHERE id = ?", (str(feed_id),))
        row = c.fetchone()
    except sqlite3.Error:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row or row[0] is None:
        return None
    return bool(int(row[0]))


def set_feed_show_images(feed_id, value):
    """Set the per-feed image-alt override. value: None=inherit, True/False=override."""
    if not feed_id:
        return False
    stored = None if value is None else (1 if value else 0)
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE feeds SET show_images = ? WHERE id = ?", (stored, str(feed_id)))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_feed_settings(feed_id) -> dict:
    """Return the per-feed HTTP override settings as a dict (issue #29).

    Schema (all keys optional)::

        {
            "custom_headers": {"Header-Name": "value", ...},
            "timeout_seconds": <int> or None,
            "impersonate": "auto" | "always" | "never",
            "refresh_interval_seconds": <int> or None,
        }

    ``refresh_interval_seconds`` is the per-feed auto-refresh interval:
    None/absent follows the global ``refresh_interval`` setting, 0 means the
    feed is only refreshed manually.

    Always returns a dict; returns {} for an unknown feed, a NULL value, or
    malformed JSON.
    """
    if not feed_id:
        return {}
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT feed_settings FROM feeds WHERE id = ?", (str(feed_id),))
        row = c.fetchone()
    except sqlite3.Error:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row or row[0] is None:
        return {}
    try:
        data = json.loads(row[0])
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def set_feed_settings(feed_id, settings: dict) -> bool:
    """Persist the per-feed HTTP override settings (see get_feed_settings)."""
    if not feed_id:
        return False
    try:
        payload = json.dumps(settings if isinstance(settings, dict) else {})
    except (ValueError, TypeError):
        payload = "{}"
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE feeds SET feed_settings = ? WHERE id = ?", (payload, str(feed_id)))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_feed_refresh_interval_overrides() -> dict:
    """Return {feed_id: seconds} for every feed with a per-feed refresh interval.

    Seconds is a non-negative int; 0 means the feed is only refreshed manually
    (see get_feed_settings). Feeds without an override, or with malformed
    settings, are omitted.
    """
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, feed_settings FROM feeds WHERE feed_settings IS NOT NULL")
        rows = c.fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    overrides = {}
    for feed_id, payload in rows:
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        value = data.get("refresh_interval_seconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        overrides[str(feed_id)] = max(0, int(value))
    return overrides


# ── Per-feed update error tracking (issue #32) ───────────────────────────────
# Feeds break over time (moved/deleted content, dead URLs, server errors, feed
# format changes). These helpers persist the outcome of each update attempt so
# the "Feeds with Errors" view can show which feeds failed, when, why, and how
# many times in a row — letting the user fix or remove broken feeds instead of
# silently assuming they have no new articles.

def record_feed_error(feed_id, error_msg, when=None) -> bool:
    """Record that a feed's most recent update attempt failed (issue #32).

    Stores the error message and attempt timestamp and increments the
    consecutive-failure counter. Called by the local provider whenever a refresh
    ends in an error state.
    """
    if not feed_id:
        return False
    ts = float(when) if when is not None else time.time()
    msg = str(error_msg or "").strip() or "Unknown error"
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE feeds SET last_error = ?, last_error_at = ?, "
            "consecutive_failures = COALESCE(consecutive_failures, 0) + 1 "
            "WHERE id = ?",
            (msg, ts, str(feed_id)),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def clear_feed_error(feed_id, when=None) -> bool:
    """Clear a feed's recorded update error after a successful refresh (issue #32).

    Resets the error message and consecutive-failure counter and stamps the
    last successful update time so the feed drops out of the errors view.
    """
    if not feed_id:
        return False
    ts = float(when) if when is not None else time.time()
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE feeds SET last_error = NULL, last_error_at = NULL, "
            "last_success_at = ?, consecutive_failures = 0 WHERE id = ?",
            (ts, str(feed_id)),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_feed_errors() -> list:
    """Return feeds whose most recent update attempt failed (issue #32).

    Each entry is a dict with id, title, url, category, last_error,
    last_error_at, last_success_at, and consecutive_failures, ordered with the
    most-recently-failed feeds first. Returns [] when no feed has a recorded
    error (or on any DB error).
    """
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, title, url, category, last_error, last_error_at, "
            "last_success_at, COALESCE(consecutive_failures, 0) "
            "FROM feeds WHERE last_error IS NOT NULL AND TRIM(last_error) != '' "
            "ORDER BY COALESCE(last_error_at, 0) DESC"
        )
        rows = c.fetchall()
    except sqlite3.Error:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    errors = []
    for row in rows:
        errors.append({
            "id": row[0],
            "title": row[1] or "Untitled feed",
            "url": row[2] or "",
            "category": row[3] or UNCATEGORIZED,
            "last_error": row[4] or "",
            "last_error_at": row[5],
            "last_success_at": row[6],
            "consecutive_failures": int(row[7] or 0),
        })
    return errors


# ── Category path helpers ────────────────────────────────────────────────
# Local nested categories are identified by their full path (root -> leaf), e.g.
# "Podcasts / Others", so two subcategories that share a leaf name under
# different parents do not collide (issue #27). The path string is the stable
# identity stored in categories.title and feeds.category; only the leaf is shown
# in the UI. Flat providers never build paths, so their category names are
# single-segment and behave exactly as before.
CATEGORY_PATH_SEP = " / "


def make_category_path(parent_path, leaf):
    """Join a parent category path and a leaf title into a full category path."""
    leaf = str(leaf or "").strip()
    parent_path = str(parent_path or "").strip()
    if not parent_path:
        return leaf
    return f"{parent_path}{CATEGORY_PATH_SEP}{leaf}"


def category_display_leaf(path):
    """Return the leaf (last path segment) of a category path for display."""
    s = str(path or "")
    if CATEGORY_PATH_SEP in s:
        return s.rsplit(CATEGORY_PATH_SEP, 1)[-1]
    return s


def sanitize_category_leaf(leaf):
    """Strip the path separator out of a user-entered leaf name so it cannot
    corrupt the path encoding."""
    return str(leaf or "").strip().replace(CATEGORY_PATH_SEP, " - ")


def sync_categories(category_titles):
    """Ensure all category titles exist in the local categories table.

    This is used to mirror remote provider categories into the local DB
    so that subcategory hierarchy can be stored locally for any provider.
    """
    if not category_titles:
        return
    conn = get_connection()
    try:
        c = conn.cursor()
        for title in category_titles:
            if not title:
                continue
            c.execute(
                "INSERT OR IGNORE INTO categories (id, title) VALUES (?, ?)",
                (str(uuid.uuid4()), title),
            )
        conn.commit()
    except Exception as e:
        log.error(f"Error syncing categories: {e}")
    finally:
        conn.close()


def get_category_hierarchy():
    """Return a dict mapping category title -> parent category title (or None for top-level)."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT c.title, p.title FROM categories c LEFT JOIN categories p ON c.parent_id = p.id")
        rows = c.fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        log.error(f"Error getting category hierarchy: {e}")
        return {}
    finally:
        conn.close()


def set_category_parent(title, parent_title):
    """Set the parent of a category by title. Pass parent_title=None for top-level."""
    conn = get_connection()
    try:
        c = conn.cursor()
        if parent_title:
            c.execute("SELECT id FROM categories WHERE title = ?", (parent_title,))
            row = c.fetchone()
            parent_id = row[0] if row else None
        else:
            parent_id = None
        c.execute("UPDATE categories SET parent_id = ? WHERE title = ?", (parent_id, title))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        log.error(f"Error setting category parent: {e}")
        return False
    finally:
        conn.close()


def get_subcategory_titles(category_title):
    """Return all descendant category titles (recursive) for the given category."""
    conn = get_connection()
    try:
        c = conn.cursor()
        # Build parent_id -> title map and title -> id map
        c.execute("SELECT id, title, parent_id FROM categories")
        rows = c.fetchall()
        id_to_title = {r[0]: r[1] for r in rows}
        title_to_id = {r[1]: r[0] for r in rows}
        children_of = {}  # parent_id -> [child_titles]
        for r in rows:
            pid = r[2]
            if pid:
                children_of.setdefault(pid, []).append(r[1])

        result = []
        cat_id = title_to_id.get(category_title)
        if not cat_id:
            return result
        stack = [cat_id]
        while stack:
            pid = stack.pop()
            for child_title in children_of.get(pid, []):
                result.append(child_title)
                child_id = title_to_id.get(child_title)
                if child_id:
                    stack.append(child_id)
        return result
    except Exception as e:
        log.error(f"Error getting subcategory titles: {e}")
        return []
    finally:
        conn.close()
