# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import requests
import re
import uuid
import logging
import sqlite3
import json
import ipaddress
import math
import os
import socket
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from bs4 import BeautifulSoup as BS
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser
from dateutil.parser import UnknownTimezoneWarning
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from core.categories import UNCATEGORIZED
from core.db import CATEGORY_PATH_SEP, get_connection, make_category_path, sanitize_category_leaf
import warnings
import urllib.parse
import sys
import shlex
from core.i18n import _, ngettext

log = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=UnknownTimezoneWarning)

# Optional browser-TLS impersonation transport. Some anti-bot WAFs (e.g. APKMirror,
# Grav -- issue #29) reset the TCP/TLS connection when a request's TLS/HTTP
# fingerprint doesn't look like a real browser. When curl_cffi is installed we can
# replay Chrome's fingerprint to get past them. The import is optional so the app
# keeps working (via plain requests) when curl_cffi isn't available.
IMPERSONATE_TARGET = "chrome"
try:
    from curl_cffi import requests as _curl_requests
    _CURL_REQUESTS = _curl_requests
    CURL_CFFI_AVAILABLE = True
except Exception:
    _curl_requests = None
    _CURL_REQUESTS = None
    CURL_CFFI_AVAILABLE = False

# Per-thread transport sessions so a refresh worker's sequential feed fetches (esp.
# repeat hosts -- multi-feed YouTube/news subscriptions) reuse a warm TCP/TLS
# connection instead of paying a fresh handshake on every single call, which is
# what bare requests.get()/curl_cffi.requests.get() do internally (each opens a
# throwaway Session/pool and tears it down before returning). Keyed by object
# identity of the current `requests`/`_CURL_REQUESTS` binding (not just "is it set")
# so tests that monkeypatch those names still get an isolated fake per test.
_transport_local = threading.local()


def _get_plain_session():
    owner = requests
    if getattr(_transport_local, "plain_owner", None) is not owner:
        _transport_local.plain_session = owner.Session()
        _transport_local.plain_owner = owner
    return _transport_local.plain_session


def _get_curl_session():
    owner = _CURL_REQUESTS
    if getattr(_transport_local, "curl_owner", None) is not owner:
        _transport_local.curl_session = owner.Session()
        _transport_local.curl_owner = owner
    return _transport_local.curl_session


def platform_supports_notifications() -> bool:
    """True on platforms where `wx.adv.NotificationMessage` shows native banners.

    Windows (toast) and macOS (Notification Center) are supported. Linux/libnotify
    is intentionally excluded for now since delivery there is inconsistent.
    """
    return sys.platform.startswith("win") or sys.platform.startswith("darwin")

HEADERS = {
    # Placeholder only. The User-Agent and its sec-ch-ua* hints are stamped in
    # below from core.user_agents, and restamped from config at startup. Never
    # hard-code a version here: a UA frozen at a long-past Chrome major is a bot
    # signal by itself, and that is what kept forum.audiogames.net behind a
    # permanent Cloudflare challenge.
    'User-Agent': '',
    'Accept': 'application/rss+xml,application/xml,application/atom+xml,text/xml;q=0.9,*/*;q=0.8',
    # Full modern-browser request fingerprint so anti-bot WAFs that block "bot-like"
    # requests (issue #29) accept the connection. The plain-requests path sends all
    # of these; the curl_cffi impersonation path supplies its own matching set.
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Connection': 'keep-alive',
}


def _seed_default_user_agent() -> None:
    """Stamp the baked preset for this platform onto HEADERS at import time.

    Deliberately the preset and not the auto-detected browser: `core.utils` is
    imported by nearly everything, and detection touches the filesystem. The
    GUI upgrades this to the configured identity (which defaults to a real
    installed browser) as soon as config is available.
    """
    try:
        from core import user_agents

        for preset in user_agents.presets():
            if preset.key.endswith("_" + user_agents._platform_key()):
                HEADERS['User-Agent'] = preset.ua
                HEADERS.update(preset.hints)
                return
    except Exception:
        pass
    # core.user_agents unavailable (partial install): a plain modern Chrome
    # string still beats sending none at all.
    if not HEADERS.get('User-Agent'):
        HEADERS['User-Agent'] = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
        )


_seed_default_user_agent()

_FLAC_MIME_ALIASES = {
    "audio/flac",
    "audio/x-flac",
    "application/flac",
    "application/x-flac",
}

_ACTIVITY_TITLE_GENERIC_TEXTS = {
    "see more",
    "more",
    "profile",
    "replied",
    "reply",
    "commented",
    "comment",
    "liked",
}


def add_revalidation_headers(headers: dict | None = None) -> dict:
    """Return headers with cache-bypass directives for proxy/CDN revalidation."""
    merged = dict(headers or {})
    # Include both directives for older intermediaries and stricter caches.
    merged.setdefault("Cache-Control", "no-cache, max-age=0")
    merged.setdefault("Pragma", "no-cache")
    merged.setdefault("Expires", "0")
    return merged


def _image_alt_marker(alt: str | None) -> str:
    alt = (alt or "").strip()
    # Collapse internal whitespace so a multi-line alt reads as one line.
    alt = " ".join(alt.split())
    return f"[Image: {alt}]" if alt else "[Image]"


# Data tables larger than this are almost certainly scraped page furniture
# (finance tickers, stats dumps), not article content worth reading linearly.
_TABLE_MAX_ROWS = 100
# A cell longer than this means the "table" is holding article prose (old
# table-based page layouts), where flattening would destroy the body text.
_TABLE_MAX_CELL_LEN = 400
# Block-level content inside a cell marks a layout table, not a data table.
_TABLE_LAYOUT_TAGS = (
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "article", "section", "aside", "nav", "form",
    "ul", "ol", "blockquote", "figure", "table",
)


def _table_cell_text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def format_table_text(table) -> str:
    """Linearize a BeautifulSoup ``<table>`` into screen-reader-friendly text.

    Plain-text reader panes have no real table semantics, so each data row
    becomes one line pairing every cell with its column header::

        Table with 3 rows and 2 columns: Caption.
        Row 1: Year: 2025; Flaws patched: 140.
        ...
        End of table.

    Returns "" for layout tables (block content or very long prose inside
    cells) so callers keep their existing behavior for those. Markers stay
    English on purpose, like the ``[Image: alt]`` marker: downstream merge
    heuristics in the extractor recognize them by pattern.
    """
    try:
        if table.find(_TABLE_LAYOUT_TAGS) is not None:
            return ""
        grid: list[list[str]] = []
        header_row: list[str] | None = None
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            texts = [_table_cell_text(c) for c in cells]
            if not any(texts):
                continue
            if any(len(t) > _TABLE_MAX_CELL_LEN for t in texts):
                return ""
            is_head = tr.find_parent("thead") is not None or all(c.name == "th" for c in cells)
            if header_row is None and not grid and is_head:
                header_row = texts
                continue
            grid.append(texts)
            if len(grid) > _TABLE_MAX_ROWS:
                return ""
        if not grid and not header_row:
            return ""
        ncols = max(len(r) for r in (grid or [header_row]))
        if ncols < 2 or not grid:
            # A single-column (or header-only) table isn't tabular data; read
            # its cells as plain lines without table framing.
            lines = list(header_row or [])
            lines.extend(t for row in grid for t in row)
            return "\n".join(lines)

        caption = ""
        cap = table.find("caption")
        if cap is not None:
            caption = _table_cell_text(cap)

        head = f"Table with {len(grid)} rows and {ncols} columns"
        lines = [f"{head}: {caption}." if caption else f"{head}."]
        for i, row in enumerate(grid, 1):
            if header_row and len(row) == len(header_row):
                pairs = [f"{h}: {v}" for h, v in zip(header_row, row) if v]
            else:
                pairs = [v for v in row if v]
            lines.append(f"Row {i}: " + "; ".join(pairs) + ".")
        lines.append("End of table.")
        return "\n".join(lines)
    except Exception:
        return ""


def replace_tables_with_text(soup, as_paragraphs: bool = False) -> list[str]:
    """Replace each data ``<table>`` in ``soup`` with its linearized text.

    Innermost tables are processed first so a nested data table inside a
    layout table still gets formatted. Layout tables are left untouched.
    ``as_paragraphs`` emits one ``<p>`` per line (for HTML re-extraction,
    where a raw text node's newlines would be collapsed); otherwise a plain
    text node is inserted (for direct ``get_text`` conversion). Returns the
    formatted text blocks (used by the extractor to patch JSON-LD results
    that dropped tables).
    """
    blocks: list[str] = []
    try:
        for tbl in reversed(soup.find_all("table")):
            text = format_table_text(tbl)
            if not text:
                continue
            if text in blocks:
                # Pages often ship the same table twice (desktop + mobile
                # markup); with tables previously dropped outright, keeping
                # one copy is strictly more than the old behavior.
                tbl.decompose()
                continue
            blocks.append(text)
            if as_paragraphs:
                container = soup.new_tag("div")
                for line in text.split("\n"):
                    p = soup.new_tag("p")
                    p.string = line
                    container.append(p)
                tbl.replace_with(container)
            else:
                tbl.replace_with(soup.new_string("\n\n" + text + "\n\n"))
    except Exception:
        pass
    blocks.reverse()
    return blocks


# ---------------------------------------------------------------------------
# Article structure linearization (headings / lists / block quotes).
#
# The reader pane is a plain text control, so structural HTML is preserved as
# short English marker lines, exactly like the table linearization above:
# downstream merge heuristics in the extractor recognize the markers by
# pattern, so they must never be localized or reworded. Each element type is
# an opt-in Settings toggle; the GUI pushes the config values in here so core
# code stays config-free.
# ---------------------------------------------------------------------------

ARTICLE_STRUCTURE_DEFAULTS = {
    # Tables ship enabled (v1.100.0 behavior); the rest are opt-in extras.
    "tables": True,
    "headings": False,
    "lists": False,
    "quotes": False,
    # Show each hyperlink's target inline as "text (URL)" so screen-reader
    # users can tell it is a link and the reader pane can open it on Enter.
    "links": False,
}
_article_structure_options = dict(ARTICLE_STRUCTURE_DEFAULTS)


def set_article_structure_options(options: dict | None) -> None:
    """Set which structural elements are linearized into article text."""
    global _article_structure_options
    merged = dict(ARTICLE_STRUCTURE_DEFAULTS)
    for key, value in (options or {}).items():
        if key in merged:
            merged[key] = bool(value)
    _article_structure_options = merged


