# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Small, bounded pytubefix fallback for YouTube media extraction.

yt-dlp remains BlindRSS's primary YouTube extractor.  This module is imported
only after every ordinary yt-dlp route has failed and before the much heavier
hidden Chromium bootstrap.

pytubefix 10.11 depends on ``nodejs-wheel-binaries`` solely to run its bundled
signature-decipher worker.  BlindRSS already ships Deno for yt-dlp, so frozen
builds deliberately exclude the 100+ MB duplicate Node runtime.  The worker is
CommonJS; Deno can run it with automatic CommonJS detection and environment
access (the upstream Node process has the same environment access).
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import socket
import subprocess
import sys
import threading
import types
from typing import Any

from core import utils
from core.dependency_check import _find_executable_path


log = logging.getLogger(__name__)
_extract_lock = threading.Lock()
_runner_configured_for = ""


def _install_nodejs_import_stub() -> None:
    """Let pytubefix import without packaging its duplicate Node executable."""
    if "nodejs_wheel.executable" in sys.modules:
        return
    package = types.ModuleType("nodejs_wheel")
    package.__path__ = []
    executable = types.ModuleType("nodejs_wheel.executable")
    executable.ROOT_DIR = ""
    package.executable = executable
    sys.modules["nodejs_wheel"] = package
    sys.modules["nodejs_wheel.executable"] = executable


def _configure_deno_runner(deno_path: str) -> None:
    """Route pytubefix's signature worker through BlindRSS's bundled Deno."""
    global _runner_configured_for
    resolved = os.path.abspath(str(deno_path or ""))
    if not resolved:
        raise RuntimeError("Deno is unavailable for pytubefix")
    if _runner_configured_for == resolved:
        return

    from pytubefix.sig_nsig import node_runner

    def _start_process(self) -> None:
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        self.proc = subprocess.Popen(
            [
                resolved,
                "run",
                "--allow-env",
                "--unstable-detect-cjs",
                node_runner.RUNNER_PATH,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )

    node_runner.NodeRunner._start_process = _start_process
    _runner_configured_for = resolved


@contextmanager
def _bounded_requests(timeout_s: float):
    """Clamp pytubefix's otherwise-unbounded urllib calls for this attempt."""
    from pytubefix import request

    original = request._execute_request
    limit = max(5.0, min(float(timeout_s or 20.0), 60.0))

    def _execute_request(
        url,
        method=None,
        headers=None,
        data=None,
        timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
    ):
        if timeout is socket._GLOBAL_DEFAULT_TIMEOUT or timeout is None:
            timeout = limit
        else:
            try:
                timeout = min(float(timeout), limit)
            except (TypeError, ValueError):
                timeout = limit
        return original(
            url,
            method=method,
            headers=headers,
            data=data,
            timeout=timeout,
        )

    request._execute_request = _execute_request
    try:
        yield
    finally:
        request._execute_request = original


def _numeric(value: Any) -> int:
    text = str(value or "")
    digits = "".join(char for char in text if char.isdigit())
    return int(digits or 0)


def _pick_stream(streams, *, audio_only: bool):
    if audio_only:
        candidates = list(streams.filter(only_audio=True))
        # A normal signed media URL works with VLC/yt-dlp's generic extractor;
        # SABR streams require pytubefix's own long-running downloader instead.
        ordinary = [item for item in candidates if not bool(getattr(item, "is_sabr", False))]
        candidates = ordinary or candidates
        return max(
            candidates,
            key=lambda item: (
                _numeric(getattr(item, "abr", "")),
                int(getattr(item, "bitrate", 0) or 0),
            ),
            default=None,
        )

    candidates = list(streams.filter(progressive=True, file_extension="mp4"))
    ordinary = [item for item in candidates if not bool(getattr(item, "is_sabr", False))]
    candidates = ordinary or candidates
    return max(
        candidates,
        key=lambda item: (
            _numeric(getattr(item, "resolution", "")),
            int(getattr(item, "fps", 0) or 0),
            int(getattr(item, "bitrate", 0) or 0),
        ),
        default=None,
    )


def resolve_stream(
    url: str,
    *,
    audio_only: bool = True,
    timeout_s: float = 20.0,
) -> dict[str, Any] | None:
    """Return one direct pytubefix media stream, or ``None`` on any failure."""
    target = str(url or "").strip()
    if not target:
        return None

    try:
        deno_path = _find_executable_path("deno")
    except Exception:
        deno_path = None
    if not deno_path:
        log.debug("pytubefix fallback skipped because Deno is unavailable")
        return None

    # request._execute_request and the upstream NodeRunner class are module
    # globals, so serialize this rare fallback while both are patched.
    with _extract_lock:
        try:
            _install_nodejs_import_stub()
            from pytubefix import YouTube

            _configure_deno_runner(str(deno_path))
            with _bounded_requests(timeout_s):
                video = YouTube(target, client="ANDROID_VR", use_oauth=False)
                stream = _pick_stream(video.streams, audio_only=bool(audio_only))
                if stream is None:
                    return None
                media_url = str(getattr(stream, "url", "") or "").strip()
                if not media_url.startswith(("http://", "https://")):
                    return None
                return {
                    "url": media_url,
                    "title": str(getattr(video, "title", "") or "").strip(),
                    "duration": int(getattr(video, "length", 0) or 0),
                    "http_headers": {
                        "User-Agent": utils.HEADERS.get("User-Agent", "Mozilla/5.0"),
                        "Referer": str(getattr(video, "watch_url", target) or target),
                    },
                    "format_id": str(getattr(stream, "itag", "") or ""),
                    "ext": str(getattr(stream, "subtype", "") or ""),
                    "pytubefix": True,
                }
        except Exception:
            log.debug("pytubefix YouTube fallback failed", exc_info=True)
            return None

