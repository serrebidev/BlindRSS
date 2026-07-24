# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from collections import deque

import gui.mainframe as mainframe


class _DummyNotificationHost:
    _bind_notification_payload = mainframe.MainFrame._bind_notification_payload
    _prune_notification_payloads = mainframe.MainFrame._prune_notification_payloads
    _show_windows_notification = mainframe.MainFrame._show_windows_notification

    def __init__(self):
        self._notification_payloads = {}
        self._active_notifications = deque(maxlen=500)
        self.tray_icon = None

    def _windows_notifications_enabled(self):
        return True

    def _on_windows_notification_click(self, _event):
        return None

    def _on_windows_notification_dismissed(self, _event):
        return None


def test_actionable_notification_uses_finite_long_timeout(monkeypatch):
    captured = {}

    class FakeNotification:
        def __init__(self, _title, _message, parent=None):
            self.parent = parent
            self.binds = []

        def SetFlags(self, _flags):
            return None

        def Bind(self, evt, handler):
            self.binds.append((evt, handler))

        def Show(self, timeout=None):
            captured["timeout"] = timeout
            return True

    monkeypatch.setattr(mainframe.wx.adv, "NotificationMessage", FakeNotification)
    monkeypatch.setattr(mainframe, "EVT_NOTIFICATION_MESSAGE_CLICK", object())
    monkeypatch.setattr(mainframe, "EVT_NOTIFICATION_MESSAGE_ACTION", object())
    monkeypatch.setattr(mainframe, "EVT_NOTIFICATION_MESSAGE_DISMISSED", object())

    host = _DummyNotificationHost()
    host._show_windows_notification(
        "BlindRSS",
        "Test",
        activation_payload={"article_id": "a1", "url": "https://example.com/1"},
    )

    assert captured["timeout"] == mainframe.ACTIONABLE_NOTIFICATION_TIMEOUT_SECONDS
    assert len(host._active_notifications) == 1
    assert len(host._notification_payloads) == 1


def test_non_actionable_notification_uses_auto_timeout(monkeypatch):
    captured = {}
    expected_auto_timeout = mainframe.wx.adv.NotificationMessage.Timeout_Auto

    class FakeNotification:
        Timeout_Auto = expected_auto_timeout

        def __init__(self, _title, _message, parent=None):
            self.parent = parent

        def SetFlags(self, _flags):
            return None

        def Show(self, timeout=None):
            captured["timeout"] = timeout
            return True

    monkeypatch.setattr(mainframe.wx.adv, "NotificationMessage", FakeNotification)

    host = _DummyNotificationHost()
    host._show_windows_notification("BlindRSS", "Test")

    assert captured["timeout"] == expected_auto_timeout
