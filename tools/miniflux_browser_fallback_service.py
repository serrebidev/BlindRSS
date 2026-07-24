# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Direct-browser fallback companion for self-hosted Miniflux.

This optional localhost service keeps Miniflux as the authoritative provider.
It does not proxy or mirror feeds.  A valid Miniflux API token may ask it to:

* create a feed that Miniflux could not fetch because of a browser challenge;
* renew browser clearance for existing feeds whose latest parsing error is a
  challenge/403, then trigger Miniflux's ordinary direct refresh.

The hidden Chrome session runs from the Miniflux host's own IP.  Only its
matching User-Agent and current-domain cookies are stored in Miniflux.  Feed
bodies are validated and discarded after the direct HTTP request succeeds.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from bs4 import BeautifulSoup


LOG = logging.getLogger("blindrss.miniflux_browser_fallback")
LISTEN_HOST = os.environ.get("BLINDRSS_BROWSER_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("BLINDRSS_BROWSER_LISTEN_PORT", "12794"))
MINIFLUX_URL = os.environ.get("BLINDRSS_MINIFLUX_URL", "http://127.0.0.1:12793").rstrip("/")
PROFILE_DIR = os.environ.get(
    "BLINDRSS_BROWSER_PROFILE_DIR",
    "/var/lib/blindrss-miniflux-browser/profile",
)
RUNTIME_DIR = os.environ.get(
    "BLINDRSS_BROWSER_RUNTIME_DIR",
    "/var/lib/blindrss-miniflux-browser/runtime",
)
BROWSER_TIMEOUT = max(
    30.0,
    min(float(os.environ.get("BLINDRSS_BROWSER_TIMEOUT", "90")), 180.0),
)
MAX_BODY_BYTES = 64 * 1024

_BROWSER_LOCK = threading.Lock()
_RECOVERY_LOCK = threading.Lock()


def _local_name(tag) -> str:
    value = str(tag or "")
    if "}" in value:
        value = value.rsplit("}", 1)[-1]
    if ":" in value:
        value = value.rsplit(":", 1)[-1]
    return value.casefold()


def looks_like_feed(text: str) -> bool:
    body = str(text or "").lstrip("\ufeff\x00 \t\r\n")
    if not body:
        return False
    if body.startswith("{"):
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return False
        return bool(
            isinstance(payload, dict)
            and str(payload.get("version") or "").startswith(
                "https://jsonfeed.org/version/"
            )
            and isinstance(payload.get("items", []), list)
        )
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        return False
    return _local_name(root.tag) in {"rss", "rdf", "feed", "channel"}


def feed_text_from_page_source(page_source: str) -> str | None:
    """Return raw feed text, including Chromium's escaped ``pre`` display."""
    source = str(page_source or "")
    if looks_like_feed(source):
        return source
    try:
        pre = BeautifulSoup(source, "html.parser").find("pre")
        candidate = pre.get_text() if pre is not None else ""
    except Exception:
        return None
    return candidate if looks_like_feed(candidate) else None


def looks_like_challenge_error(value) -> bool:
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


def validate_public_http_url(value: str) -> str:
    target = str(value or "").strip()
    parts = urllib.parse.urlsplit(target)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only absolute HTTP/HTTPS feed URLs are allowed")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parts.hostname,
                parts.port or (443 if parts.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise ValueError("The feed host could not be resolved") from exc
    if not addresses:
        raise ValueError("The feed host did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private, local, and reserved feed addresses are blocked")
    return target


def _miniflux_request(token: str, method: str, endpoint: str, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.update({"X-Auth-Token": token, "Accept": "application/json"})
    return requests.request(
        method,
        f"{MINIFLUX_URL}{endpoint}",
        headers=headers,
        timeout=(3, 30),
        **kwargs,
    )


def valid_miniflux_token(token: str) -> bool:
    if not token:
        return False
    try:
        return _miniflux_request(token, "GET", "/v1/me").status_code == 200
    except requests.RequestException:
        return False


def _cookie_header(cookies) -> str:
    values = []
    seen = set()
    for cookie in cookies or []:
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        if name and name not in seen and "\r" not in value and "\n" not in value:
            seen.add(name)
            values.append(f"{name}={value}")
    return "; ".join(values)


def _prepare_seleniumbase_runtime() -> None:
    """Keep driver downloads and process-global locks in writable state."""
    from seleniumbase.core import browser_launcher
    from seleniumbase.fixtures import constants as sb_constants

    work_dir = os.path.join(RUNTIME_DIR, "work")
    os.makedirs(work_dir, mode=0o700, exist_ok=True)
    browser_launcher.override_driver_dir(RUNTIME_DIR)
    sb_constants.Files.DOWNLOADS_FOLDER = work_dir
    for group_name in ("MultiBrowser", "PipInstall", "Dashboard", "Report"):
        group = getattr(sb_constants, group_name, None)
        if group is None:
            continue
        for name, value in vars(group).items():
            if name.isupper() and isinstance(value, str) and value.endswith(".lock"):
                setattr(group, name, os.path.join(work_dir, os.path.basename(value)))


def browser_clearance(url: str) -> tuple[str, str]:
    """Return a validated direct-fetch cookie header and matching User-Agent."""
    from seleniumbase import SB

    target = validate_public_http_url(url)
    os.makedirs(PROFILE_DIR, mode=0o700, exist_ok=True)
    _prepare_seleniumbase_runtime()
    with _BROWSER_LOCK:
        with SB(
            uc=True,
            headless2=True,
            test=False,
            locale="en",
            user_data_dir=PROFILE_DIR,
            no_screenshot=True,
            time_limit=BROWSER_TIMEOUT,
        ) as browser:
            browser.activate_cdp_mode(target)
            source = ""
            feed_text = None
            for attempt in range(5):
                browser.sleep(3 if attempt == 0 else 5)
                source = str(browser.get_page_source() or "")
                feed_text = feed_text_from_page_source(source)
                if feed_text is not None:
                    break
                browser.solve_captcha()
            browser_cookies = browser.get_cookies() or []
            cookie = _cookie_header(browser_cookies)
            user_agent = str(browser.get_user_agent() or "").strip()
            if feed_text is None:
                LOG.info(
                    "Browser source was not directly parseable; validating clearance cookies names=%s",
                    [str(value.get("name") or "") for value in browser_cookies],
                )

    if not cookie or not user_agent:
        raise RuntimeError("The browser did not return reusable clearance credentials")
    direct = requests.get(
        target,
        headers={"User-Agent": user_agent, "Cookie": cookie},
        timeout=(5, 30),
    )
    if direct.status_code != 200 or not looks_like_feed(direct.text):
        raise RuntimeError(
            f"Direct feed validation failed after browser clearance (HTTP {direct.status_code})"
        )
    return cookie, user_agent


def _json_or_empty(response) -> dict:
    try:
        value = response.json()
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def add_protected_feed(token: str, feed_url: str, category_id) -> dict:
    target = validate_public_http_url(feed_url)
    cookie, user_agent = browser_clearance(target)
    payload = {
        "feed_url": target,
        "category_id": int(category_id),
        "cookie": cookie,
        "user_agent": user_agent,
        "ignore_http_cache": True,
    }
    response = _miniflux_request(token, "POST", "/v1/feeds", json=payload)
    if response.status_code in (200, 201):
        result = _json_or_empty(response)
        if result.get("feed_id") is not None:
            return {
                "feed_id": result.get("feed_id"),
                "duplicate": False,
            }

    # Miniflux reports an existing feed as 400. Return it as success so a
    # failed first attempt can be repaired without deleting the subscription.
    feeds_response = _miniflux_request(token, "GET", "/v1/feeds")
    if feeds_response.status_code == 200:
        for feed in feeds_response.json() or []:
            if target in (
                str(feed.get("feed_url") or "").strip(),
                str(feed.get("site_url") or "").strip(),
            ):
                feed_id = feed.get("id")
                update = _miniflux_request(
                    token,
                    "PUT",
                    f"/v1/feeds/{feed_id}",
                    json={
                        "cookie": cookie,
                        "user_agent": user_agent,
                        "ignore_http_cache": True,
                    },
                )
                if update.status_code in (200, 201, 204):
                    _miniflux_request(token, "PUT", f"/v1/feeds/{feed_id}/refresh")
                    return {"feed_id": feed_id, "duplicate": True}

    message = _json_or_empty(response).get("error_message") or f"HTTP {response.status_code}"
    raise RuntimeError(f"Miniflux rejected the browser-cleared feed: {message}")


def recover_failed_feeds(token: str, feed_ids=None) -> int:
    response = _miniflux_request(token, "GET", "/v1/feeds")
    response.raise_for_status()
    requested = {str(value) for value in (feed_ids or []) if str(value).strip()}
    recovered = 0
    for feed in response.json() or []:
        feed_id = str(feed.get("id") or "").strip()
        if requested and feed_id not in requested:
            continue
        if not requested and not looks_like_challenge_error(
            feed.get("parsing_error_message")
        ):
            continue
        target = str(feed.get("feed_url") or "").strip()
        try:
            cookie, user_agent = browser_clearance(target)
            update = _miniflux_request(
                token,
                "PUT",
                f"/v1/feeds/{feed_id}",
                json={
                    "cookie": cookie,
                    "user_agent": user_agent,
                    "ignore_http_cache": True,
                },
            )
            update.raise_for_status()
            refresh = _miniflux_request(
                token,
                "PUT",
                f"/v1/feeds/{feed_id}/refresh",
            )
            refresh.raise_for_status()
            recovered += 1
        except Exception:
            LOG.exception("Could not recover protected Miniflux feed id=%s url=%s", feed_id, target)
    return recovered


def _background_recovery(token: str, feed_ids) -> None:
    if not _RECOVERY_LOCK.acquire(blocking=False):
        return
    try:
        recovered = recover_failed_feeds(token, feed_ids=feed_ids)
        LOG.info("Browser-feed recovery finished recovered=%s", recovered)
    finally:
        _RECOVERY_LOCK.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "BlindRSSMinifluxBrowserFallback/1"

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _write_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Invalid request body size")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def do_GET(self):
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"ok": True})
        else:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self):
        token = str(self.headers.get("X-Auth-Token") or "").strip()
        if not valid_miniflux_token(token):
            self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return
        try:
            payload = self._read_json()
            if self.path == "/v1/add":
                result = add_protected_feed(
                    token,
                    payload.get("feed_url"),
                    payload.get("category_id"),
                )
                self._write_json(HTTPStatus.CREATED, result)
                return
            if self.path == "/v1/recover":
                feed_ids = payload.get("feed_ids") or []
                if not isinstance(feed_ids, list):
                    raise ValueError("feed_ids must be a list")
                threading.Thread(
                    target=_background_recovery,
                    args=(token, feed_ids),
                    name="miniflux-browser-feed-recovery",
                    daemon=True,
                ).start()
                self._write_json(HTTPStatus.ACCEPTED, {"queued": True})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            LOG.exception("Browser-feed fallback request failed")
            self._write_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("BLINDRSS_BROWSER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    LOG.info("Listening on http://%s:%s", LISTEN_HOST, LISTEN_PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
