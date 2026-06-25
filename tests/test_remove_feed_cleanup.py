import os
import tempfile
import uuid

import core.db
from providers.local import LocalProvider


def test_local_provider_remove_feed_deletes_dependent_rows():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            core.db.init_db()

            feed_id = str(uuid.uuid4())
            other_feed_id = str(uuid.uuid4())
            article_id = str(uuid.uuid4())
            other_article_id = str(uuid.uuid4())

            media_url = "https://example.com/audio.mp3"
            article_url = "https://example.com/post/1"
            other_media_url = "https://example.com/other.mp3"

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
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
                        article_url,
                        "content",
                        "2025-01-01 00:00:00",
                        "author",
                        0,
                        0,
                        media_url,
                        "audio/mpeg",
                    ),
                )
                c.execute(
                    "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        other_article_id,
                        other_feed_id,
                        "Episode 2",
                        "https://example.com/post/2",
                        "content",
                        "2025-01-01 00:00:00",
                        "author",
                        0,
                        0,
                        other_media_url,
                        "audio/mpeg",
                    ),
                )
                c.execute(
                    "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), article_id, 0.0, "Intro", ""),
                )
                local_chapter_key = f"local:{article_id}"
                c.execute(
                    "INSERT INTO chapter_cache (id, cache_key, start, title, href) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), local_chapter_key, 0.0, "Cached intro", ""),
                )
                c.execute(
                    "INSERT INTO chapter_sources "
                    "(cache_key, source_url, etag, last_modified, checked_at, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        local_chapter_key,
                        "https://example.com/chapters.json",
                        '"etag"',
                        None,
                        1,
                        1,
                    ),
                )
                # playback_state uses multiple key formats (article:<id> preferred, plus URL fallbacks).
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"article:{article_id}", 1234, 9999, 1, 0, 1, "Episode 1"),
                )
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (media_url, 2345, 9999, 1, 0, 1, "Episode 1"),
                )
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (article_url, 3456, 9999, 1, 0, 1, "Episode 1"),
                )
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"article:{other_article_id}", 111, 222, 1, 0, 1, "Episode 2"),
                )
                conn.commit()
            finally:
                conn.close()

            provider = LocalProvider(config={})
            assert provider.remove_feed(feed_id) is True

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM feeds WHERE id = ?", (feed_id,))
                assert c.fetchone()[0] == 0

                c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (feed_id,))
                assert c.fetchone()[0] == 0

                c.execute("SELECT COUNT(*) FROM chapters WHERE article_id = ?", (article_id,))
                assert c.fetchone()[0] == 0
                c.execute("SELECT COUNT(*) FROM chapter_cache WHERE cache_key = ?", (local_chapter_key,))
                assert c.fetchone()[0] == 0
                c.execute("SELECT COUNT(*) FROM chapter_sources WHERE cache_key = ?", (local_chapter_key,))
                assert c.fetchone()[0] == 0

                for pid in (f"article:{article_id}", media_url, article_url):
                    c.execute("SELECT COUNT(*) FROM playback_state WHERE id = ?", (pid,))
                    assert c.fetchone()[0] == 0

                c.execute("SELECT COUNT(*) FROM feeds WHERE id = ?", (other_feed_id,))
                assert c.fetchone()[0] == 1
                c.execute("SELECT COUNT(*) FROM playback_state WHERE id = ?", (f"article:{other_article_id}",))
                assert c.fetchone()[0] == 1
            finally:
                conn.close()
        finally:
            core.db.DB_FILE = orig_db_file


def test_local_provider_remove_feed_preserves_shared_url_playback_state():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            core.db.init_db()

            feed_id = str(uuid.uuid4())
            other_feed_id = str(uuid.uuid4())
            article_id = str(uuid.uuid4())
            other_article_id = str(uuid.uuid4())

            shared_media_url = "https://example.com/shared.mp3"
            article_url = "https://example.com/post/1"

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
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
                        article_url,
                        "content",
                        "2025-01-01 00:00:00",
                        "author",
                        0,
                        0,
                        shared_media_url,
                        "audio/mpeg",
                    ),
                )
                c.execute(
                    "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        other_article_id,
                        other_feed_id,
                        "Episode 2",
                        "https://example.com/post/2",
                        "content",
                        "2025-01-01 00:00:00",
                        "author",
                        0,
                        0,
                        shared_media_url,
                        "audio/mpeg",
                    ),
                )
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (shared_media_url, 2345, 9999, 1, 0, 1, "Shared"),
                )
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (article_url, 3456, 9999, 1, 0, 1, "Episode 1"),
                )
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"article:{article_id}", 1234, 9999, 1, 0, 1, "Episode 1"),
                )
                c.execute(
                    "INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"article:{other_article_id}", 111, 222, 1, 0, 1, "Episode 2"),
                )
                conn.commit()
            finally:
                conn.close()

            provider = LocalProvider(config={})
            assert provider.remove_feed(feed_id) is True

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                # Feed-specific keys should be removed.
                c.execute("SELECT COUNT(*) FROM playback_state WHERE id = ?", (f"article:{article_id}",))
                assert c.fetchone()[0] == 0
                c.execute("SELECT COUNT(*) FROM playback_state WHERE id = ?", (article_url,))
                assert c.fetchone()[0] == 0

                # Shared URL key should remain because it's still referenced by other_feed_id.
                c.execute("SELECT COUNT(*) FROM playback_state WHERE id = ?", (shared_media_url,))
                assert c.fetchone()[0] == 1

                c.execute("SELECT COUNT(*) FROM feeds WHERE id = ?", (other_feed_id,))
                assert c.fetchone()[0] == 1
                c.execute("SELECT COUNT(*) FROM playback_state WHERE id = ?", (f"article:{other_article_id}",))
                assert c.fetchone()[0] == 1
            finally:
                conn.close()
        finally:
            core.db.DB_FILE = orig_db_file
