# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Structured-metadata enrichment (core.metadata_enrich): extruct JSON-LD /
OpenGraph parsing, trafilatura fallback, tag merging, and the DB update that
fills author/tags for Filter Rules matching."""
import pytest

from core import db
from core import metadata_enrich as me

# mf2py (pulled in by extruct) calls codecs.open(), deprecated by Python 3.14.
# Third-party, not fixable here. pytest.ini already ignores it, but a plain
# "-W default" on the command line outranks ini filters -- this mark outranks
# the command line, keeping ad-hoc "-W default" runs warning-free too.
pytestmark = pytest.mark.filterwarnings(
    r"ignore:codecs\.open\(\) is deprecated:DeprecationWarning:mf2py\.backcompat"
)


JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "Test Story",
  "author": {"@type": "Person", "name": "Ada Lovelace"},
  "keywords": "computing, history, engines",
  "articleSection": "Technology"
}
</script>
</head><body><p>Body text.</p></body></html>
"""

OPENGRAPH_HTML = """
<html><head prefix="og: http://ogp.me/ns# article: http://ogp.me/ns/article#">
<meta property="og:type" content="article" />
<meta property="og:title" content="OG Story" />
<meta property="article:tag" content="python" />
<meta property="article:tag" content="testing" />
<meta property="article:section" content="Dev" />
</head><body><p>Body.</p></body></html>
"""


def test_jsonld_article_metadata():
    meta = me.extract_page_metadata(JSONLD_HTML, "https://example.com/story")
    assert meta["author"] == "Ada Lovelace"
    assert meta["tags"] == ["computing", "history", "engines"]
    assert meta["section"] == "Technology"


def test_opengraph_tags_and_section():
    meta = me.extract_page_metadata(OPENGRAPH_HTML, "https://example.com/og")
    assert "python" in meta["tags"] and "testing" in meta["tags"]
    assert meta["section"] == "Dev"


def test_empty_html_is_safe():
    meta = me.extract_page_metadata("", "https://example.com")
    assert meta == {"author": "", "tags": [], "section": ""}
    # Garbage input must not raise either.
    meta = me.extract_page_metadata("<<<not html>>>", "")
    assert isinstance(meta, dict)


def test_merge_tag_string_unions_case_insensitively():
    merged = me.merge_tag_string("Python\nNews", ["python", "Testing"])
    assert merged == "Python\nNews\nTesting"
    assert me.merge_tag_string("", ["a", "b"]) == "a\nb"
    assert me.merge_tag_string(None, []) == ""


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO feeds (id, url, title, category) VALUES ('f1', 'u', 'Feed', 'News')")
        conn.execute(
            "INSERT INTO articles (id, feed_id, title, url, author, tags, is_read, is_favorite) "
            "VALUES ('a1', 'f1', 'T', 'https://example.com/story', 'Unknown', 'existing', 0, 0)"
        )
        conn.commit()
    finally:
        conn.close()
    return db


def test_enrich_stored_article_fills_author_and_merges_tags(temp_db):
    changed = me.enrich_stored_article("a1", JSONLD_HTML, "https://example.com/story")
    assert changed is True
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT author, tags FROM articles WHERE id='a1'").fetchone()
    finally:
        conn.close()
    assert row[0] == "Ada Lovelace"          # placeholder replaced
    tags = row[1].split("\n")
    assert "existing" in tags                 # stored tags preserved
    assert "computing" in tags and "Technology" in tags  # keywords + section merged


def test_enrich_never_overwrites_real_author(temp_db):
    conn = db.get_connection()
    try:
        conn.execute("UPDATE articles SET author='Real Person' WHERE id='a1'")
        conn.commit()
    finally:
        conn.close()
    me.enrich_stored_article("a1", JSONLD_HTML, "https://example.com/story")
    conn = db.get_connection()
    try:
        author = conn.execute("SELECT author FROM articles WHERE id='a1'").fetchone()[0]
    finally:
        conn.close()
    assert author == "Real Person"


def test_enrich_missing_article_is_noop(temp_db):
    assert me.enrich_stored_article("nope", JSONLD_HTML) is False
    assert me.enrich_stored_article("", JSONLD_HTML) is False
    assert me.enrich_stored_article("a1", "") is False
