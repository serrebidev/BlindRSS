# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Speech feedback from a hidden player and from the -/+10 s buttons.

With "show player on play" off (the default) a listener pressed
Enter on a YouTube item and heard nothing for 19 s, the time the stream took to
fail over to download-to-play; the player's status label was the only feedback
and it was hidden. The -/+10 s buttons only echoed "space".
"""

import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")

import gui.player as player_mod
from gui.player import PlayerFrame

_ = player_mod._


def _hidden_player(shown=False):
    p = MagicMock()
    p._hidden_announced = set()
    p.IsShown.return_value = shown
    return p


def test_hidden_player_says_each_state_once_through_the_main_window():
    p = _hidden_player()
    PlayerFrame._announce_when_hidden(p, _("Playing"))
    PlayerFrame._announce_when_hidden(p, _("Playing"))
    p.GetParent.return_value._announce_event.assert_called_once_with(
        "general", _("Playing"), interrupt=False
    )


def test_visible_player_stays_quiet_but_remembers_what_it_showed():
    p = _hidden_player(shown=True)
    PlayerFrame._announce_when_hidden(p, _("Playing"))
    # Hidden later, the first resume must not say "Playing" for this load.
    p.IsShown.return_value = False
    PlayerFrame._announce_when_hidden(p, _("Playing"))
    p.GetParent.return_value._announce_event.assert_not_called()


def _set_status(monkeypatch, p, text):
    monkeypatch.setattr(player_mod.wx, "IsMainThread", lambda: True)
    PlayerFrame._set_status(p, text)


def test_status_changes_that_matter_are_announced(monkeypatch):
    p = _hidden_player()
    p._status_text = _("Buffering...")
    p._load_start_ts = 12.0  # VLC has this load's URL
    _set_status(monkeypatch, p, _("Playing"))
    p._announce_when_hidden.assert_called_once_with(_("Playing"))

    p = _hidden_player()
    p._status_text = _("Connecting...")
    p._load_start_ts = 0.0
    _set_status(monkeypatch, p, _("Downloading for playback..."))
    p._announce_when_hidden.assert_called_once_with(_("Downloading for playback..."))


def test_previous_item_still_playing_during_resolve_is_not_announced(monkeypatch):
    p = _hidden_player()
    p._status_text = _("Connecting...")
    p._load_start_ts = 0.0  # still resolving; VLC plays the old item
    _set_status(monkeypatch, p, _("Playing"))
    _set_status(monkeypatch, p, _("Buffering..."))
    p._announce_when_hidden.assert_not_called()


WATCH_URL = "https://www.youtube.com/watch?v=abcDEF12345"
QUEUE = [
    {"media_url": "https://cdn.example.com/a.mp3", "title": "Episode A"},
    {"media_url": "https://cdn.example.com/b.mp3", "title": "Episode B"},
]


class _Cfg:
    def get(self, key, default=None):
        return False if key == "show_player_on_play" else default


def _world(monkeypatch):
    """A hidden player wired to the real play-queue code. `spoken` is what the
    screen reader is sent, `interrupting` the messages that cut off whatever it
    was reading, and `pump()` runs what wx.CallAfter posted, as the event loop
    would."""
    from gui.mainframe import MainFrame

    posted, spoken, interrupting = [], [], []
    monkeypatch.setattr(player_mod.wx, "CallAfter", lambda fn, *a, **kw: posted.append((fn, a, kw)))
    monkeypatch.setattr(player_mod.wx, "IsMainThread", lambda: True)

    mf = MagicMock()
    mf.config_manager = _Cfg()
    mf._get_play_queue.return_value = [dict(e) for e in QUEUE]
    mf._current_queue_index = 0
    def _announce_event(_event, msg, interrupt=True):
        spoken.append(msg)
        if interrupt:
            interrupting.append(msg)

    mf._announce_event.side_effect = _announce_event
    mf.play_queue_index.side_effect = lambda i, **kw: MainFrame.play_queue_index(mf, i, **kw)

    pw = MagicMock()
    pw.is_casting = False
    pw._load_seq = 0
    pw._hidden_announced = set()
    pw._status_text = ""
    pw.IsShown.return_value = False
    pw.GetParent.return_value = mf
    pw.config_manager = _Cfg()
    pw.load_media.side_effect = lambda *a, **kw: PlayerFrame.load_media(pw, *a, **kw)
    pw._announce_when_hidden.side_effect = (
        lambda text, **kw: PlayerFrame._announce_when_hidden(pw, text, **kw)
    )
    mf._ensure_player_window.return_value = pw

    def pump():
        while posted:
            fn, a, kw = posted.pop(0)
            fn(*a, **kw)

    def vlc_starts_playing():
        pw._load_start_ts = 1.0  # _load_vlc_url has handed VLC the URL
        PlayerFrame._set_status(pw, _("Buffering..."))
        PlayerFrame._set_status(pw, _("Playing"))

    mf.interrupting = interrupting
    return MainFrame, mf, pw, spoken, pump, vlc_starts_playing


def test_load_media_starts_a_new_round_and_says_loading(monkeypatch):
    _MainFrame, _mf, pw, spoken, pump, _vlc = _world(monkeypatch)
    pw._hidden_announced = {_("Playing")}
    PlayerFrame.load_media(pw, WATCH_URL, use_ytdlp=True)
    assert pw._hidden_announced == set() and spoken == []
    pump()  # after the main window has shown or hidden the player
    assert spoken == [_("Loading media...")]


def test_queue_step_title_is_the_last_thing_said(monkeypatch):
    MainFrame, mf, _pw, spoken, pump, vlc_starts_playing = _world(monkeypatch)
    MainFrame._play_queue_step(mf, +1)
    pump()
    vlc_starts_playing()
    # Neither "Loading media..." nor the later "Playing" may cut the title off.
    assert spoken == ["Playing 2 of 2: Episode B"]


def test_queue_advancing_on_its_own_says_only_trouble(monkeypatch):
    MainFrame, mf, pw, spoken, pump, vlc_starts_playing = _world(monkeypatch)
    MainFrame._advance_play_queue(mf)
    pump()
    PlayerFrame._set_status(pw, _("Downloading for playback..."))
    vlc_starts_playing()
    PlayerFrame._announce_when_hidden(pw, _("Failed to load media"))
    assert spoken == [_("Downloading for playback..."), _("Failed to load media")]


def test_play_queue_dialog_pick_is_announced(monkeypatch):
    MainFrame, mf, _pw, spoken, pump, vlc_starts_playing = _world(monkeypatch)
    MainFrame.play_queue_index(mf, 1)
    pump()
    vlc_starts_playing()
    assert spoken == [_("Loading media..."), _("Playing")]
    # Only the answer to the keypress interrupts; "Playing" seconds later
    # must not cut off what the screen reader is reading by then.
    assert mf.interrupting == [_("Loading media...")]


def test_unasked_states_do_not_interrupt(monkeypatch):
    _MainFrame, mf, pw, spoken, _pump, _vlc = _world(monkeypatch)
    PlayerFrame._set_status(pw, _("Downloading for playback..."))
    PlayerFrame._announce_when_hidden(pw, _("Failed to load media"))
    assert spoken == [_("Downloading for playback..."), _("Failed to load media")]
    assert mf.interrupting == []


def test_download_replay_does_not_say_loading_again():
    p = _hidden_player()
    p._active_load_seq = 2
    said = {_("Loading media..."), _("Downloading for playback...")}
    p._hidden_announced = set(said)

    def _fake_load_media(*_a, **_kw):
        p._hidden_announced = set()

    p.load_media.side_effect = _fake_load_media
    PlayerFrame._play_local_after_download(p, 2, r"C:\cache\abcDEF12345.m4a")
    assert p._hidden_announced == said


def test_vlc_error_with_nothing_left_to_retry_is_announced(monkeypatch):
    monkeypatch.setattr(player_mod, "get_range_cache_proxy", MagicMock())
    failed = _("Failed to load media")

    p = _hidden_player()
    p.is_casting = False
    p._active_load_seq = 1
    p.maybe_play_ytdlp_via_download.return_value = False
    p._last_vlc_url = r"C:\cache\abcDEF12345.m4a"
    p._last_used_range_proxy = False
    PlayerFrame._handle_vlc_error(p)
    p._announce_when_hidden.assert_called_once_with(failed)

    # The proxy retries are still in flight: nothing to say yet.
    p = _hidden_player()
    p.is_casting = False
    p._active_load_seq = 1
    p.maybe_play_ytdlp_via_download.return_value = False
    p._last_vlc_url = "http://127.0.0.1:1/media?id=x"
    p._last_used_range_proxy = True
    p._last_orig_url = "https://cdn.example/episode.mp3"
    p._pos_ms = 0
    p.player.get_time.return_value = 0
    p._range_proxy_retry_count = 1
    PlayerFrame._handle_vlc_error(p)
    p._announce_when_hidden.assert_not_called()

    # Both retries used up.
    p._last_used_range_proxy = True
    PlayerFrame._handle_vlc_error(p)
    p._announce_when_hidden.assert_called_once_with(failed)


class _FakeCallLater:
    made = []

    def __init__(self, ms, fn):
        self.ms, self.fn, self.restarts = ms, fn, 0
        _FakeCallLater.made.append(self)

    def IsRunning(self):
        return True

    def Restart(self, ms):
        self.restarts += 1


def _seek_player():
    p = MagicMock()
    p._seek_target_ts = 5.0
    p._seek_announce_calllater = None

    def _seek(_delta):
        p._seek_target_ts = time.monotonic()

    p.seek_relative_ms.side_effect = _seek
    return p


def test_seek_buttons_announce_once_after_presses_settle(monkeypatch):
    _FakeCallLater.made = []
    monkeypatch.setattr(player_mod.wx, "CallLater", _FakeCallLater)
    p = _seek_player()
    PlayerFrame._seek_by_button(p, 10000)
    PlayerFrame._seek_by_button(p, 10000)
    PlayerFrame._seek_by_button(p, -10000)
    assert len(_FakeCallLater.made) == 1
    timer = _FakeCallLater.made[0]
    assert timer.fn is p._announce_seek_position and timer.restarts == 2


def test_refused_seek_at_the_end_adds_no_position(monkeypatch):
    _FakeCallLater.made = []
    monkeypatch.setattr(player_mod.wx, "CallLater", _FakeCallLater)
    p = _seek_player()
    p.seek_relative_ms.side_effect = None  # refused: "End of track" was said
    PlayerFrame._seek_by_button(p, 10000)
    assert _FakeCallLater.made == []


def test_seek_buttons_route_through_the_announcing_seek():
    p = MagicMock()
    p.is_casting = False
    p.seek_forward_ms = 10000
    p.seek_back_ms = 10000
    PlayerFrame.on_forward(p, None)
    PlayerFrame.on_rewind(p, None)
    assert [c.args for c in p._seek_by_button.call_args_list] == [(10000,), (-10000,)]


@pytest.mark.parametrize(
    "duration, expected",
    [(45 * 60 * 1000, "Elapsed 01:23, Remaining 43:37, Total 45:00"), (0, "Elapsed 01:23")],
)
def test_seek_position_text(duration, expected):
    p = MagicMock()
    p._current_position_ms.return_value = 83_000
    p.duration = duration
    p._format_time.side_effect = lambda ms: PlayerFrame._format_time(p, ms)
    p._remaining_ms.side_effect = lambda ms: PlayerFrame._remaining_ms(p, ms)
    p._compose_time_info.side_effect = lambda ms: PlayerFrame._compose_time_info(p, ms)
    PlayerFrame._announce_seek_position(p)
    p._announce_media_nav.assert_called_once_with(expected)


def test_pending_seek_announcement_is_dropped_on_load_and_shutdown():
    p = MagicMock()
    p.is_casting = False
    p._load_seq = 0
    PlayerFrame.load_media(p, "https://cdn.example.com/next.mp3")
    assert ("_seek_announce_calllater",) in [c.args[:1] for c in p._stop_calllater.call_args_list]

    p = MagicMock()
    p._shutdown_done = False
    p.is_casting = False
    PlayerFrame.shutdown(p)
    assert ("_seek_announce_calllater",) in [c.args[:1] for c in p._stop_calllater.call_args_list]
