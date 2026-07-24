# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""
Focused profiler to find the exact blocking point.
"""
import time
import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_URL = "https://op3.dev/e/injector.simplecastaudio.com/d838244c-2029-41b5-aa66-d28628ab36fa/episodes/fccd857a-7dd2-4517-9af9-fdb945de72d0/audio/128/default.mp3?aid=rss_feed&awCollectionId=d838244c-2029-41b5-aa66-d28628ab36fa&awEpisodeId=fccd857a-7dd2-4517-9af9-fdb945de72d0&feed=MhX_XZQZ"


def profile_resolve_steps():
    """Profile just the resolve steps without wx."""
    from core import utils
    from core.range_cache_proxy import get_range_cache_proxy
    from urllib.parse import urlparse
    
    print("=== Profiling Resolution Steps (no wx) ===\n")
    
    url = TEST_URL
    
    # Step 1: Extension check
    t0 = time.perf_counter()
    low = url.lower()
    parsed = urlparse(low)
    path = parsed.path or low
    SEEKABLE_EXTENSIONS = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac", ".mp4", ".m4v", ".webm", ".mkv", ".mov")
    should_resolve = not path.endswith(SEEKABLE_EXTENSIONS)
    print(f"1. Extension check: {(time.perf_counter() - t0)*1000:.2f}ms (should_resolve={should_resolve})")
    
    # Step 2: Resolve URL if needed (THIS IS THE SLOW ONE)
    if should_resolve:
        print("\n2. resolve_final_url() - THIS MAY BE SLOW...")
        t0 = time.perf_counter()
        final_url = utils.resolve_final_url(url, max_redirects=30)
        print(f"   resolve_final_url: {time.perf_counter() - t0:.3f}s")
    else:
        final_url = url
        print(f"2. resolve_final_url: SKIPPED (has seekable extension)")
    
    # Step 3: Normalize
    t0 = time.perf_counter()
    final_url = utils.normalize_url_for_vlc(final_url)
    print(f"3. normalize_url_for_vlc: {(time.perf_counter() - t0)*1000:.2f}ms")
    
    # Step 4: Proxy setup
    print("\n4. Setting up proxy...")
    t0 = time.perf_counter()
    proxy = get_range_cache_proxy()
    proxied = proxy.proxify(final_url, headers={'User-Agent': 'Mozilla/5.0'})
    print(f"   proxify: {time.perf_counter() - t0:.3f}s")
    print(f"   Proxied URL: {proxied}")
    
    return proxied


def profile_vlc_playback(proxied_url):
    """Profile VLC playback initiation."""
    import vlc
    
    print("\n=== Profiling VLC Playback ===\n")
    
    # Create instance
    t0 = time.perf_counter()
    instance = vlc.Instance("--no-video", "--quiet")
    player = instance.media_player_new()
    print(f"VLC setup: {(time.perf_counter() - t0)*1000:.1f}ms")
    
    # Create media
    t0 = time.perf_counter()
    media = instance.media_new(proxied_url)
    media.add_option(':network-caching=50')  # Very low caching for fast start
    media.add_option(':file-caching=50')
    player.set_media(media)
    print(f"Media setup: {(time.perf_counter() - t0)*1000:.1f}ms")
    
    # Start playback
    t0 = time.perf_counter()
    player.play()
    print(f"player.play() call: {(time.perf_counter() - t0)*1000:.1f}ms")
    
    # Wait for actual playback
    print("\nWaiting for playback state changes...")
    t_start = time.perf_counter()
    last_state = None
    playing_ts = None
    
    for i in range(200):  # 20 seconds max
        time.sleep(0.1)
        state = player.get_state()
        
        if state != last_state:
            elapsed = time.perf_counter() - t_start
            print(f"  State change at {elapsed:.2f}s: {last_state} -> {state}")
            last_state = state
            
            if state == vlc.State.Playing:
                playing_ts = time.perf_counter()
                break
            elif state == vlc.State.Error:
                print("  ERROR state reached!")
                break
    
    if playing_ts:
        print(f"\nPlayback started in {playing_ts - t_start:.2f}s from player.play()")
    else:
        print(f"\nPlayback did not start within 20 seconds")
    
    player.stop()
    return playing_ts is not None


if __name__ == "__main__":
    print("=" * 70)
    print("FOCUSED MEDIA LOADING PROFILER")
    print("=" * 70 + "\n")
    
    proxied_url = profile_resolve_steps()
    
    print("\n" + "-" * 70)
    
    # Don't wait - test immediate VLC request after proxify
    print("\nTesting immediate VLC playback (no wait for probe)...")
    
    profile_vlc_playback(proxied_url)
    
    print("\n" + "=" * 70)
    print("DONE")
