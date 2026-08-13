# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import requests
from requests.adapters import HTTPAdapter
import hashlib
import re
import logging
import ssl
import time
import copy
import concurrent.futures
import threading
from xml.etree import ElementTree as ET
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser
from .base import RSSProvider
from core.models import Feed, Article
from core.categories import UNCATEGORIZED
from core import utils

log = logging.getLogger(__name__)


class _SystemTrustHTTPAdapter(HTTPAdapter):
    """Requests adapter that starts with the operating system's trusted roots.

    Requests normally replaces the platform defaults with its bundled CA file.
    That makes a private CA trusted through Windows Certificate Manager invisible
    to Miniflux connections.  Starting urllib3 with ``create_default_context``
    loads Windows' CA/ROOT stores first; Requests may then add its public CA file
    without discarding those locally trusted roots.
    """

    def __init__(self, *args, **kwargs):
        self._system_ssl_context = ssl.create_default_context()
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self._system_ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs.setdefault("ssl_context", self._system_ssl_context)
        return super().proxy_manager_for(proxy, **proxy_kwargs)


class MinifluxProvider(RSSProvider):
    # Short connect timeout so an unreachable address (e.g. a dead IPv6 AAAA whose
    # gateway is down) fails over to the next address in seconds instead of stalling
    # the UI for the full read timeout. This does NOT pin IPv4: the OS still orders
    # addresses normally (IPv6-first per RFC 6724), so when IPv6 is healthy its
    # connect succeeds immediately and is used. The generous read timeout below
    # still covers large entry payloads.
    CONNECT_TIMEOUT_SECONDS = 3

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
        # Shared session so TCP/TLS connections are reused (keep-alive) across the
        # many calls a single refresh makes. Without this every request opens a new
        # HTTPS connection, paying a full handshake each time -- which on a host whose
        # DNS advertises an unreachable AAAA also re-incurs the IPv6 connect timeout
        # on every call. One pooled connection turns ~6 handshakes per refresh into 1.
        self._session = requests.Session()
        # pool_maxsize must exceed the targeted-refresh worker cap (32 in
        # _targeted_refresh_worker_count) plus the handful of concurrent GETs the
        # refresh and feed-tree-load threads issue during a force refresh, PLUS the
        # few straggler connections a previous manual refresh may still hold open
        # while its slow feeds finish in the background. 48 keeps comfortable headroom
        # so back-to-back refreshes don't overflow the pool. Otherwise urllib3 discards
        # and re-handshakes the overflow connections ("Connection pool is full,
        # discarding connection"), re-paying a TLS handshake per overflow worker.
        adapter = _SystemTrustHTTPAdapter(pool_connections=4, pool_maxsize=48)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._cached_get_responses: dict[str, Any] = {}
        # Per-thread: the feed-tree load and a refresh run issue overlapping GETs
        # (both fetch /v1/feeds within milliseconds at startup), and a single shared
        # slot means whichever finishes last describes *both*. The refresh decides
        # whether to fire targeted per-feed refreshes from this, so a cross-thread
        # read is a real wrong-decision bug, not just a confusing log line.
        self._request_info_local = threading.local()
        self._last_add_feed_result = {
            "ok": False,
            "duplicate": False,
            "feed_id": None,
            "feed_url": None,
        }
        # Optional same-origin companion used by self-hosted Miniflux instances
        # to solve browser-verification challenges from the Miniflux host's own
        # IP.  A 404 disables probing for the rest of this process, so ordinary
        # Miniflux servers pay at most one cheap capability check.
        self._browser_feed_fallback_available = None
        # Backoff for repeatedly failing targeted per-feed refresh endpoints.
        # This avoids hammering a single broken feed refresh route and spamming logs.
        self._targeted_refresh_backoff_until: dict[str, float] = {}
        self._targeted_refresh_fail_counts: dict[str, int] = {}
        self._targeted_refresh_backoff_lock = threading.Lock()
        # Server-wide circuit breaker for the targeted per-feed refresh route.
        # The per-feed backoff above only helps the *next* cycle: when the server
        # rejects the route outright it answers 5xx for every feed, so a whole
        # batch fires and fails before any backoff applies. This stops the batch
        # mid-flight and parks the route for a cooldown.
        self._targeted_refresh_route_cooldown_until = 0.0

    @staticmethod
    def _blank_request_info() -> dict[str, Any]:
        return {
            "ok": False,
            "used_cache": False,
            "status_code": None,
            "endpoint": "",
            "method": "",
            "error_body": None,
            "error_message": None,
        }

    @property
    def _last_request_info(self) -> dict[str, Any]:
        """Outcome of the most recent request *made on this thread*."""
        info = getattr(self._request_info_local, "info", None)
        if info is None:
            info = self._blank_request_info()
            self._request_info_local.info = info
        return info

    @_last_request_info.setter
    def _last_request_info(self, value) -> None:
        try:
            self._request_info_local.info = dict(value or {})
        except Exception:
            self._request_info_local.info = self._blank_request_info()

    def _browser_feed_fallback_request(self, action: str, payload: dict, *, wait: bool = False):
        """Call the optional direct-browser Miniflux companion endpoint.

        The API token is forwarded only to the configured Miniflux origin.  The
        companion validates it against ``/v1/me`` before doing any work.  This
        path is intentionally separate from ``_req`` because it is an optional
        BlindRSS extension rather than an upstream Miniflux API route.
        """
        if not bool(self.config.get("browser_feed_fallback_enabled", True)):
            return None
        if self._browser_feed_fallback_available is False or not self.base_url:
            return None

        path = str(
            self.conf.get(
                "browser_feed_fallback_path",
                "/blindrss-browser-feed/v1",
            )
            or ""
        ).strip()
        if not path:
            return None
        if not path.startswith("/"):
            path = "/" + path
        endpoint = f"{self.base_url}{path.rstrip('/')}/{str(action or '').strip('/')}"

        timeout_s = 12
        if wait:
            try:
                browser_timeout = float(
                    self.config.get("browser_feed_fallback_timeout_seconds", 90) or 90
                )
            except (TypeError, ValueError):
                browser_timeout = 90.0
            timeout_s = int(max(45.0, min(browser_timeout, 180.0)) + 30.0)

        try:
            response = self._session.post(
                endpoint,
                headers=self.headers,
                json=dict(payload or {}),
                timeout=(self.CONNECT_TIMEOUT_SECONDS, timeout_s),
            )
        except Exception:
            log.debug("Miniflux browser-feed fallback request failed", exc_info=True)
            return None

        if response.status_code == 404:
            self._browser_feed_fallback_available = False
            return None
        if response.status_code not in (200, 201, 202):
            log.warning(
                "Miniflux browser-feed fallback rejected action=%s status=%s",
                action,
                response.status_code,
            )
            return None

        self._browser_feed_fallback_available = True
        try:
            value = response.json()
        except Exception:
            value = {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _looks_like_browser_challenge_error(value) -> bool:
        text = str(value or "").casefold()
        return any(
            marker in text
            for marker in (
                "status code: 403",
                "status code 403",
                "http 403",
                "forbidden",
                "cloudflare",
                "browser verification",
                "bot challenge",
                "cf-mitigated",
            )
        )

    def _queue_browser_feed_recovery(self, feed_ids=None) -> bool:
        result = self._browser_feed_fallback_request(
            "recover",
            {"feed_ids": [str(value) for value in (feed_ids or []) if str(value).strip()]},
            wait=False,
        )
        return result is not None

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
            # Per-feed refresh is a synchronous server-side upstream fetch: Miniflux
            # goes out and fetches the feed while our HTTP request stays open. We must
            # NOT cancel a feed the server is still legitimately fetching -- that would
            # drop real content from slow-but-alive feeds. So the client read timeout
            # is kept generous (>= the server's own HTTP_CLIENT_TIMEOUT plus margin).
            # Bounding *dead* feeds is the server's job, not ours: Miniflux gives up on
            # an unresponsive upstream at HTTP_CLIENT_TIMEOUT and returns an error,
            # which we receive comfortably within this window. Lowering the server's
            # HTTP_CLIENT_TIMEOUT -- not this client value -- is how you trade dead-feed
            # patience for speed.
            try:
                floor = int(self.config.get("miniflux_per_feed_refresh_timeout_s", 18) or 18)
            except Exception:
                floor = 18
            return max(base_timeout, floor)
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
            # Per-feed refresh must not retry: a slow feed hits the per-feed timeout
            # cap, and a retry would re-pay that full cap (turning one 8s stall into
            # ~16s) and dominate the whole-account refresh wall-clock. One attempt is
            # enough -- the server keeps fetching in the background and the global
            # refresh / next scheduled cycle reconciles any straggler.
            retries = 0
        return retries

    def _is_transient_status(self, status_code: int | None) -> bool:
        return int(status_code or 0) in (429, 500, 502, 503, 504)

    def _is_targeted_refresh_endpoint(self, endpoint: str = "") -> bool:
        ep = str(endpoint or "").strip().lower()
        return ep.startswith("/v1/feeds/") and ep.endswith("/refresh") and ep != "/v1/feeds/refresh"

    def _targeted_refresh_worker_count(self, feed_count: int) -> int:
        try:
            configured = int(
                self.config.get(
                    "miniflux_targeted_refresh_workers",
                    8,
                )
                or 1
            )
        except Exception:
            configured = 8
        try:
            count = max(1, int(feed_count or 0))
        except Exception:
            count = 1
        # Cap at 32: enough parallelism to refresh a large (100+ feed) account in a
        # few waves, while staying within the HTTP connection pool (pool_maxsize=48)
        # and not overwhelming the upstream Miniflux server with outbound fetches.
        # Users who want more can raise miniflux_targeted_refresh_workers, but the
        # hard cap protects the shared connection pool from overflow re-handshakes.
        return max(1, min(32, configured, count))

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

    def _targeted_refresh_route_batch_5xx_limit(self) -> int:
        """Consecutive 5xx from the per-feed refresh route before the whole batch is
        abandoned. 0 disables the breaker. Default 3: one or two failures are a bad
        feed, but three in a row means the route itself is refusing work."""
        try:
            val = int(self.config.get("miniflux_targeted_refresh_5xx_limit", 3))
        except Exception:
            val = 3
        return max(0, val)

    def _targeted_refresh_route_cooldown_seconds(self) -> float:
        try:
            val = float(self.config.get("miniflux_targeted_refresh_cooldown_s", 300) or 0)
        except Exception:
            val = 300.0
        return max(0.0, val)

    def _targeted_refresh_route_in_cooldown(self) -> bool:
        try:
            return float(self._targeted_refresh_route_cooldown_until or 0.0) > time.monotonic()
        except Exception:
            return False

    def _trip_targeted_refresh_route_breaker(self, failures: int) -> None:
        cooldown = self._targeted_refresh_route_cooldown_seconds()
        if cooldown <= 0:
            return
        already = self._targeted_refresh_route_in_cooldown()
        self._targeted_refresh_route_cooldown_until = time.monotonic() + cooldown
        if not already:
            log.warning(
                "Miniflux per-feed refresh route returned %s consecutive 5xx; "
                "skipping targeted refreshes for %.0fs and letting the server poller work.",
                failures,
                cooldown,
            )

    def _should_attempt_targeted_refresh(self, feed_id: str, *, force: bool = False) -> bool:
        fid = str(feed_id or "").strip()
        if not fid:
            return False
        if self._targeted_refresh_route_in_cooldown():
            return False
        now_mono = time.monotonic()
        try:
            with self._targeted_refresh_backoff_lock:
                block_until = float(self._targeted_refresh_backoff_until.get(fid, 0.0) or 0.0)
                fail_count = int(self._targeted_refresh_fail_counts.get(fid, 0) or 0)
        except Exception:
            block_until, fail_count = 0.0, 0
        in_backoff = block_until > now_mono

        if force:
            # A manual refresh retries a feed's first failure (usually transient), but
            # keeps skipping a feed that keeps failing while it is inside its backoff
            # window: an immediate synchronous retry won't fix a chronically-broken feed
            # and it holds a worker for the full timeout, dragging out the background
            # straggler drain. The server's own poller keeps retrying it on schedule.
            return not (in_backoff and fail_count >= 2)

        if in_backoff:
            return False
        try:
            with self._targeted_refresh_backoff_lock:
                self._targeted_refresh_backoff_until.pop(fid, None)
        except Exception:
            pass
        return True

    def _force_skip_error_count(self) -> int:
        """parsing_error_count at/above which a manual refresh skips a feed as
        chronically broken (the server has failed to parse it this many times in a
        row). 0 disables server-side skipping. Default 3 -- past a transient hiccup."""
        try:
            val = int(self.config.get("miniflux_force_skip_error_count", 3))
        except Exception:
            val = 3
        return max(0, val)

    def _record_targeted_refresh_attempt_result(self, feed_id: str, ok: bool, status_code: int | None) -> None:
        fid = str(feed_id or "").strip()
        if not fid:
            return
        if bool(ok):
            try:
                with self._targeted_refresh_backoff_lock:
                    self._targeted_refresh_backoff_until.pop(fid, None)
                    self._targeted_refresh_fail_counts.pop(fid, None)
            except Exception:
                pass
            return

        # Back off on any failure status (especially repeated 5xx) to reduce log spam
        # and avoid hammering the same endpoint every refresh cycle.
        try:
            with self._targeted_refresh_backoff_lock:
                fail_count = int(self._targeted_refresh_fail_counts.get(fid, 0) or 0) + 1
                self._targeted_refresh_fail_counts[fid] = fail_count
        except Exception:
            fail_count = 1
        delay = self._targeted_refresh_failure_backoff_seconds(fail_count)
        try:
            with self._targeted_refresh_backoff_lock:
                self._targeted_refresh_backoff_until[fid] = time.monotonic() + float(delay)
        except Exception:
            pass
        try:
            if int(status_code or 0) >= 500 or int(status_code or 0) in (429, 502, 503, 504):
                log.debug(
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

    def _unread_count_from_map(self, unread_map: dict, feed_id: str, raw_id=None) -> int:
        try:
            return int(
                unread_map.get(str(feed_id), None)
                if unread_map.get(str(feed_id), None) is not None
                else unread_map.get(raw_id, 0)
            )
        except Exception:
            return 0

    def _feed_progress_state_from_metadata(
        self,
        feed: Dict[str, Any],
        unread_map: dict,
        stale_cutoff,
        *,
        status_override: str | None = None,
        error_override: str | None = None,
    ) -> dict[str, Any]:
        feed_id = str(feed.get("id") or "")
        category = (feed.get("category") or {}).get("title", UNCATEGORIZED)
        unread = self._unread_count_from_map(unread_map or {}, feed_id, feed.get("id"))

        status = "ok"
        error_msg = None
        if status_override is not None:
            status = status_override
            error_msg = error_override
        else:
            checked_dt = self._parse_checked_at(feed.get("checked_at"))
            if (feed.get("parsing_error_count") or 0) > 0:
                status = "error"
                error_msg = feed.get("parsing_error_message")
            elif checked_dt and checked_dt < stale_cutoff:
                status = "stale"

        return {
            "id": feed_id,
            "title": feed.get("title") or "",
            "category": category,
            "unread_count": unread,
            "status": status,
            "new_items": None,
            "error": error_msg,
        }

    def _targeted_refresh_progress_state(
        self,
        feed_id: str,
        info: dict[str, Any],
        progress_states: dict[str, dict[str, Any]] | None,
    ) -> dict[str, Any]:
        fid = str(feed_id or "").strip()
        state = dict((progress_states or {}).get(fid) or {})
        if not state:
            state = {
                "id": fid,
                "title": fid,
                "category": UNCATEGORIZED,
                "unread_count": 0,
                "new_items": None,
            }

        if bool((info or {}).get("ok", False)):
            state["status"] = "ok"
            state["error"] = None
        else:
            status_code = (info or {}).get("status_code")
            state["status"] = "error"
            state["error"] = f"HTTP {status_code}" if status_code else "Refresh request failed."
        return state

    def get_name(self) -> str:
        return "Miniflux"

    def _chapter_cache_key(self, article_id: str) -> str | None:
        account = str(self.conf.get("api_key") or "").strip()
        identity = f"{self.base_url.rstrip('/').lower()}|{account}"
        identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return utils.build_chapter_cache_key(
            f"{self.get_name()}:{identity_hash}",
            article_id,
        )

    def test_connection(self) -> bool:
        res = self._req("GET", "/v1/me")
        return res is not None

    def get_connection_error(self) -> str | None:
        """Return an actionable description of the latest failed API request."""
        info = dict(self._last_request_info or {})
        if info.get("ok"):
            return None
        message = str(info.get("error_message") or "").strip()
        if message:
            return message
        status_code = info.get("status_code")
        if status_code:
            return f"Miniflux returned HTTP {status_code}."
        return None

    @staticmethod
    def _format_request_error(error: Exception, url: str) -> str:
        detail = " ".join(str(error or "").split())
        if isinstance(error, requests.exceptions.SSLError):
            message = (
                f"TLS certificate verification failed for {url}. BlindRSS uses the "
                "operating system certificate store for Miniflux; ensure the issuing "
                "CA is trusted and the certificate hostname matches."
            )
        elif isinstance(error, requests.Timeout):
            message = f"The Miniflux server at {url} timed out."
        elif isinstance(error, requests.HTTPError):
            status_code = int(
                getattr(getattr(error, "response", None), "status_code", 0) or 0
            )
            if status_code in (401, 403):
                message = (
                    f"Miniflux rejected the connection with HTTP {status_code}. "
                    "Check the Miniflux URL and API key."
                )
            elif status_code:
                message = f"Miniflux returned HTTP {status_code} for {url}."
            else:
                message = f"Miniflux rejected the request to {url}."
        elif isinstance(error, requests.ConnectionError):
            message = f"Could not connect to the Miniflux server at {url}."
        else:
            message = f"The Miniflux request to {url} failed."
        if detail and detail.casefold() not in message.casefold():
            message = f"{message} Details: {detail}"
        return message

    def _req(self, method, endpoint, json=None, params=None, data=None, extra_headers=None):
        if not self.base_url:
            self._last_request_info = {
                "ok": False,
                "used_cache": False,
                "status_code": None,
                "endpoint": str(endpoint or ""),
                "method": str(method or "").upper(),
                "error_body": None,
                "error_message": "The Miniflux URL is empty.",
            }
            return None
        url = f"{self.base_url}{endpoint}"
        timeout_s = self._request_timeout_seconds(endpoint)
        retries = self._request_retry_attempts(endpoint)
        req_headers = utils.add_revalidation_headers(self.headers)
        if extra_headers:
            req_headers.update(dict(extra_headers))
        method_upper = str(method or "").upper()
        is_get = method_upper == "GET"
        is_targeted_refresh = self._is_targeted_refresh_endpoint(endpoint)
        last_error = None
        last_status_code = None
        last_error_message = None

        for attempt in range(1, retries + 2):
            try:
                # Uses self.headers which includes a browser-like User-Agent.
                # Shared session reuses the keep-alive connection across calls.
                request_kwargs = {
                    "headers": req_headers,
                    "json": json,
                    "params": params,
                    "timeout": (self.CONNECT_TIMEOUT_SECONDS, timeout_s),
                }
                if data is not None:
                    request_kwargs["data"] = data
                resp = self._session.request(method_upper, url, **request_kwargs)

                status_code = int(getattr(resp, "status_code", 0) or 0)
                last_status_code = status_code
                if self._is_transient_status(status_code) and attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log_fn = log.debug if is_targeted_refresh else log.warning
                    log_fn(
                        "Miniflux transient HTTP %s for %s %s (attempt %s/%s); retrying in %.1fs",
                        status_code,
                        method_upper,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    if self._sleep_or_cancel_refresh(delay):
                        self._last_request_info = {
                            "ok": False,
                            "used_cache": False,
                            "status_code": last_status_code,
                            "endpoint": str(endpoint or ""),
                            "method": method_upper,
                            "error_body": None,
                            "cancelled": True,
                        }
                        return None
                    continue

                resp.raise_for_status()

                if status_code == 204:
                    self._last_request_info = {
                        "ok": True,
                        "used_cache": False,
                        "status_code": status_code,
                        "endpoint": str(endpoint or ""),
                        "method": method_upper,
                        "error_body": None,
                        "error_message": None,
                    }
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
                        "error_message": f"Miniflux returned invalid JSON for {url}.",
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
                    "error_message": None,
                }
                return payload

            except requests.HTTPError as e:
                last_error = e
                last_error_message = self._format_request_error(e, url)
                status_code = None
                body_preview = ""
                try:
                    status_code = int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
                except Exception:
                    status_code = 0
                last_status_code = status_code

                if self._is_transient_status(status_code) and attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log_fn = log.debug if is_targeted_refresh else log.warning
                    log_fn(
                        "Miniflux transient HTTP %s for %s %s (attempt %s/%s); retrying in %.1fs",
                        status_code,
                        method_upper,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    if self._sleep_or_cancel_refresh(delay):
                        self._last_request_info = {
                            "ok": False,
                            "used_cache": False,
                            "status_code": last_status_code,
                            "endpoint": str(endpoint or ""),
                            "method": method_upper,
                            "error_body": None,
                            "cancelled": True,
                        }
                        return None
                    continue

                if self._is_transient_status(status_code):
                    log_fn = log.debug if is_targeted_refresh else log.warning
                    log_fn("Miniflux transient HTTP %s for %s %s: %s", status_code, method_upper, url, e)
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
                last_error_message = self._format_request_error(e, url)
                last_status_code = None
                if attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log_fn = log.debug if is_targeted_refresh else log.warning
                    log_fn(
                        "Miniflux timeout for %s %s (timeout=%ss, attempt %s/%s); retrying in %.1fs",
                        method_upper,
                        url,
                        timeout_s,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    if self._sleep_or_cancel_refresh(delay):
                        self._last_request_info = {
                            "ok": False,
                            "used_cache": False,
                            "status_code": last_status_code,
                            "endpoint": str(endpoint or ""),
                            "method": method_upper,
                            "error_body": None,
                            "cancelled": True,
                        }
                        return None
                    continue
                if is_targeted_refresh:
                    log.debug("Miniflux timeout for %s (timeout=%ss): %s", url, timeout_s, e)
                else:
                    log.warning("Miniflux timeout for %s (timeout=%ss): %s", url, timeout_s, e)
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
                last_error_message = self._format_request_error(e, url)
                last_status_code = None
                if attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log_fn = log.debug if is_targeted_refresh else log.warning
                    log_fn(
                        "Miniflux request error for %s %s (attempt %s/%s); retrying in %.1fs: %s",
                        method_upper,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                        e,
                    )
                    if self._sleep_or_cancel_refresh(delay):
                        self._last_request_info = {
                            "ok": False,
                            "used_cache": False,
                            "status_code": last_status_code,
                            "endpoint": str(endpoint or ""),
                            "method": method_upper,
                            "error_body": None,
                            "cancelled": True,
                        }
                        return None
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
                last_error_message = self._format_request_error(e, url)
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
                    "error_message": last_error_message,
                }
                return cached

        self._last_request_info = {
            "ok": False,
            "used_cache": False,
            "status_code": last_status_code,
            "endpoint": str(endpoint or ""),
            "method": method_upper,
            "error_body": None if method_upper == "GET" else self._last_request_info.get("error_body"),
            "error_message": last_error_message,
        }
        if last_error is not None:
            log.debug("Miniflux request failed with no fallback for %s %s", method_upper, url, exc_info=True)
        return None

    def _request_targeted_refresh(
        self,
        feed_id: str,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        fid = str(feed_id or "").strip()
        endpoint = f"/v1/feeds/{fid}/refresh"
        info = {
            "ok": False,
            "used_cache": False,
            "status_code": None,
            "endpoint": endpoint,
            "method": "PUT",
            "error_body": None,
        }
        if not self.base_url or not fid:
            return info
        if self._refresh_cancelled(cancel_event):
            info["cancelled"] = True
            return info
        # The batch breaker may have tripped after this worker was queued but
        # before it started; skipping here is what keeps the remaining requests
        # of a doomed batch off the wire.
        if self._targeted_refresh_route_in_cooldown():
            info["skipped"] = True
            return info

        url = f"{self.base_url}{endpoint}"
        timeout_s = self._request_timeout_seconds(endpoint)
        retries = self._request_retry_attempts(endpoint)
        req_headers = utils.add_revalidation_headers(self.headers)

        for attempt in range(1, retries + 2):
            if self._refresh_cancelled(cancel_event):
                info["cancelled"] = True
                return info
            try:
                resp = self._session.request(
                    "PUT",
                    url,
                    headers=req_headers,
                    timeout=(self.CONNECT_TIMEOUT_SECONDS, timeout_s),
                )
                status_code = int(getattr(resp, "status_code", 0) or 0)
                info["status_code"] = status_code
                if self._is_transient_status(status_code) and attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.debug(
                        "Miniflux transient HTTP %s for PUT %s (attempt %s/%s); retrying in %.1fs",
                        status_code,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    if self._sleep_or_cancel_refresh(delay, cancel_event):
                        info["cancelled"] = True
                        return info
                    continue

                resp.raise_for_status()
                info["ok"] = True
                return info

            except requests.HTTPError as e:
                status_code = None
                try:
                    status_code = int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
                except Exception:
                    status_code = 0
                info["status_code"] = status_code

                if self._is_transient_status(status_code) and attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.debug(
                        "Miniflux transient HTTP %s for PUT %s (attempt %s/%s); retrying in %.1fs",
                        status_code,
                        url,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    if self._sleep_or_cancel_refresh(delay, cancel_event):
                        info["cancelled"] = True
                        return info
                    continue
                log.debug("Miniflux transient HTTP %s for PUT %s: %s", status_code, url, e)
                return info

            except requests.Timeout as e:
                if attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.debug(
                        "Miniflux timeout for PUT %s (timeout=%ss, attempt %s/%s); retrying in %.1fs",
                        url,
                        timeout_s,
                        attempt,
                        retries + 1,
                        delay,
                    )
                    if self._sleep_or_cancel_refresh(delay, cancel_event):
                        info["cancelled"] = True
                        return info
                    continue
                log.debug("Miniflux timeout for %s (timeout=%ss): %s", url, timeout_s, e)
                return info

            except requests.RequestException as e:
                if attempt <= retries:
                    delay = self._retry_backoff_seconds(attempt)
                    log.debug(
                        "Miniflux request error for PUT %s (attempt %s/%s); retrying in %.1fs: %s",
                        url,
                        attempt,
                        retries + 1,
                        delay,
                        e,
                    )
                    if self._sleep_or_cancel_refresh(delay, cancel_event):
                        info["cancelled"] = True
                        return info
                    continue
                log.debug("Miniflux request error for PUT %s: %s", url, e)
                return info

            except Exception as e:
                log.debug("Miniflux request error for PUT %s: %s", url, e)
                return info

        return info

    def _refresh_targeted_feeds(
        self,
        feed_ids,
        *,
        force: bool = False,
        progress_cb=None,
        progress_states: dict[str, dict[str, Any]] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, dict[str, Any]]:
        cancel_event = cancel_event if cancel_event is not None else self._current_refresh_cancel_event()
        ordered_ids = []
        seen = set()
        for raw_id in list(feed_ids or []):
            if self._refresh_cancelled(cancel_event):
                break
            fid = str(raw_id or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            if not self._should_attempt_targeted_refresh(fid, force=force):
                continue
            ordered_ids.append(fid)

        if not ordered_ids:
            return {}

        results: dict[str, dict[str, Any]] = {}
        worker_count = self._targeted_refresh_worker_count(len(ordered_ids))
        batch_5xx_limit = self._targeted_refresh_route_batch_5xx_limit()
        batch_state = {"consecutive_5xx": 0, "route_proven": False}
        batch_lock = threading.Lock()

        def _note_route_health(info: dict[str, Any]) -> None:
            """Trip the route breaker once the server 5xxes the whole batch."""
            if batch_5xx_limit <= 0:
                return
            try:
                status = int(info.get("status_code") or 0)
            except Exception:
                status = 0
            with batch_lock:
                if status >= 500:
                    batch_state["consecutive_5xx"] += 1
                    tripped = batch_state["consecutive_5xx"] >= batch_5xx_limit
                    count = batch_state["consecutive_5xx"]
                else:
                    # Any non-5xx answer proves the route still works.
                    batch_state["consecutive_5xx"] = 0
                    batch_state["route_proven"] = True
                    tripped, count = False, 0
            if tripped:
                self._trip_targeted_refresh_route_breaker(count)

        def _store_result(fid: str, info: dict[str, Any]) -> None:
            info = info or {}
            results[fid] = info
            if info.get("cancelled") or info.get("skipped"):
                return
            _note_route_health(info)
            self._record_targeted_refresh_attempt_result(
                fid,
                bool(info.get("ok", False)),
                info.get("status_code"),
            )
            # Requests already on the wire when the user stopped still land.
            # Their result is recorded, but reporting it would keep the UI's
            # refresh progress moving after the stop.
            if self._refresh_cancelled(cancel_event):
                return
            if progress_cb is not None:
                self._emit_progress(
                    progress_cb,
                    self._targeted_refresh_progress_state(fid, info, progress_states),
                )

        if worker_count <= 1 or len(ordered_ids) == 1:
            for fid in ordered_ids:
                if self._refresh_cancelled(cancel_event):
                    break
                _store_result(fid, self._request_targeted_refresh(fid, cancel_event=cancel_event))
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="miniflux-refresh",
            ) as executor:
                # Probe only up to the breaker threshold initially. Submitting the
                # entire batch at once made the breaker cosmetic: all 15 workers
                # could reach the wire before the third 5xx was observed. Once any
                # non-5xx proves the route works, fill the normal worker window.
                queued_ids = iter(ordered_ids)
                futures: dict[concurrent.futures.Future, str] = {}

                def _fill_window(limit: int) -> None:
                    while len(futures) < limit and not self._refresh_cancelled(cancel_event):
                        if self._targeted_refresh_route_in_cooldown():
                            return
                        try:
                            next_id = next(queued_ids)
                        except StopIteration:
                            return
                        future = executor.submit(
                            self._request_targeted_refresh, next_id, cancel_event
                        )
                        futures[future] = next_id

                probe_window = (
                    min(worker_count, batch_5xx_limit)
                    if batch_5xx_limit > 0
                    else worker_count
                )
                probing = batch_5xx_limit > 0 and worker_count > 1
                _fill_window(max(1, probe_window))
                while futures:
                    done, _pending = concurrent.futures.wait(
                        tuple(futures),
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    if self._refresh_cancelled(cancel_event):
                        for pending in futures:
                            pending.cancel()
                    for future in done:
                        fid = futures.pop(future)
                        _store_result(fid, self._future_result_info(future, fid))
                    if self._targeted_refresh_route_in_cooldown():
                        for pending in futures:
                            pending.cancel()
                    elif probing:
                        # Let the complete initial probe group settle before
                        # submitting anything else. Refilling this window after
                        # each individual completion let feeds 4 and 5 reach the
                        # wire while the third probe was still pending, making
                        # the three-failure breaker leak requests in production.
                        if not futures:
                            probing = False
                            _fill_window(worker_count)
                    else:
                        _fill_window(worker_count)

        return results

    def _refresh_soft_deadline_seconds(self) -> float:
        """Wall-clock budget (seconds) after which a manual refresh reports 'complete'
        and lets any still-running (slow but live) feeds finish in the background.

        0 disables streaming -- the refresh blocks until every targeted feed returns
        (the classic behavior). Default 5s: on a large account the fast majority of
        feeds finish well inside this window, so the user hears 'refresh complete'
        promptly while a couple of genuinely slow feeds keep loading and stream their
        new articles in a few seconds later. No feed is ever cancelled to hit this.
        """
        try:
            val = float(self.config.get("miniflux_refresh_soft_deadline_s", 5) or 0)
        except Exception:
            val = 5.0
        return max(0.0, val)

    @staticmethod
    def _future_result_info(fut, fid: str) -> dict[str, Any]:
        """Extract a targeted-refresh worker result, normalizing cancellation/errors."""
        try:
            return fut.result()
        except concurrent.futures.CancelledError:
            return {
                "ok": False, "used_cache": False, "status_code": None,
                "endpoint": f"/v1/feeds/{fid}/refresh", "method": "PUT",
                "error_body": None, "cancelled": True,
            }
        except Exception as e:
            log.debug("Miniflux targeted refresh worker failed for feed %s: %s", fid, e)
            return {
                "ok": False, "used_cache": False, "status_code": None,
                "endpoint": f"/v1/feeds/{fid}/refresh", "method": "PUT",
                "error_body": None,
            }

    def _run_targeted_with_deadline(
        self,
        feed_ids,
        *,
        force: bool = False,
        progress_cb=None,
        progress_states: dict[str, dict[str, Any]] | None = None,
        cancel_event: threading.Event | None = None,
        soft_deadline_s: float = 5.0,
        finalize_cb=None,
        on_background_done=None,
    ) -> list[str]:
        """Per-feed targeted refresh that RETURNS after ``soft_deadline_s`` and hands any
        still-pending (slow but live) feeds to a background daemon.

        The daemon drains the remaining feeds -- it never cancels them, so no content is
        dropped -- emitting per-feed progress as each finishes, then runs ``finalize_cb``
        (to re-emit fresh unread counts once the slow feeds land) and ``on_background_done``
        (to release the refresh cancel scope). Returns the list of straggler feed ids handed
        off to the background (empty if everything finished within the deadline).
        """
        ordered_ids = []
        seen = set()
        for raw_id in list(feed_ids or []):
            if self._refresh_cancelled(cancel_event):
                break
            fid = str(raw_id or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            if not self._should_attempt_targeted_refresh(fid, force=force):
                continue
            ordered_ids.append(fid)

        if not ordered_ids:
            return []

        worker_count = self._targeted_refresh_worker_count(len(ordered_ids))
        results_lock = threading.Lock()
        results: dict[str, dict[str, Any]] = {}

        def _store(fid: str, info: dict[str, Any]) -> None:
            info = info or {}
            with results_lock:
                results[fid] = info
            if info.get("cancelled"):
                return
            self._record_targeted_refresh_attempt_result(
                fid, bool(info.get("ok", False)), info.get("status_code")
            )
            # See _refresh_targeted_feeds: a stopped refresh records results but
            # reports none, so the UI's progress does not advance after a stop.
            if self._refresh_cancelled(cancel_event):
                return
            if progress_cb is not None:
                self._emit_progress(
                    progress_cb,
                    self._targeted_refresh_progress_state(fid, info, progress_states),
                )

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="miniflux-refresh"
        )
        futures = {
            executor.submit(self._request_targeted_refresh, fid, cancel_event): fid
            for fid in ordered_ids
            if not self._refresh_cancelled(cancel_event)
        }
        pending = set(futures)
        deadline = time.monotonic() + max(0.0, float(soft_deadline_s or 0.0))

        while pending:
            if self._refresh_cancelled(cancel_event):
                for f in pending:
                    f.cancel()
                break
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                break
            done, pending = concurrent.futures.wait(
                pending,
                timeout=remaining_time,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                fid = futures[fut]
                _store(fid, self._future_result_info(fut, fid))

        if not pending:
            executor.shutdown(wait=False)
            return []

        straggler_ids = [futures[f] for f in pending]
        pending_snapshot = set(pending)

        def _drain_stragglers() -> None:
            try:
                for fut in concurrent.futures.as_completed(pending_snapshot):
                    if self._refresh_cancelled(cancel_event):
                        # Stopped: drop the queued stragglers and leave the ones
                        # already on the wire to end on their own. Waiting out
                        # the remaining feed timeouts would hold the refresh
                        # "active" long after the user asked it to stop.
                        for f in pending_snapshot:
                            f.cancel()
                        break
                    fid = futures[fut]
                    _store(fid, self._future_result_info(fut, fid))
            except Exception:
                log.debug("Miniflux straggler drain failed", exc_info=True)
            finally:
                try:
                    if finalize_cb is not None and not self._refresh_cancelled(cancel_event):
                        finalize_cb(straggler_ids)
                except Exception:
                    log.debug("Miniflux straggler finalize failed", exc_info=True)
                executor.shutdown(wait=False)
                try:
                    if on_background_done is not None:
                        on_background_done(straggler_ids)
                except Exception:
                    log.debug("Miniflux straggler completion callback failed", exc_info=True)

        threading.Thread(
            target=_drain_stragglers, name="miniflux-stragglers", daemon=True
        ).start()
        return straggler_ids

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
        chapter_cache_keys = {
            article_id: self._chapter_cache_key(article_id)
            for article_id in article_ids
        }
        chapters_map = utils.get_chapters_batch(
            article_ids,
            cache_keys=chapter_cache_keys,
        )

        articles: List[Article] = []
        for entry in entries:
            if self._is_placeholder_entry(entry):
                continue
            media_url = None
            media_type = None
            entry_url = entry.get("url") or ""
            entry_summary = entry.get("summary") or ""
            entry_content = entry.get("content") or entry_summary or ""
            display_title = utils.enhance_activity_entry_title(entry.get("title") or "", entry_url, entry_content) or "Untitled"

            enclosures = entry.get("enclosures", []) or []
            if enclosures:
                media_url = (enclosures[0] or {}).get("url")
                media_type = (enclosures[0] or {}).get("mime_type")

            date = self._normalize_entry_date(entry, display_title, entry_content, entry_url)

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
                author=utils.normalize_author(entry.get("author")),
                is_read=(entry.get("status") == "read"),
                is_favorite=entry.get("starred", False),
                media_url=media_url,
                media_type=media_type,
                chapters=chapters,
                cache_id=cache_id,
                description=entry_summary or None,
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

    def _parse_miniflux_server_date(self, value: str | None, *, allow_near_future: bool = False):
        if not value:
            return None
        try:
            dt = dateparser.parse(str(value), tzinfos=utils.TZINFOS)
        except Exception:
            dt = None
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        if dt.year < 1990:
            return None
        future_limit = timedelta(days=14 if allow_near_future else 2)
        if (dt - datetime.now(timezone.utc)) > future_limit:
            return None
        return dt

    def _normalize_entry_date(self, entry: Dict[str, Any], title: str, content: str, url: str) -> str:
        raw_date = entry.get("published_at") or entry.get("published")
        date = utils.normalize_date(raw_date, title, content, url)
        if date and not str(date).startswith("0001-01-01"):
            return date

        # Miniflux may preserve a server-side ordering date that is slightly in the
        # future. Keep plausible near-future dates so BlindRSS sorting matches the
        # Miniflux web UI instead of demoting the entry to the sentinel timestamp.
        for field, allow_near_future in (
            ("published_at", True),
            ("published", True),
            ("created_at", False),
            ("changed_at", False),
        ):
            dt = self._parse_miniflux_server_date(entry.get(field), allow_near_future=allow_near_future)
            if dt:
                return utils.format_datetime(dt)

        return date

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

    def refresh(self, progress_cb=None, force: bool = False, scheduled: bool = False) -> bool:
        started_at = datetime.now(timezone.utc)
        cancel_event = self._begin_refresh_cancel_scope()
        # When a manual refresh reports "complete" while slow feeds keep loading, the
        # background straggler daemon keeps the cancel scope alive, so a user "stop"
        # still cancels those stragglers. Both this call and that daemon have to be
        # finished before the scope goes away: whichever ends last releases it.
        # Releasing on the daemon alone let it end the scope while this body was
        # still emitting progress, and Stop Refresh then had nothing to cancel.
        scope_lock = threading.Lock()
        scope_state = {"main_done": False, "background_pending": False, "released": False}

        def _release_scope_when_idle() -> None:
            with scope_lock:
                if scope_state["released"]:
                    return
                if not scope_state["main_done"] or scope_state["background_pending"]:
                    return
                scope_state["released"] = True
            self._end_refresh_cancel_scope(cancel_event)

        def _stopped(feeds_count: int = 0) -> bool:
            duration_s = (datetime.now(timezone.utc) - started_at).total_seconds()
            log.info(
                "Miniflux refresh stopped by user force=%s duration_s=%.2f feeds=%s",
                force,
                duration_s,
                feeds_count,
            )
            return True

        try:
            log.info("Miniflux refresh start force=%s", force)
            # A manual (force) refresh synchronously re-fetches *every* feed below
            # via per-feed PUT .../refresh. The global background refresh would then
            # just make the server compete with itself for the same upstream
            # bandwidth, so skip it on force and let the targeted pass do the work.
            # Scheduled (non-force) refreshes still kick off the cheap global
            # background refresh and only retry stale/errored feeds individually.
            if force:
                global_refresh_ok = True
            elif scheduled:
                # Miniflux already owns feed polling on its server-side
                # scheduler.  A short BlindRSS UI interval should poll the
                # resulting metadata, not repeatedly enqueue all feeds on the
                # server (which becomes very expensive for large accounts).
                global_refresh_ok = True
                log.info("Miniflux scheduled refresh using server poller; global trigger skipped")
            else:
                # Kick off a global refresh on the Miniflux server.
                self._req("PUT", "/v1/feeds/refresh")
                if self._refresh_cancelled(cancel_event):
                    return _stopped()
                refresh_info = dict(getattr(self, "_last_request_info", {}) or {})
                global_refresh_ok = True
                if (
                    str(refresh_info.get("endpoint", "")) == "/v1/feeds/refresh"
                    and str(refresh_info.get("method", "")).upper() == "PUT"
                ):
                    global_refresh_ok = bool(refresh_info.get("ok", False))
                log.info(
                    "Miniflux global refresh request force=%s ok=%s status=%s error=%r",
                    force,
                    global_refresh_ok,
                    refresh_info.get("status_code"),
                    refresh_info.get("error_body"),
                )

            # After triggering, fetch feed metadata so we can surface stale/error
            # feeds in the UI and optionally retry them individually.
            feeds = self._req("GET", "/v1/feeds") or []
            if self._refresh_cancelled(cancel_event):
                return _stopped(len(feeds or []))
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
            chronic_skipped = 0
            force_skip_threshold = self._force_skip_error_count()

            for feed in feeds:
                if self._refresh_cancelled(cancel_event):
                    return _stopped(len(feeds or []))
                feed_id = str(feed.get("id"))
                status = "ok"

                checked_dt = self._parse_checked_at(feed.get("checked_at"))

                try:
                    parse_errors = int(feed.get("parsing_error_count") or 0)
                except Exception:
                    parse_errors = 0
                if parse_errors > 0:
                    status = "error"
                elif checked_dt and checked_dt < stale_cutoff:
                    status = "stale"

                # Manual refresh in BlindRSS sets force=True. Respect it by explicitly
                # refreshing every feed so CDN-cached feeds (e.g., Simplecast) update
                # immediately instead of waiting for Miniflux's next scheduled check.
                # BUT skip a feed the server has failed to parse repeatedly: a
                # synchronous retry won't fix a chronically-broken feed and it holds a
                # worker for the full timeout, dragging out the background straggler
                # drain (a dead feed can hang the full 18s every refresh). The server's
                # own poller keeps retrying it; the client failure-backoff (checked in
                # _should_attempt_targeted_refresh) catches feeds that fail our own
                # targeted refresh repeatedly within a session.
                if force:
                    if force_skip_threshold > 0 and parse_errors >= force_skip_threshold:
                        chronic_skipped += 1
                        continue
                    per_feed_retry_ids.append(feed_id)
                elif status in ("error", "stale"):
                    per_feed_retry_ids.append(feed_id)

            # Retrying stale/errored feeds individually stays the designed behavior;
            # what the field log exposed is that nothing stopped a batch once the
            # server started answering 5xx for every one of them. That is the route
            # breaker's job (see _trip_targeted_refresh_route_breaker), so here we
            # only add its cooldown to the existing preconditions.
            route_parked = self._targeted_refresh_route_in_cooldown()
            allow_targeted_refresh = bool(
                global_refresh_ok
                and (not feeds_from_cache)
                and not scheduled
                and not route_parked
            )
            if scheduled:
                targeted_skip_reason = "server poller owns scheduled refreshes"
            elif route_parked:
                targeted_skip_reason = "per-feed refresh route is in cooldown"
            elif feeds_from_cache:
                targeted_skip_reason = "feed list came from cache"
            elif not global_refresh_ok:
                targeted_skip_reason = "global refresh was rejected"
            else:
                targeted_skip_reason = ""
            log.info(
                "Miniflux refresh feed metadata force=%s feeds=%s feeds_from_cache=%s targeted_candidates=%s chronic_skipped=%s retry_budget=%s allow_targeted=%s",
                force,
                len(feeds or []),
                feeds_from_cache,
                len(per_feed_retry_ids),
                chronic_skipped,
                retry_budget,
                allow_targeted_refresh,
            )
            if not allow_targeted_refresh and per_feed_retry_ids:
                log.info(
                    "Skipping %s Miniflux per-feed refresh retries: %s.",
                    len(per_feed_retry_ids),
                    targeted_skip_reason or "not applicable this cycle",
                )

            if retry_budget > 0 and allow_targeted_refresh:
                progress_states = None
                if progress_cb is not None and per_feed_retry_ids:
                    counters_for_progress = self._req("GET", "/v1/feeds/counters") or {}
                    if self._refresh_cancelled(cancel_event):
                        return _stopped(len(feeds or []))
                    unread_for_progress = (
                        counters_for_progress.get("unreads", {})
                        if isinstance(counters_for_progress, dict)
                        else {}
                    )
                    progress_states = {
                        str(feed.get("id") or ""): self._feed_progress_state_from_metadata(
                            feed,
                            unread_for_progress,
                            stale_cutoff,
                        )
                        for feed in feeds or []
                    }

                targeted_ids = per_feed_retry_ids[:retry_budget]
                # A manual refresh streams: report "complete" once the fast majority
                # of feeds are in, and let the slow-but-live stragglers finish in the
                # background (they are never cancelled). Scheduled refreshes, tiny
                # accounts, and the single-worker path keep the classic blocking flow.
                soft_deadline_s = self._refresh_soft_deadline_seconds() if force else 0.0
                use_streaming = (
                    soft_deadline_s > 0
                    and len(targeted_ids) >= 3
                    and self._targeted_refresh_worker_count(len(targeted_ids)) > 1
                )

                if use_streaming:
                    def _straggler_finalize(straggler_ids):
                        # Once the slow feeds land, re-emit their fresh unread counts so
                        # their new articles/counts appear a few seconds after "complete".
                        if self._refresh_cancelled(cancel_event):
                            return
                        feeds2 = self._req("GET", "/v1/feeds") or []
                        counters2 = self._req("GET", "/v1/feeds/counters") or {}
                        unread2 = counters2.get("unreads", {}) if isinstance(counters2, dict) else {}
                        by_id2 = {str(f.get("id") or ""): f for f in feeds2}
                        for sid in straggler_ids:
                            feed2 = by_id2.get(str(sid))
                            if feed2 is None:
                                continue
                            self._emit_progress(
                                progress_cb,
                                self._feed_progress_state_from_metadata(feed2, unread2, stale_cutoff),
                            )

                    def _straggler_done(straggler_ids):
                        total_dur = (datetime.now(timezone.utc) - started_at).total_seconds()
                        log.info(
                            "Miniflux refresh stragglers finished force=%s stragglers=%s total_duration_s=%.2f",
                            force, len(straggler_ids or []), total_dur,
                        )
                        with scope_lock:
                            scope_state["background_pending"] = False
                        _release_scope_when_idle()

                    # Claimed before the call: the daemon can finish (and call
                    # _straggler_done) before _run_targeted_with_deadline returns.
                    with scope_lock:
                        scope_state["background_pending"] = True
                    straggler_ids = self._run_targeted_with_deadline(
                        targeted_ids,
                        force=force,
                        progress_cb=progress_cb,
                        progress_states=progress_states,
                        cancel_event=cancel_event,
                        soft_deadline_s=soft_deadline_s,
                        finalize_cb=_straggler_finalize,
                        on_background_done=_straggler_done,
                    )
                    if straggler_ids:
                        log.info(
                            "Miniflux refresh reporting complete with %s straggler feed(s) finishing in background force=%s",
                            len(straggler_ids), force,
                        )
                    else:
                        # Nothing was handed off, so no daemon will ever release
                        # the claim made above.
                        with scope_lock:
                            scope_state["background_pending"] = False
                else:
                    self._refresh_targeted_feeds(
                        targeted_ids,
                        force=force,
                        progress_cb=progress_cb,
                        progress_states=progress_states,
                        cancel_event=cancel_event,
                    )
                    if self._refresh_cancelled(cancel_event):
                        return _stopped(len(feeds or []))

            # A scheduled UI poll has not changed server state, so reuse the
            # metadata already fetched above instead of downloading and
            # decoding thousands of feeds twice every interval.  Startup and
            # manual refreshes retain the second read because they may have
            # issued refresh requests immediately above.
            if not scheduled:
                feeds = self._req("GET", "/v1/feeds") or feeds
            if self._refresh_cancelled(cancel_event):
                return _stopped(len(feeds or []))
            counters_data = self._req("GET", "/v1/feeds/counters") or {}
            if self._refresh_cancelled(cancel_event):
                return _stopped(len(feeds or []))
            unread_map = counters_data.get("unreads", {}) if isinstance(counters_data, dict) else {}

            for feed in feeds:
                if self._refresh_cancelled(cancel_event):
                    return _stopped(len(feeds or []))
                self._emit_progress(
                    progress_cb,
                    self._feed_progress_state_from_metadata(feed, unread_map, stale_cutoff),
                )

            duration_s = (datetime.now(timezone.utc) - started_at).total_seconds()
            with scope_lock:
                stragglers_bg = scope_state["background_pending"]
            log.info(
                "Miniflux refresh finished force=%s duration_s=%.2f feeds=%s stragglers_bg=%s",
                force, duration_s, len(feeds or []), stragglers_bg,
            )
            # The companion filters this list server-side and queues work only
            # for feeds whose latest Miniflux error indicates a browser gate.
            # The request returns immediately; Chrome never extends refresh UI
            # latency for accounts that have one protected subscription.
            self._queue_browser_feed_recovery()
            return True
        finally:
            # Whichever of this call and the straggler daemon finishes last
            # releases the cancel scope. Releasing it while the other is still
            # working would let a "stop" silently no-op against live work.
            with scope_lock:
                scope_state["main_done"] = True
            _release_scope_when_idle()

    def refresh_feed(self, feed_id: str, progress_cb=None) -> bool:
        """Refresh a single Miniflux feed and emit one progress state for the UI."""
        fid = str(feed_id or "").strip()
        if not fid:
            return False
        cancel_event = self._begin_refresh_cancel_scope()
        log.info("Miniflux single-feed refresh start feed_id=%s force=True", fid)
        try:
            if self._refresh_cancelled(cancel_event):
                return True

            # Trigger a targeted refresh on the Miniflux server.
            results = self._refresh_targeted_feeds([fid], force=True, cancel_event=cancel_event)
            if fid in results:
                self._last_request_info = dict(results[fid])
            if self._refresh_cancelled(cancel_event):
                log.info("Miniflux single-feed refresh stopped by user feed_id=%s", fid)
                return True

            # Whether the refresh call succeeded or timed out, try to fetch the latest metadata
            # so the UI can stop showing "Adding feed..." and display current state.
            feeds = self._req("GET", "/v1/feeds") or []
            if self._refresh_cancelled(cancel_event):
                log.info("Miniflux single-feed refresh stopped by user feed_id=%s", fid)
                return True
            counters_data = self._req("GET", "/v1/feeds/counters") or {}
            if self._refresh_cancelled(cancel_event):
                log.info("Miniflux single-feed refresh stopped by user feed_id=%s", fid)
                return True
            unread_map = counters_data.get("unreads", {}) if isinstance(counters_data, dict) else {}

            target = None
            for feed in (feeds or []):
                if self._refresh_cancelled(cancel_event):
                    log.info("Miniflux single-feed refresh stopped by user feed_id=%s", fid)
                    return True
                if str(feed.get("id") or "") == fid:
                    target = feed
                    break

            if target is None:
                log.info("Miniflux single-feed refresh feed not found feed_id=%s", fid)
                return False

            now = datetime.now(timezone.utc)
            stale_cutoff = now - timedelta(hours=3)
            checked_dt = self._parse_checked_at(target.get("checked_at"))

            status = "ok"
            error_msg = None
            if (target.get("parsing_error_count") or 0) > 0:
                status = "error"
                error_msg = target.get("parsing_error_message")
                if self._looks_like_browser_challenge_error(error_msg):
                    self._queue_browser_feed_recovery([fid])
            elif checked_dt and checked_dt < stale_cutoff:
                status = "stale"

            unread = unread_map.get(fid) or unread_map.get(int(target.get("id", 0) or 0), 0) or 0
            category = (target.get("category") or {}).get("title", UNCATEGORIZED)

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
            log.info("Miniflux single-feed refresh finished feed_id=%s status=%s unread=%s", fid, status, unread)
            return True
        finally:
            self._end_refresh_cancel_scope(cancel_event)

    def refresh_feeds_by_ids(self, feed_ids, progress_cb=None, force: bool = True) -> bool:
        ordered_ids = []
        seen = set()
        for raw_id in list(feed_ids or []):
            fid = str(raw_id or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            ordered_ids.append(fid)

        if not ordered_ids:
            return True
        cancel_event = self._begin_refresh_cancel_scope()
        log.info("Miniflux targeted refresh start feed_count=%s force=%s", len(ordered_ids), force)
        try:
            if self._refresh_cancelled(cancel_event):
                return True

            results = self._refresh_targeted_feeds(ordered_ids, force=force, cancel_event=cancel_event)
            ok = all(bool(info.get("ok", False)) for info in results.values()) if results else True
            if self._refresh_cancelled(cancel_event):
                log.info("Miniflux targeted refresh stopped by user feed_count=%s", len(ordered_ids))
                return True

            feeds = self._req("GET", "/v1/feeds") or []
            if self._refresh_cancelled(cancel_event):
                log.info("Miniflux targeted refresh stopped by user feed_count=%s", len(ordered_ids))
                return True
            counters_data = self._req("GET", "/v1/feeds/counters") or {}
            if self._refresh_cancelled(cancel_event):
                log.info("Miniflux targeted refresh stopped by user feed_count=%s", len(ordered_ids))
                return True
            unread_map = counters_data.get("unreads", {}) if isinstance(counters_data, dict) else {}

            feeds_by_id = {str(feed.get("id") or ""): feed for feed in feeds or []}
            stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
            for fid in ordered_ids:
                if self._refresh_cancelled(cancel_event):
                    log.info("Miniflux targeted refresh stopped by user feed_count=%s", len(ordered_ids))
                    return True
                feed = feeds_by_id.get(fid)
                if feed is None:
                    self._emit_progress(
                        progress_cb,
                        {
                            "id": fid,
                            "title": fid,
                            "category": UNCATEGORIZED,
                            "unread_count": 0,
                            "status": "error",
                            "new_items": None,
                            "error": "Feed not found after refresh.",
                        },
                    )
                    ok = False
                    continue

                checked_dt = self._parse_checked_at(feed.get("checked_at"))
                status = "ok"
                error_msg = None
                if (feed.get("parsing_error_count") or 0) > 0:
                    status = "error"
                    error_msg = feed.get("parsing_error_message")
                elif checked_dt and checked_dt < stale_cutoff:
                    status = "stale"

                unread = unread_map.get(fid) or unread_map.get(int(feed.get("id", 0) or 0), 0) or 0
                category = (feed.get("category") or {}).get("title", UNCATEGORIZED)
                self._emit_progress(
                    progress_cb,
                    {
                        "id": fid,
                        "title": feed.get("title") or "",
                        "category": category,
                        "unread_count": unread,
                        "status": status,
                        "new_items": None,
                        "error": error_msg,
                    },
                )
            log.info("Miniflux targeted refresh finished feed_count=%s force=%s ok=%s", len(ordered_ids), force, ok)
            return ok
        finally:
            self._end_refresh_cancel_scope(cancel_event)

    def get_feeds(self) -> List[Feed]:
        data = self._req("GET", "/v1/feeds")
        if not data:
            return []
        
        counters_data = self._req("GET", "/v1/feeds/counters")
        counts = {}
        if counters_data:
            # "unreads" may be present-but-null on some server responses.
            counts = counters_data.get("unreads") or {}

        feeds = []
        for f in data:
            # category/icon may be present with a null value, so `or {}` is
            # needed -- a plain default only applies when the key is absent.
            cat = (f.get("category") or {}).get("title", UNCATEGORIZED)
            fid = str(f.get("id", ""))
            feed = Feed(
                id=fid,
                title=f.get("title") or "",
                url=f.get("site_url") or "",
                category=cat,
                icon_url=(f.get("icon") or {}).get("data", "")
            )
            feed.unread_count = counts.get(fid, 0) or counts.get(f.get("id"), 0) or 0
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
        cache_key = self._chapter_cache_key(article_id)
        cached_source_url = utils.get_chapter_source_url(article_id, cache_key=cache_key)

        # Entry IDs are local to a Miniflux instance, and podcast metadata can be
        # corrected after an entry was first cached. Re-read the current entry
        # before choosing a source so a replaced chapter URL is discovered.
        entry = self._req("GET", f"/v1/entries/{article_id}")
        if entry:
            chapter_url, media_url, media_type = utils.chapter_source_and_media(entry)
            chapters = utils.fetch_and_store_chapters(
                article_id,
                media_url,
                media_type,
                chapter_url=chapter_url,
                cache_key=cache_key,
            )
            if chapters:
                return chapters
            if chapter_url:
                return utils.get_chapters_from_db(article_id, cache_key=cache_key)

        if cached_source_url:
            chapters = utils.fetch_and_store_chapters(
                article_id,
                None,
                None,
                chapter_url=cached_source_url,
                cache_key=cache_key,
            )
            if chapters:
                return chapters
        return utils.get_chapters_from_db(article_id, cache_key=cache_key)


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

    def supports_article_delete(self) -> bool:
        return True

    def delete_article(self, article_id: str) -> bool:
        return self._set_entries_status([article_id], "removed")

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
                resp = self._session.put(
                    f"{self.base_url}/v1/categories/{cid}/mark-all-as-read",
                    headers=self.headers,
                    timeout=(self.CONNECT_TIMEOUT_SECONDS, 15),
                )
                return resp.status_code in (200, 204)

            if real_feed_id == "all":
                return False

            resp = self._session.put(
                f"{self.base_url}/v1/feeds/{real_feed_id}/mark-all-as-read",
                headers=self.headers,
                timeout=(self.CONNECT_TIMEOUT_SECONDS, 15),
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
        if status not in ("read", "unread", "removed"):
            return False

        # Miniflux supports batching status changes via PUT /v1/entries.
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
                resp = self._session.put(
                    f"{self.base_url}/v1/entries",
                    headers=self.headers,
                    json={"entry_ids": chunk, "status": status},
                    timeout=(self.CONNECT_TIMEOUT_SECONDS, 15),
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

    def add_feed(self, url: str, category: str = UNCATEGORIZED) -> bool:
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
        url = utils.normalize_user_submitted_url(url)
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
            found = False
            for c in cats:
                if c["title"].lower() == category.lower():
                    category_id = c["id"]
                    found = True
                    break
            if not found:
                # Create the requested category rather than silently filing the
                # feed under whatever category happens to be first (update_feed
                # already does this).
                created = self._req("POST", "/v1/categories", json={"title": category})
                if isinstance(created, dict) and created.get("id") is not None:
                    category_id = created.get("id")
        
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

        # A self-hosted Miniflux server may be blocked by a JavaScript/browser
        # verification page even though BlindRSS can reach the feed locally.
        # Ask the optional same-origin companion to solve the challenge from the
        # server's IP, store the clearance cookie in Miniflux, and create the
        # original feed URL through the normal Miniflux API.
        browser_result = self._browser_feed_fallback_request(
            "add",
            {"feed_url": real_url, "category_id": category_id},
            wait=True,
        )
        if isinstance(browser_result, dict) and browser_result.get("feed_id") is not None:
            feed_id = str(browser_result.get("feed_id") or "").strip() or None
            self._last_add_feed_result = {
                "ok": True,
                "duplicate": bool(browser_result.get("duplicate", False)),
                "feed_id": feed_id,
                "feed_url": real_url,
            }
            log.info(
                "Miniflux browser-feed fallback added protected feed id=%s url=%s",
                feed_id,
                real_url,
            )
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
        """Submit the complete OPML document through Miniflux's bulk endpoint.

        The old base implementation called POST /v1/feeds once per outline and
        could take many minutes for a YouTube Takeout containing thousands of
        channels. Miniflux has supported POST /v1/import since v2.0.7.
        """
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            body = root.find("body")
            if body is None:
                body = root.find("./body")
            category = str(target_category or "").strip()
            if body is None:
                raise ValueError("OPML body is missing")
            if category:
                children = list(body)
                for child in children:
                    body.remove(child)
                folder = ET.SubElement(body, "outline", text=category, title=category)
                folder.extend(children)
            opml_data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        except Exception:
            log.exception("Could not prepare OPML for Miniflux bulk import: %s", path)
            return False

        result = self._req(
            "POST",
            "/v1/import",
            data=opml_data,
            extra_headers={"Content-Type": "application/xml; charset=utf-8"},
        )
        if bool((getattr(self, "_last_request_info", {}) or {}).get("ok")):
            self._cached_get_responses.clear()
            self._category_cache.clear()
            log.info("Miniflux OPML bulk import accepted bytes=%s category=%s", len(opml_data), category)
            return True

        status = int((getattr(self, "_last_request_info", {}) or {}).get("status_code") or 0)
        if status in (404, 405):
            log.warning("Miniflux OPML endpoint unavailable (HTTP %s); using compatibility import", status)
            return super().import_opml(path, target_category)
        return result is not None

    def get_categories(self) -> List[str]:
        data = self._req("GET", "/v1/categories")
        if not data:
            return []
        return [c["title"] for c in data]

    def uncategorized_is_real_category(self) -> bool:
        # Miniflux gives every feed a category, so "no category" is a real,
        # server-managed category named "Uncategorized" -- deletable and
        # renamable like any other (issue #86). See RSSProvider for the contrast.
        return True

    def add_category(self, title: str, parent_title: str = None) -> bool:
        # Miniflux categories are flat; ignore parent_title (do not simulate nesting).
        return self._req("POST", "/v1/categories", json={"title": title}) is not None

    def rename_category(self, old_title: str, new_title: str) -> bool:
        data = self._req("GET", "/v1/categories")
        if not data:
            return False
        
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
        if not data:
            return False

        cat_id = None
        for c in data:
            if c["title"] == title:
                cat_id = c["id"]
                break

        if cat_id:
            # A successful DELETE is 204 (no body), which _req also returns as
            # None -- so the return value alone can't tell success from failure.
            # Miniflux refuses to delete a category that still has feeds (HTTP
            # 400), and returning True there made BlindRSS report a phantom
            # success and silently leave the category in place. Check the
            # request outcome instead.
            self._req("DELETE", f"/v1/categories/{cat_id}")
            return bool((self._last_request_info or {}).get("ok"))
        return False

    def fetch_full_content(self, article_id: str, url: str = ""):
        """Return raw HTML from Miniflux's server-side fetch-content scraper.

        Behavior:
        - The Miniflux API exposes this as GET /v1/entries/{id}/fetch-content. (The old PUT
          form is rejected with 405 Method Not Allowed on current Miniflux, which silently
          broke this fallback — so we use GET and only fall back to PUT if a build returns
          405 for GET.)
        - Swallows 404 (entry not found/expired) quietly to avoid noisy logs.
        - Returns the article's content on success, otherwise None.
        """
        if not article_id:
            return None

        try:
            # Some instances require numeric IDs; coerce when possible.
            aid = int(str(article_id))
        except Exception:
            aid = article_id

        endpoint = f"{self.base_url}/v1/entries/{aid}/fetch-content"
        for method in ("GET", "PUT"):
            try:
                resp = self._session.request(
                    method,
                    endpoint,
                    headers=self.headers,
                    timeout=(self.CONNECT_TIMEOUT_SECONDS, 15),
                )

                if resp.status_code == 404:
                    return None
                if resp.status_code == 405:
                    # Method not supported by this build; try the other verb.
                    continue
                if resp.status_code >= 500:
                    # Miniflux couldn't scrape the target (paywall/anti-bot/timeout). Expected
                    # for some sites; degrade quietly to client-side extraction.
                    log.debug(f"Miniflux fetch-content {resp.status_code} for {article_id}")
                    return None

                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    content = data.get("content")
                    if content:
                        return content
                return None
            except requests.HTTPError as e:
                code = getattr(e.response, "status_code", None)
                if code == 405:
                    continue
                if code and (code == 404 or code >= 500):
                    return None
                if code:
                    log.error(f"Miniflux fetch-content HTTP error for {article_id}: {e}")
                return None
            except Exception as e:
                log.error(f"Miniflux fetch-content error for {article_id}: {e}")
                return None
        return None

    def _emit_progress(self, progress_cb, state):
        if progress_cb is None:
            return
        try:
            progress_cb(state)
        except Exception as e:
            log.error(f"Miniflux progress callback failed: {e}")
