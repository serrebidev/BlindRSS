# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Feeds remember the language they declare (issue #72, rule 3).

The rich reader marks content with the feed's declared language when the source
page offers none. That needs the language to survive to the DB, so these cover
the column/migration and the normalization applied on the way in.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import article_lang, db
from core.models import Feed


@pytest.fixture
def temp_db(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr(db, "DB_FILE", os.path.join(tmpdir, "rss.db"))
    db.init_db()
    yield db


def _add_feed(conn, feed_id, language=None):
    conn.execute(
        "INSERT INTO feeds (id, title, url, category, language) VALUES (?, ?, ?, ?, ?)",
        (feed_id, "T", f"https://example.com/{feed_id}", "News", language),
    )
    conn.commit()


def test_feeds_table_has_a_language_column(temp_db):
    conn = temp_db.get_connection()
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(feeds)")}
        assert "language" in cols
    finally:
        conn.close()


def test_language_round_trips_and_defaults_to_null(temp_db):
    conn = temp_db.get_connection()
    try:
        _add_feed(conn, "f-ru", "ru")
        _add_feed(conn, "f-none", None)
        rows = dict(conn.execute("SELECT id, language FROM feeds"))
        assert rows["f-ru"] == "ru"
        # NULL, not "" or "en": "the feed never said" is a real answer that the
        # resolver needs in order to fall through to the UI language.
        assert rows["f-none"] is None
    finally:
        conn.close()


def test_migration_adds_language_to_a_preexisting_feeds_table(monkeypatch):
    """Upgrades must not fail or drop data on an older DB."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "rss.db")
    monkeypatch.setattr(db, "DB_FILE", path)

    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE feeds (id TEXT PRIMARY KEY, url TEXT, title TEXT, "
        "title_is_custom INTEGER DEFAULT 0, category TEXT, icon_url TEXT)"
    )
    conn.execute("INSERT INTO feeds (id, title, url) VALUES ('old', 'Old', 'u')")
    conn.commit()
    conn.close()

    db.init_db()  # runs the ALTER TABLE migration

    conn = db.get_connection()
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(feeds)")}
        assert "language" in cols
        row = conn.execute("SELECT title, language FROM feeds WHERE id='old'").fetchone()
        assert row[0] == "Old"        # pre-existing data intact
        assert row[1] is None         # new column defaults to "not declared"
    finally:
        conn.close()


def test_init_db_is_idempotent(temp_db):
    """The ALTER runs on every startup; the second one must be a no-op."""
    temp_db.init_db()
    temp_db.init_db()
    conn = temp_db.get_connection()
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(feeds)")]
        assert cols.count("language") == 1
    finally:
        conn.close()


def test_feed_model_defaults_language_to_none():
    """Providers with no language field (e.g. Miniflux) just omit it."""
    assert Feed(id="1", title="T", url="u").language is None
    assert Feed(id="1", title="T", url="u", language="ru").language == "ru"


class TestRefreshNormalization:
    """The value stored is what article_lang.normalize_lang makes of the feed's
    raw declaration -- feeds spell languages inconsistently."""

    def test_common_feed_spellings(self):
        assert article_lang.normalize_lang("ru") == "ru"
        assert article_lang.normalize_lang("en-US") == "en-US"
        assert article_lang.normalize_lang("pt-br") == "pt-BR"

    def test_junk_declarations_become_none_not_a_bad_tag(self):
        # A feed saying nothing useful must store NULL, so the reader falls back
        # rather than pointing a screen reader at the wrong synthesizer.
        for junk in (None, "", "  ", "unknown", "x-default-lang-please-set"):
            assert article_lang.normalize_lang(junk) is None
