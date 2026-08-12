# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""A transient GitHub 5xx must not report the release as broken.

Users saw "Failed to download update metadata: 503 Server Error" simply because
GitHub's asset CDN had a bad moment: the check made exactly one request and gave
up.  These tests pin the retry and the REST-asset fallback that replaced it.
"""

import pytest

from core import updater


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}

    @property
    def ok(self):
        return self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Server Error")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)


MANIFEST = {
    "version": "v999.0.0",
    "asset": "BlindRSS-v999.0.0.zip",
    "sha256": "a" * 64,
}

CDN_URL = "https://github.com/serrebidev/BlindRSS/releases/download/v999.0.0/BlindRSS-update.json"
API_URL = "https://api.github.com/repos/serrebidev/BlindRSS/releases/assets/1"


def test_download_json_retries_after_transient_503(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResponse(503)
        return _FakeResponse(200, MANIFEST)

    monkeypatch.setattr(updater, "safe_requests_get", fake_get)
    manifest, err = updater._download_json(CDN_URL)
    assert err is None
    assert manifest == MANIFEST
    assert len(calls) == 2


def test_download_json_falls_back_to_rest_asset_url(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("headers") or {}))
        if url == CDN_URL:
            return _FakeResponse(503)
        return _FakeResponse(200, MANIFEST)

    monkeypatch.setattr(updater, "safe_requests_get", fake_get)
    manifest, err = updater._download_json(CDN_URL, fallback_urls=(API_URL,))
    assert err is None
    assert manifest == MANIFEST
    # The REST endpoint hands back asset metadata unless the bytes are requested.
    assert calls[-1][0] == API_URL
    assert calls[-1][1].get("Accept") == "application/octet-stream"


def test_download_json_reports_a_recoverable_error_when_every_attempt_fails(monkeypatch):
    monkeypatch.setattr(updater, "safe_requests_get", lambda url, **kwargs: _FakeResponse(503))
    manifest, err = updater._download_json(CDN_URL, fallback_urls=(API_URL,))
    assert manifest is None
    assert err
    assert "503" in err
    # The blind user hears this string: it must say the failure is temporary.
    assert "try again" in err.lower()


def test_permanent_error_is_not_retried(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(404)

    monkeypatch.setattr(updater, "safe_requests_get", fake_get)
    manifest, err = updater._download_json(CDN_URL)
    assert manifest is None
    assert err
    assert len(calls) == 1


def test_network_exception_is_retried(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise OSError("connection reset")
        return _FakeResponse(200, MANIFEST)

    monkeypatch.setattr(updater, "safe_requests_get", fake_get)
    manifest, err = updater._download_json(CDN_URL)
    assert err is None
    assert manifest == MANIFEST


def test_retry_after_header_is_honored_within_cap(monkeypatch):
    resp = _FakeResponse(503, headers={"Retry-After": "600"})
    assert updater._retry_delay(0, resp) == updater._RETRY_AFTER_CAP_SECONDS
    assert updater._retry_delay(0, _FakeResponse(503)) == updater._HTTP_RETRY_BACKOFF_SECONDS[0]


def test_fetch_latest_release_retries_transient_api_error(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResponse(502)
        return _FakeResponse(200, {"tag_name": "v999.0.0"})

    monkeypatch.setattr(updater, "safe_requests_get", fake_get)
    release, err = updater._fetch_latest_release()
    assert err is None
    assert release == {"tag_name": "v999.0.0"}
    assert len(calls) == 2


def _release_with_rest_urls():
    return {
        "tag_name": "v999.0.0",
        "published_at": "2026-01-01T00:00:00Z",
        "assets": [
            {
                "name": "BlindRSS-update.json",
                "browser_download_url": CDN_URL,
                "url": API_URL,
            },
            {
                "name": "BlindRSS-v999.0.0.zip",
                "browser_download_url": "https://github.com/dl/zip",
                "url": "https://api.github.com/repos/serrebidev/BlindRSS/releases/assets/2",
            },
        ],
    }


def test_check_for_updates_threads_fallback_urls_through(monkeypatch):
    seen = {}

    def fake_download_json(url, timeout=20, fallback_urls=()):
        seen["url"] = url
        seen["fallback_urls"] = tuple(fallback_urls)
        return MANIFEST, None

    monkeypatch.setattr(updater, "current_platform", lambda: "windows")
    monkeypatch.setattr(updater, "is_windows_installed_build", lambda: False)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: (_release_with_rest_urls(), None))
    monkeypatch.setattr(updater, "_download_json", fake_download_json)

    res = updater.check_for_updates()
    assert res.status == "update_available"
    assert seen["url"] == CDN_URL
    assert seen["fallback_urls"] == (API_URL,)
    assert res.info is not None
    assert res.info.download_url == "https://github.com/dl/zip"
    assert res.info.download_fallback_urls == (
        "https://api.github.com/repos/serrebidev/BlindRSS/releases/assets/2",
    )


def test_installed_build_carries_installer_fallback_urls(monkeypatch):
    release = _release_with_rest_urls()
    release["assets"].append(
        {
            "name": "BlindRSS-Setup-v999.0.0.exe",
            "browser_download_url": "https://github.com/dl/setup",
            "url": "https://api.github.com/repos/serrebidev/BlindRSS/releases/assets/3",
        }
    )
    manifest: dict = dict(MANIFEST)
    manifest["installer"] = {
        "asset": "BlindRSS-Setup-v999.0.0.exe",
        "sha256": "b" * 64,
    }

    monkeypatch.setattr(updater, "current_platform", lambda: "windows")
    monkeypatch.setattr(updater, "is_windows_installed_build", lambda: True)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: (release, None))
    monkeypatch.setattr(
        updater, "_download_json", lambda url, timeout=20, fallback_urls=(): (manifest, None)
    )

    res = updater.check_for_updates()
    assert res.status == "update_available"
    assert res.info is not None
    assert res.info.asset_kind == "installer"
    assert res.info.download_url == "https://github.com/dl/setup"
    assert res.info.download_fallback_urls == (
        "https://api.github.com/repos/serrebidev/BlindRSS/releases/assets/3",
    )
