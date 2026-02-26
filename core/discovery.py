import os
import subprocess
import json
import platform
import re
import threading
from functools import lru_cache
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus
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


def _youtube_search_entries_to_channel_feeds(entries, limit: int = 10) -> list[dict]:
    """Convert yt-dlp ytsearch entries into unique YouTube channel RSS feed results."""
    out: list[dict] = []
    seen: set[str] = set()
    try:
        limit = max(1, min(50, int(limit or 10)))
    except Exception:
        limit = 10

    for entry in (entries or []):
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
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        title = (
            str(entry.get("channel") or "").strip()
            or str(entry.get("uploader") or "").strip()
            or str(entry.get("title") or "").strip()
            or channel_id
            or feed_url
        )
        handle = str(entry.get("uploader_id") or "").strip()
        detail = "YouTube channel"
        if handle:
            detail = f"{detail} ({handle})"

        out.append(
            {
                "title": title,
                "detail": detail,
                "url": feed_url,
            }
        )
        if len(out) >= limit:
            break

    return out


def _youtube_search_entries_to_playlist_feeds(entries, limit: int = 10) -> list[dict]:
    """Convert yt-dlp playlist-search entries into YouTube playlist RSS results."""
    out: list[dict] = []
    seen: set[str] = set()
    try:
        limit = max(1, min(50, int(limit or 10)))
    except Exception:
        limit = 10

    for entry in (entries or []):
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
        if playlist_id in seen:
            continue
        seen.add(playlist_id)

        title = (
            str(entry.get("title") or "").strip()
            or playlist_id
        )
        owner = (
            str(entry.get("channel") or "").strip()
            or str(entry.get("uploader") or "").strip()
            or str(entry.get("playlist_uploader") or "").strip()
        )
        detail = "YouTube playlist"
        if owner:
            detail = f"{detail} ({owner})"

        out.append(
            {
                "title": title,
                "detail": detail,
                "url": feed_url,
            }
        )
        if len(out) >= limit:
            break

    return out


def search_youtube_channels(term: str, limit: int = 10, timeout: int = 15) -> list[dict]:
    """Search YouTube via yt-dlp and return channel RSS feed candidates.

    Results are normalized for the Feed Search dialog and use native YouTube RSS URLs.
    """
    query = str(term or "").strip()
    if not query:
        return []

    try:
        limit = max(1, min(20, int(limit or 10)))
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
            "yt-dlp",
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
        limit = max(1, min(20, int(limit or 10)))
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
            "yt-dlp",
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
        return _youtube_search_entries_to_playlist_feeds(entries, limit=limit)
    except Exception:
        return []


def search_youtube_feeds(term: str, limit: int = 12, timeout: int = 15) -> list[dict]:
    """Search YouTube for channel and playlist RSS feed candidates."""
    query = str(term or "").strip()
    if not query:
        return []

    try:
        limit = max(1, min(30, int(limit or 12)))
    except Exception:
        limit = 12
    try:
        timeout = max(5, min(60, int(timeout or 15)))
    except Exception:
        timeout = 15

    channel_limit = max(1, min(limit, (limit * 2) // 3 or 1))
    playlist_limit = max(1, min(limit, max(2, limit // 2)))

    out: list[dict] = []
    seen_urls: set[str] = set()

    for item in (search_youtube_channels(query, limit=channel_limit, timeout=timeout) or []):
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(item)
        if len(out) >= limit:
            return out

    for item in (_search_youtube_playlists(query, limit=playlist_limit, timeout=timeout) or []):
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(item)
        if len(out) >= limit:
            break

    return out


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
            cmd = ["yt-dlp", "--dump-json", "--playlist-items", "0", url]
            
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


def discover_feed(url: str) -> str:
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
        resp = utils.safe_requests_get(url, timeout=10)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. <link rel="alternate" type="application/rss+xml" href="...">
        links = soup.find_all("link", rel="alternate")
        for link in links:
            if link.get("type") in ["application/rss+xml", "application/atom+xml", "text/xml"]:
                href = link.get("href")
                if href:
                    return urljoin(url, href)
                    
        # 2. Check for common patterns if no link tag
        # e.g. /feed, /rss, /atom.xml
        # This is a bit brute force but helpful
        common_paths = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml"]
        base = url.rstrip("/")
        for path in common_paths:
            # Avoid re-checking
            candidate = base + path
            try:
                head = utils.safe_requests_head(candidate, timeout=5, allow_redirects=True)
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

        # 1) <link rel="alternate" ...>
        for link in soup.find_all("link", href=True):
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
                if ctype not in (
                    "application/rss+xml",
                    "application/atom+xml",
                    "application/xml",
                    "text/xml",
                    "application/feed+json",
                    "application/json",
                ):
                    continue

                href = link.get("href")
                if href:
                    _add(urljoin(url, href))
            except Exception:
                continue

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

        cmd = ["yt-dlp", "--dump-json", "--no-playlist", url]
        
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
