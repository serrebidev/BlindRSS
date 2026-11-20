# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Skip Silence on streamed podcasts (2026-11-19 report, ported from BlindRSS-Rust v0.1.121).

1. VLC --input-fast-seek landed MP4 seeks on the chunk start; an Anchor m4a with
   ~65 s chunks replayed up to a minute per skip.
2. Remote scans overrode the user's detector settings (-52 dB, aggressiveness 0,
   1200 ms) and remote skips waited 5 s: 52 silences found instead of 302.
3. A paced scan reads the socket slowly; CloudFront reset it ~6 min in and
   ffmpeg exited 0 with "partial file", so skipping stopped 12 min into the episode.
"""

import os
import sys
from unittest import mock
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import audio_silence, vlc_instance

URL = "https://cdn.example/ep.m4a"


class _Cfg:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_vlc_instance_has_no_fast_seek():
    assert not any("fast-seek" in a for a in vlc_instance._build_args(_Cfg()))


def _scan_cmd(source):
    with mock.patch.object(audio_silence.subprocess, "Popen", side_effect=RuntimeError("stop")) as popen:
        with pytest.raises(Exception):
            audio_silence.scan_audio_for_silence(source)
    return popen.call_args[0][0]


def test_http_scan_reconnects_local_scan_does_not():
    cmd = _scan_cmd(URL)
    before_input = cmd[: cmd.index("-i")]
    for flag in ("-reconnect", "-reconnect_on_network_error"):
        assert flag in before_input, cmd
        assert before_input[before_input.index(flag) + 1] == "1"
    assert not any(a.startswith("-reconnect") for a in _scan_cmd("C:/podcasts/ep.m4a"))


wx = pytest.importorskip("wx")
pytest.importorskip("vlc")
import gui.player as player_mod  # noqa: E402
from gui.player import PlayerFrame  # noqa: E402


class _SyncThread:
    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


def test_remote_scan_keeps_user_detector_settings(monkeypatch):
    user = {
        "skip_silence": True,
        "silence_skip_threshold_db": -38.0,
        "silence_vad_aggressiveness": 2,
        "silence_skip_min_ms": 700,
        "silence_skip_merge_gap_ms": 260,
    }
    p = MagicMock()
    p.is_casting = False
    p.current_url = URL
    p._active_load_seq = 0
    p.config_manager = _Cfg(user)
    scan = MagicMock(return_value=[])
    monkeypatch.setattr(player_mod, "scan_audio_for_silence", scan)
    monkeypatch.setattr(player_mod.threading, "Thread", _SyncThread)
    PlayerFrame._start_silence_scan(p, URL, 0)
    kw = scan.call_args.kwargs
    assert kw["threshold_db"] == -38.0
    assert kw["vad_aggressiveness"] == 2
    assert kw["min_silence_ms"] == 700
    assert kw["merge_gap_ms"] == 260
    assert kw["sample_rate"] == 8000


def test_remote_skip_cooldown_matches_local(monkeypatch):
    p = MagicMock()
    p.is_casting = False
    p.current_url = URL
    p.config_manager = _Cfg({"skip_silence": True})
    p.player.is_seekable.return_value = True
    p._pending_resume_seek_ms = None
    p._resume_restore_inflight = False
    p._silence_scan_ready = True
    p._silence_ranges = [(10_000, 20_000)]
    p._silence_skip_pause_until_ts = 0.0
    p._is_dragging_slider = False
    p._silence_skip_floor_ms = 0
    p._silence_skip_active_target = None
    p._silence_skip_last_target_ms = None
    p._silence_skip_last_idx = None
    now = 1000.0
    monkeypatch.setattr(player_mod.time, "monotonic", lambda: now)
    p._silence_skip_last_ts = now - 3.0  # past 2.5 s, inside the old 5 s
    PlayerFrame._maybe_skip_silence(p, 10_500)
    assert p._silence_skip_last_ts == now, "remote skip still held by a 5 s cooldown"
