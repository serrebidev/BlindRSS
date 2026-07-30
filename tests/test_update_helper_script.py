# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "update_helper.bat"
MAINFRAME = ROOT / "gui" / "mainframe.py"


def _helper_text() -> str:
    return HELPER.read_text(encoding="utf-8")


def test_update_helper_stops_running_install_instances_before_file_moves():
    text = _helper_text()

    stop_call = text.index("call :ensure_app_stopped")
    unlock_call = text.index("call :verify_install_unlocked")
    backup_move = text.index('robocopy "%INSTALL_DIR%" "%BACKUP_DIR%"')

    assert stop_call < unlock_call < backup_move
    assert "CloseMainWindow" in text
    assert "Stop-Process -Id $p.Id -Force" in text
    assert "[X] BlindRSS is still running from the install folder" in text
    assert "Get-InstallProc" in text
    assert "Stopping install-owned helper process(es)" in text
    assert "[X] Install-owned processes are still running" in text


def test_update_helper_checks_for_partial_backup_before_applying_update():
    text = _helper_text()

    backup_move = text.index('robocopy "%INSTALL_DIR%" "%BACKUP_DIR%"')
    drained_call = text.index("call :verify_install_drained")
    apply_move = text.index('robocopy "%STAGING_DIR%" "%INSTALL_DIR%"')

    assert backup_move < drained_call < apply_move
    assert ":verify_install_drained" in text
    assert "Files remained in the install folder after backup" in text


def test_update_helper_does_not_rollback_from_empty_backup_path():
    text = _helper_text()

    assert 'if not "%BACKUP_DIR%"=="" if exist "%BACKUP_DIR%"' in text


def test_update_helper_relocated_batch_shell_exits_cleanly():
    text = _helper_text()

    assert 'start "" /b cmd /d /c call "!TMP_HELPER!"' in text
    assert 'start "" /b "!TMP_HELPER!"' not in text


def test_update_helper_supports_signed_installer_updates():
    text = _helper_text()

    assert 'if /I "%~1"=="--installer"' in text
    assert 'start "" /wait "%INSTALLER_PATH%" /VERYSILENT' in text
    assert 'if not exist "%INSTALL_DIR%\\.windows-installed"' in text
    assert 'copy /Y "%OLD_DIR%\\.windows-installed"' in text


def test_successful_update_exits_without_modal_ready_prompt():
    text = MAINFRAME.read_text(encoding="utf-8")

    assert 'wx.MessageBox(msg, "Update Ready"' not in text
    assert "wx.CallAfter(self.real_close)" in text


def test_update_helper_retries_backup_move_on_transient_lock():
    text = _helper_text()

    # A runtime DLL transiently locked by AV/indexing must not fail the whole
    # update on the first robocopy /MOVE: the helper retries the move with a
    # settle, and only aborts after a bounded number of attempts.
    assert ":backup_move_attempt" in text
    assert ":backup_drained" in text
    assert "retrying move (attempt" in text
    assert "did not fully move the current install after" in text

    # The retry loop still sits before the staged build is applied, so a partial
    # backup can never be overwritten.
    retry_label = text.index(":backup_move_attempt")
    apply_move = text.index('robocopy "%STAGING_DIR%" "%INSTALL_DIR%"')
    assert retry_label < apply_move


def test_update_helper_probes_bundled_helper_executables_for_locks():
    text = _helper_text()

    assert "'_internal\\bin'" in text
    assert "Get-ChildItem -LiteralPath $dir -File -Filter '*.exe'" in text


def test_update_helper_preserves_backup_during_rollback():
    text = _helper_text()
    rollback_start = text.index("\n:rollback\n")
    rollback = text[rollback_start:text.index("\n:ensure_app_stopped\n")]

    assert 'robocopy "%BACKUP_DIR%" "%INSTALL_DIR%" /E /COPY:DAT' in rollback
    assert 'robocopy "%BACKUP_DIR%" "%INSTALL_DIR%" /E /MOVE' not in rollback
    assert 'if exist "%INSTALL_DIR%\\%EXE_NAME%"' in rollback
    assert "if %RC% geq 8" in text


def test_update_helper_terminates_orphaned_bundled_executable(tmp_path):
    """A surviving yt-dlp child must not block an archive update on Windows."""
    if sys.platform != "win32":
        return

    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    cmd_exe = system32 / "cmd.exe"
    ping_exe = system32 / "ping.exe"
    where_exe = system32 / "where.exe"
    if not cmd_exe.is_file() or not ping_exe.is_file() or not where_exe.is_file():
        return

    install = tmp_path / "BlindRSS"
    staging = tmp_path / "staging"
    helper_bin = install / "_internal" / "bin"
    helper_bin.mkdir(parents=True)
    staging.mkdir()

    locker_exe = helper_bin / "yt-dlp.exe"
    helper_copy = tmp_path / "helper.bat"
    shutil.copy2(HELPER, helper_copy)
    shutil.copy2(ping_exe, locker_exe)
    shutil.copy2(where_exe, install / "BlindRSS.exe")
    shutil.copy2(where_exe, staging / "BlindRSS.exe")
    (staging / "updated.txt").write_text("new build", encoding="utf-8")

    locker = subprocess.Popen(
        [str(locker_exe), "-n", "120", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        time.sleep(0.2)
        assert locker.poll() is None
        completed = subprocess.run(
            [
                str(cmd_exe), "/d", "/q", "/c", helper_copy.name,
                "0", str(install), str(staging), "BlindRSS.exe", "", "0",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert (install / "updated.txt").read_text(encoding="utf-8") == "new build"
        locker.wait(timeout=5)
    finally:
        if locker.poll() is None:
            locker.kill()
            locker.wait(timeout=5)
