import json
import os
import sqlite3

import pytest

import core.config as config_mod
import core.db as db_mod


def test_windows_user_data_dir_is_exactly_appdata_blindrss(monkeypatch):
    monkeypatch.setattr(config_mod.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\alice\AppData\Roaming")

    assert config_mod._user_data_dir() == r"C:\Users\alice\AppData\Roaming\BlindRSS"


def _configure_installed_layout(tmp_path, monkeypatch):
    app_dir = tmp_path / "install"
    user_dir = tmp_path / "roaming" / "BlindRSS"
    app_dir.mkdir(parents=True)
    (app_dir / config_mod.WINDOWS_INSTALL_MARKER).write_text(
        "BlindRSS Windows installer\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(config_mod.sys, "platform", "win32")
    monkeypatch.setattr(config_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_mod, "APP_DIR", str(app_dir))
    monkeypatch.setattr(config_mod, "USER_DATA_DIR", str(user_dir))
    monkeypatch.setattr(config_mod, "APP_CONFIG_PATH", str(app_dir / "config.json"))
    monkeypatch.setattr(config_mod, "USER_CONFIG_PATH", str(user_dir / "config.json"))
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(app_dir / "config.json"))
    return app_dir, user_dir


def test_installed_windows_build_migrates_config_and_app_relative_user_data(
    tmp_path, monkeypatch
):
    app_dir, user_dir = _configure_installed_layout(tmp_path, monkeypatch)
    old_downloads = app_dir / "podcasts"
    old_downloads.mkdir()
    episode = old_downloads / "episode.mp3"
    episode.write_bytes(b"audio")
    cookie_file = app_dir / "youtube_cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    app_config = {
        "active_provider": "local",
        "data_location": "app_folder",
        "download_path": str(old_downloads),
        "ytdlp_cookies_file": str(cookie_file),
        "downloaded_media": {
            "episode": {"path": str(episode)},
        },
    }
    (app_dir / "config.json").write_text(
        json.dumps(app_config),
        encoding="utf-8",
    )

    manager = config_mod.ConfigManager()

    new_downloads = user_dir / "podcasts"
    assert manager.config_path == str(user_dir / "config.json")
    assert manager.get("data_location") == "user_data"
    assert manager.get("download_path") == str(new_downloads)
    assert manager.get("ytdlp_cookies_file") == str(user_dir / "youtube_cookies.txt")
    assert manager.get("downloaded_media")["episode"]["path"] == str(
        new_downloads / "episode.mp3"
    )
    assert (new_downloads / "episode.mp3").read_bytes() == b"audio"
    assert (user_dir / "youtube_cookies.txt").is_file()

    # Migration is copy-first so a failed install can still be rolled back.
    assert (app_dir / "config.json").is_file()
    assert episode.is_file()


def test_installed_windows_build_keeps_existing_roaming_config_authoritative(
    tmp_path, monkeypatch
):
    app_dir, user_dir = _configure_installed_layout(tmp_path, monkeypatch)
    user_dir.mkdir(parents=True)
    (app_dir / "config.json").write_text(
        json.dumps({"active_provider": "local", "refresh_interval": 1}),
        encoding="utf-8",
    )
    (user_dir / "config.json").write_text(
        json.dumps({"active_provider": "local", "refresh_interval": 900}),
        encoding="utf-8",
    )

    manager = config_mod.ConfigManager()

    assert manager.config_path == str(user_dir / "config.json")
    assert manager.get("refresh_interval") == 900


def test_installed_windows_build_cannot_switch_back_to_install_folder(
    tmp_path, monkeypatch
):
    _app_dir, user_dir = _configure_installed_layout(tmp_path, monkeypatch)
    manager = config_mod.ConfigManager()

    ok, message = manager.change_data_location("app_folder")

    assert not ok
    assert "User Data Folder" in message
    assert manager.config_path == str(user_dir / "config.json")


def test_database_migration_uses_sqlite_backup_and_preserves_legacy_source(
    tmp_path, monkeypatch
):
    app_dir = tmp_path / "install"
    user_dir = tmp_path / "roaming" / "BlindRSS"
    app_dir.mkdir(parents=True)
    source = app_dir / "rss.db"
    target = user_dir / "rss.db"

    source_conn = sqlite3.connect(source)
    try:
        source_conn.execute("PRAGMA journal_mode=WAL")
        source_conn.execute("PRAGMA wal_autocheckpoint=0")
        source_conn.execute("CREATE TABLE migrated (value TEXT)")
        source_conn.execute("INSERT INTO migrated VALUES ('from-wal')")
        source_conn.commit()
        assert os.path.isfile(f"{source}-wal")

        monkeypatch.setattr(db_mod, "APP_DIR", str(app_dir))
        monkeypatch.setattr(db_mod, "USER_DATA_DIR", str(user_dir))
        monkeypatch.setattr(db_mod, "get_data_dir", lambda: str(user_dir))
        monkeypatch.setattr(db_mod, "_DEFAULT_DB_FILE", str(source))
        monkeypatch.setattr(db_mod, "DB_FILE", str(source))

        migrated_path = db_mod._ensure_db_available()
    finally:
        source_conn.close()

    assert os.path.abspath(migrated_path) == os.path.abspath(
        user_dir / "rss.db"
    )
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM migrated").fetchone()[0] == "from-wal"
    assert source.is_file()


