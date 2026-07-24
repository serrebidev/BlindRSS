# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Best-effort direct speech adapters for screen readers.

This module is intentionally small and GUI-free. Standard accessibility events
remain useful, but command feedback such as "not found" needs a direct path
when a screen reader ignores UIA/MSAA notifications. On Windows that path is the
NVDA/JAWS controller APIs; on macOS it is the built-in ``say`` command (macOS
has no stdlib bridge to post a VoiceOver announcement, and the app deliberately
avoids the pyobjc dependency), which gives VoiceOver users spoken confirmation
the wx status bar alone does not.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

try:
    from ctypes import wintypes
except (ImportError, ValueError):
    # ctypes.wintypes only imports on Windows; the module must still load on
    # macOS/Linux for the cross-platform speak_status path below.
    wintypes = None  # type: ignore

LOG = logging.getLogger(__name__)

_NVDA_DLL = None
_NVDA_LOAD_ATTEMPTED = False

# macOS `say` process management: keep the last spawned process so an
# interrupting announcement can cancel the previous one instead of overlapping.
_SAY_LOCK = threading.Lock()
_SAY_PROC = None
_SAY_PATH_ATTEMPTED = False
_SAY_PATH = None


def speak_status(message: str, *, interrupt: bool = True) -> bool:
    """Speak a short status string through the platform screen reader.

    Windows routes through NVDA or JAWS; macOS through the ``say`` command.
    Returns True only when a speech path reports success. All errors fail closed
    so callers can continue to UIA/MSAA/bell fallbacks.
    """
    text = str(message or "").strip()
    if not text:
        return False
    if sys.platform == "darwin":
        return _speak_macos_say(text, interrupt=interrupt)
    if not sys.platform.startswith("win"):
        return False
    if _speak_nvda(text, interrupt=interrupt):
        return True
    if _speak_jaws(text, interrupt=interrupt):
        return True
    return False


def _macos_say_path():
    """Locate the macOS ``say`` binary once (cached)."""
    global _SAY_PATH_ATTEMPTED, _SAY_PATH
    if _SAY_PATH_ATTEMPTED:
        return _SAY_PATH
    _SAY_PATH_ATTEMPTED = True
    _SAY_PATH = shutil.which("say") or (
        "/usr/bin/say" if os.path.isfile("/usr/bin/say") else None
    )
    return _SAY_PATH


def _speak_macos_say(text: str, *, interrupt: bool = True) -> bool:
    """Speak ``text`` via the macOS ``say`` command, non-blocking.

    When ``interrupt`` is True a still-speaking prior announcement is terminated
    first so status updates replace each other rather than queue up. Returns True
    once the process is launched; speech itself is asynchronous.
    """
    global _SAY_PROC
    say = _macos_say_path()
    if not say:
        return False
    try:
        with _SAY_LOCK:
            if interrupt and _SAY_PROC is not None and _SAY_PROC.poll() is None:
                try:
                    _SAY_PROC.terminate()
                except Exception:
                    pass
            _SAY_PROC = subprocess.Popen(
                [say, "--", text],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as exc:
        LOG.debug("macOS say speech failed: %s", exc)
        return False


def braille_message(message: str) -> bool:
    """Show a short message on the NVDA Braille display, if NVDA is running.

    Returns True only when NVDA's controller client accepts the message. This is
    the direct-Braille fallback used when accessible-output2 is not available;
    JAWS has no comparable simple Braille COM entry point, so it is NVDA-only.
    """
    if not sys.platform.startswith("win"):
        return False
    text = str(message or "").strip()
    if not text:
        return False
    dll = _load_nvda_controller()
    if dll is None:
        return False
    try:
        if int(dll.nvdaController_testIfRunning()) != 0:
            return False
        fn = getattr(dll, "nvdaController_brailleMessage", None)
        if fn is None:
            return False
        return int(fn(str(text))) == 0
    except Exception as exc:
        LOG.debug("NVDA controller Braille failed: %s", exc)
        return False


def _speak_nvda(text: str, *, interrupt: bool = True) -> bool:
    dll = _load_nvda_controller()
    if dll is None:
        return False
    try:
        if int(dll.nvdaController_testIfRunning()) != 0:
            return False
        if interrupt:
            try:
                dll.nvdaController_cancelSpeech()
            except Exception:
                pass
        return int(dll.nvdaController_speakText(str(text))) == 0
    except Exception as exc:
        LOG.debug("NVDA controller speech failed: %s", exc)
        return False


def _load_nvda_controller():
    global _NVDA_DLL, _NVDA_LOAD_ATTEMPTED
    if _NVDA_LOAD_ATTEMPTED:
        return _NVDA_DLL
    _NVDA_LOAD_ATTEMPTED = True
    for dll_path in _nvda_controller_candidates():
        try:
            dll = ctypes.WinDLL(str(dll_path))
            dll.nvdaController_testIfRunning.argtypes = []
            dll.nvdaController_testIfRunning.restype = ctypes.c_ulong
            dll.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            dll.nvdaController_speakText.restype = ctypes.c_ulong
            dll.nvdaController_cancelSpeech.argtypes = []
            dll.nvdaController_cancelSpeech.restype = ctypes.c_ulong
            try:
                dll.nvdaController_brailleMessage.argtypes = [ctypes.c_wchar_p]
                dll.nvdaController_brailleMessage.restype = ctypes.c_ulong
            except Exception:
                # Older controller clients may lack the Braille entry point.
                pass
            _NVDA_DLL = dll
            return _NVDA_DLL
        except Exception as exc:
            LOG.debug("Could not load NVDA controller client from %s: %s", dll_path, exc)
    _NVDA_DLL = None
    return None


def _nvda_controller_candidates() -> list[Path]:
    names = (
        "nvdaControllerClient.dll",
        "nvdaControllerClient64.dll",
    )
    roots: list[Path] = []
    env_path = os.environ.get("BLINDRSS_NVDA_CONTROLLER_DLL")
    if env_path:
        roots.append(Path(env_path))
    try:
        roots.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parents[1])

    candidates: list[Path] = []
    for root in roots:
        if root.suffix.lower() == ".dll":
            candidates.append(root)
            continue
        for rel_root in (
            root,
            root / "bin",
            root / "_internal",
            root / "_internal" / "bin",
        ):
            for name in names:
                candidates.append(rel_root / name)

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except Exception:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            deduped.append(candidate)
    return deduped


