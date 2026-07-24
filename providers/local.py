# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import feedparser
import json
import time
import uuid
import threading
import sqlite3
import concurrent.futures
import os
import re
import mimetypes
import requests
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, deque
from urllib.parse import urlparse, urljoin
from .base import RSSProvider
from core.models import Feed, Article
from core.categories import UNCATEGORIZED
from core.db import (
    get_connection,
    init_db,
    get_feed_settings,
    get_feed_refresh_interval_overrides,
    record_feed_error,
    clear_feed_error,
    get_feed_errors,
    deleted_article_tombstones_for_feed,
    remember_deleted_article,
    list_deleted_articles,
    restore_deleted_article,
    purge_deleted_article,
    record_article_version,
    get_smart_folder,
    list_filter_rules,
    get_feed_delete_behavior,
)
from core import article_lang
from core import smart_folders as smart_folders_mod
from core import filters as filters_mod
from core.discovery import discover_feed
from core import utils
from core import rumble as rumble_mod
from core import odysee as odysee_mod
from core import npr as npr_mod
from core import sky as sky_mod
from core import text_encoding
from core import browser_feed as browser_feed_mod
from bs4 import BeautifulSoup as BS, MarkupResemblesLocatorWarning, XMLParsedAsHTMLWarning
import xml.etree.ElementTree as ET
import logging
import warnings
from urllib.parse import urlsplit, urlunsplit

# Avoid noisy warnings when falling back to HTML parser for XML content
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

log = logging.getLogger(__name__)

# Refresh is network-bound (threads mostly block on sockets), not CPU-bound, so
# these ceilings scale well above core count -- they exist to protect very low-end
# hardware from opening too many simultaneous connections, not to throttle CPU
# load. Per-host limits stay comparatively low to keep single-server politeness
# (the actual anti-bot/rate-limit concern, see issue #29) independent of the
# overall worker ceiling.
_REFRESH_WORKERS_CPU_1_2 = 8
_REFRESH_WORKERS_CPU_3_4 = 16
_REFRESH_WORKERS_CPU_5_8 = 24
_REFRESH_WORKERS_CPU_9_PLUS = 32
_REFRESH_PER_HOST_LOW_CPU = 2
_REFRESH_PER_HOST_NORMAL = 4
_REFRESH_PER_HOST_HIGH_CPU = 4

_REMOVE_FEED_BUSY_TIMEOUT_MS = 5000
_DELETE_ARTICLE_BUSY_TIMEOUT_MS = 5000
_FAST_REFRESH_DISCOVERY_TIMEOUT_SECONDS = 4.0
_FAST_REFRESH_DIRECT_PROBE_TIMEOUT_SECONDS = 4.0
_DISCOVERY_FAILURE_CACHE_TTL_SECONDS = 900.0
_DISCOVERY_SUCCESS_CACHE_TTL_SECONDS = 86400.0
_RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_PERMANENT_FAILURE_COOLDOWN_SECONDS = 1800.0
_TRANSIENT_FAILURE_COOLDOWN_SECONDS = 300.0
# Upper bound for exponential retry backoff (issue #29): repeated failures back off
# 1, 2, 4, 8s rather than hammering an unhappy/anti-bot server.
_MAX_RETRY_BACKOFF_SECONDS = 8.0
_NAME_RESOLUTION_ERROR_MARKERS = (
    "failed to resolve",
    "name resolution",
    "temporary failure in name resolution",
    "nodename nor servname provided",
    "getaddrinfo failed",
)
_CHAPTER_ELEMENT_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?chapters(?:\s|/?>)", re.IGNORECASE)
_JSON_FEED_VERSIONS = {
    "https://jsonfeed.org/version/1",
    "https://jsonfeed.org/version/1.1",
}


def _xml_local_name(name) -> str:
    text = str(name or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text.lower()


def _xml_attribute(element, *names) -> Optional[str]:
    wanted = {str(name).lower() for name in names}
    for key, value in getattr(element, "attrib", {}).items():
        if _xml_local_name(key) in wanted:
            text = str(value or "").strip()
            if text:
                return text
    return None


def _xml_direct_child_text(element, *names) -> str:
    wanted = {str(name).lower() for name in names}
    for child in list(element):
        if _xml_local_name(child.tag) not in wanted:
            continue
        try:
            text = "".join(child.itertext())
        except Exception:
            text = child.text or ""
        text = str(text or "").strip()
        if text:
            return text
    return ""


def _article_matches_deleted_tombstone(
    deleted_ids: set[str],
    deleted_urls: set[str],
    *article_ids,
    url: str | None = None,
) -> bool:
    for article_id in article_ids:
        aid = str(article_id or "").strip()
        if aid and aid in deleted_ids:
            return True
    clean_url = str(url or "").strip()
    return bool(clean_url and clean_url in deleted_urls)


def _feed_item_identity_keys(element) -> List[str]:
    keys = []
    for child in list(element):
        local_name = _xml_local_name(child.tag)
        if local_name not in {"guid", "id", "link"}:
            continue
        value = _xml_attribute(child, "href") if local_name == "link" else None
        if not value:
            value = str(child.text or "").strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def _entry_text(entry, *names) -> str:
    for name in names:
        try:
            value = entry.get(name)
        except Exception:
            value = None
        if isinstance(value, dict):
            value = value.get("value")
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _visible_text(html: str) -> str:
    """Return approximate visible text of an HTML fragment (tags/scripts/whitespace stripped)."""
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _visible_text_len(html: str) -> int:
    return len(_visible_text(html))


# Photo-credit / caption markers. A feed's ``content`` sometimes carries only an image caption
# (e.g. Bloomberg ships "Photographer: ...Bloomberg" or "Photo credit should read ...Getty Images"
# as the content while the real lede is in ``summary``). Captions are short, so we only treat a
# short candidate carrying one of these markers as a caption to avoid misjudging a real article
# that merely mentions Getty Images, etc.
_PHOTO_CAPTION_MARKER_RE = re.compile(
    r"(?i)(photographer:|photo\s+credit|photo\s+by\b|image\s+credit|getty\s+images|future\s+publishing)"
)
_PHOTO_CAPTION_MAX_LEN = 400


def _looks_like_photo_caption(text: str) -> bool:
    visible = _visible_text(text)
    if not visible or len(visible) > _PHOTO_CAPTION_MAX_LEN:
        return False
    return bool(_PHOTO_CAPTION_MARKER_RE.search(visible))


def _entry_content(entry) -> str:
    """Return the richest feed body text for an entry.

    Some feeds put the real article text in ``content`` (preferred when present and substantive),
    but others put only a photo caption or stub there while the useful lede lives in
    ``summary``/``description`` (e.g. Bloomberg's RSS ships an image caption as the content and the
    actual first paragraph as the summary). So instead of blindly preferring ``content``, pick the
    candidate with the most visible text, and skip photo captions unless nothing else is available.
    """
    candidates: List[str] = []
    try:
        contents = entry.get("content")
        if contents:
            first = contents[0]
            value = first.get("value") if isinstance(first, dict) else getattr(first, "value", None)
            if value:
                candidates.append(str(value))
    except Exception:
        pass

    for name in ("summary_detail", "summary", "description"):
        text = _entry_text(entry, name)
        if text:
            candidates.append(text)

    if not candidates:
        return ""
    non_caption = [c for c in candidates if not _looks_like_photo_caption(c)]
    return max(non_caption or candidates, key=_visible_text_len)


def _entry_description(entry) -> str:
    return (
        _entry_text(entry, "description")
        or _entry_text(entry, "summary_detail")
        or _entry_text(entry, "summary")
    )


def _entry_author(entry) -> str:
    author = _entry_text(entry, "dc_creator", "dcterms_creator", "creator")
    if author:
        return author

    try:
        detail = entry.get("author_detail") or {}
    except Exception:
        detail = {}
    if isinstance(detail, dict):
        author = str(detail.get("name") or detail.get("email") or "").strip()
    else:
        author = str(getattr(detail, "name", None) or getattr(detail, "email", None) or "").strip()
    if author:
        return author

    try:
        authors = entry.get("authors") or []
    except Exception:
        authors = []
    for item in authors:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("email") or "").strip()
        else:
            name = str(getattr(item, "name", None) or getattr(item, "email", None) or "").strip()
        if name:
            return name

    # feedparser normally splits the RSS "address (Display Name)" form into
    # author_detail above; this catches the feeds where it did not.
    return utils.normalize_author(_entry_text(entry, "author"))


def _entry_tags(entry) -> str:
    """Return the article's site tags/categories as a newline-separated string.

    feedparser exposes `<category>` / Atom `<category>` / media & podcast keyword
    tags as ``entry.tags`` (each a dict with a ``term``, and sometimes a
    ``label``). JSON Feed tags are mapped to the same shape upstream. Dedupes
    case-insensitively while preserving first-seen order; returns "" when none.
    """
    try:
        tags = entry.get("tags") or []
    except Exception:
        tags = []
    seen = set()
    out = []
    for tag in tags:
        if isinstance(tag, dict):
            term = tag.get("term") or tag.get("label")
        else:
            term = getattr(tag, "term", None) or getattr(tag, "label", None)
        term = str(term or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return "\n".join(out)


# Link rels that never point at the item's webpage. Without this filter,
# enclosure-only podcast items would report the mp3 as their article URL.
_NON_WEBPAGE_LINK_RELS = {"enclosure", "self", "hub", "replies", "edit", "icon", "license", "payment"}


def _entry_primary_link(entry) -> str:
    try:
        links = entry.get("links") or []
    except Exception:
        links = []

    for wanted_rel in ("alternate", ""):
        for link in links:
            try:
                rel = str(link.get("rel") or "")
                href = str(link.get("href") or "").strip()
            except Exception:
                rel = str(getattr(link, "rel", "") or "")
                href = str(getattr(link, "href", "") or "").strip()
            if not href or rel in _NON_WEBPAGE_LINK_RELS:
                continue
            if not wanted_rel or rel == wanted_rel:
                return href

    return _entry_text(entry, "link")


def _feed_urljoin(feed_url: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return urljoin(str(feed_url or ""), text)
    except Exception:
        return text


def _plain_text_preview(raw_text: Any, limit: Optional[int] = None) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""

    if "<" in text and ">" in text:
        try:
            text = BS(text, "html.parser").get_text(" ", strip=True)
        except Exception:
            pass

    text = " ".join(text.split())
    if limit is not None and len(text) > limit:
        text = text[: max(0, limit - 3)].rstrip() + "..."
    return text


def _url_path_lower(value: str) -> str:
    text = str(value or "").strip()
    try:
        return urlsplit(text).path.lower()
    except Exception:
        return text.lower()


def _media_type_from_url(value: str) -> str:
    path = _url_path_lower(value)
    if not path:
        return ""
    guessed = None
    try:
        guessed = mimetypes.guess_type(path)[0]
    except Exception:
        guessed = None
    guessed_norm = utils.canonical_media_type(guessed)
    if utils.media_type_is_audio_video_or_podcast(guessed_norm):
        return guessed_norm
    manual = {
        ".m4a": "audio/mp4",
        ".m4b": "audio/mp4",
        ".opus": "audio/ogg",
    }
    for ext, media_type in manual.items():
        if path.endswith(ext):
            return media_type
    return ""


def _entry_raw_date(entry) -> str:
    raw_date = _entry_text(
        entry,
        "published",
        "updated",
        "pubDate",
        "date",
        "created",
        "issued",
        "modified",
        "dc_date",
        "dcterms_created",
        "dcterms_issued",
        "dcterms_modified",
        "date_published",
        "date_modified",
        "lastmod",
        "last_modified",
    )
    if raw_date:
        return raw_date

    try:
        parsed = (
            entry.get("published_parsed")
            or entry.get("updated_parsed")
            or entry.get("created_parsed")
            or entry.get("issued_parsed")
            or entry.get("modified_parsed")
            or entry.get("expired_parsed")
        )
    except Exception:
        parsed = None
    if parsed:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", parsed)
        except Exception:
            return ""
    return ""


def _entry_base_id(entry, feed_id: str, feed_url: str, content: Optional[str] = None) -> str:
    identity = _entry_text(entry, "id") or _entry_text(entry, "guid") or _entry_primary_link(entry)
    if identity:
        return identity

    title = _entry_text(entry, "title")
    raw_date = _entry_raw_date(entry)
    body = content if content is not None else _entry_content(entry)
    body = " ".join(str(body or "").split())[:500]
    if not any((title, raw_date, body)):
        return ""

    seed = "|".join([str(feed_id or ""), str(feed_url or ""), title, raw_date, body])
    return f"blindrss:entry:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"


def _decode_feed_text(data, fallback_text: Optional[str] = None) -> str:
    if fallback_text is not None:
        return str(fallback_text or "")
    if isinstance(data, bytes):
        # Detection chain (issue #75): BOM -> XML prolog declaration -> utf-8,
        # degrading through latin-1/replace instead of ever raising.
        return text_encoding.decode_bytes(data, kind="xml")
    return str(data or "")


def _json_feed_author_name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("url") or "").strip()
    return str(value or "").strip()


def _json_feed_authors(item: dict, fallback_author=None) -> str:
    authors = item.get("authors")
    if isinstance(authors, list):
        names = [_json_feed_author_name(author) for author in authors]
        names = [name for name in names if name]
        if names:
            return ", ".join(names)

    author = _json_feed_author_name(item.get("author"))
    if author:
        return author

    return _json_feed_author_name(fallback_author)


def _json_feed_enclosure_links(item: dict) -> list:
    links = []
    attachments = item.get("attachments")
    if not isinstance(attachments, list):
        return links

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        href = str(attachment.get("url") or "").strip()
        if not href:
            continue
        link = feedparser.FeedParserDict({"href": href, "rel": "enclosure"})
        mime_type = str(attachment.get("mime_type") or "").strip()
        if mime_type:
            link["type"] = mime_type
        title = str(attachment.get("title") or "").strip()
        if title:
            link["title"] = title
        size = attachment.get("size_in_bytes")
        if size is not None:
            link["length"] = str(size)
        duration = attachment.get("duration_in_seconds")
        if duration is not None:
            link["duration"] = duration
        links.append(link)
    return links


def _parse_json_feed(text: str):
    try:
        payload = json.loads(str(text or ""))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    version = str(payload.get("version") or "").strip()
    items = payload.get("items")
    if version not in _JSON_FEED_VERSIONS or not isinstance(items, list):
        return None

    feed = feedparser.FeedParserDict()
    title = str(payload.get("title") or "").strip()
    if title:
        feed["title"] = title
    home_page_url = str(payload.get("home_page_url") or "").strip()
    if home_page_url:
        feed["link"] = home_page_url
    feed_url = str(payload.get("feed_url") or "").strip()
    if feed_url:
        feed["href"] = feed_url
    description = str(payload.get("description") or "").strip()
    if description:
        feed["subtitle"] = description
    fallback_author = payload.get("author")
    if not fallback_author and isinstance(payload.get("authors"), list) and payload["authors"]:
        fallback_author = payload["authors"][0]
    author = _json_feed_author_name(fallback_author)
    if author:
        feed["author"] = author

    entries = []
    for item in items:
        if not isinstance(item, dict):
            continue

        entry = feedparser.FeedParserDict()
        item_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or item.get("external_url") or "").strip()
        if item_id:
            entry["id"] = item_id
            entry["guid"] = item_id
        if url:
            entry["link"] = url
            entry["links"] = [feedparser.FeedParserDict({"href": url, "rel": "alternate"})]
        else:
            entry["links"] = []

        title = str(item.get("title") or "").strip()
        if title:
            entry["title"] = title

        content_html = item.get("content_html")
        content_text = item.get("content_text")
        content_value = content_html if content_html is not None else content_text
        if content_value is not None:
            entry["content"] = [feedparser.FeedParserDict({"value": str(content_value)})]

        summary = item.get("summary")
        if summary is None and content_text is not None:
            summary = content_text
        if summary is not None:
            entry["summary"] = str(summary)

        published = str(item.get("date_published") or "").strip()
        modified = str(item.get("date_modified") or "").strip()
        if published:
            entry["published"] = published
            entry["date_published"] = published
        if modified:
            entry["updated"] = modified
            entry["date_modified"] = modified

        author = _json_feed_authors(item, fallback_author=fallback_author)
        if author:
            entry["author"] = author

        tags = item.get("tags")
        if isinstance(tags, list):
            entry["tags"] = [
                feedparser.FeedParserDict({"term": str(tag)})
                for tag in tags
                if str(tag or "").strip()
            ]

        enclosure_links = _json_feed_enclosure_links(item)
        if enclosure_links:
            entry["links"].extend(enclosure_links)

        entries.append(entry)

    parsed = feedparser.FeedParserDict()
    parsed["feed"] = feed
    parsed["entries"] = entries
    parsed["bozo"] = False
    return parsed


def _parse_cdf_document(text: str):
    try:
        root = ET.fromstring(str(text or ""))
    except (ET.ParseError, ValueError):
        return None
    if _xml_local_name(root.tag) != "channel":
        return None

    item_elements = [child for child in list(root) if _xml_local_name(child.tag) == "item"]
    if not item_elements:
        return None

    base_url = _xml_attribute(root, "base") or ""
    channel_href = _xml_attribute(root, "href", "src") or ""
    channel_link = urljoin(base_url, channel_href) if channel_href else base_url

    feed = feedparser.FeedParserDict()
    feed["links"] = []
    title = _xml_direct_child_text(root, "title")
    if title:
        feed["title"] = title
    if channel_link:
        feed["link"] = channel_link
        feed["links"].append(
            feedparser.FeedParserDict({"href": channel_link, "rel": "alternate", "type": "text/html"})
        )
    subtitle = _xml_direct_child_text(root, "abstract", "description")
    if subtitle:
        feed["subtitle"] = subtitle

    entries = []
    for item in item_elements:
        entry = feedparser.FeedParserDict()
        entry["links"] = []
        href = _xml_attribute(item, "href", "src") or ""
        link = urljoin(base_url or channel_link, href) if href else ""
        if link:
            entry["id"] = link
            entry["link"] = link
            entry["links"].append(
                feedparser.FeedParserDict({"href": link, "rel": "alternate", "type": "text/html"})
            )

        title = _xml_direct_child_text(item, "title")
        if title:
            entry["title"] = title
        summary = _xml_direct_child_text(item, "abstract", "description")
        if summary:
            entry["summary"] = summary
            entry["summary_detail"] = feedparser.FeedParserDict(
                {"type": "text/plain", "language": None, "base": base_url or channel_link, "value": summary}
            )
        lastmod = _xml_attribute(item, "lastmod", "lastmodified") or _xml_direct_child_text(
            item, "lastmod", "lastmodified"
        )
        if lastmod:
            entry["updated"] = lastmod
            entry["lastmod"] = lastmod
        entries.append(entry)

    parsed = feedparser.FeedParserDict()
    parsed["feed"] = feed
    parsed["entries"] = entries
    parsed["bozo"] = False
    parsed["version"] = "cdf"
    return parsed


def _parse_feed_document(data, text: Optional[str] = None, content_type: str = ""):
    decoded_text = _decode_feed_text(data, text)
    stripped = decoded_text.lstrip()
    content_type = str(content_type or "").lower()
    if stripped.startswith("{") or "json" in content_type:
        json_feed = _parse_json_feed(decoded_text)
        if json_feed is not None:
            return json_feed

    cdf_feed = _parse_cdf_document(decoded_text)
    if cdf_feed is not None:
        return cdf_feed

    parsed = feedparser.parse(data)

    # Resilience: if 0 entries, try parsing decoded text as fallback
    # (Sometimes feedparser fails on bytes with certain encoding declarations vs actual content)
    if len(parsed.entries) == 0 and parsed.bozo and decoded_text:
        try:
            parsed_text = feedparser.parse(decoded_text)
            if len(parsed_text.entries) > 0:
                return parsed_text
        except Exception:
            pass

    return parsed


def _parse_feed_chapter_metadata_soup(xml_text: str) -> Dict[str, Dict[str, Any]]:
    """Best-effort fallback for feeds that feedparser accepts despite malformed XML."""
    try:
        soup = BS(xml_text, "xml")
    except Exception as parser_exc:
        log.debug("XML parser unavailable for chapter metadata fallback; using html.parser (%s)", parser_exc)
        soup = BS(xml_text, "html.parser")
    items = soup.find_all(lambda tag: _xml_local_name(getattr(tag, "name", "")) in {"item", "entry"})
    if not items:
        soup = BS(xml_text, "html.parser")
        items = soup.find_all(lambda tag: _xml_local_name(getattr(tag, "name", "")) in {"item", "entry"})

    metadata = {}
    for item in items:
        keys = []
        for child in item.find_all(recursive=False):
            local_name = _xml_local_name(getattr(child, "name", ""))
            if local_name not in {"guid", "id", "link"}:
                continue
            value = child.get("href") if local_name == "link" else None
            if not value:
                value = child.get_text(strip=True)
            if value and value not in keys:
                keys.append(value)

        chapter_url = None
        inline_chapters = []
        for element in item.find_all(
            lambda tag: _xml_local_name(getattr(tag, "name", "")) == "chapters"
        ):
            if not chapter_url:
                chapter_url = (
                    element.get("url")
                    or element.get("href")
                    or element.get("src")
                    or element.get("link")
                )
            for chapter in element.find_all(
                lambda tag: _xml_local_name(getattr(tag, "name", "")) == "chapter"
            ):
                inline_chapters.append(
                    {
                        "start": chapter.get("start") or chapter.get("starttime") or chapter.get("start_time"),
                        "title": chapter.get("title") or "",
                        "href": chapter.get("href") or chapter.get("url") or chapter.get("link"),
                    }
                )

        normalized_inline = utils._normalize_chapters(inline_chapters) if inline_chapters else []
        if not chapter_url and not normalized_inline:
            continue
        value = {"chapter_url": chapter_url, "chapters": normalized_inline}
        for key in keys:
            metadata[key] = value
    return metadata


