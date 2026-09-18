# Vendored from Caster 0.5.23 (e293ec0) by tools/sync_caster.py.
# Verbatim copy of caster_config.py.
# Do not edit: fix it in Caster and run tools/sync_caster.py again.
# Copyright (c) serrebidev and contributors
# This file is part of Caster
# SPDX-License-Identifier: MIT
"""Caster settings: a small JSON file under %APPDATA%\\Caster.

Nothing here is required for the app to run. A missing, unreadable or
half-written settings file falls back to defaults rather than failing to
start, because losing your preferences is an annoyance and refusing to
launch is not.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading

APP_DIR_NAME = "Caster"
SETTINGS_NAME = "settings.json"

#: How many recently cast URLs to keep.
MAX_RECENT = 25

DEFAULTS: dict = {
    # Startup
    "discover_on_launch": True,
    "reselect_last_device": True,
    "last_devices": [],           # display labels, most recent first
    # Playback
    "volume": 100,
    "muted": False,
    # Capture
    "capture_quality": "balanced",   # latency | balanced | quality
    "capture_audio_device": "",      # "" = the default output's loopback
    "capture_include_mic": False,
    "capture_mic_device": "",
    "av_offset_ms": 0,               # + delays audio behind video
    # Which screen grabber ffmpeg can actually use here, and the machine
    # state that answer was true for. Probing costs seconds and the answer
    # never changes on a given box, so it is asked once and remembered.
    "screen_grabber": "",            # "ddagrab" | "gdigrab" | "" = unknown
    "screen_grabber_key": "",        # host + session the cache belongs to
    # Lists
    "recent_urls": [],
    "favourites": [],                # [{"name": ..., "url": ...}, ...]
    # Behaviour
    "global_hotkeys": True,
    "minimise_to_tray": False,
    "sleep_timer_minutes": 0,        # 0 = off
    "auto_reconnect": True,
    "speak_status": True,            # talk to NVDA directly when available
    # Sonos
    "sonos_seed_ips": [],            # for speakers on another subnet or VLAN
    "sonos_resync_hours": 2,         # 0 = never
    # MusicCast (Yamaha). A receiver answers this alongside whatever carries
    # the audio, so these apply to it however it is being cast to.
    "musiccast_power_on": True,       # wake a receiver in network standby
    "musiccast_restore_input": True,  # put it back on its previous input
    "musiccast_link_control": "",     # "" = leave alone | speed | standard
                                      # | stability
    "musiccast_link_audio_delay": "",  # "" = leave alone | audio_sync
                                       # | balanced | lip_sync
    # Kodi
    "kodi_username": "",
    "kodi_password": "",
}


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def settings_path() -> str:
    return os.path.join(config_dir(), SETTINGS_NAME)


def _same_type(value, default) -> bool:
    """Whether a stored value may stand in for this default.

    isinstance() alone is too permissive here, because in Python a bool IS an
    int: a JSON `true` in a numeric field passed the guard and became 1, so a
    hand-edited `"volume": true` was near-silence rather than a rejected
    value. Booleans and numbers are kept strictly apart.
    """
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


class Settings:
    """Dict-like settings with an atomic save.

    Saves are frequent and small (a volume nudge, a URL added to the recent
    list), so they are written to a temp file and moved into place. A power
    cut mid-write then leaves the previous settings intact rather than a
    truncated file that would read as "no settings at all".
    """

    def __init__(self, path: str = "") -> None:
        self.path = path or settings_path()
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self.load()

    # ---- persistence ----

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except (OSError, ValueError):
            return                       # first run, or unreadable: defaults
        if not isinstance(stored, dict):
            return
        with self._lock:
            # Merge rather than replace, so a settings file written by an
            # older version still gets every key added since.
            for key, value in stored.items():
                if key in DEFAULTS and _same_type(value, DEFAULTS[key]):
                    self._data[key] = value

    def save(self) -> None:
        with self._lock:
            snapshot = dict(self._data)
        # Beside the file being written, not in the default directory. Using
        # config_dir() unconditionally meant the path= argument only half
        # worked: %APPDATA%\Caster was created even for a caller who asked for
        # somewhere else, and os.replace across two volumes raises OSError --
        # swallowed below, so those settings would silently never persist.
        folder = os.path.dirname(self.path) or config_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=folder, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(snapshot, handle, indent=2, ensure_ascii=False)
                os.replace(temp, self.path)
            except BaseException:
                try:
                    os.unlink(temp)
                except OSError:
                    pass
                raise
        except OSError:
            pass                         # read-only profile: run without saving

    # ---- access ----

    def __getitem__(self, key: str):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default if default is not None
                                  else DEFAULTS.get(key))

    def __setitem__(self, key: str, value) -> None:
        self.set(key, value)

    def set(self, key: str, value, save: bool = True) -> None:
        with self._lock:
            if self._data.get(key) == value:
                return                   # no churn for a no-op write
            self._data[key] = value
        if save:
            self.save()

    def update(self, **pairs) -> None:
        changed = False
        with self._lock:
            for key, value in pairs.items():
                if self._data.get(key) != value:
                    self._data[key] = value
                    changed = True
        if changed:
            self.save()

    # ---- lists ----

    def add_recent_url(self, url: str) -> None:
        url = (url or "").strip()
        if not url:
            return
        with self._lock:
            recent = [u for u in self._data.get("recent_urls", []) if u != url]
            recent.insert(0, url)
            self._data["recent_urls"] = recent[:MAX_RECENT]
        self.save()

    def clear_recent_urls(self) -> None:
        self.set("recent_urls", [])

    def add_favourite(self, name: str, url: str) -> None:
        name, url = (name or "").strip(), (url or "").strip()
        if not name or not url:
            return
        with self._lock:
            favourites = [f for f in self._data.get("favourites", [])
                          if f.get("name") != name]
            favourites.append({"name": name, "url": url})
            favourites.sort(key=lambda f: f.get("name", "").lower())
            self._data["favourites"] = favourites
        self.save()

    def remove_favourite(self, name: str) -> None:
        with self._lock:
            self._data["favourites"] = [
                f for f in self._data.get("favourites", [])
                if f.get("name") != name]
        self.save()

    def note_device(self, label: str) -> None:
        """Remember a device as the most recently used one."""
        if not label:
            return
        with self._lock:
            devices = [d for d in self._data.get("last_devices", [])
                       if d != label]
            devices.insert(0, label)
            self._data["last_devices"] = devices[:10]
        self.save()


#: Capture presets. Latency is not a single knob -- frame rate, bitrate and
#: resolution all trade against it -- so they move together behind one choice.
#: Capture and relay tuning per quality choice.
#:
#: Playlist history and startup buffering are different. Cast starts near
#: the live edge unless given a position, regardless of retained history.
#: `hls_start_seconds` supplies a modest initial cushion, and Caster loads
#: its own live relay from the beginning of the available seekable window.
#: `hls_trail_seconds` retains the longer window for jitter and recovery.
#: Keep hls_prime at three: extra buffering is requested in seconds, never
#: in an assumed number of source GOPs. Long-GOP promotion happens before
#: waiting for the startup cushion, so eight 7.5s GOPs cannot cost a minute.
QUALITY_PRESETS = {
    "latency": {"fps": 30, "bitrate": "3M", "max_width": 1280,
                "max_height": 720, "keyframe_seconds": 0.4,
                "hls_time": 2, "hls_prime": 3, "hls_trail": 6, "hls_trail_seconds": 25,
                "hls_start_seconds": 12,
                "label": "Lowest delay (720p)"},
    "balanced": {"fps": 30, "bitrate": "6M", "max_width": 1920,
                 "max_height": 1080, "keyframe_seconds": 0.5,
                 "hls_time": 2, "hls_prime": 3, "hls_trail": 8, "hls_trail_seconds": 45,
                 "hls_start_seconds": 16,
                 "label": "Balanced (1080p)"},
    "quality": {"fps": 60, "bitrate": "12M", "max_width": 1920,
                "max_height": 1080, "keyframe_seconds": 1.0,
                "hls_time": 2, "hls_prime": 3, "hls_trail": 12, "hls_trail_seconds": 60,
                "hls_start_seconds": 20,
                "label": "Best picture (1080p60)"},
}


def preset(name: str) -> dict:
    return QUALITY_PRESETS.get(name, QUALITY_PRESETS["balanced"])
