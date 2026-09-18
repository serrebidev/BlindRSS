# Vendored from Caster 0.5.23 (e293ec0) by tools/sync_caster.py.
# Verbatim copy of caster_devices.py.
# Do not edit: fix it in Caster and run tools/sync_caster.py again.
# Copyright (c) serrebidev and contributors
# This file is part of Caster
# SPDX-License-Identifier: MIT
"""Receiver protocols beyond Chromecast, AirPlay and plain UPnP/DLNA.

Sonos, Roku and Kodi each need their own discovery and their own way of
being told to play a URL. Kept out of caster.py so the GUI is not carrying
four protocol clients, and free of caster imports so there is no cycle.

A note on what is deliberately absent. Miracast is a Windows display
feature rather than a network protocol this app could speak; Spotify
Connect needs a Premium account and a proprietary client; Bluetooth is not
casting. DLNA already reaches most smart TVs (Samsung, LG, Sony), Xbox and
almost every AV receiver, so those are not separate integrations.
"""

from __future__ import annotations

import concurrent.futures
import concurrent.futures as _futures
import json
import re
import select
import socket
import threading
import time
import urllib.parse
import urllib.request as _urlreq
import uuid

from caster_extras import mdns_host, ssdp_sockets

# ---------------------------------------------------------------------------
# Sonos
# ---------------------------------------------------------------------------
#
# Sonos speaks UPnP AVTransport, but is not reachable through ordinary DLNA
# discovery: it answers SSDP as a ZonePlayer, not a MediaRenderer. It also
# advertises AirPlay 2, which is a trap -- that path needs MFi hardware
# authentication no Python client can do, so an AirPlay cast to a Sonos
# fails with the speaker refusing the audio port. Both of those are why
# Sonos gets its own discovery here and is filtered out of the AirPlay and
# UPnP lists (see looks_like_sonos).

_SONOS_TIMEOUT = 4.0        # SoCo defaults to 20s; one asleep speaker then
                            # stalls every code path that touches it.
_soco_lock = threading.Lock()
_soco_ready = False


def _soco():
    """The soco module, configured, or None when it is not installed.

    Imported lazily: it is only needed if there is a Sonos on the network,
    and importing it costs a noticeable fraction of a second at startup.
    """
    global _soco_ready
    try:
        import soco
        import soco.config as soco_config
    except ImportError:
        return None
    with _soco_lock:
        if not _soco_ready:
            soco_config.REQUEST_TIMEOUT = _SONOS_TIMEOUT
            _soco_ready = True
    return soco


def sonos_available() -> bool:
    return _soco() is not None


def sonos_discover(timeout: int = 5, seed_ips: list | None = None) -> list:
    """Sonos zones as [(name, ip), ...].

    Seed addresses are for a household on a subnet or VLAN that multicast
    cannot reach: touching any one speaker yields the whole household
    through its zone group topology, so one address is enough per system.
    """
    soco = _soco()
    if soco is None:
        return []
    seeds = [str(ip).strip() for ip in (seed_ips or []) if str(ip).strip()]

    def from_seed(ip):
        try:
            device = soco.SoCo(ip)
            _ = device.player_name          # warm the topology cache
            return device.visible_zones or {device}
        except Exception:
            return set()

    zones = set()
    # The multicast sweep and each seed are independent waits, and a seed
    # that is switched off costs the full request timeout. Overlapping them
    # keeps a household on another subnet from adding seconds per address.
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=1 + len(seeds), thread_name_prefix="sonos") as pool:
        sweep = pool.submit(lambda: soco.discover(timeout=timeout) or set())
        seeded = [pool.submit(from_seed, ip) for ip in seeds]
        try:
            zones |= sweep.result() or set()
        except Exception:
            pass
        for fut in seeded:
            zones |= fut.result()
    found = []
    for zone in zones:
        try:
            found.append((zone.player_name, zone.ip_address))
        except Exception:
            pass
    return sorted(set(found))


def _sonos_device(ip: str):
    soco = _soco()
    if soco is None:
        raise RuntimeError("Sonos support needs the 'soco' package")
    return soco.SoCo(ip)


def _sonos_coordinator(device):
    """The zone that actually accepts transport commands for this group.

    Sonos rejects play and stop sent to a group member that is not the
    coordinator. Grouped speakers all replicate the coordinator anyway, so
    routing through it means acting on any member controls the whole group,
    which is what the Sonos app itself shows as one unit.
    """
    try:
        group = device.group
        if group is not None and group.coordinator is not None:
            return group.coordinator
    except Exception:
        pass
    return device


