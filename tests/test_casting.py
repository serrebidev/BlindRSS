# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import asyncio
import threading
import time
from types import SimpleNamespace
from uuid import UUID

import pytest

from core import casting


class _Browser:
    def __init__(self, *, fail_stop=False):
        self.fail_stop = bool(fail_stop)
        self.stop_calls = 0

    def stop_discovery(self):
        self.stop_calls += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")


class _Chromecast:
    def __init__(
        self,
        *,
        name="R & B Room",
        identifier="94b4d1b1-08bb-5fee-ca1c-491e0f225607",
        host="192.168.1.73",
        wait_error=None,
        connected=True,
        app_id=casting.APP_MEDIA_RECEIVER,
        start_app_error=None,
        quit_app_error=None,
    ):
        self.name = name
        self.uuid = UUID(identifier)
        self.cast_info = SimpleNamespace(
            friendly_name=name,
            host=host,
            port=8009,
        )
        self.model_name = "SmartTV 4K FFM"
        self.cast_type = "cast"
        self.wait_error = wait_error
        self.wait_calls = []
        self.disconnect_calls = []
        self.start_app_calls = []
        self.start_app_error = start_app_error
        self.quit_app_calls = []
        self.quit_app_error = quit_app_error
        self.status = SimpleNamespace(app_id=app_id)
        self.receiver_controller = SimpleNamespace(
            status=SimpleNamespace(app_id=app_id),
            app_id=app_id,
            update_status=lambda callback_function=None: (
                callback_function(True, {}) if callback_function else None
            ),
        )
        self.socket_client = SimpleNamespace(
            is_connected=bool(connected),
            receiver_controller=self.receiver_controller,
        )
        self.media_controller = SimpleNamespace(
            status=SimpleNamespace(media_session_id=None),
            update_status=lambda: None,
            stop=lambda: None,
        )

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.wait_error is not None:
            raise self.wait_error

    def disconnect(self, timeout=None):
        self.disconnect_calls.append(timeout)

    @property
    def app_id(self):
        return self.status.app_id

    def start_app(self, app_id, force_launch=False, timeout=None):
        self.start_app_calls.append((app_id, force_launch, timeout))
        if self.start_app_error is not None:
            raise self.start_app_error
        self.status.app_id = app_id
        self.receiver_controller.status.app_id = app_id
        self.receiver_controller.app_id = app_id

    def quit_app(self, timeout=None):
        self.quit_app_calls.append(timeout)
        if self.quit_app_error is not None:
            raise self.quit_app_error
        self.status.app_id = None
        self.receiver_controller.status.app_id = None
        self.receiver_controller.app_id = None


def _device(
    *,
    name="R & B Room",
    identifier="94b4d1b1-08bb-5fee-ca1c-491e0f225607",
    host="192.168.1.73",
):
    return casting.CastDevice(
        name=name,
        protocol=casting.CastProtocol.CHROMECAST,
        identifier=identifier,
        host=host,
        port=8009,
    )


def test_chromecast_discovery_preserves_name_and_always_stops_browser(monkeypatch):
    browser = _Browser(fail_stop=True)
    chromecast = _Chromecast()
    monkeypatch.setattr(
        casting.pychromecast,
        "get_chromecasts",
        lambda **kwargs: ([chromecast], browser),
    )

    caster = casting.ChromecastCaster()
    devices = asyncio.run(caster.discover(timeout=2.5))

    assert [device.name for device in devices] == ["R & B Room"]
    assert devices[0].identifier == str(chromecast.uuid)
    assert browser.stop_calls == 1


def test_chromecast_connect_uses_uuid_object_and_known_host(monkeypatch):
    browser = _Browser()
    chromecast = _Chromecast()
    calls = []

    def get_listed_chromecasts(**kwargs):
        calls.append(kwargs)
        return [chromecast], browser

    monkeypatch.setattr(
        casting.pychromecast,
        "get_listed_chromecasts",
        get_listed_chromecasts,
    )

    caster = casting.ChromecastCaster()
    asyncio.run(caster.connect(_device()))

    assert len(calls) == 1
    assert calls[0]["uuids"] == [chromecast.uuid]
    assert isinstance(calls[0]["uuids"][0], UUID)
    assert calls[0]["known_hosts"] == ["192.168.1.73"]
    assert calls[0]["discovery_timeout"] == caster._DISCOVERY_TIMEOUT
    assert chromecast.wait_calls == [caster._READY_TIMEOUT]
    assert caster.is_connected() is True


