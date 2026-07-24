# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Synthetic feeds and complete-thread readers for web discussion services.

Google Groups no longer publishes RSS, so its group landing page is treated as
a local synthetic subscription.  Google Help Communities embed their thread
data in the page, and Discourse exposes a public JSON topic endpoint.  This
module turns all three into the same small, semantic HTML vocabulary consumed
by BlindRSS's classic and rich readers.
"""

from __future__ import annotations

import ast
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from core import utils
from core.i18n import _


_GOOGLE_GROUP_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_GOOGLE_GROUP_EMAIL_RE = re.compile(
    r"^(?:mailto:)?(?P<group>[A-Za-z0-9_.-]+)@googlegroups\.com$", re.I
)
_GOOGLE_GROUP_PATH_RE = re.compile(r"^/g/(?P<group>[^/]+)/?$", re.I)
_GOOGLE_GROUP_THREAD_RE = re.compile(
    r"^/g/(?P<group>[^/]+)/c/(?P<conversation>[A-Za-z0-9_-]+)(?:/m/(?P<message>[A-Za-z0-9_-]+))?/?$",
    re.I,
)
_GOOGLE_SUPPORT_THREAD_RE = re.compile(
    r"^/(?P<product>[A-Za-z0-9_-]+)/thread/(?P<thread_id>[0-9]+)(?:/[^/?#]+)?/?$",
    re.I,
)
_DISCOURSE_TOPIC_RE = re.compile(
    r"^/t/(?:[^/]+/)?(?P<topic_id>[0-9]+)(?:/(?P<post_number>[0-9]+))?/?$",
    re.I,
)
_THREAD_VIEW_RE = re.compile(r"\bvar\s+thread_view='((?:\\.|[^'])*)';", re.S)
_MAX_DISCOURSE_POSTS = 10_000
_DISCOURSE_POST_BATCH = 100


@dataclass(frozen=True)
class ForumFeedItem:
    id: str
    url: str
    title: str
    author: str = ""
    published: str = ""
    content: str = ""


def normalize_google_groups_url(value: str) -> Optional[str]:
    """Canonicalize a Google Groups email, current URL, or legacy hash URL."""
    text = str(value or "").strip().strip("<>").strip("`")
    email_match = _GOOGLE_GROUP_EMAIL_RE.fullmatch(text)
    if email_match:
        group = email_match.group("group")
        return f"https://groups.google.com/g/{quote(group, safe='._-')}"

    try:
        parts = urlsplit(text)
    except Exception:
        return None
    if (parts.scheme or "").lower() not in ("http", "https"):
        return None
    if (parts.hostname or "").lower() != "groups.google.com":
        return None

    fragment = unquote(parts.fragment or "")
    legacy_group = re.fullmatch(r"!forum/([A-Za-z0-9_.-]+)", fragment, re.I)
    if legacy_group:
        return f"https://groups.google.com/g/{quote(legacy_group.group(1), safe='._-')}"
    legacy_topic = re.fullmatch(
        r"!topic/([A-Za-z0-9_.-]+)/([A-Za-z0-9_-]+)", fragment, re.I
    )
    if legacy_topic:
        return (
            "https://groups.google.com/g/"
            f"{quote(legacy_topic.group(1), safe='._-')}/c/{legacy_topic.group(2)}"
        )

    group_match = _GOOGLE_GROUP_PATH_RE.fullmatch(parts.path or "")
    if group_match:
        group = unquote(group_match.group("group")).strip()
        if _GOOGLE_GROUP_NAME_RE.fullmatch(group):
            return f"https://groups.google.com/g/{quote(group, safe='._-')}"

    thread_match = _GOOGLE_GROUP_THREAD_RE.fullmatch(parts.path or "")
    if thread_match:
        group = unquote(thread_match.group("group")).strip()
        if not _GOOGLE_GROUP_NAME_RE.fullmatch(group):
            return None
        path = (
            f"/g/{quote(group, safe='._-')}/c/"
            f"{thread_match.group('conversation')}"
        )
        if thread_match.group("message"):
            path += f"/m/{thread_match.group('message')}"
        return f"https://groups.google.com{path}"
    return None


def google_group_subscription_url(value: str) -> Optional[str]:
    """Return a canonical synthetic-subscription URL, excluding thread URLs."""
    canonical = normalize_google_groups_url(value)
    if canonical and _GOOGLE_GROUP_PATH_RE.fullmatch(urlsplit(canonical).path or ""):
        return canonical
    return None


def is_google_group_url(value: str) -> bool:
    return google_group_subscription_url(value) is not None


def is_google_groups_thread_url(value: str) -> bool:
    canonical = normalize_google_groups_url(value)
    return bool(canonical and _GOOGLE_GROUP_THREAD_RE.fullmatch(urlsplit(canonical).path or ""))


def _google_request(url: str, *, timeout: float = 20):
    return utils.safe_requests_get(
        url,
        timeout=max(1.0, float(timeout or 20)),
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
        allow_redirects=True,
    )


def _google_groups_permission_denied(soup: BeautifulSoup, response_url: str = "") -> bool:
    text = " ".join(soup.get_text(" ", strip=True).lower().split())
    return (
        "you don't have permission to access this content" in text
        or "you don’t have permission to access this content" in text
        or "/access-error" in str(response_url or "")
    )


def fetch_google_group_items(
    url: str, *, max_items: int = 30, timeout: float = 20
) -> tuple[str, list[ForumFeedItem]]:
    """Read the newest server-rendered conversations from a Google Group."""
    canonical = google_group_subscription_url(url)
    if not canonical:
        raise ValueError("Not a Google Groups group address")
    response = _google_request(canonical + "?hl=en", timeout=timeout)
    response.raise_for_status()
    response_url = str(getattr(response, "url", "") or canonical)
    soup = BeautifulSoup(response.text or "", "html.parser")
    if _google_groups_permission_denied(soup, response_url):
        raise PermissionError(
            _(
                "This Google Group requires sign-in. Import its browser cookies with "
                "Tools > Import Site Cookies, then refresh the feed."
            )
        )

    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    page_title = re.sub(r"\s+-\s+Google Groups\s*$", "", page_title).strip()
    group_name = unquote(_GOOGLE_GROUP_PATH_RE.fullmatch(urlsplit(canonical).path).group("group"))
    title = page_title or group_name
    limit = max(1, min(int(max_items or 30), 100))
    items: list[ForumFeedItem] = []
    seen: set[str] = set()
    for row in soup.select("[data-rowid]"):
        conversation_id = str(row.get("data-rowid") or "").strip()
        if not conversation_id or conversation_id in seen:
            continue
        subject_anchor = row.select_one('a[href*="/c/"] .o1DPKc')
        subject_anchor = subject_anchor.find_parent("a") if subject_anchor is not None else None
        if subject_anchor is None:
            for anchor in row.select('a[href*="/c/"]'):
                if anchor.select_one(".t17a0d") is not None:
                    subject_anchor = anchor
                    break
        if subject_anchor is None:
            continue
        subject_node = subject_anchor.select_one(".o1DPKc") or subject_anchor.select_one(".t17a0d")
        item_title = subject_node.get_text(" ", strip=True) if subject_node else ""
        if not item_title:
            item_title = str(row.get("aria-label") or "").removeprefix("Select ").strip()
        if not item_title:
            continue
        # Google emits ``./g/name/c/id``. Resolve that against the site root;
        # resolving it against ``/g/name/`` would duplicate the group path.
        item_url = urljoin("https://groups.google.com/", str(subject_anchor.get("href") or ""))
        canonical_item = normalize_google_groups_url(item_url)
        if not canonical_item or not is_google_groups_thread_url(canonical_item):
            continue
        authors = []
        for node in row.select(".z0zUgf"):
            name = node.get_text(" ", strip=True)
            if name and name not in authors:
                authors.append(name)
        published_node = row.select_one(".tRlaM")
        snippet_node = row.select_one(".WzoK")
        seen.add(conversation_id)
        items.append(
            ForumFeedItem(
                id=conversation_id,
                url=canonical_item,
                title=item_title,
                author=", ".join(authors),
                published=published_node.get_text(" ", strip=True) if published_node else "",
                content=snippet_node.get_text(" ", strip=True) if snippet_node else "",
            )
        )
        if len(items) >= limit:
            break
    return title, items


def _clean_post_html(raw: object, *, drop_quotes: bool = False) -> str:
    soup = BeautifulSoup(str(raw or ""), "html.parser")
    root = soup.body or soup
    selectors = ["script", "style", "iframe", "object", "embed", "form", "input", "button"]
    if drop_quotes:
        selectors.extend((".gmail_quote", ".wqmMgb"))
    for selector in selectors:
        for node in root.select(selector):
            node.decompose()
    return "".join(str(child) for child in root.contents).strip()


def _render_thread_document(
    title: str,
    posts: list[dict],
    canonical_url: str,
    *,
    source_label: str,
    css_prefix: str,
) -> str:
    sections = []
    seen = set()
    for fallback_number, post in enumerate(posts, 1):
        identity = str(post.get("id") or fallback_number)
        if identity in seen:
            continue
        seen.add(identity)
        number = str(post.get("number") or fallback_number)
        role = "Posted" if fallback_number == 1 else "Message"
        author = str(post.get("author") or "Unknown author").strip() or "Unknown author"
        heading = f"#{number} {role} by {author}"
        created = str(post.get("created") or "").strip()
        if created:
            heading += f" — {created}"
        reply_to = str(post.get("reply_to") or "").strip()
        if reply_to:
            heading += f" — Reply to #{reply_to}"
        body = str(post.get("body") or "").strip() or "<p>[no text available]</p>"
        sections.append(
            f'<section class="blindrss-{css_prefix}-post">'
            f"<h2>{html.escape(heading)}</h2>"
            f'<div class="blindrss-{css_prefix}-body">{body}</div>'
            "</section>"
        )
    if not sections:
        return ""
    safe_title = html.escape(str(title or f"{source_label} thread").strip())
    safe_url = html.escape(canonical_url, quote=True)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<title>{safe_title}</title></head><body>"
        f"<h1>{safe_title}</h1>"
        f'<p><a href="{safe_url}">Open thread on {html.escape(source_label)}</a></p>'
        + "".join(sections)
        + "</body></html>"
    )


def download_google_groups_thread_html(url: str, *, timeout: float = 20) -> str:
    """Return the server-rendered messages from a Google Groups conversation."""
    canonical = normalize_google_groups_url(url)
    if not canonical or not is_google_groups_thread_url(canonical):
        return ""
    response = _google_request(canonical + "?hl=en", timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text or "", "html.parser")
    if _google_groups_permission_denied(soup, str(getattr(response, "url", "") or canonical)):
        return ""
    title = soup.title.get_text(" ", strip=True) if soup.title else "Google Groups conversation"
    title = re.sub(r"\s+-\s+Google Groups\s*$", "", title).strip()
    posts = []
    for block in soup.select("div.eH2Xlc"):
        body_node = block.select_one('[role="region"][aria-labelledby]') or block.select_one(".ptW7te")
        if body_node is None:
            continue
        header = block.select_one("h3")
        date_node = block.select_one(".zX2W9c") or block.select_one("time")
        id_node = block.select_one("[data-message-id]")
        body = _clean_post_html(str(body_node), drop_quotes=True)
        if not body:
            continue
        posts.append(
            {
                "id": str(id_node.get("data-message-id") or "") if id_node else "",
                "number": len(posts) + 1,
                "author": header.get_text(" ", strip=True) if header else "Unknown author",
                "created": date_node.get_text(" ", strip=True) if date_node else "",
                "body": body,
            }
        )
    return _render_thread_document(
        title, posts, canonical, source_label="Google Groups", css_prefix="googlegroups"
    )


def is_google_support_thread_url(url: str) -> bool:
    try:
        parts = urlsplit(str(url or "").strip())
    except Exception:
        return False
    return bool(
        (parts.scheme or "").lower() in ("http", "https")
        and (parts.hostname or "").lower() == "support.google.com"
        and _GOOGLE_SUPPORT_THREAD_RE.fullmatch(parts.path or "")
    )


def _decode_thread_view(page_html: str):
    match = _THREAD_VIEW_RE.search(str(page_html or ""))
    if not match:
        return None
    try:
        # literal_eval decodes the JavaScript string's \xNN/\uNNNN escapes while
        # preserving real non-ASCII characters; the result itself is JSON.
        decoded = ast.literal_eval("'" + match.group(1) + "'")
        data = json.loads(decoded)
    except (SyntaxError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, list) else None


def _nested(value, *indexes, default=None):
    current = value
    try:
        for index in indexes:
            current = current[index]
        return current
    except (IndexError, KeyError, TypeError):
        return default


def _timestamp_label(value: object) -> str:
    try:
        number = float(value or 0)
        if number > 10_000_000_000_000:
            number /= 1_000_000
        elif number > 10_000_000_000:
            number /= 1000
        if number > 0:
            return datetime.fromtimestamp(number, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OSError, OverflowError, TypeError, ValueError):
        pass
    return ""


def google_support_thread_document(page_html: str, url: str) -> str:
    """Decode a Google Help Community's embedded complete conversation."""
    data = _decode_thread_view(page_html)
    topic = _nested(data, 1)
    if not isinstance(topic, list):
        return ""
    title = str(_nested(topic, 8, default="") or "Google Support thread").strip()
    body = _clean_post_html(_nested(topic, 12, default=""))
    author = str(_nested(data, 3, 0, 0, default="") or "Unknown author").strip()
    posts = [
        {
            "id": str(_nested(topic, 0, 0, default="") or "1"),
            "number": 1,
            "author": author,
            "created": _timestamp_label(_nested(topic, 0, 1, default=0)),
            "body": body,
        }
    ]
    replies = _nested(data, 39, 0, default=[])
    if isinstance(replies, list):
        for wrapper in replies:
            post = _nested(wrapper, 0)
            if not isinstance(post, list):
                continue
            reply_body = _clean_post_html(_nested(post, 3, default=""))
            if not reply_body:
                continue
            posts.append(
                {
                    "id": str(_nested(post, 0, 0, default="") or len(posts) + 1),
                    "number": len(posts) + 1,
                    "author": str(
                        _nested(wrapper, 2, 0, 0, default="") or "Unknown author"
                    ).strip(),
                    "created": _timestamp_label(_nested(post, 0, 1, default=0)),
                    "body": reply_body,
                }
            )
    return _render_thread_document(
        title, posts, url, source_label="Google Support", css_prefix="googlesupport"
    )


