# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Resolve the language to mark article content with (issue #72).

The rich reader used to render every article as ``<html lang="en">``, so a
screen reader read Russian, Greek or Hebrew content with an English voice, an
English Braille table and English character names, and bidirectional text could
lay out wrongly. Marking content with its real language is what lets assistive
tech pick the right synthesizer, table and direction.

Priority (highest first), per issue #72:

1. the target language of BlindRSS's automatic translation, when the shown text
   was translated;
2. the ``lang``/``xml:lang`` of the source page's ``<html>`` element;
3. the feed's declared language (``xml:lang`` on the item, else the channel's
   ``<language>``);
4. BlindRSS's active UI language.

This module is GUI-free so the priority logic is testable without wx.
"""

from __future__ import annotations

import re
from typing import Optional

# lang="..." / xml:lang="..." on the opening <html> tag. Deliberately a regex on
# the raw markup rather than a parse: this runs on every rich render, the
# attribute is in the first few hundred bytes, and a full soup of a large page
# purely to read one attribute is waste.
_HTML_TAG_RE = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
_LANG_ATTR_RE = re.compile(
    r"""\b(?:xml:)?lang\s*=\s*["']?\s*([A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*)""",
    re.IGNORECASE,
)

# BCP-47 shape: primary subtag, optional subtags. Enough to reject junk like
# "unknown", "", "{{lang}}" or a whole sentence without pulling in a registry.
_BCP47_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

DEFAULT_LANG = "en"


def normalize_lang(value) -> Optional[str]:
    """Return a clean BCP-47 tag, or None if ``value`` is not usable.

    Accepts the gettext/POSIX spellings that turn up in feeds and catalogs
    ("pt_BR", "ru_RU.UTF-8", "en-US") and normalizes them to a hyphenated tag.
    Returns None rather than guessing: a wrong lang is worse than none, since it
    actively points assistive tech at the wrong synthesizer.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Drop a POSIX charset/modifier suffix: "ru_RU.UTF-8@petr1708" -> "ru_RU".
    text = re.split(r"[.@]", text, maxsplit=1)[0]
    text = text.replace("_", "-").strip("-")
    if not text or not _BCP47_RE.match(text):
        return None
    parts = text.split("-")
    # Canonical casing: language lowercase, region uppercase, script Titlecase.
    out = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 2:
            out.append(part.upper())
        elif len(part) == 4:
            out.append(part.capitalize())
        else:
            out.append(part.lower())
    return "-".join(out)


def lang_from_page_html(page_html) -> Optional[str]:
    """Language declared by a source page's ``<html>`` tag, or None (rule 2)."""
    if not isinstance(page_html, str) or not page_html:
        return None
    match = _HTML_TAG_RE.search(page_html)
    if not match:
        return None
    attr = _LANG_ATTR_RE.search(match.group(0))
    if not attr:
        return None
    return normalize_lang(attr.group(1))


def app_ui_language() -> str:
    """BlindRSS's active UI language (rule 4) -- always a usable tag."""
    try:
        from core import i18n

        return normalize_lang(i18n.current_language()) or DEFAULT_LANG
    except Exception:
        return DEFAULT_LANG


def resolve_content_language(
    *,
    translation_target: Optional[str] = None,
    page_html: Optional[str] = None,
    page_lang: Optional[str] = None,
    feed_item_lang: Optional[str] = None,
    feed_lang: Optional[str] = None,
    fallback: Optional[str] = None,
) -> str:
    """Pick the content language by issue #72's priority order.

    Every source is optional; the first that normalizes to a usable tag wins.
    ``page_html`` is a convenience for rule 2 (the raw source page). ``fallback``
    defaults to the app UI language (rule 4), which is why this always returns a
    tag rather than None -- the document must be marked with *something*, and an
    unmarked document is what the bug was.
    """
    candidates = [
        translation_target,          # 1. what the text was translated INTO
        page_lang,                   # 2. explicit page language
        lang_from_page_html(page_html) if page_html else None,
        feed_item_lang,              # 3a. per-item xml:lang
        feed_lang,                   # 3b. channel <language>
        fallback,                    # 4. caller's fallback
    ]
    for candidate in candidates:
        normalized = normalize_lang(candidate)
        if normalized:
            return normalized
    return app_ui_language()