def test_chromecast_connect_falls_back_to_unescaped_name_and_cleans_first_browser(monkeypatch):
    uuid_browser = _Browser()
    name_browser = _Browser()
    chromecast = _Chromecast()
    calls = []

    def get_listed_chromecasts(**kwargs):
        calls.append(kwargs)
        if "uuids" in kwargs:
            return [], uuid_browser
        return [chromecast], name_browser

    monkeypatch.setattr(
        casting.pychromecast,
        "get_listed_chromecasts",
        get_listed_chromecasts,
    )

    caster = casting.ChromecastCaster()
    asyncio.run(caster.connect(_device()))

    assert len(calls) == 2
    assert calls[1]["friendly_names"] == ["R & B Room"]
    assert calls[1]["known_hosts"] == ["192.168.1.73"]
    assert uuid_browser.stop_calls == 1
    assert name_browser.stop_calls == 0


def test_chromecast_connect_failure_cleans_cast_and_browser(monkeypatch):
    browser = _Browser()
    chromecast = _Chromecast(wait_error=TimeoutError("not ready"))
    monkeypatch.setattr(
        casting.pychromecast,
        "get_listed_chromecasts",
        lambda **kwargs: ([chromecast], browser),
    )

    caster = casting.ChromecastCaster()
    with pytest.raises(casting.ConnectionError, match="R & B Room"):
        asyncio.run(caster.connect(_device()))

    assert chromecast.disconnect_calls == [5.0]
    assert browser.stop_calls == 1
    assert caster.is_connected() is False


def test_chromecast_connection_state_tracks_socket_state():
    caster = casting.ChromecastCaster()
    chromecast = _Chromecast(connected=False)
    caster._cast = chromecast

    assert caster.is_connected() is False

    chromecast.socket_client.is_connected = True
    assert caster.is_connected() is True


def test_chromecast_disconnect_is_bounded_and_stops_browser():
    caster = casting.ChromecastCaster()
    chromecast = _Chromecast()
    browser = _Browser()
    caster._cast = chromecast
    caster._browser = browser

    asyncio.run(caster.disconnect())

    assert chromecast.disconnect_calls == [5.0]
    assert browser.stop_calls == 1
    assert caster._cast is None
    assert caster._browser is None


def test_chromecast_play_proxies_windows_absolute_path_for_device(monkeypatch):
    local_path = r"C:\Users\admin\Music\test.wav"
    proxy_url = "http://192.168.1.20:8123/file/test-token"
    proxy_calls = []
    play_calls = []
    block_calls = []

    proxy = SimpleNamespace(
        get_file_url=lambda path, device_ip=None: (
            proxy_calls.append((path, device_ip)) or proxy_url
        )
    )
    chromecast = _Chromecast(host="192.168.1.73")
    chromecast.media_controller.play_media = (
        lambda url, content_type, **kwargs: play_calls.append(
            (url, content_type, kwargs)
        )
    )
    chromecast.media_controller.block_until_active = (
        lambda timeout=None: block_calls.append(timeout)
    )

    monkeypatch.setattr(casting, "get_proxy", lambda: proxy)
    monkeypatch.setattr(
        casting.os.path,
        "isfile",
        lambda path: path == local_path,
    )

    caster = casting.ChromecastCaster()
    caster._cast = chromecast
    asyncio.run(
        caster.play(
            local_path,
            title="Local test",
            content_type="audio/wav",
        )
    )

    assert proxy_calls == [(local_path, "192.168.1.73")]
    assert play_calls == [
        (
            proxy_url,
            "audio/wav",
            {
                "title": "Local test",
                "autoplay": True,
                "stream_type": "BUFFERED",
            },
        )
    ]
    assert play_calls[0][0] != local_path
    assert block_calls == [10]


def test_chromecast_play_launches_default_receiver_before_media(monkeypatch):
    events = []
    chromecast = _Chromecast(app_id="70FE3A67")

    def start_app(app_id, force_launch=False, timeout=None):
        events.append(("start_app", app_id, force_launch, timeout))
        chromecast.status.app_id = app_id
        chromecast.receiver_controller.status.app_id = app_id
        chromecast.receiver_controller.app_id = app_id

    chromecast.start_app = start_app
    chromecast.media_controller.play_media = (
        lambda url, content_type, **kwargs: events.append(
            ("play_media", url, content_type)
        )
    )
    chromecast.media_controller.block_until_active = lambda timeout=None: None
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._cast = chromecast
    asyncio.run(
        caster.play(
            "https://example.com/test.wav",
            title="Receiver handoff",
            content_type="audio/wav",
        )
    )

    assert events == [
        (
            "start_app",
            casting.APP_MEDIA_RECEIVER,
            True,
            caster._RECEIVER_LAUNCH_TIMEOUT,
        ),
        ("play_media", "https://example.com/test.wav", "audio/wav"),
    ]


