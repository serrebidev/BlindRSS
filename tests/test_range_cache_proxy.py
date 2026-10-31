# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import sys
import tempfile
import threading
import time
import http.client
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.range_cache_proxy import RangeCacheProxy, _Entry, _parse_range_header


def test_parse_range_open_ended_keeps_end_none_when_length_known():
    # Open-ended ranges should keep end=None so the caller can clamp
    # to a small inline window for responsive startup.
    assert _parse_range_header("bytes=0-", 1000) == (0, None)


def test_parse_range_open_ended_keeps_end_none_when_length_unknown():
    assert _parse_range_header("bytes=512-", None) == (512, None)


def test_parse_range_clamps_end_to_length():
    # Explicit end should still be clamped to known length.
    assert _parse_range_header("bytes=100-200", 150) == (100, 149)


def test_proxify_background_probe_does_not_hold_entry_lock(monkeypatch):
    """
    Regression test:
    The background probe kicked off by proxify() must not hold ent.lock while it
    does network work. If it does, the /media handler blocks on cache/segment
    bookkeeping and playback can stall for many seconds.
    """

    started = threading.Event()

    def slow_probe(self: _Entry) -> None:
        started.set()
        # Simulate a slow network probe without doing real IO.
        time.sleep(1.0)
        try:
            self._probe_done.set()
        except Exception:
            pass

    monkeypatch.setattr(_Entry, "probe", slow_probe, raising=True)

    cache_dir = tempfile.mkdtemp(prefix="BlindRSS_test_cache_")
    proxy = RangeCacheProxy(cache_dir=cache_dir, background_download=False)
    try:
        proxied = proxy.proxify("https://example.invalid/audio.mp3", headers={"User-Agent": "test"})
        assert "/media?id=" in proxied
        sid = proxied.split("id=", 1)[1]
        ent = proxy._entries[sid]

        assert started.wait(timeout=2.0), "background probe never started"

        # If the probe holds ent.lock, this will block until the sleep completes.
        done = threading.Event()

        def _call() -> None:
            try:
                ent._find_best_segment_covering(0)
            finally:
                done.set()

        t = threading.Thread(target=_call, daemon=True)
        t.start()

        assert done.wait(timeout=0.2), "entry lock appears to be held during background probe"
    finally:
        try:
            proxy.stop()
        except Exception:
            pass


