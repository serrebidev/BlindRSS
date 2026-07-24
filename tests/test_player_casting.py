# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import pytest

wx = pytest.importorskip("wx")
pytest.importorskip("vlc")

import gui.player as player_mod
from core.casting import CastDevice, CastProtocol


class _Control:
    def __init__(self):
        self.label = None

    def SetLabel(self, label):
        self.label = str(label)


class _MenuItem:
    def __init__(self):
        self.label = None

    def SetItemLabel(self, label):
        self.label = str(label)


class _LocalPlayer:
    def __init__(self):
        self.pause_calls = []
        self.play_calls = 0

    def set_pause(self, paused):
        self.pause_calls.append(int(paused))

    def pause(self):
        self.pause_calls.append(1)

    def play(self):
        self.play_calls += 1


class _CastingManager:
    def __init__(self, connected=True, play_error=None):
        self.connected = bool(connected)
        self.play_error = play_error
        self.connected_checks = []
        self.connect_calls = []
        self.play_calls = []
        self.disconnect_calls = 0

    def is_connected_to(self, device):
        self.connected_checks.append(device)
        return self.connected

    def connect(self, device, credentials=None):
        self.connect_calls.append((device, credentials))
        self.connected = True

    def play(self, url, title, content_type=None, start_time_seconds=None):
        self.play_calls.append((url, title, content_type, start_time_seconds))
        if self.play_error is not None:
            raise self.play_error

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False

    def get_status_async(self, callback):
        self.status_callback = callback
        return object()

    def play_async(self, url, title, content_type=None, start_time_seconds=None, callback=None):
        self.play_calls.append((url, title, content_type, start_time_seconds))
        self.recovery_callback = callback
        return object()

    def pause_async(self):
        return object()


class _CastDialog:
    selected_device = CastDevice(
        name="R & B Room",
        protocol=CastProtocol.CHROMECAST,
        identifier="94b4d1b1-08bb-5fee-ca1c-491e0f225607",
        host="192.168.1.73",
        port=8009,
    )

    def __init__(self, parent, manager, config_manager=None):
        self.parent = parent
        self.manager = manager
        self.config_manager = config_manager
        self.destroyed = False

    def ShowModal(self):
        return wx.ID_OK

    def Destroy(self):
        self.destroyed = True


class _Frame:
    def __init__(self, *, connected, play_error=None):
        self.is_casting = False
        self.config_manager = None
        self.casting_manager = _CastingManager(
            connected=connected,
            play_error=play_error,
        )
        self.cast_btn = _Control()
        self.title_lbl = _Control()
        self.player = _LocalPlayer()
        self.current_title = "Test episode"
        self.current_url = None
        self.current_chapters = []
        self.current_article_id = None
        self.is_playing = False
        self._seek_target_ms = None

    def _current_position_ms(self):
        return 0


def test_on_cast_reuses_connection_established_by_dialog(monkeypatch):
    monkeypatch.setattr(player_mod, "CastDialog", _CastDialog)
    frame = _Frame(connected=True)

    player_mod.PlayerFrame.on_cast(frame, None)

    assert frame.casting_manager.connected_checks == [_CastDialog.selected_device]
    assert frame.casting_manager.connect_calls == []
    assert frame.is_casting is True
    assert frame.cast_btn.label == "Disconnect"
    assert frame.title_lbl.label == "Test episode (Casting to R & B Room)"


def test_cast_menu_label_tracks_casting_state():
    frame = _Frame(connected=True)
    frame._cast_menu_item = _MenuItem()

    player_mod.PlayerFrame._refresh_cast_menu_state(frame)
    assert frame.cast_btn.label == "Cast"
    assert frame._cast_menu_item.label == "&Cast to Device..."

    frame.is_casting = True
    player_mod.PlayerFrame._refresh_cast_menu_state(frame)
    assert frame.cast_btn.label == "Disconnect"
    assert frame._cast_menu_item.label == "&Disconnect Cast"


def test_on_cast_reconnects_when_dialog_session_dropped(monkeypatch):
    monkeypatch.setattr(player_mod, "CastDialog", _CastDialog)
    frame = _Frame(connected=False)

    player_mod.PlayerFrame.on_cast(frame, None)

    assert frame.casting_manager.connect_calls == [(_CastDialog.selected_device, None)]
    assert frame.is_casting is True


def test_on_cast_play_failure_restores_local_playback(monkeypatch):
    monkeypatch.setattr(player_mod, "CastDialog", _CastDialog)
    messages = []
    monkeypatch.setattr(
        player_mod.wx,
        "MessageBox",
        lambda message, title, style: messages.append((message, title, style)),
    )
    frame = _Frame(connected=True, play_error=RuntimeError("load rejected"))
    frame.current_url = "https://example.com/episode.mp3"
    frame.is_playing = True

    player_mod.PlayerFrame.on_cast(frame, None)

    assert frame.casting_manager.disconnect_calls == 1
    assert frame.player.pause_calls == [1]
    assert frame.player.play_calls == 1
    assert frame.is_casting is False
    assert frame.cast_btn.label == "Cast"
    assert frame.title_lbl.label == "Test episode (Local)"
    assert messages[0][0] == "Casting failed: load rejected"