def test_chromecast_play_does_not_relaunch_default_receiver(monkeypatch):
    chromecast = _Chromecast(app_id=casting.APP_MEDIA_RECEIVER)
    play_calls = []
    chromecast.media_controller.play_media = (
        lambda url, content_type, **kwargs: play_calls.append((url, content_type))
    )
    chromecast.media_controller.block_until_active = lambda timeout=None: None
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._cast = chromecast
    asyncio.run(
        caster.play(
            "https://example.com/test.wav",
            content_type="audio/wav",
        )
    )

    assert chromecast.start_app_calls == []
    assert play_calls == [("https://example.com/test.wav", "audio/wav")]


def test_chromecast_play_sends_start_time_and_one_bounded_seek(monkeypatch):
    chromecast = _Chromecast(app_id=casting.APP_MEDIA_RECEIVER)
    play_calls = []
    seek_calls = []
    chromecast.media_controller.play_media = (
        lambda url, content_type, **kwargs: play_calls.append((url, content_type, kwargs))
    )
    chromecast.media_controller.block_until_active = lambda timeout=None: None
    chromecast.media_controller.seek = (
        lambda position, timeout=None: seek_calls.append((position, timeout))
    )
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._cast = chromecast
    asyncio.run(
        caster.play(
            "https://example.com/episode.mp3",
            content_type="audio/mpeg",
            start_time_seconds=42.5,
        )
    )

    assert play_calls[0][2]["current_time"] == 42.5
    assert seek_calls == [(42.5, 2.0)]


def test_chromecast_status_waits_for_acknowledged_snapshot():
    chromecast = _Chromecast(app_id=casting.APP_MEDIA_RECEIVER)
    chromecast.status.transport_id = "transport-2"
    chromecast.media_controller.status = SimpleNamespace(
        media_session_id=9,
        content_id="https://example.com/episode.mp3",
        player_state="PLAYING",
        adjusted_current_time=320.75,
    )

    def update_status(callback_function=None):
        if callback_function:
            callback_function(True, {})

    chromecast.media_controller.update_status = update_status
    caster = casting.ChromecastCaster()
    caster._cast = chromecast

    status = asyncio.run(caster.get_status())

    assert status == {
        "position_seconds": 320.75,
        "media_session_id": 9,
        "content_id": "https://example.com/episode.mp3",
        "player_state": "PLAYING",
        "receiver_app_ids": [casting.APP_MEDIA_RECEIVER],
        "transport_id": "transport-2",
        "connected": True,
        "supports_session_detection": True,
    }


def test_casting_manager_seek_does_not_wait_for_network_completion():
    completed = threading.Event()

    class _SlowCaster:
        async def seek(self, position):
            await asyncio.sleep(0.15)
            completed.set()

    manager = casting.CastingManager()
    manager.active_caster = _SlowCaster()
    manager.start()
    try:
        started = time.monotonic()
        manager.seek(12.0)
        elapsed = time.monotonic() - started
        assert elapsed < 0.1
        assert completed.wait(1.0)
    finally:
        manager.stop()


def test_chromecast_receiver_launch_failure_is_playback_error(monkeypatch):
    chromecast = _Chromecast(
        app_id="70FE3A67",
        start_app_error=TimeoutError("launch timed out"),
    )
    play_calls = []
    chromecast.media_controller.play_media = lambda *args, **kwargs: play_calls.append(args)
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._RECEIVER_CONFIRM_TIMEOUT = 0.01
    caster._RECEIVER_STATUS_WAIT = 0.005
    caster._cast = chromecast

    with pytest.raises(casting.PlaybackError, match="Default Media Receiver"):
        asyncio.run(
            caster.play(
                "https://example.com/test.wav",
                content_type="audio/wav",
            )
        )

    assert play_calls == []


def test_chromecast_play_accepts_acknowledged_launch_without_app_status(monkeypatch):
    chromecast = _Chromecast(app_id=None)
    launch_calls = []
    play_calls = []
    chromecast.start_app = (
        lambda app_id, force_launch=False, timeout=None: launch_calls.append(
            (app_id, force_launch, timeout)
        )
    )
    chromecast.media_controller.play_media = (
        lambda url, content_type, **kwargs: play_calls.append((url, content_type))
    )
    chromecast.media_controller.block_until_active = lambda timeout=None: None
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._cast = chromecast
    asyncio.run(
        caster.play(
            "https://example.com/test.wav",
            content_type="audio/wav",
        )
    )

    assert launch_calls == [
        (
            casting.APP_MEDIA_RECEIVER,
            True,
            caster._RECEIVER_LAUNCH_TIMEOUT,
        )
    ]
    assert play_calls == [("https://example.com/test.wav", "audio/wav")]


