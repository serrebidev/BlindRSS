# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import functools
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

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


@functools.lru_cache(maxsize=1)
def local_tcp_stream_delivery_works() -> bool:
    """Can a local TCP server still deliver a second write to a client?

    A machine can end up in a state where everything a local server sends
    after its first write is swallowed: the client gets the response headers
    and then nothing -- not the body, not even the FIN, and its socket never
    becomes readable. Seen on Windows 11 in July 2026, affecting only
    medium-integrity (non-elevated) processes; the same code run elevated was
    fine, UDP was fine, and remote connections were fine. A reboot clears it.

    Tests that stand up a mock origin server cannot run at all in that state,
    and they fail in a way that looks exactly like a proxy bug, so they check
    this first and skip with an explanation instead.
    """
    head, body = b"H" * 32, b"BODY"

    # Setting the probe up must never be confused with the condition it looks
    # for: if the sockets cannot even be created, say "healthy" and let the
    # real tests report whatever is wrong. Only the read below decides.
    try:
        srv = socket.socket()
        srv.settimeout(3.0)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def serve():
            try:
                conn, _ = srv.accept()
                conn.recv(64)
                conn.sendall(head)
                time.sleep(0.02)   # force a second, separate write
                conn.sendall(body)
                time.sleep(0.2)
                conn.close()
            except Exception:
                pass
            finally:
                try:
                    srv.close()
                except Exception:
                    pass

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        client = socket.create_connection(("127.0.0.1", port), timeout=3.0)
    except Exception:
        return True

    got = b""
    try:
        client.sendall(b"probe")
        while len(got) < len(head) + len(body):
            chunk = client.recv(256)
            if not chunk:
                break
            got += chunk
    except Exception:
        # A read timeout here IS the condition: the second write never landed.
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass
        worker.join(timeout=2.0)
    return got.endswith(body)


@pytest.fixture(scope="session")
def local_tcp_server():
    """Skip when this machine cannot deliver a local TCP response body."""
    if not local_tcp_stream_delivery_works():
        pytest.skip(
            "local TCP delivery is broken on this machine: a server's second "
            "write never reaches the client, so a mock origin cannot serve a "
            "response body. Not a BlindRSS fault -- reboot to clear it."
        )


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
