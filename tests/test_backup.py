import os
import sqlite3
import zipfile

import pytest

from core import backup


def _make_data(root):
    data = root / "data"
    data.mkdir()
    (data / "config.json").write_text('{"a": 1}', encoding="utf-8")
    (data / "site_cookies.txt").write_text("# Netscape", encoding="utf-8")
    conn = sqlite3.connect(data / "rss.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE feeds (url TEXT)")
    conn.execute("INSERT INTO feeds VALUES ('https://example.com/feed')")
    conn.commit()
    return data, conn  # keep open: backup must work against a live WAL db


def test_backup_round_trip_through_staged_restore(tmp_path):
    data, conn = _make_data(tmp_path)
    zpath = tmp_path / "b.zip"
    backup.create_backup(str(zpath), str(data), str(data / "config.json"), str(data / "rss.db"))
    conn.close()
    with zipfile.ZipFile(zpath) as zf:
        assert set(zf.namelist()) == {"config.json", "rss.db", "site_cookies.txt"}

    # Damage the live copy, leave a stale WAL, then restore.
    (data / "config.json").write_text("{}", encoding="utf-8")
    os.remove(data / "rss.db")
    (data / "rss.db-wal").write_bytes(b"stale")
    backup.stage_restore(str(zpath), str(data))
    assert (data / "config.json").read_text(encoding="utf-8") == "{}"  # not applied yet
    assert backup.apply_pending_restore(str(data)) is True
    assert not (data / "rss.db-wal").exists()
    assert (data / "config.json").read_text(encoding="utf-8") == '{"a": 1}'
    rows = sqlite3.connect(data / "rss.db").execute("SELECT url FROM feeds").fetchall()
    assert rows == [("https://example.com/feed",)]
    assert backup.apply_pending_restore(str(data)) is False


def test_stage_rejects_foreign_zip(tmp_path):
    zpath = tmp_path / "x.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(backup.BackupError):
        backup.stage_restore(str(zpath), str(tmp_path))
    assert not (tmp_path / backup.PENDING_DIR).exists()


def test_auto_backup_keeps_newest(tmp_path):
    data, conn = _make_data(tmp_path)
    conn.close()
    folder = tmp_path / "auto"
    folder.mkdir()
    for day in range(1, 5):
        (folder / f"{backup.AUTO_PREFIX}2026-01-0{day}-000000.zip").write_bytes(b"")
    (folder / "keep-me.zip").write_bytes(b"")
    made = backup.run_auto_backup(str(folder), str(data), str(data / "config.json"), str(data / "rss.db"), keep=2)
    names = sorted(os.listdir(folder))
    assert os.path.basename(made) in names
    assert "keep-me.zip" in names
    assert len([n for n in names if n.startswith(backup.AUTO_PREFIX)]) == 2


def test_auto_backup_due():
    assert backup.auto_backup_due(0, 100000)
    assert not backup.auto_backup_due(100000, 100000 + 3600)


def test_rejected_database_is_never_applied_on_restart(tmp_path):
    data, conn = _make_data(tmp_path)
    conn.close()
    zpath = tmp_path / "damaged.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("rss.db", b"not a SQLite database")
    with pytest.raises((backup.BackupError, sqlite3.DatabaseError)):
        backup.stage_restore(str(zpath), str(data))
    assert backup.apply_pending_restore(str(data)) is False
    conn = sqlite3.connect(data / "rss.db")
    try:
        assert conn.execute("SELECT url FROM feeds").fetchall() == [("https://example.com/feed",)]
    finally:
        conn.close()


@pytest.mark.parametrize("config", ["{broken", "[]", "null"])
def test_restore_rejects_invalid_settings(tmp_path, config):
    zpath = tmp_path / "bad-settings.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("config.json", config)
    with pytest.raises(backup.BackupError):
        backup.stage_restore(str(zpath), str(tmp_path))
    assert backup.apply_pending_restore(str(tmp_path)) is False


def test_restore_keeps_not_a_backup_message(tmp_path):
    zpath = tmp_path / "other.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(backup.BackupError, match="not a BlindRSS backup"):
        backup.stage_restore(str(zpath), str(tmp_path))
