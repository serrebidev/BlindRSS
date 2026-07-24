# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Shared libVLC instance, created once and warmed on a background thread.

libVLC instance creation scans and loads every plugin DLL (BlindRSS passes
--no-plugins-cache, so there is no cache to shortcut the scan). On frozen
Windows builds with a bundled VLC this takes multiple seconds, and doing it on
the wx main thread froze the whole app whenever playback started without a
live player window: the first play of a session, and every play after the
player window was closed (closing used to release the instance). Keeping one
instance for the process lifetime and creating it off-thread keeps the UI
responsive while audio is being prepared.

``import vlc`` stays inside the creation path so importing this module never
loads libVLC.
"""

from __future__ import annotations

import logging
import sys
import threading

from core.vlc_options import build_vlc_instance_args

log = logging.getLogger(__name__)

_lock = threading.Lock()
_done = threading.Event()
_instance = None
_creating = False


def _build_args(config_manager) -> tuple:
    try:
        cache_ms = int(config_manager.get("vlc_network_caching_ms", 500))
    except Exception:
        cache_ms = 500
    if cache_ms < 0:
        cache_ms = 0
    file_cache_ms = max(500, cache_ms)
    try:
        startup_volume = max(0, min(100, int(config_manager.get("volume", 100))))
    except Exception:
        startup_volume = 100
    args = [
        "--no-video",
        "--input-fast-seek",
    ]
    # The audio-output selection and volume seeding below are Windows-only
    # module options (mmdevice/directx plugins). libvlc_new() FAILS (returns
    # NULL) when handed an option no loaded plugin registers, so passing these
    # on macOS/Linux — where those plugins do not exist — made instance
    # creation fail outright and playback report "VLC is not initialized".
    if sys.platform == "win32":
        args += [
            # WASAPI, not directsound: with --aout=directsound every set_rate()
            # (playback-speed change) drained/rebuilt the output, silencing audio
            # for 0.2-3s per step (measured via session-peak metering; mmdevice
            # measured gapless). mmdevice is also what apply_preferred_soundcard()
            # already switches to for endpoint selection.
            "--aout=mmdevice",
            # libvlc drops audio_set_volume until the audio output exists,
            # and the output is only created once the stream actually
            # produces audio. Seed the output modules' startup volume so
            # the very first audible sample is already at the configured
            # level instead of VLC's own default.
            f"--directx-volume={startup_volume / 100.0:.4f}",
            f"--mmdevice-volume={startup_volume / 100.0:.4f}",
        ]
    args += [
        f"--network-caching={cache_ms}",
        f"--file-caching={file_cache_ms}",
        "--http-reconnect",
    ]
    return build_vlc_instance_args(*args)


def _create(config_manager) -> None:
    global _instance, _creating
    inst = None
    try:
        import vlc

        inst = vlc.Instance(*_build_args(config_manager))
        if inst is None:
            # libvlc_new() returns NULL when any startup option is unknown to
            # the loaded plugin set (platform-specific option landmine). Retry
            # with the minimal safe set so playback still works.
            log.error(
                "libVLC rejected the configured startup options; retrying with safe defaults"
            )
            inst = vlc.Instance(*build_vlc_instance_args("--no-video"))
        if inst is None:
            raise RuntimeError("libVLC returned no instance (is VLC installed?)")
    except Exception:
        log.exception("Failed to create shared VLC instance")
        inst = None
    with _lock:
        _instance = inst
        _creating = False
    _done.set()


def warm_async(config_manager) -> None:
    """Start creating the shared instance in the background (idempotent)."""
    global _creating
    with _lock:
        if _instance is not None or _creating:
            return
        _creating = True
        _done.clear()
    threading.Thread(
        target=_create,
        args=(config_manager,),
        daemon=True,
        name="VLCInstanceWarmup",
    ).start()


def get_shared(config_manager, wait_s: float | None = None):
    """Return the shared vlc.Instance, or None if (still) unavailable.

    wait_s=0 never blocks: it kicks off background creation when needed and
    returns None until that finishes. wait_s=None blocks until creation
    finishes (only call that off the UI thread, or when the instance is known
    to exist). A previous failure is retried on the next call.
    """
    with _lock:
        if _instance is not None:
            return _instance
        creating = _creating
    if not creating:
        warm_async(config_manager)
    if wait_s is not None and wait_s <= 0:
        return None
    _done.wait(timeout=wait_s)
    with _lock:
        return _instance


def reset(config_manager):
    """Drop the current instance and synchronously create a fresh one.

    Only for rare VLC error-recovery paths (e.g. set_media/pause raising
    OSError), where the old instance itself may be broken.
    """
    global _instance, _creating
    with _lock:
        in_flight = _creating
        old = None
        if not in_flight:
            old = _instance
            _instance = None
            _creating = True
            _done.clear()
    if in_flight:
        _done.wait()
        with _lock:
            return _instance
    if old is not None:
        try:
            old.release()
        except Exception:
            pass
    _create(config_manager)
    with _lock:
        return _instance


def release_shared() -> None:
    """Release the shared instance (app shutdown only)."""
    global _instance
    with _lock:
        inst = _instance
        _instance = None
    if inst is not None:
        try:
            inst.release()
        except Exception:
            pass
