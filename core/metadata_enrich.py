# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Structured-metadata enrichment for articles (GUI-free).

Many feeds omit the author and the site's tags/categories even though the
article's web page carries them as structured data (JSON-LD ``Article``
schema, microdata, OpenGraph ``article:*`` properties). This module extracts
that metadata from page HTML the app has ALREADY downloaded for full-text
extraction — no extra network requests — and folds it into the stored article
row so Filter Rules matching on ``author``/``tag`` work on more feeds.

Extraction order (first hit wins per field):
    1. extruct: JSON-LD, then microdata, then OpenGraph.
    2. trafilatura.extract_metadata as the fallback.

Everything is best-effort and fail-closed: a missing extruct install, malformed
markup, or a DB hiccup returns empty results / False and never raises into the
callers (the full-text pipeline must keep working exactly as before).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Schema.org types whose author/keywords/articleSection describe the page's
# main article (JSON-LD @type values, case-sensitive per schema.org).
_ARTICLE_TYPES = {
    "Article", "NewsArticle", "BlogPosting", "Report", "ScholarlyArticle",
    "SocialMediaPosting", "TechArticle", "LiveBlogPosting", "ReportageNewsArticle",
}

_MAX_TAGS = 20
_MAX_TAG_LEN = 80


def _clean(value) -> str:
    return str(value or "").strip()


def _person_name(value) -> str:
    """Author fields appear as a string, a Person object, or a list of either."""
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        return _clean(value.get("name"))
    if isinstance(value, list):
        names = [n for n in (_person_name(v) for v in value) if n]
        return ", ".join(names[:3])
    return ""


def _keyword_list(value) -> list:
    """keywords/tags appear as a comma-separated string or a list of strings."""
    items = []
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, str):
                items.append(v)
            elif isinstance(v, dict):
                items.append(v.get("name") or "")
    out = []
    seen = set()
    for item in items:
        term = _clean(item)
        if not term or len(term) > _MAX_TAG_LEN:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= _MAX_TAGS:
            break
    return out


def _jsonld_nodes(data):
    """Flatten JSON-LD (including @graph containers) into candidate nodes."""
    stack = list(data) if isinstance(data, list) else [data]
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        graph = node.get("@graph")
        if isinstance(graph, list):
            stack.extend(graph)
        yield node


def _node_is_article(node) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return any(t in _ARTICLE_TYPES for t in node_type if isinstance(t, str))
    return node_type in _ARTICLE_TYPES


def _from_jsonld(data) -> dict:
    for node in _jsonld_nodes(data):
        if not _node_is_article(node):
            continue
        return {
            "author": _person_name(node.get("author")),
            "tags": _keyword_list(node.get("keywords")),
            "section": _clean(node.get("articleSection") if not isinstance(node.get("articleSection"), list)
                              else ", ".join(_keyword_list(node.get("articleSection")))),
        }
    return {}


def _from_microdata(items) -> dict:
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_type = _clean(item.get("type")).rsplit("/", 1)[-1]
        if item_type not in _ARTICLE_TYPES:
            continue
        props = item.get("properties") or {}
        return {
            "author": _person_name(props.get("author")),
            "tags": _keyword_list(props.get("keywords")),
            "section": _clean(props.get("articleSection") if not isinstance(props.get("articleSection"), list)
                              else ", ".join(_keyword_list(props.get("articleSection")))),
        }
    return {}


def _from_opengraph(og_items) -> dict:
    """extruct's opengraph output: list of {'namespace':…, 'properties': [(k, v), …]}."""
    for item in og_items or []:
        props = item.get("properties") if isinstance(item, dict) else None
        if not props:
            continue
        author = ""
        tags = []
        section = ""
        for key, value in props:
            if key == "article:author" and not author:
                # Often a profile URL, only useful when it reads like a name.
                candidate = _clean(value)
                if candidate and "://" not in candidate:
                    author = candidate
            elif key == "article:tag":
                term = _clean(value)
                if term and len(term) <= _MAX_TAG_LEN and term.lower() not in {t.lower() for t in tags}:
                    tags.append(term)
            elif key == "article:section" and not section:
                section = _clean(value)
        if author or tags or section:
            return {"author": author, "tags": tags[:_MAX_TAGS], "section": section}
    return {}


