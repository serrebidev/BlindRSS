# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.dependency_check as dc


def test_brew_path_probes_standard_prefixes(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(dc.shutil, "which", lambda _name: None)

    seen = {}

    def fake_isfile(path):
        return path == "/opt/homebrew/bin/brew"

    def fake_access(path, _mode):
        seen["access"] = path
        return True

    monkeypatch.setattr(dc.os.path, "isfile", fake_isfile)
    monkeypatch.setattr(dc.os, "access", fake_access)

    assert dc._brew_path() == "/opt/homebrew/bin/brew"
    assert dc._has_brew() is True


def test_brew_path_none_off_macos(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Windows")
    assert dc._brew_path() is None
    assert dc._has_brew() is False


def test_brew_install_uses_cask_flag(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(dc, "_brew_path", lambda: "/opt/homebrew/bin/brew")

    calls = []

    def fake_run_quiet(cmd, timeout=900):
        calls.append(list(cmd))
        return 0

    monkeypatch.setattr(dc, "_run_quiet", fake_run_quiet)

    assert dc._brew_install("vlc", cask=True) is True
    assert calls[-1] == ["/opt/homebrew/bin/brew", "install", "--cask", "vlc"]

    assert dc._brew_install("ffmpeg") is True
    assert calls[-1] == ["/opt/homebrew/bin/brew", "install", "ffmpeg"]


def test_brew_install_reports_failure(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(dc, "_brew_path", lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(dc, "_run_quiet", lambda cmd, timeout=900: 1)
    assert dc._brew_install("ffmpeg") is False


def test_install_media_tools_macos_dispatch(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(dc, "_has_brew", lambda: True)

    installed = []
    monkeypatch.setattr(dc, "_brew_install", lambda name, cask=False: installed.append((name, cask)) or True)
    monkeypatch.setattr(dc, "_wait_for_executable", lambda name, timeout=30: True)
    monkeypatch.setattr(dc, "_ensure_tool_on_path", lambda name: None)

    dc.install_media_tools(vlc=True, ffmpeg=True, ytdlp=True)

    assert ("vlc", True) in installed
    assert ("ffmpeg", False) in installed
    assert ("yt-dlp", False) in installed


def test_install_media_tools_macos_noop_without_brew(monkeypatch):
    monkeypatch.setattr(dc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(dc, "_has_brew", lambda: False)

    called = []
    monkeypatch.setattr(dc, "_brew_install", lambda *a, **k: called.append(a) or True)

    dc.install_media_tools(vlc=True, ffmpeg=True, ytdlp=True)
    assert called == []
