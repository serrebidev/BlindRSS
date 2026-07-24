# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Miniflux server-side fetch-content must use GET.

The endpoint is GET /v1/entries/{id}/fetch-content; the old PUT form returns 405 on
current Miniflux, which silently disabled the full-text provider fallback. We use GET
and only fall back to PUT if a build rejects GET with 405.
"""

from types import SimpleNamespace

from providers.miniflux import MinifluxProvider


class _FakeResp:
    def __init__(self, status=200, content="full html"):
        self.status_code = status
        self._content = content

    def json(self):
        return {"content": self._content}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            err = requests.HTTPError(response=SimpleNamespace(status_code=self.status_code))
            raise err


class _FakeSession:
    def __init__(self, responder):
        self._responder = responder
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        return self._responder(method, url)


def _provider(responder):
    prov = MinifluxProvider.__new__(MinifluxProvider)
    prov.base_url = "https://mf.example.com"
    prov.headers = {}
    prov.CONNECT_TIMEOUT_SECONDS = 5
    prov._session = _FakeSession(responder)
    return prov


def test_fetch_content_uses_get():
    prov = _provider(lambda method, url: _FakeResp(200, "the full article"))
    out = prov.fetch_full_content("243971", "https://site/x")
    assert out == "the full article"
    assert prov._session.calls[0][0] == "GET"
    assert prov._session.calls[0][1].endswith("/v1/entries/243971/fetch-content")


def test_fetch_content_falls_back_to_put_on_405():
    def responder(method, url):
        return _FakeResp(405) if method == "GET" else _FakeResp(200, "via put")

    prov = _provider(responder)
    out = prov.fetch_full_content("5", "")
    assert out == "via put"
    assert [m for m, _ in prov._session.calls] == ["GET", "PUT"]


def test_fetch_content_404_returns_none_quietly():
    prov = _provider(lambda method, url: _FakeResp(404, ""))
    assert prov.fetch_full_content("9", "") is None


def test_fetch_content_empty_article_id():
    prov = _provider(lambda method, url: _FakeResp(200, "x"))
    assert prov.fetch_full_content("", "") is None
    assert prov._session.calls == []