def _speak_jaws(text: str, *, interrupt: bool = True) -> bool:
    # Do not instantiate or call the JAWS COM API unless JAWS/Fusion appears to
    # be active. A COM object existing on disk is not enough to count as speech.
    if not _windows_process_running({"jfw.exe", "jaws.exe", "fusion.exe"}):
        return False
    if _speak_jaws_via_pywin32(text, interrupt=interrupt):
        return True
    return _speak_jaws_via_comtypes(text, interrupt=interrupt)


def _speak_jaws_via_pywin32(text: str, *, interrupt: bool = True) -> bool:
    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except Exception:
        return False

    initialized = False
    try:
        pythoncom.CoInitialize()
        initialized = True
        try:
            jaws = win32com.client.Dispatch("FreedomSci.JawsApi")
        except pywintypes.com_error:
            jaws = win32com.client.Dispatch("freedomsci.jawsapi")
        return bool(jaws.SayString(str(text), bool(interrupt)))
    except Exception as exc:
        LOG.debug("JAWS COM speech via pywin32 failed: %s", exc)
        return False
    finally:
        if initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _speak_jaws_via_comtypes(text: str, *, interrupt: bool = True) -> bool:
    try:
        import comtypes
        import comtypes.client
    except Exception:
        return False

    initialized = False
    try:
        try:
            comtypes.CoInitialize()
            initialized = True
        except Exception:
            pass
        try:
            jaws = comtypes.client.CreateObject("FreedomSci.JawsApi")
        except Exception:
            jaws = comtypes.client.CreateObject("freedomsci.jawsapi")
        return bool(jaws.SayString(str(text), bool(interrupt)))
    except Exception as exc:
        LOG.debug("JAWS COM speech via comtypes failed: %s", exc)
        return False
    finally:
        if initialized:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


def _windows_process_running(names: set[str]) -> bool:
    if not sys.platform.startswith("win"):
        return False
    wanted = {name.lower() for name in names}
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return False

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return False
        while True:
            if str(entry.szExeFile).lower() in wanted:
                return True
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        return False
    except Exception as exc:
        LOG.debug("Screen-reader process enumeration failed: %s", exc)
        return False
    finally:
        try:
            kernel32.CloseHandle(snapshot)
        except Exception:
            pass


def _reset_for_tests() -> None:
    global _NVDA_DLL, _NVDA_LOAD_ATTEMPTED, _SAY_PROC, _SAY_PATH, _SAY_PATH_ATTEMPTED
    _NVDA_DLL = None
    _NVDA_LOAD_ATTEMPTED = False
    _SAY_PROC = None
    _SAY_PATH = None
    _SAY_PATH_ATTEMPTED = False
