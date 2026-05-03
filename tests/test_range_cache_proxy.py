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
