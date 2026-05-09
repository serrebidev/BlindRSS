import os
import sys
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
import requests

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.miniflux import MinifluxProvider
from core import utils


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


def _provider(feed_timeout_seconds=15):
    cfg = {
        "feed_timeout_seconds": feed_timeout_seconds,
        "providers": {
            "miniflux": {
                "url": "https://example.test",
                "api_key": "token",
            }
        },
    }
    return MinifluxProvider(cfg)


def test_miniflux_req_uses_configured_timeout_for_normal_endpoints(monkeypatch):
    p = _provider(feed_timeout_seconds=42)
    seen = {}

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        seen["timeout"] = timeout
        return _DummyResp(status_code=204)

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)
    p._req("GET", "/v1/me")
    assert seen.get("timeout") == 42


def test_miniflux_refresh_uses_longer_timeout_floor(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    seen = {}

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        seen["timeout"] = timeout
        return _DummyResp(status_code=204)

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)
    p._req("PUT", "/v1/feeds/123/refresh")
    assert seen.get("timeout") == 10


def test_miniflux_req_adds_revalidation_headers(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    seen = {}

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        seen["headers"] = dict(headers or {})
        return _DummyResp(status_code=204)

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)
    p._req("GET", "/v1/me")

    headers = seen.get("headers") or {}
    assert "no-cache" in (headers.get("Cache-Control") or "").lower()
    assert (headers.get("Pragma") or "").lower() == "no-cache"
    assert headers.get("Expires") == "0"


def test_miniflux_req_records_204_as_success(monkeypatch):
    p = _provider(feed_timeout_seconds=10)

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        return _DummyResp(status_code=204)

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)

    assert p._req("PUT", "/v1/feeds/123/refresh") is None
    assert p._last_request_info["ok"] is True
    assert p._last_request_info["status_code"] == 204
    assert p._last_request_info["endpoint"] == "/v1/feeds/123/refresh"
    assert p._last_request_info["method"] == "PUT"


def test_miniflux_successful_204_global_refresh_clears_stale_failure_state(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    calls = []

    p._last_request_info = {
        "ok": False,
        "used_cache": False,
        "status_code": 502,
        "endpoint": "/v1/feeds/refresh",
        "method": "PUT",
        "error_body": None,
    }

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        endpoint = url.removeprefix("https://example.test")
        calls.append((method, endpoint))
        if endpoint == "/v1/feeds/refresh":
            return _DummyResp(status_code=204)
        if endpoint == "/v1/feeds/10/refresh":
            return _DummyResp(status_code=204)
        if endpoint == "/v1/feeds":
            return _DummyResp(
                status_code=200,
                payload=[
                    {
                        "id": 10,
                        "title": "Feed 10",
                        "category": {"title": "Podcasts"},
                        "checked_at": recent,
                        "parsing_error_count": 0,
                    }
                ],
            )
        if endpoint == "/v1/feeds/counters":
            return _DummyResp(status_code=200, payload={"unreads": {"10": 0}})
        raise AssertionError(f"Unexpected request: {method} {endpoint}")

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)

    assert p.refresh(force=True) is True
    assert ("PUT", "/v1/feeds/10/refresh") in calls


