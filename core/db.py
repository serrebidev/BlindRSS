import sqlite3
import os
import shutil
import logging
import uuid
from core.config import APP_DIR, USER_DATA_DIR, get_data_dir

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
                shutil.copy2(src, target)
                for sidecar in ("-wal", "-shm", "-journal"):
                    side_src = src + sidecar
                    if os.path.exists(side_src):
                        try:
                            shutil.copy2(side_src, target + sidecar)
                        except Exception:
                            log.exception("Failed to copy sqlite sidecar %s", side_src)
                log.info("Migrated rss.db from %s to %s", src, target)
                return target
        except Exception:
            log.exception("Failed while migrating rss.db from %s", src)
    return target


def _table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (name,),
    )
    return cursor.fetchone() is not None


def _chapters_references_old_articles(cursor: sqlite3.Cursor) -> bool:
    try:
        cursor.execute("PRAGMA foreign_key_list(chapters)")
        rows = cursor.fetchall()
    except sqlite3.Error:
        return False
    return any(len(row) > 2 and row[2] == "old_articles" for row in rows)


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


def _migrate_legacy_chapters_foreign_key(conn: sqlite3.Connection) -> None:
    """Repair legacy schemas where `chapters` references `old_articles`.

    Older databases used a `chapters.article_id -> old_articles(id)` foreign key.
    With foreign key enforcement enabled, deletes/updates on chapters can fail with:
        "no such table: main.old_articles"

    Prefer migrating the FK to `articles(id)` when possible; otherwise drop the FK.
    """

    cursor = conn.cursor()
    if not _table_exists(cursor, "chapters"):
        return

    if not _chapters_references_old_articles(cursor):
        return

    try:
        cursor.execute("SAVEPOINT migrate_chapters_old_articles_fk")

        can_add_fk = _articles_id_is_unique(cursor)
        if not can_add_fk:
            try:
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_id_unique ON articles (id)"
                )
            except sqlite3.Error as e:
                log.debug("Could not create unique index on articles(id) during migration: %s", e)
            can_add_fk = _articles_id_is_unique(cursor)

        prev_fk_setting = None
        try:
            cursor.execute("PRAGMA foreign_keys")
            row = cursor.fetchone()
            prev_fk_setting = int(row[0]) if row and row[0] is not None else None
        except sqlite3.Error:
            prev_fk_setting = None

        try:
            cursor.execute("PRAGMA foreign_keys=OFF")

            backup_name = "chapters_old"
            suffix = 0
            while _table_exists(cursor, backup_name):
                suffix += 1
                backup_name = f"chapters_old_{suffix}"

            log.warning(
                "Migrating legacy chapters FK old_articles -> %s (backup table: %s)",
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
                        FOREIGN KEY(article_id) REFERENCES articles(id)
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
        finally:
            if prev_fk_setting is not None:
                try:
                    cursor.execute(f"PRAGMA foreign_keys={prev_fk_setting}")
                except sqlite3.Error:
                    pass

        cursor.execute("RELEASE SAVEPOINT migrate_chapters_old_articles_fk")
    except sqlite3.Error:
        try:
            cursor.execute("ROLLBACK TO SAVEPOINT migrate_chapters_old_articles_fk")
            cursor.execute("RELEASE SAVEPOINT migrate_chapters_old_articles_fk")
        except sqlite3.Error:
            pass
        log.exception("Failed to migrate legacy chapters FK from old_articles; leaving schema unchanged")


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
            date TEXT,
            author TEXT,
            is_read INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            media_url TEXT,
            media_type TEXT,
            chapter_url TEXT,
            FOREIGN KEY(feed_id) REFERENCES feeds(id)
        )''')
        
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_feed_id ON articles (feed_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_is_read ON articles (is_read)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_date ON articles (date)")
        # Composite indexes to speed up common paging/count queries on larger databases.
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_is_read_feed_id ON articles (is_read, feed_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_date_id ON articles (date, id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_articles_feed_id_date_id ON articles (feed_id, date, id)")

        c.execute('''CREATE TABLE IF NOT EXISTS chapters (
            id TEXT PRIMARY KEY,
            article_id TEXT,
            start REAL,
            title TEXT,
            href TEXT,
            FOREIGN KEY(article_id) REFERENCES articles(id)
        )''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_chapters_article_id_start ON chapters (article_id, start)")

        _migrate_legacy_chapters_foreign_key(conn)

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

        # Migration: add parent_id to categories for subcategory support
        try:
            c.execute("ALTER TABLE categories ADD COLUMN parent_id TEXT")
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
            c.execute("INSERT OR IGNORE INTO categories (id, title) VALUES (?, ?)", ("uncategorized", "Uncategorized"))
        
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
        
        if keep_favorites:
            where_clauses.append("is_favorite = 0")
            
        where_str = " AND ".join(where_clauses)
        
        # 1. Delete chapters for these articles first (no CASCADE support guaranteed)
        # We can use subquery: DELETE FROM chapters WHERE article_id IN (SELECT id FROM articles WHERE ...)
        
        subquery = f"SELECT id FROM articles WHERE {where_str}"
        
        c = conn.cursor()
        c.execute(f"DELETE FROM chapters WHERE article_id IN ({subquery})")
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


def get_connection():
    conn = sqlite3.connect(_active_db_path(), timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception as e:
        log.warning(f"Failed to set PRAGMAs on connection: {e}")
    return conn


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
