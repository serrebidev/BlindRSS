# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Startup volume application (first-adjustment volume jump bug).

libvlc silently drops audio_set_volume calls made before the audio output
exists, and the output only appears once the stream actually produces audio —
for slow HTTP/podcast streams that can be many seconds after play(). The old
fixed retry budget (12 x 250ms = 3s) expired before then, leaving VLC at its
own default volume while PlayerFrame.volume held the configured one — the
first Volume Up/Down then jumped. _apply_volume_when_ready now retries for as
long as the playback attempt is alive, newer attempts supersede pending
retries, and VLC's actual volume is only adopted when the output exists but
keeps refusing ours.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")

import gui.player as player_mod
from gui.player import PlayerFrame

Opening = player_mod.vlc.State.Opening
Playing = player_mod.vlc.State.Playing
Error = player_mod.vlc.State.Error


class DummyPlayer:
    """VLC stand-in whose audio output becomes ready after `ready_after` calls."""

    def __init__(self, vlc_volume=100, ready_after=0, states=None):
        self._volume = vlc_volume
        self._ready_after = ready_after
        self._states = list(states) if states else None
        self.set_calls = []

    def _ready(self):
        return self._ready_after <= 0

    def audio_set_volume(self, value):
        self.set_calls.append(value)
        if self._ready():
            self._volume = int(value)
            return 0
        self._ready_after -= 1
        return -1

    def audio_get_volume(self):
        return self._volume if self._ready() else -1

    def get_state(self):
        if self._states:
            return self._states.pop(0) if len(self._states) > 1 else self._states[0]
        return Opening if not self._ready() else Playing


class DummyFrame:
    def __init__(self, is_casting=False, initial_volume=100, player=None):
        self.is_casting = is_casting
        self.volume = initial_volume
        self.player = player if player is not None else DummyPlayer()
        self.ui_update_calls = []

    def _update_volume_ui(self, val):
        self.ui_update_calls.append(val)

    def _apply_volume_when_ready(self, _seq=None, _stubborn=0, _started=None):
        return PlayerFrame._apply_volume_when_ready(self, _seq, _stubborn, _started)


def _run_synchronously(monkeypatch):
    """Make wx.CallLater invoke the retry immediately (no event loop in tests)."""
    def fake_call_later(_delay_ms, callback, *args):
        callback(*args)
    monkeypatch.setattr(player_mod.wx, "CallLater", fake_call_later)


def _capture_call_later(monkeypatch):
    """Collect scheduled retries instead of running them, for manual firing."""
    pending = []

    def fake_call_later(_delay_ms, callback, *args):
        pending.append((callback, args))
    monkeypatch.setattr(player_mod.wx, "CallLater", fake_call_later)
    return pending


def test_applies_configured_volume_once_output_is_ready(monkeypatch):
    _run_synchronously(monkeypatch)
    # VLC plays at 100 but the configured volume is 40; the first two set
    # attempts are dropped because the output isn't ready yet.
    frame = DummyFrame(initial_volume=40, player=DummyPlayer(vlc_volume=100, ready_after=2))

    frame._apply_volume_when_ready()

    assert frame.player.audio_get_volume() == 40
    assert frame.volume == 40  # tracked value never drifted
    assert frame.ui_update_calls[-1] == 40


def test_survives_long_buffering(monkeypatch):
    """A slow stream can buffer well past the old 3s budget (12 attempts);
    the loop must keep retrying until the output finally exists."""
    _run_synchronously(monkeypatch)
    frame = DummyFrame(initial_volume=40, player=DummyPlayer(vlc_volume=100, ready_after=40))

    frame._apply_volume_when_ready()

    assert frame.player.audio_get_volume() == 40
    assert frame.volume == 40
    assert len(frame.player.set_calls) == 41  # kept going far beyond 12


def test_applies_immediately_when_output_ready():
    frame = DummyFrame(initial_volume=55, player=DummyPlayer(vlc_volume=100, ready_after=0))
    frame._apply_volume_when_ready()
    assert frame.player.audio_get_volume() == 55
    assert frame.player.set_calls == [55]


def test_stops_when_playback_attempt_dies(monkeypatch):
    """No infinite retry loop after the stream errors out."""
    _run_synchronously(monkeypatch)
    player = DummyPlayer(vlc_volume=100, ready_after=999,
                         states=[Opening, Opening, Opening, Opening, Error])
    frame = DummyFrame(initial_volume=40, player=player)

    frame._apply_volume_when_ready()

    assert frame.volume == 40  # never adopted a bogus value
    assert frame.ui_update_calls == []
    assert len(player.set_calls) == 5  # stopped at Error, not unbounded


def test_new_attempt_supersedes_pending_retries(monkeypatch):
    """A pending retry from an older track load must not fire after a newer
    load started its own loop (no stacked/fighting loops)."""
    pending = _capture_call_later(monkeypatch)
    frame = DummyFrame(initial_volume=40, player=DummyPlayer(vlc_volume=100, ready_after=999))

    frame._apply_volume_when_ready()  # attempt 1: schedules a retry
    assert len(pending) == 1
    old_cb, old_args = pending.pop()

    frame._apply_volume_when_ready()  # attempt 2 (new track) bumps the seq
    assert len(pending) == 1
    calls_before = len(frame.player.set_calls)

    old_cb(*old_args)  # stale retry fires: must no-op
    assert len(frame.player.set_calls) == calls_before


def test_adopts_vlc_volume_when_set_never_sticks(monkeypatch):
    _run_synchronously(monkeypatch)

    class StubbornPlayer:
        """Output exists (get works) but set is rejected — e.g. exotic aout."""
        def __init__(self):
            self.set_calls = []

        def audio_set_volume(self, value):
            self.set_calls.append(value)
            return -1

        def audio_get_volume(self):
            return 80

        def get_state(self):
            return Playing

    frame = DummyFrame(initial_volume=40, player=StubbornPlayer())
    frame._apply_volume_when_ready()

    # Tracked volume matches what the user actually hears, so the next
    # adjustment is 80±step instead of a jump to 40±step.
    assert frame.volume == 80
    assert frame.ui_update_calls[-1] == 80
    assert len(frame.player.set_calls) == 8  # bounded fight, then adopt


def test_casting_returns_early():
    frame = DummyFrame(is_casting=True, initial_volume=40)
    frame._apply_volume_when_ready()
    assert frame.player.set_calls == []
    assert frame.volume == 40


def test_player_exception_is_swallowed():
    class ErrorPlayer:
        def audio_set_volume(self, value):
            raise RuntimeError("VLC connection error")

        def audio_get_volume(self):
            raise RuntimeError("VLC connection error")

    frame = DummyFrame(initial_volume=40, player=ErrorPlayer())
    frame._apply_volume_when_ready()  # must not raise
    assert frame.volume == 40
    assert frame.ui_update_calls == []
