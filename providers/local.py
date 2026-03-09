import feedparser
import time
import uuid
import threading
import sqlite3
import concurrent.futures
import os
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from urllib.parse import urlparse
from .base import RSSProvider
from core.models import Feed, Article
from core.db import get_connection, init_db
from core.discovery import discover_feed
from core import utils
from core import rumble as rumble_mod
from core import odysee as odysee_mod
from core import npr as npr_mod
from bs4 import BeautifulSoup as BS, XMLParsedAsHTMLWarning
import xml.etree.ElementTree as ET
import logging
import warnings

# Avoid noisy warnings when falling back to HTML parser for XML content
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

log = logging.getLogger(__name__)

_REFRESH_WORKERS_CPU_1_2 = 1
_REFRESH_WORKERS_CPU_3_4 = 2
_REFRESH_WORKERS_CPU_5_PLUS = 3
_REFRESH_PER_HOST_LOW_CPU = 1
_REFRESH_PER_HOST_NORMAL = 2

_REMOVE_FEED_BUSY_TIMEOUT_MS = 5000


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
    return _REFRESH_WORKERS_CPU_5_PLUS


def _compute_refresh_limits(
    configured_workers: int,
    configured_per_host: int,
    feed_count: int,
    cpu_count: Optional[int] = None,
) -> Tuple[int, int, int]:
    adaptive_cap = _adaptive_refresh_worker_cap(cpu_count)
    max_workers = max(1, min(int(configured_workers), adaptive_cap, max(1, int(feed_count))))
    per_host_cap = _REFRESH_PER_HOST_LOW_CPU if adaptive_cap <= 2 else _REFRESH_PER_HOST_NORMAL
    per_host_limit = max(1, min(int(configured_per_host), per_host_cap, max_workers))
    return max_workers, per_host_limit, adaptive_cap


