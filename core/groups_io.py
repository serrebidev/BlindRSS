# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Groups.io feed discovery, search subscriptions, and complete topic rendering.

Public groups and topics work without credentials.  When the user supplies a
Groups.io API key, topic reconstruction prefers the official cursor-paginated
API so member-only archives and very large topics can be read reliably.  The
key is read from the local config at request time and is never logged.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from core import config as config_mod
from core import utils

log = logging.getLogger(__name__)

_GROUP_PATH_RE = re.compile(r"^/g/(?P<group>[^/]+)(?:/(?P<section>topics|messages|rss))?/?$", re.I)
_SEARCH_PATH_RE = re.compile(r"^/g/(?P<group>[^/]+)/search/?$", re.I)
_TOPIC_PATH_RE = re.compile(
    r"^/g/(?P<group>[^/]+)/topic/(?:[^/?#]+/)?(?P<topic_id>[0-9]+)/?$", re.I
)
_MESSAGE_PATH_RE = re.compile(r"^/g/(?P<group>[^/]+)/message/(?P<message_id>[0-9]+)/?$", re.I)
_DISPLAY_TIME_RE = re.compile(r"DisplayShortTime\s*\(\s*([0-9]{10,})", re.I)
_MAX_TOPIC_MESSAGES = 10_000
_MAX_API_REQUESTS = 200
_MAX_HTML_PAGES = 500


@dataclass(frozen=True)
class GroupsIOItem:
    id: str
    url: str
    title: str
    author: str = ""
    published: str = ""
    content: str = ""


def is_groups_io_url(url: str) -> bool:
    try:
        host = (urlsplit(str(url or "")).hostname or "").lower()
    except Exception:
        return False
    return host == "groups.io" or host.endswith(".groups.io")


def _parts(url: str):
    try:
        parts = urlsplit(str(url or "").strip())
    except Exception:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc or not is_groups_io_url(url):
        return None
    return parts


def is_group_search_url(url: str) -> bool:
    parts = _parts(url)
    return bool(parts and _SEARCH_PATH_RE.match(parts.path or ""))


def topic_parts(url: str) -> Optional[tuple[str, str, int]]:
    parts = _parts(url)
    if not parts:
        return None
    match = _TOPIC_PATH_RE.match(parts.path or "")
    if not match:
        return None
    return parts.netloc, match.group("group"), int(match.group("topic_id"))


def message_parts(url: str) -> Optional[tuple[str, str, int]]:
    parts = _parts(url)
    if not parts:
        return None
    match = _MESSAGE_PATH_RE.match(parts.path or "")
    if not match:
        return None
    return parts.netloc, match.group("group"), int(match.group("message_id"))


def is_thread_url(url: str) -> bool:
    return topic_parts(url) is not None or message_parts(url) is not None


def group_feed_url(url: str) -> Optional[str]:
    """Return a group's native RSS URL for a group landing/listing URL."""
    parts = _parts(url)
    if not parts:
        return None
    match = _GROUP_PATH_RE.match(parts.path or "") or _SEARCH_PATH_RE.match(parts.path or "")
    if not match:
        return None
    group = match.group("group")
    return f"https://{parts.netloc}/g/{quote(group, safe='')}/rss"


def search_query(url: str) -> str:
    if not is_group_search_url(url):
        return ""
    try:
        return str((parse_qs(urlsplit(url).query).get("q") or [""])[0]).strip()
    except Exception:
        return ""


def _request(url: str, *, timeout: float = 20, headers: Optional[dict] = None):
    try:
        from core import site_cookies

        site_cookies.refresh_groups_io_cookies_from_browsers(url)
    except Exception:
        log.debug("Groups.io browser-cookie refresh failed", exc_info=True)
    return utils.safe_requests_get(url, timeout=timeout, headers=headers or {}, allow_redirects=True)


