# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Casting built on Caster's engine: routing, resume positions, transport controls."""

import ast
import os
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from core import casting  # noqa: E402


# --------------------------------------------------------------------------- #
# The vendored engine
# --------------------------------------------------------------------------- #
def test_engine_is_gui_free_and_complete():
    with open(os.path.join(REPO_ROOT, "caster_engine.py"), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"wx", "caster_ui", "caster_update", "pychromecast", "pyatv"}
    import caster_engine
    for name in ("HlsRelay", "TsSource", "probe_media", "Device", "LoopThread",
                 "SeekablePipeReader", "_close_atv", "_set_atv_volume"):
        assert hasattr(caster_engine, name), name


def test_engine_matches_caster_checkout():
    caster_dir = os.path.join(os.path.dirname(REPO_ROOT), "Caster")
    if not os.path.exists(os.path.join(caster_dir, "caster.py")):
        pytest.skip("no Caster checkout beside this repository")
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
    import sync_caster

    with open(os.path.join(caster_dir, "caster.py"), encoding="utf-8") as handle:
        engine, _version = sync_caster.extract_engine(handle.read())
    with open(os.path.join(REPO_ROOT, "caster_engine.py"), encoding="utf-8") as handle:
        vendored = handle.read()
    if engine not in vendored:
        pytest.skip("Caster has moved on since the last sync; run tools/sync_caster.py")


def test_engine_uses_blindrss_ffmpeg():
    casting._engine()
    import caster_engine
    import caster_extras
    assert caster_engine._find_ffmpeg is casting._ffmpeg_path
    assert caster_extras._find_ffmpeg is casting._ffmpeg_path


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
def _device(kind, key, sinks=frozenset(), name=None):
    import caster_engine
    return casting.CastDevice.from_engine(
        caster_engine.Device(kind, name or ("Test " + kind), key, sinks=sinks))


def test_device_keeps_the_fields_the_player_uses():
    device = _device("chromecast", {"host": "192.0.2.5", "port": 8009,
                                    "uuid": "94b4d1b1-08bb-5fee-ca1c-491e0f225607"},
                     name="RB Room")
    assert device.protocol is casting.CastProtocol.CHROMECAST
    assert device.display_name == "RB Room [Chromecast]"
    assert device.unique_id == "Chromecast:94b4d1b1-08bb-5fee-ca1c-491e0f225607"
    assert device.host == "192.0.2.5"
    # Built by hand (as the player's tests do), a device still works as a key.
    manual = casting.CastDevice(name="X", protocol=casting.CastProtocol.KODI,
                                identifier="http://k:8080", host="k", port=8080)
    assert manual.kind == "kodi"


def test_pairing_is_not_offered():
    manager = casting.CastingManager()
    with pytest.raises(casting.CastError):
        manager.start_pairing(None)
    assert manager.finish_pairing(None, "1234") is None


# --------------------------------------------------------------------------- #
# Where the receiver fetches from
# --------------------------------------------------------------------------- #
class _Proxy:
    def __init__(self):
        self.calls = []

    def get_file_url(self, path, device_ip=None):
        self.calls.append(("file", path, device_ip))
        return "http://lan/file"

    def get_proxied_url(self, url, headers=None, device_ip=None):
        self.calls.append(("proxy", url, headers, device_ip))
        return "http://lan/proxy"


@pytest.fixture
def proxy(monkeypatch):
    import core.stream_proxy
    fake = _Proxy()
    monkeypatch.setattr(core.stream_proxy, "get_proxy", lambda: fake)
    return fake


def test_local_files_and_localhost_go_through_the_proxy(proxy, tmp_path):
    episode = tmp_path / "episode.mp3"
    episode.write_bytes(b"ID3")
    device = _device("kodi", {"base": "http://192.0.2.9:8080"})
    manager = casting.CastingManager()
    assert manager._source_url(str(episode), {}, device) == "http://lan/file"
    assert manager._source_url(episode.as_uri(), {}, device) == "http://lan/file"
    assert manager._source_url("http://127.0.0.1:5000/cache/1", {}, device) == "http://lan/proxy"
    assert manager._source_url("https://cdn.example/ep.mp3", {"User-Agent": "UA"}, device) \
        == "http://lan/proxy"
    assert manager._source_url("https://cdn.example/ep.mp3", {}, device) == "https://cdn.example/ep.mp3"
    assert all(call[-1] == "192.0.2.9" for call in proxy.calls)