def test_chromecast_does_not_play_when_receiver_status_stays_on_other_app(monkeypatch):
    chromecast = _Chromecast(app_id="70FE3A67")
    chromecast.start_app = lambda app_id, force_launch=False, timeout=None: None
    chromecast.quit_app = lambda timeout=None: None
    play_calls = []
    chromecast.media_controller.play_media = lambda *args, **kwargs: play_calls.append(args)
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._RECEIVER_CONFIRM_TIMEOUT = 0.02
    caster._RECEIVER_STATUS_WAIT = 0.005
    caster._cast = chromecast

    with pytest.raises(casting.PlaybackError, match="reported app: 70FE3A67"):
        asyncio.run(
            caster.play(
                "https://example.com/test.wav",
                content_type="audio/wav",
            )
        )

    assert play_calls == []


def test_chromecast_launch_timeout_can_be_confirmed_by_later_status(monkeypatch):
    chromecast = _Chromecast(app_id="70FE3A67")
    start_calls = []
    play_calls = []

    def start_app(app_id, force_launch=False, timeout=None):
        start_calls.append((app_id, force_launch, timeout))
        raise TimeoutError("launch response timed out")

    def update_status(callback_function=None):
        chromecast.status.app_id = casting.APP_MEDIA_RECEIVER
        chromecast.receiver_controller.status.app_id = casting.APP_MEDIA_RECEIVER
        chromecast.receiver_controller.app_id = casting.APP_MEDIA_RECEIVER
        if callback_function:
            callback_function(True, {})

    chromecast.start_app = start_app
    chromecast.receiver_controller.update_status = update_status
    chromecast.media_controller.play_media = (
        lambda url, content_type, **kwargs: play_calls.append((url, content_type))
    )
    chromecast.media_controller.block_until_active = lambda timeout=None: None
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._cast = chromecast
    asyncio.run(
        caster.play(
            "https://example.com/test.wav",
            content_type="audio/wav",
        )
    )

    assert start_calls == [
        (
            casting.APP_MEDIA_RECEIVER,
            True,
            caster._RECEIVER_LAUNCH_TIMEOUT,
        )
    ]
    assert chromecast.quit_app_calls == []
    assert play_calls == [("https://example.com/test.wav", "audio/wav")]


def test_chromecast_stops_other_app_and_retries_launch_once(monkeypatch):
    chromecast = _Chromecast(app_id="70FE3A67")
    events = []
    launch_attempts = 0

    def start_app(app_id, force_launch=False, timeout=None):
        nonlocal launch_attempts
        launch_attempts += 1
        events.append(("start_app", launch_attempts))
        if launch_attempts == 1:
            raise TimeoutError("first launch timed out")
        chromecast.status.app_id = app_id
        chromecast.receiver_controller.status.app_id = app_id
        chromecast.receiver_controller.app_id = app_id

    def quit_app(timeout=None):
        events.append(("quit_app", timeout))
        chromecast.status.app_id = None
        chromecast.receiver_controller.status.app_id = None
        chromecast.receiver_controller.app_id = None

    chromecast.start_app = start_app
    chromecast.quit_app = quit_app
    chromecast.media_controller.play_media = (
        lambda url, content_type, **kwargs: events.append(("play_media", url))
    )
    chromecast.media_controller.block_until_active = lambda timeout=None: None
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._RECEIVER_CONFIRM_TIMEOUT = 0.01
    caster._RECEIVER_STATUS_WAIT = 0.005
    caster._cast = chromecast
    asyncio.run(
        caster.play(
            "https://example.com/test.wav",
            content_type="audio/wav",
        )
    )

    assert events == [
        ("start_app", 1),
        ("quit_app", caster._RECEIVER_STOP_TIMEOUT),
        ("start_app", 2),
        ("play_media", "https://example.com/test.wav"),
    ]


def test_chromecast_media_command_failure_is_playback_error(monkeypatch):
    chromecast = _Chromecast(app_id=casting.APP_MEDIA_RECEIVER)
    chromecast.media_controller.play_media = (
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("load rejected"))
    )
    monkeypatch.setattr(casting, "get_proxy", lambda: None)

    caster = casting.ChromecastCaster()
    caster._cast = chromecast

    with pytest.raises(casting.PlaybackError, match="load rejected"):
        asyncio.run(
            caster.play(
                "https://example.com/test.wav",
                content_type="audio/wav",
            )
        )


