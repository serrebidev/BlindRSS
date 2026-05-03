import os
import sys
from datetime import datetime, timedelta, timezone
import requests

# Ensure repo root on path
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


def test_miniflux_refresh_force_refreshes_each_feed(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
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
    p.refresh(force=True)

    assert ("PUT", "/v1/feeds/1/refresh") in calls
    assert ("PUT", "/v1/feeds/2/refresh") in calls


def test_miniflux_refresh_feeds_by_ids_refreshes_subset_and_emits_progress(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
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

    assert p.refresh_feeds_by_ids(["2", "1", "2"], progress_cb=states.append, force=True) is True

    assert calls.count(("PUT", "/v1/feeds/1/refresh")) == 1
    assert calls.count(("PUT", "/v1/feeds/2/refresh")) == 1
    assert ("PUT", "/v1/feeds/refresh") not in calls
    assert [state["id"] for state in states] == ["2", "1"]
    assert states[1]["unread_count"] == 3


def test_miniflux_refresh_non_force_only_retries_stale_or_error(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
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
    p.refresh(force=False)

    assert ("PUT", "/v1/feeds/10/refresh") in calls
    assert ("PUT", "/v1/feeds/11/refresh") in calls
    assert ("PUT", "/v1/feeds/12/refresh") not in calls


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


def test_miniflux_refresh_backs_off_repeated_targeted_feed_500s(monkeypatch):
    p = _provider(feed_timeout_seconds=10)
    calls = []
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
        if endpoint == "/v1/feeds/52/refresh":
            p._last_request_info = {
                "ok": False,
                "used_cache": False,
                "status_code": 500,
                "endpoint": endpoint,
                "method": method,
            }
            return None
        p._last_request_info = {
            "ok": True,
            "used_cache": False,
            "status_code": 204,
            "endpoint": endpoint,
            "method": method,
        }
        return None

    monkeypatch.setattr("providers.miniflux.time.monotonic", _fake_monotonic)
    monkeypatch.setattr(p, "_req", _fake_req)

    p.refresh(force=False)
    p.refresh(force=False)  # still inside cooldown -> should skip targeted feed retry

    assert calls.count(("PUT", "/v1/feeds/52/refresh")) == 1

    mono["t"] += 61.0  # first cooldown expires (60s)
    p.refresh(force=False)
    assert calls.count(("PUT", "/v1/feeds/52/refresh")) == 2
