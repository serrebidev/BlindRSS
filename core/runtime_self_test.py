# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Internal frozen-runtime verification used by macOS packaging."""

from __future__ import annotations

import ctypes
import importlib
import os
import shutil
import subprocess
import sys
import warnings


_REQUIRED_MODULES = (
    "core.article_extractor",
    "core.article_html",
    "core.discovery",
    "core.updater",
    "gui.accessibility",
    "gui.mainframe",
    "gui.player",
    "curl_cffi",
    "markdown",
    "pydoll.browser.chromium",
    "seleniumbase",
    "tld",
    "trafilatura",
    "wx.html2",
    "wx_accessible_webview",
)

_REQUIRED_TOOLS = {
    "yt-dlp": ("--version",),
    "deno": ("--version",),
    "ffmpeg": ("-version",),
}


def _check_fulltext() -> list[str]:
    try:
        from core import article_extractor
        from tld import get_tld

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            suffix = get_tld(
                "https://news.example.co.uk/runtime", fix_protocol=True
            )
        if suffix != "co.uk":
            return ["public-suffix data returned an unexpected result"]

        paragraphs = [
            (
                f"Paragraph {index} contains enough distinct article prose to verify "
                "that the packaged full-text extractor keeps the complete story when "
                "VoiceOver causes repeated prefetch and on-demand extraction passes."
            )
            for index in range(10)
        ]
        body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
        html = (
            "<html><head><title>Runtime extraction check</title></head><body>"
            f"<main><article><h1>Runtime extraction check</h1>{body}</article></main>"
            "</body></html>"
        )
        results = [
            article_extractor._extract_text_any(
                html, "https://example.com/runtime-extraction-check"
            )
            for _ in range(6)
        ]
    except Exception as exc:
        return [f"full-text extraction raised {type(exc).__name__}: {exc}"]
    if not results[0] or len(results[0]) < 500:
        return ["full-text extraction returned incomplete article text"]
    if any(result != results[0] for result in results[1:]):
        return ["full-text extraction changed across repeated passes"]
    return []


def _check_imports() -> list[str]:
    errors = []
    for module_name in _REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(
                f"could not import {module_name}: {type(exc).__name__}: {exc}"
            )
    return errors


def _check_tools() -> list[str]:
    errors = []
    for tool_name, args in _REQUIRED_TOOLS.items():
        tool_path = shutil.which(tool_name)
        if not tool_path:
            errors.append(f"bundled tool not found on PATH: {tool_name}")
            continue
        try:
            proc = subprocess.run(
                [tool_path, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            errors.append(f"could not run {tool_name}: {type(exc).__name__}: {exc}")
            continue
        if proc.returncode != 0:
            detail = (proc.stdout or "").strip().splitlines()
            suffix = f": {detail[-1]}" if detail else ""
            errors.append(f"{tool_name} exited with {proc.returncode}{suffix}")
    return errors


def _check_vlc() -> list[str]:
    lib_path = str(os.environ.get("PYTHON_VLC_LIB_PATH") or "").strip()
    plugin_path = str(os.environ.get("PYTHON_VLC_MODULE_PATH") or "").strip()
    errors = []
    if not lib_path or not os.path.isfile(lib_path):
        errors.append("bundled libVLC path is missing")
        return errors
    if not plugin_path or not os.path.isdir(plugin_path):
        errors.append("bundled VLC plugin path is missing")
    try:
        lib = ctypes.CDLL(lib_path)
        get_version = lib.libvlc_get_version
        get_version.restype = ctypes.c_char_p
        if not get_version():
            errors.append("bundled libVLC returned no version")
    except Exception as exc:
        errors.append(f"could not load bundled libVLC: {type(exc).__name__}: {exc}")
    return errors


def _check_update_support() -> list[str]:
    if sys.platform not in ("darwin", "linux"):
        return []
    try:
        from core import updater

        if updater.is_update_supported():
            return []
    except Exception as exc:
        return [f"could not check updater support: {type(exc).__name__}: {exc}"]
    return ["the packaged updater helper was not found"]


def run_runtime_self_test() -> int:
    """Return zero only when critical frozen macOS runtime paths are usable."""
    errors = []
    if not getattr(sys, "frozen", False):
        errors.append("runtime self-test requires a frozen build")
    errors.extend(_check_imports())
    errors.extend(_check_fulltext())
    errors.extend(_check_tools())
    errors.extend(_check_vlc())
    errors.extend(_check_update_support())
    if errors:
        for error in errors:
            print(f"Runtime self-test failed: {error}", file=sys.stderr)
        return 1
    print("Runtime self-test passed.")
    return 0
