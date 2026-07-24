# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional, Tuple

import requests

from core import utils

AUTH_URL = "https://www.inoreader.com/oauth2/auth"
TOKEN_URL = "https://www.inoreader.com/oauth2/token"

REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 18423
REDIRECT_PATH = "/inoreader/oauth"

DEFAULT_SCOPE = "read write"

def get_redirect_uri(
    host: str = REDIRECT_HOST,
    port: int = REDIRECT_PORT,
    path: str = REDIRECT_PATH,
    scheme: str = "https",
) -> str:
    scheme_norm = str(scheme or "https").strip().lower()
    if scheme_norm not in {"http", "https"}:
        scheme_norm = "https"
    path_norm = str(path or "")
    if path_norm and not path_norm.startswith("/"):
        path_norm = "/" + path_norm
    return f"{scheme_norm}://{host}:{port}{path_norm}"


def create_authorization_url(
    app_id: str,
    redirect_uri: str,
    scope: str | None = DEFAULT_SCOPE,
) -> Tuple[str, str]:
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    # Scope is optional in Inoreader, but BlindRSS generally needs read+write access
    # (mark read/unread, favorites, subscription management). Only send it when present.
    if scope:
        params["scope"] = scope
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", state


def parse_oauth_redirect(value: str) -> tuple[str | None, str | None, str | None]:
    """Parse an OAuth redirect URL or query string and extract `code` and `state`.

    Accepts:
    - Full URL: "https://127.0.0.1:18423/inoreader/oauth?code=...&state=..."
    - Query string: "code=...&state=..."
    - Code only: "..." (state will be None)

    Returns: (code, state, error)
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("Empty redirect value.")

    query = ""
    if "://" in text or "?" in text or "#" in text:
        parsed = urllib.parse.urlparse(text)
        query = parsed.query or ""
        if not query and parsed.fragment:
            # Some OAuth providers return params in fragment; keep it as fallback.
            query = parsed.fragment
    else:
        # Treat as a raw query string or a bare code.
        query = text

    if "code=" not in query and "state=" not in query and "error=" not in query and "?" not in text:
        # Bare code.
        return text, None, None

    if query.startswith("?"):
        query = query[1:]

    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    code = (params.get("code") or [None])[0]
    state = (params.get("state") or [None])[0]
    err = (params.get("error") or [None])[0]

    code_s = str(code).strip() if code is not None else None
    if code_s == "":
        code_s = None
    state_s = str(state).strip() if state is not None else None
    if state_s == "":
        state_s = None
    err_s = str(err).strip() if err is not None else None
    if err_s == "":
        err_s = None
    return code_s, state_s, err_s


class _OAuthHTTPServer(HTTPServer):
    allow_reuse_address = True


def wait_for_oauth_code(
    expected_state: str,
    timeout_s: int = 180,
    host: str = REDIRECT_HOST,
    port: int = REDIRECT_PORT,
    path: str = REDIRECT_PATH,
    ready_event=None,
) -> str:
    result: Dict[str, Optional[str]] = {"code": None, "error": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if path and parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return

            params = urllib.parse.parse_qs(parsed.query)
            if "error" in params:
                result["error"] = params.get("error", ["authorization_error"])[0]
            elif "code" in params:
                state = params.get("state", [""])[0]
                if expected_state and state != expected_state:
                    result["error"] = "invalid_state"
                else:
                    result["code"] = params.get("code", [""])[0]
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                body = "<html><body><p>Waiting for authorization...</p></body></html>"
                self.wfile.write(body.encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if result["code"]:
                body = "<html><body><p>Authorization complete. You can close this window.</p></body></html>"
            else:
                body = "<html><body><p>Authorization failed. You can close this window.</p></body></html>"
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, _format, *_args):
            return

    start = time.time()
    try:
        with _OAuthHTTPServer((host, port), Handler) as httpd:
            httpd.timeout = 0.5
            if ready_event is not None:
                try:
                    ready_event.set()
                except Exception:
                    pass
            while time.time() - start < timeout_s and result["code"] is None and result["error"] is None:
                httpd.handle_request()
    except OSError as exc:
        raise RuntimeError(f"Could not start local callback server on {host}:{port}: {exc}") from exc

    if result["code"]:
        return result["code"]
    if result["error"]:
        raise RuntimeError(f"Inoreader authorization failed: {result['error']}")
    raise TimeoutError("Timed out waiting for Inoreader authorization.")


def exchange_code_for_tokens(
    app_id: str,
    app_key: str,
    code: str,
    redirect_uri: str,
    timeout_s: int = 15,
) -> Dict[str, str]:
    data = {
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": app_id,
        "client_secret": app_key,
        "grant_type": "authorization_code",
    }
    headers = utils.HEADERS.copy()
    headers["Accept"] = "application/json"
    resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(
    app_id: str,
    app_key: str,
    refresh_token: str,
    timeout_s: int = 15,
) -> Dict[str, str]:
    data = {
        "client_id": app_id,
        "client_secret": app_key,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = utils.HEADERS.copy()
    headers["Accept"] = "application/json"
    resp = requests.post(TOKEN_URL, data=data, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()