def test_chromecast_stop_skips_invalid_command_without_media_session():
    caster = casting.ChromecastCaster()
    chromecast = _Chromecast()
    stop_calls = []
    chromecast.media_controller.stop = lambda: stop_calls.append(True)
    caster._cast = chromecast

    asyncio.run(caster.stop())

    assert stop_calls == []


def test_chromecast_stop_sends_command_for_active_media_session():
    caster = casting.ChromecastCaster()
    chromecast = _Chromecast()
    stop_calls = []
    chromecast.media_controller.status.media_session_id = 7
    chromecast.media_controller.stop = lambda: stop_calls.append(True)
    caster._cast = chromecast

    asyncio.run(caster.stop())

    assert stop_calls == [True]


def test_casting_manager_matches_active_device_and_live_connection():
    manager = object.__new__(casting.CastingManager)
    device = _device()
    manager.active_device = device
    manager.active_caster = SimpleNamespace(is_connected=lambda: True)

    assert manager.is_connected_to(device) is True
    assert manager.is_connected_to(_device(identifier="11111111-1111-1111-1111-111111111111")) is False

    manager.active_caster = SimpleNamespace(is_connected=lambda: False)
    assert manager.is_connected_to(device) is False


# ---------------------------------------------------------------------------
# MIME detection, CastDevice metadata, and connect orchestration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://host/playlist.m3u8", "application/x-mpegURL"),
        ("http://host/segment.ts", "video/mp2t"),
        ("http://host/movie.MP4?token=1", "video/mp4"),  # uppercase + query string
        ("http://host/clip.mkv", "video/x-matroska"),
        ("http://host/episode.mp3", "audio/mpeg"),
        ("http://host/audio.m4a", "audio/aac"),
        ("http://host/audio.opus", "audio/opus"),
        ("http://host/audio.flac", "audio/flac"),
        ("http://host/audio.wave", "audio/wav"),
    ],
)
def test_detect_mime_type_resolves_known_extensions(url, expected):
    # Extension matches return before the best-effort HEAD probe, so no network.
    assert casting._detect_mime_type(url) == expected


def test_detect_mime_type_uses_radio_heuristic_for_extensionless_streams():
    # A non-http scheme skips the HEAD probe; the radio/live heuristic applies.
    assert casting._detect_mime_type("rtsp://host/listen/main") == "audio/mpeg"
    assert casting._detect_mime_type("rtsp://host/live") == "audio/mpeg"


def test_detect_mime_type_falls_back_to_default():
    assert casting._detect_mime_type("rtsp://host/opaque") == "video/mp2t"
    assert (
        casting._detect_mime_type("rtsp://host/opaque", default="audio/mpeg")
        == "audio/mpeg"
    )


def test_cast_device_display_name_and_unique_id():
    device = _device()
    assert device.display_name == "R & B Room [Chromecast]"
    assert device.unique_id == "Chromecast:94b4d1b1-08bb-5fee-ca1c-491e0f225607"


class _RecordingCaster:
    def __init__(self):
        self.connect_calls = []
        self.disconnect_calls = 0

    async def connect(self, device):
        self.connect_calls.append(device)

    async def disconnect(self):
        self.disconnect_calls += 1


def _bare_manager(casters):
    manager = object.__new__(casting.CastingManager)
    manager.casters = dict(casters)
    manager.active_caster = None
    manager.active_device = None
    return manager


def test_connect_disconnects_previous_active_session():
    previous = _RecordingCaster()
    target = _RecordingCaster()
    manager = _bare_manager({casting.CastProtocol.CHROMECAST: target})
    manager.active_caster = previous
    manager.active_device = _device()

    asyncio.run(manager._connect_async(_device()))

    assert previous.disconnect_calls == 1
    assert target.connect_calls == [_device()]
    assert manager.active_caster is target
    assert manager.active_device == _device()


def test_connect_falls_back_to_dlna_caster_for_upnp_devices():
    dlna = _RecordingCaster()
    manager = _bare_manager({casting.CastProtocol.DLNA: dlna})
    device = casting.CastDevice(
        name="Living Room",
        protocol=casting.CastProtocol.UPNP,
        identifier="upnp-1",
        host="192.168.1.40",
        port=8200,
    )

    asyncio.run(manager._connect_async(device))

    assert dlna.connect_calls == [device]
    assert manager.active_caster is dlna


