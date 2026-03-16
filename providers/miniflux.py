import requests
import re
import logging
import time
import copy
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser
from .base import RSSProvider
from core.models import Feed, Article
from core import utils

log = logging.getLogger(__name__)

class MinifluxProvider(RSSProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._category_cache = {}
        self.conf = config.get("providers", {}).get("miniflux", {})
        url = self.conf.get("url", "").rstrip("/")
        self.base_url = re.sub(r'/v1/?$', '', url)
        self.headers = {
            "X-Auth-Token": self.conf.get("api_key", ""),
            "Accept": "application/json",
        }
        # Merge with default browser headers for better compatibility
        # Keep Miniflux API responses in JSON by overriding Accept above.
        self.headers.update(utils.HEADERS)
        # Ensure Accept stays JSON for API calls.
        self.headers["Accept"] = "application/json"
        self.headers = utils.add_revalidation_headers(self.headers)
        self._cached_get_responses: dict[str, Any] = {}
        self._last_request_info = {
            "ok": False,
            "used_cache": False,
            "status_code": None,
            "endpoint": "",
            "method": "",
            "error_body": None,
        }
        self._last_add_feed_result = {
            "ok": False,
            "duplicate": False,
            "feed_id": None,
            "feed_url": None,
        }
        # Backoff for repeatedly failing targeted per-feed refresh endpoints.
        # This avoids hammering a single broken feed refresh route and spamming logs.
        self._targeted_refresh_backoff_until: dict[str, float] = {}
        self._targeted_refresh_fail_counts: dict[str, int] = {}

    def _cacheable_get_endpoint(self, endpoint: str) -> str | None:
        ep = str(endpoint or "").split("?", 1)[0].strip()
        if ep in ("/v1/feeds", "/v1/feeds/counters", "/v1/categories"):
            return ep
        return None

    def _save_cached_get_response(self, endpoint: str, payload: Any) -> None:
        key = self._cacheable_get_endpoint(endpoint)
        if not key:
            return
        if not isinstance(payload, (dict, list)):
            return
        try:
            self._cached_get_responses[key] = copy.deepcopy(payload)
        except Exception:
            self._cached_get_responses[key] = payload

    def _load_cached_get_response(self, endpoint: str):
        key = self._cacheable_get_endpoint(endpoint)
        if not key:
            return None
        cached = self._cached_get_responses.get(key)
        if cached is None:
            return None
        try:
            return copy.deepcopy(cached)
        except Exception:
            return cached

    def _request_timeout_seconds(self, endpoint: str = "") -> int:
        """Return request timeout, with endpoint-specific floors for refresh endpoints."""
        try:
            base_timeout = int(self.config.get("feed_timeout_seconds", 15))
        except Exception:
            base_timeout = 15
        base_timeout = max(5, min(120, int(base_timeout)))
        ep = str(endpoint or "").strip().lower()
        if ep == "/v1/feeds/refresh":
            # Global refresh can be slower on busy instances.
            return max(base_timeout, 20)
        if ep.endswith("/refresh"):
            # Per-feed refresh should be quick; keep timeout tighter to avoid long UI stalls.
            return max(base_timeout, 10)
        return base_timeout

    def _request_retry_attempts(self, endpoint: str = "") -> int:
        try:
            retries = int(self.config.get("feed_retry_attempts", 1) or 0)
        except Exception:
            retries = 1
        retries = max(0, min(5, retries))
        ep = str(endpoint or "").strip().lower()
        if ep == "/v1/feeds/refresh":
            # Keep global refresh retries conservative to avoid long blocking loops when server is down.
            retries = min(retries, 2)
        elif ep.endswith("/refresh"):
            # Per-feed refresh retries can explode total refresh time; cap hard.
            retries = min(retries, 1)
        return retries

    def _is_transient_status(self, status_code: int | None) -> bool:
        return int(status_code or 0) in (429, 500, 502, 503, 504)

    def _retry_backoff_seconds(self, attempt_index: int) -> float:
        # attempt_index is 1-based
        return min(4.0, 0.4 * (2 ** max(0, int(attempt_index) - 1)))

    def _targeted_refresh_failure_backoff_seconds(self, failure_count: int) -> float:
        # Longer backoff at the per-feed refresh orchestration layer (separate from HTTP retry backoff)
        # to avoid repeated 5xx spam for the same problematic feed.
        try:
            n = max(1, int(failure_count))
        except Exception:
            n = 1
        return min(1800.0, 60.0 * (2 ** (n - 1)))  # 60s, 120s, 240s... cap 30m

    def _should_attempt_targeted_refresh(self, feed_id: str, *, force: bool = False) -> bool:
        if force:
            return True
        fid = str(feed_id or "").strip()
        if not fid:
            return False
        try:
            block_until = float(self._targeted_refresh_backoff_until.get(fid, 0.0) or 0.0)
        except Exception:
            block_until = 0.0
        now_mono = time.monotonic()
        if block_until > now_mono:
            return False
        if fid in self._targeted_refresh_backoff_until:
            try:
                self._targeted_refresh_backoff_until.pop(fid, None)
            except Exception:
                pass
        return True

    def _record_targeted_refresh_attempt_result(self, feed_id: str, ok: bool, status_code: int | None) -> None:
        fid = str(feed_id or "").strip()
        if not fid:
            return
        if bool(ok):
            try:
                self._targeted_refresh_backoff_until.pop(fid, None)
                self._targeted_refresh_fail_counts.pop(fid, None)
            except Exception:
                pass
            return

        # Back off on any failure status (especially repeated 5xx) to reduce log spam
        # and avoid hammering the same endpoint every refresh cycle.
        try:
            fail_count = int(self._targeted_refresh_fail_counts.get(fid, 0) or 0) + 1
        except Exception:
            fail_count = 1
        self._targeted_refresh_fail_counts[fid] = fail_count
        delay = self._targeted_refresh_failure_backoff_seconds(fail_count)
        try:
            self._targeted_refresh_backoff_until[fid] = time.monotonic() + float(delay)
        except Exception:
            pass
        try:
            if int(status_code or 0) >= 500 or int(status_code or 0) in (429, 502, 503, 504):
                log.warning(
                    "Miniflux targeted refresh backoff for feed %s after HTTP %s (%.0fs).",
                    fid,
                    int(status_code or 0),
                    delay,
                )
            else:
                log.debug(
                    "Miniflux targeted refresh backoff for feed %s after failure status=%s (%.0fs).",
                    fid,
                    status_code,
                    delay,
                )
        except Exception:
            pass

    def get_name(self) -> str:
        return "Miniflux"

    def test_connection(self) -> bool:
        try:
            res = self._req("GET", "/v1/me")
            return res is not None
        except:
            return False

    def _req(self, method, endpoint, json=None, params=None):
        if not self.base_url:
            self._last_request_info = {
                "ok": False,
                "used_cache": False,
                "status_code": None,
                "endpoint": str(endpoint or ""),
                "method": str(method or "").upper(),
                "error_body": None,
            }
            return None
        url = f"{self.base_url}{endpoint}"
        timeout_s = self._request_timeout_seconds(endpoint)
        retries = self._request_retry_attempts(endpoint)
        req_headers = utils.add_revalidation_headers(self.headers)
        method_upper = str(method or "").upper()
        is_get = method_upper == "GET"
        last_error = None
        last_status_code = None

        for attempt in range(1, retries + 2):
            try:
                # Uses self.headers which includes a browser-like User-Agent
                resp = requests.request(
                    method_upper,
                    url,
                    headers=req_headers,
                    json=json,
                    params=params,
                    timeout=timeout_s,
                )

                status_code = int(getattr(resp, "status_code", 0) or 0)
                last_status_code = status_code
                if self._is_transient_status(status_code) and attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.warning(
                        "Miniflux transient HTTP %s for %s %s (attempt %s/%s); retrying in %.1fs",
                        status_code,
                        method_upper,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                resp.raise_for_status()

                if status_code == 204:
                    return None

                try:
                    payload = resp.json()
                except ValueError:
                    log.error(f"Miniflux JSON error for {url}. Status: {status_code}")
                    self._last_request_info = {
                        "ok": False,
                        "used_cache": False,
                        "status_code": status_code,
                        "endpoint": str(endpoint or ""),
                        "method": method_upper,
                        "error_body": None,
                    }
                    return None

                if is_get:
                    self._save_cached_get_response(endpoint, payload)
                self._last_request_info = {
                    "ok": True,
                    "used_cache": False,
                    "status_code": status_code,
                    "endpoint": str(endpoint or ""),
                    "method": method_upper,
                    "error_body": None,
                }
                return payload

            except requests.HTTPError as e:
                last_error = e
                status_code = None
                body_preview = ""
                try:
                    status_code = int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
                except Exception:
                    status_code = 0
                last_status_code = status_code

                if self._is_transient_status(status_code) and attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.warning(
                        "Miniflux transient HTTP %s for %s %s (attempt %s/%s); retrying in %.1fs",
                        status_code,
                        method_upper,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                if self._is_transient_status(status_code):
                    log.warning("Miniflux transient HTTP %s for %s %s: %s", status_code, method_upper, url, e)
                else:
                    body_preview = ""
                    try:
                        resp_obj = getattr(e, "response", None)
                        if resp_obj is not None:
                            text = (getattr(resp_obj, "text", "") or "").strip()
                            if text:
                                text = " ".join(text.split())
                                if len(text) > 500:
                                    text = text[:497].rstrip() + "..."
                                body_preview = text
                    except Exception:
                        body_preview = ""
                    if body_preview:
                        log.error("Miniflux error for %s: %s | response=%s", url, e, body_preview)
                    else:
                        log.error(f"Miniflux error for {url}: {e}")
                self._last_request_info = {
                    "ok": False,
                    "used_cache": False,
                    "status_code": status_code,
                    "endpoint": str(endpoint or ""),
                    "method": method_upper,
                    "error_body": body_preview or None,
                }
                break
            except requests.Timeout as e:
                last_error = e
                last_status_code = None
                if attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.warning(
                        "Miniflux timeout for %s %s (timeout=%ss, attempt %s/%s); retrying in %.1fs",
                        method_upper,
                        url,
                        timeout_s,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                log.warning(f"Miniflux timeout for {url} (timeout={timeout_s}s): {e}")
                self._last_request_info = {
                    "ok": False,
                    "used_cache": False,
                    "status_code": last_status_code,
                    "endpoint": str(endpoint or ""),
                    "method": method_upper,
                    "error_body": None,
                }
                break
            except requests.RequestException as e:
                last_error = e
                last_status_code = None
                if attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.warning(
                        "Miniflux request error for %s %s (attempt %s/%s); retrying in %.1fs: %s",
                        method_upper,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                        e,
                    )
                    time.sleep(delay)
                    continue
                log.error(f"Miniflux error for {url}: {e}")
                self._last_request_info = {
                    "ok": False,
                    "used_cache": False,
                    "status_code": last_status_code,
                    "endpoint": str(endpoint or ""),
                    "method": method_upper,
                    "error_body": None,
                }
                break
            except Exception as e:
                last_error = e
                last_status_code = None
                log.error(f"Miniflux error for {url}: {e}")
                self._last_request_info = {
                    "ok": False,
                    "used_cache": False,
                    "status_code": last_status_code,
                    "endpoint": str(endpoint or ""),
                    "method": method_upper,
                    "error_body": None,
                }
                break

        if is_get:
            cached = self._load_cached_get_response(endpoint)
            if cached is not None:
                log.warning("Miniflux using cached response for %s after request failure.", endpoint)
                self._last_request_info = {
                    "ok": False,
                    "used_cache": True,
                    "status_code": last_status_code,
                    "endpoint": str(endpoint or ""),
                    "method": method_upper,
                    "error_body": None,
                }
                return cached

        self._last_request_info = {
            "ok": False,
            "used_cache": False,
            "status_code": last_status_code,
            "endpoint": str(endpoint or ""),
            "method": method_upper,
            "error_body": None if method_upper == "GET" else self._last_request_info.get("error_body"),
        }
        if last_error is not None:
            log.debug("Miniflux request failed with no fallback for %s %s", method_upper, url, exc_info=True)
        return None

    def _get_entries_paged(self, endpoint: str, params: Dict[str, Any] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Retrieve all entries by paging with limit/offset until total is reached.

        To guarantee BlindRSS can see absolutely every stored entry for a feed, we page through:
          /v1/feeds/{feedID}/entries?limit=...&offset=...
        and keep requesting until we've retrieved "total" entries.
        """
        out: List[Dict[str, Any]] = []
        offset = 0
        last_offset = -1

        base_params = dict(params or {})
        base_params.pop("offset", None)
        base_params.pop("limit", None)

        while True:
            p = dict(base_params)
            p["limit"] = int(limit)
            p["offset"] = int(offset)

            data = self._req("GET", endpoint, params=p)
            if not data:
                break

            entries = data.get("entries") or []
            total = data.get("total")

            if entries:
                out.extend(entries)

            if not entries:
                break

            if total is not None:
                try:
                    if len(out) >= int(total):
                        break
                except Exception:
                    # If total is malformed, fall back to short-page termination
                    if len(entries) < int(limit):
                        break
            else:
                # Some proxies may strip "total"; short-page implies exhaustion.
                if len(entries) < int(limit):
                    break

            last_offset = offset
            offset += len(entries)
            if offset <= last_offset:
                # Defensive: avoid infinite loops if the server repeats a page
                break

        return out


    def _get_category_id_by_title(self, title: str):
        norm_title = (title or "").strip()
        if not norm_title:
            return None
        cached = self._category_cache.get(norm_title)
        if cached is not None:
            return cached
        cats = self._req("GET", "/v1/categories") or []
        cid = None
        for c in cats:
            if (c.get("title") or "").strip() == norm_title:
                cid = c.get("id")
                break
        if cid is None:
            norm_lower = norm_title.lower()
            for c in cats:
                if (c.get("title") or "").strip().lower() == norm_lower:
                    cid = c.get("id")
                    break
        if cid is not None:
            self._category_cache[norm_title] = cid
        return cid

    def _resolve_entries_endpoint(self, feed_id: str, base_params: Dict[str, Any]):
        # category:<title> uses /v1/entries with category_id filter
        if feed_id.startswith("category:"):
            cat_title = feed_id.split(":", 1)[1]
            cid = self._get_category_id_by_title(cat_title)
            if cid is None:
                return None, None
            base_params["category_id"] = cid
            return "/v1/entries", base_params
        if feed_id == "all":
            return "/v1/entries", base_params
        return f"/v1/feeds/{feed_id}/entries", base_params

    def _strip_view_prefixes(self, feed_id: str) -> str:
        real_feed_id = feed_id or ""
        while True:
            if real_feed_id.startswith("favorites:"):
                real_feed_id = real_feed_id[10:]
            elif real_feed_id.startswith("fav:"):
                real_feed_id = real_feed_id[4:]
            elif real_feed_id.startswith("starred:"):
                real_feed_id = real_feed_id[8:]
            elif real_feed_id.startswith("unread:"):
                real_feed_id = real_feed_id[7:]
            elif real_feed_id.startswith("read:"):
                real_feed_id = real_feed_id[5:]
            else:
                break
        return real_feed_id

    def _entries_to_articles(self, entries: List[Dict[str, Any]], fallback_feed_id: str | None = None) -> List[Article]:
        if not entries:
            return []
        article_ids = [str(e.get("id")) for e in entries if e.get("id") is not None]
        chapters_map = utils.get_chapters_batch(article_ids)

        articles: List[Article] = []
        for entry in entries:
            if self._is_placeholder_entry(entry):
                continue
            media_url = None
            media_type = None
            entry_url = entry.get("url") or ""
            entry_content = entry.get("content") or entry.get("summary") or ""
            display_title = utils.enhance_activity_entry_title(entry.get("title") or "", entry_url, entry_content) or "Untitled"

            enclosures = entry.get("enclosures", []) or []
            if enclosures:
                media_url = (enclosures[0] or {}).get("url")
                media_type = (enclosures[0] or {}).get("mime_type")

            date = utils.normalize_date(
                entry.get("published_at") or entry.get("published"),
                display_title,
                entry_content,
                entry_url,
            )

            article_id = str(entry.get("id"))
            feed_id = str(entry.get("feed_id") or fallback_feed_id or "")
            cache_id = utils.build_cache_id(article_id, feed_id, self.get_name())
            chapters = chapters_map.get(article_id, [])

            articles.append(Article(
                id=article_id,
                feed_id=feed_id,
                title=display_title,
                url=entry_url,
                content=entry_content,
                date=date,
                author=entry.get("author") or "",
                is_read=(entry.get("status") == "read"),
                is_favorite=entry.get("starred", False),
                media_url=media_url,
                media_type=media_type,
                chapters=chapters,
                cache_id=cache_id,
            ))
        return articles

    def _is_placeholder_entry(self, entry: Dict[str, Any]) -> bool:
        title = (entry.get("title") or "").strip().lower()
        content = (entry.get("content") or entry.get("summary") or "").strip().lower()
        if "unable to retrieve full-text content" in title:
            return True
        if "unable to retrieve full-text content" in content:
            return True
        return False

    def _parse_checked_at(self, value: str | None):
        if not value:
            return None
        try:
            dt = dateparser.parse(value)
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def refresh(self, progress_cb=None, force: bool = False) -> bool:
        # Kick off a global refresh on the Miniflux server.
        self._req("PUT", "/v1/feeds/refresh")
        refresh_info = dict(getattr(self, "_last_request_info", {}) or {})
        global_refresh_ok = True
        if (
            str(refresh_info.get("endpoint", "")) == "/v1/feeds/refresh"
            and str(refresh_info.get("method", "")).upper() == "PUT"
        ):
            global_refresh_ok = bool(refresh_info.get("ok", False))

        # After triggering, fetch feed metadata so we can surface stale/error
        # feeds in the UI and optionally retry them individually.
        feeds = self._req("GET", "/v1/feeds") or []
        feeds_info = dict(getattr(self, "_last_request_info", {}) or {})
        feeds_from_cache = False
        if (
            str(feeds_info.get("endpoint", "")) == "/v1/feeds"
            and str(feeds_info.get("method", "")).upper() == "GET"
        ):
            feeds_from_cache = bool(feeds_info.get("used_cache", False))
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(hours=3)
        retry_budget = len(feeds) if force else 15
        per_feed_retry_ids = []

        for feed in feeds:
            feed_id = str(feed.get("id"))
            status = "ok"

            checked_dt = self._parse_checked_at(feed.get("checked_at"))

            if (feed.get("parsing_error_count") or 0) > 0:
                status = "error"
            elif checked_dt and checked_dt < stale_cutoff:
                status = "stale"

            # Manual refresh in BlindRSS sets force=True. Respect it by explicitly
            # refreshing every feed so CDN-cached feeds (e.g., Simplecast) update
            # immediately instead of waiting for Miniflux's next scheduled check.
            if force:
                per_feed_retry_ids.append(feed_id)
            elif status in ("error", "stale"):
                per_feed_retry_ids.append(feed_id)

        allow_targeted_refresh = bool(global_refresh_ok and (not feeds_from_cache))
        if not allow_targeted_refresh and per_feed_retry_ids:
            log.warning(
                "Skipping Miniflux per-feed refresh retries due to upstream instability "
                "(global refresh failed or feed list came from cache)."
            )

        if retry_budget > 0 and allow_targeted_refresh:
            attempted = 0
            for feed_id in per_feed_retry_ids:
                if attempted >= retry_budget:
                    break
                if not self._should_attempt_targeted_refresh(feed_id, force=force):
                    continue
                self._req("PUT", f"/v1/feeds/{feed_id}/refresh")
                attempted += 1
                info = dict(getattr(self, "_last_request_info", {}) or {})
                if (
                    str(info.get("endpoint", "")) == f"/v1/feeds/{feed_id}/refresh"
                    and str(info.get("method", "")).upper() == "PUT"
                ):
                    self._record_targeted_refresh_attempt_result(
                        feed_id,
                        bool(info.get("ok", False)),
                        info.get("status_code"),
                    )

        # Re-read feed/counter metadata after targeted refresh requests.
        feeds = self._req("GET", "/v1/feeds") or feeds
        counters_data = self._req("GET", "/v1/feeds/counters") or {}
        unread_map = counters_data.get("unreads", {}) if isinstance(counters_data, dict) else {}

        for feed in feeds:
            feed_id = str(feed.get("id"))
            category = (feed.get("category") or {}).get("title", "Uncategorized")
            unread = unread_map.get(feed_id) or unread_map.get(int(feed.get("id", 0) or 0), 0) or 0

            status = "ok"
            error_msg = None
            checked_dt = self._parse_checked_at(feed.get("checked_at"))
            if (feed.get("parsing_error_count") or 0) > 0:
                status = "error"
                error_msg = feed.get("parsing_error_message")
            elif checked_dt and checked_dt < stale_cutoff:
                status = "stale"

            self._emit_progress(
                progress_cb,
                {
                    "id": feed_id,
                    "title": feed.get("title") or "",
                    "category": category,
                    "unread_count": unread,
                    "status": status,
                    "new_items": None,
                    "error": error_msg,
                },
            )

        return True

    def refresh_feed(self, feed_id: str, progress_cb=None) -> bool:
        """Refresh a single Miniflux feed and emit one progress state for the UI."""
        fid = str(feed_id or "").strip()
        if not fid:
            return False

        # Trigger a targeted refresh on the Miniflux server.
        self._req("PUT", f"/v1/feeds/{fid}/refresh")
        info = dict(getattr(self, "_last_request_info", {}) or {})
        if (
            str(info.get("endpoint", "")) == f"/v1/feeds/{fid}/refresh"
            and str(info.get("method", "")).upper() == "PUT"
        ):
            self._record_targeted_refresh_attempt_result(
                fid,
                bool(info.get("ok", False)),
                info.get("status_code"),
            )

        # Whether the refresh call succeeded or timed out, try to fetch the latest metadata
        # so the UI can stop showing "Adding feed..." and display current state.
        feeds = self._req("GET", "/v1/feeds") or []
        counters_data = self._req("GET", "/v1/feeds/counters") or {}
        unread_map = counters_data.get("unreads", {}) if isinstance(counters_data, dict) else {}

        target = None
        for feed in (feeds or []):
            if str(feed.get("id") or "") == fid:
                target = feed
                break

        if target is None:
            return False

        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(hours=3)
        checked_dt = self._parse_checked_at(target.get("checked_at"))

        status = "ok"
        error_msg = None
        if (target.get("parsing_error_count") or 0) > 0:
            status = "error"
            error_msg = target.get("parsing_error_message")
        elif checked_dt and checked_dt < stale_cutoff:
            status = "stale"

        unread = unread_map.get(fid) or unread_map.get(int(target.get("id", 0) or 0), 0) or 0
        category = (target.get("category") or {}).get("title", "Uncategorized")

        self._emit_progress(
            progress_cb,
            {
                "id": fid,
                "title": target.get("title") or "",
                "category": category,
                "unread_count": unread,
                "status": status,
                "new_items": None,
                "error": error_msg,
            },
        )
        return True

    def get_feeds(self) -> List[Feed]:
        data = self._req("GET", "/v1/feeds")
        if not data: return []
        
        counters_data = self._req("GET", "/v1/feeds/counters")
        counts = {}
        if counters_data:
            counts = counters_data.get("unreads", {})
        
        feeds = []
        for f in data:
            cat = f.get("category", {}).get("title", "Uncategorized")
            feed = Feed(
                id=str(f["id"]),
                title=f["title"],
                url=f["site_url"],
                category=cat,
                icon_url=f.get("icon", {}).get("data", "")
            )
            feed.unread_count = counts.get(str(f["id"]), 0) or counts.get(int(f["id"]), 0)
            feeds.append(feed)

        return feeds

    def get_articles(self, feed_id: str) -> List[Article]:
        # Always page through results so we can retrieve *all* stored entries.
        # - For a single feed: /v1/feeds/{feedID}/entries
        # - For categories/all: /v1/entries
        # Request both unread and read entries so the client can page through
        # the entire stored history (not just the default unread view).
        base_params: Dict[str, Any] = {
            "direction": "desc",
            "order": "published_at",
            "status": ["unread", "read"],
        }
        
        real_feed_id = feed_id
        if feed_id.startswith("unread:"):
            base_params["status"] = ["unread"]
            real_feed_id = feed_id[7:]
        elif feed_id.startswith("read:"):
            base_params["status"] = ["read"]
            real_feed_id = feed_id[5:]
        elif feed_id.startswith("favorites:") or feed_id.startswith("starred:"):
            base_params["starred"] = "true"
            # Miniflux doesn't support "favorites:category:X", just global favorites or feed favorites if we combine?
            # /v1/entries?starred=true -> All favorites.
            # If we want favorites for a feed, /v1/feeds/{id}/entries?starred=true
            # The UI usually sends "favorites:all" or just "favorites".
            # If the user clicks "Favorites" in the tree, it might pass "favorites".
            # Mainframe usually passes "favorites" or "favorites:all" if it's a special node.
            # Let's handle "favorites" and "starred" as "all starred".
            real_feed_id = "all" 
            if ":" in feed_id:
                # Handle "favorites:<feed_id>" if we ever support per-feed favorites view?
                # For now let's assume global favorites view.
                suffix = feed_id.split(":", 1)[1]
                if suffix != "all":
                    # Maybe it's favorites for a specific feed/category?
                    # Miniflux supports starred=true on feed entries endpoint.
                    real_feed_id = suffix
                else:
                    real_feed_id = "all"

        entries: List[Dict[str, Any]] = []

        if real_feed_id.startswith("category:"):
            cat_title = real_feed_id.split(":", 1)[1]
            category_id = self._get_category_id_by_title(cat_title)
            if category_id is None:
                return []
            base_params["category_id"] = category_id
            entries = self._get_entries_paged("/v1/entries", base_params, limit=200)
        elif real_feed_id == "all":
            entries = self._get_entries_paged("/v1/entries", base_params, limit=200)
        else:
            # This is the guarantee path for complete retrieval.
            entries = self._get_entries_paged(f"/v1/feeds/{real_feed_id}/entries", base_params, limit=200)

        fallback_feed_id = self._strip_view_prefixes(feed_id)
        return self._entries_to_articles(entries, fallback_feed_id=fallback_feed_id)

    def get_article_chapters(self, article_id: str) -> List[Dict]:
        """
        Called by UI when an article is opened/played.
        We need to find the article's media info first. 
        Since we don't store articles in DB, we must fetch entry from API or rely on caller?
        MainFrame calls this with just ID.
        So we fetch the entry from Miniflux to get the media_url.
        """
        # Check DB first just in case
        chapters = utils.get_chapters_from_db(article_id)
        if chapters:
            return chapters

        # Fetch entry info to get media URL
        entry = self._req("GET", f"/v1/entries/{article_id}")
        if not entry:
            return []
            
        media_url = None
        media_type = None
        enclosures = entry.get("enclosures", [])
        if enclosures:
            media_url = enclosures[0].get("url")
            media_type = enclosures[0].get("mime_type")
            
        if media_url:
             return utils.fetch_and_store_chapters(article_id, media_url, media_type)
        return []


    def get_articles_page(self, feed_id: str, offset: int = 0, limit: int = 200):
        """Fetch a single page of articles quickly (used by the UI for fast-first loading)."""
        base_params: Dict[str, Any] = {
            "direction": "desc",
            "order": "published_at",
            # request both unread + read so we can page through the complete stored history
            "status": ["unread", "read"],
            "offset": int(max(0, offset)),
            "limit": int(limit),
        }

        real_feed_id = feed_id
        if feed_id.startswith("unread:"):
            base_params["status"] = ["unread"]
            real_feed_id = feed_id[7:]
        elif feed_id.startswith("read:"):
            base_params["status"] = ["read"]
            real_feed_id = feed_id[5:]
        elif feed_id.startswith("favorites:") or feed_id.startswith("starred:"):
            base_params["starred"] = "true"
            real_feed_id = "all"
            if ":" in feed_id:
                suffix = feed_id.split(":", 1)[1]
                if suffix and suffix != "all":
                    real_feed_id = suffix

        endpoint, params = self._resolve_entries_endpoint(real_feed_id, base_params)
        if not endpoint:
            return [], 0
        data = self._req("GET", endpoint, params=params) or {}
        entries = data.get("entries") or []
        total = data.get("total")
        try:
            total_int = int(total) if total is not None else None
        except Exception:
            total_int = None

        fallback_feed_id = self._strip_view_prefixes(feed_id)
        return self._entries_to_articles(entries, fallback_feed_id=fallback_feed_id), total_int

    def mark_read(self, article_id: str) -> bool:
        return self._set_entries_status([article_id], "read")

    def mark_unread(self, article_id: str) -> bool:
        return self._set_entries_status([article_id], "unread")

    def mark_read_batch(self, article_ids: List[str]) -> bool:
        return self._set_entries_status(article_ids, "read")

    def mark_all_read(self, feed_id: str) -> bool:
        if not self.base_url:
            return False

        # Avoid broad server-side marks for favorites/starred views.
        if (feed_id or "").startswith(("favorites:", "fav:", "starred:")):
            return False

        real_feed_id = self._strip_view_prefixes(feed_id)
        try:
            if real_feed_id.startswith("category:"):
                cat_title = real_feed_id.split(":", 1)[1]
                cid = self._get_category_id_by_title(cat_title)
                if cid is None:
                    return False
                resp = requests.put(
                    f"{self.base_url}/v1/categories/{cid}/mark-all-as-read",
                    headers=self.headers,
                    timeout=15,
                )
                return resp.status_code in (200, 204)

            if real_feed_id == "all":
                return False

            resp = requests.put(
                f"{self.base_url}/v1/feeds/{real_feed_id}/mark-all-as-read",
                headers=self.headers,
                timeout=15,
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            log.error(f"Miniflux mark-all-as-read failed for {feed_id}: {e}")
            return False

    def _set_entries_status(self, entry_ids: List[str], status: str) -> bool:
        if not entry_ids:
            return True
        if not self.base_url:
            return False

        status = (status or "").strip().lower()
        if status not in ("read", "unread"):
            return False

        # Miniflux supports batching via PUT /v1/entries.
        chunk_size = 200
        ok = True
        unique_ids = []
        seen = set()
        for eid in entry_ids:
            if eid is None:
                continue
            try:
                eid = int(str(eid))
            except Exception:
                eid = str(eid)
            if eid in seen:
                continue
            seen.add(eid)
            unique_ids.append(eid)

        for i in range(0, len(unique_ids), chunk_size):
            chunk = unique_ids[i:i + chunk_size]
            try:
                resp = requests.put(
                    f"{self.base_url}/v1/entries",
                    headers=self.headers,
                    json={"entry_ids": chunk, "status": status},
                    timeout=15,
                )
                if resp.status_code not in (200, 204):
                    ok = False
            except Exception as e:
                log.error(f"Miniflux batch status update failed: {e}")
                ok = False
        return ok

    def supports_favorites(self) -> bool:
        return True

    def toggle_favorite(self, article_id: str):
        # Miniflux: PUT /v1/entries/{id}/bookmark
        res = self._req("PUT", f"/v1/entries/{article_id}/bookmark")
        # Returns None on success (204) usually? Or updated entry?
        # Actually Miniflux toggle endpoint "bookmark" toggles it.
        # But wait, does it toggle or just set?
        # API docs: "Toggle "bookmark" status for an entry." -> PUT /v1/entries/{entryID}/bookmark
        if res is None: # 204 or success
             # We need to know the new state to return it.
             # Fetch entry to check?
             entry = self._req("GET", f"/v1/entries/{article_id}")
             if entry:
                 return entry.get("starred", False)
        return True # Assume toggled if we can't check? Or maybe we should use set_favorite if we want explicit control.

    def set_favorite(self, article_id: str, is_favorite: bool) -> bool:
        # Miniflux doesn't have explicit set-favorite, only toggle.
        # So we must check state first.
        entry = self._req("GET", f"/v1/entries/{article_id}")
        if not entry:
            return False
        current = entry.get("starred", False)
        if current != is_favorite:
            self._req("PUT", f"/v1/entries/{article_id}/bookmark")
        return True

    def add_feed(self, url: str, category: str = "Uncategorized") -> bool:
        from core.discovery import get_ytdlp_feed_url, discover_feed
        from core import odysee as odysee_mod
        from core import rumble as rumble_mod
        self._last_add_feed_result = {
            "ok": False,
            "duplicate": False,
            "feed_id": None,
            "feed_url": None,
        }
        
        # Try to get native feed URL for media sites (e.g. YouTube)
        # Miniflux can sometimes fail to discover these natively, leading to 500 errors.
        real_url = get_ytdlp_feed_url(url) or discover_feed(url) or url
        
        # Explicitly normalize Odysee/Rumble URLs to their RSS/Listing formats
        # Odysee: converts channel URL to RSS XML (Miniflux can parse XML).
        # Rumble: standardizes URL path (Miniflux might still fail if blocked, but this is best effort).
        real_url = odysee_mod.normalize_odysee_feed_url(real_url)
        real_url = rumble_mod.normalize_rumble_feed_url(real_url)
        
        cats = self._req("GET", "/v1/categories")
        if not cats:
            return False
            
        category_id = cats[0]["id"]
        if category:
            for c in cats:
                if c["title"].lower() == category.lower():
                    category_id = c["id"]
                    break
        
        data = {"feed_url": real_url, "category_id": category_id}
        res = self._req("POST", "/v1/feeds", json=data)
        post_info = dict(getattr(self, "_last_request_info", {}) or {})
        if isinstance(res, dict):
            self._last_add_feed_result = {
                "ok": True,
                "duplicate": False,
                "feed_id": str(res.get("feed_id") or res.get("id") or "") or None,
                "feed_url": real_url,
            }
            return True

        # Miniflux returns HTTP 400 when the feed already exists. Treat that as success
        # so BlindRSS doesn't show a misleading add failure for existing subscriptions.
        if (
            str(post_info.get("endpoint", "")) == "/v1/feeds"
            and str(post_info.get("method", "")).upper() == "POST"
            and int(post_info.get("status_code", 0) or 0) == 400
        ):
            error_body = str(post_info.get("error_body") or "")
            looks_duplicate = "already exists" in error_body.lower()
            existing_feed_id = None
            feeds = self._req("GET", "/v1/feeds") or []
            for f in (feeds or []):
                f_feed_url = str(f.get("feed_url") or "").strip()
                f_site_url = str(f.get("site_url") or "").strip()
                if real_url and real_url in (f_feed_url, f_site_url):
                    existing_feed_id = str(f.get("id") or "").strip() or None
                    looks_duplicate = True
                    break
            if looks_duplicate:
                self._last_add_feed_result = {
                    "ok": True,
                    "duplicate": True,
                    "feed_id": existing_feed_id,
                    "feed_url": real_url,
                }
                log.info("Miniflux feed already exists; treating add as success: %s", real_url)
                return True
        
        # If Miniflux fails (likely on Rumble), warn the user but don't crash.
        if res is None and rumble_mod.is_rumble_url(real_url):
            log.warning(f"Miniflux failed to add Rumble feed: {real_url}. Miniflux server may be blocked by Rumble.")
        
        return False

    def remove_feed(self, feed_id: str) -> bool:
        self._req("DELETE", f"/v1/feeds/{feed_id}")
        return True

    def supports_feed_edit(self) -> bool:
        return True

    def supports_feed_url_update(self) -> bool:
        return True

    def update_feed(self, feed_id: str, title: str = None, url: str = None, category: str = None) -> bool:
        payload = {}
        if title is not None:
            payload["title"] = title
        if url is not None:
            payload["feed_url"] = url
        if category is not None:
            cats = self._req("GET", "/v1/categories") or []
            cat_id = None
            for c in cats:
                if str(c.get("title", "")).lower() == str(category).lower():
                    cat_id = c.get("id")
                    break
            if cat_id is None and category:
                created = self._req("POST", "/v1/categories", json={"title": category})
                if isinstance(created, dict):
                    cat_id = created.get("id")
            if cat_id is not None:
                payload["category_id"] = cat_id
        if not payload:
            return True
        res = self._req("PUT", f"/v1/feeds/{feed_id}", json=payload)
        return res is not None
        
    def import_opml(self, path: str, target_category: str = None) -> bool:
        # Miniflux API has an endpoint for this, but file upload might be tricky with requests.
        # Alternatively, use the default implementation which iterates and adds feeds.
        # Let's use default implementation for now as it's safer than file upload debugging.
        # So we actually REMOVE this method too? No, Miniflux *might* be faster with native import if we implemented it,
        # but the base class one works. 
        # Actually, let's keep the user's Miniflux file logic if it was there? 
        # Wait, the current file didn't have import_opml stubbed, did it? 
        # Checking... codebase_investigator said "Miniflux implements nearly all features... missing export_opml".
        # So import_opml IS likely implemented or not present (defaulting).
        # Let's check the file content if possible, or just remove export_opml.
        
        # NOTE: I am ONLY removing export_opml.
        return super().import_opml(path, target_category)

    def get_categories(self) -> List[str]:
        data = self._req("GET", "/v1/categories")
        if not data: return []
        return [c["title"] for c in data]

    def add_category(self, title: str, parent_title: str = None) -> bool:
        result = self._req("POST", "/v1/categories", json={"title": title}) is not None
        if result and parent_title:
            from core.db import sync_categories, set_category_parent
            sync_categories([title])
            set_category_parent(title, parent_title)
        return result

    def rename_category(self, old_title: str, new_title: str) -> bool:
        data = self._req("GET", "/v1/categories")
        if not data: return False
        
        cat_id = None
        for c in data:
            if c["title"] == old_title:
                cat_id = c["id"]
                break
                
        if cat_id:
             return self._req("PUT", f"/v1/categories/{cat_id}", json={"title": new_title}) is not None
        return False

    def delete_category(self, title: str) -> bool:
        data = self._req("GET", "/v1/categories")
        if not data: return False

        cat_id = None
        for c in data:
            if c["title"] == title:
                cat_id = c["id"]
                break

        if cat_id:
            self._req("DELETE", f"/v1/categories/{cat_id}")
            return True
        return False

    def fetch_full_content(self, article_id: str, url: str = ""):
        """Return raw HTML fetched by Miniflux server-side fetch-content.

        Behavior:
        - Uses PUT /v1/entries/{id}/fetch-content (Miniflux requirement).
        - Swallows 404 (entry not found/expired) quietly to avoid noisy logs.
        - Returns the updated entry's content on success, otherwise None.
        """
        if not article_id:
            return None

        try:
            # Some instances require numeric IDs; coerce when possible.
            aid = int(str(article_id))
        except Exception:
            aid = article_id

        try:
            # Direct request so we can selectively silence 404s.
            resp = requests.put(
                f"{self.base_url}/v1/entries/{aid}/fetch-content",
                headers=self.headers,
                timeout=15,
            )

            if resp.status_code == 404:
                # Entry no longer exists on the server; just fall back.
                return None

            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                content = data.get("content")
                if content:
                    return content
        except requests.HTTPError as e:
            # Only surface non-404 errors.
            code = getattr(e.response, "status_code", None)
            if code and code != 404:
                log.error(f"Miniflux fetch-content HTTP error for {article_id}: {e}")
        except Exception as e:
            log.error(f"Miniflux fetch-content error for {article_id}: {e}")
        return None

    def _emit_progress(self, progress_cb, state):
        if progress_cb is None:
            return
        try:
            progress_cb(state)
        except Exception as e:
            log.error(f"Miniflux progress callback failed: {e}")
