"""Unified casting module for Chromecast, DLNA/UPnP, and AirPlay.

Provides a simple interface to discover and cast to network media devices.
Each device is labeled with its type for easy identification.
"""

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID
import os
import urllib.parse

from core import utils

try:
    from core.stream_proxy import get_proxy
    from core.http_headers import channel_http_headers
except ImportError:
    # Fallback/Mock if running standalone
    def get_proxy():
        return None

    def channel_http_headers(ch):
        return {}

LOG = logging.getLogger(__name__)


class CastProtocol(Enum):
    """Supported casting protocols."""
    CHROMECAST = "Chromecast"
    DLNA = "DLNA"
    UPNP = "UPnP"
    AIRPLAY = "AirPlay"


@dataclass
class CastDevice:
    """Represents a discovered casting device."""
    name: str
    protocol: CastProtocol
    identifier: str  # Unique ID for reconnection
    host: str
    port: int
    # Protocol-specific metadata
    metadata: Dict = field(default_factory=dict)
    
    @property
    def display_name(self) -> str:
        """User-friendly name with protocol label."""
        return f"{self.name} [{self.protocol.value}]"
    
    @property
    def unique_id(self) -> str:
        """Unique identifier for this device."""
        return f"{self.protocol.value}:{self.identifier}"


class CastError(Exception):
    """Base exception for casting errors."""
    pass


class DeviceNotFoundError(CastError):
    """Device could not be found on the network."""
    pass


class ConnectionError(CastError):
    """Failed to connect to device."""
    pass


class PlaybackError(CastError):
    """Failed to start or control playback."""
    pass