def sonos_didl(title: str, url: str, mime: str) -> str:
    """DIDL-Lite for a live stream from this machine.

    Tagged as a plain music track on purpose. SoCo's play_uri shortcut
    labels whatever it builds as a TuneIn broadcast, complete with a
    third-party service id -- which tells the speaker this is internet
    radio rather than audio from a device on the LAN, and makes Sonos
    withhold its tone controls while it plays.
    """
    from xml.sax.saxutils import escape
    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="1" parentID="0" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        f'<res protocolInfo="http-get:*:{escape(mime)}:*">{escape(url)}</res>'
        "</item></DIDL-Lite>"
    )


def sonos_play(ip: str, url: str, title: str = "Caster",
               mime: str = "audio/wav") -> None:
    zone = _sonos_coordinator(_sonos_device(ip))
    zone.avTransport.SetAVTransportURI([
        ("InstanceID", 0),
        ("CurrentURI", url),
        ("CurrentURIMetaData", sonos_didl(title, url, mime)),
    ])
    zone.avTransport.Play([("InstanceID", 0), ("Speed", 1)])


def sonos_stop(ip: str) -> None:
    try:
        _sonos_coordinator(_sonos_device(ip)).stop()
    except Exception:
        pass


def sonos_set_volume(ip: str, level: int) -> None:
    try:
        _sonos_device(ip).volume = max(0, min(100, int(level)))
    except Exception:
        pass


def sonos_group(ips: list) -> str:
    """Join several speakers into one group so they play in sync.

    Returns the coordinator's address, which is the only one that should
    then be told to play. Sending the same stream to each speaker
    separately would leave them audibly out of step with each other.
    """
    if not ips:
        return ""
    coordinator_ip, followers = ips[0], ips[1:]
    coordinator = _sonos_device(coordinator_ip)
    for ip in followers:
        try:
            _sonos_device(ip).unjoin()
        except Exception:
            pass
    if followers:
        time.sleep(0.5)
    for ip in followers:
        try:
            _sonos_device(ip).join(coordinator)
        except Exception:
            pass
    if followers:
        time.sleep(0.5)
    return coordinator_ip


def looks_like_sonos(name: str, extra: str = "") -> bool:
    """Whether a discovered AirPlay or UPnP entry is really a Sonos.

    Sonos answers both, and neither answer is usable: the AirPlay one needs
    hardware authentication, and the UPnP one is a ZonePlayer that wants
    Sonos' own transport handling. Hiding those duplicates also stops one
    speaker appearing three times in the device list.
    """
    blob = f"{name} {extra}".lower()
    return "sonos" in blob or "rincon" in blob


# ---------------------------------------------------------------------------
# Roku (External Control Protocol)
# ---------------------------------------------------------------------------
#
# Roku has no general "play this URL" API. What it does have is the Roku
# Media Player channel, which can be launched with a URL as a parameter --
# the same mechanism the "Play on Roku" feature uses.

ROKU_MEDIA_PLAYER = "2213"

#: Roku Media Player plays HLS, MP4 and MKV. It has no MPEG-TS support, so a
#: live capture has to reach it as MP4.
ROKU_VIDEO_FORMATS = {"video/mp4": "mp4", "application/vnd.apple.mpegurl": "hls"}
ROKU_AUDIO_FORMATS = {"audio/wav": "wav", "audio/mpeg": "mp3",
                      "audio/aac": "aac", "audio/flac": "flac"}


def roku_discover(timeout: int = 4) -> list:
    """Rokus as [(name, base_url), ...], via SSDP."""
    bases = []
    for location in _ssdp_search("roku:ecp", timeout):
        # The SSDP LOCATION points at the device description; ECP lives at
        # the server root.
        parts = urllib.parse.urlsplit(location.rstrip("/"))
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in bases:
            bases.append(base)
    if not bases:
        return []
    # Asking each Roku its name is a separate HTTP round trip that can time
    # out; done one at a time, a household of Rokus costs several seconds
    # after the SSDP window has already closed.
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, len(bases)),
            thread_name_prefix="roku-name") as pool:
        names = list(pool.map(_roku_name, bases))
    return sorted({(name, base) for name, base in zip(names, bases) if name})


