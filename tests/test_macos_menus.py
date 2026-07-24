# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""macOS native-menu and cross-platform startup parity.

The frame's menubar uses the standard role IDs (ID_ABOUT / ID_PREFERENCES /
ID_EXIT) so wxPython relocates them into the macOS application menu and assigns
the standard accelerators, and ships a standard Edit menu so the focused text
control (the article reader pane is a key VoiceOver surface) handles
Cut/Copy/Paste/Select All. These tests lock in the headless-checkable behaviour:
the startup-at-login sync now keys off the cross-platform
``windows_integration.startup_supported()`` helper instead of a Windows-only
guard, and the module imports cleanly.
"""

from core import windows_integration
import gui.mainframe as mainframe


class _Host:
    """Minimal stand-in exercising the real sync method (mirrors test_macos_notifications)."""

    _sync = mainframe.MainFrame._sync_windows_startup_setting


def test_startup_sync_delegates_when_supported(monkeypatch):
    # On a platform where startup is supported (Windows or macOS), the sync must
    # delegate to set_startup_enabled and return its result verbatim.
    calls = []

    def fake_set(enabled):
        calls.append(enabled)
        return (False, "boom")

    monkeypatch.setattr(windows_integration, "startup_supported", lambda: True, raising=False)
    monkeypatch.setattr(windows_integration, "set_startup_enabled", fake_set, raising=False)

    assert _Host()._sync(True) == (False, "boom")
    assert calls == [True]


def test_startup_sync_passes_bool_through(monkeypatch):
    # The enabled flag is coerced to a real bool before delegation.
    captured = {}

    def fake_set(enabled):
        captured["enabled"] = enabled
        return (True, "")

    monkeypatch.setattr(windows_integration, "startup_supported", lambda: True, raising=False)
    monkeypatch.setattr(windows_integration, "set_startup_enabled", fake_set, raising=False)

    assert _Host()._sync(0) == (True, "")
    assert captured["enabled"] is False
    assert isinstance(captured["enabled"], bool)


def test_startup_sync_noop_when_unsupported(monkeypatch):
    # When unsupported, return (True, "") and never touch set_startup_enabled.
    def explode(enabled):  # pragma: no cover - must not run
        raise AssertionError("set_startup_enabled called on unsupported platform")

    monkeypatch.setattr(windows_integration, "startup_supported", lambda: False, raising=False)
    monkeypatch.setattr(windows_integration, "set_startup_enabled", explode, raising=False)

    assert _Host()._sync(True) == (True, "")


def test_mainframe_imports():
    # Import smoke test: the menu changes must not break module import.
    import importlib

    importlib.reload(mainframe)
    assert hasattr(mainframe, "MainFrame")
