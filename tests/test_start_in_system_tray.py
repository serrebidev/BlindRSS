# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from gui.mainframe import MainFrame


class _StartupWindow:
    _apply_startup_window_state = MainFrame._apply_startup_window_state

    def __init__(self, *, tray=False, maximized=False, iconized=False):
        self._start_in_system_tray = tray
        self._start_maximized = maximized
        self._iconized = iconized
        self.hidden = False
        self.maximize_calls = []
        self.iconize_calls = []

    def IsIconized(self):
        return self._iconized

    def Iconize(self, value):
        self.iconize_calls.append(value)
        self._iconized = value

    def Hide(self):
        self.hidden = True

    def IsMaximized(self):
        return bool(self.maximize_calls and self.maximize_calls[-1])

    def Maximize(self, value):
        self.maximize_calls.append(value)


def test_start_in_system_tray_hides_and_overrides_maximized():
    window = _StartupWindow(tray=True, maximized=True, iconized=True)
    window._apply_startup_window_state()
    assert window.hidden is True
    assert window.iconize_calls == [False]
    assert window.maximize_calls == []


def test_normal_start_can_apply_maximized_preference():
    window = _StartupWindow(tray=False, maximized=True)
    window._apply_startup_window_state()
    assert window.hidden is False
    assert window.maximize_calls == [True]