def search_groups_io_feeds(term: str, *, limit: int = 20, timeout: float = 15) -> list[dict]:
    """Search the public Groups.io directory and return native group RSS feeds."""
    term = str(term or "").strip()
    if not term:
        return []
    response = _request(
        "https://groups.io/search?" + urlencode({"q": term}),
        timeout=timeout,
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text or "", "html.parser")
    results = []
    seen = set()
    for row in soup.select("tr"):
        anchor = row.select_one('a[href*="/g/"]')
        if anchor is None:
            continue
        group_url = urljoin(str(getattr(response, "url", "") or "https://groups.io/search"), anchor.get("href", ""))
        feed_url = group_feed_url(group_url)
        if not feed_url or feed_url in seen:
            continue
        seen.add(feed_url)
        title = anchor.get_text(" ", strip=True) or urlsplit(feed_url).path.split("/")[-2]
        detail = " ".join(row.get_text(" ", strip=True).split())
        if detail.lower().startswith(title.lower()):
            detail = detail[len(title):].strip(" -–—")
        results.append({"title": title, "detail": detail or "Groups.io group", "url": feed_url})
        if len(results) >= max(1, min(int(limit or 20), 100)):
            break
    return results


def _display_time(node) -> str:
    for script in node.select("script"):
        match = _DISPLAY_TIME_RE.search(script.get_text(" ", strip=False) or "")
        if not match:
            continue
        try:
            # Groups.io uses Unix nanoseconds.
            return datetime.fromtimestamp(int(match.group(1)) / 1_000_000_000, timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            continue
    return ""


def _canonical_topic_url(url: str) -> str:
    parts = urlsplit(url)
    match = _TOPIC_PATH_RE.match(parts.path or "")
    if match:
        path = f"/g/{match.group('group')}/topic/{match.group('topic_id')}"
        return urlunsplit(("https", parts.netloc, path, "", ""))
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))


def fetch_search_items(url: str, *, max_items: int = 100, timeout: float = 20) -> tuple[str, list[GroupsIOItem]]:
    """Enumerate a Groups.io archive-search URL, following all result pages."""
    if not is_group_search_url(url):
        raise ValueError("Not a Groups.io group search URL")
    limit = max(1, min(int(max_items or 100), 1000))
    next_url = str(url)
    visited = set()
    items = []
    title = ""
    while next_url and next_url not in visited and len(visited) < _MAX_HTML_PAGES and len(items) < limit:
        visited.add(next_url)
        response = _request(next_url, timeout=timeout, headers={"Accept": "text/html,application/xhtml+xml"})
        response.raise_for_status()
        page_url = str(getattr(response, "url", "") or next_url)
        soup = BeautifulSoup(response.text or "", "html.parser")
        if not title:
            group = _SEARCH_PATH_RE.match(urlsplit(page_url).path or "")
            group_name = group.group("group") if group else "Groups.io"
            q = search_query(url)
            title = f"{group_name} search: {q}" if q else f"{group_name} search"
        for cell in soup.select("td[id]"):
            subject = cell.select_one(".subject a") or cell.select_one('a[href*="/topic/"]')
            if subject is None:
                continue
            topic_url = _canonical_topic_url(urljoin(page_url, subject.get("href", "")))
            if topic_parts(topic_url) is None or any(item.url == topic_url for item in items):
                continue
            item_title = subject.get_text(" ", strip=True) or "Groups.io topic"
            snippet_node = cell.select_one(".truncate-two-lines")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            author_node = cell.select_one(".user-chip-name")
            author = author_node.get_text(" ", strip=True) if author_node else ""
            topic_id = str(topic_parts(topic_url)[2])
            items.append(GroupsIOItem(topic_id, topic_url, item_title, author, _display_time(cell), snippet))
            if len(items) >= limit:
                break
        next_anchor = None
        for anchor in soup.select("a[href]"):
            label = " ".join(anchor.get_text(" ", strip=True).lower().split())
            if label in ("next", "next page", "older") or anchor.get("rel") == ["next"]:
                next_anchor = anchor
                break
        next_url = urljoin(page_url, next_anchor.get("href", "")) if next_anchor is not None else ""
    return title or "Groups.io search", items


