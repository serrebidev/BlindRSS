# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Play directly when the local proxy cannot deliver a response body.

A machine can end up unable to deliver anything a local server writes after
its first send (seen on Windows 11 with the experimental BBR2 congestion
provider). The proxy's /health endpoint answers in a single flush, so it keeps
passing there -- but media serving is all second writes, so VLC would get
headers and then silence. The player has to notice before it hands VLC a proxy
URL, and fall back to the real one.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.range_cache_proxy import RangeCacheProxy
import gui.player as player_mod


def test_health_split_endpoint_reports_real_delivery(tmp_path, local_tcp_server):
    """can_deliver_body() must exercise a two-write response, and pass here."""
    proxy = RangeCacheProxy(cache_dir=str(tmp_path))
    try:
        proxy.start()
        assert proxy.can_deliver_body(timeout=3.0) is True
        # The verdict is cached, so a second call must not re-probe.
        checked_at = proxy._delivery_checked_at
        assert proxy.can_deliver_body(timeout=3.0) is True
        assert proxy._delivery_checked_at == checked_at
    finally:
        proxy.stop()


def test_delivery_probe_fails_when_the_body_never_arrives(tmp_path):
    """The detector must catch the real failure: headers land, body never does.

    This stands in a server that answers with headers only -- exactly what a
    machine in the broken state produces for every response.
    """
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve_headers_only():
        try:
            conn, _ = srv.accept()
            conn.recv(4096)
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\n"
            )
            stop.wait(2.0)          # ...and never the body
            conn.close()
        except Exception:
            pass
        finally:
            try:
                srv.close()
            except Exception:
                pass

    threading.Thread(target=serve_headers_only, daemon=True).start()

    proxy = RangeCacheProxy(cache_dir=str(tmp_path))
    proxy.start = lambda: None      # don't stand up the real server
    proxy._port = port
    try:
        assert proxy.can_deliver_body(timeout=0.6) is False
        assert proxy._delivery_ok is False
    finally:
        stop.set()


def test_negative_verdict_is_rechecked_sooner_than_a_positive_one(tmp_path):
    """A machine repaired mid-session must not stay on the direct path forever."""
    proxy = RangeCacheProxy(cache_dir=str(tmp_path))
    assert proxy._DELIVERY_BAD_SECONDS < proxy._DELIVERY_OK_SECONDS


class _StubProxy:
    """Range-cache proxy stand-in whose delivery verdict the test controls."""

    def __init__(self, deliverable):
        self.deliverable = deliverable
        self.proxify_calls = 0

    def can_deliver_body(self, timeout: float = 1.0):
        return self.deliverable

    def proxify(self, url, headers=None, skip_redirect_resolve=False):
        self.proxify_calls += 1
        return "http://127.0.0.1:9999/media?id=abc"

    def is_ready(self):
        return True


class _StubConfig:
    def __init__(self, values=None):
        self.values = {
            "range_cache_enabled": True,
            "range_cache_apply_all_hosts": True,
            "range_cache_hosts": [],
            "range_cache_dir": "",
            "range_cache_prefetch_kb": 16384,
            "range_cache_inline_window_kb": 1024,
            "range_cache_background_download": False,
            "range_cache_background_chunk_kb": 8192,
            "range_cache_initial_burst_kb": 65536,
            "range_cache_initial_inline_prefetch_kb": 1024,
            "range_cache_debug": False,
            "skip_silence": True,
        }
        self.values.update(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _PlayerHost:
    _maybe_range_cache_url = player_mod.PlayerFrame._maybe_range_cache_url

    def __init__(self):
        self.config_manager = _StubConfig()
        self._last_orig_url = None
        self._last_used_range_proxy = False
        self._last_used_stream_proxy = False
        self._last_range_proxy_headers = {}
        self._last_range_proxy_cache_dir = None
        self._last_range_proxy_prefetch_kb = None
        self._last_range_proxy_initial_burst_kb = None
        self._last_range_proxy_initial_inline_kb = None
        self._last_vlc_url = None
        self._range_proxy_retry_count = 0
        self._stream_proxy_retry_count = 0


MEDIA_URL = "https://cdn.example.com/show/episode-42.mp3"
PODTRAC_URL = (
    "https://www.podtrac.com/pts/redirect.mp3/pdst.fm/e/pscrb.fm/rss/p/"
    "mgln.ai/e/257/traffic.megaphone.fm/VMP1047667987.mp3"
)


@pytest.fixture
def host(monkeypatch):
    return _PlayerHost()


def test_proxy_used_when_delivery_works(host, monkeypatch):
    stub = _StubProxy(deliverable=True)
    monkeypatch.setattr(player_mod, "get_range_cache_proxy", lambda **kw: stub)

    out = host._maybe_range_cache_url(MEDIA_URL)

    assert out.startswith("http://127.0.0.1:")
    assert host._last_used_range_proxy is True
    assert stub.proxify_calls == 1


def test_direct_url_when_proxy_cannot_deliver(host, monkeypatch):
    stub = _StubProxy(deliverable=False)
    monkeypatch.setattr(player_mod, "get_range_cache_proxy", lambda **kw: stub)

    out = host._maybe_range_cache_url(MEDIA_URL)

    # The real URL goes to VLC, and nothing is left claiming the proxy is live
    # (the stall-recovery path keys off _last_used_range_proxy).
    assert out == MEDIA_URL
    assert host._last_used_range_proxy is False
    assert host._last_vlc_url == MEDIA_URL


def test_youtube_also_falls_back_rather_than_playing_silence(host, monkeypatch):
    """googlevideo normally forces the proxy; silence is still worse."""
    stub = _StubProxy(deliverable=False)
    monkeypatch.setattr(player_mod, "get_range_cache_proxy", lambda **kw: stub)
    yt = "https://rr3---sn-abc.googlevideo.com/videoplayback?id=xyz&mime=audio%2Fmp4"

    out = host._maybe_range_cache_url(yt)

    assert out == yt
    assert host._last_used_range_proxy is False


def test_unresolved_podcast_tracker_forces_proxy_when_cache_disabled(host, monkeypatch):
    stub = _StubProxy(deliverable=True)
    host.config_manager.values["range_cache_enabled"] = False
    monkeypatch.setattr(player_mod, "get_range_cache_proxy", lambda **kw: stub)

    out = host._maybe_range_cache_url(PODTRAC_URL)

    assert out.startswith("http://127.0.0.1:")
    assert host._last_used_range_proxy is True
    assert stub.proxify_calls == 1


def test_resolved_podcast_cdn_stays_direct_when_cache_disabled(host, monkeypatch):
    stub = _StubProxy(deliverable=True)
    host.config_manager.values["range_cache_enabled"] = False
    monkeypatch.setattr(player_mod, "get_range_cache_proxy", lambda **kw: stub)
    resolved = "https://dcs-cached.megaphone.fm/episode.mp3?key=fresh"

    out = host._maybe_range_cache_url(resolved)

    assert out == resolved
    assert host._last_used_range_proxy is False
    assert stub.proxify_calls == 0


def test_podcast_tracker_resolution_is_not_disabled_by_skip_silence():
    assert player_mod._should_resolve_direct_media_url(PODTRAC_URL) is True
    assert (
        player_mod._should_resolve_direct_media_url(
            "https://dcs-cached.megaphone.fm/episode.mp3?key=fresh"
        )
        is False
    )
