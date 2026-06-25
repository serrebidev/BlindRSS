import asyncio
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
