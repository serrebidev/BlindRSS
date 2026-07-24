# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import importlib.util
from pathlib import Path

import pytest

from providers.miniflux import MinifluxProvider
from core import utils


SERVICE_PATH = Path(__file__).parents[1] / "tools" / "miniflux_browser_fallback_service.py"
SPEC = importlib.util.spec_from_file_location("miniflux_browser_fallback_service", SERVICE_PATH)
service = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(service)


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _provider():
    return MinifluxProvider(
        {
            "browser_feed_fallback_enabled": True,
            "browser_feed_fallback_timeout_seconds": 45,
            "providers": {
                "miniflux": {
                    "url": "https://reader.example",
                    "api_key": "token",
                }
            },
        }
    )


def test_feed_validation_and_challenge_detection():
    assert service.looks_like_feed("<rss><channel/></rss>")
    assert service.looks_like_feed(
        '{"version":"https://jsonfeed.org/version/1.1","items":[]}'
    )
    assert not service.looks_like_feed("<html>Just a moment...</html>")
    assert service.looks_like_challenge_error(
        "Unable to fetch this resource (Status Code: 403)"
    )
    assert not service.looks_like_challenge_error("XML parse error")
    wrapped = "<html><body><pre>&lt;rss&gt;&lt;channel/&gt;&lt;/rss&gt;</pre></body></html>"
    assert service.feed_text_from_page_source(wrapped) == "<rss><channel/></rss>"


def test_user_url_normalization_removes_markdown_delimiters():
    expected = "https://forum.audiogames.net/feed/rss/"
    assert utils.normalize_user_submitted_url(expected + "`") == expected
    assert utils.normalize_user_submitted_url(f"`{expected}`") == expected
    assert utils.normalize_user_submitted_url(f"<{expected}>") == expected


def test_private_feed_targets_are_rejected(monkeypatch):
    monkeypatch.setattr(
        service.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="Private"):
        service.validate_public_http_url("https://localhost/feed")


def test_miniflux_add_falls_back_to_same_origin_companion(monkeypatch):
    provider = _provider()
    calls = []

    def fake_req(method, endpoint, json=None, params=None):
        if method == "GET" and endpoint == "/v1/categories":
            return [{"id": 7, "title": "News"}]
        if method == "POST" and endpoint == "/v1/feeds":
            provider._last_request_info = {
                "method": "POST",
                "endpoint": endpoint,
                "status_code": 400,
                "error_body": '{"error_message":"Unable to fetch feed: 403"}',
            }
            return None
        if method == "GET" and endpoint == "/v1/feeds":
            return []
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(provider, "_req", fake_req)
    monkeypatch.setattr(
        provider,
        "_browser_feed_fallback_request",
        lambda action, payload, wait=False: calls.append((action, payload, wait))
        or {"feed_id": 91, "duplicate": False},
    )
    monkeypatch.setattr("core.discovery.get_ytdlp_feed_url", lambda _url: None)
    monkeypatch.setattr("core.discovery.discover_feed", lambda _url: None)

    assert provider.add_feed("https://protected.example/feed", "News") is True
    assert calls == [
        (
            "add",
            {"feed_url": "https://protected.example/feed", "category_id": 7},
            True,
        )
    ]
    assert provider._last_add_feed_result["feed_id"] == "91"


def test_missing_companion_is_disabled_after_one_404(monkeypatch):
    provider = _provider()
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(404, {})

    monkeypatch.setattr(provider._session, "post", fake_post)

    assert provider._queue_browser_feed_recovery(["1"]) is False
    assert provider._queue_browser_feed_recovery(["1"]) is False
    assert len(calls) == 1


def test_recover_is_queued_only_for_browser_challenge_metadata(monkeypatch):
    provider = _provider()
    queued = []
    monkeypatch.setattr(
        provider,
        "_queue_browser_feed_recovery",
        lambda ids=None: queued.append(ids) or True,
    )

    assert provider._looks_like_browser_challenge_error("Status Code: 403")
    assert not provider._looks_like_browser_challenge_error("Malformed XML")