def test_head_waits_for_probe_metadata_before_reporting_media():
    """
    Regression test:
    VLC may issue HEAD /media before the background range probe has finished.
    The proxy should wait briefly for that in-flight probe so VLC sees content
    length metadata and treats the local proxy URL as seekable.
    """

    cache_dir = tempfile.mkdtemp(prefix="BlindRSS_test_cache_")
    proxy = RangeCacheProxy(cache_dir=cache_dir, background_download=False)
    proxy.start()
    try:
        ent = _Entry(
            url="https://example.invalid/audio.m4a",
            headers={"User-Agent": "test"},
            cache_dir=cache_dir,
            prefetch_bytes=64 * 1024,
            initial_burst_bytes=64 * 1024,
            initial_inline_prefetch_bytes=0,
            background_download=False,
            background_chunk_bytes=64 * 1024,
        )

        class _ProbeDone:
            wait_called = False

            def is_set(self):
                return False

            def wait(self, timeout=None):
                self.wait_called = True
                ent.total_length = 12345
                ent.content_type = "audio/mp4"
                ent.range_supported = True
                return True

        probe_done = _ProbeDone()
        ent._probe_done = probe_done
        sid = "headwait"
        proxy._entries[sid] = ent

        parsed = urlparse(proxy.base_url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            conn.request("HEAD", f"/media?id={sid}")
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 200
            assert probe_done.wait_called is True
            assert resp.getheader("Content-Length") == "12345"
            assert resp.getheader("Content-Type") == "audio/mp4"
            assert resp.getheader("Accept-Ranges") == "bytes"
        finally:
            conn.close()
    finally:
        try:
            proxy.stop()
        except Exception:
            pass


def test_background_download_caps_each_origin_request_at_10_mib(tmp_path):
    """googlevideo answers ranges over ~10 MiB at ~31 KB/s, so the 64 MB
    bootstrap must be fetched in <= 10 MiB requests, still from byte 0."""
    from core import range_cache_proxy as rcp

    mib = 1024 * 1024
    total = 40 * mib
    ent = _Entry(
        url="https://rr1---sn-x.googlevideo.com/videoplayback?id=1",
        headers={},
        cache_dir=str(tmp_path),
        prefetch_bytes=16 * mib,
        initial_burst_bytes=64 * mib,
        initial_inline_prefetch_bytes=0,
        background_download=True,
        background_chunk_bytes=8 * mib,
    )
    ent.total_length = total
    ent.range_supported = True
    ent._probe_done.set()

    requested = []
    done = threading.Event()

    def _fake_fetch_range(start, end, check_abort=None):
        requested.append((start, end))
        with ent.lock:
            ent.segments = rcp._normalize_segments(ent.segments + [(start, end)])
        if end >= total - 1:
            done.set()
        return True

    ent._fetch_range = _fake_fetch_range
    ent.maybe_start_background_download()
    try:
        assert done.wait(timeout=10.0), f"background download stalled: {requested}"
    finally:
        ent.stop_background()

    assert requested[0][0] == 0
    assert all((e - s + 1) <= 10 * mib for s, e in requested), requested
    covered = sum(e - s + 1 for s, e in requested)
    assert covered == total


def test_passthrough_relays_an_encoded_body_as_sent(tmp_path, local_tcp_server):
    """An origin that gzips anyway: the proxy forwards its Content-Encoding and
    Content-Length, so the body must be the same raw bytes, not decoded ones."""
    import gzip
    from http.server import BaseHTTPRequestHandler, HTTPServer

    payload = b"ID3" + b"A" * 100_000
    packed = gzip.compress(payload)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):  # ignores Range and Accept-Encoding: identity
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(packed)))
            self.end_headers()
            self.wfile.write(packed)

    origin = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    proxy = RangeCacheProxy(cache_dir=str(tmp_path), background_download=False)
    proxy.start()
    try:
        url = f"http://127.0.0.1:{origin.server_address[1]}/episode.mp3"
        local = urlparse(proxy.proxify(url, headers={}))
        conn = http.client.HTTPConnection(local.hostname, local.port, timeout=10)
        try:
            conn.request("GET", f"{local.path}?{local.query}")
            resp = conn.getresponse()
            data = resp.read()
        finally:
            conn.close()
        assert resp.getheader("Content-Encoding") == "gzip"
        assert data == packed
    finally:
        proxy.stop()
        origin.shutdown()
        origin.server_close()


