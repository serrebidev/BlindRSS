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

    def connect(self, device):
        self.connect_calls.append(device)
        self.connected = True

    def play(self, url, title, content_type=None, start_time_seconds=None):
        self.play_calls.append((url, title, content_type, start_time_seconds))
        if self.play_error is not None:
            raise self.play_error

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False


class _CastDialog:
    selected_device = CastDevice(
        name="R & B Room",
        protocol=CastProtocol.CHROMECAST,
        identifier="94b4d1b1-08bb-5fee-ca1c-491e0f225607",
        host="192.168.1.73",
        port=8009,
    )

    def __init__(self, parent, manager):
        self.parent = parent
        self.manager = manager
        self.destroyed = False

    def ShowModal(self):
        return wx.ID_OK

    def Destroy(self):
        self.destroyed = True


class _Frame:
    def __init__(self, *, connected, play_error=None):
        self.is_casting = False
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


def test_on_cast_reconnects_when_dialog_session_dropped(monkeypatch):
    monkeypatch.setattr(player_mod, "CastDialog", _CastDialog)
    frame = _Frame(connected=False)

    player_mod.PlayerFrame.on_cast(frame, None)

    assert frame.casting_manager.connect_calls == [_CastDialog.selected_device]
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
    scheduled = []
    monkeypatch.setattr(
        player_mod.wx,
        "CallLater",
        lambda ms, fn: scheduled.append((ms, fn)),
    )
    frame = _Frame(connected=True)
    frame.current_url = "https://example.com/episode.mp3"
    frame.is_playing = False  # user casts a paused episode
    frame._current_position_ms = lambda: 30000
    frame._cast_handoff_seek_tick = lambda: None  # real PlayerFrame method
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
    assert scheduled and scheduled[0][0] == 1200  # resume-seek handoff scheduled
