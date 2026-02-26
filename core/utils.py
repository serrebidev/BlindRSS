import requests
import re
import uuid
import logging
import sqlite3
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup as BS
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser
from dateutil.parser import UnknownTimezoneWarning
from io import BytesIO
from core.db import get_connection
import warnings
import urllib.parse

log = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=UnknownTimezoneWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml,application/xml,application/atom+xml,text/xml;q=0.9,*/*;q=0.8'
}

_FLAC_MIME_ALIASES = {
    "audio/flac",
    "audio/x-flac",
    "application/flac",
    "application/x-flac",
}

_ACTIVITY_TITLE_GENERIC_TEXTS = {
    "see more",
    "more",
    "profile",
    "replied",
    "reply",
    "commented",
    "comment",
    "liked",
}


def add_revalidation_headers(headers: dict | None = None) -> dict:
    """Return headers with cache-bypass directives for proxy/CDN revalidation."""
    merged = dict(headers or {})
    # Include both directives for older intermediaries and stricter caches.
    merged.setdefault("Cache-Control", "no-cache, max-age=0")
    merged.setdefault("Pragma", "no-cache")
    merged.setdefault("Expires", "0")
    return merged


def canonical_media_type(media_type: str | None) -> str:
    """Normalize common media MIME aliases to a stable value."""
    mt = str(media_type or "").split(";", 1)[0].strip().lower()
    if mt in _FLAC_MIME_ALIASES:
        return "audio/flac"
    return mt


def media_type_is_audio_video_or_podcast(media_type: str | None) -> bool:
    mt = canonical_media_type(media_type)
    if not mt:
        return False
    return mt.startswith(("audio/", "video/")) or "podcast" in mt


def _activity_title_norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _activity_title_norm_link(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(str(url or "").strip())
    except Exception:
        return ""
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = urllib.parse.unquote((p.path or "").rstrip("/"))
    # Ignore tracking-style params so activity links can match canonical content links.
    try:
        q = urllib.parse.parse_qsl(p.query or "", keep_blank_values=True)
        q = [(k, v) for (k, v) in q if str(k).lower() not in {"xg_source", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}]
        q.sort()
        query = urllib.parse.urlencode(q, doseq=True)
    except Exception:
        query = ""
    return urllib.parse.urlunsplit((p.scheme.lower(), host, path, query, ""))


def _activity_title_anchor_has_ancestor(a, tag_names: tuple[str, ...] = (), class_names: tuple[str, ...] = ()) -> bool:
    try:
        for parent in getattr(a, "parents", []) or []:
            if parent is None:
                continue
            if tag_names and str(getattr(parent, "name", "") or "").lower() in tag_names:
                return True
            if class_names:
                classes = [str(c or "").lower() for c in (parent.get("class") or [])]
                if any(cls in classes for cls in class_names):
                    return True
    except Exception:
        return False
    return False


def _looks_like_generic_activity_link_text(text: str) -> bool:
    t = _activity_title_norm_space(text).lower().strip(" .:;!-")
    if not t:
        return True
    if t in _ACTIVITY_TITLE_GENERIC_TEXTS:
        return True
    if re.fullmatch(r"\d+\s+more(?:…|\.\.\.)?", t):
        return True
    if "more" in t and len(t) <= 10:
        return True
    return False


def _looks_like_profile_activity_link(href: str) -> bool:
    href_low = str(href or "").lower()
    return "/profile/" in href_low or "/members/" in href_low


def enhance_activity_entry_title(title: str | None, url: str | None, content: str | None) -> str:
    """Derive a better title from activity-feed HTML when the real story title is embedded.

    This is intentionally conservative and primarily targets Ning-style activity feeds where
    generic titles like "X posted a video" hide the actual content title in the description HTML.
    """
    cur_title = _activity_title_norm_space(title or "")
    html = str(content or "")
    if not html or "<" not in html or ">" not in html:
        return cur_title

    low_html = html.lower()
    # Markers commonly seen in Ning activity feeds and similar "activity log" HTML.
    if not any(m in low_html for m in ("feed-story-title", "xg_source=activity", "feed-more", "<strong><a", "</strong><a")):
        return cur_title

    try:
        soup = BS(html, "html.parser")
    except Exception:
        return cur_title

    target_url = _activity_title_norm_link(url or "")
    candidates: list[tuple[int, int, str]] = []

    for idx, a in enumerate(soup.find_all("a", href=True)):
        try:
            text = _activity_title_norm_space(a.get_text(" ", strip=True))
        except Exception:
            text = ""
        href = str(a.get("href") or "").strip()
        if not text or not href:
            continue

        score = 0
        if _looks_like_generic_activity_link_text(text):
            score -= 8
        else:
            score += 1

        if _looks_like_profile_activity_link(href):
            score -= 4

        # Prefer explicit story-title wrappers and strong heading-style links.
        classes = [str(c or "").lower() for c in (a.get("class") or [])]
        if "feed-story-title" in classes:
            score += 8
        if _activity_title_anchor_has_ancestor(a, class_names=("feed-story-title",)):
            score += 8
        if _activity_title_anchor_has_ancestor(a, tag_names=("h1", "h2", "h3", "h4", "h5", "h6")):
            score += 6
        if _activity_title_anchor_has_ancestor(a, tag_names=("strong",)):
            score += 5
        if _activity_title_anchor_has_ancestor(a, class_names=("feed-more",)):
            score -= 10

        href_norm = _activity_title_norm_link(href)
        if target_url and href_norm and href_norm == target_url:
            score += 7
        elif target_url and href_norm and urllib.parse.urlsplit(href_norm).path == urllib.parse.urlsplit(target_url).path:
            score += 4

        # Prefer meaningful longer titles over action words.
        score += min(6, max(0, len(text) // 20))

        candidates.append((score, -idx, text))

    if not candidates:
        return cur_title

    candidates.sort(reverse=True)
    best_score, _neg_idx, best_text = candidates[0]
    if best_score < 6:
        return cur_title
    if _looks_like_generic_activity_link_text(best_text):
        return cur_title

    return best_text or cur_title

# Common timezone abbreviations mapping for dateutil
TZINFOS = {
    "UTC": 0,
    "GMT": 0,
    "EST": -18000,
    "EDT": -14400,
    "CST": -21600,
    "CDT": -18000,
    "MST": -25200,
    "MDT": -21600,
    "PST": -28800,
    "PDT": -25200,
}


def build_playback_speeds(start: float = 0.5, stop: float = 4.0, step: float = 0.12):
    """
    Generate a list of playback speeds rounded to 2 decimals, inclusive of bounds.
    Default range: 0.50x .. 4.00x in 0.12 increments (VLC-safe window).
    """
    speeds = []
    val = round(start, 2)
    upper = round(stop, 2)
    while val <= upper + 1e-9:
        speeds.append(val)
        val = round(val + step, 2)
    if speeds[-1] != upper:
        speeds.append(upper)
    # Always include true 1.00x so "Normal" snaps exactly, not ~0.98x
    speeds.append(1.0)
    # Deduplicate and sort to keep monotonic order, but drop near-1.0 variants like 0.98
    speeds = sorted(set(round(v, 2) for v in speeds))
    cleaned = []
    for v in speeds:
        if abs(v - 1.0) <= 0.025 and abs(v - 1.0) > 1e-9:
            continue
        cleaned.append(v)
    return cleaned


def safe_requests_get(url, **kwargs):
    """Wrapper for requests.get with default browser headers."""
    headers = kwargs.pop("headers", {})
    # Merge with defaults, preserving caller's headers if they exist
    final_headers = HEADERS.copy()
    final_headers.update(headers)
    return requests.get(url, headers=final_headers, **kwargs)


def safe_requests_head(url, **kwargs):
    """Wrapper for requests.head with default browser headers."""
    headers = kwargs.pop("headers", {})
    final_headers = HEADERS.copy()
    final_headers.update(headers)
    return requests.head(url, headers=final_headers, **kwargs)


def build_cache_id(article_id: str | None, feed_id: str | None = None, provider: str | None = None) -> str | None:
    """Build a stable cache id that scopes articles by provider/feed when needed."""
    if not article_id:
        return None
    parts = []
    if provider:
        parts.append(str(provider))
    if feed_id:
        parts.append(str(feed_id))
    prefix = ":".join(parts)
    aid = str(article_id)
    if prefix:
        if aid.startswith(prefix + ":"):
            return aid
        return f"{prefix}:{aid}"
    return aid

# --- Date Parsing ---


def format_datetime(dt: datetime) -> str:
    """Return UTC-normalized string for consistent ordering.
    Assumes naive datetimes are already in UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def extract_date_from_text(text: str, fuzzy: bool = True):
    """
    Try multiple date patterns inside arbitrary text.
    Returns datetime or None.
    """
    if not text:
        return None
    
    # 1) ISO-like yyyy-mm-dd (Check FIRST to avoid greedy matching by other patterns)
    m_iso = re.search(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b", text)
    if m_iso:
        try:
            y, mth, d = map(int, m_iso.groups())
            if 1 <= mth <= 12 and 1 <= d <= 31:
                return datetime(y, mth, d, tzinfo=timezone.utc)
        except Exception:
            pass

    # 2) numeric with / or - (e.g. 12/25/2023 or 25-12-23)
    # Require word boundaries to avoid matching inside other numbers
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if m:
        a, b, year = m.groups()
        try:
            year_int = int(year)
            if year_int < 100:
                year_int += 2000 if year_int < 70 else 1900
            a_int, b_int = int(a), int(b)
            # heuristic: if both <=12, prefer US mm/dd for consistency with dateparser defaults
            if a_int > 12 and b_int <= 12:
                day, month = a_int, b_int
            elif b_int > 12 and a_int <= 12:
                day, month = b_int, a_int
            else:
                month, day = a_int, b_int
            if 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year_int, month, day, tzinfo=timezone.utc)
        except Exception:
            pass
            
    # 3) Explicit Month Name (Strict) - e.g. "Jan 1, 2020", "15 May 1999"
    # Matches: Month DD, YYYY or DD Month YYYY
    m_text = re.search(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text)
    if not m_text:
        m_text = re.search(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+(\d{4})\b", text)
        
    if m_text:
        try:
            dt = dateparser.parse(m_text.group(0), tzinfos=TZINFOS)
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except Exception:
            pass

    if not fuzzy:
        return None

    # 4) Month name forms (fuzzy fallback)
    try:
        dt = dateparser.parse(text, fuzzy=True, default=datetime(1900, 1, 1, tzinfo=timezone.utc), tzinfos=TZINFOS)
        if dt and dt.year > 1900:
            # If parser only saw a bare year (fills month/day with defaults), skip it;
            # we don't want to override feed dates with year-only hints like "2025".
            lower = text.lower()
            has_month_day_hint = (
                re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{1,2}", lower) or
                re.search(r"\d{1,2}[/-]\d{1,2}", text) or
                re.search(r"\d{4}-\d{1,2}-\d{1,2}", text)
            )
            only_year = (dt.month == 1 and dt.day == 1 and not has_month_day_hint)
            if not only_year:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
    except Exception:
        pass
    return None


def normalize_date(raw_date_str: str, title: str = "", content: str = "", url: str = "") -> str:
    """
    Robust date normalizer.
    Prioritizes the Raw Feed Date to ensure correct sorting of new articles.
    Fallbacks to Title/URL/Content only if the feed date is missing or invalid.
    """
    now = datetime.now(timezone.utc)
    
    def valid(dt: datetime) -> bool:
        if not dt:
            return False
        if dt.tzinfo:
            dt_cmp = dt.astimezone(timezone.utc)
        else:
            dt_cmp = dt.replace(tzinfo=timezone.utc)
        # discard if more than 2 days in future (some timezones are ahead, but not by years)
        if (dt_cmp - now) > timedelta(days=2):
            return False
        # Discard if ridiculously old (before RSS existed) unless it's explicitly parsed
        if dt_cmp.year < 1990:
            return False
        return True

    # 1) Check raw feed date (Priority)
    if raw_date_str:
        # Check for Unix Timestamp (numeric string)
        if raw_date_str.replace('.', '', 1).isdigit():
            try:
                ts = float(raw_date_str)
                # Reasonable bounds for timestamp (e.g. > 1980 and < 2100)
                if 315532800 < ts < 4102444800:
                    dt = datetime.fromtimestamp(ts, timezone.utc)
                    if valid(dt):
                        return format_datetime(dt)
            except Exception:
                pass

        try:
            dt = dateparser.parse(raw_date_str, tzinfos=TZINFOS)
            if valid(dt):
                return format_datetime(dt)
        except Exception:
            pass

    # 2) Check Title (Fallback)
    if title:
        dt = extract_date_from_text(title, fuzzy=False)
        if dt and valid(dt):
            return format_datetime(dt)

    # 3) Check URL (Fallback)
    if url:
        dt = extract_date_from_text(url, fuzzy=False)
        if dt and valid(dt):
            return format_datetime(dt)

    # 4) Check content (Allow fuzzy here as content often contains "Published on..." blocks)
    if content:
        dt = extract_date_from_text(content, fuzzy=True)
        if dt and valid(dt):
            return format_datetime(dt)

    # 5) Fallback sentinel
    return "0001-01-01 00:00:00"



def parse_datetime_utc(value: str):
    """Parse a date/time string into an aware UTC datetime.

    BlindRSS stores normalized dates as UTC-formatted strings ("YYYY-MM-DD HH:MM:SS").
    If a parsed datetime is naive, it is assumed to be UTC.

    Returns:
        datetime (tz-aware, UTC) or None if parsing fails or the value is a sentinel.
    """
    if not value:
        return None
    value = str(value).strip()
    if not value or value.startswith("0001-01-01"):
        return None

    dt = None
    # Optimize: Try fast standard parsing first (DB uses this format)
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        try:
            # Fallback for older python or slightly different formats
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    if not dt:
        try:
            dt = dateparser.parse(value, tzinfos=TZINFOS)
        except Exception:
            dt = None

    if not dt:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def humanize_article_date(date_str: str, now_utc: datetime = None) -> str:
    """Human-friendly article date.

    - For the first 24 hours: relative time (e.g., "5 minutes ago", "2 hours ago").
    - After 24 hours: absolute local time using the system timezone.
    """
    dt_utc = parse_datetime_utc(date_str)
    if not dt_utc:
        return ""

    now = now_utc or datetime.now(timezone.utc)
    delta = now - dt_utc
    if delta.total_seconds() < 0:
        delta = timedelta(seconds=0)

    if delta <= timedelta(hours=24):
        secs = int(delta.total_seconds())
        if secs < 60:
            return "Just now"
        mins = secs // 60
        if mins < 60:
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        hours = mins // 60
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    # Absolute local time
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    dt_local = dt_utc.astimezone(local_tz)
    return dt_local.strftime("%Y-%m-%d %H:%M")


# --- Chapters ---


def get_chapters_from_db(article_id: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT start, title, href FROM chapters WHERE article_id = ? ORDER BY start", (article_id,))
        rows = c.fetchall()
        return [{"start": r[0], "title": r[1], "href": r[2]} for r in rows]
    finally:
        conn.close()


def get_chapters_batch(article_ids: list) -> dict:
    """
    Fetches chapters for multiple articles in chunks to optimize performance.
    Returns a dict: {article_id: [chapter_list]}
    """
    if not article_ids:
        return {}
    
    conn = get_connection()
    try:
        c = conn.cursor()
        chapters_map = {}
        
        # SQLite limit usually 999 vars
        chunk_size = 900
        for i in range(0, len(article_ids), chunk_size):
            chunk = article_ids[i:i+chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            c.execute(f"SELECT article_id, start, title, href FROM chapters WHERE article_id IN ({placeholders}) ORDER BY article_id, start", chunk)
            for row in c.fetchall():
                aid = row[0]
                if aid not in chapters_map:
                    chapters_map[aid] = []
                chapters_map[aid].append({"start": row[1], "title": row[2], "href": row[3]})
                
        return chapters_map
    finally:
        conn.close()


def fetch_and_store_chapters(article_id, media_url, media_type, chapter_url=None, allow_id3: bool = True, cursor=None):
    """
    Fetches chapters from chapter_url (JSON) or media_url (ID3 tags).
    Stores them in DB linked to article_id.
    Returns list of chapter dicts.
    """
    try:
        article_key = str(article_id).strip() if article_id is not None else ""
    except Exception:
        article_key = ""
    if not article_key:
        article_key = None

    # Check DB first
    # Note: get_chapters_from_db opens its own connection. 
    # If we are in a transaction (cursor provided), we should probably use that cursor or skip this check if we know it's a fresh insert.
    # But for simplicity, we can just query using the provided cursor if available.
    if cursor and article_key:
        cursor.execute("SELECT start, title, href FROM chapters WHERE article_id = ? ORDER BY start", (article_key,))
        rows = cursor.fetchall()
        existing = [{"start": float(r[0] or 0), "title": r[1], "href": r[2]} for r in rows]
    elif article_key:
        existing = get_chapters_from_db(article_key)
    else:
        existing = []
        
    if existing:
        return existing

    chapters_out = []
    
    # 1) Explicit chapter URL (Podcasting 2.0)
    if chapter_url:
        try:
            resp = safe_requests_get(chapter_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            chapters = data.get("chapters", [])
            
            persist_enabled = bool(article_key)
            c = None
            conn = None
            if persist_enabled:
                if cursor:
                    c = cursor
                else:
                    conn = get_connection()
                    c = conn.cursor()
                
            try:
                persist_blocked = False
                for ch in chapters:
                    ch_id = str(uuid.uuid4())
                    start = ch.get("startTime") or ch.get("start_time") or 0
                    title_ch = ch.get("title", "")
                    href = ch.get("url") or ch.get("link")
                    start_f = float(start)
                    chapters_out.append({"start": start_f, "title": title_ch, "href": href})
                    if c is None or persist_blocked:
                        continue
                    try:
                        c.execute(
                            "INSERT OR REPLACE INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
                            (ch_id, article_key, start_f, title_ch, href),
                        )
                    except sqlite3.IntegrityError as e:
                        persist_blocked = True
                        log.info(
                            "Skipping chapter DB persistence for article_id=%s due to DB constraint: %s",
                            article_key,
                            e,
                        )
                
                if conn is not None:
                    conn.commit()
            finally:
                if conn is not None:
                    conn.close()

            if chapters_out:
                return chapters_out
        except Exception as e:
            log.warning(f"Chapter fetch failed for {chapter_url}: {e}")

    if not allow_id3:
        return chapters_out

    # 2) ID3 CHAP frames if audio
    media_url_str = str(media_url or "")
    media_type_l = canonical_media_type(media_type)
    media_path_l = urllib.parse.urlsplit(media_url_str).path.lower() or media_url_str.lower()
    audio_exts = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac")

    if media_url and (media_type_l.startswith("audio/") or "podcast" in media_type_l or media_path_l.endswith(audio_exts)):
        try:
            from mutagen.id3 import ID3, error as ID3Error

            def _read_prefix_bytes(url: str, *, headers: dict, max_bytes: int, timeout_s: int) -> bytes:
                if max_bytes <= 0:
                    return b""
                resp = safe_requests_get(url, headers=headers, timeout=int(timeout_s), stream=True)
                try:
                    if not getattr(resp, "ok", False):
                        return b""
                    buf = bytearray()
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        remaining = int(max_bytes) - len(buf)
                        if remaining <= 0:
                            break
                        if len(chunk) > remaining:
                            buf.extend(chunk[:remaining])
                            break
                        buf.extend(chunk)
                        if len(buf) >= int(max_bytes):
                            break
                    return bytes(buf)
                finally:
                    try:
                        resp.close()
                    except Exception:
                        pass

            # Read just the ID3v2 header first to determine tag size.
            hdr = _read_prefix_bytes(media_url, headers={"Range": "bytes=0-9"}, max_bytes=10, timeout_s=6)
            if len(hdr) < 10 or hdr[:3] != b"ID3":
                return chapters_out

            try:
                flags = int(hdr[5])
                ss = hdr[6:10]
                tag_size = ((ss[0] & 0x7F) << 21) | ((ss[1] & 0x7F) << 14) | ((ss[2] & 0x7F) << 7) | (ss[3] & 0x7F)
                total = int(tag_size) + 10
                if flags & 0x10:
                    # Footer present.
                    total += 10
            except Exception:
                total = 0

            # Never download large media files just to detect chapters.
            max_tag_bytes = 1_000_000
            if total <= 10 or total > max_tag_bytes:
                return chapters_out

            tag_bytes = _read_prefix_bytes(
                media_url,
                headers={"Range": f"bytes=0-{int(total) - 1}"},
                max_bytes=int(total),
                timeout_s=12,
            )
            if len(tag_bytes) < 10 or tag_bytes[:3] != b"ID3":
                return chapters_out

            id3 = ID3(BytesIO(tag_bytes))

            parsed_chapters = []
            for frame in id3.getall("CHAP"):
                start = frame.start_time / 1000.0 if frame.start_time else 0
                title_ch = ""
                tit2 = frame.sub_frames.get("TIT2")
                if tit2 and tit2.text:
                    title_ch = tit2.text[0]
                href = None
                parsed_chapters.append({"start": float(start), "title": title_ch, "href": href})

            if not parsed_chapters:
                return chapters_out

            chapters_out.extend(parsed_chapters)

            persist_enabled = bool(article_key)
            c = None
            conn = None
            if persist_enabled:
                if cursor:
                    c = cursor
                else:
                    conn = get_connection()
                    c = conn.cursor()
            
            try:
                persist_blocked = False
                for ch in parsed_chapters:
                    ch_id = str(uuid.uuid4())
                    if c is None or persist_blocked:
                        continue
                    try:
                        c.execute(
                            "INSERT OR REPLACE INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
                            (ch_id, article_key, float(ch["start"]), ch.get("title", ""), ch.get("href")),
                        )
                    except sqlite3.IntegrityError as e:
                        persist_blocked = True
                        log.info(
                            "Skipping chapter DB persistence for article_id=%s due to DB constraint: %s",
                            article_key,
                            e,
                        )

                if conn is not None:
                    conn.commit()
            finally:
                if conn is not None:
                    conn.close()
        except ImportError:
            log.info("mutagen not installed, skipping ID3 chapter parse.")
        except ID3Error as e:
            log.info(f"ID3 chapter parse failed for {media_url}: {e}")
        except Exception as e:
            log.info(f"ID3 chapter parse failed for {media_url}: {e}")

    return chapters_out


# --- OPML Helpers ---

def parse_opml(path: str):
    """
    Parses an OPML file and yields (title, url, category) tuples.
    """
    try:
        content = ""
        # Try to read file with different encodings
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        
        if not content:
            log.error("OPML Parse: Could not read file with supported encodings")
            return

        # Try parsing with BS4
        soup = None
        try:
            soup = BS(content, 'xml')
        except Exception:
            pass
        
        if not soup or not soup.find('opml'):
            soup = BS(content, 'html.parser')

        body = soup.find('body')
        if not body:
            return

        def process_outline(outline, current_category="Uncategorized"):
            # Case insensitive attribute lookup
            def get_attr(name):
                if name in outline.attrs:
                    return outline.attrs[name]
                for k, v in outline.attrs.items():
                    if k.lower() == name.lower():
                        return v
                return None

            text = get_attr('text') or get_attr('title')
            xmlUrl = get_attr('xmlUrl')
            
            if xmlUrl:
                yield (text, xmlUrl, current_category)
            
            # Recursion
            children = outline.find_all('outline', recursive=False)
            if children:
                new_cat = current_category
                if not xmlUrl:
                    # It's a folder
                    new_cat = text
                for child in children:
                    yield from process_outline(child, new_cat)

        for outline in body.find_all('outline', recursive=False):
            yield from process_outline(outline)

    except Exception as e:
        log.error(f"OPML Parse Error: {e}")


def write_opml(feeds: list, path: str):
    """
    Writes a list of Feed objects (or dicts/tuples with title, url, category) to an OPML file.
    """
    try:
        root = ET.Element("opml", version="1.0")
        head = ET.SubElement(root, "head")
        ET.SubElement(head, "title").text = "RSS Exports"
        body = ET.SubElement(root, "body")
        
        # Group by category
        categories = {}
        for feed in feeds:
            # Handle both objects and dicts/tuples if needed, assuming Feed objects primarily
            title = getattr(feed, 'title', None)
            url = getattr(feed, 'url', None)
            cat = getattr(feed, 'category', "Uncategorized")
            
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((title, url))
            
        for cat, items in categories.items():
            if cat == "Uncategorized" or not cat:
                for title, url in items:
                    ET.SubElement(body, "outline", text=title or "", xmlUrl=url or "")
            else:
                cat_outline = ET.SubElement(body, "outline", text=cat)
                for title, url in items:
                    ET.SubElement(cat_outline, "outline", text=title or "", xmlUrl=url or "")
                    
        tree = ET.ElementTree(root)
        tree.write(path, encoding='utf-8', xml_declaration=True)
        return True
    except Exception as e:
        log.error(f"OPML Write Error: {e}")
        return False

def resolve_final_url(url: str, max_redirects: int = 30, timeout_s: float = 15.0, user_agent: str | None = None) -> str:
    """Resolve tracking/redirect URLs to a final URL that VLC can open reliably.

    This performs an HTTP GET with redirects enabled and then closes the response immediately.
    """
    if not isinstance(url, str):
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        return url

    ua = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    hdrs = HEADERS.copy()
    hdrs["User-Agent"] = ua

    try:
        s = requests.Session()
        s.max_redirects = int(max_redirects) if int(max_redirects) > 0 else 30
        # GET (not HEAD): many trackers/hosts behave differently for HEAD and can loop.
        r = s.get(url, allow_redirects=True, timeout=timeout_s, headers=hdrs, stream=True)
        # Consume nothing; just close the socket.
        final = r.url or url
        try:
            r.close()
        except Exception:
            pass
        return final
    except Exception:
        return url


def normalize_url_for_vlc(url: str) -> str:
    """Ensure URL is safely encoded for VLC (avoid unescaped spaces, etc.)."""
    if not isinstance(url, str):
        return url
    if not (url.startswith("http://") or url.startswith("https://")):
        return url
    try:
        parts = urllib.parse.urlsplit(url)
        # Keep reserved characters, but encode spaces and other unsafe chars.
        # Include '%' in safe to avoid double-encoding already-encoded sequences like %27.
        path = urllib.parse.quote(parts.path, safe="/:@-._~!$&'()*+,;=%")
        query = urllib.parse.quote_plus(parts.query, safe="=&:@-._~!$&'()*+,;/%")
        frag = urllib.parse.quote(parts.fragment, safe="%")
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, frag))
    except Exception:
        return url
