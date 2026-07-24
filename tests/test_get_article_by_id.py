# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import shutil
import uuid
from pathlib import Path

import core.db
from providers.local import LocalProvider


def test_local_provider_get_article_by_id_returns_article_with_chapters():
    tmp_root = Path(".tmp_test")
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = tmp_root / f"test_get_article_by_id_{uuid.uuid4().hex}"
    tmp.mkdir(parents=True, exist_ok=True)

    orig_db_file = core.db.DB_FILE
    core.db.DB_FILE = os.path.join(str(tmp), "rss.db")
    try:
        core.db.init_db()

        feed_id = str(uuid.uuid4())
        article_id = str(uuid.uuid4())
        article_url = "https://example.com/posts/123"

        conn = core.db.get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
                (feed_id, "https://example.com/feed.xml", "Example Feed", "Uncategorized", ""),
            )
            c.execute(
                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article_id,
                    feed_id,
                    "Episode 123",
                    article_url,
                    "content",
                    "2026-02-01 10:00:00",
                    "Example Author",
                    0,
                    0,
                    "https://cdn.example.com/episode123.mp3",
                    "audio/mpeg",
                ),
            )
            c.execute(
                "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), article_id, 12.5, "Chapter One", ""),
            )
            c.execute(
                "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), article_id, 45.0, "Chapter Two", ""),
            )
            conn.commit()
        finally:
            conn.close()

        provider = LocalProvider(config={})
        article = provider.get_article_by_id(article_id)
        assert article is not None
        assert article.id == article_id
        assert article.feed_id == feed_id
        assert article.url == article_url
        assert article.media_url == "https://cdn.example.com/episode123.mp3"
        assert article.media_type == "audio/mpeg"
        assert [c["title"] for c in article.chapters] == ["Chapter One", "Chapter Two"]

        assert provider.get_article_by_id("missing-id") is None
    finally:
        core.db.DB_FILE = orig_db_file
        shutil.rmtree(tmp, ignore_errors=True)
