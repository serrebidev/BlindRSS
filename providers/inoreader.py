import requests
import logging
import time
import threading
import urllib.parse
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any
from .base import RSSProvider
from core.models import Feed, Article
from core import utils
from core import inoreader_oauth

log = logging.getLogger(__name__)

class RateLimitError(RuntimeError):
    def __init__(self, retry_after: int | None, message: str):
        super().__init__(message)
        self.retry_after = retry_after

class InoreaderProvider(RSSProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.config = config
        self.conf = config.get("providers", {}).get("inoreader", {})
        self.base_url = "https://www.inoreader.com/reader/api/0"
        self.token = (self.conf.get("token") or "").strip()
        self.app_id = (self.conf.get("app_id") or "").strip()
        self.app_key = (self.conf.get("app_key") or "").strip()
        self.refresh_token = (self.conf.get("refresh_token") or "").strip()
        self.token_expires_at = self._parse_timestamp(self.conf.get("token_expires_at"))
        self._rate_limit_lock = threading.Lock()
        self._rate_limit_until = 0.0
        self._cache_lock = threading.Lock()
        self._feeds_cache = None
        self._categories_cache = None
        self._feeds_cache_time = 0.0
        self._categories_cache_time = 0.0
        self._cache_ttl_s = self._metadata_cache_ttl_s()
        self._force_next_fetch = False
        self._article_cache_lock = threading.Lock()
        self._article_view_cache: Dict[str, Dict[str, Any]] = {}
        self._article_cache_ttl_s = self._articles_cache_ttl_s()
        self._article_page_n = self._articles_page_n()

    def get_name(self) -> str:
        return "Inoreader"

    def _metadata_cache_ttl_s(self) -> int:
        """Cache feed/category metadata aggressively to avoid burning Inoreader API quotas.

        Inoreader provider refresh is server-backed (no local feed crawling), so polling
        subscription metadata every UI refresh interval offers little value but can easily hit
        the default 100 req/day app quota. Manual refresh still bypasses this via cache invalidation.
        """
        try:
            raw = (
                self.conf.get("metadata_cache_ttl_seconds")
                if isinstance(self.conf, dict)
                else None
            )
            ttl = int(raw if raw is not None else 3600)
        except Exception:
            ttl = 3600
        return max(60, min(24 * 3600, ttl))

    def _articles_cache_ttl_s(self) -> int:
        """Short-lived per-view article cache to absorb repeated UI requests."""
        try:
            raw = (
                self.conf.get("article_cache_ttl_seconds")
                if isinstance(self.conf, dict)
                else None
            )
            ttl = int(raw if raw is not None else 90)
        except Exception:
            ttl = 90
        return max(5, min(900, ttl))

    def _articles_page_n(self) -> int:
        """API page size for stream/contents requests (larger pages reduce request count)."""
        try:
            raw = (
                self.conf.get("article_request_page_size")
                if isinstance(self.conf, dict)
                else None
            )
            n = int(raw if raw is not None else 100)
        except Exception:
            n = 100
        return max(20, min(1000, n))

    def _timeout_s(self) -> int:
        """Default network timeout for Inoreader API calls.

        Without a timeout, requests can hang indefinitely and effectively stall refresh/get_feeds
        until the app is restarted.
        """
        try:
            base = int(self.config.get("feed_timeout_seconds", 15) or 15)
        except Exception:
            base = 15
        # Keep a sane floor/ceiling for UI responsiveness.
        return max(5, min(120, int(base)))

    def _parse_timestamp(self, value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _headers(self):
        h = utils.add_revalidation_headers(utils.HEADERS)
        if self.app_id:
            h["AppId"] = self.app_id
        if self.app_key:
            h["AppKey"] = self.app_key
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _cache_is_fresh(self, cache_time: float) -> bool:
        if self._cache_ttl_s <= 0:
            return False
        return (time.time() - cache_time) < self._cache_ttl_s

    def _article_cache_is_fresh(self, cache_time: float) -> bool:
        if self._article_cache_ttl_s <= 0:
            return False
        return (time.time() - float(cache_time or 0.0)) < self._article_cache_ttl_s

    def _build_categories_from_feeds(self, feeds: List[Feed]) -> List[str]:
        categories = []
        seen = set()
        for feed in feeds:
            cat = feed.category or "Uncategorized"
            if cat not in seen:
                categories.append(cat)
                seen.add(cat)
        return sorted(categories, key=lambda c: c.lower())

    def _set_feed_cache(self, feeds: List[Feed]) -> None:
        now = time.time()
        with self._cache_lock:
            self._feeds_cache = list(feeds)
            self._feeds_cache_time = now
            self._categories_cache = self._build_categories_from_feeds(feeds)
            self._categories_cache_time = now
            self._force_next_fetch = False

    def _set_categories_cache(self, categories: List[str]) -> None:
        now = time.time()
        with self._cache_lock:
            self._categories_cache = list(categories)
            self._categories_cache_time = now

    def _get_cached_feeds(self, allow_stale: bool = False) -> List[Feed] | None:
        with self._cache_lock:
            if self._feeds_cache is None:
                return None
            if not allow_stale:
                if self._force_next_fetch or not self._cache_is_fresh(self._feeds_cache_time):
                    return None
            return list(self._feeds_cache)

    def _get_cached_categories(self, allow_stale: bool = False) -> List[str] | None:
        with self._cache_lock:
            if self._categories_cache is None:
                return None
            if not allow_stale and not self._cache_is_fresh(self._categories_cache_time):
                return None
            return list(self._categories_cache)

    def _mark_cache_dirty(self) -> None:
        self._force_next_fetch = True

    def _clear_article_cache(self) -> None:
        with self._article_cache_lock:
            self._article_view_cache.clear()

    def _invalidate_article_cache(self) -> None:
        self._clear_article_cache()

    def _parse_retry_after(self, value: str | None) -> int | None:
        if not value:
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            try:
                dt = parsedate_to_datetime(value)
                if dt is None:
                    return None
                delta = dt.timestamp() - time.time()
                return max(0, int(delta))
            except Exception:
                return None

    def _apply_rate_limit(self, wait_s: int) -> None:
        if wait_s <= 0:
            return
        with self._rate_limit_lock:
            until = time.time() + wait_s
            if until > self._rate_limit_until:
                self._rate_limit_until = until

    def _respect_rate_limit(self, allow_sleep: bool) -> None:
        with self._rate_limit_lock:
            wait_s = max(0.0, self._rate_limit_until - time.time())
        if wait_s <= 0:
            return
        if not allow_sleep:
            retry_after = int(wait_s)
            raise RateLimitError(retry_after, f"Inoreader rate limit active. Retry in {retry_after}s.")
        time.sleep(wait_s)

    def _request(self, method: str, url: str, *, params=None, data=None, **kwargs):
        allow_sleep = threading.current_thread() is not threading.main_thread()
        self._respect_rate_limit(allow_sleep)
        headers = kwargs.pop("headers", None)
        # Always set a timeout unless explicitly overridden by the caller.
        kwargs.setdefault("timeout", self._timeout_s())
        req_headers = self._headers()
        if headers:
            req_headers.update(headers)
        resp = requests.request(method, url, headers=req_headers, params=params, data=data, **kwargs)
        if resp.status_code == 429:
            retry_after = self._parse_retry_after(resp.headers.get("Retry-After")) or 30
            self._apply_rate_limit(retry_after)
            if allow_sleep:
                self._respect_rate_limit(True)
                resp = requests.request(method, url, headers=req_headers, params=params, data=data, **kwargs)
                if resp.status_code == 429:
                    retry_after = self._parse_retry_after(resp.headers.get("Retry-After")) or retry_after
                    self._apply_rate_limit(retry_after)
                    raise RateLimitError(retry_after, f"Inoreader rate limit active. Retry in {retry_after}s.")
            else:
                raise RateLimitError(retry_after, f"Inoreader rate limit active. Retry in {retry_after}s.")
        resp.raise_for_status()
        return resp

    def _update_provider_config(self, data: Dict[str, Any]) -> None:
        try:
            self.conf.update(data)
        except Exception:
            pass
        if hasattr(self.config, "update_provider_config"):
            try:
                self.config.update_provider_config("inoreader", data)
                return
            except Exception:
                pass
        if isinstance(self.config, dict):
            providers = self.config.setdefault("providers", {})
            if isinstance(providers, dict):
                p_cfg = providers.setdefault("inoreader", {})
                if isinstance(p_cfg, dict):
                    p_cfg.update(data)

    def _set_tokens(self, access_token: str | None, refresh_token: str | None, expires_in: Any) -> None:
        if access_token is not None:
            self.token = str(access_token or "")
        if refresh_token is not None:
            self.refresh_token = str(refresh_token or "")
        expires_at = 0
        try:
            expires_in_int = int(expires_in or 0)
            if expires_in_int > 0:
                expires_at = int(time.time() + max(0, expires_in_int - 60))
        except Exception:
            expires_at = 0
        self.token_expires_at = expires_at
        self._update_provider_config({
            "token": self.token or "",
            "refresh_token": self.refresh_token or "",
            "token_expires_at": int(self.token_expires_at or 0),
        })

    def _has_app_credentials(self) -> bool:
        return bool(self.app_id and self.app_key)

    def _token_is_stale(self) -> bool:
        if not self.token:
            return True
        if not self.token_expires_at:
            return False
        return time.time() >= float(self.token_expires_at) - 60
    
    def _has_required_auth(self) -> bool:
        if not self._has_app_credentials():
            return False
        if not self._token_is_stale():
            return True
        if self.refresh_token:
            try:
                data = inoreader_oauth.refresh_access_token(
                    self.app_id,
                    self.app_key,
                    self.refresh_token,
                )
                access_token = data.get("access_token")
                new_refresh = data.get("refresh_token", self.refresh_token)
                expires_in = data.get("expires_in", 0)
                if access_token:
                    self._set_tokens(access_token, new_refresh, expires_in)
                    return True
            except requests.HTTPError as e:
                # Inoreader returns {"error":"invalid_grant", ...} when the refresh token is
                # revoked/expired. Clear it so the UI shows "Not authorized" instead of
                # looping and logging on every refresh.
                try:
                    resp = getattr(e, "response", None)
                    data = resp.json() if resp is not None else None
                except Exception:
                    data = None

                if isinstance(data, dict) and data.get("error") == "invalid_grant":
                    log.warning("Inoreader refresh token invalid; please re-authorize in Settings.")
                    self._set_tokens("", "", 0)
                    return False

                log.error(f"Inoreader Refresh Token Error: {e}")
                return False
            except Exception as e:
                log.error(f"Inoreader Refresh Token Error: {e}")
                return False
        return bool(self.token)

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

    def _resolve_stream_id(self, feed_id: str) -> str | None:
        if not feed_id:
            return None
        if feed_id.startswith(("favorites:", "fav:", "starred:", "read:")):
            return None
        real_feed_id = self._strip_view_prefixes(feed_id)
        if not real_feed_id or real_feed_id == "all":
            return "user/-/state/com.google/reading-list"
        if real_feed_id.startswith("category:"):
            label = real_feed_id.split(":", 1)[1]
            return f"user/-/label/{label}"
        return real_feed_id

    def _resolve_item_feed_id(self, item: Dict[str, Any], fallback_feed_id: str | None) -> str:
        origin = None
        try:
            origin = (item.get("origin") or {}).get("streamId")
        except Exception:
            origin = None
        return str(origin or fallback_feed_id or "")

    def _build_item_cache_id(self, item: Dict[str, Any], fallback_feed_id: str | None) -> str | None:
        article_id = item.get("id")
        if article_id is None:
            return None
        feed_id = self._resolve_item_feed_id(item, fallback_feed_id)
        return utils.build_cache_id(str(article_id), feed_id, self.get_name())

    def _build_articles_request(self, feed_id: str):
        real_feed_id = feed_id
        params: Dict[str, Any] = {"output": "json"}

        if feed_id.startswith("unread:"):
            real_feed_id = feed_id[7:]
            params["xt"] = "user/-/state/com.google/read"
        elif feed_id.startswith("read:"):
            real_feed_id = feed_id[5:]
            params["it"] = "user/-/state/com.google/read"

        if real_feed_id == "all":
            stream_id = "user/-/state/com.google/reading-list"
        elif real_feed_id.startswith("category:"):
            label = real_feed_id.split(":", 1)[1]
            stream_id = f"user/-/label/{label}"
        elif real_feed_id.startswith("favorites:") or real_feed_id.startswith("starred:"):
            stream_id = "user/-/state/com.google/starred"
        else:
            stream_id = real_feed_id

        encoded_stream_id = urllib.parse.quote(str(stream_id or ""), safe="")
        url = f"{self.base_url}/stream/contents/{encoded_stream_id}"
        fallback_feed_id = real_feed_id or stream_id or feed_id
        return url, params, fallback_feed_id

    def _items_to_articles(self, items: List[Dict[str, Any]], fallback_feed_id: str) -> List[Article]:
        if not items:
            return []

        article_ids = [item.get("id") for item in items if item.get("id") is not None]
        chapters_map = utils.get_chapters_batch(article_ids)
        articles: List[Article] = []

        for item in items:
            content = ""
            if "summary" in item:
                content = (item.get("summary") or {}).get("content", "")
            if "content" in item:
                content = (item.get("content") or {}).get("content", "")

            media_url = None
            media_type = None
            if "enclosure" in item and item["enclosure"]:
                encs = item["enclosure"]
                if isinstance(encs, list) and encs:
                    media_url = (encs[0] or {}).get("href")
                    media_type = (encs[0] or {}).get("type")

            article_id = item.get("id")
            if article_id is None:
                continue
            article_feed_id = self._resolve_item_feed_id(item, fallback_feed_id)
            cache_id = self._build_item_cache_id(item, fallback_feed_id)

            alt = item.get("alternate") or [{}]
            if not isinstance(alt, list):
                alt = [{}]
            first_alt = alt[0] if alt else {}
            article_url = ""
            try:
                article_url = first_alt.get("href", "")
            except Exception:
                article_url = ""
            display_title = utils.enhance_activity_entry_title(item.get("title", ""), article_url, content) or item.get("title", "No Title")

            date = utils.normalize_date(
                str(item.get("published", "")),
                display_title,
                content,
                article_url,
            )

            chapters = chapters_map.get(article_id, [])

            is_fav = False
            is_read_flag = False
            for cat in item.get("categories", []) or []:
                if "starred" in str(cat):
                    is_fav = True
                if "read" in str(cat) and "com.google" in str(cat):
                    is_read_flag = True

            articles.append(Article(
                id=article_id,
                feed_id=article_feed_id,
                title=display_title,
                url=article_url,
                content=content,
                date=date,
                author=item.get("author", "Unknown"),
                is_read=is_read_flag,
                is_favorite=is_fav,
                media_url=media_url,
                media_type=media_type,
                chapters=chapters,
                cache_id=cache_id,
            ))

        return articles

    def _new_article_view_state(self, feed_id: str) -> Dict[str, Any]:
        url, base_params, fallback_feed_id = self._build_articles_request(feed_id)
        return {
            "feed_id": str(feed_id or ""),
            "url": url,
            "base_params": dict(base_params),
            "fallback_feed_id": fallback_feed_id,
            "articles": [],
            "id_set": set(),
            "continuation": None,
            "complete": False,
            "updated_at": 0.0,
        }

    def _get_article_view_state(self, feed_id: str, require_fresh: bool = True) -> Dict[str, Any] | None:
        key = str(feed_id or "")
        with self._article_cache_lock:
            state = self._article_view_cache.get(key)
            if not state:
                return None
            if require_fresh and not self._article_cache_is_fresh(state.get("updated_at", 0.0)):
                self._article_view_cache.pop(key, None)
                return None
            return state

    def _save_article_view_state(self, feed_id: str, state: Dict[str, Any]) -> None:
        key = str(feed_id or "")
        state["updated_at"] = time.time()
        with self._article_cache_lock:
            self._article_view_cache[key] = state

    def _fetch_articles_page_from_api(self, state: Dict[str, Any]) -> None:
        params = dict(state.get("base_params") or {})
        params["n"] = self._article_page_n
        continuation = state.get("continuation")
        if continuation:
            params["c"] = continuation

        resp = self._request("get", state["url"], params=params)
        data = resp.json() if resp is not None else {}
        items = data.get("items") or []
        continuation = data.get("continuation")

        new_articles = self._items_to_articles(items, state.get("fallback_feed_id", ""))
        for article in new_articles:
            cache_id = str(getattr(article, "cache_id", "") or "")
            if not cache_id:
                cache_id = str(getattr(article, "id", "") or "")
            if not cache_id or cache_id in state["id_set"]:
                continue
            state["id_set"].add(cache_id)
            state["articles"].append(article)

        state["continuation"] = continuation
        if not items or not continuation:
            state["complete"] = True

    def _get_articles_page_cached(self, feed_id: str, offset: int, limit: int):
        target = max(0, int(offset)) + max(0, int(limit))
        state = self._get_article_view_state(feed_id, require_fresh=True)
        if state is None:
            state = self._new_article_view_state(feed_id)

        while (not state.get("complete")) and len(state.get("articles", [])) < target:
            self._fetch_articles_page_from_api(state)
            self._save_article_view_state(feed_id, state)

        # Cache freshly built state even if no remote fetch was needed (keeps TTL current for repeated opens).
        if state.get("updated_at", 0.0) <= 0:
            self._save_article_view_state(feed_id, state)

        articles = list(state.get("articles") or [])
        total = len(articles) if state.get("complete") else None
        start = max(0, int(offset))
        end = start + max(0, int(limit))
        return articles[start:end], total

    def _iter_unread_ids(self, stream_id: str):
        if not stream_id:
            return
        continuation = None
        base_params = {
            "s": stream_id,
            "output": "json",
            "n": 1000,
            "xt": "user/-/state/com.google/read",
        }
        while True:
            params = dict(base_params)
            if continuation:
                params["c"] = continuation
            resp = self._request("get", f"{self.base_url}/stream/items/ids", params=params)
            data = resp.json() if resp is not None else {}
            items = data.get("items") or []
            for item_id in items:
                if item_id is not None:
                    yield str(item_id)
            continuation = data.get("continuation")
            if not continuation or not items:
                break

    def _set_read_state_batch(self, article_ids: List[str], is_read: bool) -> bool:
        if not self._has_required_auth():
            return False
        if not article_ids:
            return True
        action_key = "a" if is_read else "r"
        state_value = "user/-/state/com.google/read"
        chunk_size = 200
        ok = True
        for i in range(0, len(article_ids), chunk_size):
            chunk = article_ids[i:i + chunk_size]
            data = [("i", str(aid)) for aid in chunk if aid is not None]
            if not data:
                continue
            data.append((action_key, state_value))
            try:
                resp = self._request("post", f"{self.base_url}/edit-tag", data=data)
                if not getattr(resp, "ok", False):
                    ok = False
            except Exception as e:
                log.error(f"Inoreader batch edit-tag failed: {e}")
                ok = False
        return ok

    def refresh(self, progress_cb=None, force: bool = False) -> bool:
        if force:
            self._mark_cache_dirty()
            self._clear_article_cache()
            return True
        # Inoreader is already server-synced; avoid triggering subscription/category fetches on
        # every client refresh tick when metadata is still cached.
        if self._get_cached_feeds(allow_stale=False) is not None:
            return False
        return True

    def get_feeds(self) -> List[Feed]:
        if not self._has_required_auth():
            return []

        cached = self._get_cached_feeds(allow_stale=False)
        if cached is not None:
            return cached

        try:
            resp = self._request("get", f"{self.base_url}/subscription/list", params={"output": "json"})
            data = resp.json()

            feeds = []
            for sub in data.get("subscriptions", []):
                cat = "Uncategorized"
                if sub.get("categories"):
                    cat = sub["categories"][0]["label"]

                feeds.append(Feed(
                    id=sub["id"],
                    title=sub["title"],
                    url=sub["url"],
                    category=cat,
                    icon_url=sub.get("iconUrl", "")
                ))
            self._set_feed_cache(feeds)
            return feeds
        except RateLimitError as e:
            cached = self._get_cached_feeds(allow_stale=True)
            if cached is not None:
                log.warning(f"Inoreader Feeds Rate Limit: {e}")
                return cached
            raise
        except Exception as e:
            cached = self._get_cached_feeds(allow_stale=True)
            if cached is not None:
                log.error(f"Inoreader Feeds Error (cached): {e}")
                return cached
            log.error(f"Inoreader Feeds Error: {e}")
            raise

    def get_articles(self, feed_id: str) -> List[Article]:
        try:
            articles, _total = self.get_articles_page(feed_id, offset=0, limit=50)
            return articles
        except Exception as e:
            log.error(f"Inoreader Articles Error: {e}")
            return []

    def get_articles_page(self, feed_id: str, offset: int = 0, limit: int = 200):
        if not self._has_required_auth():
            return [], 0
        try:
            off = max(0, int(offset or 0))
            lim = max(0, int(limit or 0))
            if lim <= 0:
                return [], 0
            return self._get_articles_page_cached(feed_id, off, lim)
        except RateLimitError:
            stale = self._get_article_view_state(feed_id, require_fresh=False)
            if stale:
                articles = list(stale.get("articles") or [])
                off = max(0, int(offset or 0))
                lim = max(0, int(limit or 0))
                return articles[off:off + lim], (len(articles) if stale.get("complete") else None)
            raise
        except Exception as e:
            log.error(f"Inoreader Articles Page Error: {e}")
            return [], 0

    def get_article_chapters(self, article_id: str) -> List[Dict]:
        # Similar to Miniflux, we need media info.
        # For now, try to check DB.
        chapters = utils.get_chapters_from_db(article_id)
        if chapters: return chapters
        # We can't easily fetch single item details without knowing feed ID in Google Reader API sometimes,
        # but strictly speaking /stream/items/ids works if supported.
        return []

    def mark_read(self, article_id: str) -> bool:
        if not self._has_required_auth(): return False
        try:
            self._request("post", f"{self.base_url}/edit-tag", data={
                "i": article_id,
                "a": "user/-/state/com.google/read"
            })
            self._invalidate_article_cache()
            return True
        except Exception as e:
            log.error(f"Inoreader Mark Read Error: {e}")
            return False

    def mark_unread(self, article_id: str) -> bool:
        if not self._has_required_auth(): return False
        try:
            self._request("post", f"{self.base_url}/edit-tag", data={
                "i": article_id,
                "r": "user/-/state/com.google/read"
            })
            self._invalidate_article_cache()
            return True
        except Exception as e:
            log.error(f"Inoreader Mark Unread Error: {e}")
            return False

    def mark_read_batch(self, article_ids: List[str]) -> bool:
        ok = self._set_read_state_batch(article_ids, True)
        if ok:
            self._invalidate_article_cache()
        return ok

    def mark_all_read(self, feed_id: str) -> bool:
        if not self._has_required_auth():
            return False
        if not feed_id or feed_id.startswith(("favorites:", "fav:", "starred:", "read:")):
            return False
        stream_id = self._resolve_stream_id(feed_id)
        if not stream_id:
            return False

        # Prefer the native API endpoint for efficiency.
        try:
            ts = int(time.time() * 1_000_000)
            resp = self._request(
                "post",
                f"{self.base_url}/mark-all-as-read",
                data={"s": stream_id, "ts": str(ts)},
            )
            if getattr(resp, "ok", False):
                self._invalidate_article_cache()
                return True
        except Exception as e:
            log.error(f"Inoreader mark-all-as-read failed for {feed_id}: {e}")

        # Fallback: enumerate unread item ids and mark them read in batches.
        try:
            unread_ids = list(self._iter_unread_ids(stream_id))
            if not unread_ids:
                return True
            ok = self._set_read_state_batch(unread_ids, True)
            if ok:
                self._invalidate_article_cache()
            return ok
        except Exception as e:
            log.error(f"Inoreader mark-all fallback failed for {feed_id}: {e}")
            return False

    def supports_favorites(self) -> bool:
        return True

    def set_favorite(self, article_id: str, is_favorite: bool) -> bool:
        if not self._has_required_auth(): return False
        try:
            action = "a" if is_favorite else "r"
            self._request("post", f"{self.base_url}/edit-tag", data={
                "i": article_id,
                action: "user/-/state/com.google/starred"
            })
            self._invalidate_article_cache()
            return True
        except Exception as e:
            log.error(f"Inoreader Set Favorite Error: {e}")
            return False

    def toggle_favorite(self, article_id: str):
        if not self._has_required_auth(): return None
        try:
            resp = self._request("get", f"{self.base_url}/stream/items/ids", params={"i": article_id, "output": "json"})
            if resp.ok:
                items = resp.json().get("items", [])
                if items:
                    cats = items[0].get("categories", [])
                    is_fav = any("starred" in c for c in cats)
                    new_state = not is_fav
                    self.set_favorite(article_id, new_state)
                    return new_state
        except:
            pass
        return None

    def add_feed(self, url: str, category: str = None) -> bool:
        if not self._has_required_auth(): return False
        from core.discovery import get_ytdlp_feed_url, discover_feed
        real_url = get_ytdlp_feed_url(url) or discover_feed(url) or url
        try:
            data = {
                "s": f"feed/{real_url}",
                "ac": "subscribe"
            }
            if category:
                data["t"] = category
            
            self._request("post", f"{self.base_url}/subscription/edit", data=data)
            self._mark_cache_dirty()
            self._clear_article_cache()
            return True
        except Exception as e:
            log.error(f"Inoreader Add Feed Error: {e}")
            return False

    def remove_feed(self, feed_id: str) -> bool:
        if not self._has_required_auth(): return False
        try:
            self._request("post", f"{self.base_url}/subscription/edit", data={
                "s": feed_id,
                "ac": "unsubscribe"
            })
            self._mark_cache_dirty()
            self._clear_article_cache()
            return True
        except Exception as e:
            log.error(f"Inoreader Remove Feed Error: {e}")
            return False

    def supports_feed_edit(self) -> bool:
        return True

    def supports_feed_url_update(self) -> bool:
        return False

    def update_feed(self, feed_id: str, title: str = None, url: str = None, category: str = None) -> bool:
        if not self._has_required_auth():
            return False
        data = {"s": feed_id, "ac": "edit"}
        if title is not None:
            data["t"] = title

        if category is not None:
            current_cat = None
            try:
                for f in self.get_feeds():
                    if f.id == feed_id:
                        current_cat = f.category or "Uncategorized"
                        break
            except Exception:
                current_cat = None
            if current_cat and current_cat != category:
                if current_cat and current_cat != "Uncategorized":
                    data["r"] = f"user/-/label/{current_cat}"
                if category and category != "Uncategorized":
                    data["a"] = f"user/-/label/{category}"

        try:
            resp = self._request("post", f"{self.base_url}/subscription/edit", data=data)
            if resp.ok:
                self._mark_cache_dirty()
                self._clear_article_cache()
            return resp.ok
        except Exception as e:
            log.error(f"Inoreader Update Feed Error: {e}")
            return False

    def get_categories(self) -> List[str]:
        if not self._has_required_auth():
            return []

        cached = self._get_cached_categories(allow_stale=False)
        if cached is not None:
            return cached

        feeds_cached = self._get_cached_feeds(allow_stale=True)
        if feeds_cached is not None:
            cats = self._build_categories_from_feeds(feeds_cached)
            self._set_categories_cache(cats)
            return cats

        try:
            resp = self._request("get", f"{self.base_url}/tag/list", params={"output": "json"})
            data = resp.json()
            cats = []
            for tag in data.get("tags", []):
                tag_id = tag.get("id", "")
                if tag_id.startswith("user/") and "/label/" in tag_id:
                    label = tag_id.split("/label/", 1)[1]
                    cats.append(label)
            cats = sorted(cats, key=lambda c: c.lower())
            self._set_categories_cache(cats)
            return cats
        except RateLimitError as e:
            cached = self._get_cached_categories(allow_stale=True)
            if cached is not None:
                log.warning(f"Inoreader Get Categories Rate Limit: {e}")
                return cached
            raise
        except Exception as e:
            cached = self._get_cached_categories(allow_stale=True)
            if cached is not None:
                log.error(f"Inoreader Get Categories Error (cached): {e}")
                return cached
            log.error(f"Inoreader Get Categories Error: {e}")
            raise

    def add_category(self, title: str) -> bool:
        self._mark_cache_dirty()
        return True

    def rename_category(self, old_title: str, new_title: str) -> bool:
        if not self._has_required_auth(): return False
        try:
            source = f"user/-/label/{old_title}"
            dest = f"user/-/label/{new_title}"
            resp = self._request("post", f"{self.base_url}/rename-tag", data={
                "s": source,
                "dest": dest
            })
            if resp.ok:
                self._mark_cache_dirty()
                self._clear_article_cache()
            return resp.ok
        except Exception as e:
            log.error(f"Inoreader Rename Category Error: {e}")
            return False

    def delete_category(self, title: str) -> bool:
        if not self._has_required_auth(): return False
        try:
            tag = f"user/-/label/{title}"
            self._request("post", f"{self.base_url}/disable-tag", data={
                "s": tag
            })
            self._mark_cache_dirty()
            self._clear_article_cache()
            return True
        except Exception as e:
            log.error(f"Inoreader Delete Category Error: {e}")
            return False