def get_article_structure_options() -> dict:
    return dict(_article_structure_options)


def apply_article_structure_config(config_get) -> None:
    """Load the ``article_structure_*`` config keys via ``config_get(key, default)``."""
    try:
        set_article_structure_options({
            key: config_get(f"article_structure_{key}", default)
            for key, default in ARTICLE_STRUCTURE_DEFAULTS.items()
        })
    except Exception:
        set_article_structure_options(None)


_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def linearize_structure(
    soup, *, headings: bool = False, lists: bool = False, quotes: bool = False, links: bool = False
) -> None:
    """Rewrite structural HTML in ``soup`` into screen-reader marker paragraphs.

    Inline children (links, emphasis) are kept in place so extraction
    heuristics that rely on link density still work; only the containers are
    renamed and prefixed:

    - ``<h2>Why</h2>``            -> ``<p>Heading level 2: Why</p>``
    - ``<li>`` in ``<ul>``/``<ol>`` -> ``<p>• item</p>`` / ``<p>1. item</p>``
    - ``<blockquote>``            -> ``Quote:`` ... ``End of quote.`` paragraphs

    When ``links`` is set, each absolute ``http(s)`` anchor keeps its ``<a>``
    tag (so link-density boilerplate detection is unchanged) but has its target
    appended to the visible text as ``text (URL)``. Bare links show just the
    URL. The URL stays a single whitespace-free token so the reader pane can
    recover it from the rendered plain text and open it on Enter.
    """
    if headings:
        for h in soup.find_all(_HEADING_TAGS):
            if not h.get_text(strip=True):
                continue
            h.insert(0, soup.new_string(f"Heading level {h.name[1]}: "))
            h.name = "p"
    if lists:
        # Innermost-first so a nested list is already linearized (its <li>
        # renamed) before the outer list counts its own direct items.
        for lst in reversed(soup.find_all(["ul", "ol"])):
            ordered = lst.name == "ol"
            index = 0
            for li in lst.find_all("li", recursive=False):
                if not li.get_text(strip=True):
                    continue
                index += 1
                prefix = f"{index}. " if ordered else "• "
                li.insert(0, soup.new_string(prefix))
                li.name = "p"
            lst.name = "div"
    if quotes:
        for bq in reversed(soup.find_all("blockquote")):
            if not bq.get_text(strip=True):
                continue
            start = soup.new_tag("p")
            start.string = "Quote:"
            end = soup.new_tag("p")
            end.string = "End of quote."
            bq.insert(0, start)
            bq.append(end)
            bq.name = "div"
    if links:
        for a in soup.find_all("a"):
            href = str(a.get("href") or "").strip()
            if not href or not href.lower().startswith(("http://", "https://")):
                continue
            # Keep the URL a single openable token: skip anything with
            # whitespace/control characters the reader pane could not recover.
            if any(ch.isspace() or ord(ch) < 32 for ch in href):
                continue
            text = a.get_text(strip=True)
            if not text or text == href:
                # Bare link (or image link): make the URL itself the visible text.
                a.clear()
                a.append(soup.new_string(href))
            elif href not in text:
                a.append(soup.new_string(f" ({href})"))


# Block-level elements that separate paragraphs in the plain-text rendering.
_BLOCK_TEXT_TAGS = (
    "address", "article", "aside", "blockquote", "caption", "dd", "details",
    "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav",
    "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "ul",
)
_NONVISIBLE_TAGS = ("script", "style", "noscript", "template")


