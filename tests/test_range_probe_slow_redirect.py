# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The proxy must not advertise the inline window as the whole file.

Reproduces the Simplecast/WNYC bug: podcast enclosures sit behind several
tracker redirects (pscrb.fm -> mgln.ai -> podtrac -> CDN) that can take longer
than the handler's short probe wait. The handler then answered VLC's open-ended
range request with "Content-Range: bytes 0-<window>/*", so VLC adopted the
4 MiB inline window as the entire file: every ~60 minute episode showed 4:22
(4 MiB at 128 kbps) and playback stopped there.

The handler must instead wait for the probe to learn the real total, and fall
back to honest pass-through streaming when the total cannot be learned at all.
"""

import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.range_cache_proxy as rcp

_TOTAL = 400_000
_BODY = bytes((i % 251) for i in range(_TOTAL))


def _parse_range(header, total):
    start, end = 0, total - 1
    if header.startswith("bytes="):
        a, _, b = header[len("bytes="):].partition("-")
        start = int(a or 0)
        if b:
            end = int(b)
    return start, min(end, total - 1)


def _make_origin(redirect_delay_s=0.0, reveal_total=True):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/redirect"):
                if redirect_delay_s:
                    time.sleep(redirect_delay_s)
                self.send_response(302)
                self.send_header("Location", "/file")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path.startswith("/file"):
                start, end = _parse_range(self.headers.get("Range", ""), _TOTAL)
                chunk = _BODY[start:end + 1]
                total = str(_TOTAL) if reveal_total else "*"
                self.send_response(206)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    ).start()
    return server


def _make_proxy(cache_dir):
    proxy = rcp.RangeCacheProxy(
        cache_dir=cache_dir,
        inline_window_kb=64,  # floor-clamped to 256 KiB, well below _TOTAL
        background_download=False,
    )
    proxy.start()
    return proxy


def test_slow_redirect_chain_still_reports_real_total(monkeypatch):
    # Make the redirect outlast the short probe wait, like a tracker chain.
    monkeypatch.setattr(rcp, "_PROBE_WAIT_S", 0.03)
    monkeypatch.setattr(rcp, "_PROBE_RESOLVE_WAIT_S", 10.0)
    server = _make_origin(redirect_delay_s=0.15)
    port = server.server_address[1]
    proxy = None
    try:
        with tempfile.TemporaryDirectory() as cache_dir:
            proxy = _make_proxy(cache_dir)
            url = proxy.proxify(f"http://127.0.0.1:{port}/redirect")

            # VLC's first request arrives before the probe has resolved.
            r = requests.get(url, headers={"Range": "bytes=0-"}, timeout=30)
            assert r.status_code == 206
            cr = r.headers.get("Content-Range", "")
            assert cr.endswith(f"/{_TOTAL}"), (
                f"proxy answered {cr!r} before the probe finished; VLC would "
                f"treat the inline window as the whole file"
            )
            served = int(r.headers.get("Content-Length", "0"))
            assert served == proxy.inline_window_bytes
            assert r.content == _BODY[:served]
    finally:
        if proxy is not None:
            proxy.stop()
        server.shutdown()
        server.server_close()


def test_unknown_total_falls_back_to_passthrough():
    # Origin never reveals the total ("bytes a-b/*"): the proxy must not invent
    # one by clamping to the inline window; it should stream the origin through.
    server = _make_origin(reveal_total=False)
    port = server.server_address[1]
    proxy = None
    try:
        with tempfile.TemporaryDirectory() as cache_dir:
            proxy = _make_proxy(cache_dir)
            url = proxy.proxify(f"http://127.0.0.1:{port}/file")

            r = requests.get(url, headers={"Range": "bytes=0-"}, timeout=30)
            assert r.status_code == 206
            # Forwarded from the origin verbatim: honest unknown total, and the
            # full body rather than a window masquerading as the file.
            assert r.headers.get("Content-Range", "").endswith("/*")
            assert r.content == _BODY
    finally:
        if proxy is not None:
            proxy.stop()
        server.shutdown()
        server.server_close()


def test_probe_does_not_take_total_from_206_content_length():
    # A 206 without a Content-Range total: its Content-Length is the size of
    # the served part (1 byte for the probe), never the size of the file.
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(206)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", "1")
            self.end_headers()
            self.wfile.write(b"\x00")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    ).start()
    port = server.server_address[1]
    try:
        with tempfile.TemporaryDirectory() as cache_dir:
            ent = rcp._Entry(
                url=f"http://127.0.0.1:{port}/file",
                headers={},
                cache_dir=cache_dir,
                prefetch_bytes=1024 * 1024,
                initial_burst_bytes=4 * 1024 * 1024,
                initial_inline_prefetch_bytes=0,
                background_download=False,
                background_chunk_bytes=1024 * 1024,
            )
            ent.probe()
            assert ent.range_supported is True
            assert ent.total_length is None
    finally:
        server.shutdown()
        server.server_close()
