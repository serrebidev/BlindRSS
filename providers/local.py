import feedparser
import json
import time
import uuid
import threading
import sqlite3
import concurrent.futures
import os
import re
import requests
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from urllib.parse import urlparse
from .base import RSSProvider
from core.models import Feed, Article
from core.db import get_connection, init_db, get_feed_settings
from core.discovery import discover_feed
from core import utils
from core import rumble as rumble_mod
from core import odysee as odysee_mod
from core import npr as npr_mod
from bs4 import BeautifulSoup as BS, XMLParsedAsHTMLWarning
import xml.etree.ElementTree as ET
import logging
import warnings
from urllib.parse import urlsplit, urlunsplit

# Avoid noisy warnings when falling back to HTML parser for XML content
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

log = logging.getLogger(__name__)

_REFRESH_WORKERS_CPU_1_2 = 2
_REFRESH_WORKERS_CPU_3_4 = 4
_REFRESH_WORKERS_CPU_5_8 = 6
_REFRESH_WORKERS_CPU_9_PLUS = 8
_REFRESH_PER_HOST_LOW_CPU = 1
_REFRESH_PER_HOST_NORMAL = 2
_REFRESH_PER_HOST_HIGH_CPU = 2

_REMOVE_FEED_BUSY_TIMEOUT_MS = 5000
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