def _roku_name(base: str) -> str:
    try:
        with _urlreq.urlopen(f"{base}/query/device-info", timeout=4) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception:
        return ""
    for tag in ("friendly-device-name", "user-device-name", "default-device-name",
                "model-name"):
        m = re.search(rf"<{tag}>([^<]+)</{tag}>", body)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def roku_play(base: str, url: str, mime: str = "video/mp4",
              title: str = "Caster") -> None:
    audio = mime.startswith("audio/")
    params = {"t": "a" if audio else "v", "u": url}
    if audio:
        params["audioName"] = title
        params["audioFormat"] = ROKU_AUDIO_FORMATS.get(mime, "mp3")
    else:
        params["videoName"] = title
        params["videoFormat"] = ROKU_VIDEO_FORMATS.get(mime, "mp4")
    target = f"{base}/launch/{ROKU_MEDIA_PLAYER}?{urllib.parse.urlencode(params)}"
    _post(target)


def roku_stop(base: str) -> None:
    # There is no "stop" in ECP; going Home leaves the media player.
    try:
        _post(f"{base}/keypress/Home")
    except Exception:
        pass


def roku_key(base: str, key: str) -> None:
    """Send one ECP keypress (Play, VolumeUp, VolumeDown, VolumeMute, ...)."""
    _post(f"{base}/keypress/{key}")


def _post(url: str, timeout: int = 6) -> bytes:
    req = _urlreq.Request(url, data=b"", method="POST")
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------------------
# Kodi (JSON-RPC)
# ---------------------------------------------------------------------------
#
# Kodi plays essentially anything ffmpeg can, MPEG-TS included, which makes
# it the most forgiving target here for a live capture.

KODI_SERVICE = "_xbmc-jsonrpc-h._tcp.local."


def kodi_discover(timeout: int = 4, zc=None) -> list:
    """Kodi instances as [(name, base_url), ...], over mDNS.

    Pass ``zc`` to browse on a Zeroconf someone else already owns -- two
    instances in one process each bind port 5353 and send the same queries
    twice for nothing. A borrowed instance is left open for its owner.
    """
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return []
    hits: list = []
    seen: set = set()
    lock = threading.Lock()

    class _Listener:
        def add_service(self, zc_, type_, name):
            with lock:
                if name in seen:
                    return
                seen.add(name)
            hits.append((type_, name))

        def update_service(self, zc_, type_, name):
            pass

        def remove_service(self, zc_, type_, name):
            pass

    borrowed = zc is not None
    zc = zc or Zeroconf()
    browser = None
    try:
        browser = ServiceBrowser(zc, KODI_SERVICE, _Listener())
        time.sleep(timeout)

        def resolve(hit):
            type_, name = hit
            try:
                info = zc.get_service_info(type_, name, 3000)
            except Exception:
                return None
            if not info or not info.addresses:
                return None
            host = mdns_host(info)
            if not host:
                return None
            label = name.split(".")[0] or host
            netloc = f"[{host}]" if ":" in host else host
            return (label, f"http://{netloc}:{info.port or 8080}")

        pending = list(hits)
        if not pending:
            return []
        # Each resolve waits up to three seconds on its own; in a row that
        # is the whole browse window over again per instance.
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(8, len(pending)),
                thread_name_prefix="kodi-resolve") as pool:
            found = [r for r in pool.map(resolve, pending) if r]
    finally:
        if browser is not None:
            try:
                browser.cancel()
            except Exception:
                pass
        if not borrowed:
            try:
                zc.close()
            except Exception:
                pass
    return sorted(set(found))


def _kodi_rpc(base: str, method: str, params: dict | None = None,
              auth: tuple = ("", ""), timeout: int = 8):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                          "params": params or {}}).encode()
    req = _urlreq.Request(f"{base}/jsonrpc", data=payload, method="POST",
                          headers={"Content-Type": "application/json"})
    user, password = auth
    if user:
        import base64
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with _urlreq.urlopen(req, timeout=timeout) as r:
        reply = json.loads(r.read().decode("utf-8", "replace"))
    # JSON-RPC reports failure inside an HTTP 200. Returned as a result, a
    # refused Player.Open was announced as "Playing".
    if isinstance(reply, dict) and reply.get("error"):
        error = reply["error"]
        detail = error.get("message") if isinstance(error, dict) else ""
        raise RuntimeError(f"Kodi refused {method}: {detail or error}")
    return reply


