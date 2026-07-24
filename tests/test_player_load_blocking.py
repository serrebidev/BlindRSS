# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""
Test to verify player loading doesn't block the GUI.

This test measures time spent in synchronous operations during media load.
The player should open immediately and perform network operations in background threads.
"""

import time
import threading
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_proxify_blocking():
    """Test that proxify() doesn't block for network operations."""
    from core.range_cache_proxy import get_range_cache_proxy
    
    # A URL that requires redirect resolution (simplecast uses op3.dev redirects)
    test_url = "https://op3.dev/e/injector.simplecastaudio.com/d838244c-2029-41b5-aa66-d28628ab36fa/episodes/fccd857a-7dd2-4517-9af9-fdb945de72d0/audio/128/default.mp3?aid=rss_feed&awCollectionId=d838244c-2029-41b5-aa66-d28628ab36fa&awEpisodeId=fccd857a-7dd2-4517-9af9-fdb945de72d0&feed=MhX_XZQZ"
    
    proxy = get_range_cache_proxy()
    
    # Measure time for proxify call
    start = time.perf_counter()
    proxied_url = proxy.proxify(test_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    elapsed = time.perf_counter() - start
    
    print(f"proxify() took {elapsed:.3f} seconds")
    print(f"Proxied URL: {proxied_url}")
    
    # Should complete in under 500ms (no network blocking)
    assert elapsed <= 0.5, f"proxify() blocked for {elapsed:.3f}s - should be <=0.5s"
    print(f"PASS: proxify() completed quickly ({elapsed:.3f}s)")


def test_maybe_range_cache_url_nonblocking():
    """Test that _maybe_range_cache_url doesn't block the GUI thread."""
    import wx
    
    # Initialize wx App for testing
    app = wx.App(False)
    
    # Import after wx.App exists
    from gui.player import PlayerFrame
    from core.config import ConfigManager
    
    # Create a minimal config manager
    config = ConfigManager()
    
    # Create player frame (hidden)
    frame = PlayerFrame(None, config)
    frame.Hide()
    
    test_url = "https://op3.dev/e/injector.simplecastaudio.com/d838244c-2029-41b5-aa66-d28628ab36fa/episodes/fccd857a-7dd2-4517-9af9-fdb945de72d0/audio/128/default.mp3"
    
    # Measure time for _maybe_range_cache_url
    start = time.perf_counter()
    result_url = frame._maybe_range_cache_url(test_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    elapsed = time.perf_counter() - start
    
    print(f"_maybe_range_cache_url() took {elapsed:.3f} seconds")
    print(f"Result URL: {result_url}")
    
    # Cleanup
    frame.Destroy()
    
    # Should complete in under 500ms
    assert elapsed <= 0.5, f"_maybe_range_cache_url() blocked for {elapsed:.3f}s - should be <=0.5s"
    print(f"PASS: _maybe_range_cache_url() completed quickly ({elapsed:.3f}s)")


def test_maybe_range_cache_url_bypasses_googlevideo():
    """YouTube direct media URLs should bypass the local range proxy."""
    import wx

    app = wx.App(False)

    from gui.player import PlayerFrame
    from core.config import ConfigManager

    config = ConfigManager()
    frame = PlayerFrame(None, config)
    frame.Hide()

    try:
        test_url = (
            "https://rr1---sn-uxa0n-t8ge7.googlevideo.com/videoplayback"
            "?expire=1772240853&id=o-AHYPyeJvJhG2Mxf9UWlPqnu9yfGPSrMdWIuIrrB9-fE_&itag=140"
        )
        result_url = frame._maybe_range_cache_url(
            test_url,
            headers={"User-Agent": "Mozilla/5.0"},
            url_is_resolved=True,
        )
        assert result_url == test_url
        assert bool(getattr(frame, "_last_used_range_proxy", False)) is False
    finally:
        frame.Destroy()


if __name__ == "__main__":
    print("=" * 60)
    print("Testing player load blocking behavior")
    print("=" * 60)
    
    try:
        print("\n1. Testing proxify() blocking...")
        test_proxify_blocking()
        print("\n2. Testing _maybe_range_cache_url() blocking...")
        test_maybe_range_cache_url_nonblocking()
        print("\nPASS: all checks passed")
        sys.exit(0)
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)