# --------------------------------------------------------------------------- #
# Routing and resume positions
# --------------------------------------------------------------------------- #
@pytest.fixture
def manager(monkeypatch):
    mgr = casting.CastingManager()
    mgr._running = True
    monkeypatch.setattr(casting.CastingManager, "stop_playback", lambda self: None)
    return mgr


def _probe(mime, audio=True, live=False):
    return lambda url: {"url": url, "mime": mime, "is_audio": audio, "is_live": live}


def test_kodi_plays_and_resumes_at_the_position(manager, monkeypatch):
    import caster_devices
    calls = []
    monkeypatch.setattr(caster_devices, "kodi_play", lambda base, url, auth=("", ""): calls.append(("open", url)))
    monkeypatch.setattr(casting.CastingManager, "_kodi_player", staticmethod(lambda device: 1))
    monkeypatch.setattr(casting.CastingManager, "_kodi_seek",
                        lambda self, device, target: calls.append(("seek", target)))
    manager.active_device = _device("kodi", {"base": "http://kodi:8080"})
    manager.play("https://cdn.example/ep.mp3", "Episode", start_time_seconds=95)
    assert calls == [("open", "https://cdn.example/ep.mp3"), ("seek", 95.0)]


def test_upnp_push_then_seek_to_the_resume_position(manager, monkeypatch):
    import caster_engine
    import caster_extras
    pushed, sought = [], []
    monkeypatch.setattr(caster_engine, "probe_media", _probe("audio/mpeg"))
    monkeypatch.setattr(casting.CastingManager, "_upnp_push",
                        staticmethod(lambda device, url, mime, title: pushed.append((url, mime))))
    monkeypatch.setattr(caster_extras, "upnp_state", lambda control_url: "PLAYING")
    monkeypatch.setattr(casting.CastingManager, "_upnp_seek",
                        lambda self, device, target: sought.append(target))
    manager.active_device = _device("upnp", {"control_url": "http://tv/ctl"})
    manager.play("https://cdn.example/ep.mp3", "Episode", start_time_seconds=61)
    assert pushed == [("https://cdn.example/ep.mp3", "audio/mpeg")]
    assert sought == [61.0]


def test_sonos_resumes_with_a_seek(manager, monkeypatch):
    import caster_devices
    import caster_engine
    played, sought = [], []

    class Zone:
        def seek(self, target):
            sought.append(target)

    monkeypatch.setattr(caster_engine, "probe_media", _probe("audio/mpeg"))
    monkeypatch.setattr(caster_devices, "sonos_play",
                        lambda ip, url, title="", mime="": played.append((ip, mime)))
    monkeypatch.setattr(casting.CastingManager, "_sonos_zone", staticmethod(lambda device: Zone()))
    manager.active_device = _device("sonos", {"ip": "10.0.0.5"})
    manager.play("https://cdn.example/ep.mp3", "Episode", start_time_seconds=3725)
    assert played == [("10.0.0.5", "audio/mpeg")]
    assert sought == ["1:02:05"]


def test_play_without_a_device_raises(manager):
    with pytest.raises(casting.CastError):
        manager.play("https://cdn.example/ep.mp3", "Episode")


def test_play_async_reports_none_on_failure(monkeypatch):
    mgr = casting.CastingManager()
    mgr.start()
    try:
        results = []
        future = mgr.play_async("https://cdn.example/ep.mp3", "Episode",
                                callback=results.append)
        future.exception(timeout=5)
        time.sleep(0.1)
        assert results == [None]
    finally:
        mgr.stop()


