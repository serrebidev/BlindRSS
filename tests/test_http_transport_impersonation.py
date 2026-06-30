"""Tests for the browser-header / TLS-impersonation HTTP transport (issue #29)."""

import logging
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import utils


class _FakeResp:
    def __init__(self, tag):
        self.tag = tag
        self.status_code = 200


class _Recorder:
    """Stand-in for requests / curl_cffi.requests that records calls."""

    def __init__(self, tag):
        self.tag = tag
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return _FakeResp(self.tag)

    def head(self, url, **kwargs):
        self.calls.append(("head", url, kwargs))
        return _FakeResp(self.tag)


def test_headers_have_modern_browser_fingerprint():
    expected = {
        "User-Agent",
        "Accept",
        "Accept-Language",
        "Accept-Encoding",
        "Upgrade-Insecure-Requests",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "Sec-Fetch-Dest",
        "Sec-Fetch-Mode",
        "Sec-Fetch-Site",
        "Sec-Fetch-User",
        "Connection",
    }
    assert expected.issubset(set(utils.HEADERS.keys()))
    assert "Chrome" in utils.HEADERS["User-Agent"]


def test_referer_for_url():
    assert utils.referer_for_url("https://www.apkmirror.com/apk/x/feed/") == "https://www.apkmirror.com/"
    assert utils.referer_for_url("http://example.com:8080/a?b=1") == "http://example.com:8080/"
    assert utils.referer_for_url("not a url") == ""
    assert utils.referer_for_url("") == ""


def test_plain_get_merges_default_headers(monkeypatch):
    rec = _Recorder("requests")
    monkeypatch.setattr(utils, "requests", rec)
    resp = utils.safe_requests_get("https://example.com/feed", headers={"Referer": "https://example.com/"})
    assert resp.tag == "requests"
    method, url, kwargs = rec.calls[0]
    assert method == "get" and url == "https://example.com/feed"
    sent = kwargs["headers"]
    # Default fingerprint headers are merged in, caller header preserved.
    assert sent["User-Agent"] == utils.HEADERS["User-Agent"]
    assert sent["Referer"] == "https://example.com/"


def test_impersonate_routes_to_curl_cffi_without_static_ua(monkeypatch):
    curl_rec = _Recorder("curl")
    req_rec = _Recorder("requests")
    monkeypatch.setattr(utils, "requests", req_rec)
    monkeypatch.setattr(utils, "_CURL_REQUESTS", curl_rec)
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", True)

    resp = utils.safe_requests_get(
        "https://www.apkmirror.com/feed/",
        headers={"Referer": "https://www.apkmirror.com/"},
        timeout=15,
        impersonate=True,
    )
    assert resp.tag == "curl"
    assert req_rec.calls == []  # did not fall through to plain requests
    method, url, kwargs = curl_rec.calls[0]
    assert kwargs["impersonate"] == utils.IMPERSONATE_TARGET
    assert kwargs["timeout"] == 15
    sent = kwargs["headers"]
    # Let curl_cffi supply the fingerprint; we must NOT pin a static User-Agent.
    assert "User-Agent" not in sent
    assert sent["Referer"] == "https://www.apkmirror.com/"
    # An Accept is still ensured so feeds negotiate correctly.
    assert "Accept" in sent


def test_impersonate_falls_back_when_curl_unavailable(monkeypatch):
    req_rec = _Recorder("requests")
    monkeypatch.setattr(utils, "requests", req_rec)
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", False)

    resp = utils.safe_requests_get("https://example.com/feed", impersonate=True)
    assert resp.tag == "requests"
    sent = req_rec.calls[0][2]["headers"]
    assert sent["User-Agent"] == utils.HEADERS["User-Agent"]


def test_head_impersonates_too(monkeypatch):
    curl_rec = _Recorder("curl")
    monkeypatch.setattr(utils, "_CURL_REQUESTS", curl_rec)
    monkeypatch.setattr(utils, "CURL_CFFI_AVAILABLE", True)
    resp = utils.safe_requests_head("https://example.com/feed", impersonate=True)
    assert resp.tag == "curl"
    assert curl_rec.calls[0][0] == "head"
    assert curl_rec.calls[0][2]["impersonate"] == utils.IMPERSONATE_TARGET


def test_request_logging_redacts_secrets(monkeypatch, caplog):
    req_rec = _Recorder("requests")
    monkeypatch.setattr(utils, "requests", req_rec)
    with caplog.at_level(logging.DEBUG, logger=utils.log.name):
        utils.safe_requests_get(
            "https://example.com/feed",
            headers={"Authorization": "Bearer hunter2", "Cookie": "sid=abc", "X-Public": "ok"},
        )
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "hunter2" not in blob
    assert "sid=abc" not in blob
    assert "<redacted>" in blob
    assert "X-Public" in blob  # non-sensitive headers are still logged
