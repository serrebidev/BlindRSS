import base64
import logging
import os
import shutil
import subprocess
import sys
import tempfile

try:
    import winreg
except Exception:  # pragma: no cover - non-Windows envs
    winreg = None


log = logging.getLogger(__name__)

APP_NAME = "BlindRSS"
APP_USER_MODEL_ID = "BlindRSS.App"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUMID_KEY_ROOT = r"Software\Classes\AppUserModelId"


def is_windows() -> bool:
    return bool(sys.platform.startswith("win"))


def _quote_cmd_arg(value: str) -> str:
    return subprocess.list2cmdline([str(value or "")]).strip()


def _ps_literal(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def get_launch_parts() -> tuple[str, str, str, str]:
    """Return launch tuple: (target_path, arguments, working_dir, icon_path)."""
    if getattr(sys, "frozen", False):
        exe_path = os.path.abspath(sys.executable)
        return exe_path, "", os.path.dirname(exe_path), exe_path

    python_exe = os.path.abspath(sys.executable or "python")
    pythonw_exe = python_exe
    low = python_exe.lower()
    if low.endswith("python.exe"):
        candidate = python_exe[:-10] + "pythonw.exe"
        if os.path.exists(candidate):
            pythonw_exe = candidate

    script_path = ""
    try:
        if sys.argv and sys.argv[0]:
            script_path = os.path.abspath(sys.argv[0])
    except Exception:
        script_path = ""
    if not script_path:
        script_path = os.path.abspath("main.py")

    args = _quote_cmd_arg(script_path)
    return pythonw_exe, args, os.path.dirname(script_path), python_exe


def build_startup_command() -> str:
    target, args, _working_dir, _icon = get_launch_parts()
    cmd = _quote_cmd_arg(target)
    if args:
        cmd = f"{cmd} {args}"
    return cmd


def set_startup_enabled(enabled: bool, app_name: str = APP_NAME) -> tuple[bool, str]:
    if not is_windows() or winreg is None:
        return False, "Startup registration is only available on Windows."

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if bool(enabled):
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, build_startup_command())
                return True, "BlindRSS will now start when you sign in to Windows."
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
            return True, "BlindRSS startup on sign-in has been disabled."
    except Exception as e:
        log.exception("Failed to update Windows startup setting")
        return False, f"Could not update Windows startup setting: {e}"


def _start_menu_programs_dir() -> str:
    # os.path.expandvars only expands %VAR% on Windows; read env directly so
    # callers and tests driven from POSIX hosts get a real path, not a literal.
    appdata = os.environ.get("APPDATA") or os.path.expandvars("%APPDATA%")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")


def get_start_menu_shortcut_path(app_name: str = APP_NAME) -> str:
    resolved_name = str(app_name or APP_NAME).strip() or APP_NAME
    return os.path.join(_start_menu_programs_dir(), f"{resolved_name}.lnk")


def set_process_app_user_model_id(app_user_model_id: str = APP_USER_MODEL_ID) -> tuple[bool, str]:
    if not is_windows():
        return False, "AppUserModelID is only available on Windows."

    app_id = str(app_user_model_id or "").strip()
    if not app_id:
        return False, "AppUserModelID cannot be empty."

    try:
        import ctypes

        fn = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        fn.argtypes = [ctypes.c_wchar_p]
        fn.restype = ctypes.c_long
        hr = int(fn(str(app_id)))
        if hr != 0:
            return False, f"SetCurrentProcessExplicitAppUserModelID failed (HRESULT 0x{(hr & 0xFFFFFFFF):08X})."
        return True, f"Process AppUserModelID set: {app_id}"
    except Exception as e:
        log.exception("Failed to set process AppUserModelID")
        return False, f"Could not set process AppUserModelID: {e}"