def test_connect_raises_when_no_caster_for_protocol():
    manager = _bare_manager({})
    with pytest.raises(casting.CastError):
        asyncio.run(manager._connect_async(_device()))


# ============================================================================
# AirPlay / AirPlay 2 (RAOP)
# ============================================================================

from pyatv.const import DeviceState, FeatureName, FeatureState  # noqa: E402
from pyatv import conf as _pyatv_conf  # noqa: E402


class _FakeStream:
    def __init__(self, play_url_error=None):
        self.play_url_calls = []
        self.stream_file_calls = []
        self.play_url_error = play_url_error

    async def play_url(self, url, **kwargs):
        self.play_url_calls.append((url, kwargs))
        if self.play_url_error is not None:
            raise self.play_url_error

    async def stream_file(self, file, **kwargs):
        self.stream_file_calls.append((file, kwargs))
        # Emulate a long-running stream that stays active until cancelled.
        await asyncio.Event().wait()


class _FakeRemote:
    def __init__(self):
        self.set_position_calls = []
        self.stop_calls = 0

    async def set_position(self, pos):
        self.set_position_calls.append(pos)

    async def stop(self):
        self.stop_calls += 1

    async def pause(self):
        pass

    async def play(self):
        pass


class _FakeMetadata:
    def __init__(self, position=None, device_state=None):
        self._playing = SimpleNamespace(position=position, device_state=device_state)

    async def playing(self):
        return self._playing


class _FakeFeatures:
    def __init__(self, states):
        self._states = states

    def get_feature(self, name):
        return SimpleNamespace(state=self._states.get(name, FeatureState.Unknown))


class _FakeATV:
    def __init__(self, features_states=None, position=None, device_state=None,
                 play_url_error=None):
        self.stream = _FakeStream(play_url_error=play_url_error)
        self.remote_control = _FakeRemote()
        self.metadata = _FakeMetadata(position=position, device_state=device_state)
        self.audio = SimpleNamespace(set_volume=self._set_volume)
        self.features = _FakeFeatures(features_states or {})
        self.listener = None
        self.close_calls = 0
        self.pending = []
        self.volume_calls = []

    async def _set_volume(self, level, **kwargs):
        self.volume_calls.append(level)

    def close(self):
        self.close_calls += 1
        return set(self.pending)


def _airplay_caster(atv, **flags):
    caster = casting.AirPlayCaster()
    caster._atv = atv
    caster._supports_airplay_video = flags.get("video", True)
    caster._supports_raop = flags.get("raop", False)
    caster._device_host = flags.get("host")
    return caster


async def _play_then_cleanup(caster, *args, **kwargs):
    await caster.play(*args, **kwargs)
    # Let a scheduled RAOP task start and record its call before teardown.
    await asyncio.sleep(0.05)
    await caster._cancel_raop_task()


def test_airplay_seek_calls_set_position():
    atv = _FakeATV()
    caster = _airplay_caster(atv)
    asyncio.run(caster.seek(42.9))
    assert atv.remote_control.set_position_calls == [42]


def test_airplay_status_reports_position_and_state_without_session_detection():
    atv = _FakeATV(position=88, device_state=DeviceState.Playing)
    caster = _airplay_caster(atv)
    status = asyncio.run(caster.get_status())
    assert status["position_seconds"] == 88.0
    assert status["player_state"] == "Playing"
    assert status["connected"] is True
    # AirPlay has no media-session id, so recovery machinery must stay off.
    assert status["supports_session_detection"] is False


def test_airplay_play_uses_play_url_for_video_receiver():
    atv = _FakeATV({
        FeatureName.PlayUrl: FeatureState.Available,
        FeatureName.StreamFile: FeatureState.Unavailable,
    })
    caster = _airplay_caster(atv, video=True, raop=False)
    asyncio.run(caster.play("https://cdn.example.com/video.mp4", "Clip",
                            content_type="video/mp4", start_time_seconds=12))
    assert len(atv.stream.play_url_calls) == 1
    url, kwargs = atv.stream.play_url_calls[0]
    assert url == "https://cdn.example.com/video.mp4"
    assert kwargs.get("position") == 12
    assert atv.stream.stream_file_calls == []
    assert caster._uses_raop is False


