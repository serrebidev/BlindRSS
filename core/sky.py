# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Sky News article helpers.

Sky's RSS feeds use image enclosures even for podcast articles.  Those items
link to a Podfollow series page from the feed summary/article body; the actual
episode enclosure lives in the podcast's RSS feed.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

import feedparser
from bs4 import BeautifulSoup

from core import utils


_PODFOLLOW_URL_RE = re.compile(
    r"https?://(?:www\.)?podfollow\.com/[^\s\"'<>]+", re.IGNORECASE
)


def is_sky_news_url(url: str) -> bool:
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower() == "news.sky.com"
    except Exception:
        return False


def _response_text(response) -> str:
    try:
        if not getattr(response, "encoding", None):
            response.encoding = getattr(response, "apparent_encoding", None) or "utf-8"
    except Exception:
        pass
    try:
        return response.text or ""
    except Exception:
        return ""


def _fetch_article_html(url: str, timeout: float) -> str:
    """Fetch Sky directly, then through its live Translate proxy when gated."""
    try:
        response = utils.safe_requests_get(url, timeout=timeout, allow_redirects=True)
        body = _response_text(response)
        if 200 <= response.status_code < 400 and _podfollow_url(body):
            return body
    except Exception:
        pass

    parts = urlsplit(url)
    query = parts.query + ("&" if parts.query else "")
    query += "_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en"
    proxy_url = f"https://news-sky-com.translate.goog{parts.path or '/'}?{query}"
    try:
        response = utils.safe_requests_get(proxy_url, timeout=timeout, allow_redirects=True)
        body = _response_text(response)
        if 200 <= response.status_code < 400:
            return body
    except Exception:
        pass
    return ""


def _podfollow_url(page_html: str) -> str:
    decoded = html_lib.unescape(str(page_html or ""))
    match = _PODFOLLOW_URL_RE.search(decoded)
    if not match:
        return ""
    return match.group(0).rstrip(".,);]")


def _article_title(page_html: str) -> str:
    if not page_html:
        return ""
    soup = BeautifulSoup(page_html, "html.parser")
    heading = soup.find("h1")
    if heading:
        title = heading.get_text(" ", strip=True)
        if title:
            return title
    meta = soup.find("meta", attrs={"property": "og:title"})
    if meta and meta.get("content"):
        return str(meta.get("content")).strip()
    return ""


def _podcast_feed_url(podfollow_html: str) -> str:
    soup = BeautifulSoup(podfollow_html or "", "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text() or "")
        except Exception:
            continue
        objects = payload if isinstance(payload, list) else [payload]
        for obj in objects:
            if not isinstance(obj, Mapping):
                continue
            feed_url = str(obj.get("webFeed") or "").strip()
            if feed_url:
                return _normalise_feed_url(feed_url)
    for anchor in soup.find_all("a", href=True):
        raw_url = str(anchor.get("href") or "").strip()
        # A Podfollow page contains many ordinary listening-service links.
        # Only its explicit podcast-feed link is a feed candidate.
        if not raw_url.lower().startswith("pcast://"):
            continue
        feed_url = _normalise_feed_url(raw_url)
        if feed_url:
            return feed_url
    return ""


def _normalise_feed_url(url: str) -> str:
    if url.lower().startswith("pcast://"):
        url = "https://" + url[8:]
    try:
        return url if urlsplit(url).scheme.lower() in {"http", "https"} else ""
    except Exception:
        return ""


def _normalise_title(title: str) -> str:
    title = html_lib.unescape(str(title or ""))
    title = title.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", title).strip().casefold()


def _entry_audio(entry) -> tuple[str | None, str | None]:
    enclosures = entry.get("enclosures") or entry.get("enclosure") or []
    if isinstance(enclosures, Mapping):
        enclosures = [enclosures]
    for enclosure in enclosures:
        if not isinstance(enclosure, Mapping):
            continue
        media_url = str(enclosure.get("href") or enclosure.get("url") or "").strip()
        media_type = utils.canonical_media_type(
            enclosure.get("type") or enclosure.get("mime_type") or ""
        )
        path = urlsplit(media_url).path.lower() if media_url else ""
        if media_url and (str(media_type or "").startswith("audio/") or path.endswith(".mp3")):
            return media_url, media_type or "audio/mpeg"
    return None, None


def extract_podcast_audio(
    article_url: str,
    *,
    title: str = "",
    html_hint: str = "",
    timeout: float = 20,
) -> tuple[str | None, str | None]:
    """Resolve a Sky podcast article to its matching RSS audio enclosure."""
    if not is_sky_news_url(article_url):
        return None, None

    page_html = str(html_hint or "")
    podfollow_url = _podfollow_url(page_html)
    if not podfollow_url:
        page_html = _fetch_article_html(article_url, timeout)
        podfollow_url = _podfollow_url(page_html)
    if not podfollow_url:
        return None, None

    target_title = _normalise_title(title or _article_title(page_html))
    if not target_title:
        return None, None

    try:
        response = utils.safe_requests_get(podfollow_url, timeout=timeout, allow_redirects=True)
        if not (200 <= response.status_code < 400):
            return None, None
        feed_url = _podcast_feed_url(_response_text(response))
        if not feed_url:
            return None, None
        response = utils.safe_requests_get(feed_url, timeout=timeout, allow_redirects=True)
        if not (200 <= response.status_code < 400):
            return None, None
        parsed = feedparser.parse(response.content)
    except Exception:
        return None, None

    for entry in parsed.entries:
        if _normalise_title(entry.get("title") or "") == target_title:
            return _entry_audio(entry)
    return None, None
