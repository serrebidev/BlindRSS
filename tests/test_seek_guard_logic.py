# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import unittest

import gui.player as player_mod
from gui.player import PlayerFrame, _should_reapply_seek


class SeekGuardLogicTests(unittest.TestCase):
    def test_reapply_when_far_and_budget(self):
        self.assertTrue(_should_reapply_seek(10_000, 4_000, 2000, 2))

    def test_no_reapply_when_close(self):
        self.assertFalse(_should_reapply_seek(10_000, 9_100, 2000, 2))

    def test_no_budget_no_reapply(self):
        self.assertFalse(_should_reapply_seek(10_000, 1000, 2000, 0))

    def test_negative_current_triggers_reapply(self):
        self.assertTrue(_should_reapply_seek(5000, -1, 2000, 1))


class _Slider:
    def __init__(self):
        self.value = 0

    def SetValue(self, value):
        self.value = int(value)


class _Config:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _SeekPlayer:
    def __init__(self, playing=True, state=None, stop_on_seek=True, cur_ms=0):
        self.playing = bool(playing)
        self.state = state if state is not None else player_mod.vlc.State.Playing
        self.stop_on_seek = bool(stop_on_seek)
        self.cur_ms = int(cur_ms)
        self.set_times = []
        self.set_pause_calls = []
        self.play_calls = 0

    def is_playing(self):
        return self.playing

    def set_time(self, value):
        self.cur_ms = int(value)
        self.set_times.append(int(value))
        if self.stop_on_seek:
            self.playing = False
            self.state = player_mod.vlc.State.Stopped

    def get_time(self):
        return self.cur_ms

    def get_state(self):
        return self.state

    def set_pause(self, value):
        self.set_pause_calls.append(int(value))

    def play(self):
        self.play_calls += 1
        self.playing = True
        self.state = player_mod.vlc.State.Playing


def _bare_seek_frame(player):
    frame = PlayerFrame.__new__(PlayerFrame)
    frame.is_casting = False
    frame.player = player
    frame.duration = 300_000
    frame.slider = _Slider()
    frame.config_manager = _Config({"skip_silence": False})
    frame.is_playing = bool(player.is_playing())
    frame._seek_apply_target_ms = None
    frame._seek_apply_calllater = None
    frame._seek_apply_reason = None
    frame._seek_apply_reason_ts = 0.0
    frame._seek_apply_last_ts = 0.0
    frame._seek_apply_debounce_s = 0.18
    frame._seek_apply_max_rate_s = 0.35
    frame._seek_input_ts = 0.0
    frame._seek_target_ms = None
    frame._seek_target_ts = 0.0
    frame._seek_resume_seq = 0
    frame._seek_log_last_ts = 0.0
    frame._seek_guard_calllater = None
    frame._pos_ms = 0
    frame._pos_ts = 0.0
    frame._pos_allow_backwards_until_ts = 0.0
    frame._last_vlc_time_ms = 0
    frame._is_dragging_slider = False
    frame._start_seek_guard = lambda _target: None
    frame._stop_calllater = lambda *args, **kwargs: None
    frame._log_seek_event = lambda *args, **kwargs: None
    frame._set_elapsed_time_label = lambda _value: None
    frame._set_play_button_label = lambda _playing: None
    frame._set_status = lambda _status: None
    frame._apply_volume_when_ready = lambda *args, **kwargs: None
    frame._format_time = lambda ms: str(ms)
    frame._note_user_seek = lambda: None
    frame._schedule_resume_save_after_seek = lambda *args, **kwargs: None
    return frame


def test_seek_that_started_while_playing_resumes_if_vlc_stops(monkeypatch):
    monkeypatch.setattr(player_mod.wx, "CallLater", lambda _delay, callback, *args: callback(*args))
    fake_player = _SeekPlayer(playing=True, stop_on_seek=True)
    frame = _bare_seek_frame(fake_player)

    frame._apply_seek_time_ms(120_000, force=True, reason="seek_relative")

    assert fake_player.set_times == [120_000]
    assert fake_player.set_pause_calls == [0]
    assert fake_player.play_calls == 1
    assert fake_player.is_playing() is True


def test_seek_that_started_paused_does_not_autoplay(monkeypatch):
    monkeypatch.setattr(player_mod.wx, "CallLater", lambda _delay, callback, *args: callback(*args))
    fake_player = _SeekPlayer(
        playing=False,
        state=player_mod.vlc.State.Paused,
        stop_on_seek=False,
    )
    frame = _bare_seek_frame(fake_player)

    frame._apply_seek_time_ms(120_000, force=True, reason="seek_relative")

    assert fake_player.set_times == [120_000]
    assert fake_player.set_pause_calls == []
    assert fake_player.play_calls == 0
    assert fake_player.is_playing() is False


def test_forward_relative_seek_near_end_does_not_seek_to_exact_duration():
    fake_player = _SeekPlayer(playing=True, stop_on_seek=False, cur_ms=250_000)
    frame = _bare_seek_frame(fake_player)
    frame.duration = 256_718
    captured = {}
    frame._apply_seek_time_ms = lambda target, force=False, reason=None: captured.update(
        target=int(target),
        force=bool(force),
        reason=reason,
    )

    frame.seek_relative_ms(10_000)

    assert captured["target"] == 255_718
    assert captured["reason"] == "seek_relative"
    assert frame._seek_target_ms == 255_718


def test_forward_relative_seek_at_safe_end_is_noop():
    fake_player = _SeekPlayer(playing=True, stop_on_seek=False, cur_ms=255_718)
    frame = _bare_seek_frame(fake_player)
    frame.duration = 256_718
    frame._pos_ms = 255_718
    called = []
    frame._apply_seek_time_ms = lambda *args, **kwargs: called.append((args, kwargs))

    frame.seek_relative_ms(10_000)

    assert called == []
    assert frame._seek_target_ms is None


if __name__ == "__main__":
    unittest.main()
