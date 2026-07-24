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


def _feeds_payload():
    return [
        {"id": i, "title": f"Feed {i}", "site_url": f"http://x/{i}",
         "category": {"title": "Tests"}, "parsing_error_count": 0,
         "checked_at": "2999-01-01T00:00:00Z", "icon": {}}
        for i in (1, 2, 3, 4)
    ]


def _provider(deadline_s, slow_feed_delay_s, slow_feed_id="4"):
    cfg = {
        "feed_timeout_seconds": 15,
        "miniflux_refresh_soft_deadline_s": deadline_s,
        "miniflux_targeted_refresh_workers": 8,
        "providers": {"miniflux": {"url": "https://example.test", "api_key": "t"}},
    }
    p = MinifluxProvider(cfg)

    lock = threading.Lock()
    calls = []

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        endpoint = url.split("example.test", 1)[-1].split("?", 1)[0]
        m = str(method or "").upper()
        with lock:
            calls.append((m, endpoint))
        if m == "GET" and endpoint == "/v1/feeds":
            return _DummyResp(200, _feeds_payload())
        if m == "GET" and endpoint == "/v1/feeds/counters":
            return _DummyResp(200, {"unreads": {"1": 1, "2": 1, "3": 1, "4": 5}})
        if m == "PUT" and endpoint == "/v1/feeds/refresh":
            return _DummyResp(204)
        if m == "PUT" and endpoint.endswith("/refresh"):
            fid = endpoint.split("/")[3]
            if fid == slow_feed_id:
                time.sleep(slow_feed_delay_s)
            return _DummyResp(204)
        return _DummyResp(404)

    p._session.request = _fake_request  # type: ignore[assignment]
    return p, calls


def test_manual_refresh_returns_before_slow_feed_and_streams_it():
    # Fast feeds finish instantly; feed "4" blocks well past the soft deadline.
    # soft deadline. The manual refresh must report complete near the deadline while
    # feed 4 finishes in the background and is NOT dropped. Margins are wide so the
    # assertion stays robust under load (thread wakeup / wait() timeout granularity).
    deadline = 0.05
    slow_delay = 0.5
    p, _calls = _provider(deadline, slow_delay)

    progress_lock = threading.Lock()
    seen = {}  # id -> status
    slow_seen = threading.Event()

    def progress_cb(state):
        fid = str(state.get("id") or "")
        with progress_lock:
            seen[fid] = state.get("status")
        if fid == "4" and state.get("status") == "ok":
            slow_seen.set()

    t0 = time.monotonic()
    result = p.refresh(progress_cb=progress_cb, force=True)
    elapsed = time.monotonic() - t0

    assert result is True
    # Returned well before the slow feed's 3.0s server fetch would finish (wide
    # margin: proves it did not block on the straggler without being flaky).
    assert elapsed < 0.3, f"refresh blocked on straggler ({elapsed:.2f}s)"
    # And it did wait at least the soft-deadline window (not an instant no-op).
    assert elapsed >= deadline * 0.5

    # The slow feed streams in afterward and is recorded -- no content dropped.
    assert slow_seen.wait(timeout=1.0), "straggler feed never emitted its result"
    with progress_lock:
        assert seen.get("4") == "ok"

    # The background daemon releases the cancel scope once stragglers finish.
    deadline_at = time.monotonic() + 1.0
    while p._current_refresh_cancel_event() is not None and time.monotonic() < deadline_at:
        time.sleep(0.02)
    assert p._current_refresh_cancel_event() is None


def test_manual_refresh_all_fast_has_no_stragglers_and_releases_scope():
    # With no slow feed, everything finishes inside the deadline: no background
    # handoff, scope released synchronously by refresh() itself.
    p, _calls = _provider(deadline_s=1.0, slow_feed_delay_s=0.0, slow_feed_id="none")

    result = p.refresh(progress_cb=lambda s: None, force=True)
    assert result is True
    assert p._current_refresh_cancel_event() is None


def test_streaming_disabled_when_deadline_zero_blocks_until_done():
    # soft_deadline=0 restores classic blocking behavior: refresh only returns after
    # the slow feed completes.
    slow_delay = 0.1
    p, _calls = _provider(deadline_s=0.0, slow_feed_delay_s=slow_delay)

    t0 = time.monotonic()
    result = p.refresh(progress_cb=lambda s: None, force=True)
    elapsed = time.monotonic() - t0
    assert result is True
    assert elapsed >= slow_delay, "blocking refresh returned before slow feed finished"
    assert p._current_refresh_cancel_event() is None