def test_on_cast_paused_item_sends_resume_position_and_pauses_remote(monkeypatch):
    monkeypatch.setattr(player_mod, "CastDialog", _CastDialog)
    frame = _Frame(connected=True)
    frame.current_url = "https://example.com/episode.mp3"
    frame.is_playing = False  # user casts a paused episode
    frame._current_position_ms = lambda: 30000
    remote_pauses = []
    frame.casting_manager.pause = lambda: remote_pauses.append(True)

    player_mod.PlayerFrame.on_cast(frame, None)

    assert frame.is_casting is True
    assert frame.player.pause_calls == [1]  # set_pause(1) for a paused item
    assert frame.casting_manager.play_calls == [
        ("https://example.com/episode.mp3", "Test episode", "audio/mpeg", 30.0)
    ]
    assert remote_pauses == [True]  # remote paused to mirror local state
    assert frame.is_playing is False
    assert frame._cast_handoff_source_url == "https://example.com/episode.mp3"


def test_on_cast_uses_live_position_instead_of_stale_seek_target(monkeypatch):
    monkeypatch.setattr(player_mod, "CastDialog", _CastDialog)
    frame = _Frame(connected=True)
    frame.current_url = "https://example.com/episode.mp3"
    frame.is_playing = True
    frame._seek_target_ms = 0  # stale target from an earlier seek
    frame._current_position_ms = lambda: 30_000

    player_mod.PlayerFrame.on_cast(frame, None)

    assert frame.casting_manager.play_calls == [
        ("https://example.com/episode.mp3", "Test episode", "audio/mpeg", 30.0)
    ]


def test_cast_status_poll_is_single_flight_and_applied_via_callback(monkeypatch):
    monkeypatch.setattr(player_mod.wx, "CallAfter", lambda fn, *args: fn(*args))
    frame = _Frame(connected=True)
    frame.is_casting = True
    frame._cast_session_token = 3
    frame._cast_status_poll_inflight = False
    frame._cast_last_pos_ms = 1_000
    frame._cast_last_pos_ts = 0.0
    frame._cast_missing_status_count = 0
    frame._cast_recovery_attempted = False
    frame._cast_recovery_inflight = False
    frame._cast_started_ts = player_mod.time.monotonic()
    frame._request_cast_status_poll = player_mod.PlayerFrame._request_cast_status_poll.__get__(frame)
    frame._apply_cast_status = player_mod.PlayerFrame._apply_cast_status.__get__(frame)

    frame._request_cast_status_poll()
    frame._request_cast_status_poll()

    assert frame._cast_status_poll_inflight is True
    callback = frame.casting_manager.status_callback
    callback({"position_seconds": 42.5, "supports_session_detection": False})
    assert frame._cast_status_poll_inflight is False
    assert frame._cast_last_pos_ms == 42_500


def test_missing_chromecast_session_recovers_once_at_last_position(monkeypatch):
    monkeypatch.setattr(player_mod.wx, "CallAfter", lambda fn, *args: fn(*args))
    frame = _Frame(connected=True)
    frame.is_casting = True
    frame.is_playing = True
    frame.current_url = "https://example.com/episode.mp3"
    frame._cast_session_token = 7
    frame._cast_status_poll_inflight = True
    frame._cast_missing_status_count = 0
    frame._cast_recovery_attempted = False
    frame._cast_recovery_inflight = False
    frame._cast_started_ts = 0.0
    frame._cast_content_type = "audio/mpeg"
    frame.duration = 1_800_000  # VOD podcast: known length -> recover at position
    frame._current_position_ms = lambda: 320_000
    frame._apply_cast_status = player_mod.PlayerFrame._apply_cast_status.__get__(frame)
    frame._start_cast_recovery = player_mod.PlayerFrame._start_cast_recovery.__get__(frame)
    frame._finish_cast_recovery = player_mod.PlayerFrame._finish_cast_recovery.__get__(frame)
    empty = {
        "connected": True,
        "media_session_id": None,
        "position_seconds": None,
        "supports_session_detection": True,
    }

    frame._apply_cast_status(7, empty)
    frame._apply_cast_status(7, empty)
    frame._apply_cast_status(7, empty)

    assert frame.casting_manager.play_calls == [
        ("https://example.com/episode.mp3", "Test episode", "audio/mpeg", 320.0)
    ]
    frame.casting_manager.recovery_callback(None)
    frame._apply_cast_status(7, empty)
    assert len(frame.casting_manager.play_calls) == 1