def kodi_play(base: str, url: str, auth: tuple = ("", "")) -> None:
    _kodi_rpc(base, "Player.Open", {"item": {"file": url}}, auth)


def kodi_stop(base: str, auth: tuple = ("", "")) -> None:
    try:
        active = _kodi_rpc(base, "Player.GetActivePlayers", {}, auth)
        for player in active.get("result", []):
            _kodi_rpc(base, "Player.Stop",
                      {"playerid": player.get("playerid", 1)}, auth)
    except Exception:
        pass


def kodi_pause(base: str, auth: tuple = ("", "")) -> None:
    active = _kodi_rpc(base, "Player.GetActivePlayers", {}, auth)
    for player in active.get("result", []):
        _kodi_rpc(base, "Player.PlayPause",
                  {"playerid": player.get("playerid", 1)}, auth)


def kodi_set_volume(base: str, level: int, auth: tuple = ("", "")) -> None:
    try:
        _kodi_rpc(base, "Application.SetVolume",
                  {"volume": max(0, min(100, int(level)))}, auth)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SSDP
# ---------------------------------------------------------------------------

def _ssdp_search(search_target: str, timeout: int = 4) -> list:
    """M-SEARCH for one ST; returns the LOCATION header of each responder."""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {max(1, timeout - 1)}\r\n"
        f"ST: {search_target}\r\n"
        "\r\n"
    ).encode()
    socks = ssdp_sockets()
    if not socks:
        return []
    locations = []
    try:
        # Repeated across the window for the same reason as the UPnP search in
        # caster_extras: SSDP is lossy multicast, and one lost reply is one
        # device missing from the list.
        deadline = time.monotonic() + timeout
        next_search, searches = 0.0, 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_search and searches < 3:
                for sock in socks:
                    try:
                        sock.sendto(msg, ("239.255.255.250", 1900))
                    except OSError:
                        pass
                searches += 1
                next_search = now + timeout / 4
            try:
                ready, _, _ = select.select(
                    socks, [], [], min(0.5, max(0.0, deadline - now)))
            except (OSError, ValueError):
                break
            if not ready:
                continue
            for sock in ready:
                try:
                    data, _ = sock.recvfrom(65536)
                except OSError:
                    continue
                for line in data.decode("utf-8", "replace").splitlines():
                    if line.lower().startswith("location:"):
                        location = line.split(":", 1)[1].strip()
                        if location and location not in locations:
                            locations.append(location)
                        break
    finally:
        for sock in socks:
            sock.close()
    return locations


# ---------------------------------------------------------------------------
# Yamaha MusicCast (YamahaExtendedControl, "YXC")
# ---------------------------------------------------------------------------
#
# YXC is a plain HTTP/JSON control channel on port 80, unauthenticated, sitting
# alongside whatever the device uses to actually carry audio. It is not a
# transport: a MusicCast receiver still takes its audio over AirPlay or DLNA.
# What YXC adds is everything around the stream -- power, the input selector,
# real volume in dB, zones and multi-room grouping -- which those transports
# either cannot express or express worse.

#: Cache of /system/getFeatures per host. It is a big, slow, static document,
#: and the answer cannot change while the unit is running.
_yxc_features_cache: dict = {}
_yxc_cache_lock = threading.Lock()

#: Anything longer than this and the receiver is asleep or gone; the caller is
#: on a play path and must not be held up by either.
YXC_TIMEOUT = 4.0


def yxc_url(host: str, path: str) -> str:
    return f"http://{host}/YamahaExtendedControl/v1/{path}"


def yxc_request(host: str, path: str, timeout: float = YXC_TIMEOUT) -> dict:
    """One YXC call. Raises on transport failure or a non-zero response code."""
    req = _urlreq.Request(yxc_url(host, path),
                          headers={"User-Agent": "caster/1.0"})
    with _urlreq.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    code = data.get("response_code")
    if code not in (0, None):
        raise RuntimeError(f"MusicCast error {code} from {path}")
    return data


def yxc_try(host: str, path: str, timeout: float = YXC_TIMEOUT) -> dict:
    """yxc_request, but a failure is an empty answer rather than an exception.

    Every caller of this is decorating a cast that will work regardless --
    switching an input, nudging a volume -- so a receiver that does not answer
    should cost nothing but the feature.
    """
    try:
        return yxc_request(host, path, timeout)
    except Exception:
        return {}


