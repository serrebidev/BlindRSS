# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

LOG = logging.getLogger(__name__)

def _default_user_agent() -> str:
    """The app-wide browser identity (core/user_agents.py), resolved per call.

    Read late rather than frozen at import: the user can change the identity in
    Settings, and a module constant would keep serving the string the app was
    started with.
    """
    from core.utils import HEADERS

    return HEADERS.get("User-Agent", "")


class OdyseeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OdyseeListingItem:
    url: str
    title: str
    published: str | None = None
    author: str | None = None

    @property
    def id(self) -> str:
        return self.url


def is_odysee_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    scheme = (parsed.scheme or "").lower()
    if scheme == "lbry":
        return True

    if scheme not in ("http", "https", ""):
        return False

    domain = (parsed.netloc or "").lower()
    return "odysee.com" in domain or "lbry.tv" in domain


def normalize_odysee_url(url: str) -> str:
    if not isinstance(url, str):
        return url
    try:
        parts = urlsplit(url)
        domain = (parts.netloc or "").lower()
        if "odysee.com" not in domain and "lbry.tv" not in domain:
            return url
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return url


def normalize_odysee_feed_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        return url
    return normalize_odysee_url(url)


def _extract_listing_from_info(info: dict[str, Any]) -> tuple[str | None, list[OdyseeListingItem]]:
    if not isinstance(info, dict):
        return None, []

    title = info.get("title") if isinstance(info.get("title"), str) else None
    author = info.get("channel") or info.get("uploader") or info.get("channel_id") or None
    if not isinstance(author, str):
        author = None

    items: list[OdyseeListingItem] = []
    entries = info.get("entries")
    if isinstance(entries, list):
        for e in entries:
            if not isinstance(e, dict):
                continue
            u = e.get("url") or e.get("webpage_url") or ""
            if not isinstance(u, str) or not u:
                continue
            u = normalize_odysee_url(u)

            t = e.get("title")
            if not isinstance(t, str) or not t.strip():
                t = "Odysee Video"

            pub = e.get("timestamp") or e.get("release_timestamp") or e.get("upload_date")
            if isinstance(pub, (int, float)):
                pub_s = str(int(pub))
            elif isinstance(pub, str) and pub.strip():
                pub_s = pub.strip()
            else:
                pub_s = None

            a = e.get("channel") or e.get("uploader") or author
            if not isinstance(a, str):
                a = None

            items.append(OdyseeListingItem(url=u, title=t, published=pub_s, author=a))

    if items:
        seen: set[str] = set()
        deduped: list[OdyseeListingItem] = []
        for it in items:
            if it.url in seen:
                continue
            seen.add(it.url)
            deduped.append(it)
        return title, deduped

    u = info.get("webpage_url") or info.get("original_url") or info.get("url") or ""
    if isinstance(u, str) and u:
        u = normalize_odysee_url(u)
        t = info.get("title")
        if not isinstance(t, str) or not t.strip():
            t = "Odysee Video"
        pub = info.get("timestamp") or info.get("release_timestamp") or info.get("upload_date")
        if isinstance(pub, (int, float)):
            pub_s = str(int(pub))
        elif isinstance(pub, str) and pub.strip():
            pub_s = pub.strip()
        else:
            pub_s = None
        items = [OdyseeListingItem(url=u, title=t, published=pub_s, author=author)]

    return title, items


@lru_cache(maxsize=32)
def _cookie_sources() -> list[tuple]:
    try:
        from core.discovery import get_ytdlp_cookie_sources

        return list(get_ytdlp_cookie_sources())
    except Exception:
        return []


def fetch_listing_items(
    url: str,
    *,
    max_items: int = 100,
    timeout_s: float = 20.0,
    user_agent: str | None = None,
    allow_browser_cookies: bool = True,
) -> tuple[str | None, list[OdyseeListingItem]]:
    if not url:
        raise OdyseeError("Missing URL")

    try:
        max_items_i = int(max_items)
    except Exception:
        max_items_i = 100
    max_items_i = max(1, min(500, max_items_i))

    ua = user_agent or _default_user_agent()

    try:
        import yt_dlp

        from core.dependency_check import _get_startup_info
    except Exception as e:
        raise OdyseeError(f"yt-dlp unavailable: {e}")

    base_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playlistend": max_items_i,
        "user_agent": ua,
        "referer": url,
        "noprogress": True,
        "socket_timeout": float(timeout_s),
    }
    if platform.system().lower() == "windows":
        try:
            base_opts["subprocess_startupinfo"] = _get_startup_info()
        except Exception:
            pass

    last_err: Exception | None = None

    def _extract(opts: dict[str, Any]) -> dict[str, Any]:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=False)
        if not isinstance(data, dict):
            raise OdyseeError("yt-dlp did not return an info dict")
        return data

    try:
        info = _extract(dict(base_opts))
        return _extract_listing_from_info(info)
    except Exception as e:
        last_err = e

    if allow_browser_cookies:
        for source in _cookie_sources():
            try:
                opts = dict(base_opts)
                opts["cookiesfrombrowser"] = source
                info = _extract(opts)
                return _extract_listing_from_info(info)
            except Exception as e:
                last_err = e
                continue

    raise OdyseeError(str(last_err) if last_err else "Failed to fetch Odysee listing")

