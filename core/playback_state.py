# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Optional

from core.db import get_connection

LOG = logging.getLogger(__name__)

_PLAYBACK_STATE_BUSY_TIMEOUT_MS = 500


def _configure_conn(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(f"PRAGMA busy_timeout={int(_PLAYBACK_STATE_BUSY_TIMEOUT_MS)}")
    except sqlite3.Error as e:
        LOG.warning("Failed to set playback_state busy_timeout pragma: %s", e)


def _is_locked_error(error: Exception) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False

    # Prefer SQLite error codes when available (Python 3.11+).
    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        try:
            return int(code) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        except (TypeError, ValueError):
            pass

    # Fallback for older Python versions / unknown errors.
    return "locked" in str(error).lower()


def _execute_write_op(op_name: str, op: Callable[[sqlite3.Cursor], None]) -> bool:
    conn = get_connection()
    try:
        _configure_conn(conn)
        c = conn.cursor()
        try:
            op(c)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            # Don't block the GUI thread for long if a refresh is writing.
            # We'll retry on the next timer tick.
            if _is_locked_error(e):
                LOG.debug("playback_state is locked; skipping %s", op_name)
                return False
            raise
    finally:
        conn.close()


@dataclass(frozen=True)
class PlaybackState:
    id: str
    position_ms: int
    duration_ms: Optional[int]
    updated_at: int
    completed: bool
    seek_supported: Optional[bool]
    title: Optional[str]


def get_playback_state(playback_id: str) -> Optional[PlaybackState]:
    if not playback_id:
        return None

    conn = get_connection()
    try:
        _configure_conn(conn)
        c = conn.cursor()
        c.execute(
            "SELECT id, position_ms, duration_ms, updated_at, completed, seek_supported, title "
            "FROM playback_state WHERE id = ?",
            (playback_id,),
        )
        row = c.fetchone()
        if not row:
            return None

        duration_ms = row[2]
        seek_supported = row[5]
        return PlaybackState(
            id=str(row[0]),
            position_ms=int(row[1] or 0),
            duration_ms=(int(duration_ms) if duration_ms is not None else None),
            updated_at=int(row[3] or 0),
            completed=bool(row[4] or 0),
            seek_supported=(None if seek_supported is None else bool(int(seek_supported))),
            title=(str(row[6]) if row[6] is not None else None),
        )
    finally:
        conn.close()


def get_all_playback_states() -> dict[str, PlaybackState]:
    """Return every stored playback state keyed by id.

    Used to annotate the article list with listened/remaining time without a
    per-row query. The table is local and small (one row per played item), so a
    single scan is cheap. Returns an empty dict if the table is locked/missing.
    """
    conn = get_connection()
    try:
        _configure_conn(conn)
        c = conn.cursor()
        c.execute(
            "SELECT id, position_ms, duration_ms, updated_at, completed, seek_supported, title "
            "FROM playback_state"
        )
        out: dict[str, PlaybackState] = {}
        for row in c.fetchall():
            try:
                duration_ms = row[2]
                seek_supported = row[5]
                out[str(row[0])] = PlaybackState(
                    id=str(row[0]),
                    position_ms=int(row[1] or 0),
                    duration_ms=(int(duration_ms) if duration_ms is not None else None),
                    updated_at=int(row[3] or 0),
                    completed=bool(row[4] or 0),
                    seek_supported=(None if seek_supported is None else bool(int(seek_supported))),
                    title=(str(row[6]) if row[6] is not None else None),
                )
            except Exception:
                continue
        return out
    except sqlite3.Error as e:
        LOG.debug("Could not read all playback_state rows: %s", e)
        return {}
    finally:
        conn.close()


def upsert_playback_state(
    playback_id: str,
    position_ms: int,
    *,
    duration_ms: Optional[int] = None,
    title: Optional[str] = None,
    completed: bool = False,
    seek_supported: Optional[bool] = None,
    updated_at: Optional[int] = None,
) -> bool:
    if not playback_id:
        return True

    try:
        pos = max(0, int(position_ms))
    except (TypeError, ValueError):
        pos = 0

    dur = None
    if duration_ms is not None:
        try:
            dur = int(duration_ms)
        except (TypeError, ValueError):
            dur = None
        if dur is not None and dur <= 0:
            dur = None

    ts = int(updated_at if updated_at is not None else time.time())
    completed_i = 1 if bool(completed) else 0
    seek_i = None if seek_supported is None else (1 if bool(seek_supported) else 0)

    def _op(cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            INSERT INTO playback_state (id, position_ms, duration_ms, updated_at, completed, seek_supported, title)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                position_ms = excluded.position_ms,
                duration_ms = CASE
                    WHEN excluded.duration_ms IS NOT NULL THEN excluded.duration_ms
                    ELSE playback_state.duration_ms
                END,
                updated_at = excluded.updated_at,
                completed = excluded.completed,
                seek_supported = CASE
                    WHEN excluded.seek_supported IS NOT NULL THEN excluded.seek_supported
                    ELSE playback_state.seek_supported
                END,
                title = CASE
                    WHEN excluded.title IS NOT NULL THEN excluded.title
                    ELSE playback_state.title
                END
            """,
            (playback_id, pos, dur, ts, completed_i, seek_i, title),
        )

    return _execute_write_op("position write", _op)


def delete_playback_state(playback_id: str) -> bool:
    if not playback_id:
        return True

    def _op(cur: sqlite3.Cursor) -> None:
        cur.execute("DELETE FROM playback_state WHERE id = ?", (playback_id,))

    return _execute_write_op("delete", _op)


def set_seek_supported(playback_id: str, seek_supported: bool) -> bool:
    if not playback_id:
        return True

    def _op(cur: sqlite3.Cursor) -> None:
        cur.execute(
            "UPDATE playback_state SET seek_supported = ?, updated_at = ? WHERE id = ?",
            (1 if bool(seek_supported) else 0, int(time.time()), playback_id),
        )

    return _execute_write_op("seek_supported update", _op)
