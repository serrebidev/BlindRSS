# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""
Deep trace of media loading to find the actual bottleneck.
"""
import time
import sys
import os
import threading
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s.%(msecs)03d [%(name)s] %(message)s', datefmt='%H:%M:%S')

TEST_URL = "https://op3.dev/e/injector.simplecastaudio.com/d838244c-2029-41b5-aa66-d28628ab36fa/episodes/fccd857a-7dd2-4517-9af9-fdb945de72d0/audio/128/default.mp3?aid=rss_feed&awCollectionId=d838244c-2029-41b5-aa66-d28628ab36fa&awEpisodeId=fccd857a-7dd2-4517-9af9-fdb945de72d0&feed=MhX_XZQZ"

def trace_load():
    """Trace every step of media loading with timestamps."""
    import wx
    
    print("=" * 70)
    print("DEEP TRACE OF MEDIA LOADING")
    print("=" * 70)
    
    t_start = time.perf_counter()
    def ts():
        return f"[{time.perf_counter() - t_start:6.3f}s]"
    
    print(f"{ts()} Creating wx.App...")
    app = wx.App(False)
    
    print(f"{ts()} Importing modules...")
    from gui.player import PlayerFrame
    from core.config import ConfigManager
    
    print(f"{ts()} Creating ConfigManager...")
    config = ConfigManager()
    
    print(f"{ts()} Creating PlayerFrame...")
    frame = PlayerFrame(None, config)
    print(f"{ts()} PlayerFrame created")
    
    frame.Show()
    print(f"{ts()} Frame shown")
    
    # Patch key methods to trace timing
    original_resolve_worker = frame._resolve_media_worker
    original_finish_load = frame._finish_media_load
    original_load_vlc_url = frame._load_vlc_url
    original_maybe_range_cache = frame._maybe_range_cache_url
    
    def traced_resolve_worker(*args, **kwargs):
        print(f"{ts()} _resolve_media_worker STARTED (in thread)")
        result = original_resolve_worker(*args, **kwargs)
        print(f"{ts()} _resolve_media_worker FINISHED")
        return result
    
    def traced_finish_load(*args, **kwargs):
        print(f"{ts()} _finish_media_load STARTED (on main thread)")
        result = original_finish_load(*args, **kwargs)
        print(f"{ts()} _finish_media_load FINISHED")
        return result
    
    def traced_load_vlc_url(*args, **kwargs):
        print(f"{ts()} _load_vlc_url STARTED")
        result = original_load_vlc_url(*args, **kwargs)
        print(f"{ts()} _load_vlc_url FINISHED")
        return result
    
    def traced_maybe_range_cache(*args, **kwargs):
        print(f"{ts()} _maybe_range_cache_url STARTED")
        result = original_maybe_range_cache(*args, **kwargs)
        print(f"{ts()} _maybe_range_cache_url FINISHED -> {result[:60]}...")
        return result
    
    frame._resolve_media_worker = traced_resolve_worker
    frame._finish_media_load = traced_finish_load
    frame._load_vlc_url = traced_load_vlc_url
    frame._maybe_range_cache_url = traced_maybe_range_cache
    
    print(f"\n{ts()} Calling load_media({TEST_URL[:50]}...)")
    frame.load_media(TEST_URL, use_ytdlp=False, chapters=None, title="Test Episode")
    print(f"{ts()} load_media() returned")
    
    # Monitor state changes
    print(f"\n{ts()} Monitoring VLC state changes...")
    
    class StateMonitor:
        def __init__(self):
            self.last_state = None
            self.playing_time = None
            self.done = False
            
        def check(self):
            if self.done:
                return
                
            import vlc
            try:
                state = frame.player.get_state() if frame.player else None
                if state != self.last_state:
                    print(f"{ts()} VLC state: {self.last_state} -> {state}")
                    self.last_state = state
                    
                    if state == vlc.State.Playing:
                        self.playing_time = time.perf_counter() - t_start
                        print(f"\n{ts()} *** PLAYBACK STARTED ***")
                        self.done = True
                        wx.CallLater(500, lambda: wx.GetApp().ExitMainLoop())
                        return
                    elif state == vlc.State.Error:
                        print(f"\n{ts()} *** VLC ERROR ***")
                        self.done = True
                        wx.CallLater(100, lambda: wx.GetApp().ExitMainLoop())
                        return
            except Exception as e:
                print(f"{ts()} State check error: {e}")
            
            elapsed = time.perf_counter() - t_start
            if elapsed > 30:
                print(f"\n{ts()} *** TIMEOUT after 30s ***")
                self.done = True
                wx.GetApp().ExitMainLoop()
                return
            
            wx.CallLater(100, self.check)
    
    monitor = StateMonitor()
    wx.CallLater(100, monitor.check)
    
    print(f"{ts()} Starting event loop...")
    app.MainLoop()
    
    print(f"\n{'=' * 70}")
    if monitor.playing_time:
        print(f"TOTAL TIME TO PLAYBACK: {monitor.playing_time:.2f}s")
    else:
        print("PLAYBACK DID NOT START")
    print("=" * 70)
    
    try:
        frame.stop()
    except:
        pass
    frame.Destroy()


if __name__ == "__main__":
    trace_load()
