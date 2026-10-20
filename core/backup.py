# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Back up and restore everything a user would lose with their data folder.

A backup is one ZIP holding ``config.json``, a consistent snapshot of
``rss.db`` (subscriptions, read/favorite state, Filter Rules, Smart Folders,
playback positions) and the saved site-cookie files. It contains API keys,
passwords and cookies, so the UI must say so.

Restore never swaps a live database: ``stage_restore`` validates the ZIP and
unpacks it into ``restore_pending/``, and ``apply_pending_restore`` moves the
files into place at the next start, before the database is opened.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile

CONFIG_NAME = "config.json"
DB_NAME = "rss.db"
# Small state files in the data directory that are worth carrying across
# machines. chromium_v20_keys.json is deliberately absent: it is DPAPI-bound to
# this Windows account and useless anywhere else.
EXTRA_FILES = (
    "site_cookies.txt",
    "site_cookies_ua.txt",
    "site_cookies_ua_hosts.json",
    "youtube_cookies.txt",
)
PENDING_DIR = "restore_pending"
AUTO_DIR = "backups"
AUTO_PREFIX = "BlindRSS-auto-backup-"
AUTO_KEEP = 7


class BackupError(ValueError):
    pass


def create_backup(dest_zip: str, data_dir: str, config_path: str, db_path: str) -> None:
    """Write a backup ZIP to ``dest_zip`` (atomically: no half-written file)."""
    tmp_dir = tempfile.mkdtemp(prefix="blindrss-backup-")
    partial = dest_zip + ".partial"
    try:
        snapshot = os.path.join(tmp_dir, DB_NAME)
        if os.path.exists(db_path):
            src = sqlite3.connect(db_path, timeout=30)
            dst = sqlite3.connect(snapshot)
            try:
                src.backup(dst)  # consistent even while the app is writing
            finally:
                dst.close()
                src.close()
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(config_path):
                zf.write(config_path, CONFIG_NAME)
            if os.path.exists(snapshot):
                zf.write(snapshot, DB_NAME)
            for name in EXTRA_FILES:
                path = os.path.join(data_dir, name)
                if os.path.isfile(path):
                    zf.write(path, name)
        os.replace(partial, dest_zip)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if os.path.exists(partial):  # failed write: no stray half-ZIP
            os.remove(partial)


def _validate(zf: zipfile.ZipFile) -> list[str]:
    names = [n for n in zf.namelist() if n in (CONFIG_NAME, DB_NAME, *EXTRA_FILES)]
    if CONFIG_NAME not in names and DB_NAME not in names:
        raise BackupError("This file is not a BlindRSS backup.")
    return names


def stage_restore(backup_zip: str, data_dir: str) -> None:
    """Unpack a backup into ``restore_pending/`` for the next start to apply."""
    pending = os.path.join(data_dir, PENDING_DIR)
    staging = tempfile.mkdtemp(prefix="restore-", dir=data_dir)
    try:
        with zipfile.ZipFile(backup_zip) as zf:
            names = _validate(zf)
            for name in names:  # only known flat names: no path traversal
                with zf.open(name) as src, open(os.path.join(staging, name), "wb") as dst:
                    shutil.copyfileobj(src, dst)
        config = os.path.join(staging, CONFIG_NAME)
        if os.path.exists(config):
            with open(config, encoding="utf-8") as src:
                if not isinstance(json.load(src), dict):
                    raise BackupError("The settings in this backup are damaged.")
        db = os.path.join(staging, DB_NAME)
        if os.path.exists(db):
            conn = sqlite3.connect(db)
            try:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                conn.close()
            if not ok:
                raise BackupError("The database in this backup is damaged.")
        shutil.rmtree(pending, ignore_errors=True)
        os.replace(staging, pending)
    except zipfile.BadZipFile as exc:
        raise BackupError("This file is not a BlindRSS backup.") from exc
    except BackupError:
        raise  # a ValueError too; keep its specific message
    except (ValueError, UnicodeError, sqlite3.DatabaseError) as exc:
        raise BackupError("The settings or database in this backup are damaged.") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def apply_pending_restore(data_dir: str) -> bool:
    """Move a staged restore into place. Call before the database is opened."""
    pending = os.path.join(data_dir, PENDING_DIR)
    if not os.path.isdir(pending):
        return False
    for name in os.listdir(pending):
        target = os.path.join(data_dir, name)
        if name == DB_NAME:
            # A WAL left from the old database would be replayed onto the
            # restored one and corrupt it.
            for suffix in ("-wal", "-shm"):
                try:
                    os.remove(target + suffix)
                except FileNotFoundError:
                    pass
        os.replace(os.path.join(pending, name), target)
    shutil.rmtree(pending, ignore_errors=True)
    return True


def auto_backup_due(last_ts: float, now: float) -> bool:
    return now - float(last_ts or 0) >= 24 * 3600


def run_auto_backup(folder: str, data_dir: str, config_path: str, db_path: str, keep: int = AUTO_KEEP) -> str:
    """Write today's automatic backup and delete all but the newest ``keep``."""
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    dest = os.path.join(folder, f"{AUTO_PREFIX}{stamp}.zip")
    create_backup(dest, data_dir, config_path, db_path)
    old = sorted(n for n in os.listdir(folder) if n.startswith(AUTO_PREFIX) and n.endswith(".zip"))
    for name in old[:-keep] if keep > 0 else []:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    return dest