def _entry_content(entry) -> str:
    try:
        contents = entry.get("content")
        if contents:
            first = contents[0]
            value = first.get("value") if isinstance(first, dict) else getattr(first, "value", None)
            if value:
                return str(value)
    except Exception:
        pass

    return (
        _entry_text(entry, "summary_detail")
        or _entry_text(entry, "summary")
        or _entry_text(entry, "description")
    )


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
            if href and (not wanted_rel or rel == wanted_rel):
                return href

    return _entry_text(entry, "link")


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
        "date_published",
        "date_modified",
    )
    if raw_date:
        return raw_date

    try:
        parsed = (
            entry.get("published_parsed")
            or entry.get("updated_parsed")
            or entry.get("created_parsed")
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
        for encoding in ("utf-8-sig", "utf-8", "iso-8859-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
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


def _parse_feed_document(data, text: Optional[str] = None, content_type: str = ""):
    decoded_text = _decode_feed_text(data, text)
    stripped = decoded_text.lstrip()
    content_type = str(content_type or "").lower()
    if stripped.startswith("{") or "json" in content_type:
        json_feed = _parse_json_feed(decoded_text)
        if json_feed is not None:
            return json_feed

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
        low.endswith((".xml", ".rss", ".atom"))
        or "feed" in low
        or last_segment in {"rss", "atom", "feed", "feeds"}
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
    if any(marker in content_type for marker in ("rss", "atom", "xml", "feed+json")):
        return True

    try:
        snippet = str(getattr(resp, "text", "") or "")[:512].lstrip().lower()
    except Exception:
        snippet = ""

    return (
        snippet.startswith("<?xml")
        or "<rss" in snippet
        or "<feed" in snippet
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


def _retry_cloudflare_challenged_wordpress_feed(resp, url: str, *, headers: dict, timeout):
    """Retry WordPress-style /feed URLs with the canonical trailing slash after a challenge."""
    try:
        status_code = int(getattr(resp, "status_code", 0) or 0)
    except Exception:
        status_code = 0
    if status_code != 403 or not _response_looks_cloudflare_challenge(resp):
        return resp, url

    candidate = _wordpress_feed_slash_variant(url)
    if not candidate or candidate == url:
        return resp, url

    try:
        retry_resp = utils.safe_requests_get(candidate, headers=headers, timeout=timeout)
    except Exception:
        return resp, url

    if _response_looks_feed_like(retry_resp):
        return retry_resp, candidate
    return resp, url


def _retry_feed_not_acceptable(resp, url: str, *, headers: dict, timeout):
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
        retry_resp = utils.safe_requests_get(url, headers=retry_headers, timeout=timeout)
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

    def get_name(self) -> str:
        return "Local RSS"

    def should_force_startup_refresh(self) -> bool:
        # Forcing the local provider is just a full GET per feed (no fan-out), so the
        # first refresh after launch always pulls current content instead of trusting
        # possibly-stale ETag/Last-Modified validators that make some servers return 304.
        return True

    def _cache_ignore_enabled(self) -> bool:
        try:
            return bool(self.config.get("ignore_feed_cache", False))
        except Exception:
            return False

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
        resolved = str(url or "").strip()
        if not resolved:
            return resolved

        # YouTube search URLs have no native RSS and are enumerated on refresh;
        # keep them verbatim so discovery does not rewrite them to a channel feed.
        try:
            from core.discovery import is_youtube_search_url
            if is_youtube_search_url(resolved):
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
                "SELECT id, url, title, category, etag, last_modified, COALESCE(title_is_custom, 0) "
                "FROM feeds WHERE id = ?",
                (feed_id,),
            )
            row = c.fetchone()
        finally:
            conn.close()

        if not row:
            return False

        # For single feed refresh, use a simple semaphore since we aren't competing with other threads here.
        host_limits = defaultdict(lambda: threading.Semaphore(1))
        feed_timeout = max(1, int(self.config.get("feed_timeout_seconds", 15) or 15))
        retries = max(0, int(self.config.get("feed_retry_attempts", 1) or 0))

        try:
            self._refresh_single_feed(
                row,
                host_limits,
                feed_timeout,
                retries,
                progress_cb,
                force=True,
                respect_failure_cooldown=False,
            )
            return True
        except Exception as e:
            log.error(f"Single feed refresh failed: {e}")
            return False

    def _refresh_feed_rows(self, feed_rows, progress_cb=None, force: bool = False) -> bool:
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

        def task(feed_row):
            return self._refresh_single_feed(
                feed_row,
                host_limits,
                feed_timeout,
                retries,
                progress_cb,
                force,
                respect_failure_cooldown=True,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(task, feed_row): feed_row for feed_row in feed_rows}
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log.error(f"Refresh worker error: {e}")
        return True

    def refresh(self, progress_cb=None, force: bool = False) -> bool:
        conn = get_connection()
        try:
            c = conn.cursor()
            # Fetch etag/last_modified for conditional get plus metadata for UI updates
            c.execute(
                "SELECT id, url, title, category, etag, last_modified, COALESCE(title_is_custom, 0) FROM feeds"
            )
            feeds = c.fetchall()
        finally:
            conn.close()

        # When the user opts to ignore feed caching, treat every full refresh as
        # forced so periodic/background refreshes also bypass spurious 304s.
        effective_force = bool(force) or self._cache_ignore_enabled()
        return self._refresh_feed_rows(feeds, progress_cb=progress_cb, force=effective_force)

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
                "SELECT id, url, title, category, etag, last_modified, COALESCE(title_is_custom, 0) "
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
    ):
        # Each thread gets its own connection
        feed_id, feed_url, feed_title, feed_category, etag, last_modified, title_is_custom = feed_row
        status = "ok"
        new_items = 0
        new_article_summaries = []
        error_msg = None
        final_title = feed_title or "Unknown Feed"
        failure_cooldown_seconds = None
        started_at = time.monotonic()
        entry_count = None

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

        def _preview_for_notification(raw_text):
            text = str(raw_text or "").strip()
            if not text:
                return ""
            try:
                text = BS(text, "html.parser").get_text(" ", strip=True)
            except Exception:
                pass
            text = " ".join(text.split())
            if len(text) > 180:
                text = text[:177].rstrip() + "..."
            return text

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
                            if attempt <= retries:
                                backoff = min(4, attempt)
                                time.sleep(backoff)
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
                    title_to_store = (
                        str(feed_title or "").strip() if bool(int(title_is_custom or 0)) and str(feed_title or "").strip() else final_title
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, None, None, feed_id),
                    )
                    conn.commit()

                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        try:
                            article_id = item.id
                            title = item.title or "No Title"
                            url = item.url or ""
                            author = item.author or final_title or "Odysee"
                            raw_date = item.published or ""
                            date = utils.normalize_date(raw_date, title, "", url)

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
                            if attempt <= retries:
                                time.sleep(min(4, attempt))
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
                    title_to_store = (
                        str(feed_title or "").strip() if bool(int(title_is_custom or 0)) and str(feed_title or "").strip() else final_title
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, None, None, feed_id),
                    )
                    conn.commit()

                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
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
                    for attempt in range(1, attempts + 1):
                        try:
                            all_items.clear()
                            page_title = None
                            for page in range(1, max_pages + 1):
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
                            if attempt <= retries:
                                backoff = min(4, attempt)
                                time.sleep(backoff)
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
                    title_to_store = (
                        str(feed_title or "").strip() if bool(int(title_is_custom or 0)) and str(feed_title or "").strip() else final_title
                    )
                    c.execute(
                        "UPDATE feeds SET title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (title_to_store, None, None, feed_id),
                    )
                    conn.commit()

                    total_entries = len(all_items)
                    entry_count = total_entries
                    for i, item in enumerate(all_items):
                        try:
                            article_id = item.id
                            title = item.title or "No Title"
                            url = item.url or ""
                            author = item.author or final_title or "Rumble"
                            raw_date = item.published or ""
                            date = utils.normalize_date(raw_date, title, "", url)

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
                for attempt in range(1, attempts_total + 1):
                    if feed_impersonate_mode == "never":
                        impersonate_now = False
                    elif feed_impersonate_mode == "always":
                        impersonate_now = True
                    else:
                        impersonate_now = do_impersonation_next
                    try:
                        resp = utils.safe_requests_get(
                            feed_url,
                            headers=headers,
                            timeout=direct_fetch_timeout,
                            impersonate=impersonate_now,
                        )
                        resp = _retry_feed_not_acceptable(
                            resp,
                            feed_url,
                            headers=headers,
                            timeout=direct_fetch_timeout,
                        )
                        resp, effective_feed_url = _retry_cloudflare_challenged_wordpress_feed(
                            resp,
                            feed_url,
                            headers=headers,
                            timeout=direct_fetch_timeout,
                        )
                        if effective_feed_url != feed_url:
                            log.info("Resolved challenged local feed URL during refresh: %s -> %s", feed_url, effective_feed_url)
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
                        # Use content instead of text to let feedparser handle encoding detection
                        xml_data = resp.content
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
                        error_msg = f"HTTP {getattr(e.response, 'status_code', 'Error')}: {str(e)}"
                        failure_cooldown_seconds = _failure_cooldown_seconds_for_error(e)
                        retry_allowed = attempt <= configured_retries
                        fast_transport_retry = False
                        if (
                            not retry_allowed
                            and configured_retries == 0
                            and attempt < attempts
                            and _http_status_from_error(e) is None
                            and isinstance(
                                e,
                                (
                                    requests.exceptions.Timeout,
                                    requests.exceptions.ConnectTimeout,
                                    requests.exceptions.ReadTimeout,
                                    requests.exceptions.ConnectionError,
                                    requests.exceptions.ChunkedEncodingError,
                                ),
                            )
                        ):
                            retry_allowed = True
                            fast_transport_retry = True
                        if retry_allowed and _should_retry_refresh_error(e):
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
                            time.sleep(backoff)
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
                            time.sleep(0.01)
                            continue
                        raise last_exc

            if status == "not_modified":
                return
            if xml_data is None:
                return

            response_content_type = ""
            try:
                response_content_type = resp.headers.get("Content-Type", "")
            except Exception:
                response_content_type = ""
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
            if entry_count == 0 and not _response_looks_feed_like(resp):
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

            conn = get_connection()
            try:
                c = conn.cursor()
                c.execute("SELECT 1 FROM feeds WHERE id = ? LIMIT 1", (feed_id,))
                if not c.fetchone():
                    return
                
                final_title = d.feed.get('title', final_title)
                title_to_store = (
                    str(feed_title or "").strip() if bool(int(title_is_custom or 0)) and str(feed_title or "").strip() else final_title
                )
                if canonical_feed_url:
                    c.execute(
                        "UPDATE feeds SET url = ?, title = ?, etag = ?, last_modified = ? WHERE id = ?",
                        (canonical_feed_url, title_to_store, new_etag, new_last_modified, feed_id),
                    )
                else:
                    c.execute("UPDATE feeds SET title = ?, etag = ?, last_modified = ? WHERE id = ?",
                              (title_to_store, new_etag, new_last_modified, feed_id))
                
                # Pre-fetch existing articles to avoid N+1 SELECTs
                c.execute(
                    "SELECT id, date, chapter_url, media_url, media_type "
                    "FROM articles WHERE feed_id = ?",
                    (feed_id,),
                )
                existing_articles = {
                    row[0]: {
                        "date": row[1] or "",
                        "chapter_url": row[2],
                        "media_url": row[3],
                        "media_type": row[4],
                    }
                    for row in c.fetchall()
                }

                entry_ids = []
                for entry in d.entries:
                    content = _entry_content(entry)
                    base_id = _entry_base_id(entry, feed_id, feed_url, content)
                    if not base_id:
                        continue
                    scoped_id = f"{feed_id}:{base_id}"
                    if base_id in existing_articles or scoped_id in existing_articles:
                        continue
                    entry_ids.append(base_id)
                entry_ids = list(dict.fromkeys(entry_ids))
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
                for i, entry in enumerate(d.entries):
                    # Shared extension filters for enclosure/media tags
                    image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
                    audio_exts = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac")

                    content = _entry_content(entry)
                    base_id = _entry_base_id(entry, feed_id, feed_url, content)
                    if not base_id:
                        continue
                    scoped_id = f"{feed_id}:{base_id}"
                    article_id = base_id

                    url = _entry_primary_link(entry)
                    title = utils.enhance_activity_entry_title(entry.get('title', ''), url, content)
                    if not title or title.strip() == "No Title":
                         # Fallback: create title from content snippet (e.g. Bluesky/Mastodon)
                         snippet = content or ""
                         # Strip HTML
                         if snippet:
                             try:
                                 snippet = BS(snippet, "html.parser").get_text(" ", strip=True)
                             except Exception:
                                 pass
                         if len(snippet) > 80:
                             snippet = snippet[:80] + "..."
                         title = snippet or "No Title"
                    author = entry.get('author', 'Unknown')
                    
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
                            enc_href = getattr(enc, "href", None)
                            enc_type = getattr(enc, "type", "") or ""
                            if enc_href:
                                # Skip if it looks like an image and isn't explicitly audio/video type
                                if any(enc_href.lower().endswith(ext) for ext in image_exts):
                                    if not (enc_type.startswith("audio/") or enc_type.startswith("video/")):
                                        continue
                                valid_enclosure = enc
                                break
                        
                        if valid_enclosure:
                            enc_type = getattr(valid_enclosure, "type", "") or ""
                            enc_href = getattr(valid_enclosure, "href", None)
                            enc_type_norm = utils.canonical_media_type(enc_type) or enc_type
                            if utils.media_type_is_audio_video_or_podcast(enc_type_norm):
                                media_url = enc_href
                                media_type = enc_type_norm
                            elif enc_href and enc_href.lower().endswith(audio_exts):
                                media_url = enc_href
                                media_type = enc_type_norm or "audio/mpeg"

                    # 3. Check media:content (common in RSS 2.0 / MRSS)
                    if not media_url and 'media_content' in entry:
                        for mc in entry.media_content:
                            mc_url = mc.get('url')
                            mc_type = mc.get('type')
                            mc_type_norm = utils.canonical_media_type(mc_type) or mc_type
                            if mc_url:
                                # Skip thumbnails or images
                                if mc_type_norm and str(mc_type_norm).startswith('image/'):
                                    continue
                                if any(mc_url.lower().endswith(ext) for ext in image_exts):
                                    continue
                                
                                # Accept if audio/video or looks like audio
                                if utils.media_type_is_audio_video_or_podcast(mc_type_norm) or \
                                   mc_url.lower().endswith(audio_exts):
                                    media_url = mc_url
                                    media_type = mc_type_norm or "audio/mpeg"
                                    break

                    # 4. Check NPR-specific extraction if still no media. Do not
                    # retain an existing URL merely because the article already
                    # had media: removed enclosures must clear stale media. NPR is
                    # the explicit exception, and only after extraction confirms
                    # a currently working media URL.
                    if not media_url and npr_mod.is_npr_url(url):
                        media_url, media_type = npr_mod.extract_npr_audio(url, timeout_s=feed_timeout)

                    chapter_url = None
                    inline_chapters = []
                    if 'podcast_chapters' in entry:
                        chapters_tag = entry.podcast_chapters
                        chapter_url = getattr(chapters_tag, 'href', None) or getattr(chapters_tag, 'url', None) or getattr(chapters_tag, 'value', None)
                    if not chapter_url and 'psc_chapters' in entry:
                        chapters_tag = entry.psc_chapters
                        chapter_url = getattr(chapters_tag, 'href', None) or getattr(chapters_tag, 'url', None) or getattr(chapters_tag, 'value', None)

                    for key in (entry.get('guid'), entry.get('id'), _entry_primary_link(entry), base_id):
                        if not key or key not in chapter_metadata:
                            continue
                        raw_metadata = chapter_metadata[key]
                        if not chapter_url:
                            chapter_url = raw_metadata.get("chapter_url")
                        inline_chapters = raw_metadata.get("chapters") or []
                        break

                    if existing_article_id is not None:
                        c.execute(
                            "UPDATE articles SET date = ?, media_url = ?, media_type = ?, chapter_url = ? "
                            "WHERE id = ?",
                            (date, media_url, media_type, chapter_url, existing_article_id),
                        )
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
                        }
                        continue

                    try:
                        c.execute(
                            "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type, chapter_url) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                            (article_id, feed_id, title, url, content, date, author, media_url, media_type, chapter_url),
                        )
                        new_items += 1
                        _record_new_article(
                            article_id,
                            title,
                            author,
                            _preview_for_notification(content),
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
                        }
                    except sqlite3.IntegrityError as e:
                        if _rollback_and_abort_on_foreign_key(conn, e):
                            status = "deleted"
                            error_msg = None
                            return
                        if article_id == base_id:
                            try:
                                c.execute("SELECT feed_id, date FROM articles WHERE id = ? LIMIT 1", (base_id,))
                                row = c.fetchone()
                            except sqlite3.Error:
                                row = None

                            if row:
                                existing_feed_id = row[0]
                                if existing_feed_id == feed_id:
                                    c.execute(
                                        "UPDATE articles SET date = ?, media_url = ?, media_type = ?, "
                                        "chapter_url = ? WHERE id = ?",
                                        (date, media_url, media_type, chapter_url, base_id),
                                    )
                                    if inline_chapters:
                                        utils._replace_stored_chapters(
                                            base_id,
                                            inline_chapters,
                                            cursor=c,
                                        )
                                    continue

                                try:
                                    c.execute(
                                        "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type, chapter_url) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                                        (scoped_id, feed_id, title, url, content, date, author, media_url, media_type, chapter_url),
                                    )
                                    article_id = scoped_id
                                    new_items += 1
                                    _record_new_article(
                                        article_id,
                                        title,
                                        author,
                                        _preview_for_notification(content),
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
                                    }
                                except sqlite3.IntegrityError:
                                    continue
                            else:
                                raise
                        else:
                            continue

                # Commit once at the end
                conn.commit()
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
            elif status == "error":
                self._set_refresh_failure_cooldown(
                    feed_id,
                    failure_cooldown_seconds or _TRANSIENT_FAILURE_COOLDOWN_SECONDS,
                    error_msg,
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

    def _collect_feed_state(self, feed_id, title, category, status, new_items, error_msg, new_articles=None):
        unread = 0
        conn = None
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
            "category": category or "Uncategorized",
            "unread_count": unread,
            "status": status,
            "new_items": new_items,
            "new_articles": list(new_articles or []),
            "error": error_msg,
        }

    def _emit_progress(self, progress_cb, state):
        if progress_cb is None:
            return
        try:
            progress_cb(state)
        except Exception as e:
            log.debug(f"Progress callback failed: {e}")

    def get_feeds(self) -> List[Feed]:
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT id, title, url, category, icon_url FROM feeds")
            rows = c.fetchall()

            c.execute("SELECT feed_id, COUNT(*) FROM articles WHERE is_read = 0 GROUP BY feed_id")
            unread_map = {row[0]: row[1] for row in c.fetchall()}
            
            feeds = []
            for row in rows:
                f = Feed(id=row[0], title=row[1], url=row[2], category=row[3], icon_url=row[4])
                f.unread_count = unread_map.get(f.id, 0)
                feeds.append(f)
            return feeds
        finally:
            conn.close()

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

    def get_articles(self, feed_id: str) -> List[Article]:
        conn = get_connection()
        try:
            c = conn.cursor()
            
            # Determine filters
            real_feed_id, filter_read, filter_favorite = self._parse_article_view_filters(feed_id)

            sql_parts = ["SELECT id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type FROM articles"]
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
                    SELECT a.id, a.feed_id, a.title, a.url, a.content, a.date, a.author, a.is_read, a.is_favorite, a.media_url, a.media_type
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                """]
                placeholders = ",".join("?" for _ in cat_names)
                where_clauses.append(f"f.category IN ({placeholders})")
                params.extend(cat_names)
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
                    is_favorite=bool(row[8]), media_url=row[9], media_type=row[10], chapters=chs
                ))
            return articles
        finally:
            conn.close()


    def get_articles_page(self, feed_id: str, offset: int = 0, limit: int = 200):
        """Fetch a single page of articles from the local SQLite DB (fast-first loading)."""
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
                placeholders = ",".join("?" for _ in cat_names)
                count_where.append(f"f.category IN ({placeholders})")
                count_params.extend(cat_names)
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
            sql_parts = ["SELECT id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type FROM articles"]
            where_clauses = []
            params = []

            if is_category:
                sql_parts = ["""
                    SELECT a.id, a.feed_id, a.title, a.url, a.content, a.date, a.author, a.is_read, a.is_favorite, a.media_url, a.media_type
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                """]
                placeholders = ",".join("?" for _ in cat_names)
                where_clauses.append(f"f.category IN ({placeholders})")
                params.extend(cat_names)
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
                    chapters=chapters
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
                "SELECT id, feed_id, title, url, content, date, author, is_read, is_favorite, media_url, media_type "
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
                placeholders = ",".join("?" for _ in all_cats)
                where_clauses.append(f"feed_id IN (SELECT id FROM feeds WHERE category IN ({placeholders}))")
                params.extend(all_cats)
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

    def delete_article(self, article_id: str) -> bool:
        if not article_id:
            return False
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("DELETE FROM chapters WHERE article_id = ?", (article_id,))
            local_cache_key = f"local:{article_id}"
            c.execute("DELETE FROM chapter_cache WHERE cache_key = ?", (local_cache_key,))
            c.execute("DELETE FROM chapter_sources WHERE cache_key = ?", (local_cache_key,))
            c.execute("DELETE FROM articles WHERE id = ?", (article_id,))
            deleted = int(c.rowcount or 0)
            conn.commit()
            return deleted > 0
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

    def add_feed(self, url: str, category: str = "Uncategorized") -> bool:
        real_url = self._resolve_feed_url(url)
        
        title = real_url
        try:
            from core import discovery as _disc
            if _disc.is_youtube_search_url(real_url):
                q = _disc.youtube_search_query(real_url) or real_url
                title = f"YouTube: {q}"
            elif rumble_mod.is_rumble_url(real_url) and not real_url.lower().endswith((".xml", ".rss", ".atom")):
                page_title, _items = rumble_mod.fetch_listing_items(real_url, timeout_s=10.0)
                title = page_title or real_url
            elif odysee_mod.is_odysee_url(real_url) and not real_url.lower().endswith((".xml", ".rss", ".atom")):
                page_title, _items = odysee_mod.fetch_listing_items(real_url, max_items=1, timeout_s=10.0)
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
            c.execute("INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
                      (feed_id, real_url, title, category, ""))
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
            c.execute(
                "UPDATE feeds SET title_is_custom = 0, etag = NULL, last_modified = NULL WHERE id = ?",
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
                            if not title or title == "Uncategorized":
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
                            if path == "Uncategorized":
                                path = ""
                            for raw_part in str(folder_title or "").split(CATEGORY_PATH_SEP):
                                leaf = sanitize_category_leaf(raw_part)
                                if leaf:
                                    path = make_category_path(path, leaf)
                            return path or "Uncategorized"

                        # Make sure target category exists if used.
                        if target_category and target_category != "Uncategorized":
                            target_category = ensure_category_path(target_category) or target_category
                        base_category = target_category if target_category else "Uncategorized"

                        def process_outline(outline, current_category="Uncategorized"):
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
                                    cat_to_use = current_category or "Uncategorized"

                                    if cat_to_use and cat_to_use != "Uncategorized":
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
                                    if new_cat and new_cat != "Uncategorized":
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

    def delete_category(self, title: str) -> bool:
        # `title` is the full path. Direct children are reparented to the deleted
        # node's parent, which shortens their paths; descendant paths and the
        # feeds assigned to them are rewritten to match.
        from core.db import CATEGORY_PATH_SEP
        path = (title or "").strip()
        if path.lower() == "uncategorized":
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
                    c.execute("UPDATE feeds SET category = 'Uncategorized' WHERE category = ?", (sp,))
                    c.execute("DELETE FROM categories WHERE title = ?", (sp,))
                conn.commit()
                return True

            # Reparent direct children (parent_id is by id, so deeper links hold).
            c.execute("UPDATE categories SET parent_id = ? WHERE parent_id = ?", (cat_parent_id, cat_id))
            for old_p, new_p in mapping:
                c.execute("UPDATE categories SET title = ? WHERE title = ?", (new_p, old_p))
                c.execute("UPDATE feeds SET category = ? WHERE category = ?", (new_p, old_p))
            # Feeds directly in the deleted category fall back to Uncategorized.
            c.execute("UPDATE feeds SET category = 'Uncategorized' WHERE category = ?", (path,))
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
                "SELECT media_url, media_type, chapter_url FROM articles WHERE id = ? LIMIT 1",
                (article_id,),
            )
            row = c.fetchone()
        finally:
            conn.close()

        if not row:
            return []

        media_url, media_type, chapter_url = row
        return utils.fetch_and_store_chapters(article_id, media_url, media_type, chapter_url=chapter_url)
