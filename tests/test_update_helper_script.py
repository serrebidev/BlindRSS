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


def test_successful_update_exits_without_modal_ready_prompt():
    text = MAINFRAME.read_text(encoding="utf-8")

    assert 'wx.MessageBox(msg, "Update Ready"' not in text
    assert "wx.CallAfter(self.real_close)" in text