def test_media_requests_ask_the_origin_for_identity_encoding(tmp_path):
    """Range math needs the raw bytes. setdefault() never applied "identity"
    because the shared HEADERS already ask for gzip/deflate/br."""
    import io

    import requests

    seen = []

    class _OfflineSession:
        def get(self, _url, headers=None, **_kwargs):
            seen.append(dict(headers or {}))
            raise requests.ConnectionError("offline")

        def close(self):
            pass

    def _entry(probed):
        ent = _Entry(
            url="https://cdn.example.invalid/episode.mp3",
            headers={"User-Agent": "test"},
            cache_dir=str(tmp_path),
            prefetch_bytes=64 * 1024,
            initial_burst_bytes=64 * 1024,
            initial_inline_prefetch_bytes=0,
            background_download=False,
            background_chunk_bytes=64 * 1024,
        )
        ent._make_session = _OfflineSession
        if probed:
            ent.total_length = 1000
            ent.range_supported = True
            ent._probe_done.set()
        return ent

    _entry(probed=False).probe()
    _entry(probed=True)._fetch_range(0, 10)  # also re-resolves after the failure
    _entry(probed=True).stream_origin_range_to_and_cache(0, 10, io.BytesIO())

    # Origin without range support: the handler streams straight through.
    passthrough = _entry(probed=False)
    passthrough.range_supported = False
    passthrough._probe_done.set()
    proxy = RangeCacheProxy(cache_dir=str(tmp_path), background_download=False)
    proxy.start()
    try:
        proxy._entries["passthrough"] = passthrough
        parsed = urlparse(proxy.base_url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        try:
            conn.request("GET", "/media?id=passthrough", headers={"Range": "bytes=0-"})
            conn.getresponse().read()
        finally:
            conn.close()
    finally:
        proxy.stop()

    assert len(seen) >= 5, seen  # probe, range, re-resolve, stream, pass-through
    assert all(h.get("Accept-Encoding") == "identity" for h in seen), seen


def _origin_refusing_first_ranges(refusals, total=200_000):
    """Mock googlevideo: answers the first `refusals` range requests with 403."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    body = bytes(i % 251 for i in range(total))
    state = {"range_requests": 0, "statuses": []}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = self.headers.get("Range", "")
            if rng:
                state["range_requests"] += 1
            if rng and state["range_requests"] <= refusals:
                state["statuses"].append(403)
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, end = 0, total - 1
            if rng.startswith("bytes="):
                a, _, b = rng[len("bytes="):].partition("-")
                start, end = int(a or 0), min(int(b or total - 1), total - 1)
            chunk = body[start:end + 1]
            state["statuses"].append(206 if rng else 200)
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", "audio/mp4")
            self.send_header("Accept-Ranges", "bytes")
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state, body


def test_probe_retries_a_forbidden_first_answer(monkeypatch, tmp_path, local_tcp_server, caplog):
    """googlevideo can answer the proxy's first probe with 403; the entry was
    then marked "no range support" for the whole session."""
    from core import range_cache_proxy as rcp

    monkeypatch.setattr(rcp, "_PROBE_FORBIDDEN_RETRY_S", 0.05, raising=False)
    server, state, _body = _origin_refusing_first_ranges(refusals=1)
    try:
        ent = _Entry(
            url=f"http://127.0.0.1:{server.server_address[1]}/videoplayback",
            headers={},
            cache_dir=str(tmp_path),
            prefetch_bytes=64 * 1024,
            initial_burst_bytes=64 * 1024,
            initial_inline_prefetch_bytes=0,
            background_download=False,
            background_chunk_bytes=64 * 1024,
        )
        with caplog.at_level("DEBUG", logger="core.range_cache_proxy"):
            ent.probe()
        assert state["statuses"] == [403, 206]
        assert ent.range_supported is True
        assert ent.total_length == 200_000
        # Visible in a live DEBUG log, without the (signed) URL.
        lines = [r.getMessage() for r in caplog.records]
        assert any(line.startswith("RangeCacheProxy probe refused (HTTP 403); retrying once") for line in lines)
        assert not any("127.0.0.1" in line or "videoplayback" in line for line in lines)
    finally:
        server.shutdown()
        server.server_close()


def test_vlc_never_gets_the_origins_passing_403(monkeypatch, tmp_path, local_tcp_server, caplog):
    """Through the proxy: probe refused, then VLC's first range request got
    the origin's 403 relayed and VLC sat in Opening until the stall watchdog
    gave up on the stream."""
    from core import range_cache_proxy as rcp

    monkeypatch.setattr(rcp, "_PROBE_FORBIDDEN_RETRY_S", 0.05, raising=False)
    # Three refusals: the background probe and its retry use two, so VLC's
    # request is answered by await_probe probing again (403, then 206). Without
    # that re-probe the request passes through and VLC gets the third 403.
    origin, state, body = _origin_refusing_first_ranges(refusals=3)
    proxy = RangeCacheProxy(cache_dir=str(tmp_path), background_download=False)
    proxy.start()
    try:
        url = f"http://127.0.0.1:{origin.server_address[1]}/videoplayback?expire=1"
        with caplog.at_level("DEBUG", logger="core.range_cache_proxy"):
            local = urlparse(proxy.proxify(url, headers={}, skip_redirect_resolve=True))
            conn = http.client.HTTPConnection(local.hostname, local.port, timeout=10)
            try:
                conn.request("GET", f"{local.path}?{local.query}", headers={"Range": "bytes=0-"})
                resp = conn.getresponse()
                data = resp.read()
            finally:
                conn.close()
        assert resp.status == 206, state["statuses"]
        assert any(r.getMessage().startswith("RangeCacheProxy probe still refused (HTTP 403)")
                   for r in caplog.records)
        assert resp.getheader("Content-Range", "").endswith("/200000")
        assert data == body[: len(data)] and data
    finally:
        proxy.stop()
        origin.shutdown()
        origin.server_close()