def download_google_support_thread_html(url: str, *, timeout: float = 20) -> str:
    if not is_google_support_thread_url(url):
        return ""
    response = _google_request(url, timeout=timeout)
    response.raise_for_status()
    return google_support_thread_document(response.text or "", str(getattr(response, "url", "") or url))


def discourse_topic_parts(url: str) -> Optional[tuple[str, int]]:
    """Return ``(origin, topic id)`` for a possible Discourse topic URL."""
    try:
        parts = urlsplit(str(url or "").strip())
    except Exception:
        return None
    if (parts.scheme or "").lower() not in ("http", "https") or not parts.netloc:
        return None
    match = _DISCOURSE_TOPIC_RE.fullmatch(parts.path or "")
    if not match:
        return None
    return f"{parts.scheme}://{parts.netloc}", int(match.group("topic_id"))


def is_discourse_topic_url(url: str) -> bool:
    return discourse_topic_parts(url) is not None


def google_developer_forum_feed_url(url: str) -> Optional[str]:
    """Map Google Developer Forums pages to their native Discourse RSS feeds."""
    try:
        parts = urlsplit(str(url or "").strip())
    except Exception:
        return None
    if (parts.scheme or "").lower() not in ("http", "https"):
        return None
    if (parts.hostname or "").lower() != "discuss.google.dev":
        return None
    origin = f"{parts.scheme}://{parts.netloc}"
    path = (parts.path or "/").rstrip("/") or "/"
    if path in ("/", "/latest", "/categories"):
        return origin + "/latest.rss?order=created"
    if re.fullmatch(r"/c/[^/]+/[0-9]+", path, re.I):
        return origin + path + ".rss"
    if re.fullmatch(r"/tag/[^/]+", path, re.I):
        return origin + path + ".rss"
    topic = _DISCOURSE_TOPIC_RE.fullmatch(path)
    if topic:
        return origin + f"/t/-/{topic.group('topic_id')}.rss"
    return None