def test_disconnected_chromecast_triggers_teardown_after_two_polls(monkeypatch):
    frame = _Frame(connected=True)
    frame.is_casting = True
    frame._cast_session_token = 9
    frame._cast_started_ts = 0.0  # outside startup grace
    frame._cast_disconnect_count = 0
    calls = []
    frame._handle_cast_connection_lost = lambda token: calls.append(token)
    frame._apply_cast_status = player_mod.PlayerFrame._apply_cast_status.__get__(frame)
    down = {"connected": False, "media_session_id": None, "supports_session_detection": True}

    frame._apply_cast_status(9, down)
    assert calls == []  # one disconnected poll: not yet
    frame._apply_cast_status(9, down)
    assert calls == [9]  # two consecutive: fall back to local


def test_disconnected_count_resets_on_reconnect(monkeypatch):
    frame = _Frame(connected=True)
    frame.is_casting = True
    frame._cast_session_token = 1
    frame._cast_started_ts = 0.0
    frame._cast_disconnect_count = 0
    calls = []
    frame._handle_cast_connection_lost = lambda token: calls.append(token)
    frame._apply_cast_status = player_mod.PlayerFrame._apply_cast_status.__get__(frame)
    down = {"connected": False, "media_session_id": None, "supports_session_detection": True}
    up = {"connected": True, "media_session_id": 5, "supports_session_detection": True}

    frame._apply_cast_status(1, down)
    frame._apply_cast_status(1, up)     # reconnect clears the counter
    frame._apply_cast_status(1, down)
    assert calls == []                  # only one disconnected poll since reset


def test_handle_cast_connection_lost_restores_local(monkeypatch):
    monkeypatch.setattr(player_mod.PlayerFrame, "_refresh_cast_menu_state", lambda self: None)
    frame = _Frame(connected=True)
    frame.is_casting = True
    frame._cast_session_token = 3
    frame.current_url = "https://example.com/episode.mp3"
    frame.is_playing = True
    frame._current_position_ms = lambda: 5000
    frame._set_status = lambda text: None
    restored = []
    frame._restore_local_after_cast = lambda pos, playing: restored.append((pos, playing))
    frame.casting_manager.disconnect_async = lambda callback=None: None
    frame._handle_cast_connection_lost = player_mod.PlayerFrame._handle_cast_connection_lost.__get__(frame)

    frame._handle_cast_connection_lost(3)
    assert frame.is_casting is False
    assert frame._cast_session_token == 4          # session retired
    assert restored == [(5000, True)]              # local playback restored at position


def test_restore_local_after_cast_reloads_when_media_differs():
    frame = _Frame(connected=True)
    frame.current_url = "https://example.com/episode.mp3"
    frame._cast_handoff_source_url = None  # not the same media -> reload
    frame.current_chapters = []
    frame.current_article_id = None
    loaded = []
    frame.load_media = lambda url, **kw: loaded.append((url, kw))
    frame._resume_local_from_cast = lambda pos, playing: False
    frame._restore_local_after_cast = player_mod.PlayerFrame._restore_local_after_cast.__get__(frame)

    frame._restore_local_after_cast(320_000, True)
    assert loaded and loaded[0][0] == "https://example.com/episode.mp3"
    assert frame._pending_resume_seek_ms == 320_000
    assert frame._pending_resume_paused is False


def test_live_stream_recovery_recasts_without_start_position(monkeypatch):
    monkeypatch.setattr(player_mod.wx, "CallAfter", lambda fn, *args: fn(*args))
    frame = _Frame(connected=True)
    frame.is_casting = True
    frame.is_playing = True
    frame.current_url = "https://example.com/live"
    frame._cast_session_token = 2
    frame._cast_started_ts = 0.0
    frame._cast_missing_status_count = 0
    frame._cast_recovery_attempted = False
    frame._cast_recovery_inflight = False
    frame._cast_content_type = "audio/mpeg"
    frame.duration = 0  # live/unknown length
    frame._current_position_ms = lambda: 999_000
    frame._apply_cast_status = player_mod.PlayerFrame._apply_cast_status.__get__(frame)
    frame._start_cast_recovery = player_mod.PlayerFrame._start_cast_recovery.__get__(frame)
    frame._finish_cast_recovery = player_mod.PlayerFrame._finish_cast_recovery.__get__(frame)
    down = {"connected": True, "media_session_id": None, "supports_session_detection": True}

    frame._apply_cast_status(2, down)
    frame._apply_cast_status(2, down)

    # A live stream must not be re-cast at a bogus dead-reckoned offset.
    assert frame.casting_manager.play_calls == [
        ("https://example.com/live", "Test episode", "audio/mpeg", None)
    ]