def _parse_feed_chapter_metadata(xml_text: str) -> Dict[str, Dict[str, Any]]:
    """Map RSS/Atom item identities to external or inline chapter metadata."""
    text = str(xml_text or "")
    if not text or not _CHAPTER_ELEMENT_RE.search(text):
        return {}

    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError) as e:
        log.debug("Chapter metadata XML parse failed; using tolerant parser: %s", e)
        return _parse_feed_chapter_metadata_soup(text)

    metadata = {}
    for item in root.iter():
        if _xml_local_name(item.tag) not in {"item", "entry"}:
            continue

        chapter_url = None
        inline_chapters = []
        for element in item.iter():
            if _xml_local_name(element.tag) != "chapters":
                continue
            if not chapter_url:
                chapter_url = _xml_attribute(element, "url", "href", "src", "link")
            for chapter in element.iter():
                if chapter is element or _xml_local_name(chapter.tag) != "chapter":
                    continue
                inline_chapters.append(
                    {
                        "start": _xml_attribute(chapter, "start", "starttime", "start_time"),
                        "title": _xml_attribute(chapter, "title") or "",
                        "href": _xml_attribute(chapter, "href", "url", "link"),
                    }
                )

        normalized_inline = utils._normalize_chapters(inline_chapters) if inline_chapters else []
        if not chapter_url and not normalized_inline:
            continue
        value = {"chapter_url": chapter_url, "chapters": normalized_inline}
        for key in _feed_item_identity_keys(item):
            metadata[key] = value

    return metadata


def _xml_direct_child_feed_description(element) -> str:
    for wanted in ("description", "summary"):
        for child in list(element):
            if _xml_local_name(child.tag) != wanted:
                continue
            if wanted == "summary":
                tag_text = str(child.tag or "").lower()
                if "itunes.com" in tag_text:
                    continue
            try:
                text = "".join(child.itertext())
            except Exception:
                text = child.text or ""
            text = str(text or "").strip()
            if text:
                return text
    return ""


def _parse_feed_description_metadata_soup(xml_text: str) -> Dict[str, str]:
    try:
        soup = BS(xml_text, "xml")
    except Exception as parser_exc:
        log.debug("XML parser unavailable for description metadata fallback; using html.parser (%s)", parser_exc)
        soup = BS(xml_text, "html.parser")
    items = soup.find_all(lambda tag: _xml_local_name(getattr(tag, "name", "")) in {"item", "entry"})
    if not items:
        soup = BS(xml_text, "html.parser")
        items = soup.find_all(lambda tag: _xml_local_name(getattr(tag, "name", "")) in {"item", "entry"})

    metadata: Dict[str, str] = {}
    for item in items:
        description = ""
        for wanted in ("description", "summary"):
            for child in item.find_all(recursive=False):
                local_name = _xml_local_name(getattr(child, "name", ""))
                if local_name != wanted:
                    continue
                raw_name = str(getattr(child, "name", "") or "").lower()
                if wanted == "summary" and raw_name.startswith("itunes:"):
                    continue
                value = child.get_text(" ", strip=True)
                if value:
                    description = value
                    break
            if description:
                break
        if not description:
            continue

        keys = []
        for child in item.find_all(recursive=False):
            local_name = _xml_local_name(getattr(child, "name", ""))
            if local_name not in {"guid", "id", "link"}:
                continue
            value = child.get("href") if local_name == "link" else None
            if not value:
                value = child.get_text(strip=True)
            if value and value not in keys:
                keys.append(value)
        for key in keys:
            metadata[key] = description
    return metadata


def _parse_feed_description_metadata(xml_text: str) -> Dict[str, str]:
    """Map feed item identities to the literal feed-provided description/summary."""
    text = str(xml_text or "")
    if not text:
        return {}

    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError) as e:
        log.debug("Description metadata XML parse failed; using tolerant parser: %s", e)
        return _parse_feed_description_metadata_soup(text)

    metadata: Dict[str, str] = {}
    for item in root.iter():
        if _xml_local_name(item.tag) not in {"item", "entry"}:
            continue
        description = _xml_direct_child_feed_description(item)
        if not description:
            continue
        for key in _feed_item_identity_keys(item):
            metadata[key] = description
    return metadata


def _is_locked_error(error: Exception) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False

    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        try:
            return int(code) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        except (TypeError, ValueError):
            pass

    msg = str(error).lower()
    return "locked" in msg or "busy" in msg


def _is_foreign_key_error(error: Exception) -> bool:
    if not isinstance(error, sqlite3.IntegrityError):
        return False

    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        try:
            return int(code) == sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY
        except (TypeError, ValueError):
            pass

    msg = str(error).lower()
    return "foreign key" in msg


def _rollback_and_abort_on_foreign_key(conn: sqlite3.Connection, error: Exception) -> bool:
    if not _is_foreign_key_error(error):
        return False
    try:
        conn.rollback()
    except Exception:
        pass
    return True


def _adaptive_refresh_worker_cap(cpu_count: Optional[int] = None) -> int:
    cpu = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    if cpu <= 2:
        return _REFRESH_WORKERS_CPU_1_2
    if cpu <= 4:
        return _REFRESH_WORKERS_CPU_3_4
    if cpu <= 8:
        return _REFRESH_WORKERS_CPU_5_8
    return _REFRESH_WORKERS_CPU_9_PLUS


def _compute_refresh_limits(
    configured_workers: int,
    configured_per_host: int,
    feed_count: int,
    cpu_count: Optional[int] = None,
) -> Tuple[int, int, int]:
    adaptive_cap = _adaptive_refresh_worker_cap(cpu_count)
    max_workers = max(1, min(int(configured_workers), adaptive_cap, max(1, int(feed_count))))
    if adaptive_cap <= _REFRESH_WORKERS_CPU_1_2:
        per_host_cap = _REFRESH_PER_HOST_LOW_CPU
    elif adaptive_cap >= _REFRESH_WORKERS_CPU_5_8:
        per_host_cap = _REFRESH_PER_HOST_HIGH_CPU
    else:
        per_host_cap = _REFRESH_PER_HOST_NORMAL
    per_host_limit = max(1, min(int(configured_per_host), per_host_cap, max_workers))
    return max_workers, per_host_limit, adaptive_cap


def _refresh_row_host(feed_row) -> str:
    try:
        raw_url = feed_row[1]
    except Exception:
        raw_url = ""
    try:
        return (urlparse(str(raw_url or "")).hostname or str(raw_url or "")).lower()
    except Exception:
        return str(raw_url or "").lower()


def _interleave_feed_rows_by_host(feed_rows):
    """Round-robin feed rows by host before submitting work to the executor.

    Per-host semaphores are acquired inside worker tasks. If several same-host
    feeds are queued together, blocked tasks can occupy worker slots while
    unrelated hosts wait behind them. Interleaving keeps the worker pool useful.
    """
    buckets = {}
    host_order = []
    for row in list(feed_rows or []):
        host = _refresh_row_host(row)
        if host not in buckets:
            buckets[host] = deque()
            host_order.append(host)
        buckets[host].append(row)

    ordered = []
    while True:
        added = False
        for host in host_order:
            bucket = buckets.get(host)
            if not bucket:
                continue
            ordered.append(bucket.popleft())
            added = True
        if not added:
            break
    return ordered


def _load_current_feed_articles_for_entries(cursor, feed_id: str, base_ids) -> Dict[str, Dict[str, Any]]:
    """Load only stored rows represented by the feed document currently being refreshed.

    A feed response normally exposes only its recent entries, while its local history can contain
    thousands of older rows.  Refresh processing only ever consults the current response's base
    IDs (and their feed-scoped collision variants), so loading the full history wastes SQLite I/O
    and Python allocations on every forced/full refresh.
    """
    candidate_ids = []
    seen_ids = set()
    for raw_base_id in base_ids or ():
        base_id = str(raw_base_id or "").strip()
        if not base_id:
            continue
        for article_id in (base_id, f"{feed_id}:{base_id}"):
            if article_id not in seen_ids:
                seen_ids.add(article_id)
                candidate_ids.append(article_id)

    existing_articles = {}
    # SQLite's default parameter limit is commonly 999.  One parameter is reserved for feed_id.
    for offset in range(0, len(candidate_ids), 900):
        chunk = candidate_ids[offset:offset + 900]
        placeholders = ",".join("?" for _ in chunk)
        cursor.execute(
            "SELECT id, date, chapter_url, media_url, media_type, url, description "
            f"FROM articles WHERE feed_id = ? AND id IN ({placeholders})",
            (feed_id, *chunk),
        )
        for row in cursor.fetchall():
            existing_articles[row[0]] = {
                "date": row[1] or "",
                "chapter_url": row[2],
                "media_url": row[3],
                "media_type": row[4],
                "url": row[5] or "",
                "description": row[6] or "",
            }
    return existing_articles


def _url_looks_feed_like(url: str) -> bool:
    low = str(url or "").strip().lower()
    if not low:
        return False
    try:
        path = urlparse(low).path.rstrip("/")
        last_segment = path.rsplit("/", 1)[-1]
    except Exception:
        last_segment = ""
    return (
        low.endswith((".xml", ".rss", ".atom", ".cdf"))
        or "feed" in low
        or last_segment in {"rss", "atom", "feed", "feeds", "cdf"}
    )


def _http_status_from_error(error: Exception) -> Optional[int]:
    response = getattr(error, "response", None)
    if response is None:
        return None
    try:
        status = int(getattr(response, "status_code", 0) or 0)
    except Exception:
        return None
    return status or None


def _format_refresh_error(error: Exception) -> str:
    status = _http_status_from_error(error)
    detail = str(error) or type(error).__name__
    if status is not None:
        return f"HTTP {status}: {detail}"
    return f"Error: {detail}"


def _is_name_resolution_error(error: Exception) -> bool:
    text = str(error or "").lower()
    return any(marker in text for marker in _NAME_RESOLUTION_ERROR_MARKERS)


def _should_retry_refresh_error(error: Exception) -> bool:
    status = _http_status_from_error(error)
    if status is not None:
        return status in _RETRYABLE_HTTP_STATUS_CODES

    if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        return True

    if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return not _is_name_resolution_error(error)

    return False


def _resolve_feed_title_update(stored_title, title_is_custom, prev_upstream_title, fetched_title, feed_url):
    """Decide what to store for a feed's title after a refresh (issue #43).

    The user's custom name must always win over the feed-provided <title>.
    Returns (title_to_store, title_is_custom_to_store). A stored title that
    matches neither the previous upstream title, the feed URL, nor an empty
    placeholder is treated as a user rename even when title_is_custom was
    never set (renames made in builds that predate the flag) and is flagged
    custom so it survives future refreshes.
    """
    stored = str(stored_title or "").strip()
    fetched = str(fetched_title or "").strip()
    prev_upstream = str(prev_upstream_title or "").strip()
    url = str(feed_url or "").strip()

    if bool(int(title_is_custom or 0)) and stored:
        return stored, 1

    refresh_managed = (
        not stored
        or stored == url
        or stored == fetched
        or (prev_upstream and stored == prev_upstream)
    )
    if refresh_managed:
        return (fetched or stored or url), 0
    return stored, 1


_SSL_CERTIFICATE_ERROR_MARKERS = (
    "ssl certificate problem",
    "certificate verify failed",
    "certificate_verify_failed",
    "unable to get local issuer certificate",
    "self-signed certificate",
    "self signed certificate",
    "certificate has expired",
    "curl: (60)",
    "curl: (77)",
)


def _looks_like_ssl_certificate_error(error: Exception) -> bool:
    """True for certificate-validation failures (untrusted issuer, self-signed,
    expired, incomplete chain) from either the requests or curl_cffi transport."""
    if isinstance(error, requests.exceptions.SSLError):
        return True
    text = str(error or "").lower()
    return any(marker in text for marker in _SSL_CERTIFICATE_ERROR_MARKERS)


def _should_escalate_to_impersonation(error: Exception) -> bool:
    """True for transport/connection failures a browser-TLS impersonation retry might
    get past -- e.g. anti-bot WAFs that reset the connection (issue #29).

    HTTP-status errors and DNS name-resolution failures are excluded: impersonation
    cannot help those.
    """
    if _http_status_from_error(error) is not None:
        return False
    if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError)):
        return not _is_name_resolution_error(error)
    return False


def _retry_backoff_seconds(attempt: int, error: Optional[Exception] = None) -> float:
    response = getattr(error, "response", None) if error is not None else None
    retry_after = None
    try:
        retry_after = response.headers.get("Retry-After") if response is not None else None
    except Exception:
        retry_after = None

    if retry_after:
        try:
            return max(0.0, min(_MAX_RETRY_BACKOFF_SECONDS, float(retry_after)))
        except (TypeError, ValueError):
            pass

    # Exponential backoff (attempt is 1-based): 1s, 2s, 4s, 8s, capped. Honors a
    # server Retry-After above; otherwise backs off progressively (issue #29).
    delay = 2.0 ** max(0, int(attempt or 1) - 1)
    return max(0.25, min(_MAX_RETRY_BACKOFF_SECONDS, delay))


def _per_feed_attempt_deadline(timeout_s: float) -> float:
    """Monotonic deadline bounding one feed's total retry time this refresh cycle.

    A single unresponsive server (full ReadTimeout on every attempt, no fast
    failure to short-circuit on) could otherwise occupy a refresh worker slot for
    every configured retry plus the impersonation escalation back-to-back -- with
    feed_retry_attempts=0 that is 11 attempts, each paying the full timeout again.
    Scaling with the feed's own timeout (rather than a flat constant) means a feed
    with a deliberately raised per-feed timeout override still gets a proportional
    retry budget instead of being cut off after one attempt.
    """
    return time.monotonic() + max(20.0, 2.5 * float(timeout_s or 15.0))


def _failure_cooldown_seconds_for_error(error: Exception) -> float:
    status = _http_status_from_error(error)
    if status is not None:
        if status in (400, 401, 403, 404, 405, 410, 422):
            return _PERMANENT_FAILURE_COOLDOWN_SECONDS
        if status in _RETRYABLE_HTTP_STATUS_CODES:
            return _TRANSIENT_FAILURE_COOLDOWN_SECONDS

    if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        return _TRANSIENT_FAILURE_COOLDOWN_SECONDS

    if isinstance(error, requests.exceptions.ConnectionError):
        if _is_name_resolution_error(error):
            return _PERMANENT_FAILURE_COOLDOWN_SECONDS
        return _TRANSIENT_FAILURE_COOLDOWN_SECONDS

    return _TRANSIENT_FAILURE_COOLDOWN_SECONDS


def _response_looks_feed_like(resp) -> bool:
    content_type = str(getattr(resp, "headers", {}).get("Content-Type", "") or "").lower()
    if any(marker in content_type for marker in ("rss", "atom", "xml", "feed+json", "x-cdf")):
        return True

    try:
        snippet = str(getattr(resp, "text", "") or "")[:512].lstrip().lower()
    except Exception:
        snippet = ""

    return (
        snippet.startswith("<?xml")
        or "<rss" in snippet
        or "<feed" in snippet
        or (snippet.startswith("<channel") and "<item" in snippet)
        or '"version":"https://jsonfeed.org/version/' in snippet
        or '"version": "https://jsonfeed.org/version/' in snippet
    )


def _response_looks_cloudflare_challenge(resp) -> bool:
    headers = getattr(resp, "headers", {}) or {}
    if str(headers.get("Cf-Mitigated") or headers.get("cf-mitigated") or "").lower() == "challenge":
        return True

    try:
        snippet = str(getattr(resp, "text", "") or "")[:4096].lower()
    except Exception:
        snippet = ""
    return "challenges.cloudflare.com" in snippet and "just a moment" in snippet


def _response_looks_blocked(resp) -> bool:
    """True if a response looks like an anti-bot block a real browser fingerprint
    might get past (issue #29): a Cloudflare/JS challenge, a 200 OK that returns
    an HTML interstitial instead of a feed, or a 403/429 HTML block page instead
    of a feed (classic WAF wall, e.g. Akamai's "Access Denied" on radiofarda.com).
    Other 4xx/5xx are intentionally excluded so genuine errors aren't retried
    needlessly."""
    if _response_looks_cloudflare_challenge(resp):
        return True
    try:
        status_code = int(getattr(resp, "status_code", 0) or 0)
    except Exception:
        status_code = 0
    if status_code in (200, 403, 429) and not _response_looks_feed_like(resp):
        content_type = str(getattr(resp, "headers", {}).get("Content-Type", "") or "").lower()
        if "html" in content_type:
            return True
    return False


_BROWSER_FALLBACK_STATUS_CODES = frozenset({401, 403, 429, 503})

# Transport failures that look like an active anti-bot rejection: a TLS-level
# reset or a mid-response abort. Connection-refused, unreachable-network,
# timeout, and DNS failures mean a dead or unreachable server, which a real
# browser cannot fix.
_BROWSER_FALLBACK_RESET_MARKERS = (
    "connection reset",
    "reset by peer",
    "connection aborted",
    "remotedisconnected",
    "curl: (56)",
    "curl: (35)",
    "unexpected eof",
    "handshake",
)


def _browser_fallback_response_qualifies(resp) -> bool:
    """True when a response carries actual bot-protection evidence.

    The automated-browser fallback pays a serialized headless Chromium launch
    of up to browser_feed_fallback_timeout_seconds, so ordinary failures --
    dead feeds, 404s, webpages that simply are not feeds -- must never reach
    it. Escalating every terminal failure more than doubled refresh time on a
    several-hundred-feed collection (issue #79 follow-up)."""
    try:
        status_code = int(getattr(resp, "status_code", 0) or 0)
    except Exception:
        status_code = 0
    if status_code in _BROWSER_FALLBACK_STATUS_CODES or status_code >= 520:
        return True
    if _response_looks_cloudflare_challenge(resp):
        return True
    try:
        body = str(getattr(resp, "text", "") or "")
    except Exception:
        body = ""
    return browser_feed_mod._looks_like_challenge_page(body)


def _browser_fallback_error_qualifies(error: Exception) -> bool:
    """True when a terminal refresh failure looks like bot protection rather
    than a dead feed (see _browser_fallback_response_qualifies)."""
    status = _http_status_from_error(error)
    if status is not None:
        if status in _BROWSER_FALLBACK_STATUS_CODES or status >= 520:
            return True
        response = getattr(error, "response", None)
        return response is not None and _browser_fallback_response_qualifies(response)
    if isinstance(error, requests.exceptions.Timeout):
        return False
    if _is_name_resolution_error(error):
        return False
    text = str(error or "").lower()
    return any(marker in text for marker in _BROWSER_FALLBACK_RESET_MARKERS)


def _feed_has_stored_articles(feed_id: str) -> bool:
    try:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT 1 FROM articles WHERE feed_id = ? LIMIT 1", (feed_id,))
            return c.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return True


def _wordpress_feed_slash_variant(url: str) -> Optional[str]:
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except Exception:
        return None

    path = parts.path or ""
    if not path or path.endswith("/") or not path.lower().endswith("/feed"):
        return None
    return urlunsplit((parts.scheme, parts.netloc, path + "/", parts.query, parts.fragment))


def _retry_cloudflare_challenged_wordpress_feed(resp, url: str, *, headers: dict, timeout, proxies=None):
    """Retry WordPress-style /feed URLs with the canonical trailing slash after a challenge."""
    def _effective_url(response, fallback: str) -> str:
        # A response object's ``url`` alone is not evidence that this request
        # redirected (test doubles and adapters often populate it with an
        # arbitrary canonical-looking value).  Only adopt it for a normal
        # request when the client recorded a redirect history.  Explicit
        # WordPress retry callers still pass their known candidate as fallback.
        try:
            if not getattr(response, "history", None):
                return fallback
            resolved = str(getattr(response, "url", "") or "").strip()
        except Exception:
            resolved = ""
        return resolved or fallback

    try:
        status_code = int(getattr(resp, "status_code", 0) or 0)
    except Exception:
        status_code = 0
    if status_code != 403 or not _response_looks_cloudflare_challenge(resp):
        # requests/curl_cffi normally follow ordinary HTTP redirects. Preserve
        # their final response URL so the caller can persist it instead of
        # repeatedly refreshing the stale pre-redirect address.
        return resp, _effective_url(resp, url)

    candidate = _wordpress_feed_slash_variant(url)
    if not candidate or candidate == url:
        return resp, _effective_url(resp, url)

    try:
        retry_resp = utils.safe_requests_get(candidate, headers=headers, timeout=timeout, proxies=proxies)
    except Exception:
        return resp, _effective_url(resp, url)

    if _response_looks_feed_like(retry_resp):
        return retry_resp, _effective_url(retry_resp, candidate)
    return resp, _effective_url(resp, url)


def _retry_feed_not_acceptable(resp, url: str, *, headers: dict, timeout, proxies=None):
    try:
        status_code = int(getattr(resp, "status_code", 0) or 0)
    except Exception:
        status_code = 0
    if status_code != 406:
        return resp

    retry_headers = dict(headers or {})
    if (
        str(retry_headers.get("Accept") or "").strip() == "*/*"
        and str(retry_headers.get("User-Agent") or "").strip() == "BlindRSS/1.0"
    ):
        return resp
    retry_headers["Accept"] = "*/*"
    retry_headers["User-Agent"] = "BlindRSS/1.0"

    try:
        retry_resp = utils.safe_requests_get(url, headers=retry_headers, timeout=timeout, proxies=proxies)
    except Exception:
        log.debug("Feed header retry failed for %s", url, exc_info=True)
        return resp

    try:
        retry_status = int(getattr(retry_resp, "status_code", 0) or 0)
    except Exception:
        retry_status = 0
    if retry_status != 406:
        log.info("Retried feed with generic feed-reader headers after HTTP 406: %s", url)
        return retry_resp
    return resp


