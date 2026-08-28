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
    assert "TrimEnd('\\') + '\\'" in text
    assert "[StringComparison]::OrdinalIgnoreCase" in text


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
    temp_root = tmp_path / "BlindRSS_update_work"
    staging = temp_root / "extract" / "BlindRSS"
    helper_bin = install / "_internal" / "bin"
    helper_bin.mkdir(parents=True)
    staging.mkdir(parents=True)

    locker_exe = helper_bin / "yt-dlp.exe"
    helper_copy = tmp_path / "BlindRSS_update_helper_test.bat"
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
                # Full path, not the bare name: with the machine-wide
                # NoDefaultCurrentDirectoryInExePath=1 hardening, cmd /c will
                # not search the cwd and "x.bat" is reported as unrecognized.
                str(cmd_exe), "/d", "/q", "/c", str(helper_copy),
                "0", str(install), str(staging), "BlindRSS.exe", str(temp_root), "0",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert (install / "updated.txt").read_text(encoding="utf-8") == "new build"
        assert not temp_root.exists(), "successful update left its temp root behind"
        for _ in range(100):
            if not helper_copy.exists():
                break
            time.sleep(0.05)
        assert not helper_copy.exists(), "successful update left its helper copy behind"
        locker.wait(timeout=5)
    finally:
        if locker.poll() is None:
            locker.kill()
            locker.wait(timeout=5)


def test_success_cleanup_is_final_and_synchronous():
    text = _helper_text()

    cleanup = text.index(':cleanup_temp_root_now')
    fallback = text.index('if errorlevel 1 call :schedule_temp_cleanup', cleanup)
    assert cleanup < fallback
    assert 'Cleaned temp root' in text
    assert '(goto) 2>nul & del /f /q "%~f0"' in text


def _skip_dirs(text):
    return text.split('set "SKIP_DIRS=')[1].split('"')[0].split()


def _skip_files(text):
    return text.split('set "SKIP_FILES=')[1].split('"')[0].split()


def test_update_helper_preserves_install_local_runtime_state():
    """Chromium profiles and cookie jars must never be moved out of the install.

    They live inside the install dir whenever get_data_dir() resolves to it
    (portable/AppData installs), they are not part of the shipped build, and a
    live or orphaned browser keeps them locked -- which used to fail the whole
    backup move with robocopy code 9 and roll the update back.
    """
    text = _helper_text()

    dirs = _skip_dirs(text)
    for name in (
        ".git",
        ".venv",
        "__pycache__",
        "feed_browser_profile",
        "feed_browser_pydoll_profile",
        "youtube_browser_profile",
        "feed_browser_runtime",
        "ytplay_cache",
        "podcasts",
    ):
        assert name in dirs

    files = _skip_files(text)
    for name in ("site_cookies.txt", "site_cookies_ua_hosts.json", "chromium_v20_keys.json"):
        assert name in files

    backup_move = text[text.index('robocopy "%INSTALL_DIR%" "%BACKUP_DIR%"'):]
    backup_move = backup_move[:backup_move.index("\n")]
    assert "/XD %SKIP_DIRS%" in backup_move
    assert "/XF %SKIP_FILES%" in backup_move

    # The drain check has to honour the same list, or the preserved state would
    # look like an install that never moved and burn every retry attempt.
    drained = text[text.index("\n:verify_install_drained\n"):text.index("\n:restore_user_data\n")]
    assert "$env:SKIP_DIRS" in drained
    assert "$env:SKIP_FILES" in drained


def test_update_helper_stops_browsers_by_user_data_dir():
    """System Chrome runs from Program Files, so the image-path sweep misses it."""
    text = _helper_text()

    stopped = text[text.index("\n:ensure_app_stopped\n"):text.index("\n:verify_install_unlocked\n")]
    assert "Get-ProfileProc" in stopped
    assert "Win32_Process" in stopped
    assert "'--user-data-dir'" in stopped
    assert "Stopping browser process(es) holding an install-owned profile" in stopped

    # The browser has to go before uc_driver, or force-killing the driver
    # orphans the Chromium that is actually holding the profile open.
    assert stopped.index("$browsers=@(Get-ProfileProc)") < stopped.index("$helpers=@(Get-InstallProc)")


def test_rollback_only_purges_once_the_staged_build_started_landing():
    text = _helper_text()

    rollback = text[text.index("\n:rollback\n"):text.index("\n:ensure_app_stopped\n")]
    assert 'if "%APPLY_STARTED%"=="1" set "ROLLBACK_PURGE=/PURGE"' in rollback
    assert "!ROLLBACK_PURGE!" in rollback
    # Purging must never reach the preserved user state.
    assert "/XD %SKIP_DIRS%" in rollback
    assert "/XF %SKIP_FILES%" in rollback

    # The flag is only set once the backup is known complete.
    assert 'set "APPLY_STARTED=0"' in text
    apply_flag = text.index('set "APPLY_STARTED=1"')
    apply_move = text.index('robocopy "%STAGING_DIR%" "%INSTALL_DIR%"')
    drained = text.index(":backup_drained\n")
    assert drained < apply_flag < apply_move


