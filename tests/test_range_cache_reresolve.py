# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Range-cache proxy re-resolves an expired signed URL mid-stream.

Reproduces the megaphone/podtrac podcast bug: the origin redirects to a
time-limited signed URL; when that link expires partway through a long file the
proxy used to get a 403 and stop, cutting the podcast off. The proxy must
re-follow the redirect from the original URL to mint a fresh link and continue.
"""

import os
import sys
import tempfile
import threading
from io import BytesIO
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.range_cache_proxy import _Entry

_TOTAL = 2_000_000
_BODY = bytes((i % 251) for i in range(_TOTAL))


class _State:
    valid_token = "tok1"
    counter = 0
    reresolved = False


def _make_server():
    state = _State()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path
            if path.startswith("/original"):
                # Issue a fresh signed token each time the original is resolved.
                state.counter += 1
                token = f"tok{state.counter}"
                state.valid_token = token
                if state.counter >= 2:
                    state.reresolved = True
                self.send_response(302)
                self.send_header("Location", f"/signed?token={token}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if path.startswith("/signed"):
                token = ""
                if "token=" in path:
                    token = path.split("token=", 1)[1].split("&")[0]
                # Expired/invalid token -> 403 (what megaphone does after TTL).
                if token != state.valid_token:
                    self.send_response(403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                rng = self.headers.get("Range", "")
                start, end = 0, _TOTAL - 1
                if rng.startswith("bytes="):
                    a, _, b = rng[len("bytes="):].partition("-")
                    start = int(a or 0)
                    end = int(b or (_TOTAL - 1))
                end = min(end, _TOTAL - 1)
                chunk = _BODY[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{_TOTAL}")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return

            self.send_response(404)
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    return server, state


def _new_entry(url, cache_dir):
    return _Entry(
        url=url,
        headers={},
        cache_dir=cache_dir,
        prefetch_bytes=1024 * 1024,
        initial_burst_bytes=4 * 1024 * 1024,
        initial_inline_prefetch_bytes=0,
        background_download=False,
        background_chunk_bytes=1024 * 1024,
    )


def test_fetch_range_reresolves_expired_signed_url():
    server, state = _make_server()
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with tempfile.TemporaryDirectory() as cache_dir:
            base = f"http://127.0.0.1:{port}/original"
            ent = _new_entry(base, cache_dir)

            # Probe resolves the original to a signed URL (token tok1).
            ent.probe()
            assert ent.range_supported is True
            assert ent.total_length == _TOTAL
            assert "token=tok1" in (ent.real_url or "")

            # Simulate the signed link expiring mid-playback.
            state.valid_token = "expired"

            # A range fetch now hits 403 on the stale link; the proxy must
            # re-resolve from the original url and succeed with a fresh token.
            ok = ent._fetch_range(1_000_000, 1_000_010)
            assert ok is True, "fetch should recover by re-resolving the signed URL"
            assert state.reresolved is True
            assert "token=tok1" not in (ent.real_url or "")

            # The recovered bytes must be correct.
            served_end, data = ent._read_from_cache(1_000_000, 1_000_010)
            assert data == _BODY[1_000_000:1_000_011]
    finally:
        server.shutdown()
        server.server_close()  # shutdown() alone leaks the listening socket


def test_stream_origin_range_reresolves_expired_signed_url():
    server, state = _make_server()
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with tempfile.TemporaryDirectory() as cache_dir:
            base = f"http://127.0.0.1:{port}/original"
            ent = _new_entry(base, cache_dir)

            ent.probe()
            assert ent.range_supported is True
            assert "token=tok1" in (ent.real_url or "")

            state.valid_token = "expired"

            out = BytesIO()
            served_end = ent.stream_origin_range_to_and_cache(1_000_000, 1_000_010, out)

            assert served_end == 1_000_010
            assert state.reresolved is True
            assert "token=tok1" not in (ent.real_url or "")
            assert out.getvalue() == _BODY[1_000_000:1_000_011]

            cached_end, data = ent._read_from_cache(1_000_000, 1_000_010)
            assert cached_end == 1_000_010
            assert data == _BODY[1_000_000:1_000_011]
    finally:
        server.shutdown()
        server.server_close()  # shutdown() alone leaks the listening socket


def test_refresh_real_url_updates_from_original():
    server, state = _make_server()
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with tempfile.TemporaryDirectory() as cache_dir:
            base = f"http://127.0.0.1:{port}/original"
            ent = _new_entry(base, cache_dir)
            ent.probe()
            first = ent.real_url
            # Force the throttle window open, then re-resolve.
            ent._last_reresolve_ts = 0.0
            assert ent._refresh_real_url(min_interval_s=0.0) is True
            assert ent.real_url and ent.real_url != first
    finally:
        server.shutdown()
        server.server_close()  # shutdown() alone leaks the listening socket
