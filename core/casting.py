# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Casting: Chromecast, AirPlay, UPnP/DLNA, Sonos, Roku and Kodi.

The protocol clients and the streaming engine are Caster's, synced verbatim by
tools/sync_caster.py: caster_engine (media probing, the HLS relay that keeps
live streams smooth on a receiver, the replay-dropping TS reader, the asyncio
loop pyatv needs), caster_devices and caster_extras (discovery and each
protocol's control calls). This module is the part Caster keeps inside its wx
window - how a URL reaches each kind of receiver, and how it is paused,
resumed, sought and watched - without the window.

What BlindRSS adds on top of Caster:

* Resume positions. A podcast is cast from where it was playing locally.
* Transport control on every protocol the device allows: pause, resume, seek,
  position and a status poll the player uses to notice a dropped session.
* Local files and localhost URLs (downloads, the range cache) are served to
  the receiver through BlindRSS's token-protected stream proxy.

Blocking calls return once the receiver is playing or has failed (raising
CastError); the ``*_async`` variants run them on a worker thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
import uuid as uuidlib
from enum import Enum
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)

#: How long discovery listens; the protocols run in parallel.
DISCOVER_SECONDS = 5
AIRPLAY_START_TIMEOUT = 25.0
#: Live Cast recovery (Caster's measured values).
WATCHDOG_SECONDS = 5.0
CAST_STALL_TIMEOUT = 20.0
CAST_RECOVERY_INTERVAL = 30.0
CAST_APP_ID = "CC1AD845"
LOAD_TIMEOUT = 12.0
LOAD_POLL = 0.15
STALE_IDLE_REASONS = ("INTERRUPTED", "CANCELLED")
#: Caster's relay preset: 2 s segments, a 16 s start cushion, 45 s of history.
RELAY_PRESET = "balanced"
#: Bound on every receiver command, so a receiver that stops answering cannot
#: hold a caller for pychromecast's default ten seconds per call.
COMMAND_TIMEOUT = 3.0
_AVT = "urn:schemas-upnp-org:service:AVTransport:1"


class CastProtocol(Enum):
    """Receiver kinds, as shown after a device's name."""
    CHROMECAST = "Chromecast"
    DLNA = "DLNA"
    UPNP = "UPnP"
    AIRPLAY = "AirPlay"
    SONOS = "Sonos"
    ROKU = "Roku"
    KODI = "Kodi"


_KIND_TO_PROTOCOL = {
    "chromecast": CastProtocol.CHROMECAST,
    "airplay": CastProtocol.AIRPLAY,
    "upnp": CastProtocol.UPNP,
    "sonos": CastProtocol.SONOS,
    "roku": CastProtocol.ROKU,
    "kodi": CastProtocol.KODI,
}
_PROTOCOL_TO_KIND = {protocol: kind for kind, protocol in _KIND_TO_PROTOCOL.items()}
_PROTOCOL_TO_KIND[CastProtocol.DLNA] = "upnp"


class CastError(Exception):
    """Casting failed; the message says why."""


class DeviceNotFoundError(CastError):
    pass


class ConnectionError(CastError):  # noqa: A001 - kept for existing callers
    pass


class PlaybackError(CastError):
    pass


def _ffmpeg_path() -> str:
    """ffmpeg as BlindRSS finds it (user setting, bundled, PATH, winget)."""
    try:
        from core.dependency_check import _find_executable_path
        found = _find_executable_path("ffmpeg")
        if found:
            return found
    except Exception:
        LOG.debug("casting: ffmpeg lookup through dependency_check failed", exc_info=True)
    return shutil.which("ffmpeg") or "ffmpeg"


def _engine():
    """caster_engine, with ffmpeg resolved the way BlindRSS resolves it."""
    import caster_engine
    import caster_extras

    caster_engine._find_ffmpeg = _ffmpeg_path
    caster_extras._find_ffmpeg = _ffmpeg_path
    return caster_engine


def _redact(url: str) -> str:
    try:
        from core import utils
        return utils.redact_url_for_log(url)
    except Exception:
        return "<url>"


def _hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _parse_hms(text) -> Optional[float]:
    match = re.match(r"^\s*(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)\s*$", str(text or ""))
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class CastDevice:
    """One receiver found on the network."""

    def __init__(self, name: str, protocol: CastProtocol, identifier: str,
                 host: str = "", port: int = 0, metadata: Optional[Dict] = None,
                 device: Any = None) -> None:
        self.name = name
        self.protocol = protocol
        self.identifier = identifier
        self.host = host
        self.port = port
        self.metadata = dict(metadata or {})
        self.device = device            # caster_engine.Device; None when built by hand

    @classmethod
    def from_engine(cls, device) -> "CastDevice":
        key = device.key
        kind = device.kind
        if kind == "chromecast":
            identifier, port = str(key.get("uuid") or device.name), int(key.get("port") or 8009)
        elif kind == "airplay":
            identifier, port = str(getattr(key, "identifier", "") or device.name), 0
        elif kind == "upnp":
            identifier, port = str(key.get("control_url") or device.name), 0
        elif kind == "sonos":
            identifier, port = str(key.get("ip") or device.name), 1400
        else:
            identifier, port = str(key.get("base") or device.name), 0
        return cls(device.name, _KIND_TO_PROTOCOL.get(kind, CastProtocol.UPNP), identifier,
                   host=device.host, port=port, device=device)

    @property
    def kind(self) -> str:
        return _PROTOCOL_TO_KIND.get(self.protocol, "upnp")

    @property
    def display_name(self) -> str:
        return f"{self.name} [{self.protocol.value}]"

    @property
    def unique_id(self) -> str:
        return f"{self.protocol.value}:{self.identifier}"

    @property
    def supports_video(self) -> bool:
        return bool(self.device is not None and self.device.supports_video)

    def __repr__(self) -> str:
        return f"CastDevice({self.protocol.value}, {self.name!r})"


class _AirSession:
    """State of one RAOP stream, shared between its runner and the controls."""

    def __init__(self, generation: int) -> None:
        self.generation = generation
        self.loop_future = None
        self.shutdown: Optional[asyncio.Event] = None
        self.wake: Optional[asyncio.Event] = None
        self.atv = None
        self.proc = None
        self.state = "stopped"          # "playing" | "paused" | "stopped"
        self.pos = 0.0                  # position at the last play/seek/pause
        self.t0: Optional[float] = None # monotonic clock at (re)start
        self.pending_seek: Optional[float] = None
        self.live = False

    def position(self) -> float:
        pos = self.pos
        if self.state == "playing" and self.t0 is not None:
            pos += time.monotonic() - self.t0
        return pos


