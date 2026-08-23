# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import subprocess
import json
import platform
import re
import time
import io
import contextlib
import threading
import concurrent.futures
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from dataclasses import dataclass
from functools import lru_cache
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus, quote, unquote, urlencode
from core import utils


_ARTICLE_DATE_PATH_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/")
_ARTICLE_PATH_HINTS = (
    "/news/",
    "/article",
    "/story/",
)
_MEDIA_PATH_HINTS = (
    "/video/",
    "/videos/",
    "/watch",
    "/clip",
    "/player",
    "/av/",
    "/reel/",
    "/embed",
    "/podcast",
    "/audio",
    "/episode",
    "/track",
)

# Extractors whose URL patterns are too broad to treat as "playable media" by
# default. For these, require explicit media-ish URL hints (see _MEDIA_PATH_HINTS)
# to avoid classifying arbitrary articles as playable.
_EXTRACTORS_REQUIRE_MEDIA_HINTS = {
    "VoxMedia",  # Matches most pages on theverge.com/vox.com/etc, not just media
    # Bluesky's post URL (bsky.app/profile/<handle>/post/<id>) is identical for a
    # plain-text post and a video post, so yt-dlp's Bluesky extractor matches
    # every post link. Without this, every article from a Bluesky RSS feed was
    # mislabeled "Contains audio" regardless of content.
    "Bluesky",
}

# Cache for yt-dlp extractors (loaded once in background)
_ytdlp_extractors = None
_ytdlp_extractors_lock = threading.Lock()
_ytdlp_extractors_loading = False

_YTDLP_SEARCH_SITE_LABEL_OVERRIDES = {
    "ytsearch": "YouTube",
    "bilisearch": "Bilibili",
    "nicosearch": "Niconico",
    "nicosearchdate": "Niconico",
    "scsearch": "SoundCloud",
    "rkfnsearch": "Rokfin",
    "prxseries": "PRX Series",
    "prxstories": "PRX Stories",
    "gvsearch": "Google Video",
    "yvsearch": "Yahoo Video",
    "netsearch": "Netverse",
}

_YTDLP_ADULT_KEYWORDS = (
    "adult",
    "porn",
    "sex",
    "erotic",
    "xhamster",
    "xvideos",
    "xnxx",
    "redtube",
    "youporn",
    "tube8",
    "spankbang",
    "hentai",
)

# Search sites that only duplicate a better site's results (or are dead), so we
# expose a single canonical site instead of several that "make no sense". yt-dlp's
# Yahoo/Google "video search" both just return YouTube results (or nothing at
# all), so the YouTube site (ytsearch) already covers them.
_REDUNDANT_SEARCH_SITE_IDS = frozenset({"gvsearch", "yvsearch"})

# Extra non-adult search sites that aren't yt-dlp query-search (_SEARCH_KEY)
# extractors. Backed by their own API (search_provider), dispatched in
# search_ytdlp_site. Included in normal (non-adult) search.
_EXTRA_SEARCH_SITES = (
    {"id": "mixcloud", "label": "Mixcloud", "search_provider": "mixcloud"},
)

# Adult sites are not exposed through yt-dlp's query-search (_SEARCH_KEY) system,
# so we search them via their on-site search-results page, which yt-dlp can
# extract as a flat playlist. Curated and verified so results stay sane; extend
# this as yt-dlp gains reliable adult search-page extractors. "{query}" is
# URL-quoted at run time. These are never returned unless adult sites are asked
# for explicitly (see get_ytdlp_searchable_sites / get_adult_searchable_sites).
_ADULT_SEARCH_SITES = (
    {
        "id": "pornhub",
        "label": "Pornhub",
        "search_url_template": "https://www.pornhub.com/video/search?search={query}",
    },
)

_URL_FALLBACK_SITE_NAMES = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "facebook.com": "Facebook",
    "bilibili.com": "Bilibili",
    "rokfin.com": "Rokfin",
    "soundcloud.com": "SoundCloud",
}

_ROKFIN_PUBLIC_API_BASE = "https://prod-api-v2.production.rokfin.com/api/v2/public"
_QUICK_TITLE_PREFETCH_MAX_WORKERS = 16
_ALTERNATE_FEED_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/feed+json",
    "application/x-cdf",
}


# yt-dlp YouTube player clients to extract from, in addition to whatever yt-dlp's
# own maintained "default" set is. YouTube frequently throttles or blocks any
# single client (and started requiring PO tokens for `android`), so widening the
# client pool is what makes playback reliable instead of haphazard: yt-dlp pulls
# formats from every listed client and the format selector then picks the best
# available audio. "default" tracks yt-dlp's current best clients (tv/ios/web*)
# and `android_vr` is the workaround that has kept packaged builds working.
YOUTUBE_PLAYER_CLIENTS = ("default", "android_vr")
# Last-resort, wider client pool tried only after the primary set fails. YouTube
# blocks/throttles individual clients unpredictably, so casting a wider net is the
# final way to coax out a playable stream before giving up. Avoids plain "android"
# (now requires PO tokens) but includes web/tv/ios/mweb variants that frequently
# still resolve anonymously.
YOUTUBE_PLAYER_CLIENTS_FALLBACK = (
    "default",
    "android_vr",
    "web_safari",
    "web_embedded",
    "web_music",
    "tv_simply",
    "tv_downgraded",
    "tv",
    "ios",
    "mweb",
    "web",
)


def youtube_player_client_list(clients=None) -> list[str]:
    """yt-dlp Python API form: extractor_args youtube.player_client list."""
    return list(clients if clients is not None else YOUTUBE_PLAYER_CLIENTS)


def youtube_player_client_arg(clients=None, *, visitor_data: str | None = None) -> str:
    """yt-dlp CLI extractor args for clients and optional browser visitor data."""
    value = "youtube:player_client=" + ",".join(
        clients if clients is not None else YOUTUBE_PLAYER_CLIENTS
    )
    visitor = str(visitor_data or "").strip()
    if visitor and not any(char in visitor for char in (";", "\r", "\n")):
        value += ";visitor_data=" + visitor
    return value


def normalize_ytdlp_single_item_url(url: str) -> str:
    """Remove YouTube radio-mix context when extracting one watch item.

    ``list=RD...&start_radio=1`` describes an endless generated mix, not the
    selected video. ``--no-playlist`` normally avoids enumerating that mix, but
    some YouTube player clients still return an unavailable response while the
    radio context remains. Callers keep the original URL for display/history;
    only yt-dlp receives this canonical single-video URL.
    """
    raw = str(url or "").strip()
    if not raw:
        return raw
    try:
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]

        query = parse_qs(parsed.query or "", keep_blank_values=True)
        video_id = ""
        if host == "youtube.com" and (parsed.path or "").rstrip("/") == "/watch":
            video_id = str((query.get("v") or [""])[0] or "").strip()
        elif host == "youtu.be":
            video_id = str((parsed.path or "").strip("/").split("/", 1)[0]).strip()
        else:
            return raw

        mix_id = str((query.get("list") or [""])[0] or "").strip()
        start_radio = (
            str((query.get("start_radio") or [""])[0] or "").strip().lower()
        )
        if (
            video_id
            and mix_id.upper().startswith("RD")
            and start_radio in {"1", "true", "yes"}
        ):
            return "https://www.youtube.com/watch?v=" + quote(video_id, safe="-_")
    except Exception:
        return raw
    return raw


def youtube_single_item_recovery_urls(url: str) -> list[str]:
    """Return alternate official YouTube frontends for one video.

    A video's playability response can differ between the ordinary watch page,
    YouTube Music, and the privacy-enhanced embedded player.  yt-dlp normally
    needs only the canonical watch URL, so these routes are deliberately
    last-resort retries after its maintained default clients and BlindRSS's
    wider client pool have both failed.
    """
    canonical = normalize_ytdlp_single_item_url(url)
    try:
        parsed = urlparse(canonical)
        host = str(parsed.hostname or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]
        if host != "youtube.com" or (parsed.path or "").rstrip("/") != "/watch":
            return []
        query = parse_qs(parsed.query or "", keep_blank_values=True)
        video_id = str((query.get("v") or [""])[0] or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id):
            return []
        encoded = quote(video_id, safe="-_")
        return [
            f"https://music.youtube.com/watch?v={encoded}",
            f"https://www.youtube-nocookie.com/embed/{encoded}",
        ]
    except Exception:
        return []


def _resolve_ytdlp_cli_path() -> str:
    try:
        from core.dependency_check import _find_executable_path

        cli_path = _find_executable_path("yt-dlp")
        if cli_path:
            return str(cli_path)
    except Exception:
        pass
    return "yt-dlp"


def _load_ytdlp_extractors():
    """Load yt-dlp extractors in background. Called once at startup."""
    global _ytdlp_extractors, _ytdlp_extractors_loading
    with _ytdlp_extractors_lock:
        if _ytdlp_extractors is not None or _ytdlp_extractors_loading:
            return
        _ytdlp_extractors_loading = True
    
    try:
        from yt_dlp.extractor import gen_extractor_classes
        extractors = list(gen_extractor_classes())
        with _ytdlp_extractors_lock:
            _ytdlp_extractors = extractors
        # Pre-compile the extractors' URL regexes here (still on the preload
        # thread) so the first is_ytdlp_supported() call on the UI thread does
        # not pay for compiling ~2000 patterns.
        for extractor_cls in extractors:
            try:
                extractor_cls.suitable("https://example.invalid/warmup")
            except Exception:
                pass
    except Exception:
        with _ytdlp_extractors_lock:
            _ytdlp_extractors = []
    finally:
        with _ytdlp_extractors_lock:
            _ytdlp_extractors_loading = False


def _get_ytdlp_extractors():
    """Get cached extractors, loading synchronously if needed."""
    global _ytdlp_extractors
    if _ytdlp_extractors is not None:
        return _ytdlp_extractors
    _load_ytdlp_extractors()
    return _ytdlp_extractors or []


def _wait_for_ytdlp_extractors(timeout_s: float = 5.0, poll_s: float = 0.05):
    """Wait briefly for the background extractor preload to finish."""
    try:
        timeout_s = max(0.0, float(timeout_s or 0.0))
    except Exception:
        timeout_s = 5.0
    try:
        poll_s = max(0.01, float(poll_s or 0.05))
    except Exception:
        poll_s = 0.05

    extractors = _get_ytdlp_extractors()
    if extractors:
        return extractors

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with _ytdlp_extractors_lock:
            if _ytdlp_extractors is not None:
                return _ytdlp_extractors or []
            loading = bool(_ytdlp_extractors_loading)
        if not loading:
            break
        time.sleep(poll_s)

    # Last attempt if the preload thread finished between checks.
    with _ytdlp_extractors_lock:
        if _ytdlp_extractors is not None:
            return _ytdlp_extractors or []
    return []


def _is_adult_ytdlp_search_extractor(*parts) -> bool:
    text = " ".join(str(p or "") for p in parts).lower()
    if not text:
        return False
    return any(tok in text for tok in _YTDLP_ADULT_KEYWORDS)


