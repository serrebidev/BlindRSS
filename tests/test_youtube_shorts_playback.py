#!/usr/bin/env python
"""Test that YouTube Shorts URLs are correctly resolved and playable.

Regression test for a bug where `should_resolve` was undefined in the
yt-dlp code path of `_resolve_media_worker`, causing a silent NameError
that prevented `_finish_media_load` from being called.
"""

import sys, os, time, threading, logging

logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import db
db.init_db()

import wx


SHORTS_URL = "https://www.youtube.com/shorts/Op8ESv7VcUE"


def test_ytdlp_resolve():
    """Verify yt-dlp can resolve a Shorts URL to a direct media stream."""
    import yt_dlp

    opts = {'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(SHORTS_URL, download=False)

    assert info.get('url'), "yt-dlp must return a direct media URL"
    assert info.get('title'), "yt-dlp must return a title"
    print(f"PASS: yt-dlp resolved Shorts URL -> {info['url'][:80]}...")


def test_should_resolve_defined_for_ytdlp(tmp_path):
    """Ensure the player's resolve worker doesn't crash on yt-dlp paths.

    Before the fix, `should_resolve` was only defined in the else (non-yt-dlp)
    branch, causing a NameError that was silently swallowed.
    """
    app = wx.App(False)

    from gui.player import PlayerFrame
    from core.config import ConfigManager

    config = ConfigManager()
    # Playback can legitimately fall back to a local yt-dlp download. Keep that
    # integration artifact in pytest's temporary directory instead of polluting
    # the source checkout with the default ``ytplay_cache`` folder.
    config.config["youtube_play_cache_dir"] = str(tmp_path / "ytplay_cache")
    player = PlayerFrame(None, config_manager=config)
    player.Show()

    results = {"finished": False, "playing": False, "error": None}

    def check_state():
        try:
            if player.player:
                import vlc
                state = player.player.get_state()
                pos = player.player.get_time()
                print(f"  State: {state}, Position: {pos}ms")

                last_vlc_url = getattr(player, '_last_vlc_url', None)
                print(f"  _last_vlc_url: {last_vlc_url[:80] if last_vlc_url else 'None'}")

                if state == vlc.State.Playing:
                    results["playing"] = True
                elif state == vlc.State.Error:
                    results["error"] = "VLC Error state"
        except Exception as e:
            results["error"] = str(e)
            print(f"  Error: {e}")

    print(f"Loading Shorts URL: {SHORTS_URL}")
    player.load_media(SHORTS_URL, use_ytdlp=True, title="Shorts Test")

    class TimeoutFrame(wx.Frame):
        def __init__(self, app_ref, player_ref, res, max_seconds=30):
            super().__init__(None, title="Test Timer", size=(1, 1))
            self.app_ref = app_ref
            self.player_ref = player_ref
            self.res = res
            self.start_time = time.time()
            self.max_seconds = max_seconds
            self.check_count = 0

            self.timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
            self.timer.Start(1000)

        def on_timer(self, event):
            self.check_count += 1
            elapsed = time.time() - self.start_time
            print(f"\nCheck #{self.check_count} at {elapsed:.1f}s:")
            check_state()

            if self.res["playing"]:
                print("\nPASS: YouTube Shorts audio is playing!")
                self.finish()
            elif self.res["error"]:
                print(f"\nFAIL: {self.res['error']}")
                self.finish()
            elif elapsed > self.max_seconds:
                print("\nFAIL: Timeout - media never started playing")
                self.finish()

        def finish(self):
            self.timer.Stop()
            try:
                self.player_ref.stop()
            except Exception:
                pass
            try:
                self.player_ref.Close()
                self.player_ref.Destroy()
            except Exception:
                pass
            self.Close()
            self.app_ref.ExitMainLoop()

    tf = TimeoutFrame(app, player, results)
    tf.Show(False)
    app.MainLoop()

    print("\n=== SUMMARY ===")
    print(f"Playing: {results['playing']}")
    print(f"Error:   {results['error']}")
    assert results["error"] is None, f"Unexpected playback error: {results['error']}"
    assert results["playing"], "Expected VLC to enter Playing state within timeout"


if __name__ == "__main__":
    try:
        test_ytdlp_resolve()
        test_should_resolve_defined_for_ytdlp()
        sys.exit(0)
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
