# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""
Profile the full media loading pipeline to identify all bottlenecks.
Measures actual time from user action to GUI responsiveness and playback start.
"""
import time
import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test URL from Double Tap podcast
TEST_URL = "https://op3.dev/e/injector.simplecastaudio.com/d838244c-2029-41b5-aa66-d28628ab36fa/episodes/fccd857a-7dd2-4517-9af9-fdb945de72d0/audio/128/default.mp3?aid=rss_feed&awCollectionId=d838244c-2029-41b5-aa66-d28628ab36fa&awEpisodeId=fccd857a-7dd2-4517-9af9-fdb945de72d0&feed=MhX_XZQZ"


def profile_all_init_steps():
    """Break down PlayerFrame init into components."""
    import wx
    
    print("\n=== Detailed PlayerFrame Init Breakdown ===")
    
    app = wx.App(False)
    
    from core.config import ConfigManager
    from core.casting import CastingManager
    import vlc
    
    config = ConfigManager()
    
    # Profile CastingManager creation
    t0 = time.perf_counter()
    casting_manager = CastingManager()
    print(f"CastingManager.__init__(): {(time.perf_counter() - t0)*1000:.1f}ms")
    
    # Profile CastingManager.start()
    t0 = time.perf_counter()
    casting_manager.start()
    print(f"CastingManager.start(): {(time.perf_counter() - t0)*1000:.1f}ms")
    
    # Profile VLC instance creation
    t0 = time.perf_counter()
    instance = vlc.Instance("--no-video", "--quiet")
    print(f"vlc.Instance(): {(time.perf_counter() - t0)*1000:.1f}ms")
    
    # Profile player creation
    t0 = time.perf_counter()
    player = instance.media_player_new()
    print(f"media_player_new(): {(time.perf_counter() - t0)*1000:.1f}ms")
    
    # Profile wx.Frame creation
    t0 = time.perf_counter()
    frame = wx.Frame(None, title="Test", size=(520, 260))
    print(f"wx.Frame(): {(time.perf_counter() - t0)*1000:.1f}ms")
    
    frame.Destroy()


def profile_player_with_events():
    """Profile PlayerFrame with proper wx event handling."""
    import wx
    
    print("\n=== Profiling PlayerFrame with Event Loop ===")
    
    app = wx.App(False)
    
    from gui.player import PlayerFrame
    from core.config import ConfigManager
    
    config = ConfigManager()
    
    # Profile PlayerFrame init
    t0 = time.perf_counter()
    frame = PlayerFrame(None, config)
    t_init = time.perf_counter() - t0
    print(f"PlayerFrame.__init__(): {t_init:.3f}s")
    
    frame.Show()
    
    # Profile load_media call
    t0 = time.perf_counter()
    t_load_start = t0
    frame.load_media(TEST_URL, use_ytdlp=False, chapters=None, title="Test Episode")
    t_load = time.perf_counter() - t0
    print(f"load_media() returned in: {t_load:.3f}s")
    
    # Run event loop with timeout checking for playback
    print("\nWaiting for playback to start...")
    playback_started = False
    playing_time = None
    
    class TimeoutChecker:
        def __init__(self, timeout=15):
            self.start = time.perf_counter()
            self.timeout = timeout
            self.done = False
            self.last_log = 0
            
        def check(self):
            elapsed = time.perf_counter() - self.start
            
            if elapsed > self.timeout:
                self.done = True
                wx.GetApp().ExitMainLoop()
                return
            
            # Check playback state
            try:
                import vlc
                if frame.player and frame.player.get_state() == vlc.State.Playing:
                    nonlocal playback_started, playing_time
                    playback_started = True
                    playing_time = elapsed
                    print(f"  Playback started at {elapsed:.2f}s")
                    self.done = True
                    wx.GetApp().ExitMainLoop()
                    return
            except:
                pass
            
            # Log every second
            if elapsed - self.last_log >= 1.0:
                self.last_log = elapsed
                state = "unknown"
                try:
                    import vlc
                    if frame.player:
                        state = frame.player.get_state()
                except:
                    pass
                print(f"  ...waiting {elapsed:.1f}s (VLC state: {state})")
            
            # Schedule next check
            wx.CallLater(100, self.check)
    
    checker = TimeoutChecker(timeout=15)
    wx.CallLater(100, checker.check)
    
    # Run event loop
    app.MainLoop()
    
    if playback_started:
        print(f"\nSUCCESS: Playback started in {playing_time:.2f}s from load_media()")
    else:
        print(f"\nFAILURE: Playback did not start within 15 seconds")
    
    # Cleanup
    try:
        frame.stop()
    except:
        pass
    frame.Destroy()
    
    return playback_started, playing_time


if __name__ == "__main__":
    print("=" * 70)
    print("DETAILED MEDIA LOADING PROFILER")
    print("=" * 70)
    
    profile_all_init_steps()
    success, play_time = profile_player_with_events()
    
    print("\n" + "=" * 70)
    if success:
        print(f"RESULT: Media playback started in {play_time:.2f}s - ", end="")
        if play_time < 3.0:
            print("GOOD")
        elif play_time < 5.0:
            print("ACCEPTABLE")
        else:
            print("NEEDS IMPROVEMENT")
    else:
        print("RESULT: FAILED to start playback")
    print("=" * 70)
