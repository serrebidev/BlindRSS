# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""macOS notification parity.

New-article notifications were hard-gated to Windows even though
`wx.adv.NotificationMessage` renders native banners on macOS. These tests lock in
that the capability is recognised on macOS and that the enable-gate honours it.
"""

from types import SimpleNamespace

from core import utils
import gui.mainframe as mainframe


def test_platform_supports_notifications(monkeypatch):
    for plat, expected in [("win32", True), ("darwin", True), ("linux", False)]:
        monkeypatch.setattr(utils.sys, "platform", plat)
        assert utils.platform_supports_notifications() is expected


class _Host:
    """Minimal stand-in exercising the real gate method."""

    _windows_notifications_enabled = mainframe.MainFrame._windows_notifications_enabled

    def __init__(self, enabled):
        self.config_manager = SimpleNamespace(get=lambda k, d=None: enabled if k == "windows_notifications_enabled" else d)


def test_gate_enabled_on_macos_when_configured(monkeypatch):
    monkeypatch.setattr(utils.sys, "platform", "darwin")
    assert _Host(enabled=True)._windows_notifications_enabled() is True
    assert _Host(enabled=False)._windows_notifications_enabled() is False


def test_gate_disabled_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(utils.sys, "platform", "linux")
    # Even with the setting on, an unsupported platform must not enable notifications.
    assert _Host(enabled=True)._windows_notifications_enabled() is False


def test_gate_enabled_on_windows_when_configured(monkeypatch):
    monkeypatch.setattr(utils.sys, "platform", "win32")
    assert _Host(enabled=True)._windows_notifications_enabled() is True
