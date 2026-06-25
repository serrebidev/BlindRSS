"""macOS startup registration via a per-user LaunchAgent.

Pure stdlib (no pyobjc). Enabling writes a LaunchAgent plist to
``~/Library/LaunchAgents`` and loads it with ``launchctl`` so BlindRSS starts
when the user logs in; disabling unloads and removes the plist. The launch
command is shared with the Windows path via
``core.windows_integration.get_launch_parts`` so both platforms launch the same
target.
"""

import logging
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path


log = logging.getLogger(__name__)

LAUNCH_AGENT_LABEL = "com.serrebidev.blindrss"
_LAUNCHCTL_TIMEOUT_S = 20


def is_macos() -> bool:
    return sys.platform == "darwin"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    """Path to the per-user LaunchAgent plist for BlindRSS."""
    return _launch_agents_dir() / f"{LAUNCH_AGENT_LABEL}.plist"


def _program_arguments() -> list[str]:
    """Build the LaunchAgent ProgramArguments from the shared launch parts.

    For a frozen ``.app`` the target is the bundle's executable (``sys.executable``);
    for a source checkout it's the python interpreter plus the script path. The
    arguments string may be empty.
    """
    from core import windows_integration

    target, arguments, _working_dir, _icon = windows_integration.get_launch_parts()
    program_args = [str(target)]
    if arguments:
        program_args.extend(shlex.split(arguments))
    return program_args


def _run_launchctl(args: list[str]) -> tuple[bool, str]:
    cmd = ["launchctl", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_LAUNCHCTL_TIMEOUT_S)
    except Exception as e:
        return False, str(e)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode == 0:
        return True, out
    return False, err or out or f"launchctl exited with code {proc.returncode}."


def set_macos_startup_enabled(enabled: bool) -> tuple[bool, str]:
    if not is_macos():
        return False, "Startup registration is only available on macOS."

    target = plist_path()
    try:
        if bool(enabled):
            program_args = _program_arguments()
            if not program_args or not program_args[0]:
                return False, "Could not determine how to launch BlindRSS."

            target.parent.mkdir(parents=True, exist_ok=True)
            plist = {
                "Label": LAUNCH_AGENT_LABEL,
                "ProgramArguments": program_args,
                "RunAtLoad": True,
            }
            with open(target, "wb") as fh:
                plistlib.dump(plist, fh)

            # Unload first so a stale definition is replaced; ignore its result.
            _run_launchctl(["unload", str(target)])
            ok, msg = _run_launchctl(["load", "-w", str(target)])
            # launchctl returns non-zero when the agent is already loaded; the
            # plist is written and that state is still "enabled", so accept it.
            if not ok and "already loaded" not in msg.lower():
                log.warning("launchctl load failed for %s: %s", target, msg)
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    log.warning(
                        "Could not remove failed LaunchAgent plist %s: %s",
                        target,
                        cleanup_error,
                    )
                    return (
                        False,
                        "Could not register BlindRSS to start at login: "
                        f"{msg} (the failed plist could not be removed: {cleanup_error})",
                    )
                return False, f"Could not register BlindRSS to start at login: {msg}"
            return True, "BlindRSS will now start when you log in."

        # Disable: unload (ignore errors) then remove the plist.
        _run_launchctl(["unload", "-w", str(target)])
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return True, "BlindRSS startup on login has been disabled."
    except Exception as e:
        log.exception("Failed to update macOS startup setting")
        return False, f"Could not update macOS startup setting: {e}"
