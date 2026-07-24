# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import time
import threading

import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.miniflux import MinifluxProvider


class _DummyResp:
    def __init__(self, status_code=204, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if int(self.status_code or 0) >= 400:
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err
        return None

    def json(self):
        return self._payload


def _bare_provider(**extra):
    cfg = {"providers": {"miniflux": {"url": "https://example.test", "api_key": "t"}}}
    cfg.update(extra)
    return MinifluxProvider(cfg)


def test_force_retries_first_failure_but_skips_chronic_in_backoff():
    p = _bare_provider()
    now = time.monotonic()

    # No history -> always attempt on force.
    assert p._should_attempt_targeted_refresh("A", force=True) is True

    # In backoff, but only one failure so far -> a manual refresh retries it once.
    with p._targeted_refresh_backoff_lock:
        p._targeted_refresh_backoff_until["B"] = now + 100
        p._targeted_refresh_fail_counts["B"] = 1
    assert p._should_attempt_targeted_refresh("B", force=True) is True

    # In backoff AND failed repeatedly -> chronic, skipped even on force.
    with p._targeted_refresh_backoff_lock:
        p._targeted_refresh_backoff_until["C"] = now + 100
        p._targeted_refresh_fail_counts["C"] = 2
    assert p._should_attempt_targeted_refresh("C", force=True) is False

    # Repeatedly failed but backoff already expired -> attempt again on force.
    with p._targeted_refresh_backoff_lock:
        p._targeted_refresh_backoff_until["D"] = now - 1
        p._targeted_refresh_fail_counts["D"] = 5
    assert p._should_attempt_targeted_refresh("D", force=True) is True


def test_force_refresh_skips_feeds_with_high_parsing_error_count():
    # Feed 4 is chronically broken server-side (parsing_error_count >= 3); a manual
    # refresh must not synchronously re-fetch it.
    p = _bare_provider(miniflux_refresh_soft_deadline_s=0)  # blocking path, simpler to assert

    feeds = [
        {"id": 1, "title": "Fine 1", "category": {"title": "T"}, "parsing_error_count": 0,
         "checked_at": "2999-01-01T00:00:00Z", "icon": {}},
        {"id": 2, "title": "Transient", "category": {"title": "T"}, "parsing_error_count": 1,
         "checked_at": "2999-01-01T00:00:00Z", "icon": {}},
        {"id": 4, "title": "Broken", "category": {"title": "T"}, "parsing_error_count": 5,
         "checked_at": "2999-01-01T00:00:00Z", "icon": {}},
    ]
    refreshed = []
    lock = threading.Lock()

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        endpoint = url.split("example.test", 1)[-1].split("?", 1)[0]
        m = str(method or "").upper()
        if m == "GET" and endpoint == "/v1/feeds":
            return _DummyResp(200, feeds)
        if m == "GET" and endpoint == "/v1/feeds/counters":
            return _DummyResp(200, {"unreads": {}})
        if m == "PUT" and endpoint.endswith("/refresh") and endpoint != "/v1/feeds/refresh":
            with lock:
                refreshed.append(endpoint.split("/")[3])
            return _DummyResp(204)
        return _DummyResp(404)

    p._session.request = _fake_request  # type: ignore[assignment]
    p.refresh(progress_cb=lambda s: None, force=True)

    assert "1" in refreshed
    assert "2" in refreshed          # one prior error -> still retried
    assert "4" not in refreshed      # chronic (>=3 errors) -> skipped


def test_force_skip_threshold_zero_disables_skipping():
    p = _bare_provider(miniflux_refresh_soft_deadline_s=0, miniflux_force_skip_error_count=0)
    feeds = [
        {"id": 4, "title": "Broken", "category": {"title": "T"}, "parsing_error_count": 9,
         "checked_at": "2999-01-01T00:00:00Z", "icon": {}},
    ]
    refreshed = []

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        endpoint = url.split("example.test", 1)[-1].split("?", 1)[0]
        m = str(method or "").upper()
        if m == "GET" and endpoint == "/v1/feeds":
            return _DummyResp(200, feeds)
        if m == "GET" and endpoint == "/v1/feeds/counters":
            return _DummyResp(200, {"unreads": {}})
        if m == "PUT" and endpoint.endswith("/refresh") and endpoint != "/v1/feeds/refresh":
            refreshed.append(endpoint.split("/")[3])
            return _DummyResp(204)
        return _DummyResp(404)

    p._session.request = _fake_request  # type: ignore[assignment]
    p.refresh(progress_cb=lambda s: None, force=True)
    assert refreshed == ["4"]  # threshold 0 -> even a badly-broken feed is still forced