def _merge_meta(base: dict, extra: dict) -> dict:
    out = dict(base)
    if not out.get("author") and extra.get("author"):
        out["author"] = extra["author"]
    if not out.get("section") and extra.get("section"):
        out["section"] = extra["section"]
    have = {t.lower() for t in out.get("tags") or []}
    merged = list(out.get("tags") or [])
    for term in extra.get("tags") or []:
        if term.lower() not in have and len(merged) < _MAX_TAGS:
            have.add(term.lower())
            merged.append(term)
    out["tags"] = merged
    return out


def _meta_complete(meta: dict) -> bool:
    return bool(meta.get("author")) and bool(meta.get("tags")) and bool(meta.get("section"))


def extract_page_metadata(html, url: str = "") -> dict:
    """Extract ``{"author": str, "tags": [str], "section": str}`` from page HTML.

    Never raises; returns empty fields when nothing is found or the optional
    extractors are unavailable.
    """
    meta = {"author": "", "tags": [], "section": ""}
    html = str(html or "")
    if not html.strip():
        return meta

    try:
        import extruct  # optional dependency; fail closed without it
        data = extruct.extract(
            html,
            base_url=str(url or "") or None,
            syntaxes=["json-ld", "microdata", "opengraph"],
            errors="ignore",
        )
        meta = _merge_meta(meta, _from_jsonld(data.get("json-ld") or []))
        if not _meta_complete(meta):
            meta = _merge_meta(meta, _from_microdata(data.get("microdata") or []))
        if not _meta_complete(meta):
            meta = _merge_meta(meta, _from_opengraph(data.get("opengraph") or []))
    except Exception:
        log.debug("extruct metadata extraction failed for %s", url, exc_info=True)

    if not _meta_complete(meta):
        try:
            import trafilatura
            tmeta = trafilatura.extract_metadata(html, default_url=str(url or "") or None)
            if tmeta is not None:
                extra = {
                    "author": _clean(getattr(tmeta, "author", "")),
                    "tags": _keyword_list(list(getattr(tmeta, "tags", None) or [])
                                          + list(getattr(tmeta, "categories", None) or [])),
                    "section": "",
                }
                meta = _merge_meta(meta, extra)
        except Exception:
            log.debug("trafilatura metadata extraction failed for %s", url, exc_info=True)

    return meta


def merge_tag_string(existing, new_tags) -> str:
    """Union newline-separated stored tags with newly found ones (order kept)."""
    out = []
    seen = set()
    for term in str(existing or "").split("\n"):
        term = _clean(term)
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    for term in new_tags or []:
        term = _clean(term)
        if term and term.lower() not in seen and len(out) < _MAX_TAGS * 2:
            seen.add(term.lower())
            out.append(term)
    return "\n".join(out)


def _author_is_placeholder(author) -> bool:
    return _clean(author).lower() in ("", "unknown", "(unknown)")


def enrich_stored_article(article_id, html, url: str = "") -> bool:
    """Fold page metadata into the stored local article row.

    Fills ``author`` only when the stored value is empty/"Unknown" and merges
    the page's tags + section into ``articles.tags``. Returns True when the row
    changed. Never raises.
    """
    aid = _clean(article_id)
    if not aid or not str(html or "").strip():
        return False
    meta = extract_page_metadata(html, url)
    found_tags = list(meta.get("tags") or [])
    if meta.get("section"):
        found_tags.append(meta["section"])
    if not meta.get("author") and not found_tags:
        return False

    try:
        from core.db import get_connection
        conn = get_connection()
        try:
            # Best-effort enrichment: don't inherit the 60s default busy
            # timeout. During a refresh the write lock is held nearly
            # continuously and waiting that long just stacks threads — a
            # missed enrichment is retried on the article's next extraction.
            try:
                conn.execute("PRAGMA busy_timeout=5000")
            except Exception:
                pass
            c = conn.cursor()
            row = c.execute("SELECT author, tags FROM articles WHERE id = ?", (aid,)).fetchone()
            if not row:
                return False
            stored_author, stored_tags = row[0], row[1]
            sets = []
            params = []
            if meta.get("author") and _author_is_placeholder(stored_author):
                sets.append("author = ?")
                params.append(meta["author"])
            if found_tags:
                merged = merge_tag_string(stored_tags, found_tags)
                if merged != _clean(stored_tags):
                    sets.append("tags = ?")
                    params.append(merged)
            if not sets:
                return False
            params.append(aid)
            c.execute(f"UPDATE articles SET {', '.join(sets)} WHERE id = ?", tuple(params))
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        log.debug("Article metadata enrichment failed for %s", aid, exc_info=True)
        return False
