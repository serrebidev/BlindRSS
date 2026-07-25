# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Playback start must not pay for local health checks.

Measured before the fix, per YouTube playback:
    yt-dlp resolve   2.23s   (network, irreducible here)
    proxify()        1.07s   <- all of it /health round trips
    is_ready()       0.53s   <- another one, whose result is only logged

/health sent its headers and then wrote the 2-byte body separately; that second
write never reached the client, so every check blocked for the full 0.5s socket
timeout and still reported success because the status line had already parsed.
"""

import http.client
import os
import sys
import threading
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pytest

from core import range_cache_proxy as rcp


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    p = rcp.RangeCacheProxy(cache_dir=str(tmp_path_factory.mktemp("rcp")))
    p.start()
    assert p._wait_ready(timeout=5.0), "proxy did not become ready"
    yield p
    try:
        p.stop()
    except Exception:
        pass


def _health(proxy, timeout=2.0):
    conn = http.client.HTTPConnection(proxy._host, proxy._port, timeout=timeout)
    try:
        conn.request("GET", "/health")
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_health_returns_its_body(proxy):
    """The regression: headers arrived, the body never did."""
    status, body = _health(proxy)
    assert status == 200
    assert body == b"ok"


def test_health_is_fast(proxy):
    t0 = time.perf_counter()
    for _ in range(5):
        status, body = _health(proxy)
        assert (status, body) == (200, b"ok")
    elapsed = time.perf_counter() - t0
    # Five loopback round trips. Before the fix this was ~2.5s (5 x 0.5s timeout).
    assert elapsed < 1.0, f"5 health checks took {elapsed:.2f}s"


def test_wait_ready_requires_the_body(proxy):
    """A half-delivered response must not count as ready."""
    assert proxy._wait_ready(timeout=2.0) is True

    handler = proxy._server.RequestHandlerClass
    original = handler._send_health

    def headers_only(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "2")
        self.end_headers()  # body deliberately withheld

    handler._send_health = headers_only
    try:
        assert proxy._wait_ready(timeout=0.6) is False
    finally:
        handler._send_health = original

    assert proxy._wait_ready(timeout=2.0) is True


def test_proxify_is_fast_when_the_server_is_already_up(proxy):
    proxy.proxify("https://example.test/warm.mp3", headers={"User-Agent": "x"})

    t0 = time.perf_counter()
    for i in range(5):
        url = proxy.proxify(f"https://example.test/media{i}.mp3",
                            headers={"User-Agent": "x"},
                            skip_redirect_resolve=True)
        assert url.startswith(f"http://{proxy._host}:{proxy._port}/media?id=")
    elapsed = time.perf_counter() - t0
    # Was ~1.0s each (two health round trips per call).
    assert elapsed < 0.5, f"5 proxify() calls took {elapsed:.2f}s"


def test_is_ready_does_not_block(proxy):
    assert proxy.is_ready() is True
    t0 = time.perf_counter()
    for _ in range(20):
        proxy.is_ready()
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"20 is_ready() calls took {elapsed:.2f}s"


def test_base_url_does_not_block_once_bound(proxy):
    t0 = time.perf_counter()
    for _ in range(20):
        assert proxy.base_url == f"http://{proxy._host}:{proxy._port}"
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"20 base_url reads took {elapsed:.2f}s"


def test_stale_readiness_is_re_verified(proxy):
    """The cheap path must not blind us to a server that died."""
    assert proxy.is_ready() is True
    proxy._last_ready_check = time.monotonic() - (proxy._READY_RECHECK_SECONDS + 1)

    handler = proxy._server.RequestHandlerClass
    original = handler._send_health
    handler._send_health = lambda self: self.send_error(500, "down")
    try:
        assert proxy.is_ready() is False
    finally:
        handler._send_health = original


def test_entry_stop_background_exists_and_signals(tmp_path):
    """prune() calls this inside a try/except; when it went missing, background
    downloader threads leaked silently."""
    entry = rcp._Entry(
        url="https://example.test/a.mp3",
        headers={},
        cache_dir=str(tmp_path),
        prefetch_bytes=1024,
        initial_burst_bytes=1024,
        initial_inline_prefetch_bytes=1024,
        background_download=False,
        background_chunk_bytes=1024,
    )
    assert hasattr(entry, "stop_background")
    assert not entry._bg_stop.is_set()

    entry.stop_background()

    assert entry._bg_stop.is_set()


def test_entry_stop_background_joins_a_running_thread(tmp_path):
    entry = rcp._Entry(
        url="https://example.test/a.mp3",
        headers={},
        cache_dir=str(tmp_path),
        prefetch_bytes=1024,
        initial_burst_bytes=1024,
        initial_inline_prefetch_bytes=1024,
        background_download=False,
        background_chunk_bytes=1024,
    )
    stopped = threading.Event()

    def _spin():
        while not entry._bg_stop.is_set():
            time.sleep(0.01)
        stopped.set()

    entry._bg_thread = threading.Thread(target=_spin, daemon=True)
    entry._bg_thread.start()

    entry.stop_background()

    assert stopped.wait(timeout=2.0), "background thread was not stopped"
    assert entry._bg_thread is None


def test_dead_proxy_methods_are_gone_from_entry():
    """They referenced attributes _Entry never had, so they could only raise."""
    for name in ("proxify", "is_ready", "base_url", "_wait_ready", "prune"):
        assert not hasattr(rcp._Entry, name), f"_Entry.{name} is back"
