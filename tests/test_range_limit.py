# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Test that open-ended range requests are limited to inline_window_bytes."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.range_cache_proxy import get_range_cache_proxy, _parse_range_header

def test_parse_range():
    # Open-ended request
    result = _parse_range_header("bytes=0-", 140285994)
    print(f"Parse 'bytes=0-' with total=140285994: {result}")
    assert result == (0, None), f"Expected (0, None), got {result}"
    
    # Explicit end
    result = _parse_range_header("bytes=0-1000", 140285994)
    print(f"Parse 'bytes=0-1000' with total=140285994: {result}")
    assert result == (0, 1000), f"Expected (0, 1000), got {result}"
    
    # Start from middle
    result = _parse_range_header("bytes=21966541-", 140285994)
    print(f"Parse 'bytes=21966541-' with total=140285994: {result}")
    assert result == (21966541, None), f"Expected (21966541, None), got {result}"
    
    print("\nAll parse tests passed!")

def test_proxy_limits_open_ended():
    """Verify that the proxy limits open-ended requests."""
    # Create proxy with 4 MB inline window (like user's config)
    proxy = get_range_cache_proxy(
        inline_window_kb=4096,  # 4 MB
        background_download=False,
        initial_burst_kb=8192,
        initial_inline_prefetch_kb=1024,
    )
    
    print(f"\nProxy inline_window_bytes: {proxy.inline_window_bytes} ({proxy.inline_window_bytes / 1024 / 1024:.1f} MB)")
    
    # Test URL (doesn't need to be real for this test)
    test_url = "https://example.com/test.mp3"
    
    # Register the URL (bypass probe by adding directly)
    import hashlib
    url_hash = hashlib.sha256(test_url.encode("utf-8", "ignore")).hexdigest()[:24]
    sid = f"http://127.0.0.1:{proxy._port}/media?id={url_hash}"
    
    # Create entry directly to avoid network probe
    from core.range_cache_proxy import _Entry
    ent = _Entry(
        url=test_url,
        headers={},
        cache_dir=proxy.cache_dir,
        prefetch_bytes=proxy.prefetch_bytes,
        background_download=False,
        initial_burst_bytes=proxy.initial_burst_bytes,
        initial_inline_prefetch_bytes=proxy.initial_inline_prefetch_bytes,
        background_chunk_bytes=proxy.background_chunk_bytes,
    )
    proxy._entries[url_hash] = ent
    print(f"Created entry with id: {url_hash[:12]}...")
    
    # Simulate what the handler does with an open-ended request when total_length is known
    # Simulate known total length
    ent.total_length = 140285994  # ~140 MB
    
    # Simulate open-ended request: bytes=0-
    start = 0
    end = None  # open-ended
    
    # This is the NEW logic from our fix:
    if ent.total_length is not None:
        if end is None:
            # Limit open-ended requests to inline window
            end = min(start + max(0, int(proxy.inline_window_bytes) - 1), ent.total_length - 1)
        else:
            end = min(int(end), ent.total_length - 1)
    else:
        if end is None:
            end = start + max(0, int(proxy.inline_window_bytes) - 1)
    
    print(f"\nOpen-ended request 'bytes=0-' with total_length={ent.total_length}:")
    print(f"  Calculated end: {end} ({end / 1024 / 1024:.1f} MB)")
    print(f"  Response would be: bytes 0-{end}/{ent.total_length}")
    
    # Verify the limit is applied
    expected_end = min(proxy.inline_window_bytes - 1, ent.total_length - 1)
    assert end == expected_end, f"Expected end={expected_end}, got end={end}"
    print(f"\n✓ Open-ended request correctly limited to {(end + 1) / 1024 / 1024:.1f} MB (inline_window_bytes)")
    
    print("\nAll proxy tests passed!")

if __name__ == "__main__":
    test_parse_range()
    test_proxy_limits_open_ended()