class LocalProvider(RSSProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        init_db()
        self._discovery_cache: Dict[str, Tuple[Optional[str], float]] = {}
        self._discovery_cache_lock = threading.Lock()
        self._refresh_failure_cooldowns: Dict[str, Tuple[float, Optional[str]]] = {}
        self._refresh_failure_cooldowns_lock = threading.Lock()
        # Last refresh-attempt time per feed (monotonic), used to honor per-feed
        # refresh_interval_seconds overrides on scheduled refreshes. In-memory
        # only: after a restart every feed is due, which matches startup refresh.
        self._scheduled_refresh_last_attempt: Dict[str, float] = {}
        self._scheduled_refresh_last_attempt_lock = threading.Lock()
    def get_name(self) -> str:
        return "Local RSS"

    def _automatic_feed_refresh_workload(self) -> str:
        """Return the selected automatic-refresh caching policy.

        ``ignore_feed_cache`` predates the three-state setting.  Keep it as a
        fallback only when a caller provides an older config dictionary, which
        also preserves integrations that have not yet saved the new setting.
        """
        try:
            workload = str(
                self.config.get("automatic_feed_refresh_workload", "") or ""
            ).strip().lower()
        except Exception:
            workload = ""
        if workload in {"cached", "startup_full", "always_full"}:
            return workload

        try:
            return "always_full" if bool(self.config.get("ignore_feed_cache", False)) else "startup_full"
        except Exception:
            return "startup_full"

    def should_force_startup_refresh(self) -> bool:
        # The default full startup GET prevents stale launches caused by servers
        # that return spurious 304s.  Users who need a lighter, more responsive
        # launch can explicitly use normal conditional refreshes instead.
        return self._automatic_feed_refresh_workload() != "cached"

    def _cache_ignore_enabled(self) -> bool:
        return self._automatic_feed_refresh_workload() == "always_full"

    def _discover_feed_url(self, url: str, timeout_s: Optional[float] = None, use_cache: bool = False) -> Optional[str]:
        key = str(url or "").strip()
        if not key:
            return None

        now = time.monotonic()
        if use_cache:
            with self._discovery_cache_lock:
                cached = self._discovery_cache.get(key)
                if cached is not None:
                    cached_value, expires_at = cached
                    if expires_at > now:
                        return cached_value
                    self._discovery_cache.pop(key, None)

        request_timeout = None
        probe_timeout = None
        if timeout_s is not None:
            try:
                request_timeout = max(1.0, float(timeout_s))
            except Exception:
                request_timeout = None
            if request_timeout is not None:
                probe_timeout = max(1.0, min(request_timeout, 5.0))

        resolved = None
        try:
            resolved = discover_feed(key, request_timeout=request_timeout or 10.0, probe_timeout=probe_timeout or 5.0)
        except Exception:
            resolved = None

        if use_cache:
            ttl = _DISCOVERY_SUCCESS_CACHE_TTL_SECONDS if resolved else _DISCOVERY_FAILURE_CACHE_TTL_SECONDS
            with self._discovery_cache_lock:
                self._discovery_cache[key] = (resolved, now + ttl)

        return resolved

    def _resolve_feed_url(
        self,
        url: str,
        allow_network: bool = True,
        discovery_timeout: Optional[float] = None,
        use_cache: bool = False,
    ) -> str:
        resolved = utils.normalize_user_submitted_url(url)
        if not resolved:
            return resolved

        # Google Groups' retired RSS endpoints are replaced by a synthetic
        # subscription over the current web conversation list.  Accept the
        # group's email address and legacy #!forum link as well as /g/name.
        try:
            from core import forum_sources

            google_group = forum_sources.google_group_subscription_url(resolved)
            if google_group:
                return google_group
        except Exception:
            pass

        # Groups.io archive searches have no filtered RSS endpoint.  Preserve
        # them as synthetic local subscriptions; ordinary group pages still
        # normalize to the group's native /rss feed through discovery.
        try:
            from core import groups_io

            if groups_io.is_group_search_url(resolved):
                return resolved
        except Exception:
            pass

        # YouTube search URLs have no native RSS and are enumerated on refresh;
        # keep them verbatim so discovery does not rewrite them to a channel feed.
        try:
            from core.discovery import is_youtube_search_url
            if is_youtube_search_url(resolved):
                return resolved
        except Exception:
            pass

        # SoundCloud/Mixcloud user & playlist pages likewise have no native RSS and
        # are enumerated on refresh; keep them verbatim so discovery doesn't rewrite
        # or reject them.
        try:
            from core import discovery as _dsc
            if _dsc.is_soundcloud_url(resolved) and _dsc.soundcloud_listing_kind(resolved) in ("user", "playlist"):
                return resolved
            if _dsc.is_mixcloud_url(resolved) and _dsc.mixcloud_listing_kind(resolved) in ("user", "playlist"):
                return resolved
        except Exception:
            pass

        if allow_network:
            from core.discovery import get_ytdlp_feed_url

            try:
                resolved = get_ytdlp_feed_url(resolved) or self._discover_feed_url(
                    resolved,
                    timeout_s=discovery_timeout,
                    use_cache=use_cache,
                ) or resolved
            except Exception:
                pass

        try:
            resolved = rumble_mod.normalize_rumble_feed_url(resolved)
        except Exception:
            pass

        try:
            resolved = odysee_mod.normalize_odysee_feed_url(resolved)
        except Exception:
            pass

        return str(resolved or url or "").strip()

    def _get_refresh_failure_cooldown(self, feed_id: str) -> Tuple[Optional[float], Optional[str]]:
        key = str(feed_id or "").strip()
        if not key:
            return None, None

        now = time.monotonic()
        with self._refresh_failure_cooldowns_lock:
            cached = self._refresh_failure_cooldowns.get(key)
            if cached is None:
                return None, None
            expires_at, error_msg = cached
            if expires_at <= now:
                self._refresh_failure_cooldowns.pop(key, None)
                return None, None
            return expires_at, error_msg

    def _set_refresh_failure_cooldown(self, feed_id: str, cooldown_s: float, error_msg: Optional[str] = None) -> None:
        key = str(feed_id or "").strip()
        if not key:
            return
        ttl = max(1.0, float(cooldown_s or 0.0))
        with self._refresh_failure_cooldowns_lock:
            self._refresh_failure_cooldowns[key] = (time.monotonic() + ttl, error_msg)

    def _clear_refresh_failure_cooldown(self, feed_id: str) -> None:
        key = str(feed_id or "").strip()
        if not key:
            return
        with self._refresh_failure_cooldowns_lock:
            self._refresh_failure_cooldowns.pop(key, None)

    def refresh_feed(self, feed_id: str, progress_cb=None) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, url, title, category, etag, last_modified, COALESCE(title_is_custom, 0), upstream_title "
                "FROM feeds WHERE id = ?",
                (feed_id,),
            )
            row = c.fetchone()
        finally:
            conn.close()

        if not row:
            return False

        return self._refresh_feed_rows(
            [row],
            progress_cb=progress_cb,
            force=True,
            respect_failure_cooldown=False,
        )

    def _refresh_feed_rows(
        self,
        feed_rows,
        progress_cb=None,
        force: bool = False,
        respect_failure_cooldown: bool = True,
    ) -> bool:
        if not feed_rows:
            return True

        configured_workers = max(1, int(self.config.get("max_concurrent_refreshes", 6) or 1))
        configured_per_host = max(1, int(self.config.get("per_host_max_connections", 2) or 1))

        cpu_count = max(1, int(os.cpu_count() or 1))
        max_workers, per_host_limit, adaptive_cap = _compute_refresh_limits(
            configured_workers,
            configured_per_host,
            len(feed_rows),
            cpu_count=cpu_count,
        )
        if configured_workers != max_workers:
            log.info(
                "Using %s local refresh worker(s) for %s feed(s); configured max_concurrent_refreshes=%s "
                "(cpu=%s, adaptive_cap=%s)",
                max_workers,
                len(feed_rows),
                configured_workers,
                cpu_count,
                adaptive_cap,
            )
        if configured_per_host != per_host_limit:
            log.info(
                "Using %s per-host local refresh connection(s) for %s feed(s); configured per_host_max_connections=%s "
                "(cpu=%s, adaptive_cap=%s)",
                per_host_limit,
                len(feed_rows),
                configured_per_host,
                cpu_count,
                adaptive_cap,
            )
        feed_timeout = max(1, int(self.config.get("feed_timeout_seconds", 15) or 15))
        retries = max(0, int(self.config.get("feed_retry_attempts", 1) or 0))
        host_limits = defaultdict(lambda: threading.Semaphore(per_host_limit))

        # Cooperative stop (user's "Stop Refresh"): feeds already being fetched
        # finish; queued ones are skipped. The event is per-run so a stop
        # request can never leak into a later refresh.
        cancel_event = self._begin_refresh_cancel_scope()

        def task(feed_row):
            if cancel_event.is_set():
                return None
            return self._refresh_single_feed(
                feed_row,
                host_limits,
                feed_timeout,
                retries,
                progress_cb,
                force,
                respect_failure_cooldown=respect_failure_cooldown,
                cancel_event=cancel_event,
            )

        ordered_feed_rows = _interleave_feed_rows_by_host(feed_rows)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(task, feed_row): feed_row for feed_row in ordered_feed_rows}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        log.error(f"Refresh worker error: {e}")
            if cancel_event.is_set():
                log.info("Local refresh stopped by user; remaining feeds skipped")
        finally:
            self._end_refresh_cancel_scope(cancel_event)
        return True

    def refresh(self, progress_cb=None, force: bool = False, scheduled: bool = False) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            # Fetch etag/last_modified for conditional get plus metadata for UI updates
            c.execute(
                "SELECT id, url, title, category, etag, last_modified, COALESCE(title_is_custom, 0), upstream_title FROM feeds"
            )
            feeds = c.fetchall()
        finally:
            conn.close()

        if scheduled:
            feeds = self._filter_scheduled_due_rows(feeds)
            if not feeds:
                return True

        # When the user opts to ignore feed caching, treat every full refresh as
        # forced so periodic/background refreshes also bypass spurious 304s.
        effective_force = bool(force) or self._cache_ignore_enabled()
        return self._refresh_feed_rows(feeds, progress_cb=progress_cb, force=effective_force)

    def scheduled_refresh_tick(self, global_interval_s: int) -> int:
        # Per-feed overrides can be shorter than the global interval, so the
        # refresh loop must wake often enough to service the fastest feed.
        try:
            global_interval = int(global_interval_s)
        except (TypeError, ValueError):
            global_interval = 300
        try:
            overrides = get_feed_refresh_interval_overrides()
        except Exception:
            overrides = {}
        candidates = [v for v in overrides.values() if v > 0]
        if global_interval > 0:
            candidates.append(global_interval)
        return min(candidates) if candidates else global_interval

    def _filter_scheduled_due_rows(self, feed_rows):
        """Keep only the feeds due for a scheduled (periodic) refresh.

        Each feed's effective interval is its refresh_interval_seconds override
        when set, else the global refresh_interval. An interval of 0 means never
        auto-refresh. A feed not yet attempted this session is always due.
        """
        try:
            overrides = get_feed_refresh_interval_overrides()
        except Exception:
            overrides = {}
        if not overrides:
            return feed_rows
        try:
            global_interval = int(self.config.get("refresh_interval", 300) or 0)
        except (TypeError, ValueError):
            global_interval = 300
        now = time.monotonic()
        with self._scheduled_refresh_last_attempt_lock:
            last_attempts = dict(self._scheduled_refresh_last_attempt)
        due = []
        for row in feed_rows:
            feed_id = str(row[0])
            interval = overrides.get(feed_id, global_interval)
            if interval <= 0:
                continue
            last = last_attempts.get(feed_id)
            # 1s tolerance so a feed whose interval equals the loop tick is not
            # pushed a whole extra tick by scheduling jitter.
            if last is None or (now - last) >= (interval - 1.0):
                due.append(row)
        return due

    def _note_scheduled_refresh_attempt(self, feed_id) -> None:
        key = str(feed_id or "").strip()
        if not key:
            return
        with self._scheduled_refresh_last_attempt_lock:
            self._scheduled_refresh_last_attempt[key] = time.monotonic()

    def refresh_feeds_by_ids(self, feed_ids, progress_cb=None, force: bool = True) -> bool:
        ordered_ids = []
        seen = set()
        for raw_id in list(feed_ids or []):
            fid = str(raw_id or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            ordered_ids.append(fid)

        if not ordered_ids:
            return True

        conn = get_connection()
        try:
            c = conn.cursor()
            placeholders = ",".join(["?"] * len(ordered_ids))
            c.execute(
                "SELECT id, url, title, category, etag, last_modified, COALESCE(title_is_custom, 0), upstream_title "
                f"FROM feeds WHERE id IN ({placeholders})",
                ordered_ids,
            )
            rows = c.fetchall()
        finally:
            conn.close()

        if not rows:
            return False

        rows_by_id = {str(row[0]): row for row in rows}
        ordered_rows = [rows_by_id[fid] for fid in ordered_ids if fid in rows_by_id]
        return self._refresh_feed_rows(ordered_rows, progress_cb=progress_cb, force=force)

    def _refresh_single_feed(
        self,
        feed_row,
        host_limits,
        feed_timeout,
        retries,
        progress_cb,
        force=False,
        respect_failure_cooldown: bool = False,
        cancel_event: Optional[threading.Event] = None,
    ):
        if self._refresh_cancelled(cancel_event):
            return
        # Each thread gets its own connection
        feed_id, feed_url, feed_title, feed_category, etag, last_modified, title_is_custom, upstream_title = feed_row
        status = "ok"
        new_items = 0
        content_changed = False
        feed_metadata_changed = False
        new_article_summaries = []
        error_msg = None
        final_title = feed_title or "Unknown Feed"
        failure_cooldown_seconds = None
        started_at = time.monotonic()
        entry_count = None
        known_unread_count = None

        if respect_failure_cooldown and not force:
            expires_at, cached_error = self._get_refresh_failure_cooldown(feed_id)
            if expires_at is not None:
                status = "cooldown"
                error_msg = cached_error
                log.info(
                    "Local feed refresh skipped id=%s title=%r status=cooldown remaining_s=%.1f error=%r url=%s",
                    feed_id,
                    final_title,
                    max(0.0, float(expires_at - time.monotonic())),
                    error_msg,
                    feed_url,
                )
                state = self._collect_feed_state(
                    feed_id,
                    final_title,
                    feed_category,
                    status,
                    new_items,
                    error_msg,
                    new_article_summaries,
                )
                self._emit_progress(progress_cb, state)
                return

        # Real attempt begins: restart this feed's per-feed refresh-interval
        # clock. Cooldown skips above intentionally don't count as attempts.
        self._note_scheduled_refresh_attempt(feed_id)

        def _preview_for_notification(raw_text):
            return _plain_text_preview(raw_text, limit=180)

        def _record_new_article(article_id, title, author, preview="", url="", media_url="", media_type=""):
            if len(new_article_summaries) >= 500:
                return
            try:
                new_article_summaries.append(
                    {
                        "id": str(article_id or ""),
                        "title": str(title or "New article"),
                        "author": str(author or ""),
                        "preview": str(preview or ""),
                        "url": str(url or ""),
                        "media_url": str(media_url or ""),
                        "media_type": str(media_type or ""),
                    }
                )
            except Exception:
                pass

        def _apply_rules_to_new_article(
            article_id, title, content, description, author, url, tags,
            date, media_url, media_type, chapter_url,
        ):
            """Run the filter-rules pipeline against a just-inserted article.

            Must be called immediately after ``_record_new_article`` so that a
            "delete" or "skip notification" outcome can undo that article's
            notification bookkeeping (it pops the summary it just appended). The
            unread count is recomputed separately, so we only adjust ``new_items``
            (the notification counter), never the row's read state here.
            """
            nonlocal new_items
            if not filter_rules:
                return
            art = {
                "title": title or "",
                "content": content or "",
                "description": description or "",
                "author": author or "",
                "feed": final_title or feed_title or "",
                "url": url or "",
                "tag": tags or "",
                "read": False,
                "favorite": False,
                "opened": False,
                "updated": False,
            }
            try:
                agg = filters_mod.evaluate_pipeline(filter_rules, art)
            except Exception:
                log.debug("Filter pipeline evaluation failed", exc_info=True)
                return
            if not agg.get("matched_rule_ids"):
                return
            eff = filters_mod.resolve_effective_actions(agg, delete_behavior)
            snapshot = {
                "url": url, "title": title, "content": content, "description": description,
                "date": date, "author": author, "media_url": media_url,
                "media_type": media_type, "chapter_url": chapter_url,
                "is_read": 0, "is_favorite": 0,
            }
            try:
                removed = filters_mod.apply_effective_actions(
                    c, article_id, eff, snapshot=snapshot, feed_id=feed_id
                )
            except Exception:
                log.debug("Filter pipeline application failed for %s", article_id, exc_info=True)
                return
            if removed or eff.get("skip_notification"):
                if new_article_summaries and str(new_article_summaries[-1].get("id")) == str(article_id):
                    new_article_summaries.pop()
                new_items = max(0, new_items - 1)
            if removed:
                existing_articles.pop(article_id, None)

        headers = utils.add_revalidation_headers({})
        is_npr_feed = npr_mod.is_npr_url(feed_url)

        # Per-feed HTTP overrides (issue #29): custom request headers, a timeout
        # override, and the browser-impersonation mode. A site-root Referer is added
        # so the request looks like an in-site navigation past anti-bot WAFs.
        try:
            feed_settings = get_feed_settings(feed_id) or {}
        except Exception:
            feed_settings = {}
        feed_impersonate_mode = str(feed_settings.get("impersonate") or "auto").lower()
        if feed_impersonate_mode not in ("auto", "always", "never"):
            feed_impersonate_mode = "auto"
        # Issue #42: public feeds behind broken certificates (self-signed,
        # missing intermediates, expired) should still load. When a fetch fails
        # certificate validation we log a warning and retry once without
        # verification. Set "ignore_feed_ssl_errors": false in config.json to
        # enforce strict validation instead. Feed retrieval only — other
        # network operations keep full verification.
        ignore_feed_ssl_errors = bool(self.config.get("ignore_feed_ssl_errors", True))
        feed_custom_headers = feed_settings.get("custom_headers")
        if not isinstance(feed_custom_headers, dict):
            feed_custom_headers = {}

        def _apply_feed_http_overrides(hdrs: dict, url: str) -> None:
            ref = utils.referer_for_url(url)
            if ref and "Referer" not in hdrs:
                hdrs["Referer"] = ref
            for key, value in feed_custom_headers.items():
                if key:
                    hdrs[str(key)] = str(value)

        _apply_feed_http_overrides(headers, feed_url)

        try:
            per_feed_timeout = feed_settings.get("timeout_seconds")
            if per_feed_timeout is not None:
                feed_timeout = max(1, int(per_feed_timeout))
        except (TypeError, ValueError):
            pass

        # Per-feed proxy (issue #29): the escape hatch for IP-reputation blocks that no
        # header/TLS change can fix. Routed through both the plain and impersonation
        # transports. None means a direct connection (the default).
        feed_proxy = str(feed_settings.get("proxy") or "").strip()
        feed_proxies = {"http": feed_proxy, "https": feed_proxy} if feed_proxy else None

        # Last-resort real-browser retrieval. ConfigManager supplies the default
        # for the real app; the False fallback keeps partial config dictionaries
        # used by embedders/tests from unexpectedly launching a browser.
        browser_feed_fallback_enabled = bool(
            self.config.get("browser_feed_fallback_enabled", False)
        )
        try:
            browser_feed_fallback_timeout = max(
                15.0,
                min(
                    float(self.config.get("browser_feed_fallback_timeout_seconds", 90) or 90),
                    180.0,
                ),
            )
        except (TypeError, ValueError):
            browser_feed_fallback_timeout = 90.0
        browser_feed_fallback_attempted = False

        def _try_browser_feed_fallback(reason: str, *, response=None, error=None):
            nonlocal browser_feed_fallback_attempted
            if (
                not browser_feed_fallback_enabled
                or browser_feed_fallback_attempted
                or self._refresh_cancelled(cancel_event)
            ):
                return None
            # The browser launch is expensive and process-serialized, so only
            # failures that actually look like bot protection may escalate.
            # Dead feeds, 404s, and plain non-feed pages never qualify: with
            # several hundred feeds the unconditional escalation more than
            # doubled total refresh time (issue #79 follow-up).
            if error is not None:
                if not _browser_fallback_error_qualifies(error):
                    return None
            elif response is not None and not _browser_fallback_response_qualifies(response):
                return None
            browser_feed_fallback_attempted = True
            log.info(
                "Local feed refresh escalating to automated browser after %s "
                "id=%s title=%r url=%s",
                reason,
                feed_id,
                final_title,
                feed_url,
            )
            return browser_feed_mod.fetch_feed(
                feed_url,
                timeout_s=browser_feed_fallback_timeout,
                proxy=feed_proxy or None,
                cancel_event=cancel_event,
            )

        # Per-feed encoding override (issue #75): when set, the raw feed bytes
        # are decoded with this codec instead of any automatic detection.
        feed_encoding_override = str(feed_settings.get("encoding") or "").strip()

        # Automatic refreshes can use validators. Manual/targeted refreshes are
        # force=True and should fetch the feed body even when a server's validator
        # metadata is stale or incorrect.
        use_conditional = (not force) and (not is_npr_feed) and bool(etag or last_modified)
        if use_conditional and not _feed_has_stored_articles(feed_id):
            log.info(
                "Skipping conditional headers for local feed with empty article cache id=%s title=%r url=%s",
                feed_id,
                final_title,
                feed_url,
            )
            use_conditional = False
        if use_conditional:
            if etag:
                headers['If-None-Match'] = etag
            if last_modified:
                headers['If-Modified-Since'] = last_modified
        elif not force and is_npr_feed and (etag or last_modified):
            log.debug("Skipping conditional headers for NPR feed %s", feed_url)

        log.info(
            "Local feed refresh start id=%s title=%r force=%s respect_cooldown=%s conditional=%s "
            "has_etag=%s has_last_modified=%s timeout_s=%s retries=%s url=%s",
            feed_id,
            final_title,
            force,
            respect_failure_cooldown,
            use_conditional,
            bool(etag),
            bool(last_modified),
            feed_timeout,
            retries,
            feed_url,
        )

        host = urlparse(feed_url).hostname or feed_url
        limiter = host_limits[host]

        xml_text = None
        new_etag = None
        new_last_modified = None
        canonical_feed_url = None

        try:
            from core import rumble as rumble_mod
            from core import odysee as odysee_mod

            is_odysee_listing = (
                odysee_mod.is_odysee_url(feed_url)
                and not str(feed_url).lower().endswith((".xml", ".rss", ".atom"))
            )
            if is_odysee_listing:
                normalized_feed_url = odysee_mod.normalize_odysee_feed_url(feed_url)
                if normalized_feed_url and normalized_feed_url != feed_url:
                    feed_metadata_changed = True
                    try:
                        connu = get_connection()
                        try:
                            cu = connu.cursor()
                            cu.execute("UPDATE feeds SET url = ? WHERE id = ?", (normalized_feed_url, feed_id))
                            connu.commit()
                            feed_url = normalized_feed_url
                        finally:
                            connu.close()
                    except Exception:
                        feed_url = normalized_feed_url

                existing_count = 0
                try:
                    conn0 = get_connection()
                    try:
                        c0 = conn0.cursor()
                        c0.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (feed_id,))
                        existing_count = int(c0.fetchone()[0] or 0)
                    finally:
                        conn0.close()
                except Exception:
                    existing_count = 0

                try:
                    max_items = int(
                        self.config.get("odysee_max_items_initial", 150)
                        if existing_count == 0
                        else self.config.get("odysee_max_items_refresh", 60)
                    )
                except Exception:
                    max_items = 150 if existing_count == 0 else 60
                max_items = max(1, min(500, max_items))

                page_title = None
                all_items = []

                with limiter:
                    last_exc = None
                    attempts = retries + 1
                    deadline = _per_feed_attempt_deadline(feed_timeout)
                    for attempt in range(1, attempts + 1):
                        try:
                            page_title, all_items = odysee_mod.fetch_listing_items(
                                feed_url,
                                max_items=int(max_items),
                                timeout_s=float(feed_timeout),
                            )
                            break
                        except Exception as e:
                            last_exc = e
                            status = "error"
                            error_msg = str(e)
                            if attempt <= retries and time.monotonic() < deadline:
                                backoff = min(4, attempt)
                                if self._sleep_or_cancel_refresh(backoff, cancel_event):
                                    return
                                continue
                            raise last_exc

                if page_title:
                    final_title = page_title

                conn = get_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                    if not c.fetchone():
                        return
                    title_to_store, custom_to_store = _resolve_feed_title_update(
                        feed_title, title_is_custom, upstream_title, final_title, feed_url
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, title_is_custom = ?, upstream_title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, custom_to_store, str(final_title or "").strip(), None, None, feed_id),
                    )
                    conn.commit()
                    deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                        feed_id,
                        cursor=c,
                    )

                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        if self._refresh_cancelled(cancel_event):
                            return
                        try:
                            article_id = item.id
                            title = item.title or "No Title"
                            url = item.url or ""
                            author = item.author or final_title or "Odysee"
                            raw_date = item.published or ""
                            date = utils.normalize_date(raw_date, title, "", url)
                            if _article_matches_deleted_tombstone(
                                deleted_article_ids,
                                deleted_article_urls,
                                article_id,
                                url=url,
                            ):
                                continue

                            c.execute("SELECT date FROM articles WHERE id = ?", (article_id,))
                            row = c.fetchone()
                            if row:
                                existing_date = row[0] or ""
                                if existing_date != date:
                                    c.execute("UPDATE articles SET date = ? WHERE id = ?", (date, article_id))
                                    if i % 5 == 0 or i == total_entries - 1:
                                        conn.commit()
                                continue

                            c.execute(
                                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                                (article_id, feed_id, title, url, "", date, author, None, None),
                            )
                            new_items += 1
                            _record_new_article(article_id, title, author, url=url)

                            if i % 5 == 0 or i == total_entries - 1:
                                conn.commit()
                        except sqlite3.IntegrityError as e:
                            if _rollback_and_abort_on_foreign_key(conn, e):
                                return
                            log.debug(f"Odysee entry parse/insert failed for {feed_url}: {e}")
                            continue
                        except Exception as e:
                            log.debug(f"Odysee entry parse/insert failed for {feed_url}: {e}")
                            continue
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

                return

            # SoundCloud and Mixcloud user/playlist feeds have no native RSS; we
            # enumerate their latest items (SoundCloud via yt-dlp, Mixcloud via its
            # public API) and store them as yt-dlp-playable articles, mirroring the
            # Odysee/YouTube-search listing paths above.
            sc_mc_kind = ""
            sc_mc_source = ""
            try:
                from core import discovery as _disc2
                if _disc2.is_soundcloud_url(feed_url):
                    k = _disc2.soundcloud_listing_kind(feed_url)
                    if k in ("user", "playlist"):
                        sc_mc_kind, sc_mc_source = k, "soundcloud"
                elif _disc2.is_mixcloud_url(feed_url):
                    k = _disc2.mixcloud_listing_kind(feed_url)
                    if k in ("user", "playlist"):
                        sc_mc_kind, sc_mc_source = k, "mixcloud"
            except Exception:
                sc_mc_kind, sc_mc_source = "", ""

            if sc_mc_source:
                existing_count = 0
                try:
                    conn0 = get_connection()
                    try:
                        c0 = conn0.cursor()
                        c0.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (feed_id,))
                        existing_count = int(c0.fetchone()[0] or 0)
                    finally:
                        conn0.close()
                except Exception:
                    existing_count = 0

                try:
                    max_items = int(
                        self.config.get("audio_listing_max_items_initial", 80)
                        if existing_count == 0
                        else self.config.get("audio_listing_max_items_refresh", 40)
                    )
                except Exception:
                    max_items = 80 if existing_count == 0 else 40
                max_items = max(1, min(300, max_items))

                page_title = None
                all_items = []
                with limiter:
                    last_exc = None
                    attempts = retries + 1
                    deadline = _per_feed_attempt_deadline(max(15, feed_timeout))
                    for attempt in range(1, attempts + 1):
                        try:
                            if sc_mc_source == "soundcloud":
                                page_title, all_items = _disc2.fetch_soundcloud_listing(
                                    feed_url, max_items=int(max_items), timeout=float(max(20, feed_timeout))
                                )
                            else:
                                page_title, all_items = _disc2.fetch_mixcloud_listing(
                                    feed_url, max_items=int(max_items), timeout=float(max(15, feed_timeout))
                                )
                            break
                        except Exception as e:
                            last_exc = e
                            status = "error"
                            error_msg = str(e)
                            if attempt <= retries and time.monotonic() < deadline:
                                if self._sleep_or_cancel_refresh(min(4, attempt), cancel_event):
                                    return
                                continue
                            raise last_exc

                if page_title:
                    final_title = page_title

                conn = get_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                    if not c.fetchone():
                        return
                    title_to_store, custom_to_store = _resolve_feed_title_update(
                        feed_title, title_is_custom, upstream_title, final_title, feed_url
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, title_is_custom = ?, upstream_title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, custom_to_store, str(final_title or "").strip(), None, None, feed_id),
                    )
                    conn.commit()
                    deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                        feed_id,
                        cursor=c,
                    )

                    default_author = final_title or sc_mc_source.capitalize()
                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        if self._refresh_cancelled(cancel_event):
                            return
                        try:
                            url = item.url or ""
                            if not url:
                                continue
                            title = item.title or "No Title"
                            article_id = str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    f"blindrss:{sc_mc_source}-listing:{feed_id}:{url}",
                                )
                            )
                            author = item.author or default_author
                            date = utils.normalize_date(item.published or "", title, "", url)
                            if _article_matches_deleted_tombstone(
                                deleted_article_ids,
                                deleted_article_urls,
                                article_id,
                                url=url,
                            ):
                                continue

                            c.execute(
                                "SELECT id, date FROM articles WHERE feed_id = ? AND (id = ? OR url = ?) LIMIT 1",
                                (feed_id, article_id, url),
                            )
                            row = c.fetchone()
                            if row:
                                existing_id, existing_date = row
                                if (existing_date or "") != date:
                                    c.execute("UPDATE articles SET title = ?, date = ?, author = ? WHERE id = ?",
                                              (title, date, author, existing_id))
                                    if i % 5 == 0 or i == total_entries - 1:
                                        conn.commit()
                                continue

                            c.execute(
                                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                                (article_id, feed_id, title, url, "", date, author, None, None),
                            )
                            new_items += 1
                            _record_new_article(article_id, title, author, url=url)

                            if i % 5 == 0 or i == total_entries - 1:
                                conn.commit()
                        except sqlite3.IntegrityError as e:
                            if _rollback_and_abort_on_foreign_key(conn, e):
                                return
                            log.debug(f"{sc_mc_source} listing insert failed for {feed_url}: {e}")
                            continue
                        except Exception as e:
                            log.debug(f"{sc_mc_source} listing insert failed for {feed_url}: {e}")
                            continue
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

                return

            try:
                from core import forum_sources as _forum_sources
                is_google_group = _forum_sources.is_google_group_url(feed_url)
            except Exception:
                is_google_group = False

            if is_google_group:
                try:
                    max_items = int(self.config.get("google_groups_max_items", 30))
                except Exception:
                    max_items = 30
                max_items = max(1, min(100, max_items))
                page_title = ""
                all_items = []
                with limiter:
                    last_exc = None
                    attempts = retries + 1
                    deadline = _per_feed_attempt_deadline(max(10, feed_timeout))
                    for attempt in range(1, attempts + 1):
                        try:
                            page_title, all_items = _forum_sources.fetch_google_group_items(
                                feed_url,
                                max_items=max_items,
                                timeout=float(max(10, feed_timeout)),
                            )
                            break
                        except Exception as e:
                            last_exc = e
                            status = "error"
                            error_msg = str(e)
                            if attempt <= retries and time.monotonic() < deadline:
                                if self._sleep_or_cancel_refresh(min(4, attempt), cancel_event):
                                    return
                                continue
                            raise last_exc

                if page_title:
                    final_title = page_title
                conn = get_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                    if not c.fetchone():
                        return
                    title_to_store, custom_to_store = _resolve_feed_title_update(
                        feed_title, title_is_custom, upstream_title, final_title, feed_url
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, title_is_custom = ?, upstream_title = ?, "
                        "etag = ?, last_modified = ? WHERE id = ?",
                        (
                            title_to_store,
                            custom_to_store,
                            str(final_title or "").strip(),
                            None,
                            None,
                            feed_id,
                        ),
                    )
                    conn.commit()
                    deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                        feed_id, cursor=c,
                    )
                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        if self._refresh_cancelled(cancel_event):
                            return
                        try:
                            legacy_article_id = str(item.id or item.url)
                            title = item.title or "No Title"
                            article_url = item.url or ""
                            article_id = str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    f"blindrss:google-groups:{feed_id}:"
                                    f"{article_url or legacy_article_id}",
                                )
                            )
                            author = item.author or final_title or "Google Groups"
                            date = utils.normalize_date(
                                item.published or "", title, item.content or "", article_url
                            )
                            if _article_matches_deleted_tombstone(
                                deleted_article_ids,
                                deleted_article_urls,
                                article_id,
                                legacy_article_id,
                                url=article_url,
                            ):
                                continue
                            c.execute(
                                "SELECT id, date FROM articles WHERE feed_id = ? "
                                "AND (id = ? OR id = ? OR url = ?) LIMIT 1",
                                (feed_id, article_id, legacy_article_id, article_url),
                            )
                            row = c.fetchone()
                            if row:
                                existing_id, existing_date = row
                                c.execute(
                                    "UPDATE articles SET title = ?, url = ?, content = ?, "
                                    "date = ?, author = ? WHERE id = ?",
                                    (
                                        title,
                                        article_url,
                                        item.content or "",
                                        date,
                                        author,
                                        existing_id,
                                    ),
                                )
                                if existing_date != date or i % 5 == 0 or i == total_entries - 1:
                                    conn.commit()
                                continue
                            c.execute(
                                "INSERT INTO articles "
                                "(id, feed_id, title, url, content, date, author, is_read) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                                (
                                    article_id,
                                    feed_id,
                                    title,
                                    article_url,
                                    item.content or "",
                                    date,
                                    author,
                                ),
                            )
                            new_items += 1
                            _record_new_article(article_id, title, author, url=article_url)
                            if i % 5 == 0 or i == total_entries - 1:
                                conn.commit()
                        except sqlite3.IntegrityError as e:
                            if _rollback_and_abort_on_foreign_key(conn, e):
                                return
                            log.debug("Google Groups entry insert failed for %s: %s", feed_url, e)
                        except Exception as e:
                            log.debug("Google Groups entry insert failed for %s: %s", feed_url, e)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                return

            try:
                from core import groups_io as _groups_io
                is_groups_io_search = _groups_io.is_group_search_url(feed_url)
            except Exception:
                is_groups_io_search = False

            if is_groups_io_search:
                try:
                    max_items = int(self.config.get("groups_io_search_max_items", 100))
                except Exception:
                    max_items = 100
                max_items = max(1, min(1000, max_items))
                page_title = ""
                all_items = []
                with limiter:
                    last_exc = None
                    attempts = retries + 1
                    deadline = _per_feed_attempt_deadline(max(10, feed_timeout))
                    for attempt in range(1, attempts + 1):
                        try:
                            page_title, all_items = _groups_io.fetch_search_items(
                                feed_url,
                                max_items=max_items,
                                timeout=float(max(10, feed_timeout)),
                            )
                            break
                        except Exception as e:
                            last_exc = e
                            status = "error"
                            error_msg = str(e)
                            if attempt <= retries and time.monotonic() < deadline:
                                if self._sleep_or_cancel_refresh(min(4, attempt), cancel_event):
                                    return
                                continue
                            raise last_exc

                if page_title:
                    final_title = page_title
                conn = get_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                    if not c.fetchone():
                        return
                    title_to_store, custom_to_store = _resolve_feed_title_update(
                        feed_title, title_is_custom, upstream_title, final_title, feed_url
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, title_is_custom = ?, upstream_title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, custom_to_store, str(final_title or "").strip(), None, None, feed_id),
                    )
                    conn.commit()
                    deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                        feed_id, cursor=c,
                    )
                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        if self._refresh_cancelled(cancel_event):
                            return
                        try:
                            legacy_article_id = str(item.id or item.url)
                            title = item.title or "No Title"
                            url = item.url or ""
                            article_id = str(uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"blindrss:groups-io-search:{feed_id}:{url or legacy_article_id}",
                            ))
                            author = item.author or final_title or "Groups.io"
                            date = utils.normalize_date(item.published or "", title, item.content or "", url)
                            if _article_matches_deleted_tombstone(
                                deleted_article_ids, deleted_article_urls,
                                article_id, legacy_article_id, url=url,
                            ):
                                continue
                            c.execute(
                                "SELECT id, date FROM articles WHERE feed_id = ? "
                                "AND (id = ? OR id = ? OR url = ?) LIMIT 1",
                                (feed_id, article_id, legacy_article_id, url),
                            )
                            row = c.fetchone()
                            if row:
                                existing_id, existing_date = row
                                c.execute(
                                    "UPDATE articles SET title = ?, url = ?, content = ?, date = ?, author = ? WHERE id = ?",
                                    (title, url, item.content or "", date, author, existing_id),
                                )
                                if existing_date != date or i % 5 == 0 or i == total_entries - 1:
                                    conn.commit()
                                continue
                            c.execute(
                                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                                (article_id, feed_id, title, url, item.content or "", date, author),
                            )
                            new_items += 1
                            _record_new_article(article_id, title, author, url=url)
                            if i % 5 == 0 or i == total_entries - 1:
                                conn.commit()
                        except sqlite3.IntegrityError as e:
                            if _rollback_and_abort_on_foreign_key(conn, e):
                                return
                            log.debug("Groups.io search entry insert failed for %s: %s", feed_url, e)
                        except Exception as e:
                            log.debug("Groups.io search entry insert failed for %s: %s", feed_url, e)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                return

            try:
                from core import discovery as _disc
                is_youtube_search = _disc.is_youtube_search_url(feed_url)
            except Exception:
                is_youtube_search = False

            if is_youtube_search:
                # YouTube search results have no native RSS; enumerate recent videos
                # via yt-dlp (date-sorted) and store them as video/youtube articles so
                # the existing yt-dlp playback path handles them.
                from core import discovery as _disc
                query = _disc.youtube_search_query(feed_url) or ""
                try:
                    max_items = int(self.config.get("youtube_search_max_items", 30))
                except Exception:
                    max_items = 30
                max_items = max(1, min(100, max_items))

                page_title = None
                all_items = []
                with limiter:
                    last_exc = None
                    attempts = retries + 1
                    deadline = _per_feed_attempt_deadline(max(10, feed_timeout))
                    for attempt in range(1, attempts + 1):
                        try:
                            page_title, all_items = _disc.fetch_youtube_search_items(
                                query,
                                max_items=max_items,
                                timeout_s=float(max(10, feed_timeout)),
                                cookiefile=(str(self.config.get("ytdlp_cookies_file", "") or "").strip() or None),
                            )
                            break
                        except Exception as e:
                            last_exc = e
                            status = "error"
                            error_msg = str(e)
                            if attempt <= retries and time.monotonic() < deadline:
                                if self._sleep_or_cancel_refresh(min(4, attempt), cancel_event):
                                    return
                                continue
                            raise last_exc

                if page_title:
                    final_title = page_title

                conn = get_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                    if not c.fetchone():
                        return
                    title_to_store, custom_to_store = _resolve_feed_title_update(
                        feed_title, title_is_custom, upstream_title, final_title, feed_url
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, title_is_custom = ?, upstream_title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, custom_to_store, str(final_title or "").strip(), None, None, feed_id),
                    )
                    conn.commit()
                    deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                        feed_id,
                        cursor=c,
                    )

                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        if self._refresh_cancelled(cancel_event):
                            return
                        try:
                            legacy_article_id = item.id
                            title = item.title or "No Title"
                            url = item.url or ""
                            article_id = str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    f"blindrss:youtube-search:{feed_id}:{url or legacy_article_id}",
                                )
                            )
                            author = item.author or final_title or "YouTube"
                            raw_date = item.published or ""
                            date = utils.normalize_date(raw_date, title, "", url)
                            if _article_matches_deleted_tombstone(
                                deleted_article_ids,
                                deleted_article_urls,
                                article_id,
                                legacy_article_id,
                                url=url,
                            ):
                                continue

                            c.execute(
                                "SELECT id, date FROM articles "
                                "WHERE feed_id = ? AND (id = ? OR id = ? OR url = ?) LIMIT 1",
                                (feed_id, article_id, legacy_article_id, url),
                            )
                            row = c.fetchone()
                            if row:
                                existing_id, existing_date = row
                                c.execute(
                                    "UPDATE articles SET title = ?, url = ?, date = ?, author = ?, "
                                    "media_url = ?, media_type = ? WHERE id = ?",
                                    (title, url, date, author, url, "video/youtube", existing_id),
                                )
                                if existing_date != date or i % 5 == 0 or i == total_entries - 1:
                                    conn.commit()
                                continue

                            c.execute(
                                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                                (article_id, feed_id, title, url, "", date, author, url, "video/youtube"),
                            )
                            new_items += 1
                            _record_new_article(
                                article_id, title, author, url=url, media_url=url, media_type="video/youtube"
                            )

                            if i % 5 == 0 or i == total_entries - 1:
                                conn.commit()
                        except sqlite3.IntegrityError as e:
                            if _rollback_and_abort_on_foreign_key(conn, e):
                                return
                            log.debug(f"YouTube search entry insert failed for {feed_url}: {e}")
                            continue
                        except Exception as e:
                            log.debug(f"YouTube search entry insert failed for {feed_url}: {e}")
                            continue
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

                return

            is_rumble_listing = (
                rumble_mod.is_rumble_url(feed_url)
                and not str(feed_url).lower().endswith((".xml", ".rss", ".atom"))
            )

            if is_rumble_listing:
                # Rumble listing pages (channels/playlists/subscriptions) are HTML, not RSS.
                # Fetch via curl and scrape the video list into synthetic entries.
                normalized_feed_url = rumble_mod.normalize_rumble_feed_url(feed_url)
                if normalized_feed_url and normalized_feed_url != feed_url:
                    feed_metadata_changed = True
                    try:
                        connu = get_connection()
                        try:
                            cu = connu.cursor()
                            cu.execute("UPDATE feeds SET url = ? WHERE id = ?", (normalized_feed_url, feed_id))
                            connu.commit()
                            feed_url = normalized_feed_url
                        finally:
                            connu.close()
                    except Exception:
                        feed_url = normalized_feed_url

                existing_count = 0
                try:
                    conn0 = get_connection()
                    try:
                        c0 = conn0.cursor()
                        c0.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (feed_id,))
                        existing_count = int(c0.fetchone()[0] or 0)
                    finally:
                        conn0.close()
                except Exception:
                    existing_count = 0

                try:
                    max_pages = int(self.config.get("rumble_max_pages_initial", 3) if existing_count == 0 else self.config.get("rumble_max_pages_refresh", 1))
                except Exception:
                    max_pages = 3 if existing_count == 0 else 1
                max_pages = max(1, min(10, max_pages))

                from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qs

                def _with_page(u: str, page: int) -> str:
                    try:
                        parts = urlsplit(u)
                        qs = parse_qs(parts.query)
                        qs["page"] = [str(int(page))]
                        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(qs, doseq=True), ""))
                    except Exception:
                        return u

                page_title = None
                all_items = []

                with limiter:
                    last_exc = None
                    attempts = retries + 1
                    deadline = _per_feed_attempt_deadline(feed_timeout)
                    for attempt in range(1, attempts + 1):
                        try:
                            all_items.clear()
                            page_title = None
                            for page in range(1, max_pages + 1):
                                if page > 1 and time.monotonic() >= deadline:
                                    break
                                page_url = feed_url if page == 1 else _with_page(feed_url, page)
                                t, items = rumble_mod.fetch_listing_items(page_url, timeout_s=float(feed_timeout))
                                if t and not page_title:
                                    page_title = t
                                if not items:
                                    break
                                all_items.extend(items)
                            break
                        except Exception as e:
                            last_exc = e
                            status = "error"
                            error_msg = str(e)
                            if attempt <= retries and time.monotonic() < deadline:
                                backoff = min(4, attempt)
                                if self._sleep_or_cancel_refresh(backoff, cancel_event):
                                    return
                                continue
                            raise last_exc

                if page_title:
                    final_title = page_title

                conn = get_connection()
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                    if not c.fetchone():
                        return
                    # Clear conditional-cache metadata (HTML listing refresh does not use ETag/Last-Modified)
                    title_to_store, custom_to_store = _resolve_feed_title_update(
                        feed_title, title_is_custom, upstream_title, final_title, feed_url
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, title_is_custom = ?, upstream_title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, custom_to_store, str(final_title or "").strip(), None, None, feed_id),
                    )
                    conn.commit()
                    deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                        feed_id,
                        cursor=c,
                    )

                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        if self._refresh_cancelled(cancel_event):
                            return
                        try:
                            article_id = item.id
                            title = item.title or "No Title"
                            url = item.url or ""
                            author = item.author or final_title or "Rumble"
                            raw_date = item.published or ""
                            date = utils.normalize_date(raw_date, title, "", url)
                            if _article_matches_deleted_tombstone(
                                deleted_article_ids,
                                deleted_article_urls,
                                article_id,
                                url=url,
                            ):
                                continue

                            c.execute("SELECT date FROM articles WHERE id = ?", (article_id,))
                            row = c.fetchone()
                            if row:
                                existing_date = row[0] or ""
                                if existing_date != date:
                                    c.execute("UPDATE articles SET date = ? WHERE id = ?", (date, article_id))
                                    if i % 5 == 0 or i == total_entries - 1:
                                        conn.commit()
                                continue

                            c.execute(
                                "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                                (article_id, feed_id, title, url, "", date, author, None, None),
                            )
                            new_items += 1
                            _record_new_article(article_id, title, author, url=url)

                            if i % 5 == 0 or i == total_entries - 1:
                                conn.commit()
                        except sqlite3.IntegrityError as e:
                            if _rollback_and_abort_on_foreign_key(conn, e):
                                return
                            log.debug(f"Rumble entry parse/insert failed for {feed_url}: {e}")
                            continue
                        except Exception as e:
                            log.debug(f"Rumble entry parse/insert failed for {feed_url}: {e}")
                            continue
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

                return

            should_attempt_initial_resolution = False
            direct_fetch_timeout = feed_timeout
            direct_fetch_retries = retries
            direct_feed_probe_only = False
            if not _url_looks_feed_like(feed_url):
                try:
                    conn0 = get_connection()
                    try:
                        c0 = conn0.cursor()
                        c0.execute("SELECT 1 FROM articles WHERE feed_id = ? LIMIT 1", (feed_id,))
                        should_attempt_initial_resolution = c0.fetchone() is None
                    finally:
                        conn0.close()
                except Exception:
                    should_attempt_initial_resolution = False

            if should_attempt_initial_resolution:
                log.info(
                    "Local feed refresh attempting startup URL discovery id=%s title=%r url=%s",
                    feed_id,
                    final_title,
                    feed_url,
                )
                resolved_feed_url = self._resolve_feed_url(
                    feed_url,
                    discovery_timeout=_FAST_REFRESH_DISCOVERY_TIMEOUT_SECONDS,
                    use_cache=True,
                )
                if resolved_feed_url and resolved_feed_url != feed_url:
                    log.info("Resolved local feed URL during refresh: %s -> %s", feed_url, resolved_feed_url)
                    feed_metadata_changed = True
                    try:
                        connu = get_connection()
                        try:
                            cu = connu.cursor()
                            cu.execute(
                                "UPDATE feeds SET url = ?, etag = NULL, last_modified = NULL WHERE id = ?",
                                (resolved_feed_url, feed_id),
                            )
                            connu.commit()
                        finally:
                            connu.close()
                    except Exception:
                        log.debug("Failed to persist resolved feed URL %s for %s", resolved_feed_url, feed_id, exc_info=True)
                    feed_url = resolved_feed_url
                    etag = None
                    last_modified = None
                    headers = utils.add_revalidation_headers({})
                    _apply_feed_http_overrides(headers, feed_url)
                    host = urlparse(feed_url).hostname or feed_url
                    limiter = host_limits[host]
                else:
                    direct_feed_probe_only = True
                    direct_fetch_timeout = min(float(feed_timeout), _FAST_REFRESH_DIRECT_PROBE_TIMEOUT_SECONDS)
                    direct_fetch_retries = 0
                    log.info(
                        "Local feed refresh discovery did not find a feed id=%s; probing original URL timeout_s=%s url=%s",
                        feed_id,
                        direct_fetch_timeout,
                        feed_url,
                    )

            with limiter:
                last_exc = None
                configured_retries = max(0, int(direct_fetch_retries or 0))
                attempts = configured_retries + 1
                if configured_retries == 0:
                    # Windows localhost test servers and real network edges can
                    # reset a fresh connection before a response exists. Give
                    # transport failures cheap retries without changing the
                    # configured retry behavior for HTTP status errors.
                    attempts += 9
                # Browser-TLS impersonation policy (issue #29): "always"/"never" honor
                # the per-feed setting. "auto" gives plain requests their full retry
                # budget first (so transient resets still recover), then makes ONE extra
                # last-resort attempt with browser impersonation if a WAF reset the
                # connection. do_impersonation_next flips on for that reserved attempt.
                impersonation_fallback = feed_impersonate_mode == "auto" and utils.CURL_CFFI_AVAILABLE
                attempts_total = attempts + (1 if impersonation_fallback else 0)
                do_impersonation_next = False
                # Bound one feed's total retry time (issue: 2-minute refreshes) --
                # without this, a server that times out on every attempt could occupy
                # a refresh worker for attempts_total * feed_timeout seconds back to
                # back, since each retry still pays the full timeout again.
                attempt_deadline = _per_feed_attempt_deadline(direct_fetch_timeout)
                for attempt in range(1, attempts_total + 1):
                    if feed_impersonate_mode == "never":
                        impersonate_now = False
                    elif feed_impersonate_mode == "always":
                        impersonate_now = True
                    else:
                        impersonate_now = do_impersonation_next
                    try:
                        try:
                            resp = utils.safe_requests_get(
                                feed_url,
                                headers=headers,
                                timeout=direct_fetch_timeout,
                                impersonate=impersonate_now,
                                proxies=feed_proxies,
                            )
                        except Exception as fetch_exc:
                            if not (ignore_feed_ssl_errors and _looks_like_ssl_certificate_error(fetch_exc)):
                                raise
                            log.warning(
                                "SSL certificate problem for feed id=%s url=%s (%s); "
                                "retrying without certificate verification (issue #42)",
                                feed_id,
                                feed_url,
                                fetch_exc,
                            )
                            resp = utils.safe_requests_get(
                                feed_url,
                                headers=headers,
                                timeout=direct_fetch_timeout,
                                impersonate=impersonate_now,
                                proxies=feed_proxies,
                                verify=False,
                            )
                        resp = _retry_feed_not_acceptable(
                            resp,
                            feed_url,
                            headers=headers,
                            timeout=direct_fetch_timeout,
                            proxies=feed_proxies,
                        )
                        resp, effective_feed_url = _retry_cloudflare_challenged_wordpress_feed(
                            resp,
                            feed_url,
                            headers=headers,
                            timeout=direct_fetch_timeout,
                            proxies=feed_proxies,
                        )
                        # A challenge/interstitial block (not just a reset) also escalates
                        # the reserved attempt to browser impersonation (issue #29). For
                        # discovery probes a 200 HTML page just means "not a feed", so those
                        # keep the fast fail -- but a non-200 block (403/429 WAF wall, e.g.
                        # Akamai's Access Denied) still escalates even on a probe.
                        if (
                            impersonation_fallback
                            and not (
                                direct_feed_probe_only
                                and int(getattr(resp, "status_code", 0) or 0) == 200
                            )
                            and not do_impersonation_next
                            and not impersonate_now
                            and attempt < attempts_total
                            and _response_looks_blocked(resp)
                            and time.monotonic() < attempt_deadline
                        ):
                            do_impersonation_next = True
                            log.info(
                                "Local feed refresh escalating to browser impersonation after block "
                                "id=%s title=%r attempt=%s/%s status=%s url=%s",
                                feed_id,
                                final_title,
                                attempt,
                                attempts_total,
                                getattr(resp, "status_code", None),
                                feed_url,
                            )
                            if self._sleep_or_cancel_refresh(0.01, cancel_event):
                                return
                            continue
                        if effective_feed_url != feed_url:
                            log.info("Resolved challenged local feed URL during refresh: %s -> %s", feed_url, effective_feed_url)
                            feed_metadata_changed = True
                            feed_url = effective_feed_url
                            canonical_feed_url = effective_feed_url
                        if resp.status_code == 304:
                            status = "not_modified"
                            error_msg = None
                            failure_cooldown_seconds = None
                            new_etag = etag
                            new_last_modified = last_modified
                            log.info(
                                "Local feed refresh HTTP 304 id=%s title=%r conditional=%s url=%s",
                                feed_id,
                                final_title,
                                use_conditional,
                                feed_url,
                            )
                            break
                        resp.raise_for_status()
                        if direct_feed_probe_only and not _response_looks_feed_like(resp):
                            browser_resp = _try_browser_feed_fallback(
                                "non-feed discovery response", response=resp
                            )
                            if browser_resp is None:
                                status = "error"
                                error_msg = f"Feed discovery failed for {feed_url}"
                                failure_cooldown_seconds = _PERMANENT_FAILURE_COOLDOWN_SECONDS
                                xml_data = None
                                log.info(
                                    "Local feed refresh probe rejected non-feed response id=%s title=%r status=%s url=%s",
                                    feed_id,
                                    final_title,
                                    getattr(resp, "status_code", None),
                                    feed_url,
                                )
                                break
                            resp = browser_resp
                            direct_feed_probe_only = False
                            if str(getattr(resp, "url", "") or "") != feed_url:
                                canonical_feed_url = str(resp.url)
                                feed_metadata_changed = True
                        # Use content instead of text to let feedparser handle encoding detection
                        xml_data = resp.content
                        if feed_encoding_override:
                            # Issue #75: the user pinned this feed's encoding. Decode
                            # here and hand feedparser text so it cannot re-guess.
                            xml_text = text_encoding.decode_bytes(
                                resp.content,
                                override=feed_encoding_override,
                                content_type=str(resp.headers.get("Content-Type", "") or ""),
                                kind="xml",
                            )
                            xml_data = xml_text
                        else:
                            xml_text = resp.text
                        status = "ok"
                        error_msg = None
                        failure_cooldown_seconds = None
                        new_etag = resp.headers.get('ETag')
                        new_last_modified = resp.headers.get('Last-Modified')
                        log.info(
                            "Local feed refresh HTTP %s id=%s title=%r bytes=%s final_url=%s",
                            getattr(resp, "status_code", None),
                            feed_id,
                            final_title,
                            len(xml_data or b""),
                            getattr(resp, "url", feed_url),
                        )
                        break
                    except Exception as e:
                        last_exc = e
                        status = "error"
                        error_msg = _format_refresh_error(e)
                        failure_cooldown_seconds = _failure_cooldown_seconds_for_error(e)
                        retry_allowed = attempt <= configured_retries
                        fast_transport_retry = False
                        if (
                            not retry_allowed
                            and configured_retries == 0
                            and attempt < attempts
                            and _http_status_from_error(e) is None
                            and time.monotonic() < attempt_deadline
                            # Only true fast-failing resets qualify as "cheap" retries.
                            # A Timeout/ReadTimeout already burned the full timeout
                            # budget, so retrying it "cheaply" (0.01s backoff) just
                            # repeats that full wait again, up to 9 extra times --
                            # the actual cause of multi-minute refreshes when a feed
                            # is simply unresponsive and feed_retry_attempts=0.
                            and isinstance(
                                e,
                                (
                                    requests.exceptions.ConnectionError,
                                    requests.exceptions.ChunkedEncodingError,
                                ),
                            )
                        ):
                            retry_allowed = True
                            fast_transport_retry = True
                        if retry_allowed and _should_retry_refresh_error(e) and time.monotonic() < attempt_deadline:
                            backoff = 0.01 if fast_transport_retry else _retry_backoff_seconds(attempt, e)
                            log.info(
                                "Local feed refresh retrying id=%s title=%r attempt=%s/%s backoff_s=%.2f error=%r url=%s",
                                feed_id,
                                final_title,
                                attempt,
                                attempts_total,
                                backoff,
                                error_msg,
                                feed_url,
                            )
                            if self._sleep_or_cancel_refresh(backoff, cancel_event):
                                return
                            continue
                        # Plain retries are exhausted. If a WAF-style reset closed the
                        # connection, spend the one reserved last-resort attempt on a
                        # real browser TLS/HTTP fingerprint via curl_cffi (issue #29).
                        if (
                            impersonation_fallback
                            and not do_impersonation_next
                            and not impersonate_now
                            and attempt < attempts_total
                            and _should_escalate_to_impersonation(e)
                            and time.monotonic() < attempt_deadline
                        ):
                            do_impersonation_next = True
                            log.info(
                                "Local feed refresh escalating to browser impersonation after reset "
                                "id=%s title=%r attempt=%s/%s url=%s",
                                feed_id,
                                final_title,
                                attempt,
                                attempts_total,
                                feed_url,
                            )
                            if self._sleep_or_cancel_refresh(0.01, cancel_event):
                                return
                            continue
                        browser_resp = _try_browser_feed_fallback(
                            error_msg or "HTTP failure", error=e
                        )
                        if browser_resp is not None:
                            resp = browser_resp
                            xml_data = resp.content
                            xml_text = resp.text
                            status = "ok"
                            error_msg = None
                            failure_cooldown_seconds = None
                            new_etag = None
                            new_last_modified = None
                            if str(getattr(resp, "url", "") or "") != feed_url:
                                canonical_feed_url = str(resp.url)
                                feed_metadata_changed = True
                            break
                        raise last_exc

            if status == "not_modified":
                # A conditional request can still have followed a permanent
                # redirect. Persist that canonical address even though there
                # is no document body to parse or otherwise the next refresh
                # repeats the redirect and the cached feed model stays stale.
                if canonical_feed_url:
                    try:
                        conn = get_connection()
                        try:
                            conn.execute(
                                "UPDATE feeds SET url = ? WHERE id = ?",
                                (canonical_feed_url, feed_id),
                            )
                            conn.commit()
                        finally:
                            conn.close()
                    except Exception:
                        log.debug(
                            "Failed to persist canonical 304 feed URL %s for %s",
                            canonical_feed_url,
                            feed_id,
                            exc_info=True,
                        )
                return
            if xml_data is None:
                return

            response_content_type = ""
            try:
                response_content_type = resp.headers.get("Content-Type", "")
            except Exception:
                response_content_type = ""
            try:
                d = _parse_feed_document(xml_data, xml_text, response_content_type)
            except Exception:
                browser_resp = _try_browser_feed_fallback("feed parse failure", response=resp)
                if browser_resp is None:
                    raise
                resp = browser_resp
                xml_data = resp.content
                xml_text = resp.text
                response_content_type = str(resp.headers.get("Content-Type", "") or "")
                d = _parse_feed_document(xml_data, xml_text, response_content_type)
            entry_count = len(d.entries)
            log.info(
                "Local feed parsed id=%s title=%r entries=%s bozo=%s url=%s",
                feed_id,
                d.feed.get('title', final_title),
                entry_count,
                bool(getattr(d, "bozo", False)),
                feed_url,
            )
            parsed_document_invalid = entry_count == 0 and (
                bool(getattr(d, "bozo", False)) or not _response_looks_feed_like(resp)
            )
            if parsed_document_invalid:
                browser_resp = _try_browser_feed_fallback(
                    "invalid or non-feed parsed response", response=resp
                )
                if browser_resp is not None:
                    resp = browser_resp
                    xml_data = resp.content
                    xml_text = resp.text
                    response_content_type = str(resp.headers.get("Content-Type", "") or "")
                    d = _parse_feed_document(xml_data, xml_text, response_content_type)
                    entry_count = len(d.entries)
                parsed_document_invalid = entry_count == 0 and (
                    bool(getattr(d, "bozo", False)) or not _response_looks_feed_like(resp)
                )
                if parsed_document_invalid:
                    status = "error"
                    error_msg = f"Response from {feed_url} did not look like a feed"
                    failure_cooldown_seconds = _PERMANENT_FAILURE_COOLDOWN_SECONDS
                    log.info(
                        "Local feed refresh rejected non-feed zero-entry response id=%s title=%r content_type=%r url=%s",
                        feed_id,
                        final_title,
                        response_content_type,
                        feed_url,
                    )
                    return
            
            # Parse only feeds that contain a local-name "chapters" element. Element
            # matching deliberately ignores namespace prefixes and namespace URIs.
            chapter_metadata = _parse_feed_chapter_metadata(xml_text)
            description_metadata = _parse_feed_description_metadata(xml_text)

            conn = get_connection()
            try:
                c = conn.cursor()
                c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                if not c.fetchone():
                    return
                
                final_title = d.feed.get('title', final_title)
                title_to_store, custom_to_store = _resolve_feed_title_update(
                    feed_title, title_is_custom, upstream_title, final_title, feed_url
                )
                upstream_to_store = str(final_title or "").strip()
                # The channel's declared content language (RSS <language> /
                # Atom xml:lang), normalized to BCP-47. None when the feed does
                # not say -- stored as NULL so the rich reader can tell "not
                # declared" from a real value (issue #72).
                language_to_store = article_lang.normalize_lang(d.feed.get('language'))
                # The feeds UPDATE is deferred to the write phase below: it is
                # the statement that opens the write transaction, and SQLite has
                # a single writer, so nothing may be written until all per-entry
                # parsing/network work is done.


                # Pre-compute the current document's identities before asking SQLite about
                # existing rows.  Do not hydrate a feed's entire retained history here: only
                # these entries can be updated/inserted by this refresh.
                candidate_base_ids = []
                candidate_base_id_set = set()
                for entry in d.entries:
                    if self._refresh_cancelled(cancel_event):
                        return
                    content = _entry_content(entry)
                    base_id = _entry_base_id(entry, feed_id, feed_url, content)
                    if base_id and base_id not in candidate_base_id_set:
                        candidate_base_id_set.add(base_id)
                        candidate_base_ids.append(base_id)
                existing_articles = _load_current_feed_articles_for_entries(
                    c,
                    feed_id,
                    candidate_base_ids,
                )
                deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                    feed_id,
                    cursor=c,
                )

                # Categorization pipeline (see core.filters): load the enabled
                # rules and this feed's effective delete behavior once, then apply
                # them to each newly inserted article below.
                try:
                    filter_rules = list_filter_rules(enabled_only=True, cursor=c)
                except Exception:
                    filter_rules = []
                delete_behavior = self._resolve_delete_behavior(feed_id) if filter_rules else "deleted"

                entry_ids = []
                for base_id in candidate_base_ids:
                    scoped_id = f"{feed_id}:{base_id}"
                    if base_id in existing_articles or scoped_id in existing_articles:
                        continue
                    entry_ids.append(base_id)
                conflicting_ids = set()
                if entry_ids:
                    chunk_size = 900
                    for i in range(0, len(entry_ids), chunk_size):
                        chunk = entry_ids[i:i + chunk_size]
                        placeholders = ",".join(["?"] * len(chunk))
                        c.execute(
                            f"SELECT id, feed_id FROM articles WHERE id IN ({placeholders})",
                            chunk,
                        )
                        for row in c.fetchall():
                            if row[1] != feed_id:
                                conflicting_ids.add(row[0])
                
                total_entries = len(d.entries)

                # Shared extension filters for enclosure/media tags
                image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
                audio_exts = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac")

                # Phase 1: prepare every entry BEFORE any row is written, so the
                # write transaction below never spans per-entry parsing or the
                # NPR media-page fetch (a network call). SQLite has a single
                # writer; holding the write lock across that work starved every
                # concurrent writer (delete/restore, full-text metadata
                # enrichment) for the duration of a feed's save.
                prepared_entries = []
                for entry in d.entries:
                    if self._refresh_cancelled(cancel_event):
                        return

                    content = _entry_content(entry)
                    description = _entry_description(entry)
                    tags = _entry_tags(entry)
                    base_id = _entry_base_id(entry, feed_id, feed_url, content)
                    if not base_id:
                        continue
                    for key in (entry.get('guid'), entry.get('id'), _entry_primary_link(entry), base_id):
                        if key and key in description_metadata:
                            description = description_metadata[key]
                            break
                    scoped_id = f"{feed_id}:{base_id}"
                    article_id = base_id

                    url = _feed_urljoin(feed_url, _entry_primary_link(entry))
                    title = utils.enhance_activity_entry_title(entry.get('title', ''), url, content)
                    if not title or title.strip() == "No Title":
                         # Fallback: create title from content snippet (e.g. Bluesky/Mastodon)
                         snippet = content or ""
                         snippet = _plain_text_preview(snippet, limit=83)
                         title = snippet or "No Title"
                    author = _entry_author(entry) or 'Unknown'
                    
                    # BlueSky/Microblog fallback: if author is unknown, try to use feed title
                    if author == 'Unknown' and final_title:
                         if final_title.startswith('@'):
                             # Extract handle from "@handle - Name" format common in BlueSky RSS
                             parts = final_title.split(' ', 1)
                             if parts:
                                 author = parts[0]
                         else:
                             author = final_title

                    raw_date = _entry_raw_date(entry)
                    
                    date = utils.normalize_date(
                        str(raw_date) if raw_date else "", 
                        title, 
                        content or (entry.get('summary') or ''),
                        url
                    )

                    if base_id in conflicting_ids:
                        article_id = scoped_id

                    if _article_matches_deleted_tombstone(
                        deleted_article_ids,
                        deleted_article_urls,
                        base_id,
                        scoped_id,
                        article_id,
                        url=url,
                    ):
                        continue

                    existing_article_id = None
                    existing_metadata = existing_articles.get(base_id)
                    if existing_metadata is not None:
                        existing_article_id = base_id
                    else:
                        existing_metadata = existing_articles.get(scoped_id)
                        if existing_metadata is not None:
                            existing_article_id = scoped_id

                    media_url = None
                    media_type = None
                    
                    # 1. Prioritize YouTube video ID if present (ensures we get the video, not thumbnail)
                    if 'yt_videoid' in entry:
                        media_url = url
                        media_type = "video/youtube"
                    # 2. Check enclosures, but filter out common image types (thumbnails)
                    elif 'enclosures' in entry and len(entry.enclosures) > 0:
                        valid_enclosure = None
                        for enc in entry.enclosures:
                            enc_href = _feed_urljoin(feed_url, getattr(enc, "href", None))
                            enc_type = getattr(enc, "type", "") or ""
                            if enc_href:
                                # Skip if it looks like an image and isn't explicitly audio/video type
                                enc_path = _url_path_lower(enc_href)
                                if any(enc_path.endswith(ext) for ext in image_exts):
                                    if not (enc_type.startswith("audio/") or enc_type.startswith("video/")):
                                        continue
                                valid_enclosure = enc
                                break
                        
                        if valid_enclosure:
                            enc_type = getattr(valid_enclosure, "type", "") or ""
                            enc_href = _feed_urljoin(feed_url, getattr(valid_enclosure, "href", None))
                            enc_type_norm = utils.canonical_media_type(enc_type) or enc_type
                            if utils.media_type_is_audio_video_or_podcast(enc_type_norm):
                                media_url = enc_href
                                media_type = enc_type_norm
                            else:
                                inferred_type = _media_type_from_url(enc_href)
                                if inferred_type:
                                    media_url = enc_href
                                    media_type = inferred_type

                    # 3. Check media:content (common in RSS 2.0 / MRSS)
                    if not media_url and 'media_content' in entry:
                        for mc in entry.media_content:
                            mc_url = _feed_urljoin(feed_url, mc.get('url'))
                            mc_type = mc.get('type')
                            mc_type_norm = utils.canonical_media_type(mc_type) or mc_type
                            if mc_url:
                                # Skip thumbnails or images
                                if mc_type_norm and str(mc_type_norm).startswith('image/'):
                                    continue
                                mc_path = _url_path_lower(mc_url)
                                if any(mc_path.endswith(ext) for ext in image_exts):
                                    continue
                                
                                # Accept if audio/video or looks like audio
                                inferred_type = _media_type_from_url(mc_url)
                                if utils.media_type_is_audio_video_or_podcast(mc_type_norm):
                                    media_url = mc_url
                                    media_type = mc_type_norm
                                    break
                                if inferred_type:
                                    media_url = mc_url
                                    media_type = inferred_type
                                    break

                    # 4. Check NPR-specific extraction if still no media. Do not
                    # retain an existing URL merely because the article already
                    # had media: removed enclosures must clear stale media. NPR is
                    # the explicit exception, and only after extraction confirms
                    # a currently working media URL.
                    if not media_url and npr_mod.is_npr_url(url):
                        media_url, media_type = npr_mod.extract_npr_audio(url, timeout_s=feed_timeout)

                    # Sky marks podcast entries with an image enclosure and a
                    # Podfollow link in the summary. Resolve that series feed
                    # and attach the episode whose title exactly matches this
                    # article; ordinary Sky news items pay no extra requests.
                    sky_hint = "\n".join(
                        str(value or "")
                        for value in (entry.get("summary"), content)
                        if value
                    )
                    if (
                        not media_url
                        and sky_mod.is_sky_news_url(url)
                        and "podfollow.com/" in sky_hint.lower()
                    ):
                        media_url, media_type = sky_mod.extract_podcast_audio(
                            url,
                            title=title,
                            html_hint=sky_hint,
                            timeout=feed_timeout,
                        )

                    chapter_url = None
                    inline_chapters = []
                    if 'podcast_chapters' in entry:
                        chapters_tag = entry.podcast_chapters
                        chapter_url = _feed_urljoin(
                            feed_url,
                            getattr(chapters_tag, 'href', None)
                            or getattr(chapters_tag, 'url', None)
                            or getattr(chapters_tag, 'value', None),
                        )
                    if not chapter_url and 'psc_chapters' in entry:
                        chapters_tag = entry.psc_chapters
                        chapter_url = _feed_urljoin(
                            feed_url,
                            getattr(chapters_tag, 'href', None)
                            or getattr(chapters_tag, 'url', None)
                            or getattr(chapters_tag, 'value', None),
                        )

                    for key in (entry.get('guid'), entry.get('id'), _entry_primary_link(entry), base_id):
                        if not key or key not in chapter_metadata:
                            continue
                        raw_metadata = chapter_metadata[key]
                        if not chapter_url:
                            chapter_url = _feed_urljoin(feed_url, raw_metadata.get("chapter_url"))
                        inline_chapters = raw_metadata.get("chapters") or []
                        break

                    prepared_entries.append({
                        "base_id": base_id,
                        "scoped_id": scoped_id,
                        "article_id": article_id,
                        "title": title,
                        "url": url,
                        "content": content,
                        "description": description,
                        "date": date,
                        "author": author,
                        "tags": tags,
                        "media_url": media_url,
                        "media_type": media_type,
                        "chapter_url": chapter_url,
                        "inline_chapters": inline_chapters,
                        "existing_article_id": existing_article_id,
                        "existing_stored_url": str((existing_metadata or {}).get("url") or ""),
                        "existing_stored_description": str((existing_metadata or {}).get("description") or ""),
                        "notify_preview": _preview_for_notification(content),
                    })

                # Phase 2: all row changes in one short write transaction. The
                # feeds UPDATE is the first write statement, so this is where
                # the write lock is taken — after all parsing and network work.
                # COALESCE on language: a conditional GET or a transiently
                # language-less parse must not erase a language the feed
                # declared earlier -- keep the last one we actually saw.
                if canonical_feed_url:
                    c.execute(
                        "UPDATE feeds SET url = ?, title = ?, title_is_custom = ?, upstream_title = ?, "
                        "language = COALESCE(?, language), etag = ?, last_modified = ? WHERE id = ?",
                        (canonical_feed_url, title_to_store, custom_to_store, upstream_to_store,
                         language_to_store, new_etag, new_last_modified, feed_id),
                    )
                else:
                    c.execute(
                        "UPDATE feeds SET title = ?, title_is_custom = ?, upstream_title = ?, "
                        "language = COALESCE(?, language), etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, custom_to_store, upstream_to_store,
                         language_to_store, new_etag, new_last_modified, feed_id))

                # Re-read tombstones now that the write lock is held: a delete
                # committed while phase 1 was busy (e.g. fetching NPR pages)
                # must not be resurrected by an insert prepared from the stale
                # pre-phase-1 snapshot.
                deleted_article_ids, deleted_article_urls = deleted_article_tombstones_for_feed(
                    feed_id,
                    cursor=c,
                )

                for prep in prepared_entries:
                    if self._refresh_cancelled(cancel_event):
                        return
                    base_id = prep["base_id"]
                    scoped_id = prep["scoped_id"]
                    article_id = prep["article_id"]
                    title = prep["title"]
                    url = prep["url"]
                    content = prep["content"]
                    description = prep["description"]
                    date = prep["date"]
                    author = prep["author"]
                    tags = prep["tags"]
                    media_url = prep["media_url"]
                    media_type = prep["media_type"]
                    chapter_url = prep["chapter_url"]
                    inline_chapters = prep["inline_chapters"]
                    existing_article_id = prep["existing_article_id"]
                    notify_preview = prep["notify_preview"]

                    if _article_matches_deleted_tombstone(
                        deleted_article_ids,
                        deleted_article_urls,
                        base_id,
                        scoped_id,
                        article_id,
                        url=url,
                    ):
                        continue

                    if existing_article_id is not None:
                        # Self-heal stored webpage URLs: adopt the feed's current
                        # link, and clear stale values that were really the media
                        # enclosure (older builds stored the mp3 as the article
                        # URL). Never wipe a good URL just because the feed
                        # temporarily omits its link.
                        stored_url = prep["existing_stored_url"]
                        stored_description = prep["existing_stored_description"]
                        url_to_store = stored_url
                        if url and url != stored_url:
                            url_to_store = url
                        elif not url and stored_url and (
                            stored_url == (media_url or "") or _media_type_from_url(stored_url)
                        ):
                            url_to_store = ""
                        existing_metadata = existing_articles.get(existing_article_id) or {}
                        metadata_changed = (
                            date != str(existing_metadata.get("date") or "")
                            or description != stored_description
                            or media_url != existing_metadata.get("media_url")
                            or media_type != existing_metadata.get("media_type")
                            or chapter_url != existing_metadata.get("chapter_url")
                            or url_to_store != stored_url
                        )
                        if metadata_changed:
                            c.execute(
                                "UPDATE articles SET date = ?, description = ?, media_url = ?, media_type = ?, chapter_url = ?, url = ? "
                                "WHERE id = ?",
                                (date, description, media_url, media_type, chapter_url, url_to_store, existing_article_id),
                            )
                            content_changed = True
                        # Change history: append a version when the feed's content
                        # for this item differs from the latest recorded version.
                        try:
                            if record_article_version(existing_article_id, title, content, cursor=c):
                                content_changed = True
                        except Exception:
                            pass
                        if inline_chapters:
                            utils._replace_stored_chapters(
                                existing_article_id,
                                inline_chapters,
                                cursor=c,
                            )
                        existing_articles[existing_article_id] = {
                            "date": date,
                            "chapter_url": chapter_url,
                            "media_url": media_url,
                            "media_type": media_type,
                            "url": url_to_store,
                            "description": description,
                        }
                        continue

                    try:
                        c.execute(
                            "INSERT INTO articles (id, feed_id, title, url, content, description, date, author, is_read, media_url, media_type, chapter_url, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                            (article_id, feed_id, title, url, content, description, date, author, media_url, media_type, chapter_url, tags or None),
                        )
                        content_changed = True
                        new_items += 1
                        # Change history: seed the original version at first fetch.
                        try:
                            record_article_version(article_id, title, content, cursor=c)
                        except Exception:
                            pass
                        _record_new_article(
                            article_id,
                            title,
                            author,
                            notify_preview,
                            url=url,
                            media_url=media_url,
                            media_type=media_type,
                        )
                        if inline_chapters:
                            utils._replace_stored_chapters(article_id, inline_chapters, cursor=c)
                        existing_articles[article_id] = {
                            "date": date,
                            "chapter_url": chapter_url,
                            "media_url": media_url,
                            "media_type": media_type,
                            "url": url,
                            "description": description,
                        }
                        _apply_rules_to_new_article(
                            article_id, title, content, description, author, url, tags,
                            date, media_url, media_type, chapter_url,
                        )
                    except sqlite3.IntegrityError as e:
                        if _rollback_and_abort_on_foreign_key(conn, e):
                            status = "deleted"
                            error_msg = None
                            return
                        if article_id == base_id:
                            try:
                                c.execute("SELECT feed_id, date, url FROM articles WHERE id = ? LIMIT 1", (base_id,))
                                row = c.fetchone()
                            except sqlite3.Error:
                                row = None

                            if row:
                                existing_feed_id = row[0]
                                if existing_feed_id == feed_id:
                                    # Same stale-URL healing as the main update path above.
                                    stored_url = str(row[2] or "")
                                    url_to_store = stored_url
                                    if url and url != stored_url:
                                        url_to_store = url
                                    elif not url and stored_url and (
                                        stored_url == (media_url or "") or _media_type_from_url(stored_url)
                                    ):
                                        url_to_store = ""
                                    c.execute(
                                        "UPDATE articles SET date = ?, media_url = ?, media_type = ?, "
                                        "chapter_url = ?, description = ?, url = ? WHERE id = ?",
                                        (date, media_url, media_type, chapter_url, description, url_to_store, base_id),
                                    )
                                    content_changed = True
                                    if inline_chapters:
                                        utils._replace_stored_chapters(
                                            base_id,
                                            inline_chapters,
                                            cursor=c,
                                        )
                                    continue

                                try:
                                    c.execute(
                                        "INSERT INTO articles (id, feed_id, title, url, content, description, date, author, is_read, media_url, media_type, chapter_url, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                                        (scoped_id, feed_id, title, url, content, description, date, author, media_url, media_type, chapter_url, tags or None),
                                    )
                                    content_changed = True
                                    article_id = scoped_id
                                    new_items += 1
                                    _record_new_article(
                                        article_id,
                                        title,
                                        author,
                                        notify_preview,
                                        url=url,
                                        media_url=media_url,
                                        media_type=media_type,
                                    )
                                    if inline_chapters:
                                        utils._replace_stored_chapters(article_id, inline_chapters, cursor=c)
                                    existing_articles[article_id] = {
                                        "date": date,
                                        "chapter_url": chapter_url,
                                        "media_url": media_url,
                                        "media_type": media_type,
                                        "url": url,
                                        "description": description,
                                    }
                                    _apply_rules_to_new_article(
                                        article_id, title, content, description, author, url, tags,
                                        date, media_url, media_type, chapter_url,
                                    )
                                except sqlite3.IntegrityError:
                                    continue
                            else:
                                raise
                        else:
                            continue

                # Commit once at the end
                conn.commit()
                # Reuse this already-open worker connection for the progress
                # count.  Opening a fresh SQLite connection (and its PRAGMAs)
                # for every successfully refreshed feed was needless churn.
                try:
                    c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ? AND is_read = 0", (feed_id,))
                    known_unread_count = c.fetchone()[0] or 0
                except Exception:
                    # The write has already committed.  Keep a transient count
                    # failure from turning a successful feed refresh into an
                    # error; _collect_feed_state will fall back to its safe
                    # standalone lookup below.
                    known_unread_count = None
                    log.debug("Could not reuse worker unread count for %s", feed_id, exc_info=True)
                final_title = title_to_store
            finally:
                conn.close()
        except Exception as e:
            if not error_msg:
                error_msg = str(e)
            status = "error"
            if failure_cooldown_seconds is None:
                failure_cooldown_seconds = _TRANSIENT_FAILURE_COOLDOWN_SECONDS
            log.error(f"Error processing feed {feed_url}: {e}")
        finally:
            if status in ("ok", "not_modified", "deleted"):
                self._clear_refresh_failure_cooldown(feed_id)
                # Persist the success so the feed drops out of the "Feeds with
                # Errors" view across restarts (issue #32).
                try:
                    clear_feed_error(feed_id)
                except Exception:
                    log.debug("Failed to clear persisted feed error for %s", feed_id, exc_info=True)
            elif status == "error":
                self._set_refresh_failure_cooldown(
                    feed_id,
                    failure_cooldown_seconds or _TRANSIENT_FAILURE_COOLDOWN_SECONDS,
                    error_msg,
                )
                # Persist the failure (message, time, consecutive count) for the
                # "Feeds with Errors" view (issue #32).
                try:
                    record_feed_error(feed_id, error_msg)
                except Exception:
                    log.debug("Failed to record persisted feed error for %s", feed_id, exc_info=True)
            state = self._collect_feed_state(
                feed_id,
                final_title,
                feed_category,
                status,
                new_items,
                error_msg,
                new_article_summaries,
                content_changed=content_changed,
                feed_metadata_changed=feed_metadata_changed,
                known_unread_count=known_unread_count,
            )
            log.info(
                "Local feed refresh finished id=%s title=%r status=%s force=%s conditional=%s "
                "entries=%s new_items=%s unread=%s duration_s=%.2f error=%r url=%s",
                feed_id,
                state.get("title", final_title),
                status,
                force,
                use_conditional,
                entry_count,
                new_items,
                state.get("unread_count"),
                time.monotonic() - started_at,
                error_msg,
                feed_url,
            )
            self._emit_progress(progress_cb, state)

    def _resolve_delete_behavior(self, feed_id):
        """Per-feed delete-behavior override, else the global setting, else soft
        delete. Drives what a filter-rule "delete" action does for this feed."""
        try:
            override = get_feed_delete_behavior(feed_id)
            if override:
                return override
        except Exception:
            pass
        try:
            return str(self.config.get("delete_behavior", "deleted") or "deleted")
        except Exception:
            return "deleted"

    def _collect_feed_state(
        self,
        feed_id,
        title,
        category,
        status,
        new_items,
        error_msg,
        new_articles=None,
        content_changed: bool = False,
        feed_metadata_changed: bool = False,
        known_unread_count: Optional[int] = None,
    ):
        unread = 0
        conn = None
        if known_unread_count is not None:
            try:
                unread = max(0, int(known_unread_count))
            except (TypeError, ValueError):
                unread = 0
        else:
            try:
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT title, category FROM feeds WHERE id = ?", (feed_id,))
                row = c.fetchone()
                if row:
                    title = row[0] or title
                    category = row[1] or category
                c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ? AND is_read = 0", (feed_id,))
                unread = c.fetchone()[0] or 0
            except Exception as e:
                log.debug(f"Feed state fetch failed for {feed_id}: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
        return {
            "id": feed_id,
            "title": title,
            "category": category or UNCATEGORIZED,
            "unread_count": unread,
            "status": status,
            "new_items": new_items,
            "new_articles": list(new_articles or []),
            "content_changed": bool(content_changed),
            "feed_metadata_changed": bool(feed_metadata_changed),
            "error": error_msg,
        }

    def _emit_progress(self, progress_cb, state):
        if progress_cb is None:
            return
        try:
            progress_cb(state)
        except Exception as e:
            log.debug(f"Progress callback failed: {e}")

    def get_feed_read_counts(self):
        """Read-article count per feed id, for the tree's Read filter (issue #36)."""
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT feed_id, COUNT(*) FROM articles WHERE is_read = 1 GROUP BY feed_id"
            )
            return {row[0]: row[1] for row in c.fetchall()}
        finally:
            conn.close()

    def get_feeds(self) -> List[Feed]:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT id, title, url, category, icon_url, language FROM feeds")
            rows = c.fetchall()

            c.execute("SELECT feed_id, COUNT(*) FROM articles WHERE is_read = 0 GROUP BY feed_id")
            unread_map = {row[0]: row[1] for row in c.fetchall()}

            feeds = []
            for row in rows:
                f = Feed(id=row[0], title=row[1], url=row[2], category=row[3], icon_url=row[4], language=row[5])
                f.unread_count = unread_map.get(f.id, 0)
                feeds.append(f)
            return feeds
        finally:
            conn.close()

    def get_feed_errors(self) -> List[Dict[str, Any]]:
        """Feeds whose most recent update attempt failed (issue #32).

        Backed by the persisted per-feed error columns, so the list survives
        restarts. See core.db.get_feed_errors for the entry shape.
        """
        return get_feed_errors()

    def _parse_article_view_filters(self, feed_id: str) -> Tuple[str, Optional[int], Optional[int]]:
        filter_read = None  # None=all, 0=unread, 1=read
        filter_favorite = None  # None=all, 1=favorites only
        real_feed_id = feed_id or ""

        # Allow stacking prefixes in any order, e.g. "favorites:unread:all".
        while True:
            if real_feed_id.startswith("favorites:"):
                filter_favorite = 1
                real_feed_id = real_feed_id[10:]
            elif real_feed_id.startswith("fav:"):
                filter_favorite = 1
                real_feed_id = real_feed_id[4:]
            elif real_feed_id.startswith("unread:"):
                filter_read = 0
                real_feed_id = real_feed_id[7:]
            elif real_feed_id.startswith("read:"):
                filter_read = 1
                real_feed_id = real_feed_id[5:]
            else:
                break

        return real_feed_id, filter_read, filter_favorite

    @staticmethod
    def _category_membership_clause(cat_names, *, aliased):
        """SQL clause + params selecting articles that belong to a category view.

        An article belongs to a category when: its feed is in the category AND it
        has not been moved elsewhere (``category_override IS NULL``); OR it was
        MOVED here (``category_override`` in the set); OR it is LABELED with the
        category (article_labels). ``aliased`` picks the ``a.``/``f.`` form used
        by the JOINed listing queries vs. the bare-column form for
        ``UPDATE articles``. See core.filters for how those columns get set.
        """
        prefix = "a." if aliased else ""
        ph = ",".join("?" for _ in cat_names)
        if aliased:
            feed_cat = f"f.category IN ({ph})"
        else:
            feed_cat = f"feed_id IN (SELECT id FROM feeds WHERE category IN ({ph}))"
        clause = (
            f"(({prefix}category_override IS NULL AND {feed_cat}) "
            f"OR {prefix}category_override IN ({ph}) "
            f"OR {prefix}id IN (SELECT article_id FROM article_labels WHERE category IN ({ph})))"
        )
        return clause, list(cat_names) * 3

    @staticmethod
    def _is_deleted_view_id(feed_id) -> bool:
        """True for the special 'Deleted Articles' view id(s)."""
        fid = str(feed_id or "")
        return fid == "deleted:all" or fid.startswith("deleted:")

    def _get_deleted_articles_page(self, offset, limit):
        """Build (articles, total) for the Deleted Articles view from tombstone
        snapshots. Newest deletion first."""
        rows, total = list_deleted_articles(offset=offset, limit=limit)
        articles: List[Article] = []
        for r in rows:
            title = r.get("title") or r.get("url") or "(deleted article)"
            articles.append(Article(
                id=r.get("article_id"),
                feed_id=r.get("feed_id"),
                title=title,
                url=r.get("url"),
                content=r.get("content"),
                description=r.get("description"),
                date=r.get("date"),
                author=r.get("author"),
                is_read=bool(r.get("is_read")),
                is_favorite=bool(r.get("is_favorite")),
                media_url=r.get("media_url"),
                media_type=r.get("media_type"),
            ))
        return articles, total

    @staticmethod
    def _smart_folder_id_from_view(feed_id):
        """Return the folder id for a 'smart:<id>' view, else None."""
        fid = str(feed_id or "")
        if fid.startswith("smart:"):
            return fid[len("smart:"):]
        return None

    def _get_smart_articles_page(self, folder_id, offset, limit):
        """Build (articles, total) for a Smart Folder by compiling its rule to a
        WHERE clause over the local articles table."""
        folder = get_smart_folder(folder_id)
        if not folder:
            return [], 0
        where_sql, where_params = smart_folders_mod.build_where(folder.get("rule") or {})
        base_from = "FROM articles a LEFT JOIN feeds f ON a.feed_id = f.id WHERE " + where_sql

        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) " + base_from, tuple(where_params))
            total = int(c.fetchone()[0] or 0)

            sql = (
                "SELECT a.id, a.feed_id, a.title, a.url, a.content, a.date, a.author, "
                "a.is_read, a.is_favorite, a.media_url, a.media_type, a.description "
                + base_from
                + " ORDER BY a.date DESC, a.id DESC"
            )
            params = list(where_params)
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                params.extend([int(limit), int(max(0, offset))])
            c.execute(sql, tuple(params))
            rows = c.fetchall()

            article_ids = [r[0] for r in rows]
            chapters_map = {}
            if article_ids:
                chunk_size = 900
                for i in range(0, len(article_ids), chunk_size):
                    chunk = article_ids[i:i + chunk_size]
                    ph = ",".join("?" for _ in chunk)
                    c.execute(
                        f"SELECT article_id, start, title, href FROM chapters WHERE article_id IN ({ph}) ORDER BY article_id, start",
                        chunk,
                    )
                    for ch in c.fetchall():
                        chapters_map.setdefault(ch[0], []).append({"start": ch[1], "title": ch[2], "href": ch[3]})

            articles: List[Article] = []
            for r in rows:
                articles.append(Article(
                    id=r[0], feed_id=r[1], title=r[2], url=r[3], content=r[4], date=r[5], author=r[6],
                    is_read=bool(r[7]), is_favorite=bool(r[8]), media_url=r[9], media_type=r[10],
                    chapters=chapters_map.get(r[0], []), description=r[11],
                ))
            return articles, total
        finally:
            conn.close()

    def get_articles(self, feed_id: str) -> List[Article]:
        if self._is_deleted_view_id(feed_id):
            page, _total = self._get_deleted_articles_page(0, None)
            return page
        smart_id = self._smart_folder_id_from_view(feed_id)
        if smart_id is not None:
            page, _total = self._get_smart_articles_page(smart_id, 0, None)
            return page

        conn = get_connection()
        try:
            c = conn.cursor()

            # Determine filters
            real_feed_id, filter_read, filter_favorite = self._parse_article_view_filters(feed_id)

            sql_parts = [
                "SELECT id, feed_id, title, url, content, date, author, is_read, "
                "is_favorite, media_url, media_type, description FROM articles"
            ]
            where_clauses = []
            params = []
            
            # For category queries we alias articles as 'a' (because of JOIN). 
            # For simple queries we don't alias or can assume table is articles.
            # To be consistent, let's handle the join case specifically.
            
            is_category = real_feed_id.startswith("category:")
            if is_category:
                cat_name = real_feed_id.split(":", 1)[1]
                from core.db import get_subcategory_titles
                sub_cats = get_subcategory_titles(cat_name)
                cat_names = [cat_name] + sub_cats
                sql_parts = ["""
                    SELECT a.id, a.feed_id, a.title, a.url, a.content, a.date, a.author, a.is_read, a.is_favorite, a.media_url, a.media_type, a.description
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                """]
                clause, cat_params = self._category_membership_clause(cat_names, aliased=True)
                where_clauses.append(clause)
                params.extend(cat_params)
            elif real_feed_id != "all":
                where_clauses.append("feed_id = ?")
                params.append(real_feed_id)

            if filter_read is not None:
                # If we are in category mode, we use 'a.is_read', otherwise just 'is_read'
                col = "a.is_read" if is_category else "is_read"
                where_clauses.append(f"{col} = ?")
                params.append(filter_read)

            if filter_favorite is not None:
                col = "a.is_favorite" if is_category else "is_favorite"
                where_clauses.append(f"{col} = ?")
                params.append(filter_favorite)

            if where_clauses:
                sql_parts.append("WHERE " + " AND ".join(where_clauses))
            
            sort_col = "a.date" if is_category else "date"
            sort_id = "a.id" if is_category else "id"
            sql_parts.append(f"ORDER BY {sort_col} DESC, {sort_id} DESC")
            
            c.execute(" ".join(sql_parts), tuple(params))
                
            rows = c.fetchall()
            
            # Batch fetch chapters for these articles
            article_ids = [r[0] for r in rows]
            chapters_map = {}
            
            if article_ids:
                # SQLite limits variables, simple chunking
                chunk_size = 900
                for i in range(0, len(article_ids), chunk_size):
                    chunk = article_ids[i:i+chunk_size]
                    placeholders = ','.join(['?'] * len(chunk))
                    c.execute(f"SELECT article_id, start, title, href FROM chapters WHERE article_id IN ({placeholders})", chunk)
                    for ch_row in c.fetchall():
                        aid = ch_row[0]
                        if aid not in chapters_map: chapters_map[aid] = []
                        chapters_map[aid].append({"start": ch_row[1], "title": ch_row[2], "href": ch_row[3]})

            articles = []
            for row in rows:
                chs = chapters_map.get(row[0], [])
                chs.sort(key=lambda x: x["start"])
                
                articles.append(Article(
                    id=row[0], feed_id=row[1], title=row[2], url=row[3], content=row[4], date=row[5], author=row[6], is_read=bool(row[7]),
                    is_favorite=bool(row[8]), media_url=row[9], media_type=row[10], chapters=chs, description=row[11]
                ))
            return articles
        finally:
            conn.close()


    def get_articles_page(self, feed_id: str, offset: int = 0, limit: int = 200):
        """Fetch a single page of articles from the local SQLite DB (fast-first loading)."""
        if self._is_deleted_view_id(feed_id):
            return self._get_deleted_articles_page(int(max(0, offset)), int(limit))
        smart_id = self._smart_folder_id_from_view(feed_id)
        if smart_id is not None:
            return self._get_smart_articles_page(smart_id, int(max(0, offset)), int(limit))

        offset = int(max(0, offset))
        limit = int(limit)

        conn = get_connection()
        try:
            c = conn.cursor()

            # Determine filters
            real_feed_id, filter_read, filter_favorite = self._parse_article_view_filters(feed_id)

            # 1. Calculate Total
            count_sql_parts = []
            count_where = []
            count_params = []
            
            is_category = real_feed_id.startswith("category:")
            cat_names = []

            if is_category:
                cat_name = real_feed_id.split(":", 1)[1]
                # Include subcategories
                from core.db import get_subcategory_titles
                sub_cats = get_subcategory_titles(cat_name)
                cat_names = [cat_name] + sub_cats
                count_sql_parts = ["SELECT COUNT(*) FROM articles a JOIN feeds f ON a.feed_id = f.id"]
                clause, cat_params = self._category_membership_clause(cat_names, aliased=True)
                count_where.append(clause)
                count_params.extend(cat_params)
            elif real_feed_id == "all":
                count_sql_parts = ["SELECT COUNT(*) FROM articles"]
            else:
                count_sql_parts = ["SELECT COUNT(*) FROM articles"]
                count_where.append("feed_id = ?")
                count_params.append(real_feed_id)
            
            if filter_read is not None:
                # If we are in category mode (or generally aliased), check prefix
                # But for simple "SELECT COUNT(*) FROM articles", no alias 'a' is defined unless we added it or joined.
                # 'is_category' uses JOIN so 'a' is defined.
                # 'all' and 'feed_id' do not use JOIN in count query above.
                col = "a.is_read" if is_category else "is_read"
                count_where.append(f"{col} = ?")
                count_params.append(filter_read)

            if filter_favorite is not None:
                col = "a.is_favorite" if is_category else "is_favorite"
                count_where.append(f"{col} = ?")
                count_params.append(filter_favorite)
            
            if count_where:
                count_sql_parts.append("WHERE " + " AND ".join(count_where))
                
            c.execute(" ".join(count_sql_parts), tuple(count_params))
            total = int(c.fetchone()[0] or 0)

            # 2. Fetch Page
            sql_parts = [
                "SELECT id, feed_id, title, url, content, date, author, is_read, "
                "is_favorite, media_url, media_type, description FROM articles"
            ]
            where_clauses = []
            params = []

            if is_category:
                sql_parts = ["""
                    SELECT a.id, a.feed_id, a.title, a.url, a.content, a.date, a.author, a.is_read, a.is_favorite, a.media_url, a.media_type, a.description
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                """]
                clause, cat_params = self._category_membership_clause(cat_names, aliased=True)
                where_clauses.append(clause)
                params.extend(cat_params)
            elif real_feed_id != "all":
                where_clauses.append("feed_id = ?")
                params.append(real_feed_id)

            if filter_read is not None:
                col = "a.is_read" if is_category else "is_read"
                where_clauses.append(f"{col} = ?")
                params.append(filter_read)

            if filter_favorite is not None:
                col = "a.is_favorite" if is_category else "is_favorite"
                where_clauses.append(f"{col} = ?")
                params.append(filter_favorite)
            
            if where_clauses:
                sql_parts.append("WHERE " + " AND ".join(where_clauses))
                
            sort_col = "a.date" if is_category else "date"
            sort_id = "a.id" if is_category else "id"
            sql_parts.append(f"ORDER BY {sort_col} DESC, {sort_id} DESC LIMIT ? OFFSET ?")
            params.append(limit)
            params.append(offset)
            
            c.execute(" ".join(sql_parts), tuple(params))
            rows = c.fetchall()

            # Fetch chapters for just this page
            article_ids = [r[0] for r in rows]
            chapters_map = {}
            if article_ids:
                chunk_size = 900
                for i in range(0, len(article_ids), chunk_size):
                    chunk = article_ids[i:i+chunk_size]
                    placeholders = ",".join(["?" for _ in chunk])
                    c.execute(
                        f"SELECT article_id, start, title, href FROM chapters WHERE article_id IN ({placeholders}) ORDER BY article_id, start",
                        chunk,
                    )
                    for row in c.fetchall():
                        aid = row[0]
                        if aid not in chapters_map:
                            chapters_map[aid] = []
                        chapters_map[aid].append({"start": row[1], "title": row[2], "href": row[3]})

            articles: List[Article] = []
            for r in rows:
                chapters = chapters_map.get(r[0], [])
                articles.append(Article(
                    id=r[0],
                    feed_id=r[1],
                    title=r[2],
                    url=r[3],
                    content=r[4],
                    date=r[5],
                    author=r[6],
                    is_read=bool(r[7]),
                    is_favorite=bool(r[8]),
                    media_url=r[9],
                    media_type=r[10],
                    chapters=chapters,
                    description=r[11],
                ))
            return articles, total
        finally:
            conn.close()

    def get_article_by_id(self, article_id: str) -> Optional[Article]:
        aid = str(article_id or "").strip()
        if not aid:
            return None

        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type, description "
                "FROM articles WHERE id = ? LIMIT 1",
                (aid,),
            )
            row = c.fetchone()
            if not row:
                return None

            c.execute(
                "SELECT start, title, href FROM chapters WHERE article_id = ? ORDER BY start",
                (aid,),
            )
            chapters = [{"start": r[0], "title": r[1], "href": r[2]} for r in c.fetchall()]

            return Article(
                id=row[0],
                feed_id=row[1],
                title=row[2],
                url=row[3],
                content=row[4],
                date=row[5],
                author=row[6],
                is_read=bool(row[7]),
                is_favorite=bool(row[8]),
                media_url=row[9],
                media_type=row[10],
                chapters=chapters,
                description=row[11],
            )
        finally:
            conn.close()

    def mark_read(self, article_id: str) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE articles SET is_read = 1 WHERE id = ?", (article_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def mark_unread(self, article_id: str) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE articles SET is_read = 0 WHERE id = ?", (article_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def mark_all_read(self, feed_id: str) -> bool:
        if not feed_id:
            return False
        try:
            real_feed_id, filter_read, filter_favorite = self._parse_article_view_filters(feed_id)
        except Exception:
            return False

        # Avoid mass-marking favorites or already-read views.
        if filter_favorite is not None or filter_read == 1:
            return False

        conn = get_connection()
        try:
            c = conn.cursor()
            where_clauses = []
            params = []

            if real_feed_id.startswith("category:"):
                cat_name = real_feed_id.split(":", 1)[1]
                from core.db import get_subcategory_titles
                sub_cats = get_subcategory_titles(cat_name)
                all_cats = [cat_name] + sub_cats
                clause, cat_params = self._category_membership_clause(all_cats, aliased=False)
                where_clauses.append(clause)
                params.extend(cat_params)
            elif real_feed_id != "all":
                where_clauses.append("feed_id = ?")
                params.append(real_feed_id)

            if filter_read is not None:
                where_clauses.append("is_read = ?")
                params.append(filter_read)

            where_sql = ""
            if where_clauses:
                where_sql = " WHERE " + " AND ".join(where_clauses)

            c.execute(f"UPDATE articles SET is_read = 1{where_sql}", tuple(params))
            conn.commit()
            return True
        except Exception as e:
            log.error(f"Local mark-all-read error: {e}")
            return False
        finally:
            conn.close()

    def supports_favorites(self) -> bool:
        return True

    def supports_article_delete(self) -> bool:
        return True

    def supports_restore_deleted(self) -> bool:
        return True

    def restore_article(self, article_id: str, feed_id: str | None = None) -> bool:
        """Restore a previously deleted article from its tombstone snapshot."""
        try:
            return restore_deleted_article(article_id, feed_id=feed_id) is not None
        except Exception:
            log.exception("Local restore article error for %s", article_id)
            return False

    def supports_purge_deleted(self) -> bool:
        return True

    def purge_deleted_article(self, article_id: str, feed_id: str | None = None) -> bool:
        """Permanently remove a deleted article's tombstone and snapshot."""
        try:
            return bool(purge_deleted_article(article_id, feed_id=feed_id))
        except Exception:
            log.exception("Local purge deleted article error for %s", article_id)
            return False

    def supports_smart_folders(self) -> bool:
        return True

    def get_smart_folders(self):
        from core.db import list_smart_folders
        return list_smart_folders()

    def create_smart_folder(self, name, rule):
        from core.db import create_smart_folder
        return create_smart_folder(name, rule)

    def update_smart_folder(self, folder_id, name=None, rule=None):
        from core.db import update_smart_folder
        return update_smart_folder(folder_id, name=name, rule=rule)

    def delete_smart_folder(self, folder_id):
        from core.db import delete_smart_folder
        return delete_smart_folder(folder_id)

    # ── Filter Rules (categorization pipeline) ──────────────────────────────
    def supports_filter_rules(self) -> bool:
        return True

    def get_filter_rules(self):
        from core.db import list_filter_rules
        return list_filter_rules()

    def get_filter_rule(self, rule_id):
        from core.db import get_filter_rule
        return get_filter_rule(rule_id)

    def create_filter_rule(self, name, rule, actions, enabled=True, stop=False):
        from core.db import create_filter_rule
        return create_filter_rule(name, rule, actions, enabled=enabled, stop=stop)

    def update_filter_rule(self, rule_id, **kwargs):
        from core.db import update_filter_rule
        return update_filter_rule(rule_id, **kwargs)

    def delete_filter_rule(self, rule_id):
        from core.db import delete_filter_rule
        return delete_filter_rule(rule_id)

    def reorder_filter_rules(self, ordered_ids):
        from core.db import reorder_filter_rules
        return reorder_filter_rules(ordered_ids)

    def apply_filter_rules_to_existing(self) -> dict:
        """Run the enabled rule pipeline against every existing local article
        (retroactive apply, e.g. after creating or editing a rule). Returns
        ``{"scanned": N, "changed": M}``. Safe to call from a background thread.
        """
        rules = list_filter_rules(enabled_only=True)
        if not rules:
            return {"scanned": 0, "changed": 0}
        global_behavior = self._resolve_delete_behavior(None)
        scanned = 0
        changed = 0
        conn = get_connection()
        try:
            c = conn.cursor()
            feed_behavior = {}
            for fid, beh in c.execute("SELECT id, delete_behavior FROM feeds").fetchall():
                if beh:
                    feed_behavior[fid] = beh
            rows = c.execute(
                "SELECT a.id, a.feed_id, a.title, a.content, a.description, a.author, "
                "COALESCE(f.title, ''), a.url, COALESCE(a.tags, ''), a.is_read, a.is_favorite, "
                "CASE WHEN a.opened_at IS NOT NULL THEN 1 ELSE 0 END, "
                "(SELECT COUNT(*) FROM article_versions v WHERE v.article_id = a.id) "
                "FROM articles a LEFT JOIN feeds f ON a.feed_id = f.id"
            ).fetchall()
            for row in rows:
                scanned += 1
                article_id, feed_id = row[0], row[1]
                art = {
                    "title": row[2] or "",
                    "content": row[3] or "",
                    "description": row[4] or "",
                    "author": row[5] or "",
                    "feed": row[6] or "",
                    "url": row[7] or "",
                    "tag": row[8] or "",
                    "read": bool(row[9]),
                    "favorite": bool(row[10]),
                    "opened": bool(row[11]),
                    "updated": int(row[12] or 0) > 1,
                }
                agg = filters_mod.evaluate_pipeline(rules, art)
                if not agg.get("matched_rule_ids"):
                    continue
                behavior = feed_behavior.get(feed_id, global_behavior)
                eff = filters_mod.resolve_effective_actions(agg, behavior)
                try:
                    filters_mod.apply_effective_actions(c, article_id, eff, feed_id=feed_id)
                    changed += 1
                except Exception:
                    log.debug("Retroactive rule apply failed for %s", article_id, exc_info=True)
            conn.commit()
        finally:
            conn.close()
        return {"scanned": scanned, "changed": changed}

    def toggle_favorite(self, article_id: str):
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT is_favorite FROM articles WHERE id = ?", (article_id,))
            row = c.fetchone()
            if not row:
                return None
            new_val = 0 if int(row[0] or 0) else 1
            c.execute("UPDATE articles SET is_favorite = ? WHERE id = ?", (new_val, article_id))
            conn.commit()
            return bool(new_val)
        finally:
            conn.close()

    def set_favorite(self, article_id: str, is_favorite: bool) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,))
            if not c.fetchone():
                return False
            c.execute("UPDATE articles SET is_favorite = ? WHERE id = ?", (1 if is_favorite else 0, article_id))
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_article(self, article_id: str, behavior: str | None = None) -> bool:
        """Delete an article, honoring the configured delete behavior.

        ``behavior`` (resolved by the caller from the per-feed override or the
        global ``delete_behavior`` setting) selects what "delete" does:
          * "deleted"/None → soft delete: tombstone + remove (Deleted view).
          * "purge"        → permanent: tombstone marked purged (hidden from the
                             Deleted view) + remove; refresh still won't resurrect.
          * "category:<p>" → MOVE: file the article under category ``<p>`` (set
                             category_override) and keep the row.
        See core.filters.parse_delete_behavior for the parsing.
        """
        if not article_id:
            return False
        conn = get_connection()
        try:
            try:
                conn.execute(f"PRAGMA busy_timeout={_DELETE_ARTICLE_BUSY_TIMEOUT_MS}")
            except sqlite3.Error:
                pass
            c = conn.cursor()
            c.execute("BEGIN IMMEDIATE")

            c.execute(
                "SELECT feed_id, url, title, content, description, date, author, "
                "media_url, media_type, chapter_url, is_read, is_favorite "
                "FROM articles WHERE id = ? LIMIT 1",
                (article_id,),
            )
            row = c.fetchone()
            if not row:
                conn.rollback()
                return False
            feed_id, article_url = row[0], row[1]

            # Resolve the effective behavior now that we know the feed (per-feed
            # override wins over the global setting) when the caller didn't pass one.
            effective_behavior = behavior if behavior is not None else self._resolve_delete_behavior(feed_id)
            kind, category = filters_mod.parse_delete_behavior(effective_behavior)

            if kind == "category" and category:
                # Move, don't remove: refile under the target category.
                c.execute(
                    "UPDATE articles SET category_override = ? WHERE id = ?",
                    (category, article_id),
                )
                moved = int(c.rowcount or 0)
                conn.commit()
                return moved > 0
            # Preserve the full article so the Deleted Articles view can show and
            # restore it (the row itself is removed below).
            snapshot = {
                "title": row[2],
                "content": row[3],
                "description": row[4],
                "date": row[5],
                "author": row[6],
                "media_url": row[7],
                "media_type": row[8],
                "chapter_url": row[9],
                "is_read": row[10],
                "is_favorite": row[11],
            }
            remember_deleted_article(
                feed_id, article_id, article_url,
                snapshot=snapshot, purged=(kind == "purge"), cursor=c,
            )
            c.execute("DELETE FROM article_labels WHERE article_id = ?", (article_id,))
            c.execute("DELETE FROM chapters WHERE article_id = ?", (article_id,))
            local_cache_key = f"local:{article_id}"
            c.execute("DELETE FROM chapter_cache WHERE cache_key = ?", (local_cache_key,))
            c.execute("DELETE FROM chapter_sources WHERE cache_key = ?", (local_cache_key,))
            c.execute("DELETE FROM articles WHERE id = ?", (article_id,))
            deleted = int(c.rowcount or 0)
            conn.commit()
            return deleted > 0
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if _is_locked_error(e):
                log.warning("Database locked while deleting article %s", article_id, exc_info=True)
                return False
            log.error("Local delete article error for %s: %s", article_id, e)
            return False
        finally:
            conn.close()

    def update_article_media(self, article_id: str, media_url: str, media_type: str) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE articles SET media_url = ?, media_type = ? WHERE id = ?", (media_url, media_type, article_id))
            conn.commit()
            return True
        except Exception as e:
            log.error(f"Error updating article media: {e}")
            return False
        finally:
            conn.close()

    def add_feed(self, url: str, category: str = UNCATEGORIZED) -> bool:
        real_url = self._resolve_feed_url(url)
        
        title = real_url
        try:
            from core import discovery as _disc
            from core import forum_sources as _forum_sources
            from core import groups_io as _groups_io
            if _forum_sources.is_google_group_url(real_url):
                page_title, _items = _forum_sources.fetch_google_group_items(
                    real_url, max_items=1, timeout=10
                )
                title = page_title or real_url
            elif _groups_io.is_group_search_url(real_url):
                query = _groups_io.search_query(real_url)
                group_path = urlsplit(real_url).path.split("/")
                group = group_path[2] if len(group_path) > 2 else "Groups.io"
                title = f"{group} search: {query}" if query else f"{group} search"
            elif _disc.is_youtube_search_url(real_url):
                q = _disc.youtube_search_query(real_url) or real_url
                title = f"YouTube: {q}"
            elif rumble_mod.is_rumble_url(real_url) and not real_url.lower().endswith((".xml", ".rss", ".atom")):
                page_title, _items = rumble_mod.fetch_listing_items(real_url, timeout_s=10.0)
                title = page_title or real_url
            elif odysee_mod.is_odysee_url(real_url) and not real_url.lower().endswith((".xml", ".rss", ".atom")):
                page_title, _items = odysee_mod.fetch_listing_items(real_url, max_items=1, timeout_s=10.0)
                title = page_title or real_url
            elif _disc.is_soundcloud_url(real_url) and _disc.soundcloud_listing_kind(real_url) in ("user", "playlist"):
                page_title, _items = _disc.fetch_soundcloud_listing(real_url, max_items=1, timeout=12.0)
                title = page_title or real_url
            elif _disc.is_mixcloud_url(real_url) and _disc.mixcloud_listing_kind(real_url) in ("user", "playlist"):
                page_title, _items = _disc.fetch_mixcloud_listing(real_url, max_items=1, timeout=12.0)
                title = page_title or real_url
            else:
                resp = utils.safe_requests_get(real_url, timeout=10)
                resp = _retry_feed_not_acceptable(resp, real_url, headers={}, timeout=10)
                resp, effective_url = _retry_cloudflare_challenged_wordpress_feed(
                    resp,
                    real_url,
                    headers={},
                    timeout=10,
                )
                if effective_url != real_url:
                    real_url = effective_url
                    title = real_url
                content_type = ""
                try:
                    content_type = resp.headers.get("Content-Type", "")
                except Exception:
                    content_type = ""
                d = _parse_feed_document(resp.content, resp.text, content_type)
                title = d.feed.get('title', real_url)
        except Exception:
            title = title or real_url
            
        conn = get_connection()
        try:
            c = conn.cursor()
            feed_id = str(uuid.uuid4())
            c.execute("INSERT INTO feeds (id, url, title, upstream_title, category, icon_url) VALUES (?, ?, ?, ?, ?, ?)",
                      (feed_id, real_url, title, title, category, ""))
            conn.commit()
            return True
        finally:
            conn.close()

    def remove_feed(self, feed_id: str) -> bool:
        if not feed_id:
            return False

        conn = get_connection()
        try:
            try:
                # Don't hang the UI for up to busy_timeout when a refresh is writing.
                conn.execute(f"PRAGMA busy_timeout={_REMOVE_FEED_BUSY_TIMEOUT_MS}")
            except sqlite3.Error:
                pass

            c = conn.cursor()
            c.execute("BEGIN IMMEDIATE")
            # Remove playback state for the feed's articles.
            # - Article ID based keys are safe to delete (unique per article).
            # - URL based keys may be shared across feeds; delete only when the URL isn't used elsewhere.
            c.execute(
                "DELETE FROM playback_state WHERE id IN (SELECT 'article:' || id FROM articles WHERE feed_id = ?)",
                (feed_id,),
            )
            c.execute(
                """
                WITH
                  -- URLs associated with the feed being deleted.
                  urls_to_delete AS (
                    SELECT url AS id FROM articles WHERE feed_id = ? AND url IS NOT NULL AND url != ''
                    UNION ALL
                    SELECT media_url AS id FROM articles WHERE feed_id = ? AND media_url IS NOT NULL AND media_url != ''
                  )
                DELETE FROM playback_state
                WHERE
                  id IN (SELECT id FROM urls_to_delete)
                  AND NOT EXISTS (
                    SELECT 1 FROM articles
                    WHERE feed_id != ?
                      AND (
                        (articles.url IS NOT NULL AND articles.url != '' AND articles.url = playback_state.id)
                        OR (articles.media_url IS NOT NULL AND articles.media_url != '' AND articles.media_url = playback_state.id)
                      )
                  )
                """,
                (feed_id, feed_id, feed_id),
            )

            # Remove dependent chapter rows before deleting articles.
            c.execute(
                "DELETE FROM chapters WHERE article_id IN (SELECT id FROM articles WHERE feed_id = ?)",
                (feed_id,),
            )
            c.execute(
                "DELETE FROM chapter_cache "
                "WHERE cache_key IN (SELECT 'local:' || id FROM articles WHERE feed_id = ?)",
                (feed_id,),
            )
            c.execute(
                "DELETE FROM chapter_sources "
                "WHERE cache_key IN (SELECT 'local:' || id FROM articles WHERE feed_id = ?)",
                (feed_id,),
            )
            c.execute("DELETE FROM articles WHERE feed_id = ?", (feed_id,))
            c.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
            removed = int(c.rowcount or 0)
            conn.commit()
            return removed > 0
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                log.debug(
                    "Error during database rollback while removing feed %s",
                    feed_id,
                    exc_info=True,
                )

            if _is_locked_error(e):
                log.warning("Database locked while removing feed %s", feed_id, exc_info=True)
            else:
                log.exception("Error removing feed %s", feed_id)

            raise
        finally:
            conn.close()

    def supports_feed_edit(self) -> bool:
        return True

    def supports_feed_url_update(self) -> bool:
        return True

    def update_feed(self, feed_id: str, title: str = None, url: str = None, category: str = None) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT url, title, category, COALESCE(title_is_custom, 0) FROM feeds WHERE id = ?",
                (feed_id,),
            )
            row = c.fetchone()
            if not row:
                return False
            cur_url, cur_title, cur_category, cur_title_is_custom = row[0], row[1], row[2], row[3]
            new_url = url if url is not None else cur_url
            new_title = title if title is not None else cur_title
            new_category = category if category is not None else cur_category
            new_title_is_custom = int(cur_title_is_custom or 0)

            # Preserve refresh-managed titles unless the user explicitly changes the title.
            if title is not None and str(title) != str(cur_title):
                new_title_is_custom = 1

            if str(new_url or "") != str(cur_url or ""):
                c.execute(
                    "UPDATE feeds SET url = ?, title = ?, title_is_custom = ?, category = ?, etag = NULL, last_modified = NULL WHERE id = ?",
                    (new_url, new_title, new_title_is_custom, new_category, feed_id),
                )
            else:
                c.execute(
                    "UPDATE feeds SET url = ?, title = ?, title_is_custom = ?, category = ? WHERE id = ?",
                    (new_url, new_title, new_title_is_custom, new_category, feed_id),
                )
            conn.commit()
            return True
        except Exception as e:
            log.error(f"Update feed error: {e}")
            return False
        finally:
            conn.close()

    def supports_feed_title_reset(self) -> bool:
        return True

    def reset_feed_title(self, feed_id: str) -> bool:
        if not feed_id:
            return False
        conn = get_connection()
        try:
            c = conn.cursor()
            # Clear the custom-title flag so the next refresh restores the feed-provided title.
            # Also clear validators so a subsequent refresh re-fetches metadata promptly.
            # Restore the last-known upstream title immediately (and make
            # title == upstream_title) so the rename-detection in
            # _resolve_feed_title_update sees the title as refresh-managed
            # again instead of re-flagging the old custom name (issue #43).
            c.execute(
                "UPDATE feeds SET title_is_custom = 0, "
                "title = COALESCE(NULLIF(upstream_title, ''), title), "
                "upstream_title = COALESCE(NULLIF(upstream_title, ''), title), "
                "etag = NULL, last_modified = NULL WHERE id = ?",
                (feed_id,),
            )
            conn.commit()
            return int(c.rowcount or 0) > 0
        except Exception as e:
            log.error(f"Reset feed title error: {e}")
            return False
        finally:
            conn.close()

    # ... import/export/category methods ...

    def import_opml(self, path: str, target_category: str = None) -> bool:
        import os
        import sys
        import tempfile
        
        log_filename = os.path.join(tempfile.gettempdir(), f"opml_debug_{int(time.time())}_{uuid.uuid4().hex[:4]}.log")
        
        try:
            with open(log_filename, "w", encoding="utf-8") as log_file:
                def write_log(msg):
                    log_file.write(msg + "\n")
                    log_file.flush()
                    log.debug(f"OPML_DEBUG: {msg}")

                write_log(f"Starting import from: {path}")
                write_log(f"Target category: {target_category}")
                write_log(f"Global sqlite3 present: {'sqlite3' in globals()}")
                
                try:
                    content = ""
                    # Try to read file with different encodings
                    for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
                        try:
                            with open(path, 'r', encoding=encoding) as f:
                                content = f.read()
                            write_log(f"Read successfully with encoding: {encoding}")
                            break
                        except UnicodeDecodeError:
                            continue
                    
                    if not content:
                        write_log("OPML Import: Could not read file with supported encodings")
                        return False

                    # Try parsing with BS4
                    soup = None
                    try:
                        soup = BS(content, 'xml')
                        write_log("Parsed with 'xml' parser.")
                    except Exception as e:
                        write_log(f"XML parse failed: {e}")
                    
                    if not soup or not soup.find('opml'):
                        # Fallback to html.parser if xml fails or doesn't find root
                        write_log("Fallback to 'html.parser'.")
                        soup = BS(content, 'html.parser')

                    # Find body
                    body = soup.find('body')
                    if not body:
                        write_log("OPML Import: No body found")
                        return False
                    
                    write_log(f"Body found. Children: {len(body.find_all('outline', recursive=False))}")

                    conn = get_connection()
                    try:
                        c = conn.cursor()

                        from core.db import CATEGORY_PATH_SEP, make_category_path, sanitize_category_leaf

                        def ensure_category_path(title: str):
                            title = (title or "").strip()
                            if not title or title == UNCATEGORIZED:
                                return None
                            try:
                                parent_id = None
                                current_path = ""
                                for raw_part in title.split(CATEGORY_PATH_SEP):
                                    leaf = sanitize_category_leaf(raw_part)
                                    if not leaf:
                                        continue
                                    current_path = make_category_path(current_path, leaf)
                                    c.execute("SELECT id FROM categories WHERE title = ?", (current_path,))
                                    row = c.fetchone()
                                    if row:
                                        cat_id = row[0]
                                        c.execute(
                                            "UPDATE categories SET parent_id = ? WHERE id = ?",
                                            (parent_id, cat_id),
                                        )
                                    else:
                                        cat_id = str(uuid.uuid4())
                                        c.execute(
                                            "INSERT INTO categories (id, title, parent_id) VALUES (?, ?, ?)",
                                            (cat_id, current_path, parent_id),
                                        )
                                    parent_id = cat_id
                                return current_path or None
                            except Exception as e:
                                write_log(f"Could not ensure category '{title}': {e}")
                                return title

                        def append_category(parent_category: str, folder_title: str) -> str:
                            path = str(parent_category or "").strip()
                            if path == UNCATEGORIZED:
                                path = ""
                            for raw_part in str(folder_title or "").split(CATEGORY_PATH_SEP):
                                leaf = sanitize_category_leaf(raw_part)
                                if leaf:
                                    path = make_category_path(path, leaf)
                            return path or UNCATEGORIZED

                        # Make sure target category exists if used.
                        if target_category and target_category != UNCATEGORIZED:
                            target_category = ensure_category_path(target_category) or target_category
                        base_category = target_category if target_category else UNCATEGORIZED

                        def process_outline(outline, current_category=UNCATEGORIZED):
                            # Case insensitive attribute lookup helper
                            def get_attr(name):
                                # Direct lookup first
                                if name in outline.attrs:
                                    return outline.attrs[name]
                                # Case insensitive lookup
                                for k, v in outline.attrs.items():
                                    if k.lower() == name.lower():
                                        return v
                                return None

                            imported_title = str(get_attr('text') or get_attr('title') or "").strip()
                            text = imported_title or "Unknown Feed"
                            
                            xmlUrl = str(get_attr('xmlUrl') or "").strip()
                            
                            if xmlUrl:
                                # Keep OPML import fast by avoiding live site/feed discovery here.
                                # Newly imported feeds are refreshed immediately after import, and
                                # refresh will repair homepage-style URLs to the real feed URL.
                                resolved_url = self._resolve_feed_url(xmlUrl, allow_network=False) or xmlUrl
                                if resolved_url != xmlUrl:
                                    write_log(f"Resolved feed URL: {xmlUrl} -> {resolved_url}")
                                else:
                                    write_log(f"Found feed: {text} -> {xmlUrl}")

                                # It's a feed
                                candidate_urls = list(dict.fromkeys([xmlUrl, resolved_url]))
                                placeholders = ",".join(["?"] * len(candidate_urls))
                                c.execute(
                                    f"SELECT id FROM feeds WHERE url IN ({placeholders})",
                                    candidate_urls,
                                )
                                if not c.fetchone():
                                    feed_id = str(uuid.uuid4())
                                    cat_to_use = current_category or UNCATEGORIZED

                                    if cat_to_use and cat_to_use != UNCATEGORIZED:
                                        cat_to_use = ensure_category_path(cat_to_use) or cat_to_use
                                    
                                    # Preserve OPML-provided labels as user-custom titles so refresh
                                    # does not overwrite curated names imported from other readers.
                                    title_is_custom = 1 if imported_title else 0
                                    c.execute(
                                        "INSERT INTO feeds (id, url, title, title_is_custom, category, icon_url) "
                                        "VALUES (?, ?, ?, ?, ?, ?)",
                                        (feed_id, resolved_url, text, title_is_custom, cat_to_use, ""),
                                    )
                            
                            # Recursion for children
                            # In BS4, children include newlines/NavigableString, so filtering for Tags is important
                            children = outline.find_all('outline', recursive=False)
                            if children:
                                new_cat = current_category
                                # If it's a folder (no xmlUrl), append it to the current
                                # category path so standard nested OPML outlines survive import.
                                if not xmlUrl:
                                    new_cat = append_category(current_category, text)
                                    if new_cat and new_cat != UNCATEGORIZED:
                                        ensure_category_path(new_cat)

                                for child in children:
                                    process_outline(child, new_cat)

                        # Process top-level outlines in body
                        for outline in body.find_all('outline', recursive=False):
                            process_outline(outline, base_category)
                            
                        conn.commit()
                    finally:
                        conn.close()
                    write_log("Import completed successfully.")
                    return True
                except Exception as e:
                    import traceback
                    write_log(f"OPML Import error: {e}")
                    write_log(traceback.format_exc())
                    return False
        except Exception as e:
            # Logging file failed; continue without logging
            return False

    def export_opml(self, path: str) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT title, url, category FROM feeds")
            feeds = c.fetchall()
        finally:
            conn.close()

        return utils.write_opml(
            [
                {"title": title, "url": url, "category": category}
                for title, url, category in feeds
            ],
            path,
        )

    def supports_subcategories(self) -> bool:
        # The local provider stores nesting natively (categories.parent_id) and
        # identifies nested categories by their full path, so it supports
        # folders within folders, including duplicate leaf names under different
        # parents (issue #27).
        return True

    def get_categories(self) -> List[str]:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT title FROM categories ORDER BY title")
            rows = c.fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def add_category(self, title: str, parent_title: str = None) -> bool:
        # `title` is the new leaf name; `parent_title` is the parent's full path
        # (or None for top-level). The stored identity is the full path so the
        # same leaf can live under different parents.
        from core.db import make_category_path, sanitize_category_leaf
        leaf = sanitize_category_leaf(title)
        if not leaf:
            return False
        conn = get_connection()
        c = conn.cursor()
        try:
            parent_id = None
            parent_path = (parent_title or "").strip()
            if parent_path:
                c.execute("SELECT id FROM categories WHERE title = ?", (parent_path,))
                row = c.fetchone()
                if not row:
                    return False  # parent must exist
                parent_id = row[0]
            path = make_category_path(parent_path, leaf)
            c.execute(
                "INSERT INTO categories (id, title, parent_id) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), path, parent_id),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Duplicate: this leaf already exists under this parent
        finally:
            conn.close()

    def rename_category(self, old_title: str, new_title: str) -> bool:
        # `old_title` is the existing full path; `new_title` is the new leaf.
        # Renaming a node changes its path, so its descendants' paths and every
        # feed assigned to those paths must be rewritten too.
        from core.db import make_category_path, sanitize_category_leaf, CATEGORY_PATH_SEP
        old_path = (old_title or "").strip()
        new_leaf = sanitize_category_leaf(new_title)
        if not old_path or not new_leaf:
            return False
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("SELECT id, parent_id FROM categories WHERE title = ?", (old_path,))
            row = c.fetchone()
            if not row:
                return False
            cat_id, parent_id = row
            parent_path = None
            if parent_id:
                c.execute("SELECT title FROM categories WHERE id = ?", (parent_id,))
                prow = c.fetchone()
                parent_path = prow[0] if prow else None
            new_path = make_category_path(parent_path, new_leaf)
            if new_path == old_path:
                return True
            # Reject a collision with an existing sibling/category path.
            c.execute("SELECT 1 FROM categories WHERE title = ?", (new_path,))
            if c.fetchone():
                return False
            # Rewrite this path and all descendant paths (categories + feeds).
            prefix = old_path + CATEGORY_PATH_SEP
            c.execute("SELECT title FROM categories")
            affected = [r[0] for r in c.fetchall()
                        if r[0] == old_path or r[0].startswith(prefix)]
            for old_p in affected:
                new_p = new_path + old_p[len(old_path):]
                c.execute("UPDATE categories SET title = ? WHERE title = ?", (new_p, old_p))
                c.execute("UPDATE feeds SET category = ? WHERE category = ?", (new_p, old_p))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            log.error(f"Rename error: {e}")
            return False
        finally:
            conn.close()

    def move_category(self, title: str, parent_title: str = None) -> bool:
        # `title` is the moved category's full path; `parent_title` is the new
        # parent's full path, or None for top level (issue #86). The leaf name
        # is kept -- only the ancestry changes -- but because the path embeds
        # its ancestors, the node's own path, every descendant path and every
        # feed assigned to those paths are rewritten, exactly as in
        # rename_category.
        from core.db import CATEGORY_PATH_SEP, category_display_leaf, make_category_path
        old_path = (title or "").strip()
        new_parent = (parent_title or "").strip() or None
        if not old_path or old_path.casefold() == UNCATEGORIZED.casefold():
            return False
        if new_parent and new_parent.casefold() == UNCATEGORIZED.casefold():
            return False
        # A category cannot become its own ancestor: that would detach the whole
        # subtree from the root and orphan every feed under it.
        if new_parent == old_path or (new_parent or "").startswith(old_path + CATEGORY_PATH_SEP):
            return False

        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("SELECT id, parent_id FROM categories WHERE title = ?", (old_path,))
            row = c.fetchone()
            if not row:
                return False
            cat_id = row[0]

            new_parent_id = None
            if new_parent:
                c.execute("SELECT id FROM categories WHERE title = ?", (new_parent,))
                prow = c.fetchone()
                if not prow:
                    return False  # parent must exist
                new_parent_id = prow[0]

            new_path = make_category_path(new_parent, category_display_leaf(old_path))
            if new_path == old_path:
                return True
            # The target parent may already have a child with this leaf name.
            c.execute("SELECT 1 FROM categories WHERE title = ?", (new_path,))
            if c.fetchone():
                return False

            prefix = old_path + CATEGORY_PATH_SEP
            c.execute("SELECT title FROM categories")
            affected = [r[0] for r in c.fetchall()
                        if r[0] == old_path or r[0].startswith(prefix)]
            for old_p in affected:
                new_p = new_path + old_p[len(old_path):]
                c.execute("UPDATE categories SET title = ? WHERE title = ?", (new_p, old_p))
                c.execute("UPDATE feeds SET category = ? WHERE category = ?", (new_p, old_p))
            # Only the moved node changes parent; its descendants keep pointing
            # at their own parents by id, so their links survive the rewrite.
            c.execute("UPDATE categories SET parent_id = ? WHERE id = ?", (new_parent_id, cat_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            log.error(f"Move category error: {e}")
            return False
        finally:
            conn.close()

    def delete_category(self, title: str) -> bool:
        # `title` is the full path. Direct children are reparented to the deleted
        # node's parent, which shortens their paths; descendant paths and the
        # feeds assigned to them are rewritten to match.
        from core.db import CATEGORY_PATH_SEP
        path = (title or "").strip()
        if path.casefold() == UNCATEGORIZED.casefold():
            return False
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT id, parent_id FROM categories WHERE title = ?", (path,))
            row = c.fetchone()
            if not row:
                return False
            cat_id, cat_parent_id = row
            parent_path = None
            if cat_parent_id:
                c.execute("SELECT title FROM categories WHERE id = ?", (cat_parent_id,))
                prow = c.fetchone()
                parent_path = prow[0] if prow else None

            old_prefix = path + CATEGORY_PATH_SEP
            new_prefix = (parent_path + CATEGORY_PATH_SEP) if parent_path else ""
            c.execute("SELECT title FROM categories")
            all_titles = [r[0] for r in c.fetchall()]
            descendants = [t for t in all_titles if t.startswith(old_prefix)]

            # Reparenting could collide with an existing aunt category of the
            # same name; detect that up front.
            remaining = set(all_titles) - set(descendants) - {path}
            mapping = []
            collision = False
            for old_p in descendants:
                new_p = new_prefix + old_p[len(old_prefix):]
                if new_p in remaining:
                    collision = True
                    break
                mapping.append((old_p, new_p))
                remaining.add(new_p)

            if collision:
                # Safe fallback: drop the whole subtree, feeds go to Uncategorized.
                for sp in [path] + descendants:
                    c.execute("UPDATE feeds SET category = ? WHERE category = ?", (UNCATEGORIZED, sp))
                    c.execute("DELETE FROM categories WHERE title = ?", (sp,))
                conn.commit()
                return True

            # Reparent direct children (parent_id is by id, so deeper links hold).
            c.execute("UPDATE categories SET parent_id = ? WHERE parent_id = ?", (cat_parent_id, cat_id))
            for old_p, new_p in mapping:
                c.execute("UPDATE categories SET title = ? WHERE title = ?", (new_p, old_p))
                c.execute("UPDATE feeds SET category = ? WHERE category = ?", (new_p, old_p))
            # Feeds directly in the deleted category fall back to Uncategorized.
            c.execute("UPDATE feeds SET category = ? WHERE category = ?", (UNCATEGORIZED, path))
            c.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
            conn.commit()
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            log.error(f"Delete category error: {e}")
            return False
        finally:
            conn.close()

    # Optional API used by GUI when present
    def get_article_chapters(self, article_id: str):
        chapters = utils.get_chapters_from_db(article_id)
        if chapters:
            return chapters

        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT media_url, media_type, chapter_url, url FROM articles WHERE id = ? LIMIT 1",
                (article_id,),
            )
            row = c.fetchone()
        finally:
            conn.close()

        if not row:
            return []

        media_url, media_type, chapter_url, article_url = row
        if not media_url:
            media_url = article_url
        return utils.fetch_and_store_chapters(article_id, media_url, media_type, chapter_url=chapter_url)