def yxc_available(host: str) -> bool:
    """True if the device speaks MusicCast (YamahaExtendedControl)."""
    return bool(yxc_try(host, "main/getStatus", timeout=2.0))


def yxc_features(host: str, refresh: bool = False) -> dict:
    with _yxc_cache_lock:
        if not refresh and host in _yxc_features_cache:
            return _yxc_features_cache[host]
    data = yxc_try(host, "system/getFeatures", timeout=8.0)
    # Only a real answer is static. Caching the empty reply of a receiver
    # that was asleep or busy disabled volume, mute, zones and input prep
    # for that unit until Caster was restarted.
    if data:
        with _yxc_cache_lock:
            _yxc_features_cache[host] = data
    return data


def yxc_zones(host: str) -> list:
    """Zone ids this unit has, main first. Empty if it is not MusicCast."""
    return [z.get("id", "") for z in yxc_features(host).get("zone", [])
            if z.get("id")]


def yxc_zone_features(host: str, zone: str = "main") -> dict:
    for z in yxc_features(host).get("zone", []):
        if z.get("id") == zone:
            return z
    return {}


def yxc_can(host: str, func: str, zone: str = "main") -> bool:
    """Whether a zone advertises a function. Everything optional is gated on
    this rather than on a model name: the unit already publishes the list."""
    return func in yxc_zone_features(host, zone).get("func_list", [])


def yxc_status(host: str, zone: str = "main") -> dict:
    return yxc_try(host, f"{zone}/getStatus")


def yxc_max_volume(host: str, zone: str = "main") -> int:
    """Volume steps this zone has. 0-161 on an AVENTAGE-era receiver, and
    emphatically not 0-100 -- treating it as a percentage throws away most of
    the resolution and lands between real steps."""
    for r in yxc_zone_features(host, zone).get("range_step", []):
        if r.get("id") == "volume":
            return int(r.get("max", 100))
    return int(yxc_status(host, zone).get("max_volume") or 100)


def yxc_set_power(host: str, on: bool = True, zone: str = "main") -> bool:
    """Wake the zone if it is asleep. True if it is now on.

    A receiver in network standby accepts a pushed stream and plays it to a
    powered-down amplifier, which is indistinguishable from the cast having
    failed.
    """
    status = yxc_status(host, zone)
    if not status:
        return False
    if status.get("power") == "on":
        return True
    ok = bool(yxc_try(host, f"{zone}/setPower?power=on"))
    if ok:
        # The amplifier stage needs a moment before it will pass audio; a
        # stream started inside that window loses its first second.
        time.sleep(1.5)
    return ok


def yxc_prepare_input(host: str, yxc_input: str, zone: str = "main") -> None:
    """The documented step before changing input.

    MusicCast's own controller calls this immediately before selecting an
    input, and the spec makes it a requirement whenever the unit lists
    prepare_input_change. It lets the receiver spin up whatever the input
    needs -- the network client, in our case -- instead of being asked to
    switch and stream in the same breath.
    """
    if yxc_can(host, "prepare_input_change", zone):
        yxc_try(host, f"{zone}/prepareInputChange?input={yxc_input}")


def yxc_set_input(host: str, yxc_input: str = "server",
                  zone: str = "main") -> bool:
    """Switch a zone's input, preparing it first."""
    yxc_prepare_input(host, yxc_input, zone)
    return bool(yxc_try(host, f"{zone}/setInput?input={yxc_input}"))


def yxc_current_input(host: str, zone: str = "main") -> str:
    return str(yxc_status(host, zone).get("input") or "")


def yxc_set_volume(host: str, percent: int, zone: str = "main") -> bool:
    """Set volume from a 0-100 slider onto the zone's own scale."""
    if not yxc_can(host, "volume", zone):
        return False
    top = yxc_max_volume(host, zone)
    value = max(0, min(top, round(max(0, min(100, int(percent))) * top / 100)))
    return bool(yxc_try(host, f"{zone}/setVolume?volume={value}"))


def yxc_get_volume(host: str, zone: str = "main") -> int:
    """Current volume as 0-100, or -1 when it cannot be read."""
    status = yxc_status(host, zone)
    if not status or "volume" not in status:
        return -1
    top = int(status.get("max_volume") or yxc_max_volume(host, zone) or 100)
    return max(0, min(100, round(int(status["volume"]) * 100 / max(1, top))))


