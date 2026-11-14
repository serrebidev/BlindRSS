# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Seek options: fixed 60s steps, user step, jump-to-time parsing."""

import inspect

import gui.player as player
from gui.player import parse_jump_time_ms


def test_parse_jump_time_ms_all_forms():
    assert parse_jump_time_ms("90") == 90_000
    assert parse_jump_time_ms(" 90 ") == 90_000
    assert parse_jump_time_ms("1:23") == 83_000
    assert parse_jump_time_ms("1:23:45") == 5_025_000
    assert parse_jump_time_ms("0") == 0


def test_parse_jump_time_ms_rejects_garbage():
    assert parse_jump_time_ms("") is None
    assert parse_jump_time_ms(None) is None
    assert parse_jump_time_ms("abc") is None
    assert parse_jump_time_ms("1:2:3:4") is None
    assert parse_jump_time_ms("-5") is None
    assert parse_jump_time_ms("1::2") is None


def test_player_has_fixed_and_jump_controls():
    src = inspect.getsource(player.PlayerFrame.init_ui)
    assert "Back 60 seconds" in src
    assert "Forward 60 seconds" in src
    assert "Jump to Time" in src
    assert "on_back60" in src
    assert "on_forward60" in src
    assert "on_jump_to_time" in src


def test_settings_has_custom_seek_step():
    from gui import dialogs

    src = inspect.getsource(dialogs.SettingsDialog)
    assert "seek_step_ctrl" in src
    assert "seek_back_ms" in src
    assert "seek_forward_ms" in src
