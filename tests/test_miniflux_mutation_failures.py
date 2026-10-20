"""Miniflux 204 writes return None from _req on success and failure alike.

remove_feed / set_favorite / toggle_favorite must read the request outcome,
not assume success, or a rejected write is reported to the user as saved.
"""

import requests

from providers.miniflux import MinifluxProvider


def _response(status, payload=None):
    resp = requests.Response()
    resp.status_code = status
    resp._content = b"" if payload is None else __import__("json").dumps(payload).encode()
    return resp


class _Session:
    def __init__(self, responder):
        self.responder = responder

    def request(self, method, url, **kwargs):
        return self.responder(method, url)


def _provider(responder):
    prov = MinifluxProvider({"providers": {"miniflux": {"url": "https://mf.example.com", "api_key": "k"}}})
    prov._session = _Session(responder)
    prov._request_retry_attempts = lambda endpoint: 0
    return prov


def test_remove_feed_reports_server_rejection():
    assert _provider(lambda m, u: _response(204)).remove_feed("7") is True
    assert _provider(lambda m, u: _response(500)).remove_feed("7") is False


def _favorite_responder(put_status, starred):
    def respond(method, url):
        if method == "PUT":
            return _response(put_status)
        return _response(200, {"id": 1, "starred": starred})
    return respond


def test_set_favorite_reports_failed_toggle():
    assert _provider(_favorite_responder(204, False)).set_favorite("1", True) is True
    assert _provider(_favorite_responder(403, False)).set_favorite("1", True) is False


def test_toggle_favorite_returns_none_on_failure():
    assert _provider(_favorite_responder(204, True)).toggle_favorite("1") is True
    assert _provider(_favorite_responder(403, False)).toggle_favorite("1") is None