def _soup_to_block_text(soup) -> str:
    """Render ``soup`` as plain text: inline markup joins, block tags separate.

    ``get_text(separator=...)`` puts the separator between EVERY pair of text
    nodes, so a paragraph with a link or emphasis used to shred into several
    fake paragraphs. Instead, collapse whitespace inside the original text
    nodes (keeping their boundary spaces), then insert explicit paragraph
    breaks only around block-level elements.
    """
    for tag in soup.find_all(_NONVISIBLE_TAGS):
        tag.decompose()
    for s in soup.find_all(string=True):
        collapsed = re.sub(r"\s+", " ", str(s))
        if collapsed != str(s):
            s.replace_with(soup.new_string(collapsed))
    for br in soup.find_all("br"):
        br.replace_with(soup.new_string("\n"))
    for tag in soup.find_all(_BLOCK_TEXT_TAGS):
        tag.insert_before(soup.new_string("\n\n"))
        tag.insert_after(soup.new_string("\n\n"))
    text = soup.get_text()
    lines = [ln.strip() for ln in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip()


def html_to_text(html: str | None, include_images: bool = False, structure: dict | None = None) -> str:
    """Convert feed/article HTML to readable plain text.

    When ``include_images`` is True, each ``<img>`` is replaced in document order
    with its alt text as ``[Image: alt]`` (or ``[Image]`` when there is no alt), so
    screen-reader users hear that an image is present without the image URL. When
    False, images are dropped (the historical behavior).

    ``structure`` overrides the module-level article-structure options (see
    :func:`set_article_structure_options`); ``None`` uses those options.
    """
    if not html:
        return ""
    try:
        soup = BS(html, "html.parser")
    except Exception:
        return str(html)
    try:
        opts = dict(_article_structure_options)
        opts.update(structure or {})
        if include_images:
            for img in soup.find_all("img"):
                alt = img.get("alt") or img.get("title") or ""
                if isinstance(alt, (list, tuple)):
                    alt = " ".join(str(a) for a in alt)
                img.replace_with(soup.new_string(_image_alt_marker(str(alt))))
        # Data tables read as one cell per line through plain conversion,
        # losing all row/column association; linearize them into header-value
        # lines. Structure markers reuse the same in-place rewriting.
        if opts.get("tables", True):
            replace_tables_with_text(soup, as_paragraphs=True)
        linearize_structure(
            soup,
            headings=bool(opts.get("headings")),
            lists=bool(opts.get("lists")),
            quotes=bool(opts.get("quotes")),
            links=bool(opts.get("links")),
        )
        return _soup_to_block_text(soup)
    except Exception:
        return str(html)


def collapse_blank_lines(text: str | None) -> str:
    """Drop empty lines from reader body text, one paragraph per line.

    Article bodies reach the reader with two different paragraph conventions.
    A successful web extraction comes from trafilatura, which puts every
    paragraph on its own line with no blank line between them. The HTML->text
    converter above, and the site boilerplate strippers that rebuild a body
    from paragraphs, separate them with a blank line instead. A screen reader
    stops on every one of those blank lines, so the same article navigates at
    twice the line count depending only on which path produced it -- which is
    what makes a failed extraction (feed content shown instead) read so much
    worse than a successful one. Normalize on the trafilatura convention.
    """
    if not text:
        return ""
    raw = str(text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(ln.rstrip() for ln in raw.split("\n") if ln.strip()).strip()


class _PreviewTextComplete(Exception):
    """Internal early-exit once enough visible preview text was collected."""


class _HTMLPreviewParser(HTMLParser):
    """Small, bounded HTML-to-text parser for list-column previews."""

    _IGNORED_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self, max_chars: int):
        super().__init__(convert_charrefs=True)
        self.max_chars = max(1, int(max_chars))
        self.parts: list[str] = []
        self.text_length = 0
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        del attrs
        if self._ignored_depth:
            self._ignored_depth += 1
        elif str(tag or "").lower() in self._IGNORED_TAGS:
            self._ignored_depth = 1

    def handle_startendtag(self, tag, attrs):
        del tag, attrs

    def handle_endtag(self, tag):
        del tag
        if self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if self._ignored_depth:
            return
        text = " ".join(str(data or "").split())
        if not text:
            return
        separator = 1 if self.parts else 0
        remaining = self.max_chars - self.text_length - separator
        if remaining <= 0:
            raise _PreviewTextComplete
        self.parts.append(text[:remaining])
        self.text_length += separator + min(len(text), remaining)
        if len(text) >= remaining:
            raise _PreviewTextComplete

    def text(self) -> str:
        return " ".join(self.parts).strip()


def html_to_text_preview(html: str | None, max_chars: int = 320) -> str:
    """Return bounded visible text for an article-list description preview.

    The reader pane still uses :func:`html_to_text` and its full BeautifulSoup
    conversion.  List rows only display a short preview, so parsing an entire
    multi-kilobyte article 400 times wastes CPU and contends with wx/NVDA.  This
    parser skips non-visible elements and stops as soon as enough text exists.
    """
    if not html:
        return ""
    raw = str(html)
    if "<" not in raw and "&" not in raw:
        return " ".join(raw.split())[: max(1, int(max_chars))]

    parser = _HTMLPreviewParser(max_chars)
    try:
        parser.feed(raw)
        parser.close()
    except _PreviewTextComplete:
        pass
    except Exception:
        # Preserve historical behavior for malformed input the small parser
        # cannot consume; this rare fallback is allowed to do the full parse.
        return html_to_text(raw, include_images=False)[: max(1, int(max_chars))]
    return parser.text()


def first_image_url(html: str | None) -> str | None:
    """Return the first ``<img>`` source URL in the HTML, or None."""
    if not html:
        return None
    try:
        soup = BS(html, "html.parser")
        img = soup.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-original") or ""
            if isinstance(src, (list, tuple)):
                src = src[0] if src else ""
            src = str(src).strip()
            return src or None
    except Exception:
        pass
    return None


def content_has_images(html: str | None) -> bool:
    """True if the HTML contains at least one ``<img>`` with a usable source."""
    return first_image_url(html) is not None


# RSS 2.0 specifies <author> as an email address with the display name in
# parentheses, and mail-header style puts it the other way round. Forum software
# that has no real address to publish fills in a placeholder, so audiogames.net
# ships "null@example.com (sightlessHorseman)" and the reader announced the whole
# string as the author. feedparser splits this for us, but a server-side
# aggregator (Miniflux) hands over the raw field, so normalize it here where
# every backend passes through.
_AUTHOR_EMAIL_THEN_NAME_RE = re.compile(r"^\s*\S+@\S+\s*\(\s*(?P<name>.+?)\s*\)\s*$")
_AUTHOR_NAME_THEN_EMAIL_RE = re.compile(r"^\s*(?P<name>.+?)\s*<\s*\S+@\S+\s*>\s*$")


def normalize_author(author: str | None) -> str:
    """Return the human-readable display name from a feed author field.

    Falls through unchanged when the value is already a plain name, or is an
    address with no name attached — a bare address is at least identifying, and
    inventing a name from it would be worse than showing it.
    """
    text = str(author or "").strip()
    if not text:
        return ""
    for pattern in (_AUTHOR_EMAIL_THEN_NAME_RE, _AUTHOR_NAME_THEN_EMAIL_RE):
        match = pattern.match(text)
        if match:
            name = match.group("name").strip().strip('"').strip()
            if name:
                return name
    return text


def canonical_media_type(media_type: str | None) -> str:
    """Normalize common media MIME aliases to a stable value."""
    mt = str(media_type or "").split(";", 1)[0].strip().lower().rstrip("/")
    if mt in _FLAC_MIME_ALIASES:
        return "audio/flac"
    return mt


def media_type_is_audio_video_or_podcast(media_type: str | None) -> bool:
    mt = canonical_media_type(media_type)
    if not mt:
        return False
    return mt.startswith(("audio/", "video/")) or "podcast" in mt


def _activity_title_norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _activity_title_norm_link(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(str(url or "").strip())
    except Exception:
        return ""
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = urllib.parse.unquote((p.path or "").rstrip("/"))
    # Ignore tracking-style params so activity links can match canonical content links.
    try:
        q = urllib.parse.parse_qsl(p.query or "", keep_blank_values=True)
        q = [(k, v) for (k, v) in q if str(k).lower() not in {"xg_source", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}]
        q.sort()
        query = urllib.parse.urlencode(q, doseq=True)
    except Exception:
        query = ""
    return urllib.parse.urlunsplit((p.scheme.lower(), host, path, query, ""))


def _activity_title_anchor_has_ancestor(a, tag_names: tuple[str, ...] = (), class_names: tuple[str, ...] = ()) -> bool:
    try:
        for parent in getattr(a, "parents", []) or []:
            if parent is None:
                continue
            if tag_names and str(getattr(parent, "name", "") or "").lower() in tag_names:
                return True
            if class_names:
                classes = [str(c or "").lower() for c in (parent.get("class") or [])]
                if any(cls in classes for cls in class_names):
                    return True
    except Exception:
        return False
    return False


def _looks_like_generic_activity_link_text(text: str) -> bool:
    t = _activity_title_norm_space(text).lower().strip(" .:;!-")
    if not t:
        return True
    if t in _ACTIVITY_TITLE_GENERIC_TEXTS:
        return True
    if re.fullmatch(r"\d+\s+more(?:…|\.\.\.)?", t):
        return True
    if "more" in t and len(t) <= 10:
        return True
    return False


def _looks_like_profile_activity_link(href: str) -> bool:
    href_low = str(href or "").lower()
    return "/profile/" in href_low or "/members/" in href_low


# Phrases that mark a title as an "activity log" entry (Ning-style) where the
# real story title is hidden in the description HTML, e.g. "User posted a video".
_ACTIVITY_LOG_TITLE_PATTERNS = (
    r"\bposted\b",
    r"\breplied\b",
    r"\bcommented\b",
    r"\bliked\b",
    r"\bfavorited\b",
    r"\bupdated (?:their|his|her|the)\b",
    r"\b(?:added|uploaded|shared) (?:a|an|the)\b",
    r"\bis now (?:a member|friends)\b",
)
_ACTIVITY_LOG_TITLE_RE = re.compile("|".join(_ACTIVITY_LOG_TITLE_PATTERNS), re.IGNORECASE)


def _looks_like_activity_log_title(title: str) -> bool:
    """True when a feed title reads like an activity-log line rather than a real story title.

    Used to gate the description-HTML title rescue so that feeds with proper item
    titles (e.g. podcast episodes such as Supercast's "S5 EP33: ...") are never
    overridden by footer links like "⚙️ Manage Subscription".
    """
    return bool(_ACTIVITY_LOG_TITLE_RE.search(_activity_title_norm_space(title)))


def enhance_activity_entry_title(title: str | None, url: str | None, content: str | None) -> str:
    """Derive a better title from activity-feed HTML when the real story title is embedded.

    This is intentionally conservative and primarily targets Ning-style activity feeds where
    generic titles like "X posted a video" hide the actual content title in the description HTML.
    """
    cur_title = _activity_title_norm_space(title or "")
    # Only rescue a title from the description HTML when the existing title is
    # missing or reads like a generic activity-log line. Real item titles (e.g.
    # podcast episode names) must never be replaced by footer links such as
    # "⚙️ Manage Subscription" found in subscriber feeds (Supercast, etc.).
    if cur_title and not _looks_like_activity_log_title(cur_title):
        return cur_title
    html = str(content or "")
    if not html or "<" not in html or ">" not in html:
        return cur_title

    low_html = html.lower()
    # Markers commonly seen in Ning activity feeds and similar "activity log" HTML.
    if not any(m in low_html for m in ("feed-story-title", "xg_source=activity", "feed-more", "<strong><a", "</strong><a")):
        return cur_title

    try:
        soup = BS(html, "html.parser")
    except Exception:
        return cur_title

    target_url = _activity_title_norm_link(url or "")
    candidates: list[tuple[int, int, str]] = []

    for idx, a in enumerate(soup.find_all("a", href=True)):
        try:
            text = _activity_title_norm_space(a.get_text(" ", strip=True))
        except Exception:
            text = ""
        href = str(a.get("href") or "").strip()
        if not text or not href:
            continue

        score = 0
        if _looks_like_generic_activity_link_text(text):
            score -= 8
        else:
            score += 1

        if _looks_like_profile_activity_link(href):
            score -= 4

        # Prefer explicit story-title wrappers and strong heading-style links.
        classes = [str(c or "").lower() for c in (a.get("class") or [])]
        if "feed-story-title" in classes:
            score += 8
        if _activity_title_anchor_has_ancestor(a, class_names=("feed-story-title",)):
            score += 8
        if _activity_title_anchor_has_ancestor(a, tag_names=("h1", "h2", "h3", "h4", "h5", "h6")):
            score += 6
        if _activity_title_anchor_has_ancestor(a, tag_names=("strong",)):
            score += 5
        if _activity_title_anchor_has_ancestor(a, class_names=("feed-more",)):
            score -= 10

        href_norm = _activity_title_norm_link(href)
        if target_url and href_norm and href_norm == target_url:
            score += 7
        elif target_url and href_norm and urllib.parse.urlsplit(href_norm).path == urllib.parse.urlsplit(target_url).path:
            score += 4

        # Prefer meaningful longer titles over action words.
        score += min(6, max(0, len(text) // 20))

        candidates.append((score, -idx, text))

    if not candidates:
        return cur_title

    candidates.sort(reverse=True)
    best_score, _neg_idx, best_text = candidates[0]
    if best_score < 6:
        return cur_title
    if _looks_like_generic_activity_link_text(best_text):
        return cur_title

    return best_text or cur_title

# Common timezone abbreviations mapping for dateutil
TZINFOS = {
    "UTC": 0,
    "GMT": 0,
    "EST": -18000,
    "EDT": -14400,
    "CST": -21600,
    "CDT": -18000,
    "MST": -25200,
    "MDT": -21600,
    "PST": -28800,
    "PDT": -25200,
}


def build_playback_speeds(start: float = 0.5, stop: float = 4.0, step: float = 0.1):
    """
    Generate a list of playback speeds rounded to 2 decimals, inclusive of bounds.
    Default range: 0.50x .. 4.00x in even 0.1 increments, so stepping reads
    smoothly (1.1x, 1.2x, ...) instead of the old 0.12 grid (1.1x, 1.22x, 1.34x).
    """
    speeds = []
    val = round(start, 2)
    upper = round(stop, 2)
    while val <= upper + 1e-9:
        speeds.append(val)
        val = round(val + step, 2)
    if not speeds or speeds[-1] != upper:
        speeds.append(upper)
    # Always include true 1.00x so "Normal" snaps exactly, not ~0.98x
    speeds.append(1.0)
    # Deduplicate and sort to keep monotonic order, but drop near-1.0 variants like 0.98
    speeds = sorted(set(round(v, 2) for v in speeds))
    cleaned = []
    for v in speeds:
        if abs(v - 1.0) <= 0.025 and abs(v - 1.0) > 1e-9:
            continue
        cleaned.append(v)
    return cleaned


_SENSITIVE_HEADER_KEYS = {"authorization", "cookie", "proxy-authorization", "set-cookie"}


def referer_for_url(url: str) -> str:
    """Return a site-root Referer (``scheme://host/``) for a URL, or "" if unparseable.

    Sending the feed's own site as the Referer makes the request look like an
    in-site navigation, which some anti-bot WAFs require (issue #29).
    """
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
    except Exception:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return encode_non_ascii_url(f"{parts.scheme}://{parts.netloc}/")


def _redact_headers(headers: dict) -> dict:
    """Copy of ``headers`` with sensitive values masked, for safe logging."""
    redacted = {}
    for key, value in (headers or {}).items():
        if str(key).lower() in _SENSITIVE_HEADER_KEYS:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def _log_http_request(method: str, url: str, headers: dict, transport: str) -> None:
    """Log an outgoing request (headers redacted) at DEBUG for diagnostics (issue #29)."""
    if not log.isEnabledFor(logging.DEBUG):
        return
    try:
        log.debug("HTTP %s %s via %s headers=%s", method, url, transport, _redact_headers(headers))
    except Exception:
        pass


def _impersonated_headers(headers: dict) -> dict:
    """Headers to forward on the curl_cffi path.

    curl_cffi supplies a self-consistent Chrome UA / Sec-CH-UA / Sec-Fetch set that
    matches its impersonated TLS handshake, so we forward only the caller's
    functional headers (Referer, conditional, cache-control) plus an Accept.
    """
    final_headers = dict(headers or {})
    if not any(str(k).lower() == "accept" for k in final_headers):
        final_headers["Accept"] = HEADERS["Accept"]
    return final_headers


def _apply_site_cookies(url: str, final_headers: dict) -> dict:
    """Attach imported per-site cookies (and their browser's UA) to a request.

    Sites behind an interactive bot check (issue #79) only open for a session
    that already passed the challenge in a real browser, so requests to domains
    present in the imported jar carry its cookies — plus the browser's exact
    User-Agent string, which Cloudflare requires for the clearance cookie to
    count. Callers that set their own Cookie header keep it untouched.
    """
    try:
        from core import site_cookies
        if any(str(k).lower() == "cookie" for k in final_headers):
            return final_headers
        cookie_header = site_cookies.cookie_header_for(url)
        if not cookie_header:
            return final_headers
        final_headers = dict(final_headers)
        final_headers["Cookie"] = cookie_header
        ua = site_cookies.user_agent_for(url)
        if ua:
            final_headers = {
                k: v for k, v in final_headers.items() if str(k).lower() != "user-agent"
            }
            final_headers["User-Agent"] = ua
            # The client hints must follow the swapped UA. Leaving the app's
            # Chromium `sec-ch-ua` headers on a request that now claims Firefox
            # is a self-contradicting fingerprint — Gecko never sends them —
            # and a WAF spots that faster than it would have spotted the
            # original UA. See core/user_agents.py.
            from core import user_agents

            identity = user_agents.identity_from_string(ua)
            final_headers = {
                k: v
                for k, v in final_headers.items()
                if str(k).lower() not in user_agents.CLIENT_HINT_HEADERS
            }
            if identity is not None:
                final_headers.update(identity.hints)
    except Exception:
        log.debug("Site-cookie attachment failed for %s", url, exc_info=True)
    return final_headers


def encode_non_ascii_url(url: str) -> str:
    """Make a URL with non-ASCII parts request-safe (issue #41).

    Converts an internationalized hostname to its Punycode/IDNA form (e.g.
    пример.рф -> xn--e1afmkfd.xn--p1ai) and percent-encodes non-ASCII
    characters in the path, query, and fragment per RFC 3986. ASCII URLs are
    returned unchanged, and existing percent-escapes are never double-encoded.
    Applied only at the request layer — stored/displayed URLs stay as typed.
    """
    text = str(url or "").strip()
    if not text or text.isascii():
        return text
    try:
        parts = urllib.parse.urlsplit(text)

        host = parts.hostname or ""
        if host and not host.isascii():
            try:
                # UTS-46 mapping matches how browsers resolve IDNs; the idna
                # package ships as a requests dependency.
                import idna
                host = idna.encode(host, uts46=True).decode("ascii")
            except Exception:
                host = host.encode("idna").decode("ascii")

        netloc = host
        if ":" in netloc and not netloc.startswith("["):
            netloc = f"[{netloc}]"
        if parts.port is not None:
            netloc = f"{netloc}:{parts.port}"
        if parts.username:
            userinfo = urllib.parse.quote(parts.username, safe="%")
            if parts.password:
                userinfo += ":" + urllib.parse.quote(parts.password, safe="%")
            netloc = f"{userinfo}@{netloc}"

        # "%" stays in safe so already-encoded sequences survive unchanged.
        path = urllib.parse.quote(parts.path, safe="%/:@!$&'()*+,;=~-._")
        query = urllib.parse.quote(parts.query, safe="%/:@!$&'()*+,;=~-._?")
        fragment = urllib.parse.quote(parts.fragment, safe="%/:@!$&'()*+,;=~-._?")

        return urllib.parse.urlunsplit((parts.scheme, netloc, path, query, fragment))
    except Exception:
        return text


_URL_HEADER_KEYS = {"referer", "referrer", "origin"}


def _request_safe_headers(headers: dict) -> dict:
    """Return request headers with URL-valued fields made HTTP-header safe."""
    safe_headers = {}
    for key, value in (headers or {}).items():
        if value is None:
            continue
        if str(key).lower() in _URL_HEADER_KEYS:
            safe_headers[key] = encode_non_ascii_url(str(value))
        else:
            safe_headers[key] = value
    return safe_headers


def _site_cookie_impersonation(url: str) -> str:
    """The curl_cffi target a site's imported session needs, or "".

    A clearance cookie is validated against the TLS/HTTP handshake as much as
    the User-Agent, so sending one over plain `requests` wastes it. When the jar
    has a UA-paired session for this URL, the request must go out over the
    matching browser fingerprint even if the caller never asked to impersonate.
    Measured on forum.audiogames.net: the same fresh cookie 403'd on `requests`
    and on curl_cffi's Chrome hello, and returned the article on its Firefox one.
    """
    if not CURL_CFFI_AVAILABLE:
        return ""
    try:
        from core import site_cookies, user_agents

        ua = site_cookies.user_agent_for(url)
        if not ua:
            return ""
        return user_agents.impersonate_target_for_ua(ua)
    except Exception:
        return ""


def safe_requests_get(url, *, impersonate: bool = False, impersonate_target: str | None = None, **kwargs):
    """Wrapper for requests.get with default browser headers.

    When ``impersonate`` is True and curl_cffi is installed, the request is sent
    through curl_cffi with a real browser TLS/HTTP fingerprint to get past anti-bot
    WAFs that reset non-browser connections (issue #29). ``impersonate_target``
    overrides the default Chrome fingerprint (e.g. "safari184": some Cloudflare
    challenges 403 curl_cffi's Chrome hello but pass its Safari one). Falls back to
    plain ``requests`` when curl_cffi is unavailable, so behavior degrades gracefully.

    A site with an imported browser session is impersonated automatically, with
    the fingerprint that matches the session's UA (see _site_cookie_impersonation).
    """
    url = encode_non_ascii_url(url)
    headers = kwargs.pop("headers", {})
    if not impersonate:
        session_target = _site_cookie_impersonation(url)
        if session_target:
            impersonate = True
            impersonate_target = impersonate_target or session_target
    if impersonate and CURL_CFFI_AVAILABLE:
        target = impersonate_target or IMPERSONATE_TARGET
        final_headers = _apply_site_cookies(url, _request_safe_headers(_impersonated_headers(headers)))
        _log_http_request("GET", url, final_headers, f"curl_cffi:{target}")
        return _get_curl_session().get(url, headers=final_headers, impersonate=target, **kwargs)
    # Merge with defaults, preserving caller's headers if they exist
    final_headers = HEADERS.copy()
    final_headers.update(headers)
    final_headers = _apply_site_cookies(url, _request_safe_headers(final_headers))
    _log_http_request("GET", url, final_headers, "requests")
    return _get_plain_session().get(url, headers=final_headers, **kwargs)


def safe_requests_post(url, *, impersonate: bool = False, impersonate_target: str | None = None, **kwargs):
    """Wrapper for requests.post with the same safe browser headers as ``safe_requests_get``.

    Use this for form/API POSTs that need to share the per-thread HTTP session with a preceding
    safe GET (for example, a page-derived follow-up request).  It deliberately mirrors the GET
    helper so callers retain the normal header sanitizing, diagnostics, and optional browser TLS
    impersonation behavior.
    """
    url = encode_non_ascii_url(url)
    headers = kwargs.pop("headers", {})
    if impersonate and CURL_CFFI_AVAILABLE:
        target = impersonate_target or IMPERSONATE_TARGET
        final_headers = _apply_site_cookies(url, _request_safe_headers(_impersonated_headers(headers)))
        _log_http_request("POST", url, final_headers, f"curl_cffi:{target}")
        return _get_curl_session().post(url, headers=final_headers, impersonate=target, **kwargs)
    final_headers = HEADERS.copy()
    final_headers.update(headers)
    final_headers = _apply_site_cookies(url, _request_safe_headers(final_headers))
    _log_http_request("POST", url, final_headers, "requests")
    return _get_plain_session().post(url, headers=final_headers, **kwargs)


def safe_requests_head(url, *, impersonate: bool = False, **kwargs):
    """Wrapper for requests.head with default browser headers (see safe_requests_get)."""
    url = encode_non_ascii_url(url)
    headers = kwargs.pop("headers", {})
    if impersonate and CURL_CFFI_AVAILABLE:
        final_headers = _apply_site_cookies(url, _request_safe_headers(_impersonated_headers(headers)))
        _log_http_request("HEAD", url, final_headers, f"curl_cffi:{IMPERSONATE_TARGET}")
        return _get_curl_session().head(url, headers=final_headers, impersonate=IMPERSONATE_TARGET, **kwargs)
    final_headers = HEADERS.copy()
    final_headers.update(headers)
    final_headers = _apply_site_cookies(url, _request_safe_headers(final_headers))
    _log_http_request("HEAD", url, final_headers, "requests")
    return _get_plain_session().head(url, headers=final_headers, **kwargs)


def build_cache_id(article_id: str | None, feed_id: str | None = None, provider: str | None = None) -> str | None:
    """Build a stable cache id that scopes articles by provider/feed when needed."""
    if not article_id:
        return None
    parts = []
    if provider:
        parts.append(str(provider))
    if feed_id:
        parts.append(str(feed_id))
    prefix = ":".join(parts)
    aid = str(article_id)
    if prefix:
        if aid.startswith(prefix + ":"):
            return aid
        return f"{prefix}:{aid}"
    return aid


def is_bare_site_root(url: str) -> bool:
    """True when a URL points at a site's front page (no path, query, or fragment).

    Podcast feeds (e.g. Simplecast's) often set every episode's <link> to the
    show's homepage, so "Copy Link" would hand out the same useless URL for
    every episode; callers use this to fall back to the enclosure instead.
    """
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return parsed.path in ("", "/") and not parsed.query and not parsed.fragment


# --- Date Parsing ---


def format_datetime(dt: datetime) -> str:
    """Return UTC-normalized string for consistent ordering.
    Assumes naive datetimes are already in UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def extract_date_from_text(text: str, fuzzy: bool = True):
    """
    Try multiple date patterns inside arbitrary text.
    Returns datetime or None.
    """
    if not text:
        return None
    
    # 1) ISO-like yyyy-mm-dd (Check FIRST to avoid greedy matching by other patterns)
    m_iso = re.search(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b", text)
    if m_iso:
        try:
            y, mth, d = map(int, m_iso.groups())
            if 1 <= mth <= 12 and 1 <= d <= 31:
                return datetime(y, mth, d, tzinfo=timezone.utc)
        except Exception:
            pass

    # 2) numeric with / or - (e.g. 12/25/2023 or 25-12-23)
    # Require word boundaries to avoid matching inside other numbers
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if m:
        a, b, year = m.groups()
        try:
            year_int = int(year)
            if year_int < 100:
                year_int += 2000 if year_int < 70 else 1900
            a_int, b_int = int(a), int(b)
            # heuristic: if both <=12, prefer US mm/dd for consistency with dateparser defaults
            if a_int > 12 and b_int <= 12:
                day, month = a_int, b_int
            elif b_int > 12 and a_int <= 12:
                day, month = b_int, a_int
            else:
                month, day = a_int, b_int
            if 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year_int, month, day, tzinfo=timezone.utc)
        except Exception:
            pass
            
    # 3) Explicit Month Name (Strict) - e.g. "Jan 1, 2020", "15 May 1999"
    # Matches: Month DD, YYYY or DD Month YYYY
    m_text = re.search(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text)
    if not m_text:
        m_text = re.search(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+(\d{4})\b", text)
        
    if m_text:
        try:
            dt = dateparser.parse(m_text.group(0), tzinfos=TZINFOS)
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except Exception:
            pass

    if not fuzzy:
        return None

    # 4) Month name forms (fuzzy fallback)
    try:
        dt = dateparser.parse(text, fuzzy=True, default=datetime(1900, 1, 1, tzinfo=timezone.utc), tzinfos=TZINFOS)
        if dt and dt.year > 1900:
            # If parser only saw a bare year (fills month/day with defaults), skip it;
            # we don't want to override feed dates with year-only hints like "2025".
            lower = text.lower()
            has_month_day_hint = (
                re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{1,2}", lower) or
                re.search(r"\d{1,2}[/-]\d{1,2}", text) or
                re.search(r"\d{4}-\d{1,2}-\d{1,2}", text)
            )
            only_year = (dt.month == 1 and dt.day == 1 and not has_month_day_hint)
            if not only_year:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
    except Exception:
        pass
    return None


def normalize_date(raw_date_str: str, title: str = "", content: str = "", url: str = "") -> str:
    """
    Robust date normalizer.
    Prioritizes the Raw Feed Date to ensure correct sorting of new articles.
    Fallbacks to Title/URL/Content only if the feed date is missing or invalid.
    """
    now = datetime.now(timezone.utc)
    
    def valid(dt: datetime) -> bool:
        if not dt:
            return False
        if dt.tzinfo:
            dt_cmp = dt.astimezone(timezone.utc)
        else:
            dt_cmp = dt.replace(tzinfo=timezone.utc)
        # discard if more than 2 days in future (some timezones are ahead, but not by years)
        if (dt_cmp - now) > timedelta(days=2):
            return False
        # Discard if ridiculously old (before RSS existed) unless it's explicitly parsed
        if dt_cmp.year < 1990:
            return False
        return True

    # 1) Check raw feed date (Priority)
    if raw_date_str:
        # Check for Unix Timestamp (numeric string)
        if raw_date_str.replace('.', '', 1).isdigit():
            try:
                ts = float(raw_date_str)
                # Reasonable bounds for timestamp (e.g. > 1980 and < 2100)
                if 315532800 < ts < 4102444800:
                    dt = datetime.fromtimestamp(ts, timezone.utc)
                    if valid(dt):
                        return format_datetime(dt)
            except Exception:
                pass

        try:
            dt = dateparser.parse(raw_date_str, tzinfos=TZINFOS)
            if valid(dt):
                return format_datetime(dt)
        except Exception:
            pass

    # 2) Check Title (Fallback)
    if title:
        dt = extract_date_from_text(title, fuzzy=False)
        if dt and valid(dt):
            return format_datetime(dt)

    # 3) Check URL (Fallback)
    if url:
        dt = extract_date_from_text(url, fuzzy=False)
        if dt and valid(dt):
            return format_datetime(dt)

    # 4) Check content (Allow fuzzy here as content often contains "Published on..." blocks)
    if content:
        dt = extract_date_from_text(content, fuzzy=True)
        if dt and valid(dt):
            return format_datetime(dt)

    # 5) Fallback sentinel
    return "0001-01-01 00:00:00"



def parse_datetime_utc(value: str):
    """Parse a date/time string into an aware UTC datetime.

    BlindRSS stores normalized dates as UTC-formatted strings ("YYYY-MM-DD HH:MM:SS").
    If a parsed datetime is naive, it is assumed to be UTC.

    Returns:
        datetime (tz-aware, UTC) or None if parsing fails or the value is a sentinel.
    """
    if not value:
        return None
    value = str(value).strip()
    if not value or value.startswith("0001-01-01"):
        return None

    dt = None
    # Optimize: Try fast standard parsing first (DB uses this format)
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        try:
            # Fallback for older python or slightly different formats
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    if not dt:
        try:
            dt = dateparser.parse(value, tzinfos=TZINFOS)
        except Exception:
            dt = None

    if not dt:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def humanize_article_date(date_str: str, now_utc: datetime = None) -> str:
    """Human-friendly article date.

    - For the first 24 hours: relative time (e.g., "5 minutes ago", "2 hours ago").
    - After 24 hours: absolute local time using the system timezone.
    """
    dt_utc = parse_datetime_utc(date_str)
    if not dt_utc:
        return ""

    now = now_utc or datetime.now(timezone.utc)
    delta = now - dt_utc
    if delta.total_seconds() < 0:
        delta = timedelta(seconds=0)

    if delta <= timedelta(hours=24):
        secs = int(delta.total_seconds())
        if secs < 60:
            return _("Just now")
        mins = secs // 60
        if mins < 60:
            return ngettext("{n} minute ago", "{n} minutes ago", mins).format(n=mins)
        hours = mins // 60
        return ngettext("{n} hour ago", "{n} hours ago", hours).format(n=hours)

    # Absolute local time
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    dt_local = dt_utc.astimezone(local_tz)
    return dt_local.strftime("%Y-%m-%d %H:%M")


# --- Chapters ---

_MAX_CHAPTER_JSON_BYTES = 2_000_000
_MAX_CHAPTER_COUNT = 10_000
_MAX_CHAPTER_REDIRECTS = 5
_CHAPTER_REFRESH_SECONDS = 15 * 60
_CHAPTER_JSON_MIME_TYPES = {
    "application/json",
    "application/json+chapters",
    "application/octet-stream",
    "text/json",
    "text/plain",
}


def build_chapter_cache_key(provider: str | None, article_id) -> str | None:
    """Build an unambiguous provider-scoped key for hosted article chapters."""
    try:
        article_key = str(article_id).strip()
    except Exception:
        return None
    if not article_key:
        return None
    provider_key = str(provider or "").strip().lower()
    if not provider_key:
        return article_key
    if (
        ":" not in provider_key
        and ":" not in article_key
        and provider_key != "local"
    ):
        return f"{provider_key}:{article_key}"
    # Length-prefixing is reversible and avoids delimiter collisions such as
    # ("a:b", "c") versus ("a", "b:c"). Simple legacy keys remain unchanged
    # when they are already unambiguous.
    return f"hosted:v1:{len(provider_key)}:{provider_key}{article_key}"


def _chapter_start_seconds(value):
    """Return a finite, non-negative chapter timestamp in seconds."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            if ":" not in text:
                result = float(text)
            else:
                parts = text.split(":")
                if len(parts) not in (2, 3) or any(not part.strip() for part in parts):
                    return None
                values = [float(part.strip()) for part in parts]
                if any(not math.isfinite(part) or part < 0 for part in values):
                    return None
                if any(part >= 60 for part in values[1:]):
                    return None
                result = sum(part * (60 ** index) for index, part in enumerate(reversed(values)))
        except (TypeError, ValueError, OverflowError):
            return None
    if not math.isfinite(result) or result < 0:
        return None
    return result


def _chapter_text(value, *, empty=None):
    if value is None:
        return empty
    try:
        return str(value)
    except Exception:
        return empty


def _normalize_chapters(chapters):
    """Validate, sort, and deduplicate chapter dictionaries.

    Duplicate timestamps are merged in source order so a later duplicate can
    supply a missing title or href without replacing already-present metadata.
    """
    if not isinstance(chapters, (list, tuple)):
        return []

    normalized = []
    for chapter in chapters[:_MAX_CHAPTER_COUNT]:
        if not isinstance(chapter, Mapping):
            continue
        if chapter.get("toc") is False:
            continue
        start_value = None
        for key in ("startTime", "start_time", "start"):
            if key in chapter:
                start_value = chapter[key]
                break
        start = _chapter_start_seconds(start_value)
        if start is None:
            continue

        title = _chapter_text(chapter.get("title"), empty="") or ""
        href_value = chapter.get("url")
        if href_value in (None, ""):
            href_value = chapter.get("link")
        if href_value in (None, ""):
            href_value = chapter.get("href")
        href = _chapter_text(href_value, empty=None)
        normalized.append({"start": start, "title": title, "href": href})

    normalized.sort(key=lambda chapter: chapter["start"])
    deduped = []
    for chapter in normalized:
        if deduped and chapter["start"] == deduped[-1]["start"]:
            if not deduped[-1]["title"] and chapter["title"]:
                deduped[-1]["title"] = chapter["title"]
            if not deduped[-1]["href"] and chapter["href"]:
                deduped[-1]["href"] = chapter["href"]
            continue
        deduped.append(chapter)
    return deduped


def _replace_stored_chapters(article_key, chapters, cursor=None, *, cache_key=None, allow_empty=False):
    """Atomically replace one article's chapter rows.

    Constraint failures roll back only this replacement and leave any previous
    rows intact. Parsed chapters are still returned to callers when persistence
    is impossible (for example, a missing article foreign key).
    """
    storage_key = str(cache_key or article_key or "").strip()
    if not storage_key or (not chapters and not allow_empty):
        return False

    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()

    savepoint = f"replace_chapters_{uuid.uuid4().hex}"
    try:
        c.execute(f"SAVEPOINT {savepoint}")
        if cache_key:
            c.execute("DELETE FROM chapter_cache WHERE cache_key = ?", (storage_key,))
            if chapters:
                c.executemany(
                    "INSERT INTO chapter_cache (id, cache_key, start, title, href) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            str(uuid.uuid4()),
                            storage_key,
                            chapter["start"],
                            chapter["title"],
                            chapter["href"],
                        )
                        for chapter in chapters
                    ],
                )
        else:
            c.execute("DELETE FROM chapters WHERE article_id = ?", (storage_key,))
            if chapters:
                c.executemany(
                    "INSERT INTO chapters (id, article_id, start, title, href) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            str(uuid.uuid4()),
                            storage_key,
                            chapter["start"],
                            chapter["title"],
                            chapter["href"],
                        )
                        for chapter in chapters
                    ],
                )
        c.execute(f"RELEASE SAVEPOINT {savepoint}")
        if conn is not None:
            conn.commit()
        return True
    except sqlite3.Error as e:
        try:
            c.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            c.execute(f"RELEASE SAVEPOINT {savepoint}")
        except sqlite3.Error:
            pass
        log.info(
            "Skipping chapter DB persistence for key=%s due to database error: %s",
            storage_key,
            e,
        )
        return False
    finally:
        if conn is not None:
            conn.close()


