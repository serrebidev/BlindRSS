# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import uuid
import tempfile

import core.db
from providers.local import LocalProvider


def test_local_provider_favorites_toggle_and_view():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        try:
            core.db.init_db()

            feed_id = str(uuid.uuid4())
            article_id = str(uuid.uuid4())

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
                    (feed_id, "https://example.com/rss", "Example", "Uncategorized", ""),
                )
                c.execute(
                    "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        article_id,
                        feed_id,
                        "Hello",
                        "https://example.com/hello",
                        "content",
                        "2025-01-01 00:00:00",
                        "author",
                        0,
                        0,
                        None,
                        None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            provider = LocalProvider(config={})
            assert provider.supports_favorites() is True

            favorites, total = provider.get_articles_page("favorites:all", offset=0, limit=50)
            assert favorites == []
            assert total == 0

            new_state = provider.toggle_favorite(article_id)
            assert new_state is True

            favorites, total = provider.get_articles_page("favorites:all", offset=0, limit=50)
            assert total == 1
            assert len(favorites) == 1
            assert favorites[0].id == article_id
            assert favorites[0].is_favorite is True

            all_articles, total_all = provider.get_articles_page("all", offset=0, limit=50)
            assert total_all == 1
            assert len(all_articles) == 1
            assert all_articles[0].id == article_id
            assert all_articles[0].is_favorite is True

            new_state = provider.toggle_favorite(article_id)
            assert new_state is False

            favorites, total = provider.get_articles_page("favorites:all", offset=0, limit=50)
            assert favorites == []
            assert total == 0
        finally:
            core.db.DB_FILE = orig_db_file

