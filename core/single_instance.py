"""Bring the running BlindRSS window forward when a second copy is launched.

wx.SingleInstanceChecker only tells the second copy that another one exists.
A desktop shortcut hotkey (for example Ctrl+Alt+B) launches a second copy, so
that copy hands an "activate" request to the first over a loopback socket and
exits, instead of showing "already running" while the window stays in the tray.
"""

import json
import logging
import os
import secrets
import socket
import sys
import tempfile
import threading

log = logging.getLogger(__name__)

_MESSAGE = b"activate"
_ACK = b"ok"


def _state_path() -> str:
    # Must be private to this user, like the wx instance lock. Windows %TEMP%
    # is per-user; POSIX /tmp is shared and world-writable (another account
    # could plant a symlink there), so use the runtime dir or home instead.
    if sys.platform.startswith("win"):
        base = tempfile.gettempdir()
    else:
        base = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~")
    return os.path.join(base, ".blindrss-instance.json")


def _read_to_eof(conn, limit: int = 256) -> bytes:
    """Read until the peer shuts down its side; TCP may split even tiny messages."""
    data = b""
    while len(data) <= limit:
        chunk = conn.recv(limit)
        if not chunk:
            break
        data += chunk
    return data


def serve(on_activate) -> socket.socket | None:
    """Listen for activation requests; call on_activate() (from a worker thread)."""
    try:
        token = secrets.token_hex(16)
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        path = _state_path()
        try:
            os.unlink(path)  # never write through a planted symlink
        except FileNotFoundError:
            pass
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"port": server.getsockname()[1], "pid": os.getpid(), "token": token}, f)
    except Exception:
        log.debug("Single-instance activation listener not started", exc_info=True)
        return None

    def _loop():
        while True:
            try:
                conn, _addr = server.accept()
            except OSError:
                return  # closed on exit
            try:
                with conn:
                    conn.settimeout(2)
                    if _read_to_eof(conn).strip() == token.encode("ascii") + b" " + _MESSAGE:
                        conn.sendall(_ACK)
                        conn.shutdown(socket.SHUT_WR)
                        on_activate()
            except Exception:
                log.debug("Activation request failed", exc_info=True)

    threading.Thread(target=_loop, name="SingleInstanceActivation", daemon=True).start()
    return server


def activate_existing(timeout: float = 2.0) -> bool:
    """Ask the running instance to show itself. False if it could not be reached."""
    try:
        with open(_state_path(), encoding="utf-8") as f:
            state = json.load(f)
        port, pid, token = int(state["port"]), int(state["pid"]), str(state["token"])
    except Exception:
        return False
    if sys.platform.startswith("win"):
        # This launch owns the foreground (the user just pressed the hotkey);
        # pass that right on, or Windows only flashes the other window's button.
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(pid)
        except Exception:
            pass
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall(token.encode("ascii") + b" " + _MESSAGE)
            conn.shutdown(socket.SHUT_WR)
            # Only an acknowledged request counts; otherwise the caller falls
            # back to the "already running" message instead of exiting silently.
            return _read_to_eof(conn) == _ACK
    except OSError:
        return False