def _api_key() -> str:
    value = str(os.environ.get("BLINDRSS_GROUPS_IO_API_KEY", "") or "").strip()
    if value:
        return value
    try:
        with open(config_mod.CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return str(data.get("groups_io_api_key", "") or "").strip() if isinstance(data, dict) else ""
    except (OSError, ValueError, TypeError):
        return ""


def _unwrap_api_payload(payload):
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        # extended=true returns [user, requested object].  Identify the list
        # object by structure rather than position because API is still alpha.
        for item in reversed(payload):
            if isinstance(item, dict) and (item.get("object") == "list" or "data" in item or "messages" in item or "next_page_token" in item or "total_count" in item):
                return item
    return {}


def _api_topic(topic_id: int, *, timeout: float = 20) -> Optional[dict]:
    key = _api_key()
    if not key:
        return None
    messages = []
    token = ""
    topic = {}
    for request_no in range(_MAX_API_REQUESTS):
        params = {"topic_id": str(int(topic_id)), "limit": "100"}
        if token:
            params["page_token"] = token
        response = utils.safe_requests_get(
            "https://groups.io/api/v1/gettopic?" + urlencode(params),
            timeout=timeout,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            allow_redirects=True,
        )
        if response.status_code == 429:
            if request_no >= 5:
                response.raise_for_status()
            time.sleep(min(8.0, 0.5 * (2 ** request_no)))
            continue
        response.raise_for_status()
        page = _unwrap_api_payload(response.json())
        if not page:
            return None
        if not topic:
            topic = dict(page)
        page_messages = page.get("data") or page.get("messages") or []
        if isinstance(page_messages, list):
            messages.extend(m for m in page_messages if isinstance(m, dict))
        if len(messages) >= _MAX_TOPIC_MESSAGES:
            break
        new_token = str(page.get("next_page_token") or "").strip()
        if not new_token or new_token == token:
            break
        token = new_token
    if not messages:
        return None
    topic["messages"] = messages[:_MAX_TOPIC_MESSAGES]
    return topic


def _clean_message_body(raw: str, *, plain: bool = False) -> str:
    if plain:
        return "<p>" + html.escape(str(raw or "")).replace("\n", "<br>\n") + "</p>"
    soup = BeautifulSoup(str(raw or ""), "html.parser")
    body = soup.body or soup
    for tag in body.select("script, style, iframe, object, embed, form, input, button"):
        tag.decompose()
    return "".join(str(child) for child in body.contents).strip()


def _message_timestamp(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000_000:
            number /= 1_000_000_000
        elif number > 10_000_000_000:
            number /= 1000
        try:
            return datetime.fromtimestamp(number, timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return ""
    return str(value or "").strip()


def _render_document(title: str, messages: list[dict], canonical_url: str) -> str:
    sections = []
    seen = set()
    for index, message in enumerate(messages, 1):
        number = str(message.get("msg_num") or message.get("number") or index)
        if number in seen:
            continue
        seen.add(number)
        author = str(message.get("name") or message.get("author") or "Unknown author").strip()
        created = _message_timestamp(message.get("created") or message.get("published"))
        heading = f"#{index} Message by {author}"
        if created:
            heading += f" — {created}"
        if number:
            heading += f" — Message #{number}"
        body = _clean_message_body(message.get("body") or "", plain=bool(message.get("is_plain_text")))
        attachment_links = []
        for attachment in message.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            href = str(attachment.get("download_url") or attachment.get("url") or "").strip()
            label = str(attachment.get("name") or attachment.get("filename") or "Attachment").strip()
            if href:
                attachment_links.append(f'<p><a href="{html.escape(href, quote=True)}">{html.escape(label)}</a></p>')
        sections.append(
            '<section class="blindrss-groupsio-post">'
            f"<h2>{html.escape(heading)}</h2>"
            f'<div class="blindrss-groupsio-body">{body}{"".join(attachment_links)}</div>'
            "</section>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title or 'Groups.io topic')}</title></head><body>"
        f"<h1>{html.escape(title or 'Groups.io topic')}</h1>"
        f'<p><a href="{html.escape(canonical_url, quote=True)}">Open topic on Groups.io</a></p>'
        + "".join(sections)
        + "</body></html>"
    )


def _topic_url_from_message(url: str, *, timeout: float) -> str:
    response = _request(url, timeout=timeout, headers={"Accept": "text/html,application/xhtml+xml"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text or "", "html.parser")
    for anchor in soup.select('a[href*="/topic/"]'):
        candidate = _canonical_topic_url(urljoin(str(getattr(response, "url", "") or url), anchor.get("href", "")))
        if topic_parts(candidate):
            return candidate
    return ""


def _html_topic(url: str, *, timeout: float = 20) -> tuple[str, list[dict]]:
    next_url = url
    visited = set()
    messages = []
    title = ""
    while next_url and next_url not in visited and len(visited) < _MAX_HTML_PAGES and len(messages) < _MAX_TOPIC_MESSAGES:
        visited.add(next_url)
        response = _request(next_url, timeout=timeout, headers={"Accept": "text/html,application/xhtml+xml"})
        response.raise_for_status()
        page_url = str(getattr(response, "url", "") or next_url)
        soup = BeautifulSoup(response.text or "", "html.parser")
        if not title:
            heading = soup.select_one("h1")
            title = heading.get_text(" ", strip=True) if heading else ""
            if not title and soup.title:
                title = soup.title.get_text(" ", strip=True).split(" | ", 1)[0].strip()
        for block in soup.select(".expanded-message"):
            permalink = block.select_one('a.hidden-xs[href*="/message/"]') or block.select_one('a[href*="/message/"]')
            number = ""
            if permalink is not None:
                match = _MESSAGE_PATH_RE.match(urlsplit(urljoin(page_url, permalink.get("href", ""))).path or "")
                number = match.group("message_id") if match else permalink.get_text(" ", strip=True).lstrip("#")
            author_node = block.select_one(".user-chip-name")
            body_node = block.select_one(".user-content")
            if body_node is None:
                continue
            messages.append({
                "msg_num": number or len(messages) + 1,
                "name": author_node.get_text(" ", strip=True) if author_node else "Unknown author",
                "created": _display_time(block),
                "body": str(body_node),
            })
        next_anchor = None
        for anchor in soup.select("a[href]"):
            if " ".join(anchor.get_text(" ", strip=True).lower().split()) == "next page":
                next_anchor = anchor
                break
        next_url = urljoin(page_url, next_anchor.get("href", "")) if next_anchor is not None else ""
    return title or "Groups.io topic", messages


def download_thread_html(url: str, *, timeout: float = 20) -> str:
    """Return one semantic HTML document containing every available message."""
    parsed_topic = topic_parts(url)
    if parsed_topic is None and message_parts(url) is not None:
        resolved = _topic_url_from_message(url, timeout=timeout)
        parsed_topic = topic_parts(resolved)
        if parsed_topic is None:
            return ""
        url = resolved
    if parsed_topic is None:
        return ""
    host, group, topic_id = parsed_topic
    canonical = f"https://{host}/g/{quote(group, safe='')}/topic/{topic_id}"
    try:
        topic = _api_topic(topic_id, timeout=timeout)
    except Exception:
        log.info("Groups.io API topic fetch failed; using public HTML fallback", exc_info=True)
        topic = None
    if topic:
        messages = topic.get("messages") or []
        title = str(topic.get("subject") or topic.get("title") or "").strip()
        if not title and messages:
            title = str(messages[0].get("subject") or "").strip()
        return _render_document(title or "Groups.io topic", messages, canonical)
    try:
        title, messages = _html_topic(canonical, timeout=timeout)
    except Exception:
        log.debug("Groups.io HTML topic fetch failed", exc_info=True)
        return ""
    return _render_document(title, messages, canonical) if messages else ""
