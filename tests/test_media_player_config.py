# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core.config import DEFAULT_CONFIG
from core.vlc_options import build_vlc_instance_args


def test_default_preferred_soundcard_is_system_default():
    assert DEFAULT_CONFIG.get("preferred_soundcard", None) == ""


class _Cfg:
    def get(self, key, default=None):
        return default


def test_shared_instance_uses_wasapi_not_directsound(monkeypatch):
    """set_rate() on the directsound aout drained/rebuilt the output, silencing
    audio for 0.2-3s on every playback-speed step; mmdevice measured gapless
    for small steps. Keep the shared instance on WASAPI."""
    import sys

    from core import vlc_instance

    monkeypatch.setattr(sys, "platform", "win32")
    args = vlc_instance._build_args(_Cfg())
    assert "--aout=mmdevice" in args
    assert any(a.startswith("--directx-volume=") for a in args)
    assert any(a.startswith("--mmdevice-volume=") for a in args)
    assert not any(a.startswith("--aout=directsound") for a in args)


def test_shared_instance_omits_windows_only_options_off_windows(monkeypatch):
    """libvlc_new() returns NULL for options no loaded plugin registers, so the
    Windows-only mmdevice/directx options must never reach macOS/Linux — they
    made every playback attempt fail with "VLC is not initialized"."""
    import sys

    from core import vlc_instance

    for platform in ("darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        args = vlc_instance._build_args(_Cfg())
        assert not any("mmdevice" in a for a in args), platform
        assert not any("directx" in a for a in args), platform
        # The cross-platform core options must survive the gating.
        assert "--no-video" in args
        assert "--http-reconnect" in args
        assert any(a.startswith("--network-caching=") for a in args)


def test_vlc_instance_args_disable_plugin_cache():
    args = build_vlc_instance_args("--no-video", "--no-video", "--aout=directsound")

    assert args[0] == "--no-plugins-cache"
    assert args.count("--no-plugins-cache") == 1
    assert args.count("--no-video") == 1
    assert "--aout=directsound" in args