def _discourse_json(url: str, *, timeout: float, params=None):
    try:
        response = utils.safe_requests_get(
            url,
            timeout=max(1.0, float(timeout or 20)),
            headers={"Accept": "application/json"},
            params=params,
            allow_redirects=True,
        )
    except Exception:
        return None
    if not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
        return None
    try:
        payload = response.json()
    except Exception:
        try:
            payload = json.loads(response.text or "")
        except (TypeError, ValueError):
            return None
    return payload if isinstance(payload, dict) else None


def download_discourse_thread_html(url: str, *, timeout: float = 20) -> str:
    """Fetch every public post exposed by a Discourse topic API."""
    parsed = discourse_topic_parts(url)
    if not parsed:
        return ""
    origin, topic_id = parsed
    payload = _discourse_json(
        f"{origin}/t/{topic_id}.json", timeout=timeout, params={"print": "true"}
    )
    stream = (payload or {}).get("post_stream")
    if not isinstance(stream, dict) or not isinstance(stream.get("posts"), list):
        # A strict /t/... route is only a candidate; this validation prevents an
        # unrelated site's JSON from being treated as a forum conversation.
        return ""
    raw_posts = [post for post in stream.get("posts") or [] if isinstance(post, dict)]
    seen_ids = {str(post.get("id")) for post in raw_posts if post.get("id") is not None}
    wanted = [
        value
        for value in (stream.get("stream") or [])[:_MAX_DISCOURSE_POSTS]
        if str(value) not in seen_ids
    ]
    for offset in range(0, len(wanted), _DISCOURSE_POST_BATCH):
        batch = wanted[offset : offset + _DISCOURSE_POST_BATCH]
        page = _discourse_json(
            f"{origin}/t/{topic_id}/posts.json",
            timeout=timeout,
            params=[("post_ids[]", str(value)) for value in batch],
        )
        page_stream = (page or {}).get("post_stream")
        page_posts = page_stream.get("posts") if isinstance(page_stream, dict) else (page or {}).get("posts")
        if not isinstance(page_posts, list):
            break
        for post in page_posts:
            if not isinstance(post, dict):
                continue
            identity = str(post.get("id") or "")
            if identity and identity not in seen_ids:
                seen_ids.add(identity)
                raw_posts.append(post)
        if len(raw_posts) >= _MAX_DISCOURSE_POSTS:
            break
    raw_posts.sort(key=lambda post: int(post.get("post_number") or 0))
    posts = []
    for post in raw_posts[:_MAX_DISCOURSE_POSTS]:
        body = _clean_post_html(post.get("cooked") or "")
        if not body:
            continue
        username = str(post.get("username") or "").strip()
        display = str(post.get("name") or "").strip()
        author = display or (f"@{username}" if username else "Unknown author")
        posts.append(
            {
                "id": post.get("id"),
                "number": post.get("post_number") or len(posts) + 1,
                "author": author,
                "created": str(post.get("created_at") or "").strip(),
                "reply_to": post.get("reply_to_post_number") or "",
                "body": body,
            }
        )
    title = str((payload or {}).get("title") or "Discourse topic").strip()
    canonical = f"{origin}/t/-/{topic_id}"
    return _render_thread_document(
        title, posts, canonical, source_label="the forum", css_prefix="discourse"
    )
