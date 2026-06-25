"""macOS start-at-login (LaunchAgent) support.

The start-at-login checkbox used to be hard-disabled off Windows and
``set_startup_enabled`` only spoke to the Windows registry. These tests lock in
the cross-platform dispatch and the macOS LaunchAgent behaviour, never touching a
real ``launchctl`` or the user's ``~/Library/LaunchAgents``.
"""

import os
import plistlib
import sys

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import macos_integration as macint
from core import windows_integration as winint


def test_startup_supported_per_platform(monkeypatch):
    for plat, expected in [("win32", True), ("darwin", True), ("linux", False)]:
        monkeypatch.setattr(winint.sys, "platform", plat)
        assert winint.startup_supported() is expected


def test_startup_setting_label_per_platform(monkeypatch):
    cases = {
        "win32": "Start BlindRSS when Windows starts",
        "darwin": "Start BlindRSS when you log in",
        "linux": "Start BlindRSS at login",
    }
    for plat, expected in cases.items():
        monkeypatch.setattr(winint.sys, "platform", plat)
        assert winint.startup_setting_label() == expected


class _RecordingRun:
    """Stand-in for subprocess.run that records launchctl invocations."""

    def __init__(self, returncode=0):
        self.calls = []
        self._returncode = returncode

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))

        class _Proc:
            returncode = self._returncode
            stdout = ""
            stderr = ""

        return _Proc()


def _point_launch_agents_at(monkeypatch, tmp_path):
    """Redirect Path.home() so the LaunchAgents dir lands under tmp_path."""
    home = tmp_path / "home"
    monkeypatch.setattr(macint.Path, "home", classmethod(lambda cls: home))
    return home / "Library" / "LaunchAgents" / f"{macint.LAUNCH_AGENT_LABEL}.plist"


def test_enable_on_macos_writes_plist_and_loads(monkeypatch, tmp_path):
    monkeypatch.setattr(winint.sys, "platform", "darwin")
    monkeypatch.setattr(macint.sys, "platform", "darwin")
    expected_plist = _point_launch_agents_at(monkeypatch, tmp_path)

    monkeypatch.setattr(
        macint,
        "_program_arguments",
        lambda: ["/Applications/BlindRSS.app/Contents/MacOS/BlindRSS"],
    )
    runner = _RecordingRun()
    monkeypatch.setattr(macint.subprocess, "run", runner)

    # Dispatch through the cross-platform entry point the GUI/menus use.
    ok, msg = winint.set_startup_enabled(True)
    assert ok is True
    assert "log in" in msg.lower()

    assert expected_plist.exists()
    with open(expected_plist, "rb") as fh:
        data = plistlib.load(fh)
    assert data["Label"] == macint.LAUNCH_AGENT_LABEL
    assert data["RunAtLoad"] is True
    assert data["ProgramArguments"] and data["ProgramArguments"][0]
    assert "KeepAlive" not in data

    # A load invocation must have happened (after a best-effort unload).
    assert any(c[:2] == ["launchctl", "load"] for c in runner.calls)


def test_enable_on_macos_removes_plist_when_load_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(macint.sys, "platform", "darwin")
    expected_plist = _point_launch_agents_at(monkeypatch, tmp_path)
    monkeypatch.setattr(
        macint,
        "_program_arguments",
        lambda: ["/Applications/BlindRSS.app/Contents/MacOS/BlindRSS"],
    )

    calls = []

    def _run(cmd, *args, **kwargs):
        calls.append(list(cmd))

        class _Proc:
            returncode = 1 if "load" in cmd else 0
            stdout = ""
            stderr = "bootstrap failed" if returncode else ""

        return _Proc()

    monkeypatch.setattr(macint.subprocess, "run", _run)

    ok, msg = macint.set_macos_startup_enabled(True)

    assert ok is False
    assert "bootstrap failed" in msg
    assert not expected_plist.exists()
    assert any(c[:2] == ["launchctl", "load"] for c in calls)


def test_disable_on_macos_unloads_and_removes_plist(monkeypatch, tmp_path):
    monkeypatch.setattr(winint.sys, "platform", "darwin")
    monkeypatch.setattr(macint.sys, "platform", "darwin")
    expected_plist = _point_launch_agents_at(monkeypatch, tmp_path)
    expected_plist.parent.mkdir(parents=True, exist_ok=True)
    expected_plist.write_bytes(b"stale")

    runner = _RecordingRun()
    monkeypatch.setattr(macint.subprocess, "run", runner)

    ok, msg = winint.set_startup_enabled(False)
    assert ok is True
    assert "disabled" in msg.lower()
    assert not expected_plist.exists()
    assert any(c[:2] == ["launchctl", "unload"] for c in runner.calls)


def test_disable_on_macos_when_plist_absent_is_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(macint.sys, "platform", "darwin")
    expected_plist = _point_launch_agents_at(monkeypatch, tmp_path)
    assert not expected_plist.exists()

    runner = _RecordingRun()
    monkeypatch.setattr(macint.subprocess, "run", runner)

    ok, _msg = macint.set_macos_startup_enabled(False)
    assert ok is True


def test_enable_on_unsupported_platform_does_not_write_plist(monkeypatch, tmp_path):
    monkeypatch.setattr(winint.sys, "platform", "linux")
    monkeypatch.setattr(macint.sys, "platform", "linux")
    expected_plist = _point_launch_agents_at(monkeypatch, tmp_path)

    # Guard: launchctl must never be invoked on an unsupported platform.
    def _boom(*_a, **_k):
        raise AssertionError("subprocess.run should not be called on linux")

    monkeypatch.setattr(macint.subprocess, "run", _boom)

    ok, msg = winint.set_startup_enabled(True)
    assert ok is False
    assert "not supported" in msg.lower()
    assert not expected_plist.exists()
