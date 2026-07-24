# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import unittest
import io
import tempfile
from urllib.parse import urlparse

import core.range_cache_proxy as rcp


class LocalSeekingProxyTests(unittest.TestCase):
    def setUp(self):
        rcp._RANGE_PROXY_SINGLETON = None
        self.proxy = rcp.get_range_cache_proxy(
            cache_dir=None,
            prefetch_kb=64,
            inline_window_kb=64,
            background_download=False,
            background_chunk_kb=64,
            initial_burst_kb=128,
            initial_inline_prefetch_kb=32,
        )
        self.proxy.start()

    def tearDown(self):
        try:
            self.proxy.stop()
        except Exception:
            pass
        rcp._RANGE_PROXY_SINGLETON = None

    def test_health_endpoint_is_ready(self):
        base = self.proxy.base_url
        parsed = urlparse(base)
        self.assertEqual(parsed.hostname, "127.0.0.1")
        # A quick sanity check that /health responds
        import http.client

        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        resp.read()
        conn.close()

    def test_parse_range_header_clamps(self):
        # Explicit end should clamp to known length; open-ended stays None.
        self.assertEqual(rcp._parse_range_header("bytes=0-100", 50), (0, 49))
        self.assertEqual(rcp._parse_range_header("bytes=100-200", None), (100, 200))
        self.assertEqual(rcp._parse_range_header("bytes=200-", 500), (200, None))

    def test_proxify_returns_local_media_url(self):
        proxied = self.proxy.proxify("http://example.com/audio.mp3")
        parsed = urlparse(proxied)
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertTrue(parsed.path.endswith("/media"))
        self.assertIn("id=", parsed.query)

    def test_parse_content_range(self):
        self.assertEqual(rcp._parse_content_range("bytes 0-1/123"), (0, 1, 123))
        self.assertEqual(rcp._parse_content_range("bytes 10-20/*"), (10, 20, None))

    def test_stream_origin_range_writes_to_passed_writer(self):
        class _FailingWriter:
            def write(self, _data):
                raise AssertionError("Unexpected write to entry.wfile")

            def flush(self):
                raise AssertionError("Unexpected flush to entry.wfile")

        class _FakeResponse:
            status_code = 206
            headers = {"Content-Range": "bytes 0-1/2", "Content-Type": "audio/mpeg", "Content-Length": "2"}

            def iter_content(self, chunk_size=1024):
                yield b"ID"

            def close(self):
                return None

        class _FakeSession:
            def get(self, *_args, **_kwargs):
                return _FakeResponse()

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as cache_dir:
            entry = rcp._Entry(
                url="https://example.com/audio.mp3",
                headers={"User-Agent": "Mozilla/5.0"},
                cache_dir=cache_dir,
                prefetch_bytes=64 * 1024,
                initial_burst_bytes=64 * 1024,
                initial_inline_prefetch_bytes=0,
                background_download=False,
                background_chunk_bytes=64 * 1024,
            )
            entry.probe = lambda: None
            entry.range_supported = True
            entry.wfile = _FailingWriter()
            entry._make_session = lambda: _FakeSession()

            buf = io.BytesIO()
            end = entry.stream_origin_range_to_and_cache(0, 1, buf, flush_first=True)
            self.assertEqual(end, 1)
            self.assertEqual(buf.getvalue(), b"ID")


if __name__ == "__main__":
    unittest.main()
