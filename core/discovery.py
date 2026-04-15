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
from functools import lru_cache
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus, quote, unquote
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

_URL_FALLBACK_SITE_NAMES = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "facebook.com": "Facebook",
    "bilibili.com": "Bilibili",
    "rokfin.com": "Rokfin",
    "soundcloud.com": "SoundCloud",
}

_ROKFIN_PUBLIC_API_BASE = "https://prod-api-v2.production.rokfin.com/api/v2/public"
_QUICK_TITLE_PREFETCH_MAX_WORKERS = 6
_ALTERNATE_FEED_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/feed+json",
}


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

    domain = (parsed.netloc or "").lower()
    if scheme in ("http", "https") and not domain:
        return False

    # Fast allowlist for common media domains (keeps UI snappy).
    known_domains = [
        "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "dailymotion.com",
        "soundcloud.com", "facebook.com", "twitter.com", "x.com", "tiktok.com",
        "instagram.com", "rumble.com", "bilibili.com", "mixcloud.com",
        "odysee.com", "lbry.tv",
    ]
    if any(kd in domain for kd in known_domains):
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

    if platform.system().lower() == "windows":
        local = os.environ.get("LOCALAPPDATA", "")
        chromium_root = os.path.join(local, "Chromium") if local else ""
        chromium_user_data = os.path.join(chromium_root, "User Data") if chromium_root else ""
        if chromium_user_data and os.path.isdir(chromium_user_data):
            _add("chromium", chromium_user_data)
        elif chromium_root and os.path.isdir(chromium_root):
            _add("chromium", chromium_root)

        browser_dirs = [
            ("edge", os.path.join(local, "Microsoft", "Edge", "User Data")),
            ("brave", os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")),
            ("chrome", os.path.join(local, "Google", "Chrome", "User Data")),
        ]
        for name, path in browser_dirs:
            if path and os.path.isdir(path):
                _add(name)

    if not sources:
        for name in ("chromium", "edge", "brave", "chrome"):
            _add(name)

    return sources


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
    if path_low.endswith((".rss", ".xml", ".atom")):
        return True
    if path_low.endswith("/feed") or path_low.endswith("/feeds"):
        return True
    if "/feed/" in path_low or "/feeds/" in path_low:
        return True
    qs = parse_qs(parsed.query or "")
    for key in qs.keys():
        if str(key).lower() in ("feed", "rss", "format"):
            return True
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

    host = (parsed.netloc or "").lower()
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
    if "youtube.com" in host or "youtu.be" in host:
        if "youtu.be" in host and path_parts:
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
    host = (parsed.netloc or "").lower()
    if not host:
        return ""
    if not ("youtube.com" in host or "youtu.be" in host):
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
    host = (parsed.netloc or "").lower()
    if not host:
        return False
    host = host[4:] if host.startswith("www.") else host
    return ("youtube.com" in host) or ("youtu.be" in host) or ("rokfin.com" in host)


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
    target_url = str(url or "").strip()
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


def _normalize_ytdlp_search_entries(entries, site: dict, limit: int = 10) -> list[dict]:
    out: list[dict] = []
    seen_urls: set[str] = set()
    site_id = str((site or {}).get("id") or "").strip()
    search_site_label = str((site or {}).get("label") or site_id or "yt-dlp").strip()

    try:
        limit = max(1, min(500, int(limit or 10)))
    except Exception:
        limit = 10

    try:
        quick_title_map = _prefetch_quick_titles_for_entries(entries, limit=limit)
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
        title_is_fallback = False
        if raw_title:
            title = raw_title
        else:
            quick_title = str((quick_title_map or {}).get(str(url or "")) or "").strip()
            # Fallback for supported URLs not included in the prefetch map (e.g. later rows
            # after dedupe/filtering edge-cases).
            if not quick_title and _supports_quick_title_resolution(url):
                try:
                    quick_title = _resolve_quick_url_title_cached(str(url or ""))
                except Exception:
                    quick_title = ""
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


def search_ytdlp_site(term: str, site: dict, limit: int = 10, timeout: int = 15) -> list[dict]:
    """Search a single yt-dlp query-search site and normalize results for the GUI."""
    if not isinstance(site, dict):
        return []
    entries = _run_ytdlp_query_search(
        str(site.get("search_key") or ""),
        str(term or ""),
        limit=limit,
        timeout=timeout,
    )
    return _normalize_ytdlp_search_entries(entries, site=site, limit=limit)


def _youtube_playlist_id_from_url(url: str) -> str:
    """Extract a YouTube playlist ID from any YouTube URL with a list param."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower()
        if "youtube.com" not in domain and "youtu.be" not in domain:
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
        domain = (parsed.netloc or "").lower()
        if "youtube.com" not in domain and "youtu.be" not in domain:
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
    host = (parsed.netloc or "").lower()
    if not host or ("youtube.com" not in host and "youtu.be" not in host):
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
                low = candidate.lower()
                if "youtube.com" in low and any(p in low for p in ("/channel/", "/user/", "/@")):
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


def get_ytdlp_feed_url(url: str) -> str:
    """Try to get a native RSS feed for a yt-dlp supported URL (e.g. YouTube)."""
    if not url:
        return None
        
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    # 1. YouTube specific logic (fastest)
    if "youtube.com" in domain or "youtu.be" in domain:
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
                
            # extract_flat gives us channel info without downloading every video info
            # Use cookies to avoid "Sign in to confirm you’re not a bot" errors
            cmd = [_resolve_ytdlp_cli_path(), "--dump-json", "--playlist-items", "0", url]
            
            # Add cookies if available
            cookies = get_ytdlp_cookie_sources(url)
            if cookies:
                # Use the first available source
                browser = cookies[0][0]
                cmd.extend(["--cookies-from-browser", browser])
                if len(cookies[0]) > 1:
                    cmd.append(cookies[0][1]) # profile

            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                startupinfo=_get_startup_info(),
                timeout=15 # Increased timeout for cookie processing
            )
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                channel_id = data.get("channel_id") or data.get("id")
                if channel_id and data.get("_type") in ("playlist", "channel"):
                    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        except:
            pass

    # 2. Rumble note:
    # Rumble previously exposed /feeds/rss/... endpoints, but these are unreliable
    # (often 404/410). BlindRSS supports Rumble via HTML listing parsing + a
    # custom media resolver, so we intentionally do NOT return an RSS URL here.
            
    return None


def discover_feed(url: str, request_timeout: float = 10.0, probe_timeout: float = 5.0) -> str:
    """
    Given a URL, try to find the RSS/Atom feed URL.
    Returns None if not found.
    """
    if not url:
        return None
    
    # If it looks like a feed already
    if url.endswith(".xml") or url.endswith(".rss") or url.endswith(".atom") or "feed" in url:
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

        resp = utils.safe_requests_get(url, timeout=req_timeout)
        resp.raise_for_status()

        body_text = resp.text or ""
        content_type = str(resp.headers.get("Content-Type", "") or "").lower()
        looks_like_xml = (
            "xml" in content_type
            or body_text.lstrip().startswith("<?xml")
            or "<rss" in body_text[:512].lower()
            or "<feed" in body_text[:512].lower()
        )
        soup = BeautifulSoup(body_text, "xml" if looks_like_xml else "html.parser")
        
        # 1. Prefer the best matching alternate feed link when multiple are present.
        candidates = _alternate_feed_candidates(soup, url)
        if candidates:
            return candidates[0]
                    
        # 2. Check for common patterns if no link tag
        # e.g. /feed, /rss, /atom.xml
        # This is a bit brute force but helpful
        common_paths = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml"]
        base = url.rstrip("/")
        for path in common_paths:
            # Avoid re-checking
            candidate = base + path
            try:
                head = utils.safe_requests_head(candidate, timeout=head_timeout, allow_redirects=True)
                if head.status_code == 200 and "xml" in head.headers.get("Content-Type", ""):
                    return candidate
            except Exception:
                pass
                
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
    low = str(url).lower()
    if low.endswith(".xml") or low.endswith(".rss") or low.endswith(".atom") or "feed" in low:
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
        resp = utils.safe_requests_get(url, timeout=10)
        resp.raise_for_status()
        html = resp.text or ""

        soup = BeautifulSoup(html, "html.parser")

        # 1) <link rel="alternate" ...>, ordered by best page/feed match first.
        for candidate in _alternate_feed_candidates(soup, url):
            _add(candidate)

        # 2) Obvious <a href> candidates (best-effort)
        for a in soup.find_all("a", href=True):
            try:
                href = a.get("href")
                if not isinstance(href, str) or not href:
                    continue
                h = href.lower()
                if any(h.endswith(ext) for ext in (".rss", ".atom", ".xml", ".json")) or "/feed" in h or "rss" in h:
                    _add(urljoin(url, href))
            except Exception:
                continue

        # 3) Common paths (HEAD check)
        common_paths = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml"]
        base = url.rstrip("/")
        for path in common_paths:
            candidate = base + path
            try:
                head = utils.safe_requests_head(candidate, timeout=5, allow_redirects=True)
                if head.status_code == 200:
                    ct = (head.headers.get("Content-Type", "") or "").lower()
                    if any(x in ct for x in ("xml", "rss", "atom", "json")):
                        _add(candidate)
            except Exception:
                continue

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

def detect_media(url: str, timeout: int = 20) -> tuple[str | None, str | None]:
    """
    Attempt to detect media (audio/video) for a given URL using yt-dlp and other heuristics.
    Returns (media_url, media_type) or (None, None).
    """
    if not url:
        return None, None

    # 1. NPR specific
    if "npr.org" in url:
        from core import npr
        murl, mtype = npr.extract_npr_audio(url, timeout_s=float(timeout))
        if murl:
            return murl, mtype

    # 2. yt-dlp (with cookies)
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
