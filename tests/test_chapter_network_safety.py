import json
import os
import socket
import time
import uuid

import pytest

import core.db
from core import utils


class _Response:
    def __init__(self, payload=None, *, content=b"", status_code=200, headers=None):
        self.payload = payload
        self.content = bytes(content)
        self.status_code = int(status_code)
        self.ok = self.status_code < 400
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        raw = self.content
        if not raw and self.payload is not None:
            raw = json.dumps(self.payload).encode()
        for index in range(0, len(raw), chunk_size):
            yield raw[index:index + chunk_size]

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


@pytest.fixture
def chapter_db(tmp_path):
    original = core.db.DB_FILE
    core.db.DB_FILE = os.path.join(tmp_path, "rss.db")
    core.db.init_db()
    try:
        yield
    finally:
        core.db.DB_FILE = original


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    # This models the pre-request DNS validation only. Requests performs a
    # second lookup when connecting, so the production code deliberately
    # documents rather than overclaims protection from DNS rebinding.
    def fake_getaddrinfo(host, port, type=0, **_kwargs):
        assert type == socket.SOCK_STREAM
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(utils.socket, "getaddrinfo", fake_getaddrinfo)


def test_304_without_cached_rows_retries_without_validators(monkeypatch, chapter_db):
    cache_key = utils.build_chapter_cache_key("reader", "article")
    utils._save_chapter_source(
        "article",
        "https://chapters.example/episode.json",
        cache_key=cache_key,
        etag='"old"',
        last_modified="Wed, 24 Jun 2026 12:00:00 GMT",
        checked_at=0,
        fetched_at=0,
    )
    responses = [
        _Response(status_code=304, headers={"ETag": '"old"'}),
        _Response(
            {
                "version": "1.2.0",
                "chapters": [{"startTime": 0, "title": "Recovered"}],
            },
            headers={"Content-Type": "application/json+chapters", "ETag": '"new"'},
        ),
    ]
    seen_headers = []

    def fake_get(_url, **kwargs):
        seen_headers.append(dict(kwargs["headers"]))
        return responses.pop(0)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    chapters = utils.fetch_and_store_chapters(
        "article",
        None,
        None,
        chapter_url="https://chapters.example/episode.json",
        allow_id3=False,
        cache_key=cache_key,
        force_refresh=True,
    )

    assert chapters == [{"start": 0.0, "title": "Recovered", "href": None}]
    assert seen_headers[0]["If-None-Match"] == '"old"'
    assert "If-None-Match" not in seen_headers[1]
    assert "If-Modified-Since" not in seen_headers[1]


def test_chapter_dns_rejects_any_non_global_answer_before_request(monkeypatch):
    def mixed_dns(_host, port, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0)),
        ]

    monkeypatch.setattr(utils.socket, "getaddrinfo", mixed_dns)
    monkeypatch.setattr(
        utils,
        "safe_requests_get",
        lambda *_args, **_kwargs: pytest.fail("private DNS target must not be requested"),
    )

    with pytest.raises(ValueError, match="private or local"):
        utils._fetch_chapter_json("https://chapters.example/episode.json")


def test_chapter_redirect_resolves_and_rejects_private_hostname(monkeypatch):
    resolved_hosts = []
    calls = []

    def fake_dns(host, port, **_kwargs):
        resolved_hosts.append(host)
        address = "10.0.0.8" if host == "internal.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    def fake_get(url, **_kwargs):
        calls.append(url)
        return _Response(
            status_code=302,
            headers={"Location": "http://internal.example/private.json"},
        )

    monkeypatch.setattr(utils.socket, "getaddrinfo", fake_dns)
    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    with pytest.raises(ValueError, match="private or local"):
        utils._fetch_chapter_json("https://chapters.example/episode.json")

    assert calls == ["https://chapters.example/episode.json"]
    assert resolved_hosts == ["chapters.example", "internal.example"]


def test_remote_media_probe_uses_manual_bounded_redirect_validation(monkeypatch):
    calls = []
    responses = [
        _Response(status_code=302, headers={"Location": "https://cdn.example/tag"}),
        _Response(content=b"ID3payload", status_code=206),
    ]

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    assert utils._read_prefix_bytes(
        "https://media.example/episode.mp3",
        headers={"Range": "bytes=0-9"},
        max_bytes=10,
        timeout_s=6,
    ) == b"ID3payload"
    assert [url for url, _kwargs in calls] == [
        "https://media.example/episode.mp3",
        "https://cdn.example/tag",
    ]
    assert all(kwargs["allow_redirects"] is False for _url, kwargs in calls)