def _response_header(response, name):
    headers = getattr(response, "headers", {}) or {}
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return value
    return None


def _validated_public_http_url(url, *, purpose):
    try:
        raw_url = str(url or "").strip()
        parsed_url = urllib.parse.urlsplit(raw_url)
    except Exception as e:
        raise ValueError(f"invalid {purpose} URL") from e
    if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError(f"{purpose} URL must use HTTP or HTTPS")
    if "\\" in parsed_url.netloc:
        raise ValueError(f"{purpose} URL has an invalid authority")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise ValueError(f"{purpose} URL must not contain credentials")
    try:
        port = parsed_url.port
    except ValueError as e:
        raise ValueError(f"{purpose} URL has an invalid port") from e
    hostname = str(parsed_url.hostname or "").strip().rstrip(".").lower()
    if not hostname or hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(f"{purpose} URL must use a public host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError(f"{purpose} URL must not target a private or local address")

    # Requests performs its own DNS lookup after this check. Validating every
    # redirect substantially reduces SSRF exposure, but without replacing
    # Requests' connection layer there remains a DNS-rebinding/TOCTOU window
    # where an answer can change between validation and socket connection.
    try:
        resolved = socket.getaddrinfo(
            hostname,
            port or (443 if parsed_url.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as e:
        raise ValueError(f"{purpose} host could not be resolved") from e
    addresses = set()
    for result in resolved:
        sockaddr = result[4] if len(result) > 4 else None
        if not sockaddr:
            continue
        try:
            addresses.add(ipaddress.ip_address(sockaddr[0]))
        except (ValueError, TypeError):
            continue
    if not addresses:
        raise ValueError(f"{purpose} host did not resolve to an IP address")
    if any(not address.is_global for address in addresses):
        raise ValueError(f"{purpose} host resolved to a private or local address")
    return parsed_url.geturl()


def _validated_chapter_url(chapter_url):
    return _validated_public_http_url(chapter_url, purpose="chapter")


def _open_public_http_stream(
    url,
    *,
    headers,
    timeout,
    purpose,
    max_redirects=_MAX_CHAPTER_REDIRECTS,
):
    """Open a bounded streaming GET after validating every redirect target."""
    current_url = str(url or "").strip()
    for redirect_count in range(int(max_redirects) + 1):
        current_url = _validated_public_http_url(current_url, purpose=purpose)
        response = safe_requests_get(
            current_url,
            headers=headers,
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code not in {301, 302, 303, 307, 308}:
            return response, current_url
        try:
            location = _response_header(response, "Location")
        finally:
            try:
                response.close()
            except Exception:
                pass
        if not location:
            raise ValueError(f"{purpose} redirect is missing a Location header")
        if redirect_count >= int(max_redirects):
            raise ValueError(f"too many {purpose} redirects")
        current_url = urllib.parse.urljoin(current_url, str(location))
    raise ValueError(f"too many {purpose} redirects")


def _chapter_json_mime_is_compatible(content_type):
    if not content_type:
        return True
    mime = str(content_type).split(";", 1)[0].strip().lower()
    return mime in _CHAPTER_JSON_MIME_TYPES or (
        mime.startswith("application/") and mime.endswith("+json")
    )


def _validate_chapter_document(data):
    if not isinstance(data, Mapping):
        raise ValueError("chapter JSON root must be an object")
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("chapter JSON requires a string version")
    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        raise ValueError("chapter JSON requires a chapters array")
    return data


def _fetch_chapter_json(chapter_url, *, etag=None, last_modified=None):
    request_headers = add_revalidation_headers(
        {
            "Accept": (
                "application/json+chapters, application/json;q=0.9, "
                "application/*+json;q=0.8, text/json;q=0.7"
            )
        }
    )
    if etag:
        request_headers["If-None-Match"] = str(etag)
    if last_modified:
        request_headers["If-Modified-Since"] = str(last_modified)

    resp, current_url = _open_public_http_stream(
        chapter_url,
        headers=request_headers,
        timeout=(5, 10),
        purpose="chapter",
    )
    try:
        status_code = int(getattr(resp, "status_code", 200) or 200)
        if status_code == 304:
            return {
                "status": 304,
                "data": None,
                "etag": _response_header(resp, "ETag") or etag,
                "last_modified": (
                    _response_header(resp, "Last-Modified") or last_modified
                ),
                "url": current_url,
            }

        resp.raise_for_status()
        content_type = _response_header(resp, "Content-Type")
        if not _chapter_json_mime_is_compatible(content_type):
            raise ValueError(
                f"unsupported chapter JSON content type: {content_type}"
            )
        content_length = _response_header(resp, "Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError):
                declared_length = None
            if declared_length is not None and declared_length > _MAX_CHAPTER_JSON_BYTES:
                raise ValueError("chapter JSON is too large")

        raw = bytearray()
        if hasattr(resp, "iter_content"):
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                raw.extend(chunk)
                if len(raw) > _MAX_CHAPTER_JSON_BYTES:
                    raise ValueError("chapter JSON is too large")
        if raw:
            data = json.loads(raw.decode("utf-8-sig"))
        else:
            data = resp.json()
        _validate_chapter_document(data)
        return {
            "status": status_code,
            "data": data,
            "etag": _response_header(resp, "ETag"),
            "last_modified": _response_header(resp, "Last-Modified"),
            "url": current_url,
        }
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _load_chapter_json(chapter_url):
    """Compatibility wrapper for callers/tests that only need the parsed document."""
    return _fetch_chapter_json(chapter_url)["data"]


def _chapter_source_key(article_key, cache_key=None):
    storage_key = str(cache_key or article_key or "").strip()
    if not storage_key:
        return None
    return storage_key if cache_key else f"local:{storage_key}"


def _get_chapter_source(article_key=None, *, cache_key=None, cursor=None):
    source_key = _chapter_source_key(article_key, cache_key)
    if not source_key:
        return None
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    try:
        c.execute(
            "SELECT source_url, etag, last_modified, checked_at, fetched_at "
            "FROM chapter_sources WHERE cache_key = ?",
            (source_key,),
        )
        row = c.fetchone()
        if not row:
            return None
        return {
            "source_url": row[0],
            "etag": row[1],
            "last_modified": row[2],
            "checked_at": float(row[3] or 0),
            "fetched_at": float(row[4] or 0),
        }
    finally:
        if conn is not None:
            conn.close()


def _save_chapter_source(
    article_key,
    source_url,
    *,
    cache_key=None,
    etag=None,
    last_modified=None,
    checked_at=None,
    fetched_at=None,
    cursor=None,
):
    source_key = _chapter_source_key(article_key, cache_key)
    if not source_key or not source_url:
        return False
    conn = None
    c = cursor
    if c is None:
        conn = get_connection()
        c = conn.cursor()
    checked = float(checked_at if checked_at is not None else time.time())
    fetched = float(fetched_at if fetched_at is not None else checked)
    try:
        c.execute(
            "INSERT INTO chapter_sources "
            "(cache_key, source_url, etag, last_modified, checked_at, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET "
            "source_url=excluded.source_url, etag=excluded.etag, "
            "last_modified=excluded.last_modified, checked_at=excluded.checked_at, "
            "fetched_at=excluded.fetched_at",
            (
                source_key,
                str(source_url),
                etag,
                last_modified,
                checked,
                fetched,
            ),
        )
        if conn is not None:
            conn.commit()
        return True
    except sqlite3.Error as e:
        log.debug("Could not persist chapter source metadata for %s: %s", source_key, e)
        return False
    finally:
        if conn is not None:
            conn.close()


def get_chapter_source_url(article_id=None, *, cache_key=None):
    source = _get_chapter_source(article_id, cache_key=cache_key)
    return source.get("source_url") if source else None


def get_chapters_from_db(article_id: str, *, cache_key=None):
    storage_key = str(cache_key or article_id or "").strip()
    if not storage_key:
        return []
    conn = get_connection()
    try:
        c = conn.cursor()
        if cache_key:
            c.execute(
                "SELECT start, title, href FROM chapter_cache "
                "WHERE cache_key = ? ORDER BY start",
                (storage_key,),
            )
        else:
            c.execute(
                "SELECT start, title, href FROM chapters "
                "WHERE article_id = ? ORDER BY start",
                (storage_key,),
            )
        rows = c.fetchall()
        if not rows and cache_key and article_id:
            # Preserve caches written by older builds before hosted IDs were scoped.
            c.execute(
                "SELECT start, title, href FROM chapters "
                "WHERE article_id = ? ORDER BY start",
                (str(article_id),),
            )
            rows = c.fetchall()
        return [{"start": r[0], "title": r[1], "href": r[2]} for r in rows]
    finally:
        conn.close()


def get_chapters_batch(article_ids: list, *, cache_keys=None) -> dict:
    """
    Fetch chapters for multiple articles in chunks.

    ``cache_keys`` maps hosted article IDs to provider-scoped cache keys. Local
    callers omit it and continue reading the foreign-keyed ``chapters`` table.
    """
    if not article_ids:
        return {}

    normalized_ids = [str(article_id) for article_id in article_ids]
    key_map = {
        article_id: str((cache_keys or {}).get(article_id) or article_id)
        for article_id in normalized_ids
    }
    reverse_keys = {}
    for article_id, storage_key in key_map.items():
        reverse_keys.setdefault(storage_key, []).append(article_id)

    conn = get_connection()
    try:
        c = conn.cursor()
        chapters_map = {}
        storage_keys = list(reverse_keys)
        chunk_size = 900
        table = "chapter_cache" if cache_keys else "chapters"
        key_column = "cache_key" if cache_keys else "article_id"
        for i in range(0, len(storage_keys), chunk_size):
            chunk = storage_keys[i:i + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            c.execute(
                f"SELECT {key_column}, start, title, href FROM {table} "
                f"WHERE {key_column} IN ({placeholders}) ORDER BY {key_column}, start",
                chunk,
            )
            for storage_key, start, title, href in c.fetchall():
                for article_id in reverse_keys.get(storage_key, []):
                    chapters_map.setdefault(article_id, []).append(
                        {"start": start, "title": title, "href": href}
                    )
        return chapters_map
    finally:
        conn.close()


def chapter_source_and_media(item):
    """Return ``(chapter_url, media_url, media_type)`` from common provider shapes."""
    if not isinstance(item, Mapping):
        return None, None, None

    chapter_url = None
    for key in (
        "chapter_url",
        "chapters_url",
        "podcast_chapters",
        "podcast:chapters",
        "chapters",
    ):
        candidate = item.get(key)
        if isinstance(candidate, Mapping):
            candidate = candidate.get("url") or candidate.get("href")
        if isinstance(candidate, str) and candidate.strip().lower().startswith(("http://", "https://")):
            chapter_url = candidate.strip()
            break

    media_url = item.get("media_url")
    media_type = item.get("media_type") or item.get("mime_type")
    enclosure_groups = (
        item.get("enclosures"),
        item.get("enclosure"),
        item.get("attachments"),
    )
    for group in enclosure_groups:
        if isinstance(group, Mapping):
            group = [group]
        if not isinstance(group, (list, tuple)):
            continue
        for enclosure in group:
            if not isinstance(enclosure, Mapping):
                continue
            url = enclosure.get("url") or enclosure.get("href")
            mime = enclosure.get("mime_type") or enclosure.get("type")
            mime_l = canonical_media_type(mime)
            if url and (
                mime_l == "application/json+chapters"
                or mime_l.endswith("+json") and "chapter" in mime_l
            ):
                chapter_url = chapter_url or str(url)
                continue
            if url and not media_url:
                media_url = url
                media_type = mime

    # Hosted reader APIs often expose YouTube Atom items as ordinary article
    # links with no enclosure. Treat only strict YouTube video links as media
    # so their structured player chapters work through the provider-neutral
    # chapter cache too.
    if not media_url:
        link_candidates = [item.get("url"), item.get("canonical")]
        alternates = item.get("alternate") or item.get("alternates") or []
        if isinstance(alternates, Mapping):
            alternates = [alternates]
        if isinstance(alternates, (list, tuple)):
            link_candidates.extend(
                alt.get("href") or alt.get("url")
                for alt in alternates
                if isinstance(alt, Mapping)
            )
        try:
            from core import youtube_fulltext

            for candidate in link_candidates:
                if isinstance(candidate, str) and youtube_fulltext.is_youtube_video_url(candidate):
                    media_url = candidate.strip()
                    media_type = "video/youtube"
                    break
        except Exception:
            pass
    return chapter_url, media_url, media_type


def _chapters_from_id3(id3):
    parsed_chapters = []
    for frame in id3.getall("CHAP"):
        start_ms = getattr(frame, "start_time", None)
        start = _chapter_start_seconds(
            float(start_ms) / 1000.0 if start_ms is not None else None
        )
        if start is None:
            continue
        title_ch = ""
        sub_frames = getattr(frame, "sub_frames", {}) or {}
        tit2 = sub_frames.get("TIT2")
        if tit2 is None and hasattr(sub_frames, "getall"):
            title_frames = sub_frames.getall("TIT2")
            tit2 = title_frames[0] if title_frames else None
        if tit2 and tit2.text:
            title_ch = _chapter_text(tit2.text[0], empty="") or ""
        href = None
        for frame_name in ("WXXX", "WOAR", "WCOM", "WPUB"):
            url_frame = sub_frames.get(frame_name)
            if url_frame is None and hasattr(sub_frames, "getall"):
                url_frames = sub_frames.getall(frame_name)
                url_frame = url_frames[0] if url_frames else None
            candidate = getattr(url_frame, "url", None) if url_frame else None
            if candidate:
                href = _chapter_text(candidate, empty=None)
                break
        parsed_chapters.append({"start": start, "title": title_ch, "href": href})
    return _normalize_chapters(parsed_chapters)


def _local_media_path(media_url):
    value = str(media_url or "").strip()
    if not value:
        return None
    normalized_slashes = value.replace("\\", "/")
    if normalized_slashes.startswith("//") or normalized_slashes.lower().startswith("//?/unc/"):
        return None
    drive, _tail = os.path.splitdrive(value)
    if drive:
        if _path_is_network_share(value):
            return None
        return value if os.path.isfile(value) else None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme:
        if parsed.scheme.lower() != "file" or parsed.netloc:
            return None
        path = urllib.parse.unquote(parsed.path or "")
        if path.replace("\\", "/").startswith("//"):
            return None
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
    else:
        path = value
    if _path_is_network_share(path):
        return None
    return path if os.path.isfile(path) else None


def _path_is_network_share(path):
    normalized = str(path or "").replace("\\", "/")
    if normalized.startswith("//") or normalized.lower().startswith("//?/unc/"):
        return True
    if os.name != "nt":
        return False
    drive, _tail = os.path.splitdrive(str(path or ""))
    if not drive:
        return False
    try:
        import ctypes
        root = drive.rstrip("\\/") + "\\"
        return int(ctypes.windll.kernel32.GetDriveTypeW(root)) == 4
    except Exception:
        return False


def _read_prefix_bytes(url: str, *, headers: dict, max_bytes: int, timeout_s: int) -> bytes:
    if max_bytes <= 0:
        return b""
    resp, _final_url = _open_public_http_stream(
        url,
        headers=headers,
        timeout=int(timeout_s),
        purpose="media",
    )
    try:
        if not getattr(resp, "ok", False):
            return b""
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            remaining = int(max_bytes) - len(buf)
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                buf.extend(chunk[:remaining])
                break
            buf.extend(chunk)
            if len(buf) >= int(max_bytes):
                break
        return bytes(buf)
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _embedded_media_chapters(media_url, media_type):
    media_url_str = str(media_url or "")
    media_type_l = canonical_media_type(media_type)
    media_path_l = urllib.parse.urlsplit(media_url_str).path.lower() or media_url_str.lower()
    local_path = _local_media_path(media_url_str)

    if local_path:
        suffix = Path(local_path).suffix.lower()
        if suffix == ".mp3" or media_type_l == "audio/mpeg":
            from mutagen.id3 import ID3
            return _chapters_from_id3(ID3(local_path))
        if suffix in {".m4a", ".m4b", ".mp4"} or media_type_l in {
            "audio/mp4",
            "video/mp4",
            "audio/x-m4a",
        }:
            from mutagen.mp4 import MP4
            mp4_file = MP4(local_path)
            return _normalize_chapters(
                [
                    {
                        "start": getattr(chapter, "start", None),
                        "title": getattr(chapter, "title", ""),
                    }
                    for chapter in (getattr(mp4_file, "chapters", None) or [])
                ]
            )
        return []

    # Mutagen can reliably parse an ID3 tag from a bounded prefix request. MP4
    # chapter atoms can live at the end of the file, so remote MP4/AAC/Ogg/FLAC
    # files are intentionally not downloaded or advertised as supported here.
    if not (
        media_path_l.endswith(".mp3")
        or media_type_l == "audio/mpeg"
        or media_type_l == "audio/mp3"
    ):
        return []

    from mutagen.id3 import ID3
    hdr = _read_prefix_bytes(
        media_url_str,
        headers={"Range": "bytes=0-9"},
        max_bytes=10,
        timeout_s=6,
    )
    if len(hdr) < 10 or hdr[:3] != b"ID3":
        return []
    flags = int(hdr[5])
    ss = hdr[6:10]
    tag_size = (
        ((ss[0] & 0x7F) << 21)
        | ((ss[1] & 0x7F) << 14)
        | ((ss[2] & 0x7F) << 7)
        | (ss[3] & 0x7F)
    )
    total = int(tag_size) + 10 + (10 if flags & 0x10 else 0)
    if total <= 10 or total > 1_000_000:
        return []
    tag_bytes = _read_prefix_bytes(
        media_url_str,
        headers={"Range": f"bytes=0-{total - 1}"},
        max_bytes=total,
        timeout_s=12,
    )
    if len(tag_bytes) < 10 or tag_bytes[:3] != b"ID3":
        return []
    return _chapters_from_id3(ID3(BytesIO(tag_bytes)))


def fetch_and_store_chapters(
    article_id,
    media_url,
    media_type,
    chapter_url=None,
    allow_id3: bool = True,
    cursor=None,
    *,
    cache_key=None,
    force_refresh: bool = False,
):
    """Fetch, validate, cache, and return external or embedded chapters."""
    try:
        article_key = str(article_id).strip() if article_id is not None else ""
    except Exception:
        article_key = ""
    if not article_key:
        article_key = None

    storage_key = str(cache_key or article_key or "").strip()
    if cursor and storage_key:
        if cache_key:
            cursor.execute(
                "SELECT start, title, href FROM chapter_cache "
                "WHERE cache_key = ? ORDER BY start",
                (storage_key,),
            )
        else:
            cursor.execute(
                "SELECT start, title, href FROM chapters "
                "WHERE article_id = ? ORDER BY start",
                (storage_key,),
            )
        rows = cursor.fetchall()
        existing = [{"start": float(r[0] or 0), "title": r[1], "href": r[2]} for r in rows]
    elif storage_key:
        existing = get_chapters_from_db(article_key, cache_key=cache_key)
    else:
        existing = []

    # 1) Explicit chapter URL (Podcasting 2.0)
    if chapter_url:
        source = _get_chapter_source(article_key, cache_key=cache_key, cursor=cursor)
        source_matches = bool(
            source and str(source.get("source_url") or "") == str(chapter_url)
        )
        if (
            existing
            and source_matches
            and not force_refresh
            and (time.time() - float(source.get("checked_at") or 0))
            < _CHAPTER_REFRESH_SECONDS
        ):
            return existing
        try:
            result = _fetch_chapter_json(
                chapter_url,
                etag=source.get("etag") if source_matches else None,
                last_modified=source.get("last_modified") if source_matches else None,
            )
            now = time.time()
            if result["status"] == 304:
                if not existing:
                    # A validator is only useful with a cached representation.
                    # Broken intermediaries can return 304 after the local rows
                    # were evicted, so retry once with no conditional headers.
                    result = _fetch_chapter_json(chapter_url)
                    if result["status"] == 304:
                        raise ValueError(
                            "chapter server returned 304 to an unconditional request"
                        )
                    now = time.time()
                else:
                    _save_chapter_source(
                        article_key,
                        chapter_url,
                        cache_key=cache_key,
                        etag=result.get("etag"),
                        last_modified=result.get("last_modified"),
                        checked_at=now,
                        fetched_at=(source or {}).get("fetched_at") or now,
                        cursor=cursor,
                    )
                    return existing

            chapters_out = _normalize_chapters(result["data"]["chapters"])
            _replace_stored_chapters(
                article_key,
                chapters_out,
                cursor=cursor,
                cache_key=cache_key,
                allow_empty=True,
            )
            _save_chapter_source(
                article_key,
                chapter_url,
                cache_key=cache_key,
                etag=result.get("etag"),
                last_modified=result.get("last_modified"),
                checked_at=now,
                fetched_at=now,
                cursor=cursor,
            )
            return chapters_out
        except Exception as e:
            log.warning("Chapter fetch failed for %s: %s", chapter_url, e)
            if existing:
                return existing

    if existing:
        return existing

    # YouTube chapters are structured player metadata, not embedded in the
    # watch-page HTML or the RSS enclosure. Store them through the same cache as
    # podcast chapters so every GUI (including the accessible reader/player)
    # sees one consistent chapter list.
    if media_url:
        try:
            from core import youtube_fulltext

            if youtube_fulltext.is_youtube_video_url(media_url):
                parsed_chapters = _normalize_chapters(
                    youtube_fulltext.extract_chapters(media_url)
                )
                if parsed_chapters:
                    _replace_stored_chapters(
                        article_key,
                        parsed_chapters,
                        cursor=cursor,
                        cache_key=cache_key,
                    )
                return parsed_chapters
        except Exception as e:
            log.info("YouTube chapter extraction failed for %s: %s", media_url, e)

    if not allow_id3:
        return []

    # 2) Embedded chapters in formats Mutagen exposes reliably.
    if media_url:
        try:
            parsed_chapters = _embedded_media_chapters(media_url, media_type)
            if not parsed_chapters:
                return []
            _replace_stored_chapters(
                article_key,
                parsed_chapters,
                cursor=cursor,
                cache_key=cache_key,
            )
            return parsed_chapters
        except ImportError:
            log.info("mutagen not installed, skipping embedded chapter parse.")
        except Exception as e:
            log.info("Embedded chapter parse failed for %s: %s", media_url, e)

    return []


# --- OPML Helpers ---


def _opml_category_parts(category):
    category = str(category or "").strip()
    if not category or category == UNCATEGORIZED:
        return []
    return [part.strip() for part in category.split(CATEGORY_PATH_SEP) if part.strip()]


def _opml_append_category(parent_category, folder_title):
    path = str(parent_category or "").strip()
    if path == UNCATEGORIZED:
        path = ""
    for part in _opml_category_parts(folder_title):
        leaf = sanitize_category_leaf(part)
        if leaf:
            path = make_category_path(path, leaf)
    return path or UNCATEGORIZED


def _feed_opml_fields(feed):
    if isinstance(feed, Mapping):
        return (
            feed.get("title"),
            feed.get("url") or feed.get("xmlUrl"),
            feed.get("category", UNCATEGORIZED),
        )
    if isinstance(feed, (tuple, list)):
        title = feed[0] if len(feed) > 0 else None
        url = feed[1] if len(feed) > 1 else None
        category = feed[2] if len(feed) > 2 else UNCATEGORIZED
        return title, url, category
    return (
        getattr(feed, 'title', None),
        getattr(feed, 'url', None),
        getattr(feed, 'category', UNCATEGORIZED),
    )

def parse_opml(path: str):
    """
    Parses an OPML file and yields (title, url, category) tuples.
    """
    try:
        content = ""
        # Try to read file with different encodings
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        
        if not content:
            log.error("OPML Parse: Could not read file with supported encodings")
            return

        # Try parsing with BS4
        soup = None
        try:
            soup = BS(content, 'xml')
        except Exception:
            pass
        
        if not soup or not soup.find('opml'):
            soup = BS(content, 'html.parser')

        body = soup.find('body')
        if not body:
            return

        def process_outline(outline, current_category=UNCATEGORIZED):
            # Case insensitive attribute lookup
            def get_attr(name):
                if name in outline.attrs:
                    return outline.attrs[name]
                for k, v in outline.attrs.items():
                    if k.lower() == name.lower():
                        return v
                return None

            text = get_attr('text') or get_attr('title')
            xmlUrl = get_attr('xmlUrl')
            
            if xmlUrl:
                yield (text, xmlUrl, current_category)
            
            # Recursion
            children = outline.find_all('outline', recursive=False)
            if children:
                new_cat = current_category
                if not xmlUrl:
                    # It's a folder
                    new_cat = _opml_append_category(current_category, text)
                for child in children:
                    yield from process_outline(child, new_cat)

        for outline in body.find_all('outline', recursive=False):
            yield from process_outline(outline)

    except Exception as e:
        log.error(f"OPML Parse Error: {e}")


def write_opml(feeds: list, path: str):
    """
    Writes a list of Feed objects (or dicts/tuples with title, url, category) to an OPML file.
    """
    try:
        root = ET.Element("opml", version="1.0")
        head = ET.SubElement(root, "head")
        ET.SubElement(head, "title").text = "RSS Exports"
        body = ET.SubElement(root, "body")
        
        category_outlines = {}
        for feed in feeds:
            title, url, cat = _feed_opml_fields(feed)
            parent = body
            path_parts = []
            for part in _opml_category_parts(cat):
                path_parts.append(part)
                path_key = tuple(path_parts)
                if path_key not in category_outlines:
                    category_outlines[path_key] = ET.SubElement(parent, "outline", text=part)
                parent = category_outlines[path_key]
            ET.SubElement(parent, "outline", text=title or "", xmlUrl=url or "")
                    
        tree = ET.ElementTree(root)
        tree.write(path, encoding='utf-8', xml_declaration=True)
        return True
    except Exception as e:
        log.error(f"OPML Write Error: {e}")
        return False

def resolve_final_url(url: str, max_redirects: int = 30, timeout_s: float = 15.0, user_agent: str | None = None) -> str:
    """Resolve tracking/redirect URLs to a final URL that VLC can open reliably.

    This performs an HTTP GET with redirects enabled and then closes the response immediately.
    """
    if not isinstance(url, str):
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        return url

    ua = user_agent or HEADERS.get("User-Agent", "")
    hdrs = HEADERS.copy()
    hdrs["User-Agent"] = ua

    try:
        s = requests.Session()
        s.max_redirects = int(max_redirects) if int(max_redirects) > 0 else 30
        # GET (not HEAD): many trackers/hosts behave differently for HEAD and can loop.
        r = s.get(url, allow_redirects=True, timeout=timeout_s, headers=hdrs, stream=True)
        # Consume nothing; just close the socket.
        final = r.url or url
        try:
            r.close()
        except Exception:
            pass
        return final
    except Exception:
        return url


def normalize_user_submitted_url(value: str) -> str:
    """Remove common Markdown wrappers accidentally pasted with a URL.

    A single trailing backtick is particularly easy to copy from issue text and
    becomes a different upstream path (issue #79). Only presentation delimiters
    are removed; URL query/path punctuation is otherwise preserved.
    """
    text = str(value or "").strip()
    if len(text) >= 2 and text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()
    return text.strip("`").strip()


def normalize_url_for_vlc(url: str) -> str:
    """Ensure URL is safely encoded for VLC (avoid unescaped spaces, etc.)."""
    if not isinstance(url, str):
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        return url
    try:
        parts = urllib.parse.urlsplit(url)
        # Keep reserved characters, but encode spaces and other unsafe chars.
        # Include '%' in safe to avoid double-encoding already-encoded sequences like %27.
        path = urllib.parse.quote(parts.path, safe="/:@-._~!$&'()*+,;=%")
        query = urllib.parse.quote_plus(parts.query, safe="=&:@-._~!$&'()*+,;/%")
        frag = urllib.parse.quote(parts.fragment, safe="%")
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, frag))
    except Exception:
        return url


# ── Custom "open article" command (issue #31) ────────────────────────────────
# Users can open article links with a custom browser/command instead of the OS
# default, e.g. "chrome --incognito %1" or
# '"C:\\Program Files\\Mozilla Firefox\\firefox.exe" --private-window %1'.
# %1 is replaced with the article URL (appended if the template omits it).

def build_open_command(template, url):
    """Parse a custom open-article command template into an argv list (issue #31).

    ``%1`` is replaced by ``url``; if the template contains no ``%1`` the URL is
    appended as the final argument. Quoting is honored and backslashes are
    preserved so Windows paths work. Raises ``ValueError`` for an empty or
    unparseable template.
    """
    template = str(template or "").strip()
    if not template:
        raise ValueError("The command is empty.")
    # On Windows, parse in non-POSIX mode so backslashes in paths survive; that
    # mode keeps surrounding quotes on tokens, so strip them afterwards.
    posix = not sys.platform.startswith("win")
    try:
        parts = shlex.split(template, posix=posix)
    except ValueError as exc:
        raise ValueError(f"Could not parse the command: {exc}")
    cleaned = []
    for part in parts:
        if not posix and len(part) >= 2 and part[0] == '"' and part[-1] == '"':
            part = part[1:-1]
        cleaned.append(part)
    if not cleaned:
        raise ValueError("The command is empty.")

    url = str(url or "")
    argv = []
    substituted = False
    for part in cleaned:
        if "%1" in part:
            argv.append(part.replace("%1", url))
            substituted = True
        else:
            argv.append(part)
    if not substituted:
        argv.append(url)
    return argv


def launch_open_command(template, url):
    """Launch a custom open-article command (issue #31).

    Returns ``(ok, error_message)``. ``ok`` is True when the process was
    launched; on failure ``error_message`` describes why (empty/unparseable
    command, executable not found, or OS error) for display to the user.
    """
    try:
        argv = build_open_command(template, url)
    except ValueError as exc:
        return False, str(exc)
    import subprocess
    try:
        subprocess.Popen(argv)
        return True, ""
    except FileNotFoundError:
        return False, f"Command not found: {argv[0]}"
    except OSError as exc:
        return False, str(exc)