class CastingManager:
    """Discovers receivers and plays media on the one the user picked."""

    def __init__(self) -> None:
        self.active_device: Optional[CastDevice] = None
        self._loop_thread = None
        self._running = False
        self._lock = threading.RLock()
        # Every play and stop bumps this; work belonging to an older one backs
        # out instead of loading a stale stream.
        self._generation = 0
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._cast = None
        self._cast_zc = None
        self._relays: list = []
        self._live_load = None
        self._cast_progress = None
        self._cast_retry_at = 0.0
        self._recovering = False
        self._air: Optional[_AirSession] = None
        # (url, title, channel) of the last play, to start it again.
        self._last_play = None
        # Position by the clock, for receivers that cannot report one.
        self._clock_pos = 0.0
        self._clock_t0: Optional[float] = None
        self._clock_state: Optional[str] = None
        self._watchdog_stop = threading.Event()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._running:
            return
        engine = _engine()
        self._loop_thread = engine.LoopThread()
        self._loop_thread.start()
        self._loop_thread.ready.wait(5)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="cast-control")
        self._running = True
        self._watchdog_stop.clear()
        threading.Thread(target=self._watchdog_loop, daemon=True, name="cast-watchdog").start()

    def stop(self) -> None:
        """Stop casting and shut the manager down (app exit)."""
        if not self._running:
            return
        try:
            self.disconnect()
        except Exception:
            LOG.debug("CastingManager.stop: ignored exception", exc_info=True)
        self._running = False
        self._watchdog_stop.set()
        zc, self._cast_zc = self._cast_zc, None
        if zc is not None:
            try:
                zc.close()
            except Exception:
                LOG.debug("CastingManager.stop: ignored exception", exc_info=True)
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        loop_thread = self._loop_thread
        if loop_thread is not None:
            loop_thread.loop.call_soon_threadsafe(loop_thread.loop.stop)
            loop_thread.join(timeout=2)

    def _require_running(self) -> None:
        if not self._running:
            raise RuntimeError("CastingManager is not running. Call start() first.")

    def dispatch(self, coro):
        """Run a coroutine on the casting event loop and wait for its result."""
        self._require_running()
        return asyncio.run_coroutine_threadsafe(coro, self._loop_thread.loop).result()

    def _submit(self, func, *args, callback=None, **kwargs):
        """Run ``func`` on a worker thread; ``callback(result)`` when done.

        The callback gets None when ``func`` raised, as the player expects.
        """
        self._require_running()
        future = self._executor.submit(func, *args, **kwargs)
        if callback is not None:
            def completed(done):
                try:
                    result = done.result()
                except Exception:
                    LOG.info("Casting: background call failed", exc_info=True)
                    result = None
                try:
                    callback(result)
                except Exception:
                    LOG.exception("Casting async callback failed")
            future.add_done_callback(completed)
        return future

    # ------------------------------------------------------------------ #
    # Discovery (Caster's six parallel scans and merge rules)
    # ------------------------------------------------------------------ #
    def discover_all(self, timeout: float = DISCOVER_SECONDS) -> List[CastDevice]:
        self._require_running()
        _engine()
        timeout = max(1, int(round(timeout)))
        try:
            import zeroconf
            zc = zeroconf.Zeroconf()
        except Exception:
            LOG.info("Casting: mDNS unavailable; Chromecast and Kodi will not be found",
                     exc_info=True)
            zc = None
        scans = [
            ("chromecast", lambda: self._scan_chromecast(zc, timeout)),
            ("airplay", lambda: self._scan_airplay(timeout)),
            ("upnp", lambda: self._scan_upnp(timeout)),
            ("sonos", lambda: self._scan_sonos(timeout)),
            ("roku", lambda: self._scan_roku(timeout)),
            ("kodi", lambda: self._scan_kodi(zc, timeout)),
        ]

        def run(scan):
            try:
                return scan() or {}
            except Exception:
                LOG.info("Casting: a discovery scan failed", exc_info=True)
                return {}

        results: Dict[str, dict] = {}
        try:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(scans), thread_name_prefix="cast-discover") as pool:
                futures = {pool.submit(run, scan): key for key, scan in scans}
                for future in concurrent.futures.as_completed(futures):
                    results[futures[future]] = future.result()
        finally:
            if zc is not None:
                try:
                    zc.close()
                except Exception:
                    LOG.debug("CastingManager.discover_all: ignored exception", exc_info=True)

        # A fixed merge order; a box answering twice keeps the entry that can
        # show a picture when its renderer says so; Sonos last and wins.
        found: Dict[str, Any] = {}
        for key in ("chromecast", "airplay", "upnp", "roku", "kodi"):
            for name, device in results.get(key, {}).items():
                seen = found.get(name)
                if seen is None:
                    found[name] = device
                elif device.sinks and device.supports_video and not seen.supports_video:
                    found[name] = device
        found.update(results.get("sonos", {}))
        return sorted((CastDevice.from_engine(d) for d in found.values()),
                      key=lambda d: d.display_name.lower())

    def _scan_chromecast(self, zc, timeout: int) -> dict:
        """Browse _googlecast._tcp directly; pychromecast's browser misses TVs."""
        if zc is None:
            return {}
        import zeroconf
        from caster_engine import Device
        from caster_extras import mdns_host

        found: Dict[str, Any] = {}
        seen: set = set()
        lock = threading.Lock()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=8,
                                                     thread_name_prefix="cast-resolve")

        def resolve(type_: str, name: str) -> None:
            try:
                info = zc.get_service_info(type_, name, 3000)
            except Exception:
                return
            if not info or not info.addresses:
                return
            props = {}
            for k, v in info.properties.items():
                kd = k.decode() if isinstance(k, bytes) else k
                props[kd] = v.decode(errors="replace") if isinstance(v, bytes) else (v or "")
            host = mdns_host(info)
            if not host:
                return
            fn = props.get("fn") or name.split(".")[0]
            device = Device("chromecast", fn, {
                "host": host,
                "port": info.port or 8009,
                "uuid": props.get("id") or uuidlib.uuid4().hex,
                "model": props.get("md") or "Chromecast",
            })
            with lock:
                found[fn if fn not in found else f"{fn} ({host})"] = device

        class _Listener:
            def add_service(self, zc_, type_, name):
                with lock:
                    if name in seen:
                        return
                    seen.add(name)
                pool.submit(resolve, type_, name)

            def update_service(self, zc_, type_, name):
                pass

            def remove_service(self, zc_, type_, name):
                pass

        browser = None
        try:
            browser = zeroconf.ServiceBrowser(zc, "_googlecast._tcp.local.", _Listener())
            time.sleep(timeout)
        finally:
            if browser is not None:
                try:
                    browser.cancel()
                except Exception:
                    LOG.debug("CastingManager._scan_chromecast: ignored exception", exc_info=True)
            pool.shutdown(wait=True)
        return found

    def _scan_airplay(self, timeout: int) -> dict:
        try:
            import pyatv
            from pyatv.const import PairingRequirement, Protocol
        except ImportError:
            LOG.info("Casting: pyatv is not installed; AirPlay devices will not be found")
            return {}
        from caster_devices import looks_like_sonos
        from caster_engine import Device

        loop = self._loop_thread.loop
        future = asyncio.run_coroutine_threadsafe(
            pyatv.scan(loop, timeout=timeout, protocol={Protocol.RAOP, Protocol.AirPlay}), loop)
        found: Dict[str, Any] = {}
        for cfg in future.result(timeout + 15):
            if not cfg.name:
                continue
            # AirPlay here is RAOP audio with no pairing flow: a device with no
            # RAOP service, or one wanting pairing for it, can only fail.
            raop = next((s for s in cfg.services if s.protocol == Protocol.RAOP), None)
            if raop is None or raop.pairing != PairingRequirement.NotNeeded:
                continue
            if looks_like_sonos(cfg.name, str(getattr(cfg, "device_info", ""))):
                continue
            found.setdefault(cfg.name, Device("airplay", cfg.name, cfg))
        return found

    @staticmethod
    def _scan_upnp(timeout: int) -> dict:
        from caster_devices import looks_like_sonos
        from caster_engine import Device
        from caster_extras import upnp_discover

        found: Dict[str, Any] = {}
        for name, url, maker, sinks in upnp_discover(timeout=timeout):
            if looks_like_sonos(name, maker):
                continue
            found.setdefault(name, Device("upnp", name,
                                          {"control_url": url.replace("&amp;", "&")},
                                          sinks=sinks))
        return found

    @staticmethod
    def _scan_sonos(timeout: int) -> dict:
        from caster_devices import sonos_discover
        from caster_engine import Device
        return {name: Device("sonos", name, {"ip": ip})
                for name, ip in sonos_discover(timeout=timeout, seed_ips=[])}

    @staticmethod
    def _scan_roku(timeout: int) -> dict:
        from caster_devices import roku_discover
        from caster_engine import Device
        return {name: Device("roku", name, {"base": base})
                for name, base in roku_discover(timeout=timeout)}

    @staticmethod
    def _scan_kodi(zc, timeout: int) -> dict:
        from caster_devices import kodi_discover
        from caster_engine import Device
        return {name: Device("kodi", name, {"base": base})
                for name, base in kodi_discover(timeout=timeout, zc=zc)}

    # ------------------------------------------------------------------ #
    # Session
    # ------------------------------------------------------------------ #
    def connect(self, device: CastDevice, credentials: Optional[object] = None) -> None:
        """Choose the receiver; a Chromecast is connected here and reused."""
        del credentials                 # AirPlay here needs no pairing
        self._require_running()
        if device.device is None:
            raise ConnectionError(f"{device.name} was not found by discovery.")
        if self.active_device is not None and self.active_device.unique_id != device.unique_id:
            self.disconnect()
        self.active_device = device
        if device.kind == "chromecast":
            try:
                self._chromecast()
            except Exception:
                self.active_device = None
                raise

    def start_pairing(self, device: CastDevice, protocol: Optional[object] = None) -> object:
        raise CastError("AirPlay receivers that need pairing are not supported.")

    def finish_pairing(self, device: CastDevice, pin: Optional[object]) -> Optional[Dict[str, str]]:
        return None

    def is_connected(self) -> bool:
        return self.active_device is not None

    def is_connected_to(self, device: CastDevice) -> bool:
        active = self.active_device
        return active is not None and active.unique_id == device.unique_id

    def disconnect(self) -> None:
        self.stop_playback()
        cast, self._cast = self._cast, None
        if cast is not None:
            self._release_cast(cast, stop_media=False)
        self.active_device = None

    def disconnect_async(self, callback=None):
        try:
            return self._submit(self.disconnect, callback=callback)
        except Exception:
            return None

    def play(self, url: str, title: str = "", channel: Optional[Dict[str, str]] = None,
             content_type: Optional[str] = None,
             start_time_seconds: Optional[float] = None) -> None:
        """Play ``url`` on the chosen receiver, from ``start_time_seconds``.

        ``content_type`` is ignored: the stream is probed, because what a URL
        claims to be and what it is differ too often (Caster's rule).
        """
        del content_type
        self._require_running()
        device = self.active_device
        if device is None:
            raise ConnectionError("No active cast device")
        headers = {}
        if channel:
            try:
                from core.http_headers import channel_http_headers
                headers = channel_http_headers(channel) or {}
            except Exception:
                headers = {}
        start = 0.0
        try:
            start = max(0.0, float(start_time_seconds or 0.0))
        except (TypeError, ValueError):
            start = 0.0
        source = self._source_url(url, headers, device)
        self.stop_playback()
        self._last_play = (url, title, channel)
        with self._lock:
            generation = self._generation
        title = title or "BlindRSS"
        LOG.info("Casting %s to %s from %.0fs", _redact(url), device.display_name, start)
        kind = device.kind
        if kind == "chromecast":
            self._play_chromecast(device, source, title, generation, start)
        elif kind == "airplay":
            self._play_airplay(device, source, generation, start)
        elif kind == "upnp":
            self._play_upnp(device, source, title, generation, start)
        elif kind == "sonos":
            self._play_sonos(device, source, title, start)
        elif kind == "roku":
            self._play_roku(device, source, title, generation)
        elif kind == "kodi":
            self._play_kodi(device, source, start)
        else:
            raise CastError(f"{device.display_name} cannot be cast to.")
        self._clock_set("playing", start)

    def play_async(self, url: str, title: str = "", channel: Optional[Dict[str, str]] = None,
                   content_type: Optional[str] = None,
                   start_time_seconds: Optional[float] = None, callback=None):
        return self._submit(self.play, url, title, channel, content_type, start_time_seconds,
                            callback=callback)

    def stop_playback(self) -> None:
        """Stop what is playing on the receiver; keep it selected."""
        with self._lock:
            self._generation += 1
            relays, self._relays = list(self._relays), []
            self._live_load = None
            self._cast_progress = None
            air, self._air = self._air, None
        self._clock_state = None
        for relay in relays:
            try:
                relay.stop()
            except Exception:
                LOG.debug("CastingManager.stop_playback: relay", exc_info=True)
        if air is not None:
            self._end_air(air)
        device = self.active_device
        if device is None or device.device is None:
            return
        try:
            key = device.device.key
            if device.kind == "chromecast" and self._cast is not None:
                mc = self._cast.media_controller
                if getattr(mc.status, "media_session_id", None) is not None:
                    self._bounded(mc.stop)
            elif device.kind == "upnp":
                from caster_extras import upnp_stop
                upnp_stop(key["control_url"])
            elif device.kind == "sonos":
                from caster_devices import sonos_stop
                sonos_stop(key["ip"])
            elif device.kind == "roku":
                from caster_devices import roku_stop
                roku_stop(key["base"])
            elif device.kind == "kodi":
                from caster_devices import kodi_stop
                kodi_stop(key["base"])
        except Exception:
            LOG.debug("CastingManager.stop_playback: receiver stop", exc_info=True)

    def stop_async(self, callback=None):
        try:
            return self._submit(self.stop_playback, callback=callback)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Transport controls
    # ------------------------------------------------------------------ #
    def pause(self) -> None:
        device = self.active_device
        if device is None:
            return
        kind = device.kind
        if kind == "chromecast" and self._cast is not None:
            self._bounded(self._cast.media_controller.pause)
        elif kind == "airplay":
            self._air_pause()
        elif kind == "upnp":
            self._upnp_action(device, "Pause", "")
        elif kind == "sonos":
            self._sonos_zone(device).pause()
        elif kind == "kodi":
            self._kodi_play_pause(device, False)
        elif kind == "roku" and self._clock_state == "playing":
            from caster_devices import roku_key
            roku_key(device.device.key["base"], "Play")
        self._clock_set("paused")

    def resume(self) -> None:
        device = self.active_device
        if device is None:
            return
        kind = device.kind
        if kind == "chromecast" and self._cast is not None:
            self._bounded(self._cast.media_controller.play)
        elif kind == "airplay":
            self._air_resume()
        elif kind == "upnp":
            self._upnp_action(device, "Play", "<Speed>1</Speed>")
        elif kind == "sonos":
            self._sonos_zone(device).play()
        elif kind == "kodi":
            self._kodi_play_pause(device, True)
        elif kind == "roku" and self._clock_state == "paused":
            from caster_devices import roku_key
            roku_key(device.device.key["base"], "Play")
        self._clock_set("playing")

    def pause_async(self, callback=None):
        try:
            return self._submit(self.pause, callback=callback)
        except Exception:
            return None

    def resume_async(self, callback=None):
        try:
            return self._submit(self.resume, callback=callback)
        except Exception:
            return None

    def _seek(self, position_seconds: float) -> None:
        device = self.active_device
        if device is None:
            return
        target = max(0.0, float(position_seconds))
        kind = device.kind
        if kind == "chromecast" and self._cast is not None:
            self._bounded(self._cast.media_controller.seek, target)
        elif kind == "airplay":
            self._air_seek(target)
        elif kind == "upnp":
            self._upnp_seek(device, target)
        elif kind == "sonos":
            self._sonos_zone(device).seek(_hms(target))
        elif kind == "kodi":
            self._kodi_seek(device, target)
        else:
            return                      # Roku: no seek over ECP
        self._clock_set(self._clock_state or "playing", target)

    def seek(self, position_seconds: float) -> None:
        """Seek without blocking the caller."""
        try:
            self._submit(self._seek, position_seconds, callback=lambda _r: None)
        except Exception:
            LOG.debug("CastingManager.seek: ignored exception", exc_info=True)

    def set_volume(self, level: float) -> None:
        device = self.active_device
        if device is None:
            return
        level = max(0.0, min(1.0, float(level)))
        percent = int(round(level * 100))
        kind = device.kind
        key = device.device.key
        if kind == "chromecast" and self._cast is not None:
            self._cast.set_volume(level)
        elif kind == "airplay":
            air = self._air
            if air is not None and air.atv is not None:
                engine = _engine()
                asyncio.run_coroutine_threadsafe(
                    engine._set_atv_volume(air.atv, float(percent)), self._loop_thread.loop)
        elif kind == "upnp":
            from caster_extras import upnp_set_volume
            upnp_set_volume(key["control_url"], percent)
        elif kind == "sonos":
            from caster_devices import sonos_set_volume
            sonos_set_volume(key["ip"], percent)
        elif kind == "kodi":
            from caster_devices import kodi_set_volume
            kodi_set_volume(key["base"], percent)

    def set_volume_async(self, level: float, callback=None):
        try:
            return self._submit(self.set_volume, level, callback=callback)
        except Exception:
            return None

    def get_status(self) -> Dict:
        """A protocol-neutral snapshot; Chromecast also reports its session."""
        device = self.active_device
        if device is None:
            return {"position_seconds": None, "player_state": None, "connected": False,
                    "supports_session_detection": False}
        kind = device.kind
        if kind == "chromecast":
            return self._chromecast_status()
        position = None
        state = None
        try:
            if kind == "airplay":
                air = self._air
                if air is not None:
                    position = air.position()
                    state = {"playing": "PLAYING", "paused": "PAUSED"}.get(air.state, "IDLE")
            elif kind == "upnp":
                position, state = self._upnp_status(device)
            elif kind == "sonos":
                zone = self._sonos_zone(device)
                position = _parse_hms(zone.get_current_track_info().get("position"))
                raw = zone.get_current_transport_info().get("current_transport_state", "")
                state = {"PAUSED_PLAYBACK": "PAUSED", "TRANSITIONING": "BUFFERING"}.get(raw, raw)
            elif kind == "kodi":
                position, state = self._kodi_status(device)
        except Exception:
            LOG.debug("CastingManager.get_status: %s status failed", kind, exc_info=True)
        if position is None:
            position = self._clock_position()
        if state is None and self._clock_state:
            state = self._clock_state.upper()
        return {"position_seconds": position, "player_state": state, "connected": True,
                "supports_session_detection": False}

    def get_status_async(self, callback):
        try:
            return self._submit(self.get_status, callback=callback)
        except Exception:
            callback(None)
            return None

    def get_position(self) -> Optional[float]:
        try:
            return self.get_status().get("position_seconds")
        except Exception:
            return None

    def get_position_async(self, callback):
        try:
            return self._submit(self.get_position, callback=callback)
        except Exception:
            callback(None)
            return None

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #
    def _clock_set(self, state: str, position: Optional[float] = None) -> None:
        current = self._clock_position()
        self._clock_pos = current if position is None else float(position)
        self._clock_state = state
        self._clock_t0 = time.monotonic() if state == "playing" else None

    def _clock_position(self) -> Optional[float]:
        if self._clock_state is None:
            return None
        pos = self._clock_pos
        if self._clock_state == "playing" and self._clock_t0 is not None:
            pos += time.monotonic() - self._clock_t0
        return pos

    @staticmethod
    def _bounded(func, *args):
        """A pychromecast control with a bounded wait (never its 10 s default)."""
        try:
            return func(*args, timeout=COMMAND_TIMEOUT)
        except TypeError:
            return func(*args)

    @staticmethod
    def _local_path(url: str) -> Optional[str]:
        try:
            parsed = urllib.parse.urlparse(url or "")
        except ValueError:
            return None
        if parsed.scheme == "file":
            path = urllib.parse.unquote(parsed.path or "")
            if path.startswith("/") and len(path) >= 3 and path[2] == ":":
                path = path[1:]     # /C:/... on Windows
            return path
        # urlparse reads a Windows drive letter as a scheme; check the path.
        if url and os.path.isfile(url):
            return url
        return None

    def _source_url(self, url: str, headers: Dict[str, object], device: CastDevice) -> str:
        """The URL the engine and the receiver fetch.

        Local files, localhost addresses and header-protected streams are not
        reachable by a receiver as they are, so BlindRSS's stream proxy serves
        them on an address the receiver can reach. Everything else goes to the
        source directly.
        """
        path = self._local_path(url)
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
        except ValueError:
            host = ""
        needs_proxy = bool(path) or host in ("127.0.0.1", "localhost", "::1") or bool(headers)
        if not needs_proxy:
            return url
        from core.stream_proxy import get_proxy
        proxy = get_proxy()
        device_ip = device.device.host if device.device is not None else None
        if path:
            return proxy.get_file_url(path, device_ip=device_ip)
        return proxy.get_proxied_url(url, dict(headers or {}), device_ip=device_ip)

    def _abandoned(self, generation: int) -> bool:
        return not self._running or generation != self._generation

    def _keep_relay(self, relay, generation: int) -> None:
        with self._lock:
            stale = generation != self._generation
            if not stale:
                self._relays.append(relay)
        if stale:
            relay.stop()
            raise PlaybackError("Casting was stopped.")

    def _drop_relay(self, relay) -> None:
        if relay is None:
            return
        with self._lock:
            if relay in self._relays:
                self._relays.remove(relay)
        try:
            relay.stop()
        except Exception:
            LOG.debug("CastingManager._drop_relay: ignored exception", exc_info=True)

    def _start_relay(self, url: str, generation: int, codecs=None,
                     live: Optional[bool] = None) -> tuple:
        engine = _engine()
        from caster_config import preset
        chosen = preset(RELAY_PRESET)
        if codecs is None:
            codecs = engine._probe_codecs(url)
        relay = engine.HlsRelay(url, hls_time=chosen["hls_time"],
                                prime_segments=chosen["hls_prime"],
                                trail_keep=chosen["hls_trail"],
                                trail_seconds=chosen["hls_trail_seconds"],
                                startup_seconds=chosen["hls_start_seconds"],
                                codecs=codecs, live=live)
        self._keep_relay(relay, generation)
        try:
            return relay, relay.start()
        except Exception:
            self._drop_relay(relay)
            raise

    # ------------------------------------------------------------------ #
    # Chromecast
    # ------------------------------------------------------------------ #
    def _cast_zeroconf(self):
        if self._cast_zc is None:
            import zeroconf
            self._cast_zc = zeroconf.Zeroconf()
        return self._cast_zc

    def _chromecast(self):
        """The connected Chromecast for the active device, (re)connecting it."""
        cast = self._cast
        if cast is not None:
            try:
                if cast.socket_client.is_connected:
                    return cast
            except Exception:
                LOG.debug("CastingManager._chromecast: connection check", exc_info=True)
            self._release_cast(cast, stop_media=False)
            self._cast = None
        try:
            import pychromecast
            from pychromecast.const import CAST_TYPE_CHROMECAST
            from pychromecast.models import CastInfo, HostServiceInfo
        except ImportError as err:
            raise CastError("Chromecast support is not installed (pychromecast).") from err
        device = self.active_device
        key = device.device.key
        host, port = key["host"], key.get("port", 8009)
        info = CastInfo(
            uuid=uuidlib.UUID(key["uuid"]), host=host, port=port,
            cast_type=CAST_TYPE_CHROMECAST, manufacturer="",
            model_name=key.get("model") or "Chromecast", friendly_name=device.name,
            # Mandatory: with no HostServiceInfo the socket client never connects.
            services={HostServiceInfo(host, port)},
        )
        cast = pychromecast.Chromecast(info, zconf=self._cast_zeroconf(), tries=3, timeout=15)
        cast.wait(20)
        if not cast.socket_client.is_connected:
            self._release_cast(cast, stop_media=False)
            raise ConnectionError(f"Could not connect to {device.name}.")
        self._cast = cast
        return cast

    @staticmethod
    def _ensure_receiver(cast, timeout: float = 8.0) -> None:
        """Launch the media receiver only when another app holds the screen."""
        try:
            app_id = cast.app_id
            if app_id is None:
                deadline = time.monotonic() + 1.5
                while app_id is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                    app_id = cast.app_id
            if app_id == CAST_APP_ID:
                return
            cast.start_app(CAST_APP_ID, force_launch=app_id is not None)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cast.app_id == CAST_APP_ID:
                    time.sleep(0.25)
                    return
                time.sleep(0.05)
        except Exception:
            LOG.debug("CastingManager._ensure_receiver: play_media reports the failure",
                      exc_info=True)

    @staticmethod
    def _await_playing(mc, previous_session=None) -> bool:
        """True once the receiver plays; False if it rejected the load."""
        deadline = time.monotonic() + LOAD_TIMEOUT
        while time.monotonic() < deadline:
            status = mc.status
            if status is not None:
                session = getattr(status, "media_session_id", None)
                stale = previous_session is not None and session == previous_session
                if not stale:
                    if status.player_state in ("PLAYING", "PAUSED"):
                        return True
                    if (status.player_state == "IDLE" and status.idle_reason
                            and status.idle_reason not in STALE_IDLE_REASONS):
                        return False
            time.sleep(LOAD_POLL)
        return False

    def _load(self, mc, url: str, mime: str, stream_type: str, title: str,
              start: float = 0.0) -> bool:
        before = getattr(mc.status, "media_session_id", None)
        options: Dict[str, Any] = {}
        with self._lock:
            relays = list(self._relays)
        if any(getattr(r, "play_url", None) == url and r.live for r in relays):
            options["current_time"] = 0     # a live relay's buffered start
        elif start > 0 and stream_type == "BUFFERED":
            options["current_time"] = start
        mc.play_media(url, mime, title=title, stream_type=stream_type, **options)
        return self._await_playing(mc, before)

    @staticmethod
    def _release_cast(cast, stop_media: bool = True) -> None:
        """Close a Chromecast connection off the caller's thread."""
        def release() -> None:
            if stop_media:
                try:
                    mc = cast.media_controller
                    if getattr(mc.status, "media_session_id", None) is not None:
                        mc.stop(timeout=COMMAND_TIMEOUT)
                except Exception:
                    LOG.debug("CastingManager._release_cast: stop", exc_info=True)
            try:
                cast.disconnect(timeout=COMMAND_TIMEOUT)
            except Exception:
                LOG.debug("CastingManager._release_cast: disconnect", exc_info=True)
        threading.Thread(target=release, daemon=True, name="cast-release").start()

    def _play_chromecast(self, device: CastDevice, url: str, title: str,
                         generation: int, start: float) -> None:
        engine = _engine()
        cast = self._chromecast()
        mc = cast.media_controller
        relay = None
        try:
            warm = threading.Thread(target=self._ensure_receiver, args=(cast,),
                                    daemon=True, name="cast-warm")
            warm.start()
            is_playlist = url.lower().split("?")[0].endswith(".m3u8")
            probe = engine.probe_media(url)
            load_mime = probe["mime"]
            native_url = (engine._native_hls_url(url)
                          if probe["mime"] == "video/mp2t" and probe["is_live"] else None)
            if native_url:
                play_url, load_mime = native_url, "application/vnd.apple.mpegurl"
            elif probe["mime"] == "video/mp2t" and not is_playlist:
                # Cast receivers reject raw MPEG-TS: remux through Caster's relay.
                relay, play_url = self._start_relay(url, generation, live=bool(probe["is_live"]))
                load_mime = "application/vnd.apple.mpegurl"
            else:
                play_url = url
            stream_type = "LIVE" if probe["is_live"] else "BUFFERED"
            warm.join(timeout=10)
            self._ensure_receiver(cast)
            if self._abandoned(generation):
                raise PlaybackError("Casting was stopped.")

            settled = self._load(mc, play_url, load_mime, stream_type, title, start)
            if not settled and native_url and not self._abandoned(generation):
                relay, play_url = self._start_relay(url, generation, live=True)
                settled = self._load(mc, play_url, load_mime, stream_type, title)
            if not settled and not self._abandoned(generation):
                stream_type = "BUFFERED" if stream_type == "LIVE" else "LIVE"
                settled = self._load(mc, play_url, load_mime, stream_type, title, start)
            if (not settled and relay is None and play_url == url
                    and not probe["is_live"] and not self._abandoned(generation)):
                # A container or codec this receiver cannot play: re-encode.
                relay, play_url = self._start_relay(url, generation, live=False)
                load_mime, stream_type = "application/vnd.apple.mpegurl", "BUFFERED"
                settled = self._load(mc, play_url, load_mime, stream_type, title, start)
            if self._abandoned(generation):
                raise PlaybackError("Casting was stopped.")
            if not settled:
                reason = getattr(mc.status, "idle_reason", None) or "no answer"
                raise PlaybackError(f"{device.name} did not start playing ({reason}).")
            if start > 5 and stream_type == "BUFFERED":
                # Some receivers ignore currentTime on load; one bounded seek.
                current = getattr(mc.status, "current_time", None) or 0.0
                if current < start - 5:
                    try:
                        self._bounded(mc.seek, start)
                    except Exception:
                        LOG.info("Casting: resume seek was not acknowledged", exc_info=True)
            if probe["is_live"]:
                with self._lock:
                    if generation == self._generation:
                        self._live_load = (generation, cast, play_url, load_mime, stream_type)
                        self._cast_progress = None
        except Exception:
            self._drop_relay(relay)
            raise

    def _chromecast_status(self) -> Dict:
        snapshot = {"position_seconds": None, "media_session_id": None, "content_id": None,
                    "player_state": None, "receiver_app_ids": [], "transport_id": None,
                    "connected": False, "supports_session_detection": True}
        cast = self._cast
        if cast is None:
            return snapshot
        try:
            snapshot["connected"] = bool(cast.socket_client.is_connected)
        except Exception:
            return snapshot
        if not snapshot["connected"]:
            return snapshot
        mc = cast.media_controller
        try:
            before = getattr(mc.status, "last_updated", None)
            mc.update_status()
            deadline = time.monotonic() + 1.5
            while (getattr(mc.status, "last_updated", None) == before
                   and time.monotonic() < deadline):
                time.sleep(0.05)
        except Exception:
            LOG.debug("CastingManager._chromecast_status: update_status", exc_info=True)
        status = mc.status
        position = getattr(status, "adjusted_current_time", None)
        if position is None:
            position = getattr(status, "current_time", None)
        snapshot.update({
            "position_seconds": position,
            "media_session_id": getattr(status, "media_session_id", None),
            "content_id": getattr(status, "content_id", None),
            "player_state": getattr(status, "player_state", None),
            "receiver_app_ids": [cast.app_id] if cast.app_id else [],
            "transport_id": getattr(getattr(cast, "status", None), "transport_id", None),
        })
        return snapshot

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(WATCHDOG_SECONDS):
            try:
                self._recover_live_cast()
            except Exception:
                LOG.debug("CastingManager watchdog: ignored exception", exc_info=True)

    def _recover_live_cast(self) -> None:
        """Reload a live cast that ended or froze on the receiver (Caster's rules)."""
        with self._lock:
            load = self._live_load
        if load is None or self._recovering:
            return
        generation, cast, url, mime, stream_type = load
        now = time.monotonic()
        status = cast.media_controller.status
        if status is None:
            return
        state = status.player_state
        if state in ("PLAYING", "BUFFERING"):
            try:
                cast.media_controller.update_status()
            except Exception:
                LOG.debug("CastingManager._recover_live_cast: update_status", exc_info=True)
            position = getattr(status, "current_time", None)
            session = getattr(status, "media_session_id", None)
            updated = getattr(status, "last_updated", None)
            if position is None:
                return
            previous = self._cast_progress
            if previous is None or previous[0] is not load or previous[1:3] != (session, position):
                self._cast_progress = (load, session, position, now, updated)
                return
            if updated is None or updated == previous[4]:
                return
            if now - previous[3] < CAST_STALL_TIMEOUT:
                return
        elif state != "IDLE":
            self._cast_progress = None      # a pause is the user's; leave it
            return
        if now < self._cast_retry_at:
            return
        self._cast_retry_at = now + CAST_RECOVERY_INTERVAL
        self._recovering = True
        try:
            self._ensure_receiver(cast)
            if self._abandoned(generation) or self._live_load is not load:
                return
            LOG.info("Casting: live stream stalled on the receiver; reloading it")
            self._load(cast.media_controller, url, mime, stream_type, "BlindRSS")
        finally:
            self._recovering = False

    # ------------------------------------------------------------------ #
    # AirPlay (RAOP audio): pause and seek restart the source on one session
    # ------------------------------------------------------------------ #
    def _play_airplay(self, device: CastDevice, url: str, generation: int,
                      start: float) -> None:
        try:
            import pyatv
            from pyatv.const import Protocol
        except ImportError as err:
            raise CastError("AirPlay support is not installed (pyatv).") from err
        engine = _engine()
        loop = self._loop_thread.loop
        air = _AirSession(generation)
        air.pending_seek = start or None
        air.pos = start
        started = threading.Event()
        failure: list = []

        async def runner() -> None:
            stream_task = None
            air.shutdown = asyncio.Event()
            air.wake = asyncio.Event()
            with self._lock:
                if generation == self._generation:
                    self._air = air
                else:
                    air.shutdown.set()
            try:
                probe_job = loop.run_in_executor(None, engine.probe_media, url)
                air.atv = await pyatv.connect(device.device.key, loop, protocol=Protocol.RAOP)
                probe = await probe_job
                air.live = bool(probe["is_live"]) and not probe["is_audio"]
                if air.live:
                    air.pending_seek = None
                while not air.shutdown.is_set():
                    proc, reader = await self._raop_source(url, air)
                    if air.t0 is None:
                        air.t0 = time.monotonic()
                    air.state = "playing"
                    air.wake.clear()
                    stream_task = asyncio.create_task(air.atv.stream.stream_file(reader))
                    started.set()
                    stop_wait = asyncio.create_task(air.shutdown.wait())
                    wake_wait = asyncio.create_task(air.wake.wait())
                    try:
                        await asyncio.wait([stream_task, stop_wait, wake_wait],
                                           return_when=asyncio.FIRST_COMPLETED)
                        error = None
                        if not stream_task.done():
                            stream_task.cancel()
                        try:
                            await stream_task
                        except asyncio.CancelledError:
                            pass
                        except Exception as exc:
                            error = exc
                        stream_task = None
                        if air.shutdown.is_set():
                            break
                        if air.wake.is_set():
                            air.wake.clear()
                            continue            # resume or seek: reopen here
                        if air.state == "paused":
                            await air.wake.wait()
                            air.wake.clear()
                            continue
                        if air.live:
                            await asyncio.sleep(1)  # a live source dropped
                            continue
                        code = proc.poll()
                        if error is None and code not in (None, 0):
                            error = RuntimeError(f"ffmpeg could not read the stream (exit code {code})")
                        if error is not None:
                            raise error
                        air.state = "stopped"   # the episode finished
                        break
                    finally:
                        stop_wait.cancel()
                        wake_wait.cancel()
                        if proc.poll() is None:
                            proc.kill()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                failure.append(exc)
                LOG.info("Casting: AirPlay stream ended: %s", exc)
            finally:
                started.set()
                # Where it got to, so a resume can pick up from there.
                air.pos = air.position()
                air.t0 = None
                air.state = "stopped"
                if stream_task is not None and not stream_task.done():
                    stream_task.cancel()
                    try:
                        await stream_task
                    except (asyncio.CancelledError, Exception):
                        pass
                if air.atv is not None:
                    await engine._close_atv(air.atv)

        air.loop_future = asyncio.run_coroutine_threadsafe(runner(), loop)
        if not started.wait(AIRPLAY_START_TIMEOUT):
            self._end_air(air)
            raise PlaybackError(f"{device.name} did not start playing in time.")
        try:
            air.loop_future.result(timeout=1.5)  # a refusal comes at once
        except concurrent.futures.TimeoutError:
            pass
        except Exception:
            LOG.debug("CastingManager._play_airplay: runner", exc_info=True)
        if failure:
            raise PlaybackError(f"AirPlay could not play the stream: {failure[0]}")
        if self._abandoned(generation):
            raise PlaybackError("Casting was stopped.")

    async def _raop_source(self, url: str, air: _AirSession):
        """ffmpeg extracting audio as WAV for pyatv, from the pending seek (Caster's pipe)."""
        import subprocess
        engine = _engine()
        cmd = [engine._find_ffmpeg(), "-hide_banner", "-loglevel", "error"]
        if url.lower().startswith(("http://", "https://")):
            if air.live:
                cmd += ["-seekable", "0"]   # a byte-offset resume splices replays in
            cmd += ["-rw_timeout", "5000000"]
        cmd += ["-analyzeduration", "1000000", "-probesize", "1000000"]
        if air.pending_seek:
            cmd += ["-ss", str(max(air.pending_seek - 2.0, 0.0))]
        cmd += [
            "-fflags", "+genpts+nobuffer", "-flags", "+low_delay",
            "-i", url,
            "-vn", "-map", "a:0?",
            "-af", "aresample=44100:async=1000:first_pts=0",
            "-ac", "2", "-f", "wav", "-c:a", "pcm_s16le", "-flush_packets", "1", "-",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, **engine._no_window_kwargs())
        air.proc = proc
        if air.pending_seek:
            air.pos = air.pending_seek
        air.pending_seek = None
        reader = engine.SeekablePipeReader(proc.stdout.read1, proc.stdout.close)
        await asyncio.get_running_loop().run_in_executor(None, reader.prefill)
        return proc, reader

    def _wake_air(self, air: _AirSession) -> None:
        if air.wake is not None:
            self._loop_thread.loop.call_soon_threadsafe(air.wake.set)

    def _air_pause(self) -> None:
        air = self._air
        if air is None or air.state != "playing":
            return
        air.pos = air.position()
        air.t0 = None
        air.state = "paused"
        proc = air.proc
        if proc is not None and proc.poll() is None:
            proc.kill()                 # ends the stream; the session stays open

    def _air_restart_if_ended(self, target: Optional[float]) -> bool:
        """Start the stream again when its RAOP session has already ended.

        A receiver can end the session on its own - switching input, going to
        standby - and the runner then finishes. A resume or seek after that
        would only change state here while the speaker stays silent.
        """
        air = self._air
        last = self._last_play
        future = air.loop_future if air is not None else None
        if last is None or (future is not None and not future.done()):
            return False
        url, title, channel = last
        LOG.info("Casting: the AirPlay session had ended; starting it again")
        self.play(url, title, channel, start_time_seconds=target)
        return True

    def _air_resume(self) -> None:
        air = self._air
        if air is None:
            return
        if not air.live and self._air_restart_if_ended(air.position()):
            return
        if air.state != "paused":
            return
        air.pending_seek = None if air.live else air.pos
        air.t0 = time.monotonic()
        air.state = "playing"
        self._wake_air(air)

    def _air_seek(self, target: float) -> None:
        air = self._air
        if air is None or air.live:
            return
        if self._air_restart_if_ended(target):
            return
        air.pending_seek = target
        air.pos = target
        air.t0 = time.monotonic()
        air.state = "playing"
        self._wake_air(air)

    def _end_air(self, air: _AirSession) -> None:
        proc = air.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                LOG.debug("CastingManager._end_air: ffmpeg", exc_info=True)
        if air.shutdown is not None and self._loop_thread is not None:
            self._loop_thread.loop.call_soon_threadsafe(air.shutdown.set)
        future = air.loop_future
        if future is not None:
            try:
                # Let the RAOP session close properly on the receiver.
                future.result(timeout=5)
            except Exception:
                LOG.debug("CastingManager._end_air: runner", exc_info=True)

    # ------------------------------------------------------------------ #
    # UPnP / DLNA
    # ------------------------------------------------------------------ #
    def _play_upnp(self, device: CastDevice, url: str, title: str, generation: int,
                   start: float) -> None:
        engine = _engine()
        probe = engine.probe_media(url)
        relay = None
        try:
            if probe["mime"] == "video/mp2t":
                relay, play_url = self._start_relay(url, generation, live=bool(probe["is_live"]))
                mime = "application/vnd.apple.mpegurl"
            elif url.lower().startswith(("http://", "https://")):
                play_url, mime = url, probe["mime"]
            else:
                relay, play_url = self._start_relay(url, generation)
                mime = "application/vnd.apple.mpegurl"
            if self._abandoned(generation):
                raise PlaybackError("Casting was stopped.")
            self._upnp_push(device, play_url, mime, title)
        except Exception:
            self._drop_relay(relay)
            raise
        if start > 0 and not probe["is_live"]:
            # Renderers take no start position with the URL; seek once playing.
            from caster_extras import upnp_state
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    if upnp_state(device.device.key["control_url"]) == "PLAYING":
                        break
                except Exception:
                    break
                time.sleep(0.5)
            try:
                self._upnp_seek(device, start)
            except Exception:
                LOG.info("Casting: renderer refused the resume seek", exc_info=True)

    @staticmethod
    def _upnp_push(device: CastDevice, play_url: str, mime: str, title: str) -> None:
        from caster_devices import yxc_available, yxc_set_input
        from caster_extras import upnp_host, upnp_play

        control_url = device.device.key["control_url"]
        host = upnp_host(control_url)
        try:
            # A MusicCast receiver ignores a push unless on its network input.
            if host and yxc_available(host):
                yxc_set_input(host, "server")
        except Exception:
            LOG.debug("CastingManager._upnp_push: MusicCast input", exc_info=True)
        try:
            upnp_play(control_url, play_url, title, mime,
                      "object.item.audioItem.musicTrack" if mime.startswith("audio/")
                      else "object.item.videoItem")
        except Exception as err:
            raise PlaybackError(f"{device.name} refused the stream: {err}") from err

    @staticmethod
    def _upnp_action(device: CastDevice, action: str, extra: str) -> None:
        from caster_extras import _soap
        _soap(device.device.key["control_url"], action,
              f'<u:{action} xmlns:u="{_AVT}"><InstanceID>0</InstanceID>{extra}</u:{action}>')

    def _upnp_seek(self, device: CastDevice, target: float) -> None:
        self._upnp_action(device, "Seek",
                          f"<Unit>REL_TIME</Unit><Target>{_hms(target)}</Target>")

    @staticmethod
    def _upnp_status(device: CastDevice) -> tuple:
        from caster_extras import upnp_state
        control_url = device.device.key["control_url"]
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:GetPositionInfo xmlns:u="{_AVT}"><InstanceID>0</InstanceID></u:GetPositionInfo>'
            "</s:Body></s:Envelope>")
        request = urllib.request.Request(
            control_url, data=body.encode("utf-8"), method="POST",
            headers={"Content-Type": 'text/xml; charset="utf-8"',
                     "SOAPACTION": f'"{_AVT}#GetPositionInfo"'})
        with urllib.request.urlopen(request, timeout=COMMAND_TIMEOUT) as response:
            reply = response.read().decode("utf-8", "replace")
        match = re.search(r"<RelTime>([^<]+)<", reply)
        position = _parse_hms(match.group(1)) if match else None
        state = upnp_state(control_url)
        state = {"PAUSED_PLAYBACK": "PAUSED", "TRANSITIONING": "BUFFERING",
                 "STOPPED": "IDLE", "NO_MEDIA_PRESENT": "IDLE"}.get(state, state)
        return position, state

    # ------------------------------------------------------------------ #
    # Sonos, Roku, Kodi
    # ------------------------------------------------------------------ #
    @staticmethod
    def _sonos_zone(device: CastDevice):
        from caster_devices import _sonos_coordinator, _sonos_device
        return _sonos_coordinator(_sonos_device(device.device.key["ip"]))

    def _play_sonos(self, device: CastDevice, url: str, title: str, start: float) -> None:
        from caster_devices import sonos_play
        engine = _engine()
        probe = engine.probe_media(url)
        mime = probe["mime"] if probe["is_audio"] else "audio/mpeg"
        try:
            sonos_play(device.device.key["ip"], url, title, mime)
        except Exception as err:
            raise PlaybackError(f"Sonos error: {err}") from err
        if start > 0 and not probe["is_live"]:
            try:
                self._sonos_zone(device).seek(_hms(start))
            except Exception:
                LOG.info("Casting: Sonos refused the resume seek", exc_info=True)

    def _play_roku(self, device: CastDevice, url: str, title: str, generation: int) -> None:
        from caster_devices import roku_play
        engine = _engine()
        probe = engine.probe_media(url)
        relay = None
        try:
            if probe["mime"] == "video/mp2t":
                # Roku Media Player has no MPEG-TS: MP4 or HLS only.
                relay, play_url = self._start_relay(url, generation, live=bool(probe["is_live"]))
                mime = "application/vnd.apple.mpegurl"
            else:
                play_url, mime = url, engine.roku_mime(url)
            roku_play(device.device.key["base"], play_url, mime, title)
        except PlaybackError:
            self._drop_relay(relay)
            raise
        except Exception as err:
            self._drop_relay(relay)
            raise PlaybackError(f"Roku error: {err}") from err

    @staticmethod
    def _kodi_player(device: CastDevice) -> Optional[int]:
        from caster_devices import _kodi_rpc
        active = _kodi_rpc(device.device.key["base"], "Player.GetActivePlayers", {})
        players = active.get("result") or []
        return players[0].get("playerid", 1) if players else None

    def _play_kodi(self, device: CastDevice, url: str, start: float) -> None:
        import urllib.error
        from caster_devices import kodi_play
        try:
            kodi_play(device.device.key["base"], url)
        except urllib.error.HTTPError as err:
            if err.code == 401:
                raise PlaybackError("Kodi refused the request. In Kodi, allow remote "
                                    "control over HTTP without a password.") from err
            raise PlaybackError(f"Kodi error: {err}") from err
        except Exception as err:
            raise PlaybackError(f"Kodi error: {err}") from err
        if start > 0:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    if self._kodi_player(device) is not None:
                        self._kodi_seek(device, start)
                        break
                except Exception:
                    LOG.debug("CastingManager._play_kodi: resume seek", exc_info=True)
                time.sleep(0.5)

    def _kodi_play_pause(self, device: CastDevice, play: bool) -> None:
        from caster_devices import _kodi_rpc
        player = self._kodi_player(device)
        if player is not None:
            _kodi_rpc(device.device.key["base"], "Player.PlayPause",
                      {"playerid": player, "play": bool(play)})

    def _kodi_seek(self, device: CastDevice, target: float) -> None:
        from caster_devices import _kodi_rpc
        player = self._kodi_player(device)
        if player is None:
            return
        seconds = int(target)
        _kodi_rpc(device.device.key["base"], "Player.Seek", {
            "playerid": player,
            "value": {"time": {"hours": seconds // 3600, "minutes": (seconds % 3600) // 60,
                               "seconds": seconds % 60, "milliseconds": 0}},
        })

    def _kodi_status(self, device: CastDevice) -> tuple:
        from caster_devices import _kodi_rpc
        player = self._kodi_player(device)
        if player is None:
            return None, "IDLE"
        reply = _kodi_rpc(device.device.key["base"], "Player.GetProperties",
                          {"playerid": player, "properties": ["time", "speed"]})
        result = reply.get("result") or {}
        clock = result.get("time") or {}
        position = (clock.get("hours", 0) * 3600 + clock.get("minutes", 0) * 60
                    + clock.get("seconds", 0) + clock.get("milliseconds", 0) / 1000.0)
        return position, ("PAUSED" if result.get("speed", 1) == 0 else "PLAYING")
