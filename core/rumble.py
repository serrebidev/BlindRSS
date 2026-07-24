# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import logging
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from core import utils

LOG = logging.getLogger(__name__)

def _default_user_agent() -> str:
    """The app-wide browser identity (core/user_agents.py), resolved per call.

    Read late rather than frozen at import: the user can change the identity in
    Settings, and a module constant would keep serving the string the app was
    started with.
    """
    from core.utils import HEADERS

    return HEADERS.get("User-Agent", "")


class RumbleError(RuntimeError):
    pass


@dataclass(frozen=True)
class CurlFetchResult:
    url: str
    final_url: str
    status_code: int
    text: str


@dataclass(frozen=True)
class RumbleResolvedMedia:
    input_url: str
    media_url: str
    title: str | None = None
    embed_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


_EMBED_ID_RE = re.compile(r"https?://(?:www\.)?rumble\.com/embed/(?:[0-9a-z]+\.)?(?P<id>[0-9a-z]+)", re.I)
_RUMBLE_PLAY_RE = re.compile(
    r'Rumble\(\s*"play"\s*,\s*{[^}]*[\'"]?video[\'"]?\s*:\s*[\'"](?P<id>[0-9a-z]+)[\'"]',
    re.I,
)


def is_rumble_url(url: str) -> bool:
    if not url:
        return False
    try:
        return "rumble.com" in (urlparse(url).netloc or "").lower()
    except Exception:
        return False


def normalize_rumble_url(url: str) -> str:
    """Strip tracking query/fragments from rumble URLs for stable IDs."""
    if not isinstance(url, str):
        return url
    try:
        parts = urlsplit(url)
        if "rumble.com" not in (parts.netloc or "").lower():
            return url
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return url


def normalize_rumble_feed_url(url: str) -> str:
    """Best-effort normalization for Rumble list/feed URLs.

    For channel/user pages, force the "/videos" listing view (stable and parseable).
    Does not strip query strings globally since they may be meaningful for some list
    pages (e.g. search queries).
    """
    if not isinstance(url, str) or not url:
        return url
    try:
        parts = urlsplit(url)
        if "rumble.com" not in (parts.netloc or "").lower():
            return url
        path = (parts.path or "").rstrip("/")
        if re.match(r"^/(?:c|user)/[^/]+$", path, re.I):
            path = path + "/videos"
            return urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))
        # Search pages: keep the query but sort by most-recent unless the user
        # already specified a sort. Rumble's search sort param is `sort=date`.
        if re.match(r"^/search(?:/|$)", path, re.I):
            from urllib.parse import parse_qsl, urlencode
            qs = dict(parse_qsl(parts.query or "", keep_blank_values=True))
            if not qs.get("sort"):
                qs["sort"] = "date"
            new_query = urlencode(qs)
            return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, new_query, ""))
        return url
    except Exception:
        return url


def _get_curl_exe() -> str:
    return shutil.which("curl.exe") or shutil.which("curl") or ""