def register_app_user_model_id(
    app_user_model_id: str = APP_USER_MODEL_ID,
    app_name: str = APP_NAME,
) -> tuple[bool, str]:
    if not is_windows() or winreg is None:
        return False, "AppUserModelID registration is only available on Windows."

    app_id = str(app_user_model_id or "").strip()
    if not app_id:
        return False, "AppUserModelID cannot be empty."

    try:
        key_path = rf"{_AUMID_KEY_ROOT}\{app_id}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, str(app_name or APP_NAME))
            try:
                _target, _args, _working_dir, icon_path = get_launch_parts()
                if icon_path:
                    winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))
            except Exception:
                pass
        return True, f"Registered AppUserModelID: {app_id}"
    except Exception as e:
        log.exception("Failed to register AppUserModelID")
        return False, f"Could not register AppUserModelID: {e}"


def ensure_notification_prerequisites(
    *,
    app_name: str = APP_NAME,
    app_user_model_id: str = APP_USER_MODEL_ID,
    ensure_start_menu_shortcut: bool = True,
) -> tuple[bool, str]:
    if not is_windows():
        return False, "Notification prerequisites are only available on Windows."

    messages: list[str] = []
    ok_all = True

    ok_appid, msg_appid = set_process_app_user_model_id(app_user_model_id)
    messages.append(msg_appid)
    if not ok_appid:
        ok_all = False

    ok_reg, msg_reg = register_app_user_model_id(app_user_model_id=app_user_model_id, app_name=app_name)
    messages.append(msg_reg)
    if not ok_reg:
        ok_all = False

    if ensure_start_menu_shortcut:
        start_lnk = get_start_menu_shortcut_path(app_name=app_name)
        if os.path.exists(start_lnk):
            messages.append(f"Start Menu shortcut already exists: {start_lnk}")
        else:
            target, args, working_dir, icon_path = get_launch_parts()
            made, msg = _create_shortcut(start_lnk, target, args, working_dir, icon_path)
            if made:
                messages.append(f"Start Menu shortcut created: {start_lnk}")
            else:
                ok_all = False
                messages.append(f"Start Menu shortcut creation failed: {msg}")

    return ok_all, " | ".join([m for m in messages if m])


def _run_powershell(script: str, timeout_s: int = 30) -> tuple[bool, str]:
    if not is_windows():
        return False, "PowerShell integration is only available on Windows."
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(5, int(timeout_s)))
    except Exception as e:
        return False, str(e)

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode == 0:
        return True, out
    return False, err or out or f"PowerShell exited with code {proc.returncode}."


def _create_shortcut(shortcut_path: str, target_path: str, arguments: str, working_dir: str, icon_path: str) -> tuple[bool, str]:
    os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$ws = New-Object -ComObject WScript.Shell",
            f"$shortcut = $ws.CreateShortcut({_ps_literal(shortcut_path)})",
            f"$shortcut.TargetPath = {_ps_literal(target_path)}",
            f"$shortcut.Arguments = {_ps_literal(arguments)}",
            f"$shortcut.WorkingDirectory = {_ps_literal(working_dir)}",
            f"$shortcut.IconLocation = {_ps_literal(icon_path)}",
            "$shortcut.Description = 'BlindRSS'",
            "$shortcut.Save()",
        ]
    )
    ok, msg = _run_powershell(script, timeout_s=20)
    if not ok:
        return False, msg
    if not os.path.exists(shortcut_path):
        return False, "Shortcut was not created."
    return True, "OK"


def _taskbar_dir() -> str:
    appdata = os.environ.get("APPDATA") or os.path.expandvars("%APPDATA%")
    return os.path.join(
        appdata,
        "Microsoft",
        "Internet Explorer",
        "Quick Launch",
        "User Pinned",
        "TaskBar",
    )