def test_miniflux_refresh_force_refreshes_each_feed(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
    targeted_calls = []
    now = datetime.now(timezone.utc)
    recent = now.isoformat()

    feeds_payload = [
        {"id": 1, "title": "Feed 1", "category": {"title": "Podcasts"}, "checked_at": recent, "parsing_error_count": 0},
        {"id": 2, "title": "Feed 2", "category": {"title": "News"}, "checked_at": recent, "parsing_error_count": 0},
    ]

    def _fake_req(method, endpoint, json=None, params=None):
        calls.append((method, endpoint))
        if endpoint == "/v1/feeds":
            return feeds_payload
        if endpoint == "/v1/feeds/counters":
            return {"unreads": {"1": 3, "2": 0}}
        return None

    monkeypatch.setattr(p, "_req", _fake_req)
    monkeypatch.setattr(
        p,
        "_request_targeted_refresh",
        lambda fid: targeted_calls.append(str(fid)) or {
            "ok": True,
            "status_code": 204,
            "endpoint": f"/v1/feeds/{fid}/refresh",
            "method": "PUT",
        },
    )
    p.refresh(force=True)

    assert set(targeted_calls) == {"1", "2"}


def test_miniflux_refresh_feeds_by_ids_refreshes_subset_and_emits_progress(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
    targeted_calls = []
    now = datetime.now(timezone.utc)
    recent = now.isoformat()

    feeds_payload = [
        {"id": 1, "title": "Feed 1", "category": {"title": "Podcasts"}, "checked_at": recent, "parsing_error_count": 0},
        {"id": 2, "title": "Feed 2", "category": {"title": "News"}, "checked_at": recent, "parsing_error_count": 0},
    ]

    def _fake_req(method, endpoint, json=None, params=None):
        calls.append((method, endpoint))
        p._last_request_info = {
            "ok": True,
            "used_cache": False,
            "status_code": 204 if method == "PUT" else 200,
            "endpoint": endpoint,
            "method": method,
        }
        if endpoint == "/v1/feeds":
            return feeds_payload
        if endpoint == "/v1/feeds/counters":
            return {"unreads": {"1": 3, "2": 0}}
        return None

    states = []
    monkeypatch.setattr(p, "_req", _fake_req)
    monkeypatch.setattr(
        p,
        "_request_targeted_refresh",
        lambda fid: targeted_calls.append(str(fid)) or {
            "ok": True,
            "status_code": 204,
            "endpoint": f"/v1/feeds/{fid}/refresh",
            "method": "PUT",
        },
    )

    assert p.refresh_feeds_by_ids(["2", "1", "2"], progress_cb=states.append, force=True) is True

    assert targeted_calls.count("1") == 1
    assert targeted_calls.count("2") == 1
    assert ("PUT", "/v1/feeds/refresh") not in calls
    assert [state["id"] for state in states] == ["2", "1"]
    assert states[1]["unread_count"] == 3


def test_miniflux_refresh_non_force_only_retries_stale_or_error(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
    targeted_calls = []
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(hours=4)).isoformat()
    recent = now.isoformat()

    feeds_payload = [
        {
            "id": 10,
            "title": "Stale feed",
            "category": {"title": "Podcasts"},
            "checked_at": stale,
            "parsing_error_count": 0,
        },
        {
            "id": 11,
            "title": "Error feed",
            "category": {"title": "Podcasts"},
            "checked_at": recent,
            "parsing_error_count": 1,
            "parsing_error_message": "parse failed",
        },
        {
            "id": 12,
            "title": "Healthy feed",
            "category": {"title": "Podcasts"},
            "checked_at": recent,
            "parsing_error_count": 0,
        },
    ]

    def _fake_req(method, endpoint, json=None, params=None):
        calls.append((method, endpoint))
        if endpoint == "/v1/feeds":
            return feeds_payload
        if endpoint == "/v1/feeds/counters":
            return {"unreads": {"10": 0, "11": 0, "12": 0}}
        return None

    monkeypatch.setattr(p, "_req", _fake_req)
    monkeypatch.setattr(
        p,
        "_request_targeted_refresh",
        lambda fid: targeted_calls.append(str(fid)) or {
            "ok": True,
            "status_code": 204,
            "endpoint": f"/v1/feeds/{fid}/refresh",
            "method": "PUT",
        },
    )
    p.refresh(force=False)

    assert "10" in targeted_calls
    assert "11" in targeted_calls
    assert "12" not in targeted_calls


def test_miniflux_req_retries_transient_502_then_succeeds(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    p.config["feed_retry_attempts"] = 2
    seen = {"calls": 0}

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        seen["calls"] += 1
        if seen["calls"] < 3:
            return _DummyResp(status_code=502, payload={})
        return _DummyResp(status_code=200, payload={"ok": True})

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)
    monkeypatch.setattr("providers.miniflux.time.sleep", lambda _s: None)

    data = p._req("GET", "/v1/me")
    assert data == {"ok": True}
    assert seen["calls"] == 3


def test_miniflux_targeted_refresh_transients_are_debug_only(monkeypatch, caplog):
    p = _provider(feed_timeout_seconds=10)
    p.config["feed_retry_attempts"] = 1
    seen = {"calls": 0}

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        seen["calls"] += 1
        return _DummyResp(status_code=500, payload={})

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)
    monkeypatch.setattr("providers.miniflux.time.sleep", lambda _s: None)

    caplog.set_level(logging.WARNING, logger="providers.miniflux")
    assert p._req("PUT", "/v1/feeds/97/refresh") is None

    assert seen["calls"] == 2
    assert not [record for record in caplog.records if "Miniflux transient HTTP" in record.getMessage()]


def test_miniflux_global_refresh_transients_stay_warning(monkeypatch, caplog):
    p = _provider(feed_timeout_seconds=10)
    p.config["feed_retry_attempts"] = 1
    seen = {"calls": 0}

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        seen["calls"] += 1
        return _DummyResp(status_code=500, payload={})

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)
    monkeypatch.setattr("providers.miniflux.time.sleep", lambda _s: None)

    caplog.set_level(logging.WARNING, logger="providers.miniflux")
    assert p._req("PUT", "/v1/feeds/refresh") is None

    assert seen["calls"] == 2
    assert any("Miniflux transient HTTP 500" in record.getMessage() for record in caplog.records)


