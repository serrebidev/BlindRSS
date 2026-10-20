"""Hosted providers must not report writes rejected by the server as saved."""

import json

import pytest
import requests

from providers.bazqux import BazQuxProvider
from providers.inoreader import InoreaderProvider
from providers.theoldreader import TheOldReaderProvider


def _response(status, payload=None):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload or {}).encode()
    return response


@pytest.mark.parametrize("provider_class", [BazQuxProvider, TheOldReaderProvider])
@pytest.mark.parametrize("method,args", [
    ("mark_read", ("item",)),
    ("mark_unread", ("item",)),
    ("set_favorite", ("item", True)),
])
@pytest.mark.parametrize("status,want", [(200, True), (401, False), (500, False)])
def test_article_mutation_reports_http_failure(monkeypatch, provider_class, method, args, status, want):
    provider = provider_class({})
    monkeypatch.setattr(provider, "_login", lambda: True)
    transport = provider.session if isinstance(provider, BazQuxProvider) else requests
    monkeypatch.setattr(transport, "post", lambda *args, **kwargs: _response(status))
    assert getattr(provider, method)(*args) is want


@pytest.mark.parametrize("provider_class", [BazQuxProvider, TheOldReaderProvider])
@pytest.mark.parametrize("method,args", [
    ("remove_feed", ("feed/https://example.com/rss",)),
    ("delete_category", ("News",)),
])
@pytest.mark.parametrize("status,want", [(200, True), (403, False), (503, False)])
def test_subscription_mutation_reports_http_failure(monkeypatch, provider_class, method, args, status, want):
    provider = provider_class({})
    monkeypatch.setattr(provider, "_login", lambda: True)
    transport = provider.session if isinstance(provider, BazQuxProvider) else requests
    monkeypatch.setattr(transport, "post", lambda *args, **kwargs: _response(status))
    assert getattr(provider, method)(*args) is want


@pytest.mark.parametrize("status,want", [(200, True), (403, False), (500, False)])
def test_oldreader_subscribe_reports_http_failure(monkeypatch, status, want):
    from core import discovery

    provider = TheOldReaderProvider({})
    monkeypatch.setattr(provider, "_login", lambda: True)
    monkeypatch.setattr(discovery, "get_ytdlp_feed_url", lambda url: None)
    monkeypatch.setattr(discovery, "discover_feed", lambda url: url)
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: _response(status))
    assert provider.add_feed("https://example.com/rss") is want


@pytest.mark.parametrize("provider_class", [BazQuxProvider, TheOldReaderProvider, InoreaderProvider])
@pytest.mark.parametrize("status,categories,want", [
    (500, [], None),
    (200, [], True),
    (200, ["user/-/state/com.google/starred"], False),
])
def test_favorite_toggle_reports_only_saved_state(monkeypatch, provider_class, status, categories, want):
    provider = provider_class({})
    get_response = _response(200, {"items": [{"categories": categories}]})
    if isinstance(provider, InoreaderProvider):
        monkeypatch.setattr(provider, "_has_required_auth", lambda: True)

        def request(method, *args, **kwargs):
            response = get_response if method == "get" else _response(status)
            response.raise_for_status()
            return response

        monkeypatch.setattr(provider, "_request", request)
    else:
        monkeypatch.setattr(provider, "_login", lambda: True)
        transport = provider.session if isinstance(provider, BazQuxProvider) else requests
        monkeypatch.setattr(transport, "get", lambda *args, **kwargs: get_response)
        monkeypatch.setattr(transport, "post", lambda *args, **kwargs: _response(status))
    assert provider.toggle_favorite("item") is want
