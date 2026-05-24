import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")

from gui.player import PlayerFrame


class DummyPlayer:
    def __init__(self, volume: int):
        self._volume = volume
        self.get_volume_calls = 0

    def audio_get_volume(self):
        self.get_volume_calls += 1
        return self._volume


class DummyFrame:
    def __init__(self, is_casting=False, initial_volume=100, vlc_volume=50):
        self.is_casting = is_casting
        self.volume = initial_volume
        self.player = DummyPlayer(vlc_volume)
        self.ui_update_calls = []

    def _update_volume_ui(self, val):
        self.ui_update_calls.append(val)


def test_sync_volume_from_vlc_success():
    frame = DummyFrame(is_casting=False, initial_volume=100, vlc_volume=70)
    PlayerFrame._sync_volume_from_vlc(frame)
    assert frame.volume == 70
    assert frame.ui_update_calls == [70]
    assert frame.player.get_volume_calls == 1


def test_sync_volume_from_vlc_casting_returns_early():
    frame = DummyFrame(is_casting=True, initial_volume=100, vlc_volume=70)
    PlayerFrame._sync_volume_from_vlc(frame)
    assert frame.volume == 100
    assert frame.player.get_volume_calls == 0
    assert frame.ui_update_calls == []


def test_sync_volume_from_vlc_error_returns_early():
    frame = DummyFrame(is_casting=False, initial_volume=100, vlc_volume=-1)
    PlayerFrame._sync_volume_from_vlc(frame)
    assert frame.volume == 100
    assert frame.ui_update_calls == []
    assert frame.player.get_volume_calls == 1


def test_sync_volume_from_vlc_exception_handled():
    class ErrorPlayer:
        def audio_get_volume(self):
            raise RuntimeError("VLC connection error")

    frame = DummyFrame(is_casting=False, initial_volume=100, vlc_volume=50)
    frame.player = ErrorPlayer()

    # This should not raise an exception
    PlayerFrame._sync_volume_from_vlc(frame)
    assert frame.volume == 100
    assert frame.ui_update_calls == []