# --------------------------------------------------------------------------- #
# Transport controls and status
# --------------------------------------------------------------------------- #
def test_roku_position_comes_from_the_clock(manager, monkeypatch):
    import caster_devices
    import caster_engine
    keys = []
    monkeypatch.setattr(caster_engine, "probe_media", _probe("video/mp4", audio=False))
    monkeypatch.setattr(caster_devices, "roku_play", lambda *a, **k: None)
    monkeypatch.setattr(caster_devices, "roku_key", lambda base, key: keys.append(key))
    manager.active_device = _device("roku", {"base": "http://roku:8060"})
    manager.play("https://cdn.example/video.mp4", "Video", start_time_seconds=10)
    status = manager.get_status()
    assert status["player_state"] == "PLAYING"
    assert 10 <= status["position_seconds"] < 11
    manager.pause()
    assert keys == ["Play"]
    paused = manager.get_status()
    assert paused["player_state"] == "PAUSED"
    manager.pause()                      # already paused: no second toggle
    assert keys == ["Play"]
    manager.resume()
    assert keys == ["Play", "Play"]


def test_airplay_pause_resume_and_seek_restart_on_the_same_session(monkeypatch):
    """Pause stops the feed; resume and seek reopen it at the right position."""
    mgr = casting.CastingManager()
    woken = []
    monkeypatch.setattr(mgr, "_wake_air", lambda air: woken.append(air.pending_seek))

    class Proc:
        killed = False

        def poll(self):
            return None if not self.killed else -9

        def kill(self):
            self.killed = True

    air = casting._AirSession(0)
    air.state, air.pos, air.t0 = "playing", 30.0, time.monotonic() - 5
    air.proc = Proc()
    mgr._air = air

    mgr._air_pause()
    assert air.state == "paused" and air.proc.killed
    assert 34.5 < air.pos < 36
    paused_at = air.pos

    mgr._air_resume()
    assert air.state == "playing"
    assert woken[-1] == paused_at      # reopened where it paused

    mgr._air_seek(120.0)
    assert woken[-1] == 120.0
    assert 120 <= air.position() < 121


def test_airplay_live_stream_resumes_at_the_live_edge(monkeypatch):
    mgr = casting.CastingManager()
    woken = []
    monkeypatch.setattr(mgr, "_wake_air", lambda air: woken.append(air.pending_seek))
    air = casting._AirSession(0)
    air.state, air.live = "paused", True
    mgr._air = air
    mgr._air_resume()
    assert woken == [None]
    mgr._air_seek(50.0)                 # no seeking in a live stream
    assert woken == [None]


def test_chromecast_status_without_a_connection_says_disconnected():
    mgr = casting.CastingManager()
    mgr.active_device = _device("chromecast", {"host": "192.0.2.5", "port": 8009,
                                               "uuid": "94b4d1b1-08bb-5fee-ca1c-491e0f225607"})
    status = mgr.get_status()
    assert status["connected"] is False
    assert status["supports_session_detection"] is True


def test_hms_round_trip():
    assert casting._hms(3725) == "1:02:05"
    assert casting._parse_hms("1:02:05") == 3725
    assert casting._parse_hms("0:00:07.5") == 7.5
    assert casting._parse_hms("NOT_IMPLEMENTED") is None


def test_airplay_resume_after_the_receiver_ended_the_session_starts_again(monkeypatch):
    """A receiver can drop RAOP on its own; resume must not just claim PLAYING."""
    import concurrent.futures
    mgr = casting.CastingManager()
    replayed = []
    monkeypatch.setattr(mgr, "play", lambda url, title, channel, start_time_seconds=None:
                        replayed.append((url, start_time_seconds)))
    air = casting._AirSession(0)
    air.state, air.pos = "stopped", 64.0
    air.loop_future = concurrent.futures.Future()
    air.loop_future.set_result(None)        # the runner has finished
    mgr._air = air
    mgr._last_play = ("https://cdn.example/ep.mp3", "Episode", None)

    mgr._air_resume()
    assert replayed == [("https://cdn.example/ep.mp3", 64.0)]
    mgr._air_seek(150.0)
    assert replayed[-1] == ("https://cdn.example/ep.mp3", 150.0)