def fetch_text_via_curl(
    url: str,
    *,
    timeout_s: float = 20.0,
    user_agent: str | None = None,
    headers: dict[str, str] | None = None,
) -> CurlFetchResult:
    curl = _get_curl_exe()
    if not curl:
        raise FileNotFoundError("curl executable not found")

    ua = user_agent or _default_user_agent()
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", ua)

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="blindrss_rumble_", suffix=".tmp")
        try:
            Path(tmp_path).write_bytes(b"")
        finally:
            try:
                import os

                os.close(fd)
            except Exception:
                pass

        cmd = [
            curl,
            "-sS",
            "-L",
            "--compressed",
            "--max-time",
            str(float(timeout_s)),
            "-o",
            tmp_path,
            "-w",
            "%{http_code}\n%{url_effective}\n",
        ]
        for k, v in hdrs.items():
            if k and v is not None:
                cmd.extend(["-H", f"{k}: {v}"])
        cmd.append(url)

        kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if platform.system().lower() == "windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            try:
                from core.dependency_check import _get_startup_info

                kwargs["startupinfo"] = _get_startup_info()
            except Exception:
                pass

        res = subprocess.run(cmd, **kwargs)
        meta_lines = (res.stdout or "").splitlines()
        status_code = int(meta_lines[0]) if meta_lines else 0
        final_url = meta_lines[1] if len(meta_lines) > 1 else url

        try:
            text = Path(tmp_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""

        if res.returncode != 0 and not text:
            raise RumbleError((res.stderr or "").strip() or f"curl failed ({res.returncode})")

        return CurlFetchResult(url=url, final_url=final_url, status_code=status_code, text=text)
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _fetch_text(url: str, *, timeout_s: float = 20.0, user_agent: str | None = None) -> CurlFetchResult:
    try:
        return fetch_text_via_curl(url, timeout_s=timeout_s, user_agent=user_agent)
    except FileNotFoundError:
        resp = utils.safe_requests_get(url, timeout=timeout_s, allow_redirects=True)
        return CurlFetchResult(url=url, final_url=resp.url or url, status_code=int(resp.status_code), text=resp.text or "")


def extract_page_title(html: str) -> str | None:
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        t = soup.find("title")
        if t and t.get_text(strip=True):
            return t.get_text(strip=True)
    except Exception:
        pass
    return None


@dataclass(frozen=True)
class RumbleListingItem:
    url: str
    title: str
    published: str | None = None
    author: str | None = None

    @property
    def id(self) -> str:
        return self.url


_VIDEO_PATH_RE = re.compile(r"^/v(?!ideos)[^/]+\.html(?:\?.*)?$", re.I)


def parse_listing_html(html: str, *, base_url: str = "https://rumble.com") -> list[RumbleListingItem]:
    """Parse a Rumble listing page into video items (title/url/date)."""
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items: list[RumbleListingItem] = []

    for a in soup.find_all("a", href=True):
        href = a.get("href")
        if not isinstance(href, str):
            continue
        if not _VIDEO_PATH_RE.match(href):
            continue

        card = None
        try:
            card = a.find_parent(
                lambda t: t
                and t.name in ("div", "article", "li")
                and isinstance(t.get("class"), list)
                and any("videostream" in str(c) for c in t.get("class"))
            )
        except Exception:
            card = None

        full_url = href
        if href.startswith("/"):
            full_url = base_url.rstrip("/") + href
        full_url = normalize_rumble_url(full_url)

        title = None
        published = None

        if card is not None:
            try:
                h3 = card.select_one("h3.thumbnail__title")
                if h3 and h3.get_text(strip=True):
                    title = h3.get_text(" ", strip=True)
            except Exception:
                pass
            try:
                t = card.find("time")
                if t and isinstance(t.get("datetime"), str):
                    published = t.get("datetime")
            except Exception:
                pass

        if not title:
            if isinstance(a.get("title"), str) and a.get("title").strip():
                title = a.get("title").strip()
            else:
                text = a.get_text(" ", strip=True)
                title = text if text else "Rumble Video"

        if not published:
            try:
                t = a.find_next("time")
                if t and isinstance(t.get("datetime"), str):
                    published = t.get("datetime")
            except Exception:
                pass

        items.append(RumbleListingItem(url=full_url, title=title, published=published))

    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[RumbleListingItem] = []
    for it in items:
        if it.url in seen:
            continue
        seen.add(it.url)
        out.append(it)
    return out


def _looks_like_login_page(html: str, final_url: str | None = None) -> bool:
    fu = (final_url or "").lower()
    if "/login" in fu or "/signin" in fu:
        return True
    low = (html or "").lower()
    if "<title>sign in" in low or "<title>login" in low:
        return True
    if "name=\"password\"" in low and ("sign in" in low or "log in" in low):
        return True
    return False


@lru_cache(maxsize=16)
def _get_rumble_cookie_header(url: str) -> str | None:
    try:
        from yt_dlp.cookies import YDLLogger, extract_cookies_from_browser

        from core.discovery import get_rumble_cookie_sources

        sources = get_rumble_cookie_sources(url)
        if not sources:
            return None

        logger = YDLLogger(None)
        for source in sources:
            try:
                browser = source[0] if source else None
                profile = source[1] if len(source) > 1 else None
                if not browser:
                    continue
                jar = extract_cookies_from_browser(browser, profile, logger)
                hdr = jar.get_cookie_header(url)
                if hdr:
                    return hdr
            except Exception:
                continue
    except Exception:
        return None
    return None


def fetch_listing_items(
    url: str,
    *,
    timeout_s: float = 20.0,
    user_agent: str | None = None,
    allow_browser_cookies: bool = True,
) -> tuple[str | None, list[RumbleListingItem]]:
    """Fetch and parse a Rumble listing page (channel/videos, playlist, subscriptions, etc.)."""
    ua = user_agent or _default_user_agent()
    fr = _fetch_text(url, timeout_s=timeout_s, user_agent=ua)

    if allow_browser_cookies and _looks_like_login_page(fr.text, fr.final_url):
        cookie_hdr = _get_rumble_cookie_header(url)
        if cookie_hdr:
            try:
                fr = fetch_text_via_curl(
                    url,
                    timeout_s=timeout_s,
                    user_agent=ua,
                    headers={"Cookie": cookie_hdr},
                )
            except Exception:
                pass

    title = extract_page_title(fr.text)
    items = parse_listing_html(fr.text)
    return title, items


def extract_embed_id_from_video_html(html: str) -> str | None:
    if not html:
        return None

    m = _EMBED_ID_RE.search(html)
    if m:
        return m.group("id")

    m = _RUMBLE_PLAY_RE.search(html)
    if m:
        return m.group("id")

    return None


def _embed_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = _EMBED_ID_RE.search(url)
    if m:
        return m.group("id")
    return None


def _fetch_embedjs_video(embed_id: str, *, timeout_s: float = 20.0, user_agent: str | None = None) -> dict[str, Any]:
    if not embed_id:
        raise RumbleError("Missing embed id")
    api_url = f"https://rumble.com/embedJS/u3/?request=video&ver=2&v={embed_id}"
    fr = _fetch_text(api_url, timeout_s=timeout_s, user_agent=user_agent)
    if fr.status_code and fr.status_code >= 400:
        raise RumbleError(f"Rumble embedJS returned HTTP {fr.status_code}")
    try:
        return json.loads(fr.text)
    except Exception as e:
        raise RumbleError(f"Failed to parse embedJS JSON: {e}")


# Recorded live streams often expose only combined video+audio HLS/tar
# renditions (no MP4s). Buffering the top rendition (1080p+) stalls playback
# start for what the user listens to as audio, so mirror the yt-dlp policy
# ("best[height<=480]/worst"): best rendition at or below the cap, else the
# smallest available. Unknown heights (0) count as below the cap.
_STREAM_HEIGHT_CAP = 480


def _select_stream_rendition(candidates: list[tuple[int, int, str]]) -> str:
    capped = [c for c in candidates if c[0] <= _STREAM_HEIGHT_CAP]
    if capped:
        return max(capped, key=lambda t: (t[0], t[1]))[2]
    return min(candidates, key=lambda t: (t[0], t[1]))[2]


def _pick_best_direct_url(video: dict[str, Any]) -> str | None:
    candidates: list[tuple[int, int, str]] = []

    def _add_candidate(meta_h: Any, meta_bitrate: Any, url: Any) -> None:
        if not isinstance(url, str) or not url:
            return
        try:
            h = int(meta_h or 0)
        except Exception:
            h = 0
        try:
            br = int(meta_bitrate or 0)
        except Exception:
            br = 0
        candidates.append((h, br, url))

    ua = video.get("ua") or {}
    if isinstance(ua, dict):
        mp4 = ua.get("mp4")
        if isinstance(mp4, dict):
            for height_key, info in mp4.items():
                if not isinstance(info, dict):
                    continue
                meta = info.get("meta") or {}
                _add_candidate(meta.get("h") or height_key, meta.get("bitrate"), info.get("url"))
        elif isinstance(mp4, list):
            for info in mp4:
                if not isinstance(info, dict):
                    continue
                meta = info.get("meta") or {}
                _add_candidate(meta.get("h"), meta.get("bitrate"), info.get("url"))

    u = video.get("u") or {}
    if isinstance(u, dict):
        mp4u = u.get("mp4")
        if isinstance(mp4u, dict):
            meta = mp4u.get("meta") or {}
            _add_candidate(meta.get("h"), meta.get("bitrate"), mp4u.get("url"))

    if candidates:
        return max(candidates, key=lambda t: (t[0], t[1]))[2]

    # Prefer non-rumble HLS/tar URLs (avoid Cloudflare-protected rumble.com playlists).
    stream_candidates: list[tuple[int, int, str]] = []

    def _add_stream_container(container: Any) -> None:
        if isinstance(container, dict):
            for height_key, info in container.items():
                if not isinstance(info, dict):
                    continue
                meta = info.get("meta") or {}
                _add_candidate(meta.get("h") or height_key, meta.get("bitrate"), info.get("url"))
        elif isinstance(container, list):
            for info in container:
                if not isinstance(info, dict):
                    continue
                meta = info.get("meta") or {}
                _add_candidate(meta.get("h"), meta.get("bitrate"), info.get("url"))
        elif isinstance(container, str):
            _add_candidate(0, 0, container)

    # Collect tar playlists (served from 1a-*.com) if present.
    tar = None
    try:
        tar = (ua.get("tar") if isinstance(ua, dict) else None) or (u.get("tar") if isinstance(u, dict) else None)
    except Exception:
        tar = None
    _add_stream_container(tar)
    if candidates:
        # _add_candidate appends into candidates; move them into stream_candidates for selection
        stream_candidates.extend(candidates)
        candidates.clear()

    # Collect HLS playlists.
    hls = None
    try:
        hls = (ua.get("hls") if isinstance(ua, dict) else None) or (u.get("hls") if isinstance(u, dict) else None)
    except Exception:
        hls = None
    _add_stream_container(hls)
    if candidates:
        stream_candidates.extend(candidates)
        candidates.clear()

    # Prefer URLs not on rumble.com when possible.
    non_rumble = [c for c in stream_candidates if "rumble.com" not in c[2].lower()]
    if non_rumble:
        return _select_stream_rendition(non_rumble)
    if stream_candidates:
        return _select_stream_rendition(stream_candidates)

    # Last resort: very low-bitrate timeline preview.
    timeline = None
    try:
        timeline = (ua.get("timeline") if isinstance(ua, dict) else None) or (u.get("timeline") if isinstance(u, dict) else None)
    except Exception:
        timeline = None
    if isinstance(timeline, dict) and isinstance(timeline.get("url"), str):
        return timeline["url"]

    return None


def resolve_rumble_media(url: str, *, timeout_s: float = 20.0, user_agent: str | None = None) -> RumbleResolvedMedia:
    """Resolve a rumble.com video URL to a direct media URL (MP4 when available).

    This intentionally bypasses yt-dlp for Rumble, since Cloudflare can block
    Python-based HTTP stacks in some environments while still allowing curl.
    """
    if not url:
        raise RumbleError("Missing URL")

    ua = user_agent or _default_user_agent()
    input_url = url

    low = url.lower()
    if low.startswith("http") and any(low.split("?", 1)[0].endswith(ext) for ext in (".mp4", ".webm")):
        return RumbleResolvedMedia(input_url=input_url, media_url=url, headers={"User-Agent": ua})

    embed_id = _embed_id_from_url(url)
    if not embed_id:
        fr = _fetch_text(url, timeout_s=timeout_s, user_agent=ua)
        embed_id = extract_embed_id_from_video_html(fr.text)

    if not embed_id:
        raise RumbleError("Could not find Rumble embed id")

    video = _fetch_embedjs_video(embed_id, timeout_s=timeout_s, user_agent=ua)
    media_url = _pick_best_direct_url(video)
    if not media_url:
        raise RumbleError("Could not find a playable Rumble media URL")

    title = video.get("title") if isinstance(video, dict) else None
    headers = {"User-Agent": ua, "Referer": f"https://rumble.com/embed/{embed_id}/"}

    return RumbleResolvedMedia(
        input_url=input_url,
        media_url=media_url,
        title=title if isinstance(title, str) else None,
        embed_id=embed_id,
        headers=headers,
    )