def test_airplay_play_uses_raop_for_audio_only_speaker():
    atv = _FakeATV({
        FeatureName.PlayUrl: FeatureState.Unsupported,
        FeatureName.StreamFile: FeatureState.Available,
    })
    caster = _airplay_caster(atv, video=False, raop=True)
    asyncio.run(_play_then_cleanup(caster, "https://cdn.example.com/podcast.mp3",
                                   content_type="audio/mpeg"))
    assert atv.stream.play_url_calls == []
    assert len(atv.stream.stream_file_calls) == 1
    assert atv.stream.stream_file_calls[0][0] == "https://cdn.example.com/podcast.mp3"
    assert caster._uses_raop is True


def test_airplay_play_url_notsupported_falls_back_to_raop():
    class NotSupportedError(Exception):
        pass

    atv = _FakeATV(
        {
            FeatureName.PlayUrl: FeatureState.Available,
            FeatureName.StreamFile: FeatureState.Available,
        },
        play_url_error=NotSupportedError("no video"),
    )
    caster = _airplay_caster(atv, video=True, raop=True)
    asyncio.run(_play_then_cleanup(caster, "https://x/podcast.mp3",
                                   content_type="audio/mpeg"))
    assert len(atv.stream.play_url_calls) == 1
    assert len(atv.stream.stream_file_calls) == 1
    assert caster._uses_raop is True


def test_airplay_prepare_url_routing(monkeypatch):
    monkeypatch.setattr(casting, "get_proxy", lambda: _FakeProxy())
    caster = casting.AirPlayCaster()
    caster._device_host = "192.168.1.50"
    loop_url = "http://127.0.0.1:9000/podcast.mp3"

    # play_url: receiver fetches, so loopback must be proxied on a reachable IP.
    out = caster._prepare_url(loop_url, "audio/mpeg", None, for_local=False)
    assert out == f"proxied://192.168.1.50/{loop_url}"

    # RAOP: pyatv reads locally, so loopback is reachable as-is.
    assert caster._prepare_url(loop_url, "audio/mpeg", None, for_local=True) == loop_url

    # RAOP with headers: proxy through loopback to inject them.
    out_hdr = caster._prepare_url(loop_url, "audio/mpeg", {"X": "1"}, for_local=True)
    assert out_hdr == f"proxied://127.0.0.1/{loop_url}"


def test_airplay_connection_listener_marks_disconnected():
    atv = _FakeATV()
    caster = casting.AirPlayCaster()
    device = casting.CastDevice(
        name="ATV", protocol=casting.CastProtocol.AIRPLAY, identifier="atv-1",
        host="192.168.1.50", port=7000,
        metadata={"supports_airplay_video": True, "supports_raop": False},
    )
    caster._atv = atv
    caster._after_connect(device, SimpleNamespace(address="192.168.1.50"))
    assert caster.is_connected() is True

    # pyatv reports the link dropped.
    atv.listener.connection_lost(RuntimeError("boom"))
    assert caster.is_connected() is False
    assert asyncio.run(caster.get_status())["connected"] is False


def test_airplay_disconnect_awaits_close_pending_tasks():
    atv = _FakeATV()
    caster = _airplay_caster(atv)

    async def scenario():
        async def _pending():
            return None
        atv.pending = [asyncio.ensure_future(_pending())]
        await caster.disconnect()

    asyncio.run(scenario())
    assert atv.close_calls == 1
    assert caster._atv is None
    assert caster.is_connected() is False


def test_airplay_finish_pairing_returns_credentials():
    caster = casting.AirPlayCaster()

    class _Handler:
        def __init__(self):
            self.service = SimpleNamespace(credentials="CRED123")
            self.pin_calls = []
            self.closed = False

        def pin(self, code):
            self.pin_calls.append(code)

        async def finish(self):
            pass

        async def close(self):
            self.closed = True

    handler = _Handler()
    caster._pairing_handler = handler
    caster._pairing_protocol = _pyatv_conf.Protocol.AirPlay

    creds = asyncio.run(caster.finish_pairing("1234"))
    assert creds == {"AirPlay": "CRED123"}
    assert handler.pin_calls == ["1234"]
    assert handler.closed is True
    assert caster._pairing_handler is None


class _FakeProxy:
    def get_proxied_url(self, url, headers, device_ip=None):
        return f"proxied://{device_ip}/{url}"

    def get_file_url(self, path, device_ip=None):
        return f"file-proxied://{device_ip}{path}"


# ============================================================================
# Chromecast bounded-timeout + connection-listener robustness
# ============================================================================

