# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import screen_reader_announce as sra


class _FakeNvdaDll:
    def __init__(self, *, running_rc=0, speak_rc=0):
        self.running_rc = running_rc
        self.speak_rc = speak_rc
        self.calls = []

    def nvdaController_testIfRunning(self):
        self.calls.append(("test",))
        return self.running_rc

    def nvdaController_cancelSpeech(self):
        self.calls.append(("cancel",))
        return 0

    def nvdaController_speakText(self, text):
        self.calls.append(("speak", text))
        return self.speak_rc


def test_speak_status_uses_nvda_controller_success(monkeypatch):
    dll = _FakeNvdaDll()
    monkeypatch.setattr(sra.sys, "platform", "win32")
    monkeypatch.setattr(sra, "_load_nvda_controller", lambda: dll)
    monkeypatch.setattr(sra, "_speak_jaws", lambda *a, **k: (_ for _ in ()).throw(AssertionError("JAWS tried")))

    assert sra.speak_status("not found") is True
    assert dll.calls == [("test",), ("cancel",), ("speak", "not found")]


def test_speak_status_falls_through_when_nvda_is_not_running(monkeypatch):
    dll = _FakeNvdaDll(running_rc=1)
    jaws_calls = []
    monkeypatch.setattr(sra.sys, "platform", "win32")
    monkeypatch.setattr(sra, "_load_nvda_controller", lambda: dll)
    monkeypatch.setattr(sra, "_speak_jaws", lambda text, interrupt=True: jaws_calls.append((text, interrupt)) or True)

    assert sra.speak_status("not found") is True
    assert dll.calls == [("test",)]
    assert jaws_calls == [("not found", True)]


def test_speak_status_returns_false_when_nvda_speak_fails_and_jaws_fails(monkeypatch):
    dll = _FakeNvdaDll(speak_rc=5)
    monkeypatch.setattr(sra.sys, "platform", "win32")
    monkeypatch.setattr(sra, "_load_nvda_controller", lambda: dll)
    monkeypatch.setattr(sra, "_speak_jaws", lambda *a, **k: False)

    assert sra.speak_status("not found") is False
    assert dll.calls == [("test",), ("cancel",), ("speak", "not found")]


def test_jaws_requires_running_process_even_if_com_would_succeed(monkeypatch):
    monkeypatch.setattr(sra, "_windows_process_running", lambda names: False)
    monkeypatch.setattr(sra, "_speak_jaws_via_pywin32", lambda *a, **k: True)
    monkeypatch.setattr(sra, "_speak_jaws_via_comtypes", lambda *a, **k: True)

    assert sra._speak_jaws("not found") is False


def test_jaws_success_requires_successful_saystring(monkeypatch):
    calls = []
    monkeypatch.setattr(sra, "_windows_process_running", lambda names: True)
    monkeypatch.setattr(sra, "_speak_jaws_via_pywin32", lambda text, interrupt=True: calls.append(("pywin32", text, interrupt)) or False)
    monkeypatch.setattr(sra, "_speak_jaws_via_comtypes", lambda text, interrupt=True: calls.append(("comtypes", text, interrupt)) or True)

    assert sra._speak_jaws("not found", interrupt=False) is True
    assert calls == [
        ("pywin32", "not found", False),
        ("comtypes", "not found", False),
    ]
