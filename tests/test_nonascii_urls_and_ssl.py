# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Non-ASCII feed URLs (issue #41) and SSL certificate tolerance (issue #42).

#41: IDN hostnames must be converted to Punycode and non-ASCII path/query
characters percent-encoded at the request layer, without changing how URLs
are stored or displayed.

#42: Feed fetches that fail certificate validation retry once without
verification (logged), unless "ignore_feed_ssl_errors" is set to false.
"""
import os
import sys
import uuid

import pytest
import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db as db
import core.utils as utils
import providers.local as local_mod
from providers.local import LocalProvider


# --- issue #41: URL encoding -------------------------------------------------


def test_encode_non_ascii_url_punycodes_idn_domain():
    assert (
        utils.encode_non_ascii_url("http://пример.рф/feed.xml")
        == "http://xn--e1afmkfd.xn--p1ai/feed.xml"
    )


def test_encode_non_ascii_url_percent_encodes_path_and_query():
    encoded = utils.encode_non_ascii_url("https://example.com/категория?тег=новости")
    assert encoded == (
        "https://example.com/%D0%BA%D0%B0%D1%82%D0%B5%D0%B3%D0%BE%D1%80%D0%B8%D1%8F"
        "?%D1%82%D0%B5%D0%B3=%D0%BD%D0%BE%D0%B2%D0%BE%D1%81%D1%82%D0%B8"
    )


def test_encode_non_ascii_url_leaves_ascii_urls_unchanged():
    url = "https://example.com/feed.xml?page=2#frag"
    assert utils.encode_non_ascii_url(url) == url


def test_encode_non_ascii_url_does_not_double_encode():
    url = "https://example.com/%D0%BA%D0%B0%D1%82?q=%20x"
    assert utils.encode_non_ascii_url(url) == url
    mixed = utils.encode_non_ascii_url("https://example.com/%D0%BA%D0%B0%D1%82/новое")
    assert mixed == "https://example.com/%D0%BA%D0%B0%D1%82/%D0%BD%D0%BE%D0%B2%D0%BE%D0%B5"


def test_encode_non_ascii_url_preserves_port():
    assert (
        utils.encode_non_ascii_url("http://пример.рф:8080/feed")
        == "http://xn--e1afmkfd.xn--p1ai:8080/feed"
    )


def test_encode_non_ascii_url_handles_cyrillic_domain_and_path_from_issue_41():
    assert (
        utils.encode_non_ascii_url("https://\u0446\u0435\u0439\u043a\u043e\u0432\u0435\u0446.\u0440\u0444/\u0442\u0435\u0441\u0442.xml")
        == "https://xn--b1afbofy6cg.xn--p1ai/%D1%82%D0%B5%D1%81%D1%82.xml"
    )


def test_referer_for_url_punycodes_idn_domain():
    assert (
        utils.referer_for_url("https://\u0446\u0435\u0439\u043a\u043e\u0432\u0435\u0446.\u0440\u0444/\u0442\u0435\u0441\u0442.xml")
        == "https://xn--b1afbofy6cg.xn--p1ai/"
    )


def test_encode_non_ascii_url_preserves_ipv6_brackets():
    assert utils.encode_non_ascii_url("http://[::1]:8080/feed") == "http://[::1]:8080/feed"


def test_safe_requests_get_normalizes_url(monkeypatch):
    seen = {}

    class _FakeSession:
        def get(self, url, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            raise RuntimeError("stop here")

    monkeypatch.setattr(utils, "_get_plain_session", lambda: _FakeSession())
    with pytest.raises(RuntimeError):
        utils.safe_requests_get("http://пример.рф/лента.xml")
    assert seen["url"] == "http://xn--e1afmkfd.xn--p1ai/%D0%BB%D0%B5%D0%BD%D1%82%D0%B0.xml"


def test_safe_requests_get_normalizes_url_headers(monkeypatch):
    seen = {}

    class _FakeSession:
        def get(self, url, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            raise RuntimeError("stop here")

    monkeypatch.setattr(utils, "_get_plain_session", lambda: _FakeSession())
    with pytest.raises(RuntimeError):
        utils.safe_requests_get(
            "https://\u0446\u0435\u0439\u043a\u043e\u0432\u0435\u0446.\u0440\u0444/\u0442\u0435\u0441\u0442.xml",
            headers={"Referer": "https://\u0446\u0435\u0439\u043a\u043e\u0432\u0435\u0446.\u0440\u0444/"},
        )

    assert seen["url"] == "https://xn--b1afbofy6cg.xn--p1ai/%D1%82%D0%B5%D1%81%D1%82.xml"
    assert seen["headers"]["Referer"] == "https://xn--b1afbofy6cg.xn--p1ai/"


def test_refresh_error_formatter_handles_non_http_exceptions():
    err = UnicodeEncodeError(
        "latin-1",
        "\u0446\u0435\u0439\u043a\u043e\u0432\u0435\u0446.\u0440\u0444",
        0,
        1,
        "ordinal not in range",
    )
    msg = local_mod._format_refresh_error(err)

    assert msg.startswith("Error: ")
    assert "object has no attribute 'response'" not in msg


# --- issue #42: SSL certificate tolerance ------------------------------------


SIMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Cert Problem Feed</title>
    <link>https://selfsigned.example.com/</link>
    <description>d</description>
    <item>
      <guid>cert-entry-1</guid>
      <title>Episode One</title>
      <link>https://selfsigned.example.com/1</link>
      <description>body</description>
    </item>
  </channel>
</rss>
"""


