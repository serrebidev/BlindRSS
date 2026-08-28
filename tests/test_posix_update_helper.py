# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Coverage for the POSIX update helper (macOS + Linux), `update_helper.sh`.

The Windows `.bat` helper is covered by test_update_helper_script.py; the POSIX
helper — which performs the macOS `.app` swap (`ditto` + `open`) and the Linux
install-dir swap with user-data restore — had no tests. The behavioral tests run
the real script and are skipped on Windows (no POSIX `sh`).
"""

import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "update_helper.sh"

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX shell helper")


# --------------------------------------------------------------------------- #
# Static invariants (run everywhere, mirror the .bat test style)
# --------------------------------------------------------------------------- #

def _helper_text() -> str:
    return HELPER.read_text(encoding="utf-8")


def test_macos_uses_ditto_and_open():
    text = _helper_text()
    # macOS bundle swap must use ditto (preserves bundle metadata + ad-hoc signature)
    # and relaunch via `open`.
    assert 'PLATFORM" = "macos" ] && command -v ditto' in text
    assert 'ditto "$STAGING_ROOT" "$INSTALL_TARGET"' in text
    assert 'open "$RELAUNCH_PATH"' in text


def test_backup_before_apply_and_rollback_present():
    text = _helper_text()
    backup = text.index('mv "$INSTALL_TARGET" "$BACKUP_DIR"')
    apply_ = text.index("Applying update.")
    assert backup < apply_
    assert "rollback()" in text
    # Rollback must only restore from a real backup path.
    assert '[ -n "$BACKUP_DIR" ] && [ -e "$BACKUP_DIR" ]' in text


def test_aborts_without_relaunch_when_app_still_running():
    text = _helper_text()
    # If the app never exits we must NOT relaunch (would spawn a duplicate) and
    # must leave the intact install in place.
    block = text[text.index("if ! wait_for_exit"):text.index("sleep 1")]
    assert "exit 1" in block
    # The `relaunch` function must not be CALLED in the abort path (a bare-line
    # call); the word still appears in an explanatory comment, so match call lines.
    call_lines = [ln.strip() for ln in block.splitlines()]
    assert "relaunch" not in call_lines


def test_linux_restores_user_data_from_backup():
    text = _helper_text()
    assert "restore_user_data_linux" in text
    for f in ("config.json", "rss.db", "rss.db-wal"):
        assert f in text
    assert "restore_file \"podcasts\"" in text


def test_linux_restores_install_local_runtime_state():
    """Browser profiles, cookie jars and the driver runtime live in the install.

    get_data_dir() resolves to the install dir on a default Linux layout, so
    without these the swap silently discarded the user's browser profiles and
    saved cookies and re-downloaded the whole Chromium runtime.
    """
    text = _helper_text()
    for name in (
        "feed_browser_profile",
        "feed_browser_pydoll_profile",
        "youtube_browser_profile",
        "feed_browser_runtime",
        "ytplay_cache",
        "site_cookies.txt",
        "site_cookies_ua.txt",
        "site_cookies_ua_hosts.json",
        "chromium_v20_keys.json",
    ):
        assert name in text


# --------------------------------------------------------------------------- #
# Behavioral tests (real execution on POSIX)
# --------------------------------------------------------------------------- #

def _make_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _dead_pid() -> int:
    """Return a PID that has fully exited AND been reaped.

    `wait()` reaps the child so it is not left as a zombie — a zombie still
    answers `kill -0`, which would make the helper poll for the full timeout.
    """
    proc = subprocess.Popen(["sh", "-c", "exit 0"])
    proc.wait()
    return proc.pid


def _run_helper(args, env=None, timeout=20):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["sh", str(HELPER), *args],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@posix_only
def test_macos_swap_replaces_bundle_and_relaunches(tmp_path):
    install = tmp_path / "BlindRSS.app"
    (install / "Contents" / "MacOS").mkdir(parents=True)
    (install / "old_marker.txt").write_text("OLD")

    staging = tmp_path / "staging_BlindRSS.app"
    (staging / "Contents" / "MacOS").mkdir(parents=True)
    (staging / "new_marker.txt").write_text("NEW")

    # Shadow `open` so the relaunch doesn't actually launch anything.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    open_log = tmp_path / "open_called.txt"
    _make_exec(fake_bin / "open", f'#!/bin/sh\necho "$@" >> "{open_log}"\n')

    pid = _dead_pid()
    res = _run_helper(
        [str(pid), "macos", str(install), str(staging), str(install)],
        env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
    )
    assert res.returncode == 0, res.stderr

    assert install.exists()
    assert (install / "new_marker.txt").read_text() == "NEW"
    assert not (install / "old_marker.txt").exists()  # bundle fully replaced
    # Backup cleaned up on success.
    assert not list(tmp_path.glob("BlindRSS.app.bak.*"))
    assert open_log.exists()  # relaunch happened


@posix_only
def test_linux_swap_preserves_user_data(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    (install / "config.json").write_text("USER_CONFIG")
    (install / "rss.db").write_text("USER_DB")
    (install / "old_lib.txt").write_text("OLD")
    (install / "feed_browser_profile" / "Default").mkdir(parents=True)
    (install / "feed_browser_profile" / "Default" / "Cookies").write_text("JAR")
    (install / "site_cookies.txt").write_text("USER_COOKIES")

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "new_lib.txt").write_text("NEW")
    relaunch_marker = tmp_path / "relaunched.txt"
    _make_exec(staging / "BlindRSS", f'#!/bin/sh\necho up >> "{relaunch_marker}"\n')

    pid = _dead_pid()
    res = _run_helper(
        [str(pid), "linux", str(install), str(staging), str(install / "BlindRSS")],
    )
    assert res.returncode == 0, res.stderr

    # New build applied...
    assert (install / "new_lib.txt").read_text() == "NEW"
    assert not (install / "old_lib.txt").exists()
    # ...but in-dir user data restored from the backup.
    assert (install / "config.json").read_text() == "USER_CONFIG"
    assert (install / "rss.db").read_text() == "USER_DB"
    assert (install / "feed_browser_profile" / "Default" / "Cookies").read_text() == "JAR"
    assert (install / "site_cookies.txt").read_text() == "USER_COOKIES"

    # Relaunch fires in the background; give it a moment.
    for _ in range(40):
        if relaunch_marker.exists():
            break
        time.sleep(0.05)
    assert relaunch_marker.exists()


@posix_only
def test_missing_staging_aborts_without_backup(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    (install / "keep.txt").write_text("KEEP")
    missing_staging = tmp_path / "does_not_exist"
    relaunch_marker = tmp_path / "relaunch.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _make_exec(fake_bin / "open", f'#!/bin/sh\necho x >> "{relaunch_marker}"\n')

    pid = _dead_pid()
    res = _run_helper(
        [str(pid), "macos", str(install), str(missing_staging), str(install)],
        env={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
    )
    assert res.returncode == 1
    # Install must be left intact (no destructive backup move happened).
    assert (install / "keep.txt").read_text() == "KEEP"
    assert not list(tmp_path.glob("install.bak.*"))
