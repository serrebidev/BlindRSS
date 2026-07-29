# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Optional paid CAPTCHA-solving-service client (tier-4 challenge escalation).

When neither the SeleniumBase UC session nor the pydoll Turnstile auto-click
can clear a Cloudflare challenge page, the pydoll browser can hook
``window.turnstile.render``, forward the intercepted parameters to a paid
solving service, and inject the returned token. This is strictly opt-in: the
user enables it in Settings and supplies their own API key, which is stored
only in the local config.json. Without a key the tier is skipped entirely and
behavior is exactly as before.

Both supported providers implement the same HTTP API shape. Never log the API
key, the intercepted challenge parameters, or the solved token.
"""

from __future__ import annotations

import logging
import threading
import time

import requests


log = logging.getLogger(__name__)

DEFAULT_PROVIDER = "2captcha"
_PROVIDERS = {
    "2captcha": ("https://2captcha.com/in.php", "https://2captcha.com/res.php"),
    "solvecaptcha": (
        "https://api.solvecaptcha.com/in.php",
        "https://api.solvecaptcha.com/res.php",
    ),
}

_HTTP_TIMEOUT_SECONDS = 30.0
_FIRST_POLL_DELAY_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_SOLVE_TIMEOUT_SECONDS = 120.0

_settings_lock = threading.Lock()
_settings = {"enabled": False, "provider": DEFAULT_PROVIDER, "api_key": ""}


def configure(settings) -> None:
    """Register solver settings (startup and settings-save, like tool paths)."""
    global _settings
    try:
        items = dict(settings or {})
    except Exception:
        items = {}
    provider = str(items.get("provider") or DEFAULT_PROVIDER).strip().lower()
    if provider not in _PROVIDERS:
        provider = DEFAULT_PROVIDER
    cleaned = {
        "enabled": bool(items.get("enabled", False)),
        "provider": provider,
        "api_key": str(items.get("api_key") or "").strip(),
    }
    with _settings_lock:
        _settings = cleaned


def configure_from_config(config_get) -> None:
    """Feed settings from a config getter (``config_manager.get``)."""
    try:
        configure(
            {
                "enabled": config_get("captcha_solver_enabled", False),
                "provider": config_get("captcha_solver_provider", DEFAULT_PROVIDER),
                "api_key": config_get("captcha_solver_api_key", ""),
            }
        )
    except Exception:
        log.debug("Could not apply CAPTCHA solver settings", exc_info=True)


def current_settings() -> dict:
    """Return a copy of the registered settings."""
    with _settings_lock:
        return dict(_settings)


def solver_available() -> bool:
    """True only when the user opted in and supplied a usable key."""
    settings = current_settings()
    return bool(
        settings.get("enabled")
        and settings.get("api_key")
        and settings.get("provider") in _PROVIDERS
    )


def _cancelled(cancel_event) -> bool:
    try:
        return bool(cancel_event and cancel_event.is_set())
    except Exception:
        return False


def _sleep_or_cancel(seconds: float, cancel_event) -> bool:
    """Sleep in small slices so a refresh cancellation lands promptly."""
    deadline = time.monotonic() + max(0.0, float(seconds))
    while time.monotonic() < deadline:
        if _cancelled(cancel_event):
            return True
        time.sleep(min(0.25, deadline - time.monotonic()))
    return _cancelled(cancel_event)


def solve_turnstile(
    *,
    api_key: str,
    provider: str,
    sitekey: str,
    pageurl: str,
    data: str | None = None,
    pagedata: str | None = None,
    action: str | None = None,
    user_agent: str | None = None,
    timeout_s: float = DEFAULT_SOLVE_TIMEOUT_SECONDS,
    cancel_event=None,
) -> str | None:
    """Solve a Turnstile challenge through a paid service; return the token.

    ``data``/``pagedata``/``action`` are the dynamically generated parameters
    intercepted from ``window.turnstile.render`` on challenge pages. Returns
    None on any failure, timeout, or cancellation.
    """
    endpoints = _PROVIDERS.get(str(provider or "").strip().lower())
    api_key = str(api_key or "").strip()
    sitekey = str(sitekey or "").strip()
    pageurl = str(pageurl or "").strip()
    if not endpoints or not api_key or not sitekey or not pageurl:
        return None
    in_url, res_url = endpoints

    payload = {
        "key": api_key,
        "method": "turnstile",
        "sitekey": sitekey,
        "pageurl": pageurl,
        "json": 1,
    }
    if data:
        payload["data"] = str(data)
    if pagedata:
        payload["pagedata"] = str(pagedata)
    if action:
        payload["action"] = str(action)
    if user_agent:
        payload["userAgent"] = str(user_agent)

    deadline = time.monotonic() + max(15.0, float(timeout_s or DEFAULT_SOLVE_TIMEOUT_SECONDS))
    try:
        response = requests.post(in_url, data=payload, timeout=_HTTP_TIMEOUT_SECONDS)
        result = response.json()
    except Exception:
        log.info("CAPTCHA solver task submission failed", exc_info=True)
        return None
    if not isinstance(result, dict) or result.get("status") != 1:
        log.info("CAPTCHA solver rejected the task: %s", result.get("request") if isinstance(result, dict) else type(result))
        return None
    task_id = result.get("request")

    if _sleep_or_cancel(_FIRST_POLL_DELAY_SECONDS, cancel_event):
        return None
    while not _cancelled(cancel_event):
        if time.monotonic() >= deadline:
            return None
        try:
            response = requests.get(
                res_url,
                params={"key": api_key, "action": "get", "id": task_id, "json": 1},
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            result = response.json()
        except Exception:
            log.debug("CAPTCHA solver poll failed; retrying", exc_info=True)
            result = None
        if isinstance(result, dict):
            if result.get("status") == 1:
                token = str(result.get("request") or "").strip()
                return token or None
            if result.get("request") != "CAPCHA_NOT_READY":
                log.info("CAPTCHA solver failed the task: %s", result.get("request"))
                return None
        if _sleep_or_cancel(_POLL_INTERVAL_SECONDS, cancel_event):
            return None
    return None