class _RecordingMediaController:
    def __init__(self, media_session_id=1):
        self.status = SimpleNamespace(media_session_id=media_session_id)
        self.seek_calls = []
        self.pause_calls = []
        self.play_calls = []
        self.stop_calls = []
        self.block_calls = []

    def block_until_active(self, timeout=None):
        self.block_calls.append(timeout)

    def update_status(self, callback_function=None):
        if callback_function:
            callback_function(True, {})

    def seek(self, position, timeout=None):
        self.seek_calls.append((position, timeout))

    def pause(self, timeout=None):
        self.pause_calls.append(timeout)

    def play(self, timeout=None):
        self.play_calls.append(timeout)

    def stop(self, timeout=None):
        self.stop_calls.append(timeout)


class _RichCast:
    def __init__(self, connected=True, media_session_id=1):
        self.media_controller = _RecordingMediaController(media_session_id=media_session_id)
        self.registered_listeners = []
        self.socket_client = SimpleNamespace(
            is_connected=connected,
            register_connection_listener=self.registered_listeners.append,
        )
        self.status = SimpleNamespace(transport_id="t-1")
        self.volume_calls = []

    def set_volume(self, level, timeout=None):
        self.volume_calls.append((level, timeout))


def _chromecast_caster(cast):
    caster = casting.ChromecastCaster()
    caster._cast = cast
    return caster


_CC_T = casting.ChromecastCaster._CONTROL_TIMEOUT


def test_chromecast_seek_is_bounded():
    cast = _RichCast()
    caster = _chromecast_caster(cast)
    asyncio.run(caster.seek(42.0))
    # The fix: a bounded seek + a bounded block, never pychromecast's 10s default
    # or the old 10s block/poll loop.
    assert cast.media_controller.seek_calls == [(42.0, _CC_T)]
    assert cast.media_controller.block_calls == [_CC_T]


def test_chromecast_pause_resume_stop_are_bounded():
    cast = _RichCast()
    caster = _chromecast_caster(cast)
    asyncio.run(caster.pause())
    asyncio.run(caster.resume())
    asyncio.run(caster.stop())
    assert cast.media_controller.pause_calls == [_CC_T]
    assert cast.media_controller.play_calls == [_CC_T]
    assert cast.media_controller.stop_calls == [_CC_T]


def test_chromecast_set_volume_is_bounded():
    cast = _RichCast()
    caster = _chromecast_caster(cast)
    asyncio.run(caster.set_volume(0.5))
    assert cast.volume_calls == [(0.5, _CC_T)]


def test_chromecast_stop_skips_without_media_session():
    cast = _RichCast(media_session_id=None)
    caster = _chromecast_caster(cast)
    asyncio.run(caster.stop())
    assert cast.media_controller.stop_calls == []


def test_chromecast_connection_listener_marks_lost():
    cast = _RichCast(connected=True)
    caster = casting.ChromecastCaster()
    caster._conn_listener = casting._ChromecastConnListener(caster._on_conn_status)
    caster._cast = cast
    cast.socket_client.register_connection_listener(caster._conn_listener)
    assert cast.registered_listeners == [caster._conn_listener]
    assert caster.is_connected() is True

    # pychromecast reports the socket dropped.
    caster._conn_listener.new_connection_status(SimpleNamespace(status="LOST"))
    assert caster.is_connected() is False
    assert asyncio.run(caster.get_status())["connected"] is False

    # A fresh CONNECTED clears the flag.
    caster._conn_listener.new_connection_status(SimpleNamespace(status="CONNECTED"))
    assert caster.is_connected() is True


def test_chromecast_deliberate_disconnect_is_not_treated_as_lost():
    caster = casting.ChromecastCaster()
    caster._conn_listener = casting._ChromecastConnListener(caster._on_conn_status)
    caster._cast = _RichCast(connected=True)
    caster._conn_listener.new_connection_status(SimpleNamespace(status="DISCONNECTED"))
    # A deliberate DISCONNECTED must not be flagged as an unexpected loss.
    assert caster._connection_lost is False


class _AsyncTransportCaster:
    def __init__(self):
        self.calls = []

    async def resume(self):
        self.calls.append("resume")

    async def stop(self):
        self.calls.append("stop")


def test_manager_async_transport_dispatches():
    caster = _AsyncTransportCaster()
    manager = _bare_manager({})
    manager.active_caster = caster
    dispatched = []

    def fake_dispatch_async(coro, callback=None):
        # Drive the coroutine to completion synchronously for the test.
        try:
            asyncio.run(coro)
        finally:
            dispatched.append(callback)
        return object()

    manager.dispatch_async = fake_dispatch_async
    manager.resume_async()
    manager.stop_async()

    assert caster.calls == ["resume", "stop"]
    assert len(dispatched) == 2