def test_miniflux_targeted_refresh_backoff_is_debug_only(caplog):
    p = _provider(feed_timeout_seconds=10)

    caplog.set_level(logging.WARNING, logger="providers.miniflux")
    p._record_targeted_refresh_attempt_result("97", False, 500)

    assert not [record for record in caplog.records if "targeted refresh backoff" in record.getMessage()]


def test_miniflux_entries_keep_plausible_near_future_server_dates(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    future_dt = datetime.now(timezone.utc) + timedelta(days=3)
    entry = {
        "id": 203054,
        "feed_id": 114,
        "title": "Securing the Untrusted Agentic Development Layer",
        "url": "https://intelligence.theregister.com/paper/view/20103",
        "content": "",
        "status": "unread",
        "published_at": future_dt.isoformat(),
    }
    monkeypatch.setattr("providers.miniflux.utils.get_chapters_batch", lambda _ids: {})

    article = p._entries_to_articles([entry])[0]

    assert article.date == utils.format_datetime(future_dt)
    assert article.timestamp > 0


def test_miniflux_entries_fall_back_to_created_at_when_published_is_implausible(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    future_dt = datetime.now(timezone.utc) + timedelta(days=30)
    created_dt = datetime.now(timezone.utc) - timedelta(hours=2)
    entry = {
        "id": 203055,
        "feed_id": 114,
        "title": "Article Without Date",
        "url": "https://example.com/no-date",
        "content": "",
        "status": "unread",
        "published_at": future_dt.isoformat(),
        "created_at": created_dt.isoformat(),
    }
    monkeypatch.setattr("providers.miniflux.utils.get_chapters_batch", lambda _ids: {})

    article = p._entries_to_articles([entry])[0]

    assert article.date == utils.format_datetime(created_dt)
    assert article.timestamp > 0


def test_miniflux_req_uses_cached_get_response_on_502(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    p.config["feed_retry_attempts"] = 0
    responses = iter(
        [
            _DummyResp(status_code=200, payload=[{"id": 1, "title": "Feed 1"}]),
            _DummyResp(status_code=502, payload={}),
        ]
    )

    def _fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        return next(responses)

    monkeypatch.setattr("providers.miniflux.requests.request", _fake_request)
    monkeypatch.setattr("providers.miniflux.time.sleep", lambda _s: None)

    first = p._req("GET", "/v1/feeds")
    second = p._req("GET", "/v1/feeds")

    assert first == [{"id": 1, "title": "Feed 1"}]
    assert second == first


def test_miniflux_refresh_skips_targeted_refresh_when_unhealthy(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(hours=4)).isoformat()

    def _fake_req(method, endpoint, json=None, params=None):
        calls.append((method, endpoint))
        if endpoint == "/v1/feeds/refresh":
            p._last_request_info = {
                "ok": False,
                "used_cache": False,
                "status_code": 502,
                "endpoint": endpoint,
                "method": method,
            }
            return None
        if endpoint == "/v1/feeds":
            p._last_request_info = {
                "ok": False,
                "used_cache": True,
                "status_code": 502,
                "endpoint": endpoint,
                "method": method,
            }
            return [{"id": 10, "title": "Stale", "category": {"title": "Podcasts"}, "checked_at": stale, "parsing_error_count": 0}]
        if endpoint == "/v1/feeds/counters":
            p._last_request_info = {
                "ok": True,
                "used_cache": False,
                "status_code": 200,
                "endpoint": endpoint,
                "method": method,
            }
            return {"unreads": {"10": 0}}
        p._last_request_info = {
            "ok": True,
            "used_cache": False,
            "status_code": 204,
            "endpoint": endpoint,
            "method": method,
        }
        return None

    monkeypatch.setattr(p, "_req", _fake_req)
    p.refresh(force=False)

    assert ("PUT", "/v1/feeds/10/refresh") not in calls


def test_miniflux_targeted_refresh_uses_bounded_parallel_workers(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    p.config["miniflux_targeted_refresh_workers"] = 3
    lock = threading.Lock()
    active = {"count": 0, "max": 0}
    calls = []

    def _fake_targeted_refresh(fid):
        with lock:
            calls.append(str(fid))
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.05)
        with lock:
            active["count"] -= 1
        return {
            "ok": True,
            "status_code": 204,
            "endpoint": f"/v1/feeds/{fid}/refresh",
            "method": "PUT",
        }

    monkeypatch.setattr(p, "_request_targeted_refresh", _fake_targeted_refresh)

    results = p._refresh_targeted_feeds(["1", "2", "3", "4", "5"], force=True)

    assert set(calls) == {"1", "2", "3", "4", "5"}
    assert set(results) == {"1", "2", "3", "4", "5"}
    assert active["max"] > 1
    assert active["max"] <= 3


def test_miniflux_refresh_backs_off_repeated_targeted_feed_500s(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
    targeted_calls = []
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(hours=4)).isoformat()
    mono = {"t": 1000.0}

    feeds_payload = [
        {
            "id": 52,
            "title": "Problem Feed",
            "category": {"title": "Podcasts"},
            "checked_at": stale,
            "parsing_error_count": 0,
        }
    ]

    def _fake_monotonic():
        return mono["t"]

    def _fake_req(method, endpoint, json=None, params=None):
        calls.append((method, endpoint))
        if endpoint == "/v1/feeds/refresh":
            p._last_request_info = {
                "ok": True,
                "used_cache": False,
                "status_code": 204,
                "endpoint": endpoint,
                "method": method,
            }
            return None
        if endpoint == "/v1/feeds":
            p._last_request_info = {
                "ok": True,
                "used_cache": False,
                "status_code": 200,
                "endpoint": endpoint,
                "method": method,
            }
            return feeds_payload
        if endpoint == "/v1/feeds/counters":
            p._last_request_info = {
                "ok": True,
                "used_cache": False,
                "status_code": 200,
                "endpoint": endpoint,
                "method": method,
            }
            return {"unreads": {"52": 0}}
        p._last_request_info = {
            "ok": True,
            "used_cache": False,
            "status_code": 204,
            "endpoint": endpoint,
            "method": method,
        }
        return None

    def _fake_targeted_refresh(fid):
        targeted_calls.append(str(fid))
        return {
            "ok": False,
            "used_cache": False,
            "status_code": 500,
            "endpoint": f"/v1/feeds/{fid}/refresh",
            "method": "PUT",
        }

    monkeypatch.setattr("providers.miniflux.time.monotonic", _fake_monotonic)
    monkeypatch.setattr(p, "_req", _fake_req)
    monkeypatch.setattr(p, "_request_targeted_refresh", _fake_targeted_refresh)

    p.refresh(force=False)
    p.refresh(force=False)  # still inside cooldown -> should skip targeted feed retry

    assert targeted_calls.count("52") == 1

    mono["t"] += 61.0  # first cooldown expires (60s)
    p.refresh(force=False)
    assert targeted_calls.count("52") == 2