def test_remote_media_redirect_rejects_private_dns_target(monkeypatch):
    calls = []

    def fake_dns(host, port, **_kwargs):
        address = "192.168.1.9" if host == "lan.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    def fake_get(url, **_kwargs):
        calls.append(url)
        return _Response(
            status_code=302,
            headers={"Location": "http://lan.example/tag"},
        )

    monkeypatch.setattr(utils.socket, "getaddrinfo", fake_dns)
    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    with pytest.raises(ValueError, match="private or local"):
        utils._read_prefix_bytes(
            "https://media.example/episode.mp3",
            headers={"Range": "bytes=0-9"},
            max_bytes=10,
            timeout_s=6,
        )

    assert calls == ["https://media.example/episode.mp3"]


def test_remote_media_redirect_count_is_bounded(monkeypatch):
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        return _Response(status_code=302, headers={"Location": "/again"})

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    with pytest.raises(ValueError, match="too many media redirects"):
        utils._read_prefix_bytes(
            "https://media.example/again",
            headers={"Range": "bytes=0-9"},
            max_bytes=10,
            timeout_s=6,
        )

    assert len(calls) == utils._MAX_CHAPTER_REDIRECTS + 1


@pytest.mark.parametrize(
    "path",
    [
        r"\\server\share\episode.mp3",
        "//server/share/episode.mp3",
        "file://server/share/episode.mp3",
        "file://user:secret@server/share/episode.mp3",
    ],
)
def test_local_media_path_rejects_network_share_forms_without_stat(
    monkeypatch,
    path,
):
    monkeypatch.setattr(
        utils.os.path,
        "isfile",
        lambda _path: pytest.fail("network path must not be touched"),
    )

    assert utils._local_media_path(path) is None


def test_remote_media_probe_rejects_private_dns_target(monkeypatch):
    monkeypatch.setattr(
        utils.socket,
        "getaddrinfo",
        lambda _host, port, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
        ],
    )
    monkeypatch.setattr(
        utils,
        "safe_requests_get",
        lambda *_args, **_kwargs: pytest.fail("private media target must not be requested"),
    )

    with pytest.raises(ValueError, match="private or local"):
        utils._read_prefix_bytes(
            "https://media.example/episode.mp3",
            headers={"Range": "bytes=0-9"},
            max_bytes=10,
            timeout_s=6,
        )


def test_provider_cache_keys_are_collision_safe():
    assert utils.build_chapter_cache_key("miniflux", "article-1") == (
        "miniflux:article-1"
    )
    assert utils.build_chapter_cache_key("a:b", "c") != (
        utils.build_chapter_cache_key("a", "b:c")
    )


def test_hosted_cache_cleanup_preserves_local_and_recent_sources(chapter_db):
    now = time.time()
    stale_key = utils.build_chapter_cache_key("reader", "stale")
    recent_key = utils.build_chapter_cache_key("reader", "recent")
    orphan_key = utils.build_chapter_cache_key("reader", "orphan")
    conn = core.db.get_connection()
    try:
        conn.executemany(
            "INSERT INTO chapter_cache (id, cache_key, start, title) "
            "VALUES (?, ?, 0, ?)",
            [
                (str(uuid.uuid4()), stale_key, "Stale"),
                (str(uuid.uuid4()), recent_key, "Recent"),
                (str(uuid.uuid4()), orphan_key, "Orphan"),
            ],
        )
        conn.executemany(
            "INSERT INTO chapter_sources "
            "(cache_key, source_url, checked_at, fetched_at) VALUES (?, ?, ?, ?)",
            [
                (stale_key, "https://example.com/stale", now - 100 * 86400, now - 100 * 86400),
                (recent_key, "https://example.com/recent", now, now),
                ("local:article", "https://example.com/local", 0, 0),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    result = core.db.cleanup_hosted_chapter_cache(
        retention_days=90,
        max_sources=10_000,
        now=now,
    )

    conn = core.db.get_connection()
    try:
        cache_keys = {
            row[0] for row in conn.execute("SELECT DISTINCT cache_key FROM chapter_cache")
        }
        source_keys = {
            row[0] for row in conn.execute("SELECT cache_key FROM chapter_sources")
        }
    finally:
        conn.close()

    assert cache_keys == {recent_key}
    assert source_keys == {recent_key, "local:article"}
    assert result == {"sources": 1, "chapters": 2, "orphans": 1}
