import os
import sqlite3
import tempfile
import uuid

import core.db


def _create_legacy_db_with_old_articles_fk(db_path: str, *, duplicate_article_ids: bool) -> str:
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute("PRAGMA foreign_keys=OFF")

        c.execute(
            """
            CREATE TABLE feeds (
                id TEXT PRIMARY KEY,
                url TEXT,
                title TEXT,
                category TEXT,
                icon_url TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE articles (
                id TEXT,
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
                PRIMARY KEY (id, feed_id),
                FOREIGN KEY(feed_id) REFERENCES feeds(id)
            )
            """
        )
        c.execute(
            """
            CREATE TABLE chapters (
                id TEXT PRIMARY KEY,
                article_id TEXT,
                start REAL,
                title TEXT,
                href TEXT,
                FOREIGN KEY(article_id) REFERENCES "old_articles"(id)
            )
            """
        )

        feed_id = str(uuid.uuid4())
        other_feed_id = str(uuid.uuid4())
        article_id = str(uuid.uuid4())
        chapter_id = str(uuid.uuid4())

        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, "https://example.com/rss", "Feed 1", "Uncategorized", ""),
        )
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (other_feed_id, "https://example.com/rss2", "Feed 2", "Uncategorized", ""),
        )

        c.execute(
            "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                article_id,
                feed_id,
                "Episode 1",
                "https://example.com/post/1",
                "content",
                "2025-01-01 00:00:00",
                "author",
                0,
                0,
                "https://example.com/audio.mp3",
                "audio/mpeg",
            ),
        )
        if duplicate_article_ids:
            c.execute(
                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article_id,
                    other_feed_id,
                    "Episode 2",
                    "https://example.com/post/2",
                    "content",
                    "2025-01-01 00:00:00",
                    "author",
                    0,
                    0,
                    "https://example.com/other.mp3",
                    "audio/mpeg",
                ),
            )

        c.execute(
            "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
            (chapter_id, article_id, 0.0, "Intro", ""),
        )
        conn.commit()
        return feed_id
    finally:
        conn.close()


def test_init_db_migrates_legacy_chapters_fk_old_articles_to_articles():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            feed_id = _create_legacy_db_with_old_articles_fk(core.db.DB_FILE, duplicate_article_ids=False)

            core.db.init_db()

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute("PRAGMA foreign_key_list(chapters)")
                fk_rows = c.fetchall()
                assert not any(row[2] == "old_articles" for row in fk_rows)
                assert any(row[2] == "articles" for row in fk_rows)

                # The original bug manifested during deletes from chapters with FK enforcement enabled.
                c.execute("BEGIN")
                c.execute(
                    "DELETE FROM chapters WHERE article_id IN (SELECT id FROM articles WHERE feed_id = ?)",
                    (feed_id,),
                )
                conn.rollback()
            finally:
                conn.close()
        finally:
            core.db.DB_FILE = orig_db_file


def test_init_db_migrates_legacy_chapters_fk_old_articles_without_unique_articles_id():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            feed_id = _create_legacy_db_with_old_articles_fk(core.db.DB_FILE, duplicate_article_ids=True)

            core.db.init_db()

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute("PRAGMA foreign_key_list(chapters)")
                fk_rows = c.fetchall()
                assert not any(row[2] == "old_articles" for row in fk_rows)
                assert fk_rows == []

                c.execute("BEGIN")
                c.execute(
                    "DELETE FROM chapters WHERE article_id IN (SELECT id FROM articles WHERE feed_id = ?)",
                    (feed_id,),
                )
                conn.rollback()
            finally:
                conn.close()
        finally:
            core.db.DB_FILE = orig_db_file


def test_init_db_respects_explicit_db_file_override_without_migrating_app_db():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            core.db.init_db()

            assert os.path.abspath(core.db.DB_FILE) == os.path.abspath(os.path.join(tmp, "rss.db"))

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM feeds")
                assert c.fetchone()[0] == 0
                c.execute("SELECT COUNT(*) FROM articles")
                assert c.fetchone()[0] == 0
            finally:
                conn.close()
        finally:
            core.db.DB_FILE = orig_db_file