class BaseCaster(ABC):
    """Abstract base class for protocol-specific casters."""
    
    @abstractmethod
    async def discover(self, timeout: float = 5.0) -> List[CastDevice]:
        """Discover devices on the network."""
        pass
    
    @abstractmethod
    async def connect(self, device: CastDevice) -> None:
        """Connect to a specific device."""
        pass
    
    @abstractmethod
    async def play(self, url: str, title: str = "IPTV Stream",
                   content_type: str = "video/mp2t", headers: Optional[Dict[str, str]] = None,
                   start_time_seconds: Optional[float] = None) -> None:
        """Start playing a stream URL."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop playback."""
        pass
    
    @abstractmethod
    async def pause(self) -> None:
        """Pause playback."""
        pass
    
    @abstractmethod
    async def resume(self) -> None:
        """Resume playback."""
        pass
    
    @abstractmethod
    async def set_volume(self, level: float) -> None:
        """Set volume (0.0 to 1.0)."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from device."""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to a device."""
        pass
    async def seek(self, position_seconds: float) -> None:
        """Seek to a position in seconds (if supported by the protocol)."""
        raise NotImplementedError

    async def get_position(self) -> Optional[float]:
        """Return current playback position in seconds (if supported)."""
        return None



# ============================================================================
# Chromecast Implementation
# ============================================================================

try:
    import pychromecast
    from pychromecast.config import APP_MEDIA_RECEIVER
    _HAS_CHROMECAST = True
except ImportError:
    _HAS_CHROMECAST = False
    pychromecast = None
    APP_MEDIA_RECEIVER = "CC1AD845"


class ChromecastCaster(BaseCaster):
    """Chromecast protocol implementation."""

    _DISCOVERY_TIMEOUT = 8.0
    _READY_TIMEOUT = 15.0
    _SOCKET_TIMEOUT = 5.0
    _CONNECT_TRIES = 3
    _RETRY_WAIT = 1.0
    _RECEIVER_LAUNCH_TIMEOUT = 15.0
    _RECEIVER_CONFIRM_TIMEOUT = 8.0
    _RECEIVER_STATUS_WAIT = 1.0
    _RECEIVER_STOP_TIMEOUT = 8.0
    
    def __init__(self):
        if not _HAS_CHROMECAST:
            raise CastError("pychromecast is not installed. Run: pip install pychromecast")
        self._cast = None
        self._browser = None
        # StreamProxy starts lazily when needed.
    
    async def discover(self, timeout: float = 5.0) -> List[CastDevice]:
        """Discover Chromecast devices."""
        devices = []
        
        # Run discovery in thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        
        def do_discovery():
            browser = None
            try:
                # Use the standard discovery function
                # This returns a list of Playable/Cast objects and the browser, but we just want discovery info here.
                # get_chromecasts returns (casts, browser). blocking=True waits until timeout.
                casts, browser = pychromecast.get_chromecasts(timeout=timeout)
                return casts
            except Exception as e:
                LOG.warning("Chromecast discovery error: %s", e)
                return []
            finally:
                if browser is not None:
                    try:
                        browser.stop_discovery()
                    except Exception as e:
                        LOG.debug("Failed to stop Chromecast discovery browser: %s", e)
        
        discovered_casts = await loop.run_in_executor(None, do_discovery)
        
        for cast in discovered_casts:
            try:
                # cast is a Chromecast object
                # Recent pychromecast versions store details in cast_info
                host = getattr(cast.cast_info, "host", None) or getattr(cast, "host", None)
                port = getattr(cast.cast_info, "port", None) or getattr(cast, "port", 8009)
                uuid = str(cast.uuid)
                
                device = CastDevice(
                    name=cast.name or cast.cast_info.friendly_name or f"Chromecast {uuid[:8]}",
                    protocol=CastProtocol.CHROMECAST,
                    identifier=uuid,
                    host=host,
                    port=port,
                    metadata={
                        "uuid": uuid,
                        "model_name": cast.model_name,
                        "manufacturer": "Google",
                        "cast_type": cast.cast_type,
                    }
                )
                devices.append(device)
                # Cache the cast object? No, better to get a fresh one on connect
                # or we can cache the connection info.
            except Exception as e:
                LOG.debug("Failed to process Chromecast device %s: %s", cast, e)
        
        return devices
    
    async def connect(self, device: CastDevice) -> None:
        """Connect to a Chromecast device."""
        loop = asyncio.get_event_loop()
        
        def do_connect():
            cast = None
            browser = None

            def stop_browser(candidate) -> None:
                if candidate is None:
                    return
                try:
                    candidate.stop_discovery()
                except Exception as e:
                    LOG.debug("Failed to stop Chromecast discovery browser: %s", e)

            def disconnect_cast(candidate) -> None:
                if candidate is None:
                    return
                try:
                    candidate.disconnect(timeout=5.0)
                except Exception as e:
                    LOG.debug("Failed to disconnect unsuccessful Chromecast session: %s", e)

            def find_listed(**criteria):
                found, found_browser = pychromecast.get_listed_chromecasts(
                    tries=self._CONNECT_TRIES,
                    retry_wait=self._RETRY_WAIT,
                    timeout=self._SOCKET_TIMEOUT,
                    discovery_timeout=self._DISCOVERY_TIMEOUT,
                    known_hosts=[device.host] if device.host else None,
                    **criteria,
                )
                if not found:
                    stop_browser(found_browser)
                    return [], None
                return found, found_browser

            try:
                try:
                    device_uuid = UUID(str(device.identifier))
                except (TypeError, ValueError, AttributeError):
                    device_uuid = None

                chromecasts = []
                if device_uuid is not None:
                    chromecasts, browser = find_listed(uuids=[device_uuid])

                if not chromecasts:
                    # Friendly-name matching is a safe fallback when a device has
                    # been reset and advertises a new UUID. Names are passed as
                    # plain values, so characters such as "&" need no escaping.
                    chromecasts, browser = find_listed(friendly_names=[device.name])

                if not chromecasts:
                    raise DeviceNotFoundError(
                        f"Could not find Chromecast {device.name} at {device.host}"
                    )

                cast = chromecasts[0]
                
                cast.wait(timeout=self._READY_TIMEOUT)
                return cast, browser
            except Exception as e:
                disconnect_cast(cast)
                stop_browser(browser)
                raise ConnectionError(f"Failed to connect to {device.name}: {e}")
        
        self._cast, self._browser = await loop.run_in_executor(None, do_connect)

    @staticmethod
    def _reported_app_ids(cast) -> set[str]:
        """Return non-empty app IDs reported by the cast and receiver status."""
        app_ids = set()
        candidates = []
        try:
            candidates.append(getattr(cast, "app_id", None))
        except Exception:
            pass
        try:
            candidates.append(getattr(getattr(cast, "status", None), "app_id", None))
        except Exception:
            pass
        try:
            receiver = getattr(getattr(cast, "socket_client", None), "receiver_controller", None)
            candidates.append(getattr(receiver, "app_id", None))
            candidates.append(getattr(getattr(receiver, "status", None), "app_id", None))
        except Exception:
            pass

        for app_id in candidates:
            if app_id:
                app_ids.add(str(app_id))
        return app_ids

    def _poll_for_default_media_receiver(
        self,
        cast,
        *,
        accept_missing: bool,
    ) -> tuple[bool, set[str], Optional[Exception]]:
        """Refresh receiver status until the default receiver is confirmed."""
        target_app_id = APP_MEDIA_RECEIVER
        receiver = getattr(getattr(cast, "socket_client", None), "receiver_controller", None)
        deadline = time.monotonic() + self._RECEIVER_CONFIRM_TIMEOUT
        last_status_error = None

        while True:
            reported = self._reported_app_ids(cast)
            if target_app_id in reported:
                return True, reported, last_status_error
            if accept_missing and not reported:
                return True, reported, last_status_error

            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                return False, reported, last_status_error

            status_event = threading.Event()

            def status_callback(_sent, _response):
                status_event.set()

            if receiver is not None:
                try:
                    receiver.update_status(callback_function=status_callback)
                except TypeError:
                    try:
                        receiver.update_status()
                    except Exception as e:
                        last_status_error = e
                except Exception as e:
                    last_status_error = e

            if receiver is not None:
                status_event.wait(min(self._RECEIVER_STATUS_WAIT, remaining))
            else:
                time.sleep(min(0.2, remaining))

            remaining = max(0.0, deadline - time.monotonic())
            if remaining:
                time.sleep(min(0.1, remaining))

    def _stop_current_receiver_app(self, cast) -> Optional[Exception]:
        """Best-effort bounded stop of the app currently owning the receiver."""
        try:
            quit_app = getattr(cast, "quit_app", None)
            if callable(quit_app):
                quit_app(timeout=self._RECEIVER_STOP_TIMEOUT)
                return None

            receiver = getattr(
                getattr(cast, "socket_client", None),
                "receiver_controller",
                None,
            )
            if receiver is None or not hasattr(receiver, "stop_app"):
                return RuntimeError("Chromecast does not expose an app stop command")

            stopped = threading.Event()
            outcome = {"sent": False}

            def stop_callback(sent, _response):
                outcome["sent"] = bool(sent)
                stopped.set()

            receiver.stop_app(callback_function=stop_callback)
            if not stopped.wait(self._RECEIVER_STOP_TIMEOUT):
                return TimeoutError("Timed out stopping the current Chromecast app")
            if not outcome["sent"]:
                return RuntimeError("Chromecast rejected the app stop command")
            return None
        except Exception as e:
            return e

    def _ensure_default_media_receiver(self, cast) -> None:
        """Launch and confirm the Default Media Receiver before sending media."""
        target_app_id = APP_MEDIA_RECEIVER
        reported = self._reported_app_ids(cast)
        if target_app_id in reported:
            return

        launch_errors = []
        status_error = None

        try:
            cast.start_app(
                target_app_id,
                force_launch=True,
                timeout=self._RECEIVER_LAUNCH_TIMEOUT,
            )
        except Exception as e:
            launch_errors.append(e)
            confirmed, reported, status_error = self._poll_for_default_media_receiver(
                cast,
                accept_missing=False,
            )
            if confirmed:
                return
        else:
            confirmed, reported, status_error = self._poll_for_default_media_receiver(
                cast,
                accept_missing=True,
            )
            if confirmed:
                return

        stop_error = None
        if reported:
            stop_error = self._stop_current_receiver_app(cast)

        try:
            cast.start_app(
                target_app_id,
                force_launch=True,
                timeout=self._RECEIVER_LAUNCH_TIMEOUT,
            )
        except Exception as e:
            launch_errors.append(e)
            confirmed, reported, retry_status_error = (
                self._poll_for_default_media_receiver(
                    cast,
                    accept_missing=False,
                )
            )
            status_error = retry_status_error or status_error
            if confirmed:
                return
        else:
            confirmed, reported, retry_status_error = (
                self._poll_for_default_media_receiver(
                    cast,
                    accept_missing=True,
                )
            )
            status_error = retry_status_error or status_error
            if confirmed:
                return

        current = ", ".join(sorted(reported)) or "unknown"
        details = []
        if launch_errors:
            details.append(
                "launch error(s): " + "; ".join(str(error) for error in launch_errors)
            )
        if stop_error is not None:
            details.append(f"stop error: {stop_error}")
        if status_error is not None:
            details.append(f"status refresh error: {status_error}")
        detail = f"; {'; '.join(details)}" if details else ""
        raise PlaybackError(
            "Chromecast did not switch to the Default Media Receiver "
            f"(reported app: {current}){detail}"
        )
    
    async def play(self, url: str, title: str = "IPTV Stream",
                   content_type: str = "video/mp2t", headers: Optional[Dict[str, str]] = None,
                   start_time_seconds: Optional[float] = None) -> None:
        """Play a stream on Chromecast."""
        if not self._cast:
            raise ConnectionError("Not connected to a Chromecast device")
        
        loop = asyncio.get_event_loop()
        
        def do_play():
            cast = self._cast
            self._ensure_default_media_receiver(cast)
            mc = cast.media_controller
            
            content_type_actual = _detect_mime_type(url, content_type)
            
            # Chromecast must be able to reach the media URL. Local files and localhost URLs
            # must be served/proxied via StreamProxy using an IP reachable from the cast device.
            device_ip = None
            try:
                device_ip = getattr(cast, 'host', None)
                if not device_ip and getattr(cast, 'cast_info', None):
                    device_ip = getattr(cast.cast_info, 'host', None)
            except Exception:
                device_ip = None
            
            try:
                parsed = urllib.parse.urlparse(url or '')
            except Exception:
                parsed = urllib.parse.urlparse('')
            
            # Determine stream type (best-effort)
            stream_type = 'LIVE' if content_type_actual in ('application/x-mpegURL', 'application/vnd.apple.mpegurl') else 'BUFFERED'
            
            proxy = get_proxy()
            proxied_url = url
            
            try:
                file_path = None
                if parsed.scheme == 'file':
                    fp = urllib.parse.unquote(parsed.path or '')
                    # Windows file URLs are commonly like /C:/path
                    if fp.startswith('/') and len(fp) >= 3 and fp[2] == ':':
                        fp = fp[1:]
                    file_path = fp
                # urlparse treats a Windows drive letter as a URL scheme
                # (for example, C:\Music\track.wav has scheme "c"). Check
                # existing paths independently so raw Windows paths are served
                # through StreamProxy instead of being sent to Chromecast.
                elif url and os.path.isfile(url):
                    file_path = url
            
                if proxy and file_path:
                    proxied_url = proxy.get_file_url(file_path, device_ip=device_ip)
                    LOG.info('Casting local file via StreamProxy: %s -> %s', proxied_url, file_path)
                else:
                    needs_proxy = False
            
                    # localhost/loopback is not reachable by Chromecast/TV
                    if parsed.scheme in ('http', 'https') and parsed.hostname in ('127.0.0.1', 'localhost'):
                        needs_proxy = True
            
                    # If headers are required, we must proxy
                    if headers:
                        needs_proxy = True
            
                    # MPEG-TS is often not playable directly; remux to HLS
                    if content_type_actual == 'video/mp2t':
                        needs_proxy = True
            
                    if proxy and needs_proxy:
                        if content_type_actual == 'video/mp2t':
                            proxied_url = proxy.get_transcoded_url(url, headers, device_ip=device_ip)
                            stream_type = 'LIVE'
                            content_type_actual = 'application/x-mpegURL'
                            LOG.info('Remuxing MPEG-TS to HLS via proxy: %s', proxied_url)
                        else:
                            proxied_url = proxy.get_proxied_url(url, headers, device_ip=device_ip)
                            LOG.info('Casting to Chromecast via proxy: %s -> %s', proxied_url, url)
                    else:
                        proxied_url = url
            
                    # Live radio endpoints often look like /stream or /listen with no extension
                    if stream_type == 'BUFFERED' and isinstance(content_type_actual, str) and content_type_actual.startswith('audio/'):
                        p = (parsed.path or '').lower()
                        if not any(p.endswith(ext) for ext in ('.mp3', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.flac', '.wav')):
                            u = (url or '').lower()
                            if any(tok in u for tok in ('/stream', '/listen', '/live', 'radio')):
                                stream_type = 'LIVE'
            except Exception as e:
                LOG.warning('Chromecast URL preparation failed; trying direct URL: %s', e)
                proxied_url = url
            # Note: Older/Standard versions of pychromecast's play_media do not support custom_data kwarg.
            # It was added in newer versions or specific forks. We'll omit it to be safe.
            # If headers are absolutely required, a custom receiver or proxy is needed.
            # Start at a specific position if requested. pychromecast supports current_time in most versions.
            target_start = None
            try:
                if start_time_seconds is not None:
                    target_start = float(start_time_seconds)
                    if target_start < 0:
                        target_start = 0.0
            except Exception:
                target_start = None

            kwargs = dict(title=title, autoplay=True, stream_type=stream_type)
            if target_start and target_start > 0:
                kwargs["current_time"] = float(target_start)

            try:
                try:
                    mc.play_media(
                        proxied_url,
                        content_type_actual,
                        **kwargs
                    )
                except TypeError:
                    # Older pychromecast versions may not accept current_time
                    if "current_time" in kwargs:
                        kwargs.pop("current_time", None)
                    mc.play_media(
                        proxied_url,
                        content_type_actual,
                        **kwargs
                    )

                mc.block_until_active(timeout=10)
            except PlaybackError:
                raise
            except Exception as e:
                raise PlaybackError(f"Chromecast playback failed: {e}") from e

            # Some devices ignore current_time; enforce via seek with retries.
            if target_start and target_start > 0:
                import time as _time
                for _attempt in range(5):
                    try:
                        mc.update_status()
                    except Exception:
                        pass
                    cur = None
                    try:
                        st = getattr(mc, "status", None)
                        if st is not None:
                            cur = getattr(st, "adjusted_current_time", None)
                            if cur is None:
                                cur = getattr(st, "current_time", None)
                    except Exception:
                        cur = None

                    try:
                        if cur is not None and abs(float(cur) - float(target_start)) <= 2.0:
                            break
                    except Exception:
                        pass

                    try:
                        mc.seek(float(target_start))
                    except Exception:
                        pass
                    _time.sleep(0.8)

        
        await loop.run_in_executor(None, do_play)
    
    async def stop(self) -> None:
        cast = self._cast
        if cast:
            loop = asyncio.get_event_loop()

            def do_stop():
                mc = cast.media_controller
                try:
                    mc.update_status()
                except Exception:
                    pass
                status = getattr(mc, "status", None)
                if status is not None and getattr(status, "media_session_id", None) is None:
                    return
                mc.stop()

            await loop.run_in_executor(None, do_stop)
    
    async def pause(self) -> None:
        if self._cast:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._cast.media_controller.pause)
    
    async def resume(self) -> None:
        if self._cast:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._cast.media_controller.play)
    
    async def seek(self, position_seconds: float) -> None:
        """Seek to a position in seconds on Chromecast (best-effort)."""
        if not self._cast:
            return
        loop = asyncio.get_event_loop()

        def do_seek():
            import time as _time
            try:
                mc = self._cast.media_controller
                # Ensure media session is active before seeking.
                try:
                    if hasattr(mc, 'block_until_active'):
                        mc.block_until_active(timeout=10)
                except Exception:
                    pass

                start = _time.time()
                while _time.time() - start < 10:
                    try:
                        mc.update_status()
                    except Exception:
                        pass
                    st = getattr(mc, 'status', None)
                    if st is not None and getattr(st, 'media_session_id', None) is not None:
                        break
                    _time.sleep(0.2)

                try:
                    mc.seek(float(position_seconds))
                except Exception:
                    pass
            except Exception:
                pass

        await loop.run_in_executor(None, do_seek)

    async def get_position(self) -> Optional[float]:
        """Get current playback position in seconds from Chromecast (best-effort)."""
        if not self._cast:
            return None
        loop = asyncio.get_event_loop()

        def do_get():
            try:
                mc = self._cast.media_controller
                try:
                    mc.update_status()
                except Exception:
                    pass
                st = getattr(mc, 'status', None)
                if st is None:
                    return None
                v = getattr(st, 'adjusted_current_time', None)
                if v is None:
                    v = getattr(st, 'current_time', None)
                if v is None:
                    return None
                try:
                    return float(v)
                except Exception:
                    return None
            except Exception:
                return None

        return await loop.run_in_executor(None, do_get)

    async def set_volume(self, level: float) -> None:
        if self._cast:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._cast.set_volume, max(0.0, min(1.0, level)))
    
    async def disconnect(self) -> None:
        cast = self._cast
        browser = self._browser
        self._cast = None
        self._browser = None

        if cast is None and browser is None:
            return

        def do_disconnect():
            if cast:
                try:
                    cast.disconnect(timeout=5.0)
                except Exception:
                    pass
            if browser:
                try:
                    browser.stop_discovery()
                except Exception:
                    pass

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_disconnect)
    
    def is_connected(self) -> bool:
        if self._cast is None:
            return False
        try:
            socket_client = getattr(self._cast, "socket_client", None)
            if socket_client is not None and hasattr(socket_client, "is_connected"):
                return bool(socket_client.is_connected)
        except Exception:
            return False
        return True


# ============================================================================
# DLNA/UPnP Implementation
# ============================================================================

try:
    from async_upnp_client.client_factory import UpnpFactory
    from async_upnp_client.aiohttp import AiohttpRequester
    from async_upnp_client.profiles.dlna import DmrDevice
    from async_upnp_client.search import async_search
    from async_upnp_client.ssdp import SSDP_TARGET_V1
    _HAS_UPNP = True
except ImportError:
    _HAS_UPNP = False


class DLNACaster(BaseCaster):
    """DLNA/UPnP protocol implementation."""
    
    # UPnP service types for media renderers
    MEDIA_RENDERER_TYPES = [
        "urn:schemas-upnp-org:device:MediaRenderer:1",
        "urn:schemas-upnp-org:device:MediaRenderer:2",
    ]
    
    def __init__(self):
        if not _HAS_UPNP:
            raise CastError("async-upnp-client is not installed. Run: pip install async-upnp-client")
        self._device: Optional[DmrDevice] = None
        self._factory: Optional[UpnpFactory] = None
        self._requester = None
    
    async def discover(self, timeout: float = 5.0) -> List[CastDevice]:
        """Discover DLNA/UPnP media renderers."""
        devices = []
        seen_usns = set()
        
        LOG.debug("Starting DLNA discovery (timeout=%.1fs)", timeout)
        
        async def process_response(response):
            try:
                usn = response.get("usn", "")
                st = response.get("st", "")
                location = response.get("location", "")
                
                # LOG.debug("DLNA Scan: Found USN=%s ST=%s Loc=%s", usn, st, location)

                if usn in seen_usns:
                    return
                seen_usns.add(usn)
                
                if not location:
                    return
                
                # Check if it is a media renderer
                is_renderer = any(rt in st for rt in self.MEDIA_RENDERER_TYPES)
                # Also accept ssdp:all responses that have MediaRenderer in USN
                if not is_renderer and "MediaRenderer" not in usn:
                    # LOG.debug("Ignoring non-renderer: %s", usn)
                    return
                
                LOG.info("Found DLNA Renderer: %s", usn)
                
                # Extract host/port from location
                from urllib.parse import urlparse
                parsed = urlparse(location)
                host = parsed.hostname or ""
                port = parsed.port or 80
                
                # Get friendly name from cache-control or USN
                name = usn.split("::")[0] if "::" in usn else usn
                if name.startswith("uuid:"):
                    name = f"DLNA Device {name[5:13]}"
                
                if "DLNA" in st.upper() or "dlna" in location.lower():
                    protocol = CastProtocol.DLNA
                else:
                    protocol = CastProtocol.UPNP
                
                device = CastDevice(
                    name=name,
                    protocol=protocol,
                    identifier=usn,
                    host=host,
                    port=port,
                    metadata={
                        "location": location,
                        "st": st,
                        "usn": usn,
                    }
                )
                devices.append(device)
                
            except Exception as e:
                LOG.debug("Failed to process DLNA device: %s", e)
        
        try:
            # Search for media renderers
            # We explicitly search for MediaRenderer:1 to reduce noise, and ssdp:all as backup
            targets = [self.MEDIA_RENDERER_TYPES[0], SSDP_TARGET_V1]
            for target in targets:
                await async_search(process_response, timeout=timeout / len(targets), service_type=target)
        except Exception as e:
            LOG.warning("DLNA discovery error: %s", e)
        
        LOG.debug("DLNA discovery finished. Found %d candidates. Fetching names...", len(devices))
        
        # Fetch friendly names for discovered devices
        await self._fetch_device_names(devices)
        
        return devices
    
    async def _fetch_device_names(self, devices: List[CastDevice]) -> None:
        """Fetch proper friendly names from device descriptions."""
        for device in devices:
            try:
                location = device.metadata.get("location", "")
                if not location:
                    continue
                
                requester = AiohttpRequester()
                factory = UpnpFactory(requester)
                upnp_device = await factory.async_create_device(location)
                
                if upnp_device.friendly_name:
                    device.name = upnp_device.friendly_name
                if upnp_device.manufacturer:
                    device.metadata["manufacturer"] = upnp_device.manufacturer
                if upnp_device.model_name:
                    device.metadata["model_name"] = upnp_device.model_name
                
                # Refine protocol based on device info
                model = (upnp_device.model_name or "").lower()
                manufacturer = (upnp_device.manufacturer or "").lower()
                if "dlna" in model or "dlna" in manufacturer:
                    device.protocol = CastProtocol.DLNA
                
                await requester.async_close()
                
            except Exception as e:
                LOG.debug("Failed to fetch device name for %s: %s", device.identifier, e)
    
    async def connect(self, device: CastDevice) -> None:
        """Connect to a DLNA/UPnP device."""
        try:
            location = device.metadata.get("location", "")
            if not location:
                raise ConnectionError(f"No location URL for device {device.name}")
            
            self._requester = AiohttpRequester()
            self._factory = UpnpFactory(self._requester)
            upnp_device = await self._factory.async_create_device(location)
            self._device = DmrDevice(upnp_device, None)
            
        except Exception as e:
            await self.disconnect()
            raise ConnectionError(f"Failed to connect to {device.name}: {e}")
    
    async def play(self, url: str, title: str = "IPTV Stream",
                   content_type: str = "video/mp2t", headers: Optional[Dict[str, str]] = None,
                   start_time_seconds: Optional[float] = None) -> None:
        """Play a stream on DLNA device."""
        if not self._device:
            raise ConnectionError("Not connected to a DLNA device")
        
        # Improved MIME type detection
        content_type = _detect_mime_type(url, content_type)
        
        try:
            # Build DIDL-Lite metadata
            # Add DLNA flags for better compatibility (Samsung, LG, Sony)
            # DLNA.ORG_OP=01 (Seek supported), DLNA.ORG_CI=0 (Transcoded=0)
            dlna_features = "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"
            res_attrs = f'protocolInfo="http-get:*:{content_type}:{dlna_features}"'
            
            if headers:
                # Common headers might be passed as a custom element or as part of protocolInfo
                # This is a best-effort attempt as standard doesn't define well.
                # User-Agent, Referer are most common.
                user_agent = headers.get("user-agent")
                referer = headers.get("referer")
                
                if user_agent:
                    res_attrs += f' http-user-agent="{user_agent}"'
                if referer:
                    res_attrs += f' http-referer="{referer}"'
                # Other headers are harder to embed portably.
            
            didl = f'''<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
                xmlns:dc="http://purl.org/dc/elements/1.1/"
                xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
                <item id="1" parentID="0" restricted="1">
                    <dc:title>{title}</dc:title>
                    <upnp:class>object.item.videoItem.videoBroadcast</upnp:class>
                    <res {res_attrs}>{url}</res>
                </item>
            </DIDL-Lite>'''
            
            await self._device.async_set_transport_uri(url, title, didl)
            await self._device.async_play()
            
        except Exception as e:
            raise PlaybackError(f"Failed to start playback: {e}")
    
    async def stop(self) -> None:
        if self._device:
            try:
                await self._device.async_stop()
            except Exception as e:
                LOG.debug("DLNA stop error: %s", e)
    
    async def pause(self) -> None:
        if self._device:
            try:
                await self._device.async_pause()
            except Exception as e:
                LOG.debug("DLNA pause error: %s", e)
    
    async def resume(self) -> None:
        if self._device:
            try:
                await self._device.async_play()
            except Exception as e:
                LOG.debug("DLNA resume error: %s", e)
    
    async def set_volume(self, level: float) -> None:
        if self._device:
            try:
                # DLNA volume is 0-100
                vol = max(0.0, min(1.0, float(level)))
                await self._device.async_set_volume_level(int(vol * 100))
            except Exception as e:
                LOG.debug("DLNA set_volume error: %s", e)
    
    async def disconnect(self) -> None:
        self._device = None
        self._factory = None
        if self._requester:
            try:
                await self._requester.async_close()
            except Exception:
                pass
            self._requester = None


# ============================================================================
# AirPlay Implementation
# ============================================================================

try:
    import pyatv
    from pyatv import conf
    _HAS_AIRPLAY = True
except ImportError:
    _HAS_AIRPLAY = False


class AirPlayCaster(BaseCaster):
    """AirPlay protocol implementation using pyatv."""
    
    def __init__(self):
        if not _HAS_AIRPLAY:
            raise CastError("pyatv is not installed. Run: pip install pyatv")
        self._atv = None
        
    async def discover(self, timeout: float = 5.0) -> List[CastDevice]:
        """Discover AirPlay devices."""
        devices = []
        try:
            atvs = await pyatv.scan(loop=asyncio.get_event_loop(), timeout=int(timeout))
            
            for atv in atvs:
                # Prefer AirPlay protocol
                service = atv.get_service(conf.Protocol.AirPlay)
                if not service:
                    continue
                
                # atv is a BaseConfig which has address (IPv4/IPv6)
                # service is BaseService (or MutableService) which has port
                host = str(atv.address) if atv.address else ""
                
                device = CastDevice(
                    name=atv.name,
                    protocol=CastProtocol.AIRPLAY,
                    identifier=atv.identifier,
                    host=host,
                    port=service.port,
                    metadata={
                        "conf": atv
                    }
                )
                devices.append(device)
        except Exception as e:
            LOG.warning("AirPlay discovery error: %s", e)
            
        return devices
    
    async def connect(self, device: CastDevice, credentials: Optional[str] = None) -> None:
        """Connect to an AirPlay device."""
        config = device.metadata.get("conf")
        
        # Try to connect with cached config first
        try:
            if not config:
                raise ConnectionError("Missing AirPlay configuration")
            
            if credentials:
                config.set_credentials(conf.Protocol.AirPlay, credentials)

            self._atv = await pyatv.connect(config, loop=asyncio.get_event_loop())
            return
        except Exception:
            # Fallback: re-scan and retry once
            pass
            
        try:
            # Re-scan to get fresh config (handles IP changes, ephemeral ports, loop affinity)
            LOG.info(f"Re-scanning for {device.identifier}...")
            atvs = await pyatv.scan(identifier=device.identifier, loop=asyncio.get_event_loop(), timeout=3)
            if atvs:
                config = atvs[0]
                # Update metadata reference for future use
                device.metadata["conf"] = config
            
            if not config:
                raise ConnectionError("Device not found during re-scan")

            if credentials:
                config.set_credentials(conf.Protocol.AirPlay, credentials)
            
            self._atv = await pyatv.connect(config, loop=asyncio.get_event_loop())
            
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {device.name}: {e}")

    async def start_pairing(self, device: CastDevice) -> object:
        """Start pairing process. Returns a pyatv PairingHandler."""
        # Always re-scan before pairing to ensure we have the latest state/loop context
        config = device.metadata.get("conf")
        try:
            atvs = await pyatv.scan(identifier=device.identifier, loop=asyncio.get_event_loop(), timeout=3)
            if atvs:
                config = atvs[0]
                device.metadata["conf"] = config
        except Exception as e:
            LOG.warning("Re-scan for pairing failed: %s", e)
            
        if not config:
            raise CastError("Missing configuration")
        
        # Ensure we start with a clean slate for credentials to avoid "not authenticated"
        # if stale garbage is present.
        config.set_credentials(conf.Protocol.AirPlay, None)
        
        return await pyatv.pair(config, conf.Protocol.AirPlay, loop=asyncio.get_event_loop())
    
    async def play(self, url: str, title: str = "IPTV Stream",
                   content_type: str = "video/mp2t", headers: Optional[Dict[str, str]] = None,
                   start_time_seconds: Optional[float] = None) -> None:
        """Play a stream on AirPlay."""
        if not self._atv:
            raise ConnectionError("Not connected to an AirPlay device")
        
        try:
            stream = self._atv.stream
            # pyatv's play_url doesn't directly support custom HTTP headers
            # However, some headers might be embedded in the URL itself if needed
            # For most AirPlay devices, this is not a common requirement as they
            # often fetch content directly without needing custom headers from the client.
            # If a stream requires custom headers, a proxy might be needed or
            # pyatv's capabilities extended.
            pos = 0
            try:
                if start_time_seconds is not None:
                    pos = max(0, int(float(start_time_seconds)))
            except Exception:
                pos = 0
            await stream.play_url(url, position=pos)
        except Exception as e:
            # pyatv 0.14+ raises NotSupportedError if the connected protocol doesn't support streaming (e.g. RAOP only)
            if "NotSupportedError" in str(type(e).__name__):
                raise PlaybackError(
                    "This AirPlay device does not support video streaming (play_url). "
                    "It might be an audio-only device or connected via limited protocol."
                )
            raise PlaybackError(f"Failed to start playback: {e}")

    async def stop(self) -> None:
        if self._atv:
            try:
                await self._atv.remote_control.stop()
            except Exception as e:
                LOG.debug("AirPlay stop error: %s", e)

    async def pause(self) -> None:
        if self._atv:
            try:
                await self._atv.remote_control.pause()
            except Exception as e:
                LOG.debug("AirPlay pause error: %s", e)

    async def resume(self) -> None:
        if self._atv:
            try:
                await self._atv.remote_control.play()
            except Exception as e:
                LOG.debug("AirPlay resume error: %s", e)

    async def set_volume(self, level: float) -> None:
        if self._atv:
            try:
                # pyatv volume is typically 0.0-100.0
                await self._atv.audio.set_volume(level * 100.0)
            except Exception as e:
                LOG.debug("AirPlay set_volume error: %s", e)

    async def disconnect(self) -> None:
        if self._atv:
            try:
                self._atv.close()
            except Exception:
                pass
            self._atv = None

    def is_connected(self) -> bool:
        return self._atv is not None


def _detect_mime_type(url: str, default: str = "video/mp2t") -> str:
    """Detect MIME type from URL with improved heuristics for IPTV and audio."""
    u = url.lower()
    if ".m3u8" in u:
        return "application/x-mpegURL"
    if ".ts" in u:
        return "video/mp2t"
    if ".mp4" in u:
        return "video/mp4"
    if ".mkv" in u:
        return "video/x-matroska"
    if ".avi" in u:
        return "video/x-msvideo"
    if u.endswith((".mp3", ".m3u", ".pls")):
        return "audio/mpeg"
    if u.endswith((".aac", ".m4a")):
        return "audio/aac"
    if u.endswith((".ogg", ".oga")):
        return "audio/ogg"
    if u.endswith(".opus"):
        return "audio/opus"
    if u.endswith(".flac"):
        return "audio/flac"
    if u.endswith((".wav", ".wave")):
        return "audio/wav"

    # Try a lightweight HEAD request to infer content-type for opaque radio/stream URLs.
    # Keep it best-effort and non-fatal so casting keeps working offline.
    try:
        if url.startswith("http"):
            import urllib.request

            headers = dict(utils.HEADERS)
            headers["Accept"] = "*/*"
            req = urllib.request.Request(url, method="HEAD", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if ctype:
                    ctype = ctype.split(";")[0].strip().lower()
                    return ctype
    except Exception:
        pass

    # Heuristic for common radio/stream endpoints without extensions
    if any(token in u for token in ("/listen/", "/stream", "radio", "/live")):
        return "audio/mpeg"
    return default


# ============================================================================
# Unified Casting Manager
# ============================================================================

class CastingManager:
    """Manages multiple casting protocols and active sessions on a background loop."""
    
    def __init__(self):
        self.casters: Dict[CastProtocol, BaseCaster] = {}
        self.active_caster: Optional[BaseCaster] = None
        self.active_device: Optional[CastDevice] = None
        self._loop = None
        self._thread = None
        self._running = False
        
        # Initialize available casters
        if _HAS_CHROMECAST:
            self.casters[CastProtocol.CHROMECAST] = ChromecastCaster()
        if _HAS_UPNP:
            self.casters[CastProtocol.DLNA] = DLNACaster()
            # UPNP shares the same caster implementation
        if _HAS_AIRPLAY:
            self.casters[CastProtocol.AIRPLAY] = AirPlayCaster()

    def start(self):
        """Start the background asyncio loop."""
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="CastingManagerLoop")
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def stop(self):
        """Stop the background loop."""
        if not self._running:
            return
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)

    def dispatch(self, coro):
        """Run a coroutine on the background loop and return the result synchronously."""
        if not self._running or not self._loop:
            raise RuntimeError("CastingManager is not running. Call start() first.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def discover_all(self, timeout: float = 5.0) -> List[CastDevice]:
        """Discover devices across all supported protocols."""
        return self.dispatch(self._discover_all_async(timeout))

    async def _discover_all_async(self, timeout: float) -> List[CastDevice]:
        unique_casters = set(self.casters.values())
        results = await asyncio.gather(
            *[c.discover(timeout) for c in unique_casters],
            return_exceptions=True
        )
        
        all_devices = []
        for res in results:
            if isinstance(res, list):
                all_devices.extend(res)
        
        return sorted(all_devices, key=lambda d: d.name)

    def connect(self, device: CastDevice, credentials: Optional[str] = None) -> None:
        """Connect to a selected device."""
        self.dispatch(self._connect_async(device, credentials))

    async def _connect_async(self, device: CastDevice, credentials: Optional[str] = None) -> None:
        if self.active_caster:
            await self.active_caster.disconnect()
            self.active_caster = None
            self.active_device = None
            
        caster = self.casters.get(device.protocol)
        if not caster and device.protocol in (CastProtocol.DLNA, CastProtocol.UPNP):
            caster = self.casters.get(CastProtocol.DLNA)
            
        if not caster:
            raise CastError(f"No caster implementation for {device.protocol}")
            
        if isinstance(caster, AirPlayCaster):
            await caster.connect(device, credentials)
        else:
            await caster.connect(device)
            
        self.active_caster = caster
        self.active_device = device

    def start_pairing(self, device: CastDevice) -> object:
        """Start pairing if supported by the protocol."""
        return self.dispatch(self._start_pairing_async(device))

    async def _start_pairing_async(self, device: CastDevice) -> object:
        caster = self.casters.get(device.protocol)
        if isinstance(caster, AirPlayCaster):
            return await caster.start_pairing(device)
        raise CastError("Pairing not supported for this device type")

    def play(self, url: str, title: str = "IPTV Stream", channel: Optional[Dict[str, str]] = None, content_type: str = "audio/mpeg", start_time_seconds: Optional[float] = None) -> None:
        self.dispatch(self._play_async(url, title, channel, content_type, start_time_seconds))

    async def _play_async(self, url: str, title: str, channel: Optional[Dict[str, str]], content_type: str, start_time_seconds: Optional[float]) -> None:
        if not self.active_caster:
            raise ConnectionError("No active cast device")

        headers = channel_http_headers(channel)
        await self.active_caster.play(url, title, content_type=content_type, headers=headers, start_time_seconds=start_time_seconds)

    def stop_playback(self) -> None:
        if self.active_caster:
            self.dispatch(self.active_caster.stop())

    def pause(self) -> None:
        if self.active_caster:
            self.dispatch(self.active_caster.pause())

    def resume(self) -> None:
        if self.active_caster:
            self.dispatch(self.active_caster.resume())

    def seek(self, position_seconds: float) -> None:
        """Seek on the active cast device (seconds)."""
        if self.active_caster:
            try:
                self.dispatch(self.active_caster.seek(position_seconds))
            except Exception:
                pass

    def get_position(self) -> Optional[float]:
        """Return current playback position (seconds) from the active cast device."""
        if self.active_caster:
            try:
                return self.dispatch(self.active_caster.get_position())
            except Exception:
                return None
        return None

    def disconnect(self) -> None:
        self.dispatch(self._disconnect_async())

    async def _disconnect_async(self) -> None:
        if self.active_caster:
            try:
                await self.active_caster.stop()
            except Exception:
                pass
            await self.active_caster.disconnect()
            self.active_caster = None
            self.active_device = None

    def is_connected(self) -> bool:
        # This can be checked safely without dispatch if we trust the flag state
        # but strictly the caster state might change. Ideally we dispatch, 
        # but for UI checks it's okay to read the local prop if updated correctly.
        # However, 'active_caster' is set on the loop.
        return self.active_caster is not None and self.active_caster.is_connected()

    def is_connected_to(self, device: CastDevice) -> bool:
        """Return whether the active session is connected to ``device``."""
        active = self.active_device
        if active is None or active.unique_id != device.unique_id:
            return False
        return self.is_connected()
