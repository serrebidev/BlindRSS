# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Guards against the per-feed refresh storm seen in the v1.124.0 field log.

A startup refresh triggered the global ``PUT /v1/feeds/refresh`` (accepted, 204)
and then immediately fired 15 targeted ``PUT /v1/feeds/{id}/refresh`` calls, every
one of which the server answered 500 because those feeds were already sitting in
its own refresh queue. The per-feed backoff only applied to the *next* cycle, so
the whole batch went out every time.
"""

import os
import sys
import threading

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.miniflux import MinifluxProvider


def _bare_provider(**extra):
    cfg = {"providers": {"miniflux": {"url": "https://example.test", "api_key": "t"}}}
    cfg.update(extra)
    return MinifluxProvider(cfg)


def test_route_breaker_trips_after_consecutive_5xx_and_parks_the_route():
    p = _bare_provider()
    assert not p._targeted_refresh_route_in_cooldown()

    p._trip_targeted_refresh_route_breaker(3)

    assert p._targeted_refresh_route_in_cooldown()
    # Every feed is skipped while the route is parked, force or not.
    assert p._should_attempt_targeted_refresh("42") is False
    assert p._should_attempt_targeted_refresh("42", force=True) is False


def test_parked_route_short_circuits_queued_workers_without_hitting_the_network():
    """A worker queued before the breaker tripped must not reach the wire."""
    p = _bare_provider()
    calls = []

    def _boom(*a, **kw):
        calls.append(a)
        raise AssertionError("targeted refresh should not have been sent")

    p._session.put = _boom  # type: ignore[method-assign]
    p._trip_targeted_refresh_route_breaker(3)

    info = p._request_targeted_refresh("2908")

    assert info.get("skipped") is True
    assert info.get("ok") is False
    assert calls == []


def test_batch_of_5xx_trips_the_breaker_and_stops_the_rest_of_the_batch():
    """The whole point: 15 queued feeds must not all reach a 5xx-ing server."""
    p = _bare_provider()
    attempted = []

    def _fake_targeted(fid, cancel_event=None):
        if p._targeted_refresh_route_in_cooldown():
            return {"ok": False, "status_code": None, "skipped": True,
                    "endpoint": f"/v1/feeds/{fid}/refresh", "method": "PUT"}
        attempted.append(str(fid))
        return {"ok": False, "status_code": 500, "used_cache": False,
                "endpoint": f"/v1/feeds/{fid}/refresh", "method": "PUT",
                "error_body": None}

    p._request_targeted_refresh = _fake_targeted  # type: ignore[method-assign]
    # Single worker keeps the ordering deterministic so the cut-off is observable.
    p._targeted_refresh_worker_count = lambda _n: 1  # type: ignore[method-assign]

    feed_ids = [str(i) for i in range(1, 16)]
    p._refresh_targeted_feeds(feed_ids)

    assert p._targeted_refresh_route_in_cooldown()
    # Three failures trip it; everything queued behind them is dropped.
    assert len(attempted) == 3, attempted
    assert attempted == ["1", "2", "3"]


def test_parallel_batch_probes_only_to_breaker_limit_before_expanding():
    """Do not refill the probe window while its final request is pending."""
    p = _bare_provider(miniflux_targeted_refresh_workers=15)
    attempted = []
    attempted_lock = threading.Lock()
    first_two_done = threading.Event()
    release_third = threading.Event()
    completed = 0

    def _fake_targeted(fid, cancel_event=None):
        nonlocal completed
        with attempted_lock:
            attempted.append(str(fid))
        if str(fid) == "3":
            assert release_third.wait(timeout=5), "test did not release third probe"
        else:
            with attempted_lock:
                completed += 1
                if completed == 2:
                    first_two_done.set()
        return {"ok": False, "status_code": 500, "used_cache": False,
                "endpoint": f"/v1/feeds/{fid}/refresh", "method": "PUT",
                "error_body": None}

    p._request_targeted_refresh = _fake_targeted  # type: ignore[method-assign]
    worker = threading.Thread(
        target=p._refresh_targeted_feeds,
        args=([str(i) for i in range(1, 16)],),
    )
    worker.start()

    assert first_two_done.wait(timeout=5), "initial probes did not complete"
    with attempted_lock:
        assert set(attempted) == {"1", "2", "3"}, attempted

    release_third.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert p._targeted_refresh_route_in_cooldown()
    assert len(attempted) == 3, attempted


def test_a_working_feed_resets_the_consecutive_counter():
    """Isolated bad feeds must not park a route that is otherwise healthy."""
    p = _bare_provider()
    statuses = {"2": 500, "4": 500, "6": 500}

    def _fake_targeted(fid, cancel_event=None):
        status = statuses.get(str(fid))
        return {"ok": status is None, "status_code": status or 204, "used_cache": False,
                "endpoint": f"/v1/feeds/{fid}/refresh", "method": "PUT", "error_body": None}

    p._request_targeted_refresh = _fake_targeted  # type: ignore[method-assign]
    p._targeted_refresh_worker_count = lambda _n: 1  # type: ignore[method-assign]

    p._refresh_targeted_feeds([str(i) for i in range(1, 8)])

    assert not p._targeted_refresh_route_in_cooldown()


def test_breaker_disabled_by_config():
    p = _bare_provider(miniflux_targeted_refresh_5xx_limit=0)
    assert p._targeted_refresh_route_batch_5xx_limit() == 0
    p._trip_targeted_refresh_route_breaker(9)
    # A zero cooldown would also disable it; the limit is what gates the counting.
    p2 = _bare_provider(miniflux_targeted_refresh_cooldown_s=0)
    p2._trip_targeted_refresh_route_breaker(3)
    assert not p2._targeted_refresh_route_in_cooldown()


def test_request_info_is_per_thread():
    """Overlapping /v1/feeds GETs must not describe each other's outcome."""
    p = _bare_provider()
    seen = {}
    started = threading.Barrier(2)

    def _worker(name, payload):
        started.wait(timeout=5)
        p._last_request_info = payload
        # Give the other thread every chance to clobber a shared slot.
        for _ in range(200):
            pass
        seen[name] = dict(p._last_request_info)

    a = threading.Thread(target=_worker, args=("a", {"endpoint": "/v1/feeds", "ok": True}))
    b = threading.Thread(target=_worker, args=("b", {"endpoint": "/v1/categories", "ok": False}))
    a.start()
    b.start()
    a.join(timeout=5)
    b.join(timeout=5)

    assert seen["a"]["endpoint"] == "/v1/feeds"
    assert seen["a"]["ok"] is True
    assert seen["b"]["endpoint"] == "/v1/categories"
    assert seen["b"]["ok"] is False


def test_fresh_thread_gets_a_blank_request_info():
    p = _bare_provider()
    p._last_request_info = {"endpoint": "/v1/feeds", "ok": True}
    out = {}

    def _worker():
        out["info"] = dict(p._last_request_info)

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=5)

    assert out["info"]["endpoint"] == ""
    assert out["info"]["ok"] is False