def _pin_shortcut_to_taskbar(shortcut_path: str) -> tuple[bool, str]:
    # This is best-effort; modern Windows can hide taskbar pin verbs.
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$path = {_ps_literal(shortcut_path)}",
            "if (-not (Test-Path -LiteralPath $path)) { throw 'Shortcut not found.' }",
            "$shell = New-Object -ComObject Shell.Application",
            "$folder = Split-Path -Path $path",
            "$file = Split-Path -Path $path -Leaf",
            "$item = $shell.NameSpace($folder).ParseName($file)",
            "if (-not $item) { throw 'Unable to load shortcut item.' }",
            "$verbs = @($item.Verbs())",
            "$normalized = $verbs | ForEach-Object { [PSCustomObject]@{ Raw=$_; Name=($_.Name -replace '&','').Trim().ToLowerInvariant() } }",
            "$already = $normalized | Where-Object { $_.Name -like '*unpin from taskbar*' } | Select-Object -First 1",
            "if ($already) { Write-Output 'already-pinned'; exit 0 }",
            "$pin = $normalized | Where-Object { $_.Name -like '*pin to taskbar*' -or $_.Name -like '*taskbarpin*' } | Select-Object -First 1",
            "if ($pin) { $pin.Raw.DoIt(); Write-Output 'pinned'; exit 0 }",
            "exit 1",
        ]
    )
    return _run_powershell(script, timeout_s=20)


def _desktop_dir() -> str:
    # Prefer Windows-known Desktop path (handles OneDrive redirection/localization).
    if is_windows():
        script = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "$p = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)",
                "if (-not $p) {",
                "  $ws = New-Object -ComObject WScript.Shell",
                "  $p = $ws.SpecialFolders.Item('Desktop')",
                "}",
                "if ($p) { Write-Output $p }",
            ]
        )
        ok, msg = _run_powershell(script, timeout_s=10)
        if ok and msg:
            for line in str(msg).splitlines():
                path = str(line or "").strip()
                if path:
                    return path

    candidates = []
    one_drive = str(os.environ.get("OneDrive", "") or "").strip()
    if one_drive:
        candidates.append(os.path.join(one_drive, "Desktop"))
    one_drive_consumer = str(os.environ.get("OneDriveConsumer", "") or "").strip()
    if one_drive_consumer:
        candidates.append(os.path.join(one_drive_consumer, "Desktop"))
    candidates.append(os.path.join(os.path.expanduser("~"), "Desktop"))

    for path in candidates:
        if path and os.path.isdir(path):
            return path
    for path in candidates:
        if path:
            return path
    return os.path.join(os.path.expanduser("~"), "Desktop")


def create_shortcuts(
    *,
    desktop: bool = False,
    start_menu: bool = False,
    taskbar: bool = False,
    app_name: str = APP_NAME,
) -> dict[str, tuple[bool, str]]:
    results: dict[str, tuple[bool, str]] = {}
    if not is_windows():
        msg = "Shortcuts are only supported on Windows."
        if desktop:
            results["desktop"] = (False, msg)
        if start_menu:
            results["start_menu"] = (False, msg)
        if taskbar:
            results["taskbar"] = (False, msg)
        return results

    target, args, working_dir, icon_path = get_launch_parts()
    lnk_name = f"{app_name}.lnk"

    if desktop:
        desktop_dir = _desktop_dir()
        desktop_lnk = os.path.join(desktop_dir, lnk_name)
        results["desktop"] = _create_shortcut(desktop_lnk, target, args, working_dir, icon_path)

    if start_menu:
        start_lnk = get_start_menu_shortcut_path(app_name=app_name)
        results["start_menu"] = _create_shortcut(start_lnk, target, args, working_dir, icon_path)

    if taskbar:
        temp_dir = tempfile.mkdtemp(prefix="blindrss_shortcut_")
        try:
            temp_lnk = os.path.join(temp_dir, lnk_name)
            made_temp, made_msg = _create_shortcut(temp_lnk, target, args, working_dir, icon_path)
            if made_temp:
                pinned, pin_msg = _pin_shortcut_to_taskbar(temp_lnk)
                if pinned:
                    results["taskbar"] = (True, "Pinned to taskbar.")
                else:
                    taskbar_lnk = os.path.join(_taskbar_dir(), lnk_name)
                    made_tb, msg_tb = _create_shortcut(taskbar_lnk, target, args, working_dir, icon_path)
                    if made_tb:
                        results["taskbar"] = (
                            True,
                            "Created taskbar shortcut file (pin verb unavailable on this Windows build).",
                        )
                    else:
                        results["taskbar"] = (False, pin_msg or msg_tb)
            else:
                results["taskbar"] = (False, made_msg)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return results