class LocalProvider(RSSProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        init_db()

    def get_name(self) -> str:
        return "Local RSS"

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
            self._refresh_single_feed(row, host_limits, feed_timeout, retries, progress_cb, force=True)
            return True
        except Exception as e:
            log.error(f"Single feed refresh failed: {e}")
            return False

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

        if not feeds:
            return True

        configured_workers = max(1, int(self.config.get("max_concurrent_refreshes", 5) or 1))
        configured_per_host = max(1, int(self.config.get("per_host_max_connections", 3) or 1))

        cpu_count = max(1, int(os.cpu_count() or 1))
        max_workers, per_host_limit, adaptive_cap = _compute_refresh_limits(
            configured_workers,
            configured_per_host,
            len(feeds),
            cpu_count=cpu_count,
        )

        if configured_workers != max_workers:
            log.info(
                "Clamping max_concurrent_refreshes from %s to %s for responsiveness (cpu=%s, adaptive_cap=%s)",
                configured_workers,
                max_workers,
                cpu_count,
                adaptive_cap,
            )
        if configured_per_host != per_host_limit:
            log.info(
                "Clamping per_host_max_connections from %s to %s (cpu=%s, adaptive_cap=%s)",
                configured_per_host,
                per_host_limit,
                cpu_count,
                adaptive_cap,
            )
        feed_timeout = max(1, int(self.config.get("feed_timeout_seconds", 15) or 15))
        retries = max(0, int(self.config.get("feed_retry_attempts", 1) or 0))

        host_limits = defaultdict(lambda: threading.Semaphore(per_host_limit))

        def task(feed_row):
            return self._refresh_single_feed(feed_row, host_limits, feed_timeout, retries, progress_cb, force)

        # Increase workers for network-bound tasks
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(task, f): f for f in feeds}
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log.error(f"Refresh worker error: {e}")
        return True

    def _refresh_single_feed(self, feed_row, host_limits, feed_timeout, retries, progress_cb, force=False):
        # Each thread gets its own connection
        feed_id, feed_url, feed_title, feed_category, etag, last_modified, title_is_custom = feed_row
        status = "ok"
        new_items = 0
        new_article_summaries = []
        error_msg = None
        final_title = feed_title or "Unknown Feed"

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

        headers = {}
        is_npr_feed = npr_mod.is_npr_url(feed_url)

        # Some RSS/podcast CDNs set long cache lifetimes and may serve cached 200/304 responses
        # until their max-age expires. Sending "no-cache" forces intermediary revalidation so
        # new episodes appear promptly (instead of only after restart / cache expiry).
        if force:
            headers = utils.add_revalidation_headers(headers)

        use_conditional = (not force) and (not is_npr_feed)
        if use_conditional:
            if etag:
                headers['If-None-Match'] = etag
            if last_modified:
                headers['If-Modified-Since'] = last_modified

            if etag or last_modified:
                headers = utils.add_revalidation_headers(headers)
        elif not force and is_npr_feed and (etag or last_modified):
            log.debug("Skipping conditional headers for NPR feed %s", feed_url)

        host = urlparse(feed_url).hostname or feed_url
        limiter = host_limits[host]

        xml_text = None
        new_etag = None
        new_last_modified = None

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

            with limiter:
                last_exc = None
                attempts = retries + 1
                for attempt in range(1, attempts + 1):
                    try:
                        resp = utils.safe_requests_get(feed_url, headers=headers, timeout=feed_timeout)
                        if resp.status_code == 304:
                            status = "not_modified"
                            new_etag = etag
                            new_last_modified = last_modified
                            break
                        resp.raise_for_status()
                        # Use content instead of text to let feedparser handle encoding detection
                        xml_data = resp.content
                        xml_text = resp.text
                        new_etag = resp.headers.get('ETag')
                        new_last_modified = resp.headers.get('Last-Modified')
                        break
                    except Exception as e:
                        last_exc = e
                        status = "error"
                        error_msg = f"HTTP {getattr(e.response, 'status_code', 'Error')}: {str(e)}"
                        if attempt <= retries:
                            backoff = min(4, attempt)  # simple backoff
                            time.sleep(backoff)
                            continue
                        raise last_exc

            if status == "not_modified":
                return
            if xml_data is None:
                return

            d = feedparser.parse(xml_data)
            
            # Resilience: if 0 entries, try parsing decoded text as fallback
            # (Sometimes feedparser fails on bytes with certain encoding declarations vs actual content)
            if len(d.entries) == 0 and d.bozo:
                try:
                    d_text = feedparser.parse(xml_text)
                    if len(d_text.entries) > 0:
                        d = d_text
                        log.info(f"Fallback to text parsing successful for {feed_url}")
                except Exception:
                    pass
            
            # Build chapter map only when the feed payload hints chapter tags exist.
            # Most feeds have no embedded chapter pointers; skipping a second full XML parse saves CPU.
            chapter_map = {}
            xml_text_l = str(xml_text or "").lower()
            has_embedded_chapter_tags = any(
                marker in xml_text_l
                for marker in ("podcast:chapters", "psc:chapters", "<chapters")
            )
            if has_embedded_chapter_tags:
                try:
                    # Prefer XML parser if available (lxml), otherwise fall back to built-in HTML parser
                    try:
                        soup = BS(xml_text, "xml")
                    except Exception as parser_exc:
                        log.debug(f"XML parser unavailable for chapter map on {feed_url}; falling back to html.parser ({parser_exc})")
                        soup = BS(xml_text, "html.parser")

                    for item in soup.find_all("item"):
                        chap = item.find(["podcast:chapters", "psc:chapters", "chapters"])
                        if chap:
                            chap_url = chap.get("url") or chap.get("href") or chap.get("src") or chap.get("link")
                            if chap_url:
                                guid = item.find("guid")
                                link = item.find("link")
                                key = None
                                if guid and guid.text:
                                    key = guid.text.strip()
                                elif link and link.text:
                                    key = link.text.strip()
                                if key:
                                    chapter_map[key] = chap_url
                except Exception as e:
                    log.warning(f"Chapter map build failed for {feed_url}: {e}")

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
                c.execute("UPDATE feeds SET title = ?, etag = ?, last_modified = ? WHERE id = ?", 
                          (title_to_store, new_etag, new_last_modified, feed_id))
                
                # Pre-fetch existing articles to avoid N+1 SELECTs
                c.execute("SELECT id, date FROM articles WHERE feed_id = ?", (feed_id,))
                existing_articles = {row[0]: row[1] or "" for row in c.fetchall()}

                entry_ids = []
                for entry in d.entries:
                    base_id = entry.get('id') or entry.get('link')
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

                    content = ""
                    if 'content' in entry:
                        content = entry.content[0].value
                    elif 'summary_detail' in entry:
                        content = entry.summary_detail.value
                    elif 'summary' in entry:
                        content = entry.summary
                    elif 'description' in entry:
                        content = entry.description
                    
                    base_id = entry.get('id') or entry.get('link', '')
                    if not base_id:
                        continue
                    scoped_id = f"{feed_id}:{base_id}"
                    article_id = base_id

                    url = entry.get('link', '')
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

                    raw_date = entry.get('published') or entry.get('updated') or entry.get('pubDate') or entry.get('date')
                    if not raw_date:
                            parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                            if parsed:
                                raw_date = time.strftime("%Y-%m-%d %H:%M:%S", parsed)
                    
                    date = utils.normalize_date(
                        str(raw_date) if raw_date else "", 
                        title, 
                        content or (entry.get('summary') or ''),
                        url
                    )

                    existing_date = existing_articles.get(base_id)
                    if existing_date is not None:
                        if existing_date != date:
                                c.execute("UPDATE articles SET date = ? WHERE id = ?", (date, base_id))
                        continue

                    existing_date = existing_articles.get(scoped_id)
                    if existing_date is not None:
                        if existing_date != date:
                                c.execute("UPDATE articles SET date = ? WHERE id = ?", (date, scoped_id))
                        continue

                    if base_id in conflicting_ids:
                        article_id = scoped_id

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

                    # 4. Check NPR-specific extraction if still no media
                    if not media_url and npr_mod.is_npr_url(url):
                        media_url, media_type = npr_mod.extract_npr_audio(url, timeout_s=feed_timeout)

                    try:
                        c.execute(
                            "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                            (article_id, feed_id, title, url, content, date, author, media_url, media_type),
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
                        existing_articles[article_id] = date
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
                                existing_date = row[1] or ""
                                if existing_feed_id == feed_id:
                                    if existing_date != date:
                                        c.execute("UPDATE articles SET date = ? WHERE id = ?", (date, base_id))
                                    continue

                                try:
                                    c.execute(
                                        "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read, media_url, media_type) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                                        (scoped_id, feed_id, title, url, content, date, author, media_url, media_type),
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
                                    existing_articles[article_id] = date
                                except sqlite3.IntegrityError:
                                    continue
                            else:
                                raise
                        else:
                            continue

                    chapter_url = None
                    if 'podcast_chapters' in entry:
                        chapters_tag = entry.podcast_chapters
                        chapter_url = getattr(chapters_tag, 'href', None) or getattr(chapters_tag, 'url', None) or getattr(chapters_tag, 'value', None)
                    if not chapter_url and 'psc_chapters' in entry:
                        chapters_tag = entry.psc_chapters
                        chapter_url = getattr(chapters_tag, 'href', None) or getattr(chapters_tag, 'url', None) or getattr(chapters_tag, 'value', None)
                    
                    if not chapter_url:
                        key = entry.get('guid') or entry.get('id') or entry.get('link')
                        if key and key in chapter_map:
                            chapter_url = chapter_map[key]

                    if chapter_url:
                        utils.fetch_and_store_chapters(
                            article_id,
                            media_url,
                            media_type,
                            chapter_url,
                            allow_id3=False,
                            cursor=c,
                        )

                # Commit once at the end
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            error_msg = str(e)
            status = "error"
            log.error(f"Error processing feed {feed_url}: {e}")
        finally:
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
                sql_parts = ["""
                    SELECT a.id, a.feed_id, a.title, a.url, a.content, a.date, a.author, a.is_read, a.is_favorite, a.media_url, a.media_type
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                """]
                where_clauses.append("f.category = ?")
                params.append(cat_name)
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
            
            if is_category:
                cat_name = real_feed_id.split(":", 1)[1]
                count_sql_parts = ["SELECT COUNT(*) FROM articles a JOIN feeds f ON a.feed_id = f.id"]
                count_where.append("f.category = ?")
                count_params.append(cat_name)
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
                cat_name = real_feed_id.split(":", 1)[1]
                sql_parts = ["""
                    SELECT a.id, a.feed_id, a.title, a.url, a.content, a.date, a.author, a.is_read, a.is_favorite, a.media_url, a.media_type
                    FROM articles a
                    JOIN feeds f ON a.feed_id = f.id
                """]
                where_clauses.append("f.category = ?")
                params.append(cat_name)
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
                where_clauses.append("feed_id IN (SELECT id FROM feeds WHERE category = ?)")
                params.append(cat_name)
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
        from core.discovery import get_ytdlp_feed_url
        from core import rumble as rumble_mod
        from core import odysee as odysee_mod
        
        # Try to get native feed URL for media sites (e.g. YouTube)
        real_url = get_ytdlp_feed_url(url) or discover_feed(url) or url
        real_url = rumble_mod.normalize_rumble_feed_url(real_url)
        real_url = odysee_mod.normalize_odysee_feed_url(real_url)
        
        title = real_url
        try:
            if rumble_mod.is_rumble_url(real_url) and not real_url.lower().endswith((".xml", ".rss", ".atom")):
                page_title, _items = rumble_mod.fetch_listing_items(real_url, timeout_s=10.0)
                title = page_title or real_url
            elif odysee_mod.is_odysee_url(real_url) and not real_url.lower().endswith((".xml", ".rss", ".atom")):
                page_title, _items = odysee_mod.fetch_listing_items(real_url, max_items=1, timeout_s=10.0)
                title = page_title or real_url
            else:
                resp = utils.safe_requests_get(real_url, timeout=10)
                d = feedparser.parse(resp.text)
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

                        def ensure_category(title: str):
                            title = (title or "").strip()
                            if not title:
                                return
                            try:
                                c.execute(
                                    "INSERT OR IGNORE INTO categories (id, title) VALUES (?, ?)",
                                    (str(uuid.uuid4()), title),
                                )
                            except Exception:
                                pass

                        # Make sure target category exists if used.
                        if target_category and target_category != "Uncategorized":
                            ensure_category(target_category)

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
                            
                            xmlUrl = get_attr('xmlUrl')
                            
                            if xmlUrl:
                                write_log(f"Found feed: {text} -> {xmlUrl}")
                                # It's a feed
                                c.execute("SELECT id FROM feeds WHERE url = ?", (xmlUrl,))
                                if not c.fetchone():
                                    feed_id = str(uuid.uuid4())
                                    cat_to_use = target_category if target_category else current_category

                                    if cat_to_use and cat_to_use != "Uncategorized":
                                        ensure_category(cat_to_use)
                                    
                                    # Preserve OPML-provided labels as user-custom titles so refresh
                                    # does not overwrite curated names imported from other readers.
                                    title_is_custom = 1 if imported_title else 0
                                    c.execute(
                                        "INSERT INTO feeds (id, url, title, title_is_custom, category, icon_url) "
                                        "VALUES (?, ?, ?, ?, ?, ?)",
                                        (feed_id, xmlUrl, text, title_is_custom, cat_to_use, ""),
                                    )
                            
                            # Recursion for children
                            # In BS4, children include newlines/NavigableString, so filtering for Tags is important
                            children = outline.find_all('outline', recursive=False)
                            if children:
                                new_cat = current_category
                                if not target_category:
                                    # If it's a folder (no xmlUrl), use its text as category
                                    if not xmlUrl:
                                        new_cat = text
                                        if new_cat and new_cat != "Uncategorized":
                                            ensure_category(new_cat)

                                for child in children:
                                    process_outline(child, new_cat)

                        # Process top-level outlines in body
                        for outline in body.find_all('outline', recursive=False):
                            process_outline(outline)
                            
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
        
        root = ET.Element("opml", version="1.0")
        head = ET.SubElement(root, "head")
        ET.SubElement(head, "title").text = "RSS Exports"
        body = ET.SubElement(root, "body")
        
        # Group by category
        categories = {}
        for title, url, cat in feeds:
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((title, url))
            
        for cat, items in categories.items():
            if cat == "Uncategorized":
                for title, url in items:
                    ET.SubElement(body, "outline", text=title, xmlUrl=url)
            else:
                cat_outline = ET.SubElement(body, "outline", text=cat)
                for title, url in items:
                    ET.SubElement(cat_outline, "outline", text=title, xmlUrl=url)
                    
        tree = ET.ElementTree(root)
        tree.write(path, encoding='utf-8', xml_declaration=True)
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

    def add_category(self, title: str) -> bool:
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO categories (id, title) VALUES (?, ?)", (str(uuid.uuid4()), title))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False # Already exists
        finally:
            conn.close()

    def rename_category(self, old_title: str, new_title: str) -> bool:
        conn = get_connection()
        c = conn.cursor()
        try:
            # Update categories table
            c.execute("UPDATE categories SET title = ? WHERE title = ?", (new_title, old_title))
            # Update feeds
            c.execute("UPDATE feeds SET category = ? WHERE category = ?", (new_title, old_title))
            conn.commit()
            return True
        except Exception as e:
            log.error(f"Rename error: {e}")
            return False
        finally:
            conn.close()

    def delete_category(self, title: str) -> bool:
        if title.lower() == "uncategorized": return False
        conn = get_connection()
        try:
            c = conn.cursor()
            # Move feeds to Uncategorized? Or delete them? usually move.
            c.execute("UPDATE feeds SET category = 'Uncategorized' WHERE category = ?", (title,))
            c.execute("DELETE FROM categories WHERE title = ?", (title,))
            conn.commit()
            return True
        finally:
            conn.close()

    # Optional API used by GUI when present
    def get_article_chapters(self, article_id: str):
        return utils.get_chapters_from_db(article_id)