# ---------------------------------------------------------------------------
# Path containment + copy-migration helpers (config.py)
# ---------------------------------------------------------------------------


def test_path_inside_detects_containment(tmp_path):
    parent = tmp_path / "app"
    parent.mkdir()
    child = parent / "podcasts" / "ep.mp3"

    assert config_mod._path_inside(str(child), str(parent)) is True
    assert config_mod._path_inside(str(parent), str(parent)) is True
    assert config_mod._path_inside(str(tmp_path / "other"), str(parent)) is False
    assert config_mod._path_inside(None, str(parent)) is False  # type: ignore[arg-type]


def test_copy_file_if_missing_copies_then_preserves_existing(tmp_path):
    source = tmp_path / "src.txt"
    target = tmp_path / "dest" / "out.txt"
    source.write_text("original", encoding="utf-8")

    assert config_mod._copy_file_if_missing(str(source), str(target)) is True
    assert target.read_text(encoding="utf-8") == "original"

    # A second pass must never overwrite newer roaming data.
    target.write_text("user-edited", encoding="utf-8")
    source.write_text("changed-upstream", encoding="utf-8")
    assert config_mod._copy_file_if_missing(str(source), str(target)) is True
    assert target.read_text(encoding="utf-8") == "user-edited"


def test_copy_file_if_missing_returns_false_when_source_absent(tmp_path):
    missing = tmp_path / "nope.txt"
    target = tmp_path / "dest.txt"
    assert config_mod._copy_file_if_missing(str(missing), str(target)) is False
    assert not target.exists()


def test_copy_tree_missing_merges_without_overwriting(tmp_path):
    source = tmp_path / "old"
    (source / "sub").mkdir(parents=True)
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "sub" / "b.txt").write_text("b", encoding="utf-8")

    target = tmp_path / "new"
    target.mkdir()
    (target / "a.txt").write_text("keep", encoding="utf-8")

    assert config_mod._copy_tree_missing(str(source), str(target)) is True
    assert (target / "a.txt").read_text(encoding="utf-8") == "keep"
    assert (target / "sub" / "b.txt").read_text(encoding="utf-8") == "b"


def test_migrate_app_relative_path_is_noop_for_external_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "APP_DIR", str(tmp_path / "install"))

    assert config_mod._migrate_app_relative_path("") == ""
    assert config_mod._migrate_app_relative_path("relative/dir") == "relative/dir"
    external = str(tmp_path / "elsewhere" / "cache")
    assert config_mod._migrate_app_relative_path(external) == external


def test_migrate_app_relative_path_copies_into_roaming(tmp_path, monkeypatch):
    app_dir = tmp_path / "install"
    user_dir = tmp_path / "roaming"
    cache = app_dir / "ytplay_cache"
    cache.mkdir(parents=True)
    (cache / "clip.m4a").write_bytes(b"audio")
    monkeypatch.setattr(config_mod, "APP_DIR", str(app_dir))
    monkeypatch.setattr(config_mod, "USER_DATA_DIR", str(user_dir))

    migrated = config_mod._migrate_app_relative_path(str(cache))

    assert migrated == str(user_dir / "ytplay_cache")
    assert (user_dir / "ytplay_cache" / "clip.m4a").read_bytes() == b"audio"
    # Copy-first: the source is preserved for rollback.
    assert (cache / "clip.m4a").exists()


# ---------------------------------------------------------------------------
# Active rss.db resolution + backup (db.py)
# ---------------------------------------------------------------------------


def test_active_db_path_prefers_explicit_override(tmp_path, monkeypatch):
    default_db = tmp_path / "app" / "rss.db"
    monkeypatch.setattr(db_mod, "_DEFAULT_DB_FILE", str(default_db))

    # No override: DB_FILE matches the default, so it resolves via get_data_dir().
    monkeypatch.setattr(db_mod, "DB_FILE", str(default_db))
    monkeypatch.setattr(db_mod, "get_data_dir", lambda: str(tmp_path / "roaming"))
    assert db_mod._db_file_is_overridden() is False
    assert db_mod._active_db_path() == str(tmp_path / "roaming" / "rss.db")

    # Explicit override (e.g. a data-location switch or a test) wins.
    override = tmp_path / "custom" / "rss.db"
    monkeypatch.setattr(db_mod, "DB_FILE", str(override))
    assert db_mod._db_file_is_overridden() is True
    assert db_mod._active_db_path() == str(override)


def test_backup_database_copies_committed_rows(tmp_path):
    source = tmp_path / "src.db"
    target = tmp_path / "nested" / "dst.db"
    conn = sqlite3.connect(source)
    try:
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('hello')")
        conn.commit()
    finally:
        conn.close()

    db_mod._backup_database(str(source), str(target))

    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello"
    # The temp staging file is renamed into place, never left behind.
    assert not list((tmp_path / "nested").glob("*.migrating-*"))


def test_backup_database_cleans_temp_and_reraises_on_failure(tmp_path):
    # The source's parent directory does not exist, so SQLite cannot open it.
    # This exercises the temp-file cleanup + re-raise path.
    source = tmp_path / "missing" / "src.db"
    target = tmp_path / "out.db"

    with pytest.raises(sqlite3.Error):
        db_mod._backup_database(str(source), str(target))

    assert not list(tmp_path.glob("out.db.migrating-*"))
    assert not target.exists()
