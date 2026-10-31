# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The startup-stall watchdogs time VLC opening the URL, not the yt-dlp resolve.

load_media used to start the clock, so a 4 s yt-dlp resolve left VLC only 4 s
of the proxy watchdog's 8 s before "Detected stalled proxied playback
(state=Opening)" abandoned the stream for the download-to-play fallback,
reported as a "vlc-error" although none occurred.
"""

import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
vlc = pytest.importorskip("vlc")

import gui.player as player_mod
from gui.player import PlayerFrame

GOOGLEVIDEO = "https://rr1---sn-x.googlevideo.com/videoplayback?id=1"
WATCH_URL = "https://www.youtube.com/watch?v=abcDEF12345"


def _player():
    p = MagicMock()
    p.is_casting = False
    p._load_seq = 0
    p._active_load_seq = 0
    p._pending_non_media_reason.return_value = ""
    return p


def _proxied_stall_candidate(p):
    p._last_used_range_proxy = True
    p._last_orig_url = GOOGLEVIDEO
    p._range_proxy_retry_count = 0
    p._range_proxy_last_stall_recover_ts = 0.0
    return p


def test_load_media_leaves_the_watchdogs_idle_while_ytdlp_resolves():
    p = _player()
    p._load_start_ts = 123.0
    PlayerFrame.load_media(p, WATCH_URL, use_ytdlp=True)
    assert p._load_start_ts == 0.0

    _proxied_stall_candidate(p)
    PlayerFrame._maybe_recover_stalled_proxy_playback(p, vlc.State.Opening, False, 0)
    p._handle_vlc_error.assert_not_called()


def test_load_vlc_url_starts_the_watchdog_clock(monkeypatch):
    monkeypatch.setattr(player_mod.wx, "CallLater", lambda *_a, **_kw: None)
    p = _player()
    p._load_start_ts = 0.0
    before = time.monotonic()
    PlayerFrame._load_vlc_url(p, "http://127.0.0.1:8123/media?id=x", load_seq=0, http_headers={})
    assert before <= p._load_start_ts <= time.monotonic()


def test_proxy_watchdog_gives_vlc_its_full_budget_after_a_slow_resolve(monkeypatch):
    monkeypatch.setattr(player_mod.wx, "CallLater", lambda *_a, **_kw: None)
    p = _proxied_stall_candidate(_player())
    PlayerFrame._load_vlc_url(p, "http://127.0.0.1:8123/media?id=x", load_seq=0, http_headers={})
    # 4 s after VLC got the URL (8 s after load_media, after a 4 s resolve).
    p._load_start_ts -= 4.0
    PlayerFrame._maybe_recover_stalled_proxy_playback(p, vlc.State.Opening, False, 0)
    p._handle_vlc_error.assert_not_called()

    p._load_start_ts -= 4.5
    PlayerFrame._maybe_recover_stalled_proxy_playback(p, vlc.State.Opening, False, 0)
    p._handle_vlc_error.assert_called_once_with(reason="stalled")


class _Clock:
    """Stands in for gui.player's `time` module so a test can move time on."""

    def __init__(self, now=1000.0):
        self.now = now

    def monotonic(self):
        return self.now

    def time(self):
        return time.time()


def test_direct_watchdog_ignores_time_spent_resolving(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(player_mod, "time", clock)
    p = _player()
    p._last_used_range_proxy = False
    p._last_used_stream_proxy = False
    p._last_orig_url = GOOGLEVIDEO
    p._stream_proxy_retry_count = 0
    p._stream_proxy_last_stall_recover_ts = 0.0
    PlayerFrame.load_media(p, WATCH_URL, use_ytdlp=True)

    clock.now += 7.0  # a slow yt-dlp resolve; VLC has not been given a URL yet
    PlayerFrame._maybe_recover_stalled_direct_playback(p, vlc.State.Opening, False, 0)
    p._maybe_stream_proxy_url.assert_not_called()
    p.maybe_play_ytdlp_via_download.assert_not_called()


def test_silence_scan_delay_still_counts_from_load_media(monkeypatch):
    """Only the watchdogs moved to _load_vlc_url: Skip Silence must not lose
    the yt-dlp resolve time again before its first scan."""
    clock = _Clock()
    monkeypatch.setattr(player_mod, "time", clock)
    p = _player()
    p.config_manager.get.side_effect = lambda _key, default=None: default
    PlayerFrame.load_media(p, WATCH_URL, use_ytdlp=True)
    clock.now += 4.0  # yt-dlp resolved...
    PlayerFrame._load_vlc_url(p, "http://127.0.0.1:8123/media?id=x", load_seq=0, http_headers={})
    clock.now += 0.5  # ...and VLC is playing half a second later

    p._silence_scan_pending = True
    p._silence_scan_pending_info = ("http://127.0.0.1:8123/media?id=x", 0, {})
    p._active_load_seq = 0
    PlayerFrame._maybe_start_pending_silence_scan(p, True)
    p._start_silence_scan.assert_called_once()


def test_stall_recovery_is_reported_as_a_stall():
    p = _player()
    p._active_load_seq = 3
    p.maybe_play_ytdlp_via_download.return_value = True
    PlayerFrame._handle_vlc_error(p, reason="stalled")
    p.maybe_play_ytdlp_via_download.assert_called_once_with(3, reason="stalled")

    p = _player()
    p._active_load_seq = 3
    p.maybe_play_ytdlp_via_download.return_value = True
    PlayerFrame._handle_vlc_error(p)
    p.maybe_play_ytdlp_via_download.assert_called_once_with(3, reason="vlc-error")


def test_vlc_direct_last_resort_forgets_the_previous_items_proxy():
    p = _player()
    p._active_load_seq = 4
    p._last_used_range_proxy = True
    p._last_used_stream_proxy = True
    p._last_orig_url = "https://previous.example/episode.mp3"
    p._last_vlc_url = "http://127.0.0.1:1/media?id=previous"
    page = "https://news.example.com/item/abc123"

    PlayerFrame._finish_media_load(p, 4, page, page, {}, "Title", None, True)

    p._maybe_range_cache_url.assert_not_called()
    assert p._last_used_range_proxy is False
    assert p._last_used_stream_proxy is False
    assert p._last_orig_url == page
    assert p._last_vlc_url == page

    # A later VLC error must not replay the previous item through the proxy.
    p._load_vlc_url.reset_mock()
    p.maybe_play_ytdlp_via_download.return_value = False
    PlayerFrame._handle_vlc_error(p)
    p._load_vlc_url.assert_not_called()
