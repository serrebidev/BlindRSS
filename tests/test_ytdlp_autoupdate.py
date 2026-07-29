# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regression tests for keeping yt-dlp current.

YouTube changes extraction every few weeks, so a stale yt-dlp stops working
outright ("Video unavailable. This video is not available"). Three separate
holes let the shipped copy fall a month behind:

* ``_should_check_updates`` wrote its 24h marker *before* the update ran, so a
  failed update still burned the window and the copy stayed stale.
* ``yt-dlp -U``'s exit code was trusted and never verified against the actual
  installed version.
* Portable builds used the bundled copy as-is and never updated it at all.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dependency_check as dc


def test_should_check_updates_can_defer_marking(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    marker = dc._update_marker_path("unit_test_defer")
    if os.path.isfile(marker):
        os.remove(marker)

    # A deferred check must not start the throttle window by itself...
    assert dc._should_check_updates("unit_test_defer", mark=False) is True
    assert not os.path.isfile(marker)
    assert dc._should_check_updates("unit_test_defer", mark=False) is True

    # ...only an explicit success does.
    dc._mark_update_checked("unit_test_defer")
    assert os.path.isfile(marker)
    assert dc._should_check_updates("unit_test_defer", mark=False) is False


def test_update_downloads_when_minus_u_leaves_it_stale(monkeypatch, tmp_path):
    """-U reporting success while the version is unchanged must not be believed."""
    exe = tmp_path / "yt-dlp.exe"
    exe.write_text("old")
    versions = ["2026.06.25", "2026.06.25"]  # before, and again after -U

    monkeypatch.setattr(dc, "latest_ytdlp_version", lambda *a, **k: "2026.07.23")
    monkeypatch.setattr(dc, "ytdlp_version", lambda *a, **k: versions.pop(0) if versions else "2026.07.23")
    monkeypatch.setattr(dc, "_run_quiet", lambda *a, **k: 0)  # -U "succeeds"

    downloaded = {}

    def _fake_download(dest, works=None):
        downloaded["dest"] = dest
        return True

    monkeypatch.setattr(dc, "download_latest_ytdlp", _fake_download)

    assert dc._update_managed_ytdlp(str(exe), lambda _p: True) is True
    assert downloaded["dest"] == str(exe)


def test_update_skips_work_when_already_current(monkeypatch, tmp_path):
    exe = tmp_path / "yt-dlp.exe"
    exe.write_text("current")

    monkeypatch.setattr(dc, "latest_ytdlp_version", lambda *a, **k: "2026.07.23")
    monkeypatch.setattr(dc, "ytdlp_version", lambda *a, **k: "2026.07.23")

    def _boom(*_a, **_kw):
        raise AssertionError("must not run -U or download when already current")

    monkeypatch.setattr(dc, "_run_quiet", _boom)
    monkeypatch.setattr(dc, "download_latest_ytdlp", _boom)

    assert dc._update_managed_ytdlp(str(exe), lambda _p: True) is True


def test_failed_download_keeps_the_working_binary(monkeypatch, tmp_path):
    """A truncated download must never leave the app without a usable yt-dlp."""
    exe = tmp_path / "yt-dlp.exe"
    exe.write_text("working copy")

    monkeypatch.setattr(dc, "_download_file", lambda _url, _dest: False)

    assert dc.download_latest_ytdlp(str(exe), works=lambda _p: True) is False
    assert exe.read_text() == "working copy"
    assert not os.path.isfile(str(exe) + ".new")


def test_unrunnable_download_keeps_the_working_binary(monkeypatch, tmp_path):
    """A downloaded binary that will not execute must be discarded, not installed."""
    exe = tmp_path / "yt-dlp.exe"
    exe.write_text("working copy")

    def _fake_download(_url, dest):
        with open(dest, "w") as f:
            f.write("corrupt")
        return True

    monkeypatch.setattr(dc, "_download_file", _fake_download)

    assert dc.download_latest_ytdlp(str(exe), works=lambda _p: False) is False
    assert exe.read_text() == "working copy"
    assert not os.path.isfile(str(exe) + ".new")


def test_successful_download_replaces_the_binary(monkeypatch, tmp_path):
    exe = tmp_path / "yt-dlp.exe"
    exe.write_text("stale copy")

    def _fake_download(_url, dest):
        with open(dest, "w") as f:
            f.write("fresh copy")
        return True

    monkeypatch.setattr(dc, "_download_file", _fake_download)

    assert dc.download_latest_ytdlp(str(exe), works=lambda _p: True) is True
    assert exe.read_text() == "fresh copy"
    assert not os.path.isfile(str(exe) + ".new")


def test_unknown_latest_version_is_not_treated_as_current(monkeypatch, tmp_path):
    """No network answer means "don't know" — it must not skip the update."""
    exe = tmp_path / "yt-dlp.exe"
    exe.write_text("old")

    monkeypatch.setattr(dc, "latest_ytdlp_version", lambda *a, **k: "")
    monkeypatch.setattr(dc, "ytdlp_version", lambda *a, **k: "2026.06.25")
    monkeypatch.setattr(dc, "_run_quiet", lambda *a, **k: 0)

    attempted = {}

    def _fake_download(dest, works=None):
        attempted["dest"] = dest
        return True

    monkeypatch.setattr(dc, "download_latest_ytdlp", _fake_download)

    dc._update_managed_ytdlp(str(exe), lambda _p: True)
    assert attempted["dest"] == str(exe)
