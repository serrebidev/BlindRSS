# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.screen_reader_announce as sra


class _FakeProc:
    def __init__(self):
        self.terminated = False
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False


def _install_fake_say(monkeypatch):
    monkeypatch.setattr(sra.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(sra, "_macos_say_path", lambda: "/usr/bin/say")
    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProc()

    monkeypatch.setattr(sra.subprocess, "Popen", fake_popen)
    return calls


def test_speak_status_uses_say_on_macos(monkeypatch):
    sra._reset_for_tests()
    calls = _install_fake_say(monkeypatch)
    assert sra.speak_status("Article not found.") is True
    assert calls == [["/usr/bin/say", "--", "Article not found."]]


def test_speak_status_empty_is_false(monkeypatch):
    sra._reset_for_tests()
    _install_fake_say(monkeypatch)
    assert sra.speak_status("   ") is False


def test_speak_status_interrupt_terminates_previous(monkeypatch):
    sra._reset_for_tests()
    _install_fake_say(monkeypatch)
    sra.speak_status("first")
    first = sra._SAY_PROC
    assert first is not None and first.terminated is False
    sra.speak_status("second", interrupt=True)
    assert first.terminated is True


def test_speak_status_no_say_binary(monkeypatch):
    sra._reset_for_tests()
    monkeypatch.setattr(sra.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(sra, "_macos_say_path", lambda: None)
    assert sra.speak_status("hello") is False


def test_speak_status_off_supported_platforms(monkeypatch):
    sra._reset_for_tests()
    monkeypatch.setattr(sra.sys, "platform", "linux", raising=False)
    assert sra.speak_status("hello") is False


def test_module_imports_and_exposes_speak_status():
    # The guarded wintypes import must never break loading off Windows.
    assert callable(sra.speak_status)
    assert callable(sra.braille_message)