def yxc_volume_db(host: str, zone: str = "main") -> str:
    """The volume the receiver's own display shows, as text, or "".

    Worth speaking instead of a percentage: it is the number on the unit, so
    it matches what the remote and the front panel say.
    """
    actual = yxc_status(host, zone).get("actual_volume") or {}
    if "value" not in actual:
        return ""
    unit = actual.get("unit") or ""
    return f"{actual['value']}{(' ' + unit) if unit else ''}".strip()


def yxc_set_mute(host: str, muted: bool, zone: str = "main") -> bool:
    if not yxc_can(host, "mute", zone):
        return False
    return bool(yxc_try(
        host, f"{zone}/setMute?enable={'true' if muted else 'false'}"))


#: Link Control trades buffer depth against tolerance for a bad network, and
#: Link Audio Delay trades sync against latency. Both are per zone, both take
#: their values from getFeatures, and Link Audio Delay is documented as
#: ignored while Link Control is on Stability Boost.
LINK_CONTROLS = ("speed", "standard", "stability")
LINK_AUDIO_DELAYS = ("audio_sync", "balanced", "lip_sync")


def yxc_set_link_control(host: str, control: str, zone: str = "main") -> bool:
    if control not in LINK_CONTROLS or not yxc_can(host, "link_control", zone):
        return False
    return bool(yxc_try(host, f"{zone}/setLinkControl?control={control}"))


def yxc_set_link_audio_delay(host: str, delay: str,
                             zone: str = "main") -> bool:
    if delay not in LINK_AUDIO_DELAYS or not yxc_can(host, "link_audio_delay",
                                                     zone):
        return False
    return bool(yxc_try(host, f"{zone}/setLinkAudioDelay?delay={delay}"))


def musiccast_discover_at(hosts: list) -> dict:
    """{host: {"model", "name", "zones"}} for whichever of `hosts` answer YXC.

    Deliberately takes a host list rather than sweeping: every address worth
    asking has already answered SSDP or mDNS, and a 254-address sweep to find
    a receiver the other scans already found would be the slowest thing in
    discovery.
    """
    hosts = [h for h in dict.fromkeys(hosts) if h]
    if not hosts:
        return {}

    def one(host: str):
        info = yxc_try(host, "system/getDeviceInfo", timeout=2.0)
        if not info.get("model_name"):
            return host, None
        net = yxc_try(host, "system/getNetworkStatus", timeout=2.0)
        return host, {"model": info.get("model_name", ""),
                      "name": net.get("network_name", ""),
                      "zones": yxc_zones(host)}

    out = {}
    with _futures.ThreadPoolExecutor(
            max_workers=min(12, len(hosts)),
            thread_name_prefix="musiccast") as pool:
        for host, info in pool.map(one, hosts):
            if info:
                out[host] = info
    return out


def musiccast_group(hosts: list) -> str:
    """Link several MusicCast units so they play one stream in sync.

    Returns the server's address, which is the only one that should then be
    given something to play. Streaming to each unit independently leaves them
    audibly out of step, exactly as it does with Sonos.

    Only main can serve on the units seen so far -- `server_zone_list` says
    so -- so that is what is asked for.
    """
    hosts = [h for h in dict.fromkeys(hosts) if h]
    if len(hosts) < 2:
        return hosts[0] if hosts else ""
    server, clients = hosts[0], hosts[1:]
    info = yxc_try(server, "dist/getDistributionInfo")
    group_id = str(info.get("group_id") or "")
    if not group_id or set(group_id) == {"0"}:
        group_id = uuid.uuid4().hex
    for client in clients:
        yxc_try(client, f"dist/setClientInfo?group_id={group_id}"
                        f"&zone=main&type=add&client_list={server}")
    yxc_try(server, f"dist/setServerInfo?group_id={group_id}&zone=main"
                    f"&type=add&client_list={','.join(clients)}")
    yxc_try(server, "dist/startDistribution?num=0")
    return server


def musiccast_ungroup(hosts: list) -> None:
    """Break any link these units are in, so each is standalone again."""
    for host in dict.fromkeys(h for h in hosts if h):
        yxc_try(host, "dist/setServerInfo?group_id=&zone=main&type=remove")
        yxc_try(host, "dist/setClientInfo?group_id=")
