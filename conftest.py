# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
from pathlib import Path

# Below-normal on Windows; a modest positive nice value elsewhere.
_WINDOWS_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_POSIX_NICE_INCREMENT = 5


def _lower_process_priority() -> None:
    """Run the suite at reduced priority so the desktop stays usable.

    A full run costs well over a core for a minute and a half, which on a
    machine that is already busy is enough to make NVDA stutter and the UI
    stop responding — the suite is never the urgent thing, so it should yield
    to whatever the user is actually doing. Priority (not affinity or worker
    count) is the right lever: the tests still get every idle cycle and the
    wall time barely moves, they simply stop winning against the foreground.

    Set BLINDRSS_TEST_PRIORITY=normal to opt out (e.g. for timing runs or CI).
    """
    if str(os.environ.get("BLINDRSS_TEST_PRIORITY", "")).strip().lower() == "normal":
        return
    try:
        if sys.platform.startswith("win"):
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            # Declare the signatures: HANDLE is 64-bit on a 64-bit build, and
            # ctypes' default c_int restype truncates the -1 pseudo-handle, so
            # the call silently fails and the suite keeps normal priority.
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.GetCurrentProcess.argtypes = []
            kernel32.SetPriorityClass.restype = wintypes.BOOL
            kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]

            kernel32.SetPriorityClass(
                kernel32.GetCurrentProcess(), _WINDOWS_BELOW_NORMAL_PRIORITY_CLASS
            )
        else:
            # getattr keeps type checkers happy: os.nice is POSIX-only.
            nice = getattr(os, "nice", None)
            if nice is not None:
                nice(_POSIX_NICE_INCREMENT)
    except Exception:
        # Never let a niceness tweak break the run.
        pass


def _can_use_temp_base(path: Path) -> bool:
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False
    if not path.is_dir():
        return False
    try:
        with os.scandir(path):
            return True
    except OSError:
        return False


def pytest_configure(config):
    _lower_process_priority()

    raw_basetemp = getattr(config.option, "basetemp", None)
    if not raw_basetemp:
        return

    base = Path(raw_basetemp)
    if not base.is_absolute():
        base = Path.cwd() / base

    if _can_use_temp_base(base):
        return

    # Some Windows runs leave this repo-local temp base owned by an elevated
    # context. Keep pytest repo-local by falling back to a sibling directory.
    parent = base.parent
    fallback = parent / f"{base.name}-fallback"
    if _can_use_temp_base(fallback):
        config.option.basetemp = str(fallback)
        return

    config.option.basetemp = str(parent / f"{base.name}-{os.getpid()}")