def _get_ytdlp_lazy_attr(extractor_cls, name: str, default=None):
    """Read lazy extractor attrs while suppressing fallback warnings to stderr."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return getattr(extractor_cls, name, default)
    except Exception:
        return default


def _ytdlp_search_site_id(search_key: str, ie_name: str | None = None) -> str:
    sk = str(search_key or "").strip().lower()
    if not sk:
        return ""
    if sk in _YTDLP_SEARCH_SITE_LABEL_OVERRIDES:
        # Keep stable IDs for filter persistence / lookup.
        if sk in ("nicosearchdate",):
            return "nicosearch"
        return sk
    ie_name_low = str(ie_name or "").strip().lower()
    if ":search" in ie_name_low:
        base = ie_name_low.split(":search", 1)[0].strip()
        if base:
            return base
    return sk


def _ytdlp_search_site_label(search_key: str, ie_key: str | None, ie_name: str | None, ie_desc: str | None) -> str:
    sk = str(search_key or "").strip().lower()
    if sk in _YTDLP_SEARCH_SITE_LABEL_OVERRIDES:
        return _YTDLP_SEARCH_SITE_LABEL_OVERRIDES[sk]

    ie_name_text = str(ie_name or "").strip()
    if ie_name_text and ":search" in ie_name_text.lower():
        return ie_name_text.split(":", 1)[0].strip().title()

    ie_key_text = str(ie_key or "").strip()
    if ie_key_text:
        if ie_key_text.lower().endswith("searchdate"):
            ie_key_text = ie_key_text[:-10]
        elif ie_key_text.lower().endswith("search"):
            ie_key_text = ie_key_text[:-6]
        if ie_key_text:
            return ie_key_text

    desc_text = str(ie_desc or "").strip()
    if desc_text:
        low = desc_text.lower()
        if low.endswith(" search"):
            return desc_text[:-7].strip()
        return desc_text

    return sk or "Unknown"


def get_ytdlp_searchable_sites(include_adult: bool = False) -> list[dict]:
    """Return yt-dlp query-searchable sites derived from installed extractors.

    We intentionally discover this from the local yt-dlp extractor registry so the
    list tracks the installed yt-dlp version automatically.
    """
    sites_by_id: dict[str, dict] = {}
    extractors = _wait_for_ytdlp_extractors(timeout_s=4.0)

    for extractor_cls in extractors:
        try:
            cls_name = str(getattr(extractor_cls, "__name__", "") or "").strip()
        except Exception:
            cls_name = ""
        # yt-dlp lazy extractors can warn on missing attrs via __getattr__ fallback.
        # Query-search extractors use *SearchIE / *SearchDateIE class names.
        if not (
            cls_name.endswith("SearchIE")
            or cls_name.endswith("SearchDateIE")
            or cls_name.endswith("Search")
            or cls_name.endswith("SearchDate")
        ):
            continue
        try:
            search_key = str(_get_ytdlp_lazy_attr(extractor_cls, "_SEARCH_KEY", "") or "").strip()
        except Exception:
            search_key = ""
        if not search_key:
            continue

        try:
            ie_key = str(extractor_cls.ie_key() or "").strip()
        except Exception:
            ie_key = str(getattr(extractor_cls, "__name__", "") or "").strip()
        ie_name = str(_get_ytdlp_lazy_attr(extractor_cls, "IE_NAME", "") or "").strip()
        ie_desc = str(_get_ytdlp_lazy_attr(extractor_cls, "IE_DESC", "") or "").strip()
        working = bool(_get_ytdlp_lazy_attr(extractor_cls, "_WORKING", True))
        adult = _is_adult_ytdlp_search_extractor(search_key, ie_key, ie_name, ie_desc)
        if adult and not include_adult:
            continue

        site_id = _ytdlp_search_site_id(search_key, ie_name=ie_name)
        if not site_id:
            continue
        if site_id in _REDUNDANT_SEARCH_SITE_IDS:
            # Drop sites that only duplicate a canonical site's results.
            continue
        label = _ytdlp_search_site_label(search_key, ie_key, ie_name, ie_desc)

        row = {
            "id": site_id,
            "label": label,
            "search_key": search_key,
            "ie_key": ie_key,
            "ie_name": ie_name,
            "ie_desc": ie_desc,
            "adult": adult,
            "working": working,
        }

        existing = sites_by_id.get(site_id)
        if existing is None:
            sites_by_id[site_id] = row
            continue

        # Prefer non-date search variants and "working" extractors.
        preferred = existing
        cand_score = (
            1 if working else 0,
            1 if not search_key.lower().endswith("date") else 0,
            len(search_key or ""),
        )
        cur_score = (
            1 if bool(existing.get("working", True)) else 0,
            1 if not str(existing.get("search_key", "")).lower().endswith("date") else 0,
            len(str(existing.get("search_key", "") or "")),
        )
        if cand_score > cur_score:
            preferred = row
        else:
            # Keep alias visibility for debugging / future display if needed.
            aliases = list(existing.get("search_key_aliases") or [])
            if search_key not in aliases and search_key != existing.get("search_key"):
                aliases.append(search_key)
            if aliases:
                existing["search_key_aliases"] = aliases
            continue

        aliases = list(preferred.get("search_key_aliases") or [])
        for alias in [existing.get("search_key")] + list(existing.get("search_key_aliases") or []):
            alias = str(alias or "").strip()
            if alias and alias != preferred.get("search_key") and alias not in aliases:
                aliases.append(alias)
        if aliases:
            preferred["search_key_aliases"] = aliases
        sites_by_id[site_id] = preferred

    out = list(sites_by_id.values())
    # API-backed extra sites (e.g. Mixcloud) that aren't yt-dlp search extractors.
    existing_ids = {str(r.get("id") or "") for r in out}
    for extra in _EXTRA_SEARCH_SITES:
        if str(extra.get("id") or "") in existing_ids:
            continue
        row = dict(extra)
        row.setdefault("search_key", "")
        row.setdefault("adult", False)
        row.setdefault("working", True)
        out.append(row)
    out.sort(key=lambda x: (str(x.get("label", "")).lower(), str(x.get("id", "")).lower()))
    if include_adult:
        out.extend(get_adult_searchable_sites())
    return out


def get_adult_searchable_sites() -> list[dict]:
    """Return curated adult search sites (URL-template based, not _SEARCH_KEY).

    Kept separate from the safe list so callers can offer adult search only when
    the user explicitly asks for it; "all sites" search must never include these.
    """
    out: list[dict] = []
    for site in _ADULT_SEARCH_SITES:
        row = dict(site)
        row.setdefault("search_key", "")
        row["adult"] = True
        row.setdefault("working", True)
        out.append(row)
    out.sort(key=lambda x: (str(x.get("label", "")).lower(), str(x.get("id", "")).lower()))
    return out


def _tokenize_feed_hint(text: str) -> list[str]:
    return [tok for tok in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(tok) >= 3]


def _alternate_feed_candidates(soup: BeautifulSoup, page_url: str) -> list[str]:
    page_url_s = str(page_url or "").strip()
    page_parsed = urlparse(page_url_s)
    page_path = (page_parsed.path or "").strip("/")
    page_tokens = set(_tokenize_feed_hint(page_path.replace("/", " ")))

    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()

    for idx, link in enumerate(soup.find_all("link", href=True)):
        try:
            rel = link.get("rel")
            rel_vals: list[str] = []
            if isinstance(rel, str):
                rel_vals = [rel]
            elif isinstance(rel, list):
                rel_vals = [str(r) for r in rel]
            rel_vals = [r.lower().strip() for r in rel_vals if r]
            if "alternate" not in rel_vals:
                continue

            ctype = (link.get("type") or "").lower().strip()
            if ctype not in _ALTERNATE_FEED_TYPES:
                continue

            href = link.get("href")
            if not href:
                continue
            candidate = urljoin(page_url_s, href)
            if candidate in seen:
                continue
            seen.add(candidate)

            score = 0
            title = str(link.get("title") or "").strip().lower()
            cand_path = (urlparse(candidate).path or "").lower()
            cand_tokens = set(_tokenize_feed_hint(cand_path))
            title_tokens = set(_tokenize_feed_hint(title))

            if page_tokens:
                overlap = len(page_tokens & cand_tokens)
                score += overlap * 8
                title_overlap = len(page_tokens & title_tokens)
                score += title_overlap * 10
                page_slug = "-".join([tok for tok in _tokenize_feed_hint(page_path.replace("/", " "))])
                if page_slug:
                    if page_slug in cand_path:
                        score += 12
                    if page_slug in title.replace(" ", "-"):
                        score += 12

            if cand_path.endswith("/index.xml") or cand_path.endswith("/rss.xml"):
                score -= 1
            if re.search(r"/rss/(?:index\.xml)?$", cand_path):
                score -= 3
            if re.search(r"(?:^|/)(comments?|comment-feed)(?:/|$)", cand_path) or "comment" in title:
                score -= 12

            scored.append((score, -idx, candidate))
        except Exception:
            continue

    scored.sort(reverse=True)
    return [candidate for _score, _neg_idx, candidate in scored]


# Pre-load extractors in background thread at module import
threading.Thread(target=_load_ytdlp_extractors, daemon=True).start()


@lru_cache(maxsize=2048)
def is_ytdlp_supported(url: str) -> bool:
    """Return True only when yt-dlp has a non-generic extractor for this URL.

    IMPORTANT:
    We intentionally use yt-dlp's URL-pattern matching (no network) rather than a
    "does extraction succeed" check. Many normal article pages contain embedded
    players (HTML5 audio/video, YouTube iframes, etc.) and yt-dlp can often
    extract *something* from them, which would incorrectly classify articles as
    playable media.
    """
    if not url:
        return False

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme and scheme not in ("http", "https", "lbry"):
        return False

    domain = (parsed.hostname or "").lower()
    if scheme in ("http", "https") and not domain:
        return False

    # Fast allowlist for common media domains (keeps UI snappy).
    known_domains = [
        "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "dailymotion.com",
        "soundcloud.com", "facebook.com", "twitter.com", "x.com", "tiktok.com",
        "instagram.com", "rumble.com", "bilibili.com", "mixcloud.com",
        "odysee.com", "lbry.tv",
    ]
    if any(_host_matches(domain, kd) for kd in known_domains):
        return True

    path_low = (parsed.path or "").lower()
    # Heuristic: don't treat obvious article/news URLs as playable media just
    # because yt-dlp has a dedicated extractor for the publisher site.
    # (e.g., NYTimesArticle, CNN, BBC can match standard articles).
    looks_like_media = any(hint in path_low for hint in _MEDIA_PATH_HINTS)
    if not looks_like_media:
        if _ARTICLE_DATE_PATH_RE.search(path_low) or any(hint in path_low for hint in _ARTICLE_PATH_HINTS):
            return False

    # Use yt-dlp's extractor regexes (offline) and ignore Generic.
    try:
        for extractor_cls in _get_ytdlp_extractors():
            try:
                if not extractor_cls.suitable(url):
                    continue
                key = extractor_cls.ie_key()
                if key == "Generic":
                    continue
                # Many publisher sites have dedicated "...Article" extractors,
                # which are not a good signal that a URL is a playable media page.
                if str(key).lower().endswith("article"):
                    continue
                # Some extractors (e.g. VoxMedia) match most publisher pages, so
                # only treat them as supported when the URL itself looks like a
                # media page.
                if key in _EXTRACTORS_REQUIRE_MEDIA_HINTS and not looks_like_media:
                    continue
                return True
            except Exception:
                continue
    except Exception:
        return False

    return False


def is_rumble_url(url: str) -> bool:
    if not url:
        return False
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return False
    return "rumble.com" in domain


def _build_cookie_sources() -> list[tuple]:
    sources: list[tuple] = []

    def _add(browser: str, profile: str | None = None) -> None:
        tup = (browser,) if profile is None else (browser, profile)
        if tup not in sources:
            sources.append(tup)

    # Priority order: Brave first, then the other Chromium-family browsers, Edge,
    # then Firefox-family (Firefox, LibreWolf). Only yt-dlp-supported browser
    # keywords are used (brave, chrome, chromium, vivaldi, edge, opera, firefox);
    # LibreWolf is read via the firefox extractor with an explicit profile path.
    if platform.system().lower() == "windows":
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        # (browser_keyword, user_data_dir, is_default_install). For the default
        # install we pass the keyword alone (yt-dlp finds it); for variants like
        # Brave Beta we pass the explicit User Data path as the profile.
        # yt-dlp has no separate browser keyword for the Beta/Nightly/Canary
        # channels, so each variant is read through its base extractor (brave/
        # chrome/edge) with an explicit User Data path. Chrome "Nightly" is Chrome
        # Canary (Chrome SxS) and Edge "Nightly" is Edge Canary (Edge SxS); the
        # Chromium docs put them under "Chrome Beta"/"Chrome SxS"/"Edge Beta"/
        # "Edge SxS" respectively.
        chromium_dirs = [
            ("brave", os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"), True),
            ("brave", os.path.join(local, "BraveSoftware", "Brave-Browser-Beta", "User Data"), False),
            ("brave", os.path.join(local, "BraveSoftware", "Brave-Browser-Nightly", "User Data"), False),
            ("chrome", os.path.join(local, "Google", "Chrome", "User Data"), True),
            ("chrome", os.path.join(local, "Google", "Chrome Beta", "User Data"), False),
            ("chrome", os.path.join(local, "Google", "Chrome SxS", "User Data"), False),  # Chrome Canary
            ("chromium", os.path.join(local, "Chromium", "User Data"), True),
            ("vivaldi", os.path.join(local, "Vivaldi", "User Data"), True),
            ("edge", os.path.join(local, "Microsoft", "Edge", "User Data"), True),
            ("edge", os.path.join(local, "Microsoft", "Edge Beta", "User Data"), False),
            ("edge", os.path.join(local, "Microsoft", "Edge SxS", "User Data"), False),  # Edge Canary
            ("opera", os.path.join(roaming, "Opera Software", "Opera Stable"), True),
        ]
        for name, path, is_default in chromium_dirs:
            if path and os.path.isdir(path):
                _add(name) if is_default else _add(name, path)

        if roaming and os.path.isdir(os.path.join(roaming, "Mozilla", "Firefox", "Profiles")):
            _add("firefox")
        for lw_profiles in (
            os.path.join(roaming, "librewolf", "Profiles") if roaming else "",
            os.path.join(local, "librewolf", "Profiles") if local else "",
        ):
            if lw_profiles and os.path.isdir(lw_profiles):
                _add("firefox", lw_profiles)
                break
    else:
        # macOS/Linux: let yt-dlp locate the default profile for each browser.
        for name in ("brave", "chrome", "chromium", "vivaldi", "edge", "opera", "firefox"):
            _add(name)

    if not sources:
        for name in ("brave", "chrome", "chromium", "edge", "firefox"):
            _add(name)

    return sources


def cookie_arg_for_ytdlp(source) -> str | None:
    """Format a cookie-source tuple as a yt-dlp --cookies-from-browser value."""
    if not source:
        return None
    browser = source[0]
    profile = source[1] if len(source) > 1 else None
    if profile:
        return f"{browser}:{profile}"
    return browser


def is_chromium_ytdlp_cookie_source(source) -> bool:
    """True for cookie stores affected by Chromium App-Bound Encryption.

    ``source`` may be the tuple used by yt-dlp's Python API or the formatted
    ``browser:profile`` CLI value.  Firefox/LibreWolf must remain eligible after
    Chrome, Edge, or another Chromium browser reports a DPAPI failure.
    """
    if isinstance(source, (tuple, list)):
        browser = source[0] if source else ""
    else:
        browser = str(source or "").split(":", 1)[0]
    return str(browser or "").strip().lower() in {
        "brave",
        "chrome",
        "chromium",
        "vivaldi",
        "edge",
        "opera",
        "whale",
    }


def is_ytdlp_dpapi_cookie_error(exc_or_msg) -> bool:
    """True when a yt-dlp failure is Windows browser-cookie decryption, not the media.

    Chromium v127+ App-Bound Encryption (yt-dlp #10927) makes
    ``--cookies-from-browser`` fail on Chrome/Brave/Edge. That failure says
    nothing about whether the item itself is playable, so callers must never
    report it as *the* reason a public video failed: it hides the real error
    from the anonymous attempt that ran first.
    """
    text = str(exc_or_msg or "").lower()
    if not text:
        return False
    return "dpapi" in text or "failed to decrypt with dpapi" in text


def get_rumble_cookie_sources(url: str) -> list[tuple]:
    """Return cookiesfrombrowser candidates for rumble URLs."""
    if not is_rumble_url(url):
        return []
    return _build_cookie_sources()


def get_ytdlp_cookie_sources(url: str | None = None) -> list[tuple]:
    """Return cookiesfrombrowser candidates for yt-dlp extraction."""
    return _build_cookie_sources()


def _looks_like_feed_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return False
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return False
    path_low = (parsed.path or "").lower()
    if path_low.endswith((".rss", ".xml", ".atom", ".cdf")):
        return True
    if path_low.endswith("/feed") or path_low.endswith("/feeds"):
        return True
    if "/feed/" in path_low or "/feeds/" in path_low:
        return True
    qs = parse_qs(parsed.query or "", keep_blank_values=True)
    for key, values in qs.items():
        key_low = str(key).lower()
        normalized_values = {
            str(value or "").strip().lower()
            for value in values
        }
        if key_low in ("feed", "rss") and normalized_values.intersection(
            {"1", "true", "yes", "feed", "rss", "rss2", "atom", "rdf", "xml", "json", "jsonfeed", "cdf"}
        ):
            return True
        if key_low == "format" and normalized_values.intersection(
            {"rss", "rss2", "atom", "rdf", "xml", "jsonfeed", "cdf"}
        ):
            return True
    return False


def _host_matches(host: str, domain: str) -> bool:
    host = str(host or "").strip().lower().rstrip(".")
    domain = str(domain or "").strip().lower().rstrip(".")
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def _is_youtube_host(host: str) -> bool:
    return _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be")


def _body_looks_like_feed(body: str, content_type: str = "") -> bool:
    text = str(body or "").lstrip()
    if not text:
        return False

    if text.startswith(("{", "[")) or "json" in str(content_type or "").lower():
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                return False
            version = str(payload.get("version") or "").strip()
            title = payload.get("title")
            items = payload.get("items")
            if (
                version in {
                    "https://jsonfeed.org/version/1",
                    "https://jsonfeed.org/version/1.1",
                }
                and isinstance(title, str)
                and bool(title.strip())
                and isinstance(items, list)
            ):
                return True
        except Exception:
            pass

    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError, TypeError):
        return False
    tag = str(getattr(root, "tag", "") or "")
    local_name = tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()
    namespace = tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else ""
    child_names = {
        str(getattr(child, "tag", "") or "").rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()
        for child in root
    }
    if local_name == "rss":
        return "channel" in child_names
    if local_name == "feed":
        return namespace in {
            "http://www.w3.org/2005/Atom",
            "http://purl.org/atom/ns#",
        }
    if local_name == "rdf":
        return (
            namespace == "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            and "channel" in child_names
        )
    if local_name == "channel":
        return "item" in child_names
    return False


def _is_http_like_url(url: str) -> bool:
    if not url:
        return False
    try:
        scheme = (urlparse(str(url).strip()).scheme or "").lower()
    except Exception:
        return False
    return scheme in ("http", "https", "lbry")


def _pick_ytdlp_search_entry_url(entry: dict) -> str:
    if not isinstance(entry, dict):
        return ""
    for key in ("webpage_url", "url", "original_url"):
        val = str(entry.get(key) or "").strip()
        if not val:
            continue
        if _is_http_like_url(val):
            return val
    return ""


def _infer_ytdlp_search_result_kind(url: str, entry: dict, site_id: str | None = None) -> str:
    url = str(url or "").strip()
    low_url = url.lower()
    parsed = None
    path_low = ""
    path_parts: list[str] = []
    try:
        parsed = urlparse(url)
        path_low = (parsed.path or "").lower().rstrip("/")
        path_parts = [str(p or "").strip().lower() for p in (parsed.path or "").split("/") if str(p or "").strip()]
    except Exception:
        parsed = None
        path_low = low_url
        path_parts = [str(p or "").strip().lower() for p in path_low.split("/") if str(p or "").strip()]

    if _looks_like_feed_url(url):
        return "feed"

    # If yt-dlp gives a distinct uploader/profile URL, a child URL is typically media
    # (e.g. SoundCloud /user/track).
    try:
        uploader_url = str((entry or {}).get("uploader_url") or "").strip().rstrip("/")
        if uploader_url and _is_http_like_url(uploader_url):
            row_url = str(url or "").strip().rstrip("/")
            if row_url and row_url != uploader_url and row_url.startswith(uploader_url + "/"):
                return "media"
    except Exception:
        pass

    etype = str((entry or {}).get("_type") or "").strip().lower()
    if etype == "playlist":
        return "playlist"

    query = {}
    try:
        query = parse_qs(parsed.query or "") if parsed else {}
    except Exception:
        query = {}

    if "list" in query and any(str(v or "").strip() for v in (query.get("list") or [])):
        return "playlist"

    if any(tok in path_low for tok in ("/playlist", "/playlists", "/sets/", "/series", "/podcast", "/shows/", "/stack")):
        return "playlist"

    if path_parts:
        if path_parts[0] in ("channel", "channels", "profile", "profiles", "creator"):
            if len(path_parts) <= 2:
                return "user"
        if path_parts[0] in ("user", "users"):
            # Treat /user/<id> as a profile page, but deeper paths are often media items
            # on sites like SoundCloud (/user/track-name).
            if len(path_parts) <= 2:
                return "user"
    if "/@" in path_low or path_low.startswith("/@"):
        return "user"

    sid = str(site_id or "").strip().lower()
    if sid == "prxseries":
        return "feed"

    return "media"


def _build_ytdlp_search_result_detail(entry: dict, site_label: str, kind: str) -> str:
    if not isinstance(entry, dict):
        return site_label

    bits = []
    if kind and kind != "media":
        bits.append(kind.title())

    entry_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
    owner_label = _extract_ytdlp_search_entry_owner_label(entry, entry_url, allow_oembed=False)
    if owner_label and owner_label not in bits:
        bits.append(owner_label)

    try:
        duration = entry.get("duration")
        if duration is not None:
            sec = int(duration)
            if sec > 0:
                h, rem = divmod(sec, 3600)
                m, s = divmod(rem, 60)
                bits.append(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
    except Exception:
        pass

    if not bits:
        bits.append(site_label)
    return " | ".join(bits)


def _extract_ytdlp_search_entry_owner_label(entry: dict, url: str = "", allow_oembed: bool = False) -> str:
    """Best-effort owner/channel label for a yt-dlp search row."""
    if not isinstance(entry, dict):
        return ""

    owner_name = ""
    for key in ("channel", "uploader", "playlist_uploader", "artist", "creator", "author"):
        val = str(entry.get(key) or "").strip()
        if val:
            owner_name = val
            break

    owner_handle = ""
    for key in ("uploader_id", "channel_handle", "author_id", "creator_id"):
        raw = str(entry.get(key) or "").strip()
        if not raw:
            continue
        if raw.startswith("@"):
            owner_handle = raw
            break
        # Keep this strict to avoid converting arbitrary IDs into handles.
        if re.fullmatch(r"[A-Za-z0-9._-]{2,40}", raw) and not raw.upper().startswith("UC"):
            owner_handle = f"@{raw}"
            break

    if not owner_handle:
        for candidate in (
            entry.get("channel_url"),
            entry.get("uploader_url"),
            entry.get("author_url"),
            entry.get("creator_url"),
            url,
            entry.get("webpage_url"),
        ):
            handle = _youtube_handle_from_url(candidate)
            if handle:
                owner_handle = handle
                break

    if owner_name and owner_handle:
        if owner_name.lstrip("@").lower() == owner_handle.lstrip("@").lower():
            owner = owner_handle
        else:
            owner = f"{owner_name} / {owner_handle}"
    else:
        owner = owner_name or owner_handle

    if owner:
        return owner

    if allow_oembed:
        return _youtube_owner_label_from_oembed(url)

    return ""


def _extract_ytdlp_search_entry_play_count(entry: dict):
    """Return a normalized play/view count for a search entry, if present."""
    if not isinstance(entry, dict):
        return None
    for key in ("view_count", "play_count"):
        raw = entry.get(key)
        if raw is None:
            continue
        try:
            val = int(raw)
        except Exception:
            try:
                # Some extractors may expose numeric strings with decimals.
                val = int(float(str(raw).strip()))
            except Exception:
                continue
        if val >= 0:
            return val
    return None


def _friendly_title_fallback_from_url(url: str, site_label: str | None = None) -> str:
    """Create a human-readable fallback title when search results are URL-only."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        parsed = None
    if not parsed or (parsed.scheme or "").lower() not in ("http", "https"):
        return ""

    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") and host.endswith("facebook.com") else host
    path = str(parsed.path or "")
    path_parts = [unquote(p).strip() for p in path.split("/") if str(p or "").strip()]
    query = {}
    try:
        query = parse_qs(parsed.query or "")
    except Exception:
        query = {}

    site_name = str(site_label or "").strip()
    if not site_name:
        for dom, label in _URL_FALLBACK_SITE_NAMES.items():
            if host == dom or host.endswith("." + dom):
                site_name = label
                break
    if not site_name:
        base = host.split(":")[0]
        site_name = base or "Site"

    def _id_from_parts(name: str) -> str:
        if name in path_parts:
            idx = path_parts.index(name)
            if idx + 1 < len(path_parts):
                return str(path_parts[idx + 1] or "").strip()
        return ""

    # Site-specific friendly fallbacks.
    if _is_youtube_host(host):
        if _host_matches(host, "youtu.be") and path_parts:
            return f"YouTube video {path_parts[0]}"
        vid = str((query.get("v") or [""])[0] or "").strip()
        if vid:
            return f"YouTube video {vid}"
        pid = str((query.get("list") or [""])[0] or "").strip()
        if pid:
            return f"YouTube playlist {pid}"

    if "facebook.com" in host:
        reel_id = _id_from_parts("reel")
        if reel_id:
            return f"Facebook reel {reel_id}"
        vid = str((query.get("v") or [""])[0] or "").strip()
        if vid:
            return f"Facebook video {vid}"

    if "rokfin.com" in host:
        for kind in ("post", "stream", "stack"):
            item_id = _id_from_parts(kind)
            if item_id:
                return f"Rokfin {kind} {item_id}"

    if "bilibili.com" in host:
        if "video" in path_parts:
            idx = path_parts.index("video")
            if idx + 1 < len(path_parts):
                return f"Bilibili video {path_parts[idx + 1]}"

    # Generic fallback: site name + last path token (or hostname).
    leaf = path_parts[-1] if path_parts else ""
    leaf = re.sub(r"[-_]+", " ", leaf).strip()
    leaf = re.sub(r"\s+", " ", leaf).strip()
    if leaf:
        if len(leaf) > 80:
            leaf = leaf[:77].rstrip() + "..."
        return f"{site_name} {leaf}"
    return f"{site_name} item"


def _display_site_label_from_result_url(url: str, fallback_label: str | None = None) -> str:
    """Prefer the actual source site label (from URL host) over wrapper search labels."""
    raw = str(url or "").strip()
    label = str(fallback_label or "").strip()
    if not raw:
        return label
    try:
        parsed = urlparse(raw)
    except Exception:
        return label
    host = (parsed.netloc or "").lower().strip()
    if not host:
        return label
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") and host.endswith("facebook.com") else host
    for dom, dom_label in _URL_FALLBACK_SITE_NAMES.items():
        if host == dom or host.endswith("." + dom):
            return str(dom_label or label or "").strip() or label
    return label


def _clean_page_title(title: str) -> str:
    t = str(title or "").strip()
    if not t:
        return ""
    t = re.sub(r"\s+", " ", t).strip()
    if t.lower() in ("error", "not found", "403 forbidden", "404 not found"):
        return ""
    if t.lower() == "rokfin | the best way to monetize your content":
        return ""
    return t


def _rokfin_public_id_from_url(url: str) -> str:
    """Extract Rokfin public API path id like 'post/56518', 'stream/18601', or 'stack/1176'."""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return ""
    host = (parsed.netloc or "").lower()
    if "rokfin.com" not in host:
        return ""
    parts = [str(p or "").strip() for p in (parsed.path or "").split("/") if str(p or "").strip()]
    if len(parts) < 2:
        return ""
    kind = parts[0].lower()
    if kind not in ("post", "stream", "stack"):
        return ""
    item_id = parts[1]
    if not item_id.isdigit():
        return ""
    return f"{kind}/{item_id}"


def _rokfin_public_api_enrichment(url: str, timeout: int = 10) -> dict:
    """Best-effort metadata from Rokfin public API for post/stream/stack URLs."""
    out = {
        "title": "",
        "native_subscribe_url": "",
        "source_subscribe_url": "",
    }
    rk_id = _rokfin_public_id_from_url(url)
    if not rk_id:
        return out

    try:
        timeout = max(4, min(30, int(timeout or 10)))
    except Exception:
        timeout = 10

    rk_kind, _, rk_num = rk_id.partition("/")
    api_url = f"{_ROKFIN_PUBLIC_API_BASE}/{rk_id}"
    try:
        resp = utils.safe_requests_get(api_url, timeout=timeout)
        status = int(getattr(resp, "status_code", 0) or 0)
        data = resp.json() if (status == 200 and hasattr(resp, "json")) else {}
        # Some Rokfin search URLs are labelled as /post/<id> but the public API record
        # actually lives under /stream/<id>.
        if status != 200 and rk_kind == "post" and rk_num.isdigit():
            alt_url = f"{_ROKFIN_PUBLIC_API_BASE}/stream/{rk_num}"
            resp = utils.safe_requests_get(alt_url, timeout=timeout)
            status = int(getattr(resp, "status_code", 0) or 0)
            data = resp.json() if (status == 200 and hasattr(resp, "json")) else {}
        if status != 200:
            return out
        if not isinstance(data, dict):
            return out

        title = _clean_page_title(data.get("title"))
        if not title:
            try:
                title = _clean_page_title(data.get("name"))
            except Exception:
                title = ""
        if not title:
            try:
                title = _clean_page_title(data.get("text"))
            except Exception:
                title = ""
        if not title:
            try:
                title = _clean_page_title((data.get("content") or {}).get("contentTitle"))
            except Exception:
                title = ""
        # Stack endpoint often returns only a list of items and no stack title.
        if not title and rk_kind == "stack":
            items = data.get("content") or []
            if isinstance(items, list) and items:
                first = items[0] if isinstance(items[0], dict) else {}
                first_title = ""
                try:
                    first_title = _clean_page_title(first.get("text"))
                except Exception:
                    first_title = ""
                if not first_title:
                    try:
                        first_title = _clean_page_title((first.get("content") or {}).get("contentTitle"))
                    except Exception:
                        first_title = ""
                if first_title:
                    title = first_title
                else:
                    try:
                        title = f"Rokfin stack {rk_num} ({len(items)} items)"
                    except Exception:
                        title = f"Rokfin stack {rk_num}"
            elif rk_num:
                title = f"Rokfin stack {rk_num}"
        out["title"] = title or ""

        username = ""
        try:
            username = str((data.get("createdBy") or {}).get("username") or "").strip()
        except Exception:
            username = ""
        if not username:
            try:
                username = str((data.get("creator") or {}).get("username") or "").strip()
            except Exception:
                username = ""
        if not username and rk_kind == "stack":
            try:
                items = data.get("content") or []
                if isinstance(items, list) and items:
                    first = items[0] if isinstance(items[0], dict) else {}
                    username = str((first.get("createdBy") or {}).get("username") or (first.get("creator") or {}).get("username") or "").strip()
            except Exception:
                username = ""
        if username:
            out["source_subscribe_url"] = f"https://rokfin.com/{username}"
    except Exception:
        return out

    return out


def _rokfin_public_content_access_state(content_id, timeout: int = 10) -> dict:
    """Best-effort anonymous access state for a Rokfin content id."""
    out = {
        "is_authorized": None,
        "has_content": None,
        "offers": False,
    }
    try:
        cid = str(int(str(content_id or "").strip()))
    except Exception:
        return out

    api_url = f"{_ROKFIN_PUBLIC_API_BASE}/content/{cid}"
    try:
        resp = utils.safe_requests_get(api_url, timeout=timeout)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return out
        data = resp.json() if hasattr(resp, "json") else {}
        if not isinstance(data, dict):
            return out
        auth = data.get("is_authorized")
        if isinstance(auth, bool):
            out["is_authorized"] = auth
        elif auth is not None:
            out["is_authorized"] = bool(auth)
        out["has_content"] = isinstance(data.get("content"), dict)
        out["offers"] = bool(data.get("offers"))
    except Exception:
        return out
    return out


def _rokfin_hls_url_from_public_metadata(data: dict) -> str:
    """Extract a best-effort HLS URL from Rokfin post/stream public metadata."""
    if not isinstance(data, dict):
        return ""
    content = data.get("content") or {}
    if not isinstance(content, dict):
        content = {}

    content_url = str(content.get("contentUrl") or data.get("url") or "").strip()
    if content_url and content_url.lower() != "fake.m3u8":
        return content_url

    # Mirror yt-dlp fallback: derive stream.v.rokfin m3u8 from storyboard.vtt.
    timeline_url = str(content.get("timelineUrl") or data.get("timelineUrl") or "").strip()
    if timeline_url:
        m = re.search(r"https?://[^/]+/([^/]+)/storyboard\.vtt(?:\?.*)?$", timeline_url, re.I)
        if m and str(m.group(1) or "").strip():
            return f"https://stream.v.rokfin.com/{m.group(1)}.m3u8"
    return ""


def probe_rokfin_public_playback(url: str, timeout: int = 10) -> dict:
    """Best-effort Rokfin playback probe used after yt-dlp failures.

    Returns a dict with:
      - ok (bool)
      - media_url (str)
      - title (str)
      - source_subscribe_url (str)
      - http_headers (dict)
      - reason (str): auth_required, invalid_playback_id, no_content_url, ...
      - detail (str)
    """
    out = {
        "ok": False,
        "media_url": "",
        "title": "",
        "source_subscribe_url": "",
        "http_headers": {},
        "reason": "",
        "detail": "",
    }
    rk_id = _rokfin_public_id_from_url(url)
    if not rk_id:
        out["reason"] = "not_rokfin"
        return out

    try:
        timeout = max(4, min(30, int(timeout or 10)))
    except Exception:
        timeout = 10

    api_url = f"{_ROKFIN_PUBLIC_API_BASE}/{rk_id}"
    try:
        resp = utils.safe_requests_get(api_url, timeout=timeout)
        status = int(getattr(resp, "status_code", 0) or 0)
        if status != 200:
            out["reason"] = "metadata_http_error"
            out["detail"] = f"Rokfin public metadata returned HTTP {status}"
            return out
        data = resp.json() if hasattr(resp, "json") else {}
    except Exception as e:
        out["reason"] = "metadata_error"
        out["detail"] = str(e)
        return out

    if not isinstance(data, dict):
        out["reason"] = "metadata_parse_error"
        out["detail"] = "Rokfin public metadata was not a JSON object"
        return out

    try:
        out["title"] = _clean_page_title(data.get("title")) or _clean_page_title(
            (data.get("content") or {}).get("contentTitle")
        )
    except Exception:
        out["title"] = ""

    try:
        username = str((data.get("createdBy") or {}).get("username") or (data.get("creator") or {}).get("username") or "").strip()
        if username:
            out["source_subscribe_url"] = f"https://rokfin.com/{username}"
    except Exception:
        pass

    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    content_id = ""
    try:
        raw_content_id = content.get("contentId") or data.get("contentId")
        if raw_content_id is not None:
            content_id = str(int(raw_content_id))
    except Exception:
        content_id = ""

    access = {}
    if content_id:
        try:
            access = _rokfin_public_content_access_state(content_id, timeout=min(timeout, 15))
        except Exception:
            access = {}
        if access.get("is_authorized") is False and access.get("has_content") is False:
            out["reason"] = "auth_required"
            out["detail"] = "Rokfin reports anonymous playback is not authorized for this content"
            return out

    media_url = _rokfin_hls_url_from_public_metadata(data)
    if not media_url:
        out["reason"] = "no_content_url"
        out["detail"] = "Rokfin public metadata did not include a playable stream URL"
        return out

    probe_headers = {
        "User-Agent": utils.HEADERS.get("User-Agent", ""),
        "Referer": "https://rokfin.com/",
        "Origin": "https://rokfin.com",
        "Accept": "*/*",
    }

    try:
        probe_resp = utils.safe_requests_get(
            media_url,
            timeout=min(timeout, 15),
            allow_redirects=True,
            headers={**probe_headers, "Range": "bytes=0-1024"},
        )
        probe_status = int(getattr(probe_resp, "status_code", 0) or 0)
        probe_url = str(getattr(probe_resp, "url", "") or media_url).strip() or media_url
        try:
            body_text = str(getattr(probe_resp, "text", "") or "")
        except Exception:
            body_text = ""
        body_prefix = body_text[:512]
        body_lower = body_prefix.lower()
        content_type = str(getattr(probe_resp, "headers", {}).get("content-type") or "").lower()

        looks_hls = (
            "mpegurl" in content_type
            or body_lower.lstrip().startswith("#extm3u")
            or probe_url.lower().endswith(".m3u8")
        )
        if probe_status in (200, 206) and looks_hls:
            out["ok"] = True
            out["media_url"] = probe_url
            out["http_headers"] = probe_headers
            return out

        if probe_status in (401, 403):
            out["reason"] = "auth_required"
            out["detail"] = f"Rokfin stream returned HTTP {probe_status}"
            return out
        if probe_status == 404 and "invalid playback id" in body_lower:
            out["reason"] = "invalid_playback_id"
            out["detail"] = "Rokfin returned an invalid playback ID for this post"
            return out

        out["reason"] = "stream_http_error"
        out["detail"] = f"Rokfin stream probe returned HTTP {probe_status}"
        return out
    except Exception as e:
        out["reason"] = "stream_probe_error"
        out["detail"] = str(e)
        return out


def _fetch_url_title_from_html(url: str, timeout: int = 8) -> str:
    """Best-effort webpage title fallback for search results with URL-only entries."""
    try:
        timeout = max(3, min(30, int(timeout or 8)))
    except Exception:
        timeout = 8

    try:
        resp = utils.safe_requests_get(url, timeout=timeout, allow_redirects=True)
        html = getattr(resp, "text", "") or ""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")

        for attrs in (
            {"property": "og:title"},
            {"name": "twitter:title"},
            {"property": "twitter:title"},
        ):
            try:
                tag = soup.find("meta", attrs=attrs)
                if tag:
                    val = _clean_page_title(tag.get("content"))
                    if val:
                        return val
            except Exception:
                continue

        try:
            if soup.title and soup.title.string:
                val = _clean_page_title(soup.title.string)
                if val:
                    return val
        except Exception:
            pass
    except Exception:
        pass

    return ""


def _youtube_oembed_title(url: str, timeout: int = 4) -> str:
    """Fast YouTube title lookup for direct video URLs (used by UI enrichment)."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    if not _is_youtube_host(host):
        return ""
    try:
        timeout = max(2, min(15, int(timeout or 4)))
    except Exception:
        timeout = 4

    try:
        resp = utils.safe_requests_get(
            "https://www.youtube.com/oembed",
            params={"url": raw, "format": "json"},
            timeout=timeout,
        )
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return ""
        data = resp.json() if hasattr(resp, "json") else {}
        if not isinstance(data, dict):
            return ""
        return _clean_page_title(data.get("title"))
    except Exception:
        return ""


def resolve_quick_url_title(url: str, timeout: int = 4) -> str:
    """Fast title lookup for common URL-only rows before heavier yt-dlp enrichment."""
    t = _youtube_oembed_title(url, timeout=timeout)
    if t:
        return t
    try:
        rk = _rokfin_public_api_enrichment(url, timeout=max(3, min(int(timeout or 4), 8)))
    except Exception:
        rk = {}
    if isinstance(rk, dict):
        t = str(rk.get("title") or "").strip()
        if t:
            return t
    return ""


@lru_cache(maxsize=4096)
def _resolve_quick_url_title_cached(url: str) -> str:
    """Cached quick title lookup for repeated wrapper URLs across searches/sites."""
    try:
        return str(resolve_quick_url_title(url, timeout=4) or "").strip()
    except Exception:
        return ""


def _supports_quick_title_resolution(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    host = host[4:] if host.startswith("www.") else host
    return _is_youtube_host(host) or _host_matches(host, "rokfin.com")


def supports_quick_url_title(url: str) -> bool:
    """True when resolve_quick_url_title() has a cheap HTTP fast path for `url`.

    Lets the GUI queue quick title enrichment only for rows where a single
    lightweight lookup (YouTube oEmbed / Rokfin public API) can succeed, instead
    of burning queue slots on unsupported hosts.
    """
    return _supports_quick_title_resolution(url)


def _prefetch_quick_titles_for_entries(entries, limit: int = 10) -> dict[str, str]:
    """Resolve quick titles concurrently for the first `limit` URL-only entries."""
    try:
        limit = max(1, min(500, int(limit or 10)))
    except Exception:
        limit = 10

    candidates: list[str] = []
    seen_urls: set[str] = set()

    for entry in (entries or []):
        if len(candidates) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        if str(entry.get("title") or "").strip():
            continue
        url = _pick_ytdlp_search_entry_url(entry)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if not _supports_quick_title_resolution(url):
            continue
        candidates.append(url)

    if not candidates:
        return {}

    out: dict[str, str] = {u: "" for u in candidates}
    max_workers = max(1, min(_QUICK_TITLE_PREFETCH_MAX_WORKERS, len(candidates)))

    if max_workers <= 1 or len(candidates) <= 1:
        for u in candidates:
            try:
                out[u] = str(_resolve_quick_url_title_cached(u) or "").strip()
            except Exception:
                out[u] = ""
        return out

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {pool.submit(_resolve_quick_url_title_cached, u): u for u in candidates}
            for fut in concurrent.futures.as_completed(list(future_map.keys())):
                u = future_map.get(fut) or ""
                if not u:
                    continue
                try:
                    out[u] = str(fut.result() or "").strip()
                except Exception:
                    out[u] = ""
    except Exception:
        # Fallback to serial if threadpool setup fails.
        for u in candidates:
            try:
                out[u] = str(_resolve_quick_url_title_cached(u) or "").strip()
            except Exception:
                out[u] = ""

    return out


def _extract_ytdlp_info_for_url(url: str, timeout: int = 10):
    """Best-effort yt-dlp info extraction for a URL (used by search enrichment)."""
    target_url = normalize_ytdlp_single_item_url(url)
    if not target_url:
        return None

    try:
        timeout = max(4, min(45, int(timeout or 10)))
    except Exception:
        timeout = 10

    try:
        import yt_dlp
        from core.dependency_check import _get_startup_info
        parsed = None
        origin = None
        try:
            parsed = urlparse(target_url)
            if parsed.scheme and parsed.netloc:
                origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            parsed = None
            origin = None

        req_headers = {
            "User-Agent": utils.HEADERS.get("User-Agent", ""),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if origin:
            req_headers["Origin"] = origin

        class _QuietLogger:
            def debug(self, _msg):
                return

            def warning(self, _msg):
                return

            def error(self, _msg):
                return

        base_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "socket_timeout": timeout,
            "http_headers": req_headers,
            "user_agent": req_headers.get("User-Agent", ""),
            "referer": target_url,
            "noprogress": True,
            "color": "never",
            "geo_bypass": True,
            "logger": _QuietLogger(),
        }
        if platform.system().lower() == "windows":
            try:
                base_opts["subprocess_startupinfo"] = _get_startup_info()
            except Exception:
                pass

        attempts = [("base", None)]
        try:
            for source in (get_ytdlp_cookie_sources(target_url) or []):
                attempts.append(("cookies", source))
        except Exception:
            pass

        tried_sources: list[tuple] = []
        for kind, source in attempts:
            opts = dict(base_opts)
            if kind == "cookies" and source:
                if source in tried_sources:
                    continue
                tried_sources.append(source)
                opts["cookiesfrombrowser"] = source
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(target_url, download=False)
                if isinstance(info, dict):
                    return info
            except Exception:
                continue
    except Exception:
        pass

    return None


def _pick_primary_ytdlp_info_entry(info) -> dict | None:
    if not isinstance(info, dict):
        return None
    if "entries" not in info:
        return info
    try:
        for entry in (info.get("entries") or []):
            if isinstance(entry, dict):
                return entry
    except Exception:
        pass
    return info


def resolve_ytdlp_url_enrichment(url: str, timeout: int = 10) -> dict:
    """Resolve title + subscribe targets for a direct URL (best-effort)."""
    target_url = str(url or "").strip()
    out = {
        "title": "",
        "native_subscribe_url": "",
        "source_subscribe_url": "",
        "owner_label": "",
    }
    if not target_url:
        return out

    try:
        timeout = max(4, min(45, int(timeout or 10)))
    except Exception:
        timeout = 10

    info = _extract_ytdlp_info_for_url(target_url, timeout=timeout)
    if isinstance(info, dict):
        primary = _pick_primary_ytdlp_info_entry(info) or info
        try:
            title = _clean_page_title(primary.get("title") if isinstance(primary, dict) else info.get("title"))
            if title:
                out["title"] = title
        except Exception:
            pass
        try:
            info_url = ""
            if isinstance(primary, dict):
                info_url = str(primary.get("webpage_url") or primary.get("url") or "").strip()
            if not info_url:
                info_url = target_url
            kind = _infer_ytdlp_search_result_kind(info_url, primary if isinstance(primary, dict) else {}, site_id="")
            out["owner_label"] = _extract_ytdlp_search_entry_owner_label(
                primary if isinstance(primary, dict) else {},
                info_url,
                allow_oembed=True,
            )
            native_url, source_url = _derive_subscribe_targets_for_search_result(
                info_url,
                primary if isinstance(primary, dict) else {},
                kind,
                "",
            )
            out["native_subscribe_url"] = str(native_url or "").strip()
            out["source_subscribe_url"] = str(source_url or "").strip()
        except Exception:
            pass

    # 1.5) Rokfin public API fallback (works even when page HTML is generic and yt-dlp
    # cannot extract due to premium/auth restrictions).
    if (not out["title"]) or (not out["source_subscribe_url"]):
        try:
            rk = _rokfin_public_api_enrichment(target_url, timeout=min(timeout, 15))
        except Exception:
            rk = {}
        if isinstance(rk, dict):
            if not out["title"]:
                out["title"] = str(rk.get("title") or "").strip()
            if not out["native_subscribe_url"]:
                out["native_subscribe_url"] = str(rk.get("native_subscribe_url") or "").strip()
            if not out["source_subscribe_url"]:
                out["source_subscribe_url"] = str(rk.get("source_subscribe_url") or "").strip()
            if not out["owner_label"]:
                out["owner_label"] = str(rk.get("owner_label") or "").strip()

    if not out["title"]:
        out["title"] = _fetch_url_title_from_html(target_url, timeout=min(timeout, 12))
    return out


def resolve_ytdlp_url_title(url: str, timeout: int = 10) -> str:
    """Resolve a human-readable title for a direct media/page URL.

    Used to enrich query-search rows from extractors that return URL-only results
    (e.g. Yahoo Video / some Rokfin search results).
    """
    try:
        return str((resolve_ytdlp_url_enrichment(url, timeout=timeout) or {}).get("title") or "").strip()
    except Exception:
        return ""


def _native_youtube_feed_from_search_entry(url: str, entry: dict, kind: str, site_id: str) -> str:
    sid = str(site_id or "").strip().lower()
    if sid not in ("ytsearch", "youtube"):
        return ""
    if not isinstance(entry, dict):
        return ""

    if kind == "playlist":
        playlist_id = str(entry.get("playlist_id") or "").strip()
        if not playlist_id:
            try:
                playlist_id = _youtube_playlist_id_from_url(url)
            except Exception:
                playlist_id = ""
        if playlist_id:
            return f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"

    if kind == "user":
        channel_id = str(entry.get("channel_id") or "").strip()
        if channel_id:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    return ""


def _choose_entry_subscribe_source_url(entry: dict, site_id: str | None = None) -> str:
    if not isinstance(entry, dict):
        return ""

    # Prefer explicit publisher/channel URLs over the media URL.
    for key in ("channel_url", "uploader_url", "creator_url", "artist_url", "playlist_url"):
        cand = str(entry.get(key) or "").strip()
        if cand and _is_http_like_url(cand):
            return cand

    sid = str(site_id or "").strip().lower()
    if sid in ("ytsearch", "youtube", "yvsearch", "yahoo"):
        channel_id = str(entry.get("channel_id") or "").strip()
        if channel_id:
            return f"https://www.youtube.com/channel/{channel_id}"
        uploader_url = str(entry.get("uploader_url") or "").strip()
        if uploader_url and _is_http_like_url(uploader_url):
            return uploader_url

    return ""


def _derive_subscribe_targets_for_search_result(
    url: str,
    entry: dict,
    kind: str,
    site_id: str,
) -> tuple[str, str]:
    """Return (native_subscribe_url, source_subscribe_url) for a search result."""
    native_feed_url = ""
    source_subscribe_url = ""

    try:
        result_url = str(url or "").strip()
    except Exception:
        result_url = ""
    result_kind = str(kind or "").strip().lower()
    sid = str(site_id or "").strip()

    if result_kind == "feed":
        if _looks_like_feed_url(result_url):
            return result_url, result_url
        return "", result_url if _is_http_like_url(result_url) else ""

    if result_kind in ("user", "playlist"):
        source_subscribe_url = result_url if _is_http_like_url(result_url) else ""
        try:
            native_feed_url = str(_native_youtube_feed_from_search_entry(result_url, entry, result_kind, sid) or "").strip()
            if not native_feed_url and source_subscribe_url:
                native_feed_url = str(get_ytdlp_feed_url(source_subscribe_url) or "").strip()
        except Exception:
            native_feed_url = ""

        if not source_subscribe_url and native_feed_url:
            source_subscribe_url = result_url if _is_http_like_url(result_url) else ""
        elif source_subscribe_url and not native_feed_url:
            try:
                if not is_ytdlp_supported(source_subscribe_url):
                    source_subscribe_url = ""
            except Exception:
                source_subscribe_url = ""
        return native_feed_url, source_subscribe_url

    # Media results can often be subscribed via uploader/channel/profile pages.
    if result_kind == "media":
        source_subscribe_url = _choose_entry_subscribe_source_url(entry, site_id=sid)
        # If the row URL itself is already a subscribable page, use it as source fallback.
        if not source_subscribe_url and _is_http_like_url(result_url):
            media_kind = _infer_ytdlp_search_result_kind(result_url, entry or {}, site_id=sid)
            if media_kind in ("user", "playlist", "feed"):
                source_subscribe_url = result_url
                result_kind = media_kind

        if source_subscribe_url:
            try:
                native_feed_url = str(get_ytdlp_feed_url(source_subscribe_url) or "").strip()
            except Exception:
                native_feed_url = ""
            if not native_feed_url:
                try:
                    native_feed_url = str(get_social_feed_url(source_subscribe_url) or "").strip()
                except Exception:
                    native_feed_url = ""
        return native_feed_url, source_subscribe_url

    return "", ""


def _normalize_ytdlp_search_entries(
    entries,
    site: dict,
    limit: int = 10,
    *,
    quick_title_limit: int = 0,
) -> list[dict]:
    out: list[dict] = []
    seen_urls: set[str] = set()
    site_id = str((site or {}).get("id") or "").strip()
    search_site_label = str((site or {}).get("label") or site_id or "yt-dlp").strip()

    try:
        limit = max(1, min(500, int(limit or 10)))
    except Exception:
        limit = 10

    try:
        quick_title_limit = max(0, min(limit, int(quick_title_limit or 0)))
    except Exception:
        quick_title_limit = 0

    quick_title_map = {}
    if quick_title_limit > 0:
        try:
            quick_title_map = _prefetch_quick_titles_for_entries(entries, limit=quick_title_limit)
        except Exception:
            quick_title_map = {}

    for entry in (entries or []):
        if not isinstance(entry, dict):
            continue

        url = _pick_ytdlp_search_entry_url(entry)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        display_site_label = _display_site_label_from_result_url(url, fallback_label=search_site_label) or search_site_label
        kind = _infer_ytdlp_search_result_kind(url, entry, site_id=site_id)
        raw_title = str(entry.get("title") or "").strip()
        # Some flat-playlist entries carry a junk title equal to the video id or
        # the URL itself; treat those as missing so real enrichment can run.
        if raw_title:
            entry_id = str(entry.get("id") or "").strip()
            if raw_title == url or (entry_id and raw_title == entry_id):
                raw_title = ""
        title_is_fallback = False
        if raw_title:
            title = raw_title
        else:
            quick_title = str((quick_title_map or {}).get(str(url or "")) or "").strip()
            if quick_title:
                title = quick_title
                title_is_fallback = False
            else:
                title = _friendly_title_fallback_from_url(url, site_label=display_site_label) or url
                title_is_fallback = (title != url)
        try:
            native_feed_url, source_subscribe_url = _derive_subscribe_targets_for_search_result(
                url,
                entry,
                kind,
                site_id,
            )
        except Exception:
            native_feed_url, source_subscribe_url = "", ""

        out.append(
            {
                "title": title,
                "detail": _build_ytdlp_search_result_detail(entry, display_site_label, kind),
                "url": url,
                "site": display_site_label,
                "site_id": site_id,
                "kind": kind,
                "play_count": _extract_ytdlp_search_entry_play_count(entry),
                "_title_is_fallback": bool(title_is_fallback),
                "native_subscribe_url": native_feed_url,
                "source_subscribe_url": source_subscribe_url,
            }
        )
        if len(out) >= limit:
            break

    return out


def _run_ytdlp_query_search(search_key: str, term: str, limit: int = 10, timeout: int = 15):
    query = str(term or "").strip()
    sk = str(search_key or "").strip()
    if not query or not sk:
        return []

    try:
        limit = max(1, min(500, int(limit or 10)))
    except Exception:
        limit = 10
    try:
        timeout = max(5, min(90, int(timeout or 15)))
    except Exception:
        timeout = 15

    try:
        from core.dependency_check import _get_startup_info

        creationflags = 0
        if platform.system().lower() == "windows":
            creationflags = 0x08000000

        cmd = [
            _resolve_ytdlp_cli_path(),
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            str(limit),
            f"{sk}{limit}:{query}",
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=_get_startup_info(),
            timeout=timeout,
        )
        rc = getattr(res, "returncode", None)
        if rc is None or int(rc) != 0:
            return []
        stdout = getattr(res, "stdout", b"") or b""
        if not stdout:
            return []
        data = json.loads(stdout)
        if isinstance(data, dict):
            return list(data.get("entries") or [])
        if isinstance(data, list):
            return list(data)
        return []
    except Exception:
        return []


def _run_ytdlp_url_search(url_template: str, term: str, limit: int = 10, timeout: int = 15):
    """Search a site via its on-site search-results page (flat-playlist extract).

    For sites without a yt-dlp query-search key (e.g. adult sites): build the
    search-results URL from ``{query}`` and let yt-dlp enumerate it as a playlist.
    """
    query = str(term or "").strip()
    tmpl = str(url_template or "").strip()
    if not query or not tmpl or "{query}" not in tmpl:
        return []

    try:
        limit = max(1, min(500, int(limit or 10)))
    except Exception:
        limit = 10
    try:
        timeout = max(5, min(90, int(timeout or 15)))
    except Exception:
        timeout = 15

    url = tmpl.replace("{query}", quote(query))

    try:
        from core.dependency_check import _get_startup_info

        creationflags = 0
        if platform.system().lower() == "windows":
            creationflags = 0x08000000

        cmd = [
            _resolve_ytdlp_cli_path(),
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            str(limit),
            url,
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=_get_startup_info(),
            timeout=timeout,
        )
        rc = getattr(res, "returncode", None)
        if rc is None or int(rc) != 0:
            return []
        stdout = getattr(res, "stdout", b"") or b""
        if not stdout:
            return []
        data = json.loads(stdout)
        if isinstance(data, dict):
            return list(data.get("entries") or [])
        if isinstance(data, list):
            return list(data)
        return []
    except Exception:
        return []


def search_ytdlp_site(term: str, site: dict, limit: int = 10, timeout: int = 15) -> list[dict]:
    """Search a single yt-dlp search site and normalize results for the GUI.

    Sites expose either a query-search key (``search_key``, e.g. ``ytsearch``) or,
    for sites yt-dlp can't query-search, a ``search_url_template`` whose results
    page is enumerated instead.
    """
    if not isinstance(site, dict):
        return []
    provider = str(site.get("search_provider") or "").strip().lower()
    if provider == "mixcloud":
        return search_mixcloud_media(str(term or ""), limit=limit, timeout=timeout)
    url_template = str(site.get("search_url_template") or "").strip()
    if url_template:
        entries = _run_ytdlp_url_search(
            url_template,
            str(term or ""),
            limit=limit,
            timeout=timeout,
        )
    else:
        entries = _run_ytdlp_query_search(
            str(site.get("search_key") or ""),
            str(term or ""),
            limit=limit,
            timeout=timeout,
        )
    return _normalize_ytdlp_search_entries(entries, site=site, limit=limit)


def canonical_search_result_key(item: dict) -> str:
    """Stable identity for a search result, for cross-site dedupe.

    Collapses the same underlying video seen from different search backends
    (e.g. a YouTube video returned by both YouTube and a wrapper site) so the
    results list shows each item once. YouTube is keyed by video id regardless
    of surrounding URL params/host; other sites fall back to their normalized
    URL, so only genuine exact-URL duplicates collapse there.
    """
    url = str((item or {}).get("url") or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return url.lower()

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if host in ("youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
        video_id = ""
        try:
            if host == "youtu.be":
                video_id = (parsed.path or "").strip("/").split("/")[0]
            else:
                path = parsed.path or ""
                if "/shorts/" in path:
                    video_id = path.split("/shorts/", 1)[1].split("/")[0]
                elif "/embed/" in path:
                    video_id = path.split("/embed/", 1)[1].split("/")[0]
                else:
                    video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        except Exception:
            video_id = ""
        video_id = str(video_id or "").strip()
        if video_id:
            return f"youtube:{video_id}"

    path = (parsed.path or "").rstrip("/").lower()
    key = f"{host}{path}"
    query = str(parsed.query or "").strip()
    if query:
        key = f"{key}?{query}"
    return key or url.lower()


def search_result_quality_score(item: dict) -> tuple:
    """Rank duplicate results so the "best" copy is kept.

    Higher is better: a real (non-placeholder) title beats a fallback one, a row
    we can subscribe to beats one we can't, and higher known play counts win.
    """
    it = item or {}
    has_real_title = 1 if (
        str(it.get("title") or "").strip() and not bool(it.get("_title_is_fallback"))
    ) else 0
    has_subscribe = 1 if (
        str(it.get("native_subscribe_url") or "").strip()
        or str(it.get("source_subscribe_url") or "").strip()
    ) else 0
    try:
        play_val = int(it.get("play_count"))
    except Exception:
        play_val = -1
    return (has_real_title, has_subscribe, play_val)


# ---------------------------------------------------------------------------
# Mixcloud (open public API at api.mixcloud.com — no auth required)
# ---------------------------------------------------------------------------

_MIXCLOUD_API = "https://api.mixcloud.com"


@dataclass(frozen=True)
class MediaListingItem:
    """A single enumerated entry for a listing feed (SoundCloud/Mixcloud user or
    playlist), matching the (id/title/url/author/published) contract the local
    provider's refresh path consumes. These play via yt-dlp on activation."""

    url: str
    title: str
    author: str | None = None
    published: str | None = None

    @property
    def id(self) -> str:
        return self.url


def is_mixcloud_url(url: str) -> bool:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return False
    return host == "mixcloud.com" or host.endswith(".mixcloud.com")


def _mixcloud_key_from_url(url: str) -> str:
    """Return the Mixcloud API key (path) for a mixcloud.com URL, e.g. '/user/'."""
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return ""
    if not is_mixcloud_url(url):
        return ""
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path


def mixcloud_listing_kind(url: str) -> str:
    """Classify a mixcloud.com URL as 'user', 'playlist', 'cloudcast', or ''."""
    key = _mixcloud_key_from_url(url)
    if not key:
        return ""
    parts = [p for p in key.split("/") if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return "user"
    if len(parts) >= 3 and parts[1] == "playlists":
        return "playlist"
    if len(parts) == 2:
        return "cloudcast"
    return ""


def _mixcloud_api_get(path: str, params: dict | None = None, timeout: float = 15.0):
    url = _MIXCLOUD_API + path
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    try:
        resp = utils.safe_requests_get(url, timeout=timeout, headers={"User-Agent": utils.HEADERS.get("User-Agent", "Mozilla/5.0")})
        if resp is None or getattr(resp, "status_code", 0) != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _mixcloud_pictures_author(obj: dict) -> str:
    try:
        u = obj.get("user") or {}
        return str(u.get("name") or u.get("username") or "").strip()
    except Exception:
        return ""


def search_mixcloud_media(term: str, limit: int = 30, timeout: int = 15) -> list[dict]:
    """Search Mixcloud shows (cloudcasts) for Video Search. Returns result dicts
    matching the normalized yt-dlp search-result schema."""
    query = str(term or "").strip()
    if not query:
        return []
    try:
        limit = max(1, min(100, int(limit or 30)))
    except Exception:
        limit = 30
    data = _mixcloud_api_get("/search/", {"q": query, "type": "cloudcast", "limit": limit}, timeout=timeout)
    rows = (data or {}).get("data") or []
    out: list[dict] = []
    seen: set[str] = set()
    for it in rows:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(it.get("name") or "").strip() or url
        author = _mixcloud_pictures_author(it)
        detail = "Mixcloud" + (f" • {author}" if author else "")
        try:
            play_count = int((it.get("play_count") if it.get("play_count") is not None else it.get("listener_count")) or 0) or None
        except Exception:
            play_count = None
        user_url = ""
        try:
            u = it.get("user") or {}
            user_url = str(u.get("url") or "").strip()
        except Exception:
            user_url = ""
        out.append(
            {
                "title": title,
                "detail": detail,
                "url": url,
                "site": "Mixcloud",
                "site_id": "mixcloud",
                "kind": "media",
                "play_count": play_count,
                "_title_is_fallback": False,
                "native_subscribe_url": "",
                "source_subscribe_url": user_url,
            }
        )
        if len(out) >= limit:
            break
    return out


def search_mixcloud_feeds(term: str, limit: int = 20, timeout: int = 15) -> list[dict]:
    """Find Mixcloud users (and their playlists) subscribable as feeds.

    Returns feed-dialog result dicts {title, detail, url, kind}. The url is a
    Mixcloud user or playlist page, enumerated via the Mixcloud API on refresh.
    """
    query = str(term or "").strip()
    if not query:
        return []
    try:
        limit = max(1, min(50, int(limit or 20)))
    except Exception:
        limit = 20

    out: list[dict] = []
    seen: set[str] = set()

    users = ((_mixcloud_api_get("/search/", {"q": query, "type": "user", "limit": limit}, timeout=timeout) or {}).get("data")) or []
    for u in users:
        if not isinstance(u, dict):
            continue
        url = str(u.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        name = str(u.get("name") or u.get("username") or "").strip() or url
        try:
            followers = int(u.get("follower_count") or 0)
        except Exception:
            followers = 0
        detail = "Mixcloud user" + (f" • {followers:,} followers" if followers else "")
        out.append({"title": name, "detail": detail, "url": url, "kind": "user"})

        # Surface a few of this user's playlists too, since Mixcloud playlists are
        # per-user (there is no global playlist search).
        key = _mixcloud_key_from_url(url)
        if key:
            pls = ((_mixcloud_api_get(f"{key}playlists/", {"limit": 3}, timeout=timeout) or {}).get("data")) or []
            for pl in pls:
                if not isinstance(pl, dict):
                    continue
                pl_url = str(pl.get("url") or "").strip()
                if not pl_url or pl_url in seen:
                    continue
                seen.add(pl_url)
                pl_name = str(pl.get("name") or "").strip() or pl_url
                out.append(
                    {
                        "title": f"{pl_name} ({name})",
                        "detail": "Mixcloud playlist",
                        "url": pl_url,
                        "kind": "playlist",
                    }
                )
        if len(out) >= limit:
            break
    return out


def fetch_mixcloud_listing(url: str, max_items: int = 60, timeout: float = 20.0):
    """Enumerate a Mixcloud user's shows or a playlist's items for refresh.

    Returns (feed_title, list[MediaListingItem]).
    """
    try:
        max_items = max(1, min(200, int(max_items or 60)))
    except Exception:
        max_items = 60
    kind = mixcloud_listing_kind(url)
    key = _mixcloud_key_from_url(url)
    if not key or kind not in ("user", "playlist"):
        return None, []

    feed_title = None
    meta = _mixcloud_api_get(key, timeout=timeout)
    if isinstance(meta, dict):
        feed_title = str(meta.get("name") or "").strip() or None
        if kind == "playlist":
            owner = _mixcloud_pictures_author(meta)
            if feed_title and owner:
                feed_title = f"{feed_title} ({owner})"

    list_path = f"{key}cloudcasts/" if kind == "user" else f"{key}cloudcasts/"
    items: list[MediaListingItem] = []
    remaining = max_items
    next_params = {"limit": min(100, remaining)}
    guard = 0
    while remaining > 0 and guard < 6:
        guard += 1
        data = _mixcloud_api_get(list_path, next_params, timeout=timeout)
        rows = (data or {}).get("data") or []
        if not rows:
            break
        for it in rows:
            if not isinstance(it, dict):
                continue
            it_url = str(it.get("url") or "").strip()
            if not it_url:
                continue
            title = str(it.get("name") or "").strip() or it_url
            author = _mixcloud_pictures_author(it) or (feed_title or "Mixcloud")
            published = str(it.get("created_time") or "").strip()
            items.append(MediaListingItem(url=it_url, title=title, author=author, published=published))
            if len(items) >= max_items:
                break
        remaining = max_items - len(items)
        # Follow paging if the API provided a next cursor.
        paging = (data or {}).get("paging") or {}
        nxt = str(paging.get("next") or "").strip()
        if not nxt or len(items) >= max_items:
            break
        try:
            q = parse_qs(urlparse(nxt).query)
            next_params = {"limit": min(100, remaining)}
            if q.get("offset"):
                next_params["offset"] = q["offset"][0]
        except Exception:
            break
    return feed_title, items


# ---------------------------------------------------------------------------
# SoundCloud (internal api-v2 with a client_id fetched from SoundCloud's own JS
# at runtime — SoundCloud closed public API registration, and this is the same
# approach yt-dlp uses. Nothing is hardcoded; a rotated id is simply re-fetched.)
# ---------------------------------------------------------------------------

_SOUNDCLOUD_API_V2 = "https://api-v2.soundcloud.com"
_SOUNDCLOUD_CLIENT_ID = None
_SOUNDCLOUD_CLIENT_ID_LOCK = threading.Lock()


def is_soundcloud_url(url: str) -> bool:
    """True for SoundCloud *web-app* URLs (the /user, /user/track, /sets pages).

    Excludes ``feeds.soundcloud.com``, which serves ordinary podcast RSS
    (``/users/soundcloud:users:<id>/sounds.rss``, what iTunes/Apple Podcasts hand
    back for a SoundCloud-hosted show). Those are complete RSS feeds and must go
    through the normal RSS parse path, never the yt-dlp/api-v2 listing enumeration.
    """
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return False
    if host == "feeds.soundcloud.com":
        return False
    return host == "soundcloud.com" or host.endswith(".soundcloud.com")


def soundcloud_listing_kind(url: str) -> str:
    """Classify a soundcloud.com URL as 'user', 'playlist', 'track', or ''."""
    if not is_soundcloud_url(url):
        return ""
    try:
        path = (urlparse(str(url or "")).path or "").strip("/").lower()
    except Exception:
        return ""
    if not path:
        return ""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    if "sets" in parts:
        return "playlist"
    # Reserved SoundCloud sections that are not user profiles.
    if parts[0] in ("you", "search", "discover", "stream", "upload", "settings", "pages", "tags"):
        return ""
    if len(parts) == 1:
        return "user"
    if len(parts) == 2:
        return "track"
    return ""


def _fetch_soundcloud_client_id(timeout: float = 15.0) -> str:
    """Scrape a working client_id from SoundCloud's web assets."""
    headers = {"User-Agent": utils.HEADERS.get("User-Agent", "Mozilla/5.0")}
    try:
        resp = utils.safe_requests_get("https://soundcloud.com/", timeout=timeout, headers=headers)
        if resp is None or getattr(resp, "status_code", 0) != 200:
            return ""
        html = resp.text or ""
    except Exception:
        return ""
    js_urls = re.findall(r"https://[a-z0-9\-]+\.sndcdn\.com/assets/[^\"']+\.js", html)
    # SoundCloud's client_id tends to live in the later-loaded app bundles.
    for js_url in reversed(js_urls):
        try:
            r = utils.safe_requests_get(js_url, timeout=timeout, headers=headers)
            if r is None or getattr(r, "status_code", 0) != 200:
                continue
            m = re.search(r'client_id[:=]"([0-9A-Za-z]{20,})"', r.text or "")
            if m:
                return m.group(1)
        except Exception:
            continue
    return ""


def _get_soundcloud_client_id(timeout: float = 15.0, force_refresh: bool = False) -> str:
    global _SOUNDCLOUD_CLIENT_ID
    with _SOUNDCLOUD_CLIENT_ID_LOCK:
        if _SOUNDCLOUD_CLIENT_ID and not force_refresh:
            return _SOUNDCLOUD_CLIENT_ID
    cid = _fetch_soundcloud_client_id(timeout=timeout)
    if cid:
        with _SOUNDCLOUD_CLIENT_ID_LOCK:
            _SOUNDCLOUD_CLIENT_ID = cid
    return cid


def _soundcloud_api_v2_get(path: str, params: dict, timeout: float = 15.0, _retry: bool = True):
    cid = _get_soundcloud_client_id(timeout=timeout)
    if not cid:
        return None
    q = dict(params or {})
    q["client_id"] = cid
    url = _SOUNDCLOUD_API_V2 + path + "?" + urlencode(q)
    headers = {"User-Agent": utils.HEADERS.get("User-Agent", "Mozilla/5.0")}
    try:
        resp = utils.safe_requests_get(url, timeout=timeout, headers=headers)
        status = getattr(resp, "status_code", 0) if resp is not None else 0
        if status == 200:
            return resp.json()
        # A 401/403 usually means the cached client_id rotated; refresh once.
        if status in (401, 403) and _retry:
            if _get_soundcloud_client_id(timeout=timeout, force_refresh=True):
                return _soundcloud_api_v2_get(path, params, timeout=timeout, _retry=False)
        return None
    except Exception:
        return None


def search_soundcloud_feeds(term: str, limit: int = 20, timeout: int = 15) -> list[dict]:
    """Find SoundCloud users and playlists subscribable as feeds.

    Returns feed-dialog result dicts {title, detail, url, kind}. The url is a
    SoundCloud user or playlist page, enumerated via yt-dlp on refresh.
    """
    query = str(term or "").strip()
    if not query:
        return []
    try:
        limit = max(1, min(50, int(limit or 20)))
    except Exception:
        limit = 20

    per = max(3, limit // 2)
    out: list[dict] = []
    seen: set[str] = set()

    users = ((_soundcloud_api_v2_get("/search/users", {"q": query, "limit": per}, timeout=timeout) or {}).get("collection")) or []
    for u in users:
        if not isinstance(u, dict):
            continue
        url = str(u.get("permalink_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        name = str(u.get("username") or u.get("permalink") or "").strip() or url
        try:
            followers = int(u.get("followers_count") or 0)
        except Exception:
            followers = 0
        detail = "SoundCloud user" + (f" • {followers:,} followers" if followers else "")
        out.append({"title": name, "detail": detail, "url": url, "kind": "user"})

    playlists = ((_soundcloud_api_v2_get("/search/playlists", {"q": query, "limit": per}, timeout=timeout) or {}).get("collection")) or []
    for pl in playlists:
        if not isinstance(pl, dict):
            continue
        url = str(pl.get("permalink_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        name = str(pl.get("title") or "").strip() or url
        owner = ""
        try:
            owner = str((pl.get("user") or {}).get("username") or "").strip()
        except Exception:
            owner = ""
        try:
            count = int(pl.get("track_count") or 0)
        except Exception:
            count = 0
        detail = "SoundCloud playlist"
        if owner:
            detail += f" • {owner}"
        if count:
            detail += f" • {count} tracks"
        title = f"{name} ({owner})" if owner else name
        out.append({"title": title, "detail": detail, "url": url, "kind": "playlist"})

    return out[:limit]


def _run_ytdlp_flat_listing(url: str, max_items: int = 60, timeout: float = 30.0):
    """Enumerate a yt-dlp-supported listing page (e.g. a SoundCloud user/playlist)
    as a flat playlist. Returns (feed_title, list[MediaListingItem])."""
    target = str(url or "").strip()
    if not target:
        return None, []
    try:
        max_items = max(1, min(300, int(max_items or 60)))
    except Exception:
        max_items = 60
    try:
        timeout = max(10, min(120, float(timeout or 30)))
    except Exception:
        timeout = 30

    try:
        from core.dependency_check import _get_startup_info

        creationflags = 0
        if platform.system().lower() == "windows":
            creationflags = 0x08000000

        cmd = [
            _resolve_ytdlp_cli_path(),
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            str(max_items),
            target,
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=_get_startup_info(),
            timeout=timeout,
        )
        rc = getattr(res, "returncode", None)
        if rc is None or int(rc) != 0 or not getattr(res, "stdout", b""):
            return None, []
        data = json.loads(res.stdout)
    except Exception:
        return None, []

    if not isinstance(data, dict):
        return None, []
    feed_title = str(data.get("title") or data.get("uploader") or "").strip() or None
    default_author = str(data.get("uploader") or data.get("channel") or feed_title or "").strip()
    entries = data.get("entries") or []
    items: list[MediaListingItem] = []
    seen: set[str] = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        it_url = _pick_ytdlp_search_entry_url(e) or str(e.get("url") or "").strip()
        if not it_url or it_url in seen:
            continue
        seen.add(it_url)
        title = str(e.get("title") or "").strip() or it_url
        author = str(e.get("uploader") or e.get("channel") or default_author or "").strip() or None
        ts = e.get("timestamp") or e.get("release_timestamp")
        published = ""
        if ts:
            try:
                published = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))
            except Exception:
                published = ""
        items.append(MediaListingItem(url=it_url, title=title, author=author, published=published))
        if len(items) >= max_items:
            break
    return feed_title, items


def _soundcloud_api_v2_get_next(next_href: str, timeout: float = 15.0):
    """Follow a SoundCloud api-v2 `next_href` pagination cursor.

    `next_href` is an absolute api-v2 URL that already carries a (possibly stale)
    client_id; we re-route it through `_soundcloud_api_v2_get` so the path/params
    are re-signed with a fresh client_id and the 401/403 refresh retry applies.
    """
    raw = str(next_href or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        path = parsed.path or ""
        if not path:
            return None
        params = {k: v[0] for k, v in parse_qs(parsed.query).items() if k != "client_id"}
        return _soundcloud_api_v2_get(path, params, timeout=timeout)
    except Exception:
        return None


def _soundcloud_track_to_item(track: dict, default_author: str = "") -> "MediaListingItem | None":
    """Convert a SoundCloud api-v2 track object into a MediaListingItem.

    The api-v2 track carries a real publish date (`created_at`/`display_date`),
    which the yt-dlp `--flat-playlist` path does not — without it every episode
    normalizes to the year-1 sentinel and never surfaces as new on refresh.
    """
    if not isinstance(track, dict) or str(track.get("kind") or "track") != "track":
        return None
    it_url = str(track.get("permalink_url") or "").strip()
    if not it_url:
        return None
    title = str(track.get("title") or "").strip() or it_url
    author = ""
    try:
        author = str((track.get("user") or {}).get("username") or "").strip()
    except Exception:
        author = ""
    author = author or (str(default_author or "").strip() or None)
    published = str(
        track.get("created_at") or track.get("display_date") or track.get("release_date") or ""
    ).strip()
    return MediaListingItem(url=it_url, title=title, author=author, published=published)


def _fetch_soundcloud_listing_via_api(url: str, kind: str, max_items: int, timeout: float):
    """Enumerate a SoundCloud user/playlist via api-v2 (with real publish dates).

    Returns (feed_title, list[MediaListingItem]); items is empty when the API is
    unavailable (e.g. client_id could not be scraped) so the caller can fall back.
    """
    resolved = _soundcloud_api_v2_get("/resolve", {"url": url}, timeout=timeout)
    if not isinstance(resolved, dict):
        return None, []

    if kind == "user":
        uid = resolved.get("id")
        if not uid:
            return None, []
        feed_title = str(resolved.get("username") or "").strip() or None
        items: list[MediaListingItem] = []
        seen: set[str] = set()
        page = _soundcloud_api_v2_get(
            f"/users/{uid}/tracks",
            {"limit": min(200, max_items), "linked_partitioning": 1},
            timeout=timeout,
        )
        guard = 0
        while isinstance(page, dict) and guard < 8 and len(items) < max_items:
            guard += 1
            for t in (page.get("collection") or []):
                item = _soundcloud_track_to_item(t, feed_title or "")
                if item is None or item.url in seen:
                    continue
                seen.add(item.url)
                items.append(item)
                if len(items) >= max_items:
                    break
            nxt = str(page.get("next_href") or "").strip()
            if not nxt or len(items) >= max_items:
                break
            page = _soundcloud_api_v2_get_next(nxt, timeout=timeout)
        return feed_title, items[:max_items]

    # Playlist / set: the resolve payload carries the ordered track list, but only
    # the leading tracks are hydrated; the rest are {id, kind} stubs we batch-fetch.
    feed_title = str(resolved.get("title") or "").strip() or None
    owner = ""
    try:
        owner = str((resolved.get("user") or {}).get("username") or "").strip()
    except Exception:
        owner = ""
    if feed_title and owner:
        feed_title = f"{feed_title} ({owner})"

    raw_tracks = resolved.get("tracks") or []
    ordered_ids: list[int] = []
    hydrated: dict = {}
    for t in raw_tracks:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        if tid is None:
            continue
        ordered_ids.append(tid)
        if t.get("title") or t.get("permalink_url"):
            hydrated[tid] = t
        if len(ordered_ids) >= max_items:
            break

    stub_ids = [tid for tid in ordered_ids if tid not in hydrated]
    for i in range(0, len(stub_ids), 50):
        batch = stub_ids[i:i + 50]
        data = _soundcloud_api_v2_get(
            "/tracks", {"ids": ",".join(str(x) for x in batch)}, timeout=timeout
        )
        if isinstance(data, list):
            for t in data:
                if isinstance(t, dict) and t.get("id") is not None:
                    hydrated[t.get("id")] = t

    items = []
    seen = set()
    for tid in ordered_ids:
        item = _soundcloud_track_to_item(hydrated.get(tid) or {}, owner)
        if item is None or item.url in seen:
            continue
        seen.add(item.url)
        items.append(item)
        if len(items) >= max_items:
            break
    return feed_title, items


def fetch_soundcloud_listing(url: str, max_items: int = 60, timeout: float = 30.0):
    """Enumerate a SoundCloud user's tracks or a playlist for refresh.

    Uses SoundCloud's api-v2 first so each item carries its real publish date;
    falls back to yt-dlp `--flat-playlist` (dateless) only if the API is
    unavailable. Returns (feed_title, list[MediaListingItem]).
    """
    kind = soundcloud_listing_kind(url)
    if kind not in ("user", "playlist"):
        return None, []
    try:
        max_items = max(1, min(300, int(max_items or 60)))
    except Exception:
        max_items = 60
    try:
        title, items = _fetch_soundcloud_listing_via_api(url, kind, max_items, float(timeout or 30.0))
    except Exception:
        title, items = None, []
    if items:
        return title, items
    return _run_ytdlp_flat_listing(url, max_items=max_items, timeout=timeout)


def _youtube_playlist_id_from_url(url: str) -> str:
    """Extract a YouTube playlist ID from any YouTube URL with a list param."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        if not _is_youtube_host(domain):
            return ""
        playlist_id = str((parse_qs(parsed.query).get("list") or [""])[0] or "").strip()
        if not playlist_id:
            return ""
        # Preserve simple YouTube playlist IDs; ignore obviously malformed values.
        if any(ch.isspace() for ch in playlist_id):
            return ""
        return playlist_id
    except Exception:
        return ""


def _youtube_handle_from_url(url: str) -> str:
    """Extract a YouTube @handle from a profile URL when present."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        domain = parsed.hostname or ""
        if not _is_youtube_host(domain):
            return ""
        m = re.search(r"/@([^/?#]+)", str(parsed.path or ""))
        if not m:
            return ""
        handle = unquote(str(m.group(1) or "")).strip()
        if not handle:
            return ""
        return f"@{handle}"
    except Exception:
        return ""


def _normalize_youtube_handle(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("@"):
        return raw
    if raw.upper().startswith("UC"):
        return ""
    if re.fullmatch(r"[A-Za-z0-9._-]{2,40}", raw):
        return f"@{raw}"
    return ""


def _combine_youtube_owner_name_and_handle(owner_name: str, owner_handle: str) -> str:
    name = str(owner_name or "").strip()
    handle = str(owner_handle or "").strip()
    if name and handle:
        if name.lstrip("@").lower() == handle.lstrip("@").lower():
            return handle
        return f"{name} / {handle}"
    return name or handle


def _youtube_owner_label(entry: dict) -> str:
    """Return a readable source label (channel name and/or @handle) for a result."""
    if not isinstance(entry, dict):
        return ""

    owner_name = ""
    for key in ("channel", "uploader", "playlist_uploader", "artist", "creator"):
        val = str(entry.get(key) or "").strip()
        if val:
            owner_name = val
            break

    owner_handle = ""
    handle_candidates = [
        entry.get("uploader_id"),
        entry.get("channel_handle"),
        _youtube_handle_from_url(entry.get("channel_url")),
        _youtube_handle_from_url(entry.get("uploader_url")),
        _youtube_handle_from_url(entry.get("url")),
        _youtube_handle_from_url(entry.get("webpage_url")),
    ]
    for candidate in handle_candidates:
        handle = _normalize_youtube_handle(candidate)
        if handle:
            owner_handle = handle
            break

    return _combine_youtube_owner_name_and_handle(owner_name, owner_handle)


@lru_cache(maxsize=4096)
def _youtube_owner_label_from_oembed(url: str) -> str:
    """Resolve channel/source label from YouTube oEmbed for playlist/video URLs."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    host = parsed.hostname or ""
    if not _is_youtube_host(host):
        return ""

    try:
        resp = utils.safe_requests_get(
            "https://www.youtube.com/oembed",
            params={"url": raw, "format": "json"},
            timeout=4,
        )
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return ""
        data = resp.json() if hasattr(resp, "json") else {}
        if not isinstance(data, dict):
            return ""
        owner_name = str(data.get("author_name") or "").strip()
        owner_url = str(data.get("author_url") or "").strip()
        if owner_url.startswith("/"):
            owner_url = f"https://www.youtube.com{owner_url}"
        owner_handle = _youtube_handle_from_url(owner_url)
        return _combine_youtube_owner_name_and_handle(owner_name, owner_handle)
    except Exception:
        return ""


def _normalize_youtube_search_text(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", raw)).strip()


def _youtube_query_match_score(title: str, query: str) -> int:
    tnorm = _normalize_youtube_search_text(title)
    qnorm = _normalize_youtube_search_text(query)
    if not tnorm or not qnorm:
        return 0
    score = 0
    if qnorm in tnorm:
        score += 100
    qtokens = [tok for tok in qnorm.split(" ") if len(tok) >= 3]
    if qtokens:
        tset = set(tnorm.split(" "))
        score += sum(6 for tok in qtokens if tok in tset)
    return score


def _youtube_query_prefers_playlists(query: str) -> bool:
    qnorm = _normalize_youtube_search_text(query)
    if not qnorm:
        return False
    return ("playlist" in qnorm) or ("lets play" in qnorm) or ("let s play" in qnorm)


_YOUTUBE_PLAYLIST_OEMBED_LOOKUP_LIMIT = 100
_YOUTUBE_PLAYLIST_OEMBED_LOOKUP_WORKERS = 8
_YOUTUBE_FEED_CHANNEL_LIMIT_RATIO = 0.75


def _youtube_search_entries_to_channel_feeds(entries, limit: int = 10) -> list[dict]:
    """Convert yt-dlp ytsearch entries into unique YouTube channel RSS feed results."""
    out: list[dict] = []
    seen: set[str] = set()
    try:
        limit = max(1, min(200, int(limit or 10)))
    except Exception:
        limit = 10
    ranked: list[tuple[str, int, int, dict]] = []

    for idx, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            continue

        channel_id = str(entry.get("channel_id") or "").strip()
        channel_url = str(entry.get("channel_url") or "").strip()
        entry_url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
        uploader_url = str(entry.get("uploader_url") or "").strip()

        # ytsearch can return a channel item directly or video items that include channel metadata.
        if not channel_url:
            for candidate in (entry_url, uploader_url):
                if not candidate:
                    continue
                try:
                    candidate_parts = urlparse(candidate)
                except Exception:
                    candidate_parts = None
                candidate_path = str(getattr(candidate_parts, "path", "") or "").lower()
                candidate_host = str(getattr(candidate_parts, "hostname", "") or "")
                if _is_youtube_host(candidate_host) and any(
                    p in candidate_path for p in ("/channel/", "/user/", "/@")
                ):
                    channel_url = candidate
                    break

        feed_url = ""
        if channel_id:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        elif channel_url:
            try:
                feed_url = get_ytdlp_feed_url(channel_url) or ""
            except Exception:
                feed_url = ""
        if not feed_url:
            continue

        dedupe_key = channel_id or feed_url

        title = (
            str(entry.get("channel") or "").strip()
            or str(entry.get("uploader") or "").strip()
            or str(entry.get("title") or "").strip()
            or channel_id
            or feed_url
        )
        owner_label = _youtube_owner_label(entry)
        play_count = _extract_ytdlp_search_entry_play_count(entry)
        detail = "YouTube channel"
        if owner_label:
            detail = f"{detail} ({owner_label})"
        if play_count is not None:
            detail = f"{detail} | {int(play_count):,} plays"

        ranked.append(
            (
                dedupe_key,
                idx,
                int(play_count) if play_count is not None else -1,
                {
                    "title": title,
                    "detail": detail,
                    "url": feed_url,
                    "play_count": int(play_count) if play_count is not None else None,
                },
            )
        )

    ranked.sort(key=lambda row: (-row[2], row[1]))
    for dedupe_key, _idx, _play_rank, item in ranked:
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(item)
        if len(out) >= limit:
            break

    return out


def _youtube_search_entries_to_playlist_feeds(entries, limit: int = 10, query: str = "") -> list[dict]:
    """Convert yt-dlp playlist-search entries into YouTube playlist RSS results."""
    out: list[dict] = []
    seen: set[str] = set()
    try:
        limit = max(1, min(200, int(limit or 10)))
    except Exception:
        limit = 10
    ranked: list[tuple[str, int, int, int, dict]] = []

    for idx, entry in enumerate(entries or []):
        if not isinstance(entry, dict):
            continue

        entry_url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
        playlist_id = (
            str(entry.get("playlist_id") or "").strip()
            or _youtube_playlist_id_from_url(entry_url)
        )
        if not playlist_id:
            entry_id = str(entry.get("id") or "").strip()
            if entry_id and not entry_id.startswith("UC"):
                playlist_id = entry_id
        if not playlist_id:
            continue

        feed_url = f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"

        title = (
            str(entry.get("title") or "").strip()
            or playlist_id
        )
        owner_label = _youtube_owner_label(entry)
        play_count = _extract_ytdlp_search_entry_play_count(entry)
        detail = "YouTube playlist"
        if owner_label:
            detail = f"{detail} ({owner_label})"
        if play_count is not None:
            detail = f"{detail} | {int(play_count):,} plays"

        ranked.append(
            (
                playlist_id,
                idx,
                _youtube_query_match_score(title, query),
                int(play_count) if play_count is not None else -1,
                {
                    "title": title,
                    "detail": detail,
                    "url": feed_url,
                    "play_count": int(play_count) if play_count is not None else None,
                    "_owner_lookup_url": entry_url if (not owner_label and entry_url) else "",
                },
            )
        )

    ranked.sort(key=lambda row: (-row[2], -row[3], row[1]))
    for playlist_id, _idx, _match_score, _play_rank, item in ranked:
        if playlist_id in seen:
            continue
        seen.add(playlist_id)
        out.append(item)
        if len(out) >= limit:
            break

    # Keep owner/channel attribution, but run oEmbed lookups in parallel so global
    # feed search remains responsive while still enriching many rows.
    try:
        max_oembed_lookups = max(0, int(_YOUTUBE_PLAYLIST_OEMBED_LOOKUP_LIMIT or 0))
    except Exception:
        max_oembed_lookups = 0
    pending: list[tuple[dict, str]] = []
    for item in out:
        lookup_url = str(item.get("_owner_lookup_url") or "").strip()
        if not lookup_url:
            continue
        pending.append((item, lookup_url))
        if len(pending) >= max_oembed_lookups:
            break

    if pending:
        try:
            max_workers = max(1, min(int(_YOUTUBE_PLAYLIST_OEMBED_LOOKUP_WORKERS or 1), len(pending)))
        except Exception:
            max_workers = min(4, len(pending))
        future_to_item: dict[concurrent.futures.Future, dict] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for item, lookup_url in pending:
                future_to_item[executor.submit(_youtube_owner_label_from_oembed, lookup_url)] = item
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item.get(future)
                if not item:
                    continue
                try:
                    owner_label = str(future.result() or "").strip()
                except Exception:
                    continue
                if not owner_label:
                    continue
                detail = f"YouTube playlist ({owner_label})"
                play_count = item.get("play_count")
                if play_count is not None:
                    detail = f"{detail} | {int(play_count):,} plays"
                item["detail"] = detail

    for item in out:
        item.pop("_owner_lookup_url", None)

    return out


def search_youtube_channels(term: str, limit: int = 10, timeout: int = 15) -> list[dict]:
    """Search YouTube via yt-dlp and return channel RSS feed candidates.

    Results are normalized for the Feed Search dialog and use native YouTube RSS URLs.
    """
    query = str(term or "").strip()
    if not query:
        return []

    try:
        limit = max(1, min(200, int(limit or 10)))
    except Exception:
        limit = 10
    try:
        timeout = max(5, min(60, int(timeout or 15)))
    except Exception:
        timeout = 15

    # Ask for more video results than final channel results to give dedupe room.
    fetch_count = max(limit * 3, 12)

    try:
        from core.dependency_check import _get_startup_info

        creationflags = 0
        if platform.system().lower() == "windows":
            creationflags = 0x08000000

        cmd = [
            _resolve_ytdlp_cli_path(),
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            str(fetch_count),
            f"ytsearch{fetch_count}:{query}",
        ]

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=_get_startup_info(),
            timeout=timeout,
        )
        rc = getattr(res, "returncode", None)
        if rc is None or int(rc) != 0 or not getattr(res, "stdout", None):
            return []

        data = json.loads(res.stdout)
        entries = data.get("entries") if isinstance(data, dict) else []
        return _youtube_search_entries_to_channel_feeds(entries, limit=limit)
    except Exception:
        return []


def _search_youtube_playlists(term: str, limit: int = 10, timeout: int = 15) -> list[dict]:
    """Search YouTube playlists via yt-dlp and return playlist RSS feed candidates."""
    query = str(term or "").strip()
    if not query:
        return []

    try:
        limit = max(1, min(200, int(limit or 10)))
    except Exception:
        limit = 10
    try:
        timeout = max(5, min(60, int(timeout or 15)))
    except Exception:
        timeout = 15

    try:
        from core.dependency_check import _get_startup_info

        creationflags = 0
        if platform.system().lower() == "windows":
            creationflags = 0x08000000

        # YouTube search filter (sp) for "Playlists".
        playlist_filter_sp = "EgIQAw%253D%253D"
        search_url = (
            "https://www.youtube.com/results"
            f"?search_query={quote_plus(query)}&sp={playlist_filter_sp}"
        )
        cmd = [
            _resolve_ytdlp_cli_path(),
            "--dump-single-json",
            "--flat-playlist",
            "--playlist-end",
            str(limit),
            search_url,
        ]

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=_get_startup_info(),
            timeout=timeout,
        )
        rc = getattr(res, "returncode", None)
        if rc is None or int(rc) != 0 or not getattr(res, "stdout", None):
            return []

        data = json.loads(res.stdout)
        entries = data.get("entries") if isinstance(data, dict) else []
        return _youtube_search_entries_to_playlist_feeds(entries, limit=limit, query=query)
    except Exception:
        return []


def _youtube_search_query_variants(term: str, max_variants: int = 6) -> list[str]:
    """Build fallback YouTube search query variants for sparse/misspelled searches."""
    query = " ".join(str(term or "").split())
    if not query:
        return []
    try:
        max_variants = max(1, min(8, int(max_variants or 6)))
    except Exception:
        max_variants = 6

    variants: list[str] = [query]
    seen: set[str] = {query.lower()}

    raw_tokens = re.findall(r"[0-9A-Za-z@#']+", query)
    tokens: list[str] = []
    for raw in raw_tokens:
        token = str(raw or "").strip().strip("'").lower()
        if token:
            tokens.append(token)

    if len(tokens) < 2:
        return variants

    # Retry by dropping one token at a time (starting from the tail) to recover
    # from over-specific queries and single-token spelling mistakes.
    for drop_idx in range(len(tokens) - 1, -1, -1):
        candidate_tokens = [tok for idx, tok in enumerate(tokens) if idx != drop_idx]
        if len(candidate_tokens) < 2:
            continue
        candidate = " ".join(candidate_tokens)
        if candidate in seen:
            continue
        seen.add(candidate)
        variants.append(candidate)
        if len(variants) >= max_variants:
            break

    return variants


def search_youtube_feeds(term: str, limit: int = 100, timeout: int = 15) -> list[dict]:
    """Search YouTube for channel and playlist RSS feed candidates."""
    query = str(term or "").strip()
    if not query:
        return []

    try:
        limit = max(1, min(200, int(limit or 100)))
    except Exception:
        limit = 100
    try:
        timeout = max(5, min(60, int(timeout or 15)))
    except Exception:
        timeout = 15

    # Keep popularity-first ordering while reserving room for playlists so
    # playlist-focused searches remain discoverable in the final top-N.
    try:
        channel_limit = max(1, min(limit, int(round(limit * float(_YOUTUBE_FEED_CHANNEL_LIMIT_RATIO)))))
    except Exception:
        channel_limit = max(1, min(limit, int(round(limit * 0.75))))
    playlist_limit = limit

    out: list[dict] = []
    seen_urls: set[str] = set()

    def _append_query_results(search_query: str) -> int:
        added = 0
        channel_items = []
        playlist_items = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                future_channels = ex.submit(
                    search_youtube_channels,
                    search_query,
                    limit=channel_limit,
                    timeout=timeout,
                )
                future_playlists = ex.submit(
                    _search_youtube_playlists,
                    search_query,
                    limit=playlist_limit,
                    timeout=timeout,
                )
                channel_items = list(future_channels.result() or [])
                playlist_items = list(future_playlists.result() or [])
        except Exception:
            channel_items = list(search_youtube_channels(search_query, limit=channel_limit, timeout=timeout) or [])
            playlist_items = list(_search_youtube_playlists(search_query, limit=playlist_limit, timeout=timeout) or [])

        ranked_items: list[tuple[int, int, int, int, int, dict]] = []
        for idx, item in enumerate(list(channel_items) + list(playlist_items)):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().lower()
            is_playlist = "playlist_id=" in url or "/playlist?" in url
            play_raw = item.get("play_count")
            play_count = None
            if play_raw is not None:
                try:
                    play_count = int(play_raw)
                except Exception:
                    try:
                        play_count = int(float(str(play_raw).strip()))
                    except Exception:
                        play_count = None
            title = str(item.get("title") or "").strip()
            match_score = _youtube_query_match_score(title, search_query)
            ranked_items.append(
                (
                    0 if is_playlist else 1,
                    0 if play_count is not None else 1,
                    -(play_count if play_count is not None else 0),
                    -int(match_score),
                    idx,
                    item,
                )
            )

        ranked_items.sort()
        for _kind_rank, _has_missing_play_count, _neg_play_count, _neg_match_score, _idx, item in ranked_items:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append(item)
            added += 1
            if len(out) >= limit:
                return added
        return added

    for query_variant in _youtube_search_query_variants(query):
        _append_query_results(query_variant)
        if len(out) >= limit:
            break

    return out


def _mastodon_account_url_to_rss(url: str) -> str:
    """Convert a Mastodon account profile URL to its RSS URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return ""
    if (parsed.scheme or "").lower() not in ("http", "https") or not parsed.netloc:
        return ""
    path = str(parsed.path or "").rstrip("/")
    if not path:
        return ""
    low = path.lower()
    if low.endswith(".rss"):
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    if low.startswith("/@") or low.startswith("/users/"):
        return f"{parsed.scheme}://{parsed.netloc}{path}.rss"
    return ""


def _mastodon_tag_url_to_rss(url: str) -> str:
    """Convert a Mastodon hashtag page URL to its RSS URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return ""
    if (parsed.scheme or "").lower() not in ("http", "https") or not parsed.netloc:
        return ""
    path = str(parsed.path or "").rstrip("/")
    if not path:
        return ""
    low = path.lower()
    if low.endswith(".rss"):
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    if low.startswith("/tags/"):
        return f"{parsed.scheme}://{parsed.netloc}{path}.rss"
    return ""


def _mastodon_search_response_to_feeds(data, instance_base: str, limit: int = 12) -> list[dict]:
    """Normalize Mastodon /api/v2/search results into feed search dialog items."""
    out: list[dict] = []
    seen_urls: set[str] = set()
    try:
        limit = max(1, min(50, int(limit or 12)))
    except Exception:
        limit = 12

    base = str(instance_base or "").rstrip("/")
    if not isinstance(data, dict):
        return out

    def _add(item: dict) -> None:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        out.append(item)

    for acct in (data.get("accounts") or []):
        if not isinstance(acct, dict):
            continue
        profile_url = str(acct.get("url") or "").strip()
        rss_url = _mastodon_account_url_to_rss(profile_url)
        if not rss_url:
            continue
        acct_name = str(acct.get("acct") or "").strip()
        display_name = str(acct.get("display_name") or "").strip()
        followers = acct.get("followers_count")
        detail = "Mastodon user"
        if acct_name:
            detail = f"{detail} (@{acct_name})"
        try:
            if followers is not None:
                detail = f"{detail} ({int(followers)} followers)"
        except Exception:
            pass
        _add(
            {
                "title": display_name or (f"@{acct_name}" if acct_name else profile_url),
                "detail": detail,
                "url": rss_url,
            }
        )
        if len(out) >= limit:
            return out

    for tag in (data.get("hashtags") or []):
        if not isinstance(tag, dict):
            continue
        tag_name = str(tag.get("name") or "").strip().lstrip("#")
        tag_url = str(tag.get("url") or "").strip()
        rss_url = _mastodon_tag_url_to_rss(tag_url)
        if not rss_url and base and tag_name:
            rss_url = f"{base}/tags/{quote(tag_name, safe='')}.rss"
        if not rss_url:
            continue

        uses_latest = None
        try:
            history = tag.get("history") or []
            if history and isinstance(history[0], dict):
                uses_latest = int(history[0].get("uses", 0) or 0)
        except Exception:
            uses_latest = None

        detail = "Mastodon tag"
        if uses_latest is not None:
            detail = f"{detail} ({uses_latest} recent uses)"
        _add(
            {
                "title": f"#{tag_name}" if tag_name else (tag_url or "Mastodon tag"),
                "detail": detail,
                "url": rss_url,
            }
        )
        if len(out) >= limit:
            return out

    return out


def search_mastodon_feeds(
    term: str,
    limit: int = 12,
    timeout: int = 15,
    instance_url: str = "https://mastodon.social",
) -> list[dict]:
    """Search Mastodon accounts/hashtags and return RSS feed candidates."""
    query = str(term or "").strip()
    if not query:
        return []

    try:
        limit = max(1, min(20, int(limit or 12)))
    except Exception:
        limit = 12
    try:
        timeout = max(5, min(60, int(timeout or 15)))
    except Exception:
        timeout = 15

    base = str(instance_url or "https://mastodon.social").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://mastodon.social"

    params = {
        "q": query,
        "limit": limit,
    }
    # Ask Mastodon to resolve remote accounts when a handle/domain is provided.
    if "@" in query and "." in query:
        params["resolve"] = "true"

    try:
        resp = utils.safe_requests_get(f"{base}/api/v2/search", params=params, timeout=timeout)
        if getattr(resp, "status_code", None) != 200:
            return []
        data = resp.json()
        return _mastodon_search_response_to_feeds(data, base, limit=limit)
    except Exception:
        return []


def _bluesky_profile_url_to_rss(url: str) -> str:
    """Convert a Bluesky profile URL to its RSS URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return ""
    scheme = (parsed.scheme or "").lower()
    domain = (parsed.netloc or "").lower()
    if scheme not in ("http", "https") or "bsky.app" not in domain:
        return ""
    path = str(parsed.path or "").strip("/")
    if not path:
        return ""
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "profile" and parts[2] == "rss":
        ident = parts[1].strip()
        if ident:
            return f"{parsed.scheme}://{parsed.netloc}/profile/{quote(ident, safe=':@._-')}/rss"
        return ""
    if len(parts) >= 2 and parts[0] == "profile":
        ident = parts[1].strip()
        if ident:
            return f"{parsed.scheme}://{parsed.netloc}/profile/{quote(ident, safe=':@._-')}/rss"
    return ""


def _normalize_tag_candidate(term: str) -> str:
    q = str(term or "").strip()
    if not q:
        return ""
    if q.startswith("#"):
        q = q[1:].strip()
    # Bluesky/Mastodon hashtag-like token; avoid generating multi-word fake tag feeds.
    if not q or len(q) > 64 or not re.fullmatch(r"[A-Za-z0-9._-]+", q):
        return ""
    return q


def _bluesky_openrss_tag_url(tag: str) -> str:
    tag_name = _normalize_tag_candidate(tag)
    if not tag_name:
        return ""
    # OpenRSS wrapper (best-effort). Bluesky has native profile RSS, but not a stable native hashtag RSS route.
    return f"https://openrss.org/https://bsky.app/search?q=%23{quote(tag_name, safe='')}"


def _bluesky_search_response_to_feeds(data, query: str = "", limit: int = 12) -> list[dict]:
    """Normalize Bluesky actor search results into feed search dialog items."""
    out: list[dict] = []
    seen_urls: set[str] = set()
    try:
        limit = max(1, min(50, int(limit or 12)))
    except Exception:
        limit = 12

    def _add(item: dict) -> None:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        out.append(item)

    if isinstance(data, dict):
        for actor in (data.get("actors") or []):
            if not isinstance(actor, dict):
                continue
            handle = str(actor.get("handle") or "").strip()
            if not handle:
                continue
            rss_url = _bluesky_profile_url_to_rss(f"https://bsky.app/profile/{handle}")
            if not rss_url:
                continue
            display_name = str(actor.get("displayName") or "").strip()
            did = str(actor.get("did") or "").strip()
            detail = f"Bluesky user (@{handle})"
            if did:
                detail = f"{detail} ({did})"
            _add(
                {
                    "title": display_name or f"@{handle}",
                    "detail": detail,
                    "url": rss_url,
                }
            )
            if len(out) >= limit:
                return out

    # Best-effort hashtag result using OpenRSS wrapper.
    tag_name = _normalize_tag_candidate(query)
    if tag_name and len(out) < limit:
        rss_url = _bluesky_openrss_tag_url(tag_name)
        if rss_url:
            _add(
                {
                    "title": f"#{tag_name}",
                    "detail": "Bluesky tag (OpenRSS, third-party)",
                    "url": rss_url,
                }
            )

    return out


def search_bluesky_feeds(term: str, limit: int = 12, timeout: int = 15) -> list[dict]:
    """Search Bluesky users and return RSS feed candidates (plus tag fallback URLs)."""
    query = str(term or "").strip()
    if not query:
        return []
    try:
        limit = max(1, min(20, int(limit or 12)))
    except Exception:
        limit = 12
    try:
        timeout = max(5, min(60, int(timeout or 15)))
    except Exception:
        timeout = 15

    try:
        resp = utils.safe_requests_get(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActorsTypeahead",
            params={"q": query, "limit": max(1, min(limit, 10))},
            timeout=timeout,
        )
        data = resp.json() if getattr(resp, "status_code", None) == 200 else {}
    except Exception:
        data = {}
    return _bluesky_search_response_to_feeds(data, query=query, limit=limit)


def _federated_actor_url_to_feed_url(actor_url: str, *, source: str = "") -> str:
    """Convert common fediverse actor/community URLs to RSS feed URLs."""
    if not actor_url:
        return ""
    u = str(actor_url).strip()

    # Mastodon account/tag pages
    mastodon_url = _mastodon_account_url_to_rss(u) or _mastodon_tag_url_to_rss(u)
    if mastodon_url:
        return mastodon_url

    # Bluesky profiles
    bsky_url = _bluesky_profile_url_to_rss(u)
    if bsky_url:
        return bsky_url

    try:
        parsed = urlparse(u)
    except Exception:
        return ""
    scheme = (parsed.scheme or "").lower()
    host = (parsed.netloc or "").lower()
    path = str(parsed.path or "").rstrip("/")
    if scheme not in ("http", "https") or not host or not path:
        return ""

    source_l = str(source or "").lower()

    # PieFed local routes use /community/<name>/feed and /u/<name>/feed.
    if source_l == "piefed" and host and host.endswith("piefed.social"):
        if path.startswith("/c/"):
            name = path.split("/c/", 1)[1].split("/", 1)[0]
            if name:
                return f"{parsed.scheme}://{parsed.netloc}/community/{quote(name, safe='@._-')}/feed"
        if path.startswith("/u/"):
            name = path.split("/u/", 1)[1].split("/", 1)[0]
            if name:
                return f"{parsed.scheme}://{parsed.netloc}/u/{quote(name, safe='@._-')}/feed"

    # Lemmy communities
    if path.startswith("/c/"):
        comm_name = path.split("/c/", 1)[1]
        if comm_name:
            return f"{parsed.scheme}://{parsed.netloc}/feeds/c/{comm_name}.xml"

    # Kbin/Mbin magazines
    if path.startswith("/m/"):
        return f"{parsed.scheme}://{parsed.netloc}{path}/rss"

    # Lemmy users
    if path.startswith("/u/"):
        user_name = path.split("/u/", 1)[1]
        if user_name:
            return f"{parsed.scheme}://{parsed.netloc}/feeds/u/{user_name}.xml"

    return ""


def _piefed_search_response_to_feeds(data, limit: int = 12) -> list[dict]:
    """Normalize PieFed search API responses into RSS feed candidates."""
    out: list[dict] = []
    seen_urls: set[str] = set()
    try:
        limit = max(1, min(50, int(limit or 12)))
    except Exception:
        limit = 12

    def _add(item: dict) -> None:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        out.append(item)

    if not isinstance(data, dict):
        return out

    for row in (data.get("communities") or []):
        if not isinstance(row, dict):
            continue
        comm = row.get("community") or {}
        counts = row.get("counts") or {}
        actor_id = str(comm.get("actor_id") or "").strip()
        rss_url = _federated_actor_url_to_feed_url(actor_id, source="piefed")
        if not rss_url:
            continue
        title = str(comm.get("title") or comm.get("name") or actor_id).strip()
        name = str(comm.get("name") or "").strip()
        subs = counts.get("subscriptions_count") or counts.get("total_subscriptions_count")
        ap_domain = str(comm.get("ap_domain") or "").strip()
        detail = "PieFed community"
        if name:
            detail = f"{detail} ({name})"
        if ap_domain:
            detail = f"{detail} - {ap_domain}"
        try:
            if subs is not None:
                detail = f"{detail} ({int(subs)} subs)"
        except Exception:
            pass
        _add({"title": title, "detail": detail, "url": rss_url})
        if len(out) >= limit:
            return out

    for row in (data.get("users") or []):
        if not isinstance(row, dict):
            continue
        person = row.get("person") or {}
        counts = row.get("counts") or {}
        actor_id = str(person.get("actor_id") or "").strip()
        rss_url = _federated_actor_url_to_feed_url(actor_id, source="piefed")
        if not rss_url:
            continue
        title = str(person.get("title") or person.get("user_name") or actor_id).strip()
        user_name = str(person.get("user_name") or "").strip()
        detail = "Fediverse user (via PieFed)"
        if user_name:
            detail = f"{detail} (@{user_name})"
        try:
            post_count = counts.get("post_count")
            comment_count = counts.get("comment_count")
            if post_count is not None or comment_count is not None:
                detail = f"{detail} ({int(post_count or 0)} posts, {int(comment_count or 0)} comments)"
        except Exception:
            pass
        _add({"title": title, "detail": detail, "url": rss_url})
        if len(out) >= limit:
            return out

    return out


def search_piefed_feeds(term: str, limit: int = 12, timeout: int = 15, instance_url: str = "https://piefed.social") -> list[dict]:
    """Search PieFed communities/users and return RSS feed candidates."""
    query = str(term or "").strip()
    if not query:
        return []
    try:
        limit = max(1, min(20, int(limit or 12)))
    except Exception:
        limit = 12
    try:
        timeout = max(5, min(60, int(timeout or 15)))
    except Exception:
        timeout = 15

    base = str(instance_url or "https://piefed.social").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://piefed.social"
    endpoint = f"{base}/api/alpha/search"

    out: list[dict] = []
    seen_urls: set[str] = set()

    def _merge(items: list[dict]) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append(item)
            if len(out) >= limit:
                break

    for search_type in ("Communities", "Users"):
        if len(out) >= limit:
            break
        try:
            resp = utils.safe_requests_get(
                endpoint,
                params={"q": query, "type_": search_type, "limit": max(3, min(limit, 10))},
                timeout=timeout,
            )
            if getattr(resp, "status_code", None) != 200:
                continue
            data = resp.json()
            _merge(_piefed_search_response_to_feeds(data, limit=limit))
        except Exception:
            continue

    return out


def get_social_feed_url(url: str) -> str | None:
    """Convert known social profile/tag/community URLs to RSS feed URLs when possible."""
    if not url:
        return None

    # Google Developer Forums is a Discourse instance.  Its landing page and
    # category/topic routes have stable native RSS forms, so they work even
    # when the JavaScript application does not advertise an alternate link to
    # a non-browser client.
    try:
        from core import forum_sources

        developer_feed = forum_sources.google_developer_forum_feed_url(url)
        if developer_feed:
            return developer_feed
    except Exception:
        pass

    # Google removed the legacy Groups RSS endpoints.  A group email address,
    # current landing page, or old #!forum URL therefore resolves to a
    # synthetic local subscription, enumerated by LocalProvider on refresh.
    try:
        from core import forum_sources

        google_group = forum_sources.google_group_subscription_url(url)
        if google_group:
            return google_group
    except Exception:
        pass

    # Groups.io group landing, topics, messages, and archive-search pages all
    # advertise the same native per-group RSS feed.  Local search subscriptions
    # preserve /search earlier in LocalProvider; hosted providers that cannot
    # synthesize filtered results still get the useful unfiltered group feed.
    try:
        from core import groups_io

        groups_feed = groups_io.group_feed_url(url)
        if groups_feed:
            return groups_feed
    except Exception:
        pass

    # Reddit exposes a native Atom feed for every public subreddit.  Normalize
    # both the current and old frontends before doing any network discovery so
    # pasting ``reddit.com/r/name`` into Add Feed works even when the HTML site
    # is rate-limited or requires a logged-in browser session.
    try:
        parsed = urlparse(str(url).strip())
        host = (parsed.hostname or "").lower()
        parts = [unquote(part) for part in (parsed.path or "").split("/") if part]
        if (
            (parsed.scheme or "").lower() in ("http", "https")
            and _host_matches(host, "reddit.com")
            and len(parts) == 2
            and parts[0].lower() == "r"
            and re.fullmatch(r"[A-Za-z0-9_]{2,21}", parts[1])
        ):
            return f"https://www.reddit.com/r/{quote(parts[1], safe='_')}/.rss"
    except Exception:
        pass

    # Lemmy publishes native feeds for community and user pages on every
    # instance.  These route shapes are part of Lemmy's public RSS interface,
    # so they can be converted without first downloading the JavaScript app.
    # Site roots (for example https://rblind.com/) are intentionally left to
    # normal HTML discovery: Lemmy advertises /feeds/all.xml there, while an
    # arbitrary site's root URL is not enough evidence that it runs Lemmy.
    try:
        parsed = urlparse(str(url).strip())
        path = str(parsed.path or "").rstrip("/")
        host = (parsed.hostname or "").lower()
        if (
            (parsed.scheme or "").lower() in ("http", "https")
            and parsed.netloc
            and not _host_matches(host, "piefed.social")
        ):
            match = re.fullmatch(r"/(c|u)/([^/]+)", path, re.I)
            if match:
                kind = match.group(1).lower()
                name = unquote(match.group(2)).strip()
                if name and re.fullmatch(r"[A-Za-z0-9_.@-]+", name):
                    safe_name = quote(name, safe="@._-")
                    return f"{parsed.scheme}://{parsed.netloc}/feeds/{kind}/{safe_name}.xml"
    except Exception:
        pass

    for conv in (
        _mastodon_account_url_to_rss,
        _mastodon_tag_url_to_rss,
        _bluesky_profile_url_to_rss,
    ):
        try:
            out = conv(url)
            if out:
                return out
        except Exception:
            continue

    # PieFed direct pages (local instance route patterns)
    try:
        parsed = urlparse(str(url).strip())
        if (parsed.scheme or "").lower() in ("http", "https") and (parsed.netloc or "").lower().endswith("piefed.social"):
            p = str(parsed.path or "").rstrip("/")
            if p.startswith("/u/"):
                name = p.split("/u/", 1)[1].split("/", 1)[0]
                if name:
                    return f"{parsed.scheme}://{parsed.netloc}/u/{quote(name, safe='@._-')}/feed"
            if p.startswith("/community/"):
                name = p.split("/community/", 1)[1].split("/", 1)[0]
                if name:
                    return f"{parsed.scheme}://{parsed.netloc}/community/{quote(name, safe='@._-')}/feed"
            if p.startswith("/c/"):
                name = p.split("/c/", 1)[1].split("/", 1)[0]
                if name:
                    return f"{parsed.scheme}://{parsed.netloc}/community/{quote(name, safe='@._-')}/feed"
    except Exception:
        pass

    return None


@dataclass(frozen=True)
class YoutubeSearchItem:
    url: str
    title: str
    author: str | None = None
    published: str | None = None

    @property
    def id(self) -> str:
        return self.url


def is_youtube_search_url(url: str) -> bool:
    """True for a YouTube search-results URL, e.g. youtube.com/results?search_query=..."""
    if not url:
        return False
    try:
        parts = urlparse(url)
    except Exception:
        return False
    if not _host_matches(parts.hostname or "", "youtube.com"):
        return False
    if (parts.path or "").rstrip("/").lower() != "/results":
        return False
    try:
        q = parse_qs(parts.query or "")
    except Exception:
        return False
    return bool(q.get("search_query") or q.get("q"))


def youtube_search_query(url: str) -> str | None:
    """Return the search terms from a YouTube search-results URL, or None."""
    if not is_youtube_search_url(url):
        return None
    try:
        parts = urlparse(url)
        q = parse_qs(parts.query or "")
    except Exception:
        return None
    vals = q.get("search_query") or q.get("q") or []
    val = (vals[0] if vals else "").strip()
    return val or None


def fetch_youtube_search_items(query: str, max_items: int = 30, timeout_s: float = 30.0, cookiefile: str | None = None):
    """Enumerate recent YouTube videos for a search query, newest first.

    Uses yt-dlp's ``ytsearchdate`` (date-sorted search) and a flat playlist dump so
    we get lightweight entries without resolving every video. Returns
    (feed_title, list[YoutubeSearchItem]).
    """
    query = (query or "").strip()
    if not query:
        return (None, [])
    try:
        total_timeout = max(0.1, float(timeout_s or 30.0))
    except (TypeError, ValueError):
        total_timeout = 30.0
    deadline = time.monotonic() + total_timeout
    n = max(1, min(100, int(max_items or 30)))
    # Use YouTube's own date-sorted search results URL (sp=CAI%3D == "Sort by upload
    # date"). yt-dlp's `ytsearchdate` prefix is unreliable across versions, but the
    # results URL is handled robustly by the YouTube tab extractor.
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=CAI%3D"

    base_cmd = [
        _resolve_ytdlp_cli_path(),
        "--dump-json",
        "--flat-playlist",
        "--ignore-errors",
        "--no-warnings",
        "--playlist-end",
        str(n),
    ]

    creationflags = 0
    if platform.system().lower() == "windows":
        creationflags = 0x08000000  # CREATE_NO_WINDOW
    try:
        from core.dependency_check import _get_startup_info
        startupinfo = _get_startup_info()
    except Exception:
        startupinfo = None

    failures: list[str] = []

    def _run(cookie_value: str | None = None, cookiefile: str | None = None) -> tuple[bool, str]:
        cmd = list(base_cmd)
        if cookiefile:
            cmd.extend(["--cookies", cookiefile])
        elif cookie_value:
            cmd.extend(["--cookies-from-browser", cookie_value])
        cmd.append(search_url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failures.append("total search deadline expired")
            return False, ""
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                startupinfo=startupinfo,
                timeout=remaining,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            failures.append("yt-dlp search timed out")
            return False, ""
        except Exception as exc:
            failures.append(f"yt-dlp search failed: {exc}")
            return False, ""
        if res.returncode != 0:
            failures.append(f"yt-dlp search exited with status {res.returncode}")
            return False, ""
        return True, res.stdout or ""

    def _parse(stdout: str) -> list[YoutubeSearchItem]:
        out: list[YoutubeSearchItem] = []
        seen_urls: set[str] = set()
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if not isinstance(entry, dict):
                continue
            entry_type = str(entry.get("_type") or "").strip().lower()
            if entry_type in ("channel", "playlist"):
                continue
            vid = str(entry.get("id") or "").strip()
            if not vid:
                continue
            watch_url = f"https://www.youtube.com/watch?v={vid}"
            if watch_url in seen_urls:
                continue
            seen_urls.add(watch_url)
            title = str(entry.get("title") or "YouTube Video").strip()
            author = entry.get("uploader") or entry.get("channel") or entry.get("uploader_id")
            published = None
            upload_date = entry.get("upload_date")
            if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
                published = f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
            if not published:
                for timestamp_key in ("timestamp", "release_timestamp"):
                    timestamp = entry.get(timestamp_key)
                    try:
                        if timestamp is not None:
                            published = datetime.fromtimestamp(float(timestamp), timezone.utc).date().isoformat()
                            break
                    except (TypeError, ValueError, OSError, OverflowError):
                        continue
            out.append(
                YoutubeSearchItem(
                    url=watch_url,
                    title=title,
                    author=str(author) if author else None,
                    published=published,
                )
            )
        return out

    # A configured cookies.txt takes priority (works for Chromium ABE on Windows),
    # then each detected browser's cookies (Brave first), then an anonymous request
    # (reliable for public search; avoids per-browser decryption failures).
    attempts: list[tuple[str | None, str | None]] = []
    if cookiefile and os.path.isfile(cookiefile):
        attempts.append((None, cookiefile))
    try:
        for src in get_ytdlp_cookie_sources("https://www.youtube.com/"):
            arg = cookie_arg_for_ytdlp(src)
            attempt = (arg, None)
            if arg and attempt not in attempts:
                attempts.append(attempt)
    except Exception:
        pass
    attempts.append((None, None))  # anonymous fallback

    had_successful_attempt = False
    for cookie_value, attempt_cookiefile in attempts:
        succeeded, stdout = _run(
            cookie_value=cookie_value,
            cookiefile=attempt_cookiefile,
        )
        if not succeeded:
            continue
        had_successful_attempt = True
        items = _parse(stdout)
        if items:
            return (f"YouTube: {query}", items)

    if had_successful_attempt:
        return (f"YouTube: {query}", [])
    detail = failures[-1] if failures else "yt-dlp search did not run"
    raise RuntimeError(f"YouTube search failed: {detail}")


def get_ytdlp_feed_url(url: str) -> str:
    """Try to get a native RSS feed for a yt-dlp supported URL (e.g. YouTube)."""
    if not url:
        return None

    # Search-results URLs have no native RSS; they are enumerated via yt-dlp on
    # refresh. Returning None keeps the original URL so the search-listing path runs.
    if is_youtube_search_url(url):
        return None

    parsed = urlparse(url)
    domain = parsed.hostname or ""

    # 1. YouTube specific logic (fastest)
    if _is_youtube_host(domain):
        # Already the native feed. Without this, subscribing to a feed URL the
        # user (or Find a Feed) had already resolved spent ~25s running yt-dlp
        # against an XML document before falling back to the same URL.
        if (parsed.path or "").rstrip("/").lower() == "/feeds/videos.xml":
            return url

        playlist_id = _youtube_playlist_id_from_url(url)
        if playlist_id:
            return f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"

        # Check for channel_id or user in URL
        if "/channel/" in url:
            channel_id = url.split("/channel/")[1].split("/")[0].split("?")[0]
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        if "/user/" in url:
            user = url.split("/user/")[1].split("/")[0].split("?")[0]
            return f"https://www.youtube.com/feeds/videos.xml?user={user}"
        if "/@" in url:
            # Handle @handle URLs by using yt-dlp to get the channel ID
            pass
        
        # Use yt-dlp to find channel ID for custom URLs
        try:
            from core.dependency_check import _get_startup_info
            creationflags = 0
            if platform.system().lower() == "windows":
                creationflags = 0x08000000
                
            # Resolve channel metadata without enumerating the channel's videos.
            # Browser cookie databases can be locked or undecryptable, so try all
            # configured sources and retain an anonymous fallback.
            base_cmd = [
                _resolve_ytdlp_cli_path(),
                "--dump-single-json",
                "--flat-playlist",
                "--playlist-items",
                "0",
            ]
            cookie_args: list[str | None] = [None]
            for source in get_ytdlp_cookie_sources(url):
                cookie_arg = cookie_arg_for_ytdlp(source)
                if cookie_arg and cookie_arg not in cookie_args:
                    cookie_args.append(cookie_arg)

            for cookie_arg in cookie_args:
                cmd = list(base_cmd)
                if cookie_arg:
                    cmd.extend(["--cookies-from-browser", cookie_arg])
                cmd.append(url)
                try:
                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        creationflags=creationflags,
                        startupinfo=_get_startup_info(),
                        timeout=15,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                except Exception:
                    continue
                if res.returncode != 0 or not res.stdout:
                    continue
                try:
                    data = json.loads(res.stdout)
                except Exception:
                    continue
                channel_id = str(data.get("channel_id") or data.get("id") or "").strip()
                if channel_id and data.get("_type") in ("playlist", "channel"):
                    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        except Exception:
            pass

    # 2. Rumble note:
    # Rumble previously exposed /feeds/rss/... endpoints, but these are unreliable
    # (often 404/410). BlindRSS supports Rumble via HTML listing parsing + a
    # custom media resolver, so we intentionally do NOT return an RSS URL here.
            
    return None


def _impersonated_discovery_retry(url: str, timeout: float):
    """One browser-impersonated retry for discovery fetches that a WAF blocked.

    Anti-bot walls (e.g. Akamai on radiofarda.com) 403/reset the default client
    but serve the same feed to a browser TLS fingerprint (issue #29). Returns the
    successful response, or None when impersonation is unavailable or also fails.
    """
    if not getattr(utils, "CURL_CFFI_AVAILABLE", False):
        return None
    try:
        resp = utils.safe_requests_get(url, timeout=timeout, impersonate=True)
    except Exception:
        return None
    if int(getattr(resp, "status_code", 0) or 0) >= 400:
        return None
    return resp


# Well-known feed locations probed when a page doesn't advertise its feed.
# Ordered by how common each convention is; includes the old-school
# /backend.xml (TechSpot, classic Slashdot-era sites) and the WordPress
# query-string fallbacks, which some sites serve even when /feed is blocked.
_COMMON_FEED_PROBE_PATHS = (
    "/feed",
    "/rss",
    "/feed.xml",
    "/rss.xml",
    "/atom.xml",
    "/index.xml",
    "/backend.xml",
    "/index.rss",
    "/index.atom",
    "/atom",
    "/feeds",
    "?feed=rss2",
    "?rss=1",
)
_FEED_PROBE_MAX_WORKERS = 6


def _probe_feed_path_candidate(candidate: str, timeout: float) -> bool:
    """True when `candidate` serves a real feed.

    HEAD first (cheap); when HEAD is blocked or ambiguous, confirm with a GET
    and structural validation. WAFs on sites like techspot.com reject HEAD
    (403) but serve the feed to GET, so a blocked HEAD must not end the probe.
    """
    head_status = None
    try:
        head = utils.safe_requests_head(candidate, timeout=timeout, allow_redirects=True)
        head_status = int(getattr(head, "status_code", 0) or 0)
        if head_status == 200:
            ct = (head.headers.get("Content-Type", "") or "").lower()
            if any(x in ct for x in ("xml", "rss", "atom", "json")):
                return True
    except Exception:
        head_status = None
    if head_status in (404, 410):
        # A clean miss; no point re-fetching.
        return False
    try:
        got = utils.safe_requests_get(candidate, timeout=timeout)
        if int(getattr(got, "status_code", 0) or 0) != 200:
            return False
        return _body_looks_like_feed(
            got.text or "", str(got.headers.get("Content-Type", "") or "")
        )
    except Exception:
        return False


def _probe_common_feed_paths(effective_url: str, timeout: float = 5.0) -> list[str]:
    """Probe well-known feed paths for a page, returning confirmed feed URLs.

    Probes relative to the page's own path and, when the page isn't the site
    root, relative to the root as well (a subpage's feed often lives at the
    root). Candidates are checked concurrently; results keep candidate order.
    """
    page_base = str(effective_url or "").rstrip("/")
    if not page_base:
        return []
    bases = [page_base]
    try:
        parsed = urlparse(page_base)
        root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        if root and root.rstrip("/") != page_base:
            bases.append(root.rstrip("/"))
    except Exception:
        pass

    candidates: list[str] = []
    seen: set[str] = set()
    for base in bases:
        for path in _COMMON_FEED_PROBE_PATHS:
            candidate = base + path
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    if not candidates:
        return []

    confirmed: dict[str, bool] = {}
    max_workers = max(1, min(_FEED_PROBE_MAX_WORKERS, len(candidates)))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(_probe_feed_path_candidate, c, timeout): c for c in candidates
            }
            for fut in concurrent.futures.as_completed(list(future_map.keys())):
                c = future_map.get(fut) or ""
                try:
                    confirmed[c] = bool(fut.result())
                except Exception:
                    confirmed[c] = False
    except Exception:
        for c in candidates:
            try:
                confirmed[c] = _probe_feed_path_candidate(c, timeout)
            except Exception:
                confirmed[c] = False

    return [c for c in candidates if confirmed.get(c)]


def discover_feed(url: str, request_timeout: float = 10.0, probe_timeout: float = 5.0) -> str:
    """
    Given a URL, try to find the RSS/Atom feed URL.
    Returns None if not found.
    """
    if not url:
        return None
    
    # If it looks like a feed already
    if _looks_like_feed_url(url):
        return url

    # Native feed conversion for supported media URLs (e.g., YouTube channel/playlist URLs).
    try:
        media_feed = get_ytdlp_feed_url(url)
        if media_feed:
            return media_feed
    except Exception:
        pass

    try:
        social_feed = get_social_feed_url(url)
        if social_feed:
            return social_feed
    except Exception:
        pass
        
    try:
        req_timeout = max(1.0, float(request_timeout or 10.0))
        head_timeout = max(1.0, float(probe_timeout or 5.0))

        resp = None
        last_get_error = None
        for attempt in range(10):
            try:
                resp = utils.safe_requests_get(url, timeout=req_timeout)
                break
            except Exception as e:
                last_get_error = e
                if attempt < 9:
                    time.sleep(0.01)
        if resp is None:
            # Every plain attempt raised (e.g. an anti-bot WAF resetting the
            # connection). One browser-impersonated retry before giving up (issue #29).
            resp = _impersonated_discovery_retry(url, req_timeout)
            if resp is None:
                raise last_get_error
        elif int(getattr(resp, "status_code", 0) or 0) >= 400:
            # WAF block pages (e.g. Akamai's 403 "Access Denied") often clear for
            # a browser TLS fingerprint (issue #29). Keep the original response
            # when impersonation is unavailable or also blocked.
            retry_resp = _impersonated_discovery_retry(url, req_timeout)
            if retry_resp is not None:
                resp = retry_resp
        resp.raise_for_status()

        effective_url = str(getattr(resp, "url", "") or url)
        body_text = resp.text or ""
        content_type = str(resp.headers.get("Content-Type", "") or "").lower()
        if _body_looks_like_feed(body_text, content_type):
            return effective_url
        looks_like_xml = (
            "xml" in content_type
            or body_text.lstrip().startswith("<?xml")
            or "<rss" in body_text[:512].lower()
            or "<feed" in body_text[:512].lower()
        )
        soup = BeautifulSoup(body_text, "xml" if looks_like_xml else "html.parser")
        
        # 1. Prefer the best matching alternate feed link when multiple are present.
        candidates = _alternate_feed_candidates(soup, effective_url)
        if candidates:
            return candidates[0]
                    
        # 2. Check well-known feed locations if no link tag advertised one.
        probed = _probe_common_feed_paths(effective_url, timeout=head_timeout)
        if probed:
            return probed[0]

    except Exception:
        pass

    # 3. Last resort: OpenRSS generates feeds for many sites with no native RSS.
    try:
        openrss = openrss_feed_url(url, timeout=request_timeout)
        if openrss:
            return openrss
    except Exception:
        pass

    return None


def openrss_feed_url(url: str, timeout: float = 10.0) -> str | None:
    """Return an OpenRSS proxy feed URL for `url` if openrss.org supports it.

    OpenRSS serves the raw feed at https://openrss.org/feed/<host><path> and
    answers 404 for unsupported sites, so the candidate is only returned after
    a successful, feed-shaped response.
    """
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return None
    scheme = (parsed.scheme or "").lower()
    host = str(parsed.netloc or "").strip()
    if scheme not in ("http", "https") or not host:
        return None
    # Never proxy openrss.org through itself.
    if _host_matches(host.split("@")[-1].split(":")[0], "openrss.org"):
        return None
    candidate = f"https://openrss.org/feed/{host}{parsed.path or ''}"
    if parsed.query:
        candidate += f"?{parsed.query}"
    try:
        resp = utils.safe_requests_get(candidate, timeout=max(1.0, float(timeout or 10.0)))
        if resp.status_code == 200 and _body_looks_like_feed(
            resp.text or "", str(resp.headers.get("Content-Type", "") or "")
        ):
            return candidate
    except Exception:
        pass
    return None


def discover_feeds(url: str) -> list[str]:
    """Return a list of discovered RSS/Atom/JSON feeds for a webpage/site URL.

    This is a more general form of `discover_feed()` intended for UI helpers
    (e.g. "Find a podcast or RSS feed"). It tries to enumerate multiple
    candidates rather than returning the first match.
    """
    if not url:
        return []

    # If it already looks like a feed, return it as-is.
    if _looks_like_feed_url(url):
        return [url]

    try:
        media_feed = get_ytdlp_feed_url(url)
        if media_feed:
            return [media_feed]
    except Exception:
        pass

    try:
        social_feed = get_social_feed_url(url)
        if social_feed:
            return [social_feed]
    except Exception:
        pass

    feeds: list[str] = []

    def _add(candidate: str) -> None:
        if not candidate:
            return
        if candidate not in feeds:
            feeds.append(candidate)

    try:
        resp = None
        plain_get_error = None
        try:
            resp = utils.safe_requests_get(url, timeout=10)
        except Exception as e:
            plain_get_error = e
        if resp is None or int(getattr(resp, "status_code", 0) or 0) >= 400:
            # WAF block/reset on the plain client (e.g. Akamai 403): one
            # browser-impersonated retry before falling through (issue #29).
            retry_resp = _impersonated_discovery_retry(url, 10)
            if retry_resp is not None:
                resp = retry_resp
            elif resp is None:
                raise plain_get_error
        resp.raise_for_status()
        effective_url = str(getattr(resp, "url", "") or url)
        html = resp.text or ""
        content_type = str(resp.headers.get("Content-Type", "") or "").lower()
        if _body_looks_like_feed(html, content_type):
            _add(effective_url)
            return feeds

        soup = BeautifulSoup(html, "html.parser")

        # 1) <link rel="alternate" ...>, ordered by best page/feed match first.
        for candidate in _alternate_feed_candidates(soup, effective_url):
            _add(candidate)

        # 2) Obvious <a href> candidates (best-effort)
        for a in soup.find_all("a", href=True):
            try:
                href = a.get("href")
                if not isinstance(href, str) or not href:
                    continue
                h = href.lower()
                if any(h.endswith(ext) for ext in (".rss", ".atom", ".xml", ".json")) or "/feed" in h or "rss" in h:
                    _add(urljoin(effective_url, href))
            except Exception:
                continue

        # 3) Well-known feed locations (validated probe; tolerates HEAD-blocking WAFs)
        for candidate in _probe_common_feed_paths(effective_url, timeout=5):
            _add(candidate)

    except Exception:
        pass

    # Last resort: OpenRSS generates feeds for many sites with no native RSS.
    if not feeds:
        try:
            openrss = openrss_feed_url(url)
            if openrss:
                _add(openrss)
        except Exception:
            pass

    # Normalize/uniq while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for f in feeds:
        try:
            fu = str(f).strip()
        except Exception:
            continue
        if not fu or fu in seen:
            continue
        seen.add(fu)
        out.append(fu)
    return out

class PageFetchError(Exception):
    """The webpage for feed detection could not be retrieved (issue #76).

    ``is_challenge`` is True when the site answered with a bot-verification
    interstitial (Cloudflare "Just a moment...", issue #79) — callers can then
    point the user at Tools > Import Site Cookies instead of a generic error.
    """

    def __init__(self, message: str, *, is_challenge: bool = False):
        super().__init__(message)
        self.is_challenge = bool(is_challenge)


# MIME types accepted for <link rel="alternate"> feed detection (issue #76).
# Wider than _ALTERNATE_FEED_TYPES: plain application/json and RDF feeds count.
_DETECT_PAGE_FEED_TYPES = _ALTERNATE_FEED_TYPES | {
    "application/json",
    "application/rdf+xml",
}


# Channel URL shapes YouTube still serves besides /@handle.
_YOUTUBE_CHANNEL_PATH_PREFIXES = ("/channel/", "/c/", "/user/")
_VBULLETIN_FORUM_PATH_RE = re.compile(r"^/forums/(?P<forum_id>[0-9]+)(?:-|/|$)", re.I)


def _native_channel_feed_for_page(page_url: str) -> dict | None:
    """Resolve a YouTube channel/playlist page to its native videos.xml feed.

    Returns a detect_page_feeds-shaped dict, or None when the URL is not a
    YouTube channel/playlist page (or the channel id could not be resolved, in
    which case the caller falls back to scraping the HTML).

    The title is left empty on purpose: a single detection result goes straight
    to the Add Feed dialog, which reads the real channel title from the feed.
    """
    try:
        parsed = urlparse(page_url)
    except Exception:
        return None
    if not _is_youtube_host(parsed.hostname or ""):
        return None
    if is_youtube_search_url(page_url):
        return None

    path = parsed.path or "/"
    low_path = path.lower()
    # A "list" parameter means a playlist page (or a video opened inside one);
    # both have a native feed. Bare /watch?v= URLs deliberately do not.
    is_playlist = bool(_youtube_playlist_id_from_url(page_url))
    is_channel = path.startswith("/@") or any(
        low_path.startswith(prefix) for prefix in _YOUTUBE_CHANNEL_PATH_PREFIXES
    )
    if not (is_playlist or is_channel):
        return None

    try:
        feed_url = str(get_ytdlp_feed_url(page_url) or "").strip()
    except Exception:
        return None
    return {"title": "", "url": feed_url} if feed_url else None


def _vbulletin_feed_candidates(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """Return public vBulletin RSS feeds exposed by a forum index/page.

    vBulletin 4 commonly advertises feeds as ordinary ``external.php`` anchors
    beside each forum rather than ``<link rel=alternate>`` elements in the page
    head. Once at least one such same-origin RSS anchor proves the page shape,
    derive feeds for every visible ``/forums/<id>-...`` link as well. This picks
    up visible subforums (for example FileSharingTalk's Drawing Room) without a
    brittle hard-coded forum-id table.
    """
    try:
        parsed_page = urlparse(page_url)
    except Exception:
        return []
    if (parsed_page.scheme or "").lower() not in ("http", "https") or not parsed_page.hostname:
        return []

    saw_external_rss = False
    for anchor in soup.find_all("a", href=True):
        try:
            candidate = urlparse(urljoin(page_url, str(anchor.get("href") or "")))
            if (candidate.hostname or "").lower() != (parsed_page.hostname or "").lower():
                continue
            if not (candidate.path or "").lower().endswith("/external.php"):
                continue
            query = parse_qs(candidate.query or "", keep_blank_values=True)
            feed_type = str((query.get("type") or [""])[0] or "").upper()
            if feed_type not in {"RSS", "RSS1", "RSS2", "XML"}:
                continue
            saw_external_rss = True
        except Exception:
            continue
    if not saw_external_rss:
        return []

    origin = f"{parsed_page.scheme}://{parsed_page.netloc}"
    results = [{"title": "All forums", "url": origin + "/external.php?type=RSS2"}]
    seen_ids: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        try:
            forum_url = urlparse(urljoin(page_url, str(anchor.get("href") or "")))
            if (forum_url.hostname or "").lower() != (parsed_page.hostname or "").lower():
                continue
            match = _VBULLETIN_FORUM_PATH_RE.match(forum_url.path or "")
            if match is None:
                continue
            forum_id = match.group("forum_id")
            if forum_id in seen_ids:
                continue
            title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
            if not title:
                continue
            seen_ids.add(forum_id)
            results.append(
                {
                    "title": title,
                    "url": origin + f"/external.php?type=RSS2&forumids={forum_id}",
                }
            )
        except Exception:
            continue
    return results


def detect_page_feeds(
    url: str,
    timeout: float = 15.0,
    *,
    browser_fallback_enabled: bool = True,
    browser_timeout: float = 90.0,
) -> list[dict]:
    """Scan a webpage's HTML for machine-readable feed links (issue #76).

    Returns a list of ``{"title": str, "url": str}`` dicts, in document order,
    for every ``<link rel="alternate">`` whose ``type`` is a known feed MIME
    type and whose ``href`` is non-empty. Public vBulletin pages also contribute
    their ``external.php`` all-forums and visible per-forum RSS feeds. ``title``
    falls back to "" (callers display the URL then). If the URL itself serves a
    feed document, that URL is returned as the single result.

    Raises PageFetchError when the page cannot be retrieved.
    """
    page_url = str(url or "").strip()
    if not page_url:
        raise PageFetchError("empty URL")
    if "://" not in page_url:
        page_url = "https://" + page_url

    # YouTube channel/playlist pages: resolve the native videos.xml feed instead
    # of trusting the page HTML. The RSS <link> tag is only present on some
    # channel URL shapes and disappears entirely behind consent interstitials or
    # when YouTube serves its lighter shell, so scraping alone made "Detect
    # Feeds" unreliable for exactly the URL users paste (a /@handle page).
    native = _native_channel_feed_for_page(page_url)
    if native:
        return [native]

    try:
        browser_timeout = max(15.0, min(float(browser_timeout or 90.0), 180.0))
    except (TypeError, ValueError):
        browser_timeout = 90.0
    browser_attempted = False

    def _try_browser_page():
        nonlocal browser_attempted
        if not browser_fallback_enabled or browser_attempted:
            return None
        browser_attempted = True
        try:
            from core import browser_feed

            return browser_feed.fetch_page(page_url, timeout_s=browser_timeout)
        except Exception:
            return None

    resp = None
    fetch_error = None
    try:
        resp = utils.safe_requests_get(page_url, timeout=timeout, allow_redirects=True)
    except Exception as e:
        fetch_error = e
    if resp is None or int(getattr(resp, "status_code", 0) or 0) >= 400:
        # One browser-impersonated retry past WAF blocks (issue #29).
        retry_resp = _impersonated_discovery_retry(page_url, timeout)
        if retry_resp is not None:
            resp = retry_resp
    status = int(getattr(resp, "status_code", 0) or 0) if resp is not None else 0
    if resp is None or status in (401, 403, 429, 503) or status >= 520:
        browser_resp = _try_browser_page()
        if browser_resp is not None:
            resp = browser_resp
    if resp is None:
        raise PageFetchError(str(fetch_error or "no response"))
    status = int(getattr(resp, "status_code", 0) or 0)
    if not (200 <= status < 400):
        try:
            from core import site_cookies
            body = getattr(resp, "text", "") or ""
            if site_cookies.looks_like_challenge_response(status, body):
                raise PageFetchError(f"HTTP {status} (bot challenge)", is_challenge=True)
        except PageFetchError:
            raise
        except Exception:
            pass
        raise PageFetchError(f"HTTP {status}")

    effective_url = str(getattr(resp, "url", "") or page_url)
    content_type = str(resp.headers.get("Content-Type", "") or "")
    # Decode via the issue #75 chain so non-ASCII link titles survive pages
    # that omit the charset header.
    try:
        from core import text_encoding
        html = text_encoding.decode_bytes(
            getattr(resp, "content", b"") or b"", content_type=content_type, kind="html"
        )
    except Exception:
        html = resp.text or ""

    # Some verification interstitials answer 200 after the HTTP-level retry.
    # Escalate once here as well, before treating the challenge shell as a page
    # with no feeds (issue #79).
    try:
        from core import browser_feed

        challenge_page = browser_feed._looks_like_challenge_page(html)
    except Exception:
        challenge_page = False
    if challenge_page:
        browser_resp = _try_browser_page()
        if browser_resp is None:
            raise PageFetchError("bot challenge", is_challenge=True)
        resp = browser_resp
        effective_url = str(getattr(resp, "url", "") or page_url)
        content_type = str(resp.headers.get("Content-Type", "") or "")
        html = resp.text or ""

    if _body_looks_like_feed(html, content_type.lower()):
        return [{"title": "", "url": effective_url}]

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    results: list[dict] = []
    seen: set[str] = set()
    for link in soup.find_all("link", href=True):
        try:
            rel = link.get("rel")
            rel_vals = [rel] if isinstance(rel, str) else [str(r) for r in (rel or [])]
            if "alternate" not in [r.lower().strip() for r in rel_vals if r]:
                continue
            ctype = str(link.get("type") or "").lower().strip()
            if ctype not in _DETECT_PAGE_FEED_TYPES:
                continue
            href = link.get("href")
            if not isinstance(href, str) or not href.strip():
                continue
            feed_url = urljoin(effective_url, href.strip())
            if feed_url in seen:
                continue
            seen.add(feed_url)
            results.append({"title": str(link.get("title") or "").strip(), "url": feed_url})
        except Exception:
            continue
    for feed in _vbulletin_feed_candidates(soup, effective_url):
        feed_url = str(feed.get("url") or "")
        if not feed_url or feed_url in seen:
            continue
        seen.add(feed_url)
        results.append(feed)
    return results


def detect_media(url: str, timeout: int = 20) -> tuple[str | None, str | None]:
    """
    Attempt to detect media (audio/video) for a given URL using yt-dlp and other heuristics.
    Returns (media_url, media_type) or (None, None).
    """
    if not url:
        return None, None

    # 1. Publisher-specific podcast pages whose media lives outside the page.
    try:
        from core import sky

        if sky.is_sky_news_url(url):
            murl, mtype = sky.extract_podcast_audio(url, timeout=float(timeout))
            if murl:
                return murl, mtype
    except Exception:
        pass

    # 2. NPR specific
    if "npr.org" in url:
        from core import npr
        murl, mtype = npr.extract_npr_audio(url, timeout_s=float(timeout))
        if murl:
            return murl, mtype

    # 3. yt-dlp (with cookies)
    try:
        from core.dependency_check import _get_startup_info
        creationflags = 0
        if platform.system().lower() == "windows":
            creationflags = 0x08000000

        cmd = [_resolve_ytdlp_cli_path(), "--dump-json", "--no-playlist", url]
        
        # Add cookies if available
        cookies = get_ytdlp_cookie_sources(url)
        if cookies:
            browser = cookies[0][0]
            cmd.extend(["--cookies-from-browser", browser])
            if len(cookies[0]) > 1:
                cmd.append(cookies[0][1])

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=_get_startup_info(),
            timeout=timeout
        )
        
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            media_url = data.get("url")
            if media_url:
                # Determine type
                ext = data.get("ext", "")
                if ext == "mp3": mtype = "audio/mpeg"
                elif ext == "m4a": mtype = "audio/mp4"
                elif ext == "flac": mtype = "audio/flac"
                elif ext == "mp4": mtype = "video/mp4"
                else: mtype = "application/octet-stream" # Generic
                
                # Check if it's strictly video but we prefer audio? 
                # For now just return what we found.
                return media_url, mtype
    except Exception:
        pass
        
    return None, None