class _DummyResp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200
        self.headers = {"Content-Type": "application/rss+xml"}
        self.url = "https://selfsigned.example.com/feed.xml"

    def raise_for_status(self) -> None:
        pass


def _make_provider(tmp_path, monkeypatch, **config_overrides):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    config = {
        "providers": {"local": {}},
        "feed_timeout_seconds": 2,
        "feed_retry_attempts": 0,
        "max_concurrent_refreshes": 1,
        "per_host_max_connections": 1,
    }
    config.update(config_overrides)
    return LocalProvider(config)


def _insert_feed() -> str:
    feed_id = str(uuid.uuid4())
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (feed_id, "https://selfsigned.example.com/feed.xml", "Cert Feed", "Tests", ""),
        )
        conn.commit()
    finally:
        conn.close()
    return feed_id


def _ssl_failing_get(url, **kwargs):
    if kwargs.get("verify") is False:
        return _DummyResp(SIMPLE_RSS)
    raise requests.exceptions.SSLError(
        "HTTP 0: Failed to perform, curl: (60) SSL certificate problem: "
        "unable to get local issuer certificate."
    )


def test_feed_loads_despite_ssl_certificate_error(tmp_path, monkeypatch):
    provider = _make_provider(tmp_path, monkeypatch)
    feed_id = _insert_feed()
    monkeypatch.setattr(local_mod.utils, "safe_requests_get", _ssl_failing_get)

    assert provider.refresh_feed(feed_id) is True

    articles = provider.get_articles(feed_id=feed_id)
    assert len(articles) == 1
    assert articles[0].title == "Episode One"


def test_strict_ssl_config_keeps_certificate_errors_fatal(tmp_path, monkeypatch):
    provider = _make_provider(tmp_path, monkeypatch, ignore_feed_ssl_errors=False)
    feed_id = _insert_feed()
    monkeypatch.setattr(local_mod.utils, "safe_requests_get", _ssl_failing_get)

    provider.refresh_feed(feed_id)

    assert provider.get_articles(feed_id=feed_id) == []


def test_ssl_error_detector_matches_curl_and_requests_shapes():
    detector = local_mod._looks_like_ssl_certificate_error
    assert detector(requests.exceptions.SSLError("certificate verify failed"))
    assert detector(Exception("curl: (60) SSL certificate problem: self-signed certificate"))
    assert detector(Exception("certificate has expired"))
    assert not detector(Exception("HTTP 404: not found"))
    assert not detector(requests.exceptions.ConnectionError("connection reset by peer"))
