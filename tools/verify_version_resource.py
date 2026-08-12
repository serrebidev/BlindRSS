# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Verify the Windows VERSIONINFO resource stamped into a built executable.

Screen readers read the *executable's* Win32 VERSIONINFO resource when the
user asks "what application is this and what version?" -- NVDA's app-version
report (it reads ``ProductName``/``ProductVersion`` via
``GetFileVersionInfo``) and the JAWS equivalent both do. When that resource is
missing, the screen reader says "Application unknown, version not detected"
instead of "BlindRSS, version 1.127.13"; when it is stale, it confidently
announces the wrong version.

``main.spec`` stamps the resource from ``core/version.py`` at build time. This
script reads it back out of the built ``.exe`` so a broken or stale stamp fails
the build instead of shipping silently: nothing else in the pipeline would ever
notice, because the resource is invisible to the running app.

Usage::

    python tools/verify_version_resource.py dist/BlindRSS/BlindRSS.exe [more.exe ...]

The first candidate path that exists is checked. Exits non-zero (with the
mismatch spelled out) when the resource is absent or disagrees with
``core/version.py``.
"""

from __future__ import annotations

import argparse
import os
import platform
import re

# Strings a screen reader reads back to the user. ProductName is what NVDA
# announces as the application name; ProductVersion is the version.
REQUIRED_KEYS = ("ProductName", "ProductVersion", "FileVersion", "FileDescription")

EXPECTED_PRODUCT_NAME = "BlindRSS"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_app_version(repo_root: str = _REPO_ROOT) -> str:
    """Return ``APP_VERSION`` from ``core/version.py`` without importing the app.

    Mirrors the reader in main.spec/portable.spec: the frozen app's version is
    a single source of truth that build tooling must not drift from.
    """
    path = os.path.join(repo_root, "core", "version.py")
    with open(path, "r", encoding="utf-8") as fh:
        match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', fh.read())
    if not match:
        raise ValueError(f"APP_VERSION not found in {path}")
    return match.group(1)


def read_version_strings(exe_path: str) -> dict:
    """Read the VERSIONINFO string table out of a Windows executable.

    Uses the same Win32 calls a screen reader uses, so what this returns is
    literally what NVDA/JAWS would announce. Returns an empty dict when the
    file carries no version resource at all.
    """
    import ctypes
    from ctypes import wintypes

    version_dll = ctypes.WinDLL("version.dll")
    version_dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
    version_dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version_dll.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    ]
    version_dll.GetFileVersionInfoW.restype = wintypes.BOOL
    version_dll.VerQueryValueW.argtypes = [
        wintypes.LPCVOID, wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT),
    ]
    version_dll.VerQueryValueW.restype = wintypes.BOOL

    size = version_dll.GetFileVersionInfoSizeW(exe_path, None)
    if not size:
        return {}
    buf = ctypes.create_string_buffer(size)
    if not version_dll.GetFileVersionInfoW(exe_path, 0, size, buf):
        return {}

    # The string table is keyed by the resource's language/codepage pair; read
    # the first translation rather than assuming 040904B0.
    block = wintypes.LPVOID()
    length = wintypes.UINT()
    if not version_dll.VerQueryValueW(
        buf, "\\VarFileInfo\\Translation", ctypes.byref(block), ctypes.byref(length)
    ) or length.value < 4:
        return {}
    langs = ctypes.cast(block, ctypes.POINTER(ctypes.c_uint16))
    lang, codepage = langs[0], langs[1]

    values = {}
    for key in REQUIRED_KEYS:
        sub_block = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{key}"
        text = wintypes.LPVOID()
        chars = wintypes.UINT()
        if version_dll.VerQueryValueW(
            buf, sub_block, ctypes.byref(text), ctypes.byref(chars)
        ) and chars.value and text.value:
            values[key] = ctypes.wstring_at(text.value, chars.value).rstrip("\x00")
    return values


def check_version_strings(
    values: dict,
    expected_version: str,
    expected_product_name: str = EXPECTED_PRODUCT_NAME,
) -> list:
    """Return a list of human-readable problems; empty means the stamp is good.

    Kept free of ctypes and file I/O so the rules are unit-testable off
    Windows.
    """
    problems = []
    if not values:
        problems.append(
            "no VERSIONINFO resource at all -- screen readers will announce "
            "\"Application unknown, version not detected\""
        )
        return problems

    for key in REQUIRED_KEYS:
        if not (values.get(key) or "").strip():
            problems.append(f"{key} is missing or empty")

    product_name = (values.get("ProductName") or "").strip()
    if product_name and product_name != expected_product_name:
        problems.append(
            f"ProductName is {product_name!r}, expected {expected_product_name!r}"
        )

    for key in ("ProductVersion", "FileVersion"):
        stamped = (values.get(key) or "").strip()
        if stamped and stamped != expected_version:
            problems.append(
                f"{key} is {stamped!r}, expected {expected_version!r} "
                "(core/version.py) -- a screen reader would report the wrong version"
            )
    return problems


def _first_existing(paths):
    for path in paths:
        if path and os.path.isfile(path):
            return path
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the Windows VERSIONINFO resource of a built executable."
    )
    parser.add_argument(
        "candidates", nargs="+",
        help="executable path(s); the first one that exists is checked",
    )
    parser.add_argument(
        "--expected-version", default=None,
        help="version to require (default: APP_VERSION from core/version.py)",
    )
    args = parser.parse_args(argv)

    if platform.system() != "Windows":
        print("[BlindRSS Build] Not Windows; skipping version-resource check.")
        return 0

    exe_path = _first_existing(args.candidates)
    if not exe_path:
        print(
            "[X] Version resource check: none of these executables exist:\n    "
            + "\n    ".join(args.candidates)
        )
        return 1

    expected = args.expected_version or read_app_version()
    try:
        values = read_version_strings(exe_path)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[X] Version resource check failed to read {exe_path}: {exc}")
        return 1

    problems = check_version_strings(values, expected)
    if problems:
        print(f"[X] Version resource check FAILED for {exe_path}:")
        for problem in problems:
            print(f"    - {problem}")
        print(
            "    Fix the VSVersionInfo block in main.spec (see the comment "
            "there) and rebuild."
        )
        return 1

    print(
        f"[BlindRSS Build] Version resource OK: "
        f"{values.get('ProductName')} {values.get('ProductVersion')} "
        f"({os.path.basename(exe_path)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
