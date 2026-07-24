# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.bazqux import BazQuxProvider
from providers.inoreader import InoreaderProvider
from providers.theoldreader import TheOldReaderProvider


def _assert_revalidation_headers(headers):
    h = dict(headers or {})
    assert "no-cache" in (h.get("Cache-Control") or "").lower()
    assert (h.get("Pragma") or "").lower() == "no-cache"
    assert h.get("Expires") == "0"


def test_inoreader_request_uses_revalidation_headers(monkeypatch):
    cfg = {
        "feed_timeout_seconds": 10,
        "providers": {
            "inoreader": {
                "token": "token",
                "app_id": "app-id",
                "app_key": "app-key",
                "refresh_token": "",
                "token_expires_at": 0,
            }
        },
    }
    p = InoreaderProvider(cfg)
    seen = {}

    class _Resp:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

    def _fake_request(method, url, headers=None, params=None, data=None, **kwargs):
        seen["headers"] = dict(headers or {})
        return _Resp()

    monkeypatch.setattr("providers.inoreader.requests.request", _fake_request)
    p._request("get", "https://example.test/reader/api/0/me")
    _assert_revalidation_headers(seen.get("headers"))


def test_theoldreader_headers_include_revalidation_directives():
    cfg = {"providers": {"theoldreader": {"email": "", "password": ""}}}
    p = TheOldReaderProvider(cfg)
    _assert_revalidation_headers(p._headers())


def test_bazqux_headers_include_revalidation_directives():
    cfg = {"providers": {"bazqux": {"email": "", "password": ""}}}
    p = BazQuxProvider(cfg)
    _assert_revalidation_headers(p._headers())