def _system32():
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def _windows_helper_fixture_ready():
    if sys.platform != "win32":
        return False
    s32 = _system32()
    return (
        (s32 / "cmd.exe").is_file()
        and (s32 / "where.exe").is_file()
        and (s32 / "WindowsPowerShell" / "v1.0" / "powershell.exe").is_file()
    )


def _lay_out_update(tmp_path, extra_install_files=None):
    """Build an install/staging pair shaped like a real archive update."""
    s32 = _system32()
    install = tmp_path / "BlindRSS"
    temp_root = tmp_path / "BlindRSS_update_work"
    staging = temp_root / "extract" / "BlindRSS"
    (install / "_internal").mkdir(parents=True)
    staging.mkdir(parents=True)
    shutil.copy2(s32 / "where.exe", install / "BlindRSS.exe")
    shutil.copy2(s32 / "where.exe", staging / "BlindRSS.exe")
    (install / "_internal" / "old.pyd").write_text("old", encoding="utf-8")
    (staging / "updated.txt").write_text("new build", encoding="utf-8")
    for rel, body in (extra_install_files or {}).items():
        target = install / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return install, staging, temp_root


def _run_update(tmp_path, helper_copy, install, staging, temp_root):
    return subprocess.run(
        [
            str(_system32() / "cmd.exe"), "/d", "/q", "/c", str(helper_copy),
            "0", str(install), str(staging), "BlindRSS.exe", str(temp_root), "0",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def test_locked_browser_profile_no_longer_fails_the_update(tmp_path):
    """The exact reported failure: robocopy code 9 on feed_browser_profile.

    A Chromium the helper cannot see (system Chrome, or one whose kill did not
    take) holds a profile file open. The build must still swap, and the profile
    must still be sitting in the install dir afterwards.
    """
    if not _windows_helper_fixture_ready():
        return

    ps_exe = _system32() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    install, staging, temp_root = _lay_out_update(
        tmp_path,
        {
            "feed_browser_profile/Default/Network/Cookies": "cookie jar",
            "site_cookies.txt": "user cookies",
            "podcasts/episode.mp3": "audio",
        },
    )
    locked = install / "feed_browser_profile" / "Default" / "Network" / "Cookies"
    helper_copy = tmp_path / "BlindRSS_update_helper_locked.bat"
    shutil.copy2(HELPER, helper_copy)

    # A deny-share handle from a process whose image is OUTSIDE the install dir
    # and whose command line has no --user-data-dir: the helper cannot kill it,
    # so the lock is still held when robocopy runs. That is the point.
    open_cmd = (
        "$f=[IO.File]::Open('" + str(locked) + "','Open','Read','None');"
        " Start-Sleep -Seconds 90; $f.Close()"
    )
    locker = subprocess.Popen(
        [str(ps_exe), "-NoProfile", "-Command", open_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        time.sleep(2)
        assert locker.poll() is None
        completed = _run_update(tmp_path, helper_copy, install, staging, temp_root)

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert (install / "updated.txt").read_text(encoding="utf-8") == "new build"
        # Still locked right now -- the update went through around it, it did
        # not go through because the lock happened to clear.
        assert locker.poll() is None
        assert locked.exists()
        # Preserved in place: never moved to the backup, never restored.
        assert (install / "site_cookies.txt").read_text(encoding="utf-8") == "user cookies"
        assert (install / "podcasts" / "episode.mp3").read_text(encoding="utf-8") == "audio"
        # The old build really did move out.
        assert not (install / "_internal" / "old.pyd").exists()
        assert not list(tmp_path.glob("BlindRSS_backup_*"))
    finally:
        if locker.poll() is None:
            locker.kill()
            locker.wait(timeout=10)

    assert locked.read_text(encoding="utf-8") == "cookie jar"


def test_update_helper_stops_a_browser_running_outside_the_install(tmp_path):
    """A Chromium launched from Program Files is matched by --user-data-dir."""
    if not _windows_helper_fixture_ready():
        return

    ps_exe = _system32() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    install, staging, temp_root = _lay_out_update(tmp_path)
    helper_copy = tmp_path / "BlindRSS_update_helper_browser.bat"
    shutil.copy2(HELPER, helper_copy)

    profile = install / "feed_browser_profile"
    profile.mkdir(parents=True, exist_ok=True)
    browser = subprocess.Popen(
        [
            str(ps_exe), "-NoProfile", "-Command",
            "Start-Sleep -Seconds 180 # --user-data-dir=" + str(profile),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        time.sleep(2)
        assert browser.poll() is None
        completed = _run_update(tmp_path, helper_copy, install, staging, temp_root)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert browser.wait(timeout=20) is not None
    finally:
        if browser.poll() is None:
            browser.kill()
            browser.wait(timeout=10)
