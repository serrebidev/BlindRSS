# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from types import SimpleNamespace

from gui import mainframe


class _Config:
    def __init__(self, enabled):
        self.enabled = enabled

    def get(self, key, default=None):
        if key == "install_updates_automatically":
            return self.enabled
        return default


def _frame(enabled):
    installs = []
    frame = SimpleNamespace(
        config_manager=_Config(enabled),
        _update_check_inflight=True,
        _start_update_install=installs.append,
    )
    return frame, installs


def test_update_installs_without_confirmation_when_enabled(monkeypatch):
    frame, installs = _frame(True)
    info = SimpleNamespace(tag="v2.0.0", notes_summary="Notes")
    result = mainframe.updater.UpdateCheckResult("update_available", "Update available", info)
    prompts = []
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *args, **kwargs: prompts.append(args))

    mainframe.MainFrame._handle_update_check_result(frame, result, manual=False)

    assert installs == [info]
    assert prompts == []
    assert frame._update_check_inflight is False


def test_update_still_prompts_when_automatic_install_is_disabled(monkeypatch):
    frame, installs = _frame(False)
    info = SimpleNamespace(tag="v2.0.0", notes_summary="Notes")
    result = mainframe.updater.UpdateCheckResult("update_available", "Update available", info)
    prompts = []

    def message_box(*args, **kwargs):
        prompts.append(args)
        return mainframe.wx.NO

    monkeypatch.setattr(mainframe.wx, "MessageBox", message_box)

    mainframe.MainFrame._handle_update_check_result(frame, result, manual=False)

    assert installs == []
    assert len(prompts) == 1
