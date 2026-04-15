import os
import sys

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import windows_integration as winint


def test_desktop_dir_uses_windows_shell_path(monkeypatch):
    monkeypatch.setattr(winint, "is_windows", lambda: True)
    monkeypatch.setattr(
        winint,
        "_run_powershell",
        lambda _script, timeout_s=10: (True, r"C:\Users\admin\OneDrive\Desktop"),
    )
    path = winint._desktop_dir()
    assert path == r"C:\Users\admin\OneDrive\Desktop"


def test_desktop_dir_falls_back_to_onedrive_env_when_shell_fails(monkeypatch):
    monkeypatch.setattr(winint, "is_windows", lambda: True)
    monkeypatch.setattr(winint, "_run_powershell", lambda _script, timeout_s=10: (False, "nope"))
    monkeypatch.setenv("OneDrive", r"C:\Users\admin\OneDrive")
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.setattr(
        winint.os.path,
        "isdir",
        lambda p: str(p).replace("/", "\\").lower() == r"c:\users\admin\onedrive\desktop",
    )
    path = winint._desktop_dir()
    assert path.replace("/", "\\").lower() == r"c:\users\admin\onedrive\desktop"


def test_get_start_menu_shortcut_path_uses_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\admin\AppData\Roaming")
    path = winint.get_start_menu_shortcut_path("BlindRSS")
    assert path.replace("/", "\\") == (
        r"C:\Users\admin\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\BlindRSS.lnk"
    )


def test_taskbar_dir_uses_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\admin\AppData\Roaming")
    path = winint._taskbar_dir()
    assert path.replace("/", "\\") == (
        r"C:\Users\admin\AppData\Roaming\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
    )


def test_ensure_notification_prereqs_creates_start_menu_shortcut(monkeypatch, tmp_path):
    target_lnk = tmp_path / "BlindRSS.lnk"

    monkeypatch.setattr(winint, "is_windows", lambda: True)
    monkeypatch.setattr(
        winint,
        "set_process_app_user_model_id",
        lambda app_user_model_id=winint.APP_USER_MODEL_ID: (True, f"Process AppUserModelID set: {app_user_model_id}"),
    )
    monkeypatch.setattr(
        winint,
        "register_app_user_model_id",
        lambda app_user_model_id=winint.APP_USER_MODEL_ID, app_name=winint.APP_NAME: (
            True,
            f"Registered AppUserModelID: {app_user_model_id}",
        ),
    )
    monkeypatch.setattr(winint, "get_start_menu_shortcut_path", lambda app_name=winint.APP_NAME: str(target_lnk))
    monkeypatch.setattr(
        winint,
        "get_launch_parts",
        lambda: (r"C:\BlindRSS\BlindRSS.exe", "", r"C:\BlindRSS", r"C:\BlindRSS\BlindRSS.exe"),
    )
    monkeypatch.setattr(
        winint,
        "_create_shortcut",
        lambda shortcut_path, target_path, arguments, working_dir, icon_path: (True, "OK"),
    )

    ok, msg = winint.ensure_notification_prerequisites(ensure_start_menu_shortcut=True)
    assert ok is True
    assert "Registered AppUserModelID" in msg
    assert "Start Menu shortcut created" in msg


def test_ensure_notification_prereqs_fails_when_process_appid_fails(monkeypatch):
    monkeypatch.setattr(winint, "is_windows", lambda: True)
    monkeypatch.setattr(
        winint,
        "set_process_app_user_model_id",
        lambda app_user_model_id=winint.APP_USER_MODEL_ID: (False, "failed to set app id"),
    )
    monkeypatch.setattr(
        winint,
        "register_app_user_model_id",
        lambda app_user_model_id=winint.APP_USER_MODEL_ID, app_name=winint.APP_NAME: (True, "registered"),
    )

    ok, msg = winint.ensure_notification_prerequisites(ensure_start_menu_shortcut=False)
    assert ok is False
    assert "failed to set app id" in msg.lower()
