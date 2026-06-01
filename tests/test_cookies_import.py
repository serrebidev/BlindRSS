import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cookies_import


_YT_JAR = (
    "# Netscape HTTP Cookie File\n"
    "# This is a generated file!  Do not edit.\n\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tLOGIN_INFO\tabc123\n"
    "#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1999999999\tSID\tdef456\n"
)

_NON_YT_JAR = (
    "# Netscape HTTP Cookie File\n"
    ".example.com\tTRUE\t/\tFALSE\t1999999999\tsession\txyz\n"
)

_NOT_A_JAR = "just some random notes\nnothing tabbed here\n"


def _write(tmp_path, name, text):
    p = os.path.join(str(tmp_path), name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def test_is_netscape_cookie_jar_recognizes_real_jar():
    assert cookies_import.is_netscape_cookie_jar(_YT_JAR) is True
    assert cookies_import.is_netscape_cookie_jar(_NON_YT_JAR) is True
    assert cookies_import.is_netscape_cookie_jar(_NOT_A_JAR) is False
    assert cookies_import.is_netscape_cookie_jar("") is False


def test_cookie_jar_has_youtube_detects_youtube_and_google():
    assert cookies_import.cookie_jar_has_youtube(_YT_JAR) is True
    assert cookies_import.cookie_jar_has_youtube(_NON_YT_JAR) is False


def test_cookie_jar_domains_strips_httponly_and_leading_dot():
    domains = cookies_import.cookie_jar_domains(_YT_JAR)
    assert "youtube.com" in domains
    assert "google.com" in domains


def test_validate_cookie_file_accepts_youtube_jar(tmp_path):
    path = _write(tmp_path, "cookies.txt", _YT_JAR)
    ok, msg = cookies_import.validate_cookie_file(path)
    assert ok is True
    assert "valid" in msg.lower()


def test_validate_cookie_file_rejects_non_youtube_jar(tmp_path):
    path = _write(tmp_path, "cookies.txt", _NON_YT_JAR)
    ok, msg = cookies_import.validate_cookie_file(path)
    assert ok is False
    assert "youtube" in msg.lower()


def test_validate_cookie_file_rejects_non_jar(tmp_path):
    path = _write(tmp_path, "notes.txt", _NOT_A_JAR)
    ok, _ = cookies_import.validate_cookie_file(path)
    assert ok is False


def test_validate_cookie_file_missing():
    ok, msg = cookies_import.validate_cookie_file(os.path.join("nope", "missing.txt"))
    assert ok is False
    assert "not found" in msg.lower()


def test_find_latest_youtube_cookie_export_picks_newest_valid(tmp_path):
    d = str(tmp_path)
    old = _write(tmp_path, "www.youtube.com_cookies.txt", _YT_JAR)
    new = _write(tmp_path, "cookies (1).txt", _YT_JAR)
    _write(tmp_path, "other.txt", _NON_YT_JAR)
    _write(tmp_path, "readme.txt", _NOT_A_JAR)

    now = time.time()
    os.utime(old, (now - 300, now - 300))
    os.utime(new, (now - 10, now - 10))

    found = cookies_import.find_latest_youtube_cookie_export([d], now=now)
    assert found == new


def test_find_latest_ignores_stale_files(tmp_path):
    d = str(tmp_path)
    stale = _write(tmp_path, "cookies.txt", _YT_JAR)
    now = time.time()
    os.utime(stale, (now - 99999, now - 99999))
    found = cookies_import.find_latest_youtube_cookie_export([d], now=now, max_age_s=600)
    assert found is None


def test_find_latest_respects_since_ts(tmp_path):
    d = str(tmp_path)
    before = _write(tmp_path, "cookies.txt", _YT_JAR)
    now = time.time()
    os.utime(before, (now - 100, now - 100))
    # since_ts after the file's mtime -> excluded.
    found = cookies_import.find_latest_youtube_cookie_export(
        [d], since_ts=now - 50, now=now
    )
    assert found is None


def test_import_cookie_file_copies_to_dest(tmp_path):
    src = _write(tmp_path, "export.txt", _YT_JAR)
    dest_dir = os.path.join(str(tmp_path), "appdata")
    dest = cookies_import.import_cookie_file(src, dest_dir)
    assert os.path.isfile(dest)
    assert dest.endswith(cookies_import.IMPORTED_COOKIE_FILENAME)
    with open(dest, encoding="utf-8") as fh:
        assert "youtube.com" in fh.read()


def test_import_cookie_file_rejects_invalid(tmp_path):
    src = _write(tmp_path, "bad.txt", _NON_YT_JAR)
    dest_dir = os.path.join(str(tmp_path), "appdata")
    try:
        cookies_import.import_cookie_file(src, dest_dir)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-YouTube jar")


def test_import_cookie_file_same_path_is_noop(tmp_path):
    dest_dir = os.path.join(str(tmp_path), "appdata")
    os.makedirs(dest_dir, exist_ok=True)
    managed = os.path.join(dest_dir, cookies_import.IMPORTED_COOKIE_FILENAME)
    with open(managed, "w", encoding="utf-8") as fh:
        fh.write(_YT_JAR)
    dest = cookies_import.import_cookie_file(managed, dest_dir)
    assert dest == managed
    assert os.path.isfile(managed)


class _FakeConfig:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def _make_dirs(tmp_path):
    downloads = os.path.join(str(tmp_path), "Downloads")
    data_dir = os.path.join(str(tmp_path), "appdata")
    os.makedirs(downloads, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)
    return downloads, data_dir


def test_auto_import_imports_fresh_export_and_sets_config(tmp_path):
    downloads, data_dir = _make_dirs(tmp_path)
    export = os.path.join(downloads, "cookies.txt")
    with open(export, "w", encoding="utf-8") as fh:
        fh.write(_YT_JAR)
    now = time.time()
    os.utime(export, (now - 5, now - 5))

    cfg = _FakeConfig({"auto_import_browser_cookies": True})
    dest = cookies_import.auto_import_youtube_cookies(
        cfg, data_dir, search_dirs=[downloads], now=now
    )
    assert dest is not None
    assert os.path.isfile(dest)
    assert cfg.get("ytdlp_cookies_file") == dest
    assert cfg.get("ytdlp_cookies_last_import_mtime") == os.path.getmtime(export)


def test_auto_import_does_not_reimport_same_export(tmp_path):
    downloads, data_dir = _make_dirs(tmp_path)
    export = os.path.join(downloads, "cookies.txt")
    with open(export, "w", encoding="utf-8") as fh:
        fh.write(_YT_JAR)
    now = time.time()
    os.utime(export, (now - 5, now - 5))

    cfg = _FakeConfig({"auto_import_browser_cookies": True})
    first = cookies_import.auto_import_youtube_cookies(cfg, data_dir, search_dirs=[downloads], now=now)
    assert first is not None
    second = cookies_import.auto_import_youtube_cookies(cfg, data_dir, search_dirs=[downloads], now=now)
    assert second is None


def test_auto_import_picks_up_newer_export_after_first(tmp_path):
    downloads, data_dir = _make_dirs(tmp_path)
    export = os.path.join(downloads, "cookies.txt")
    with open(export, "w", encoding="utf-8") as fh:
        fh.write(_YT_JAR)
    now = time.time()
    os.utime(export, (now - 300, now - 300))

    cfg = _FakeConfig({"auto_import_browser_cookies": True})
    assert cookies_import.auto_import_youtube_cookies(cfg, data_dir, search_dirs=[downloads], now=now)

    # User re-exports: same path, newer mtime.
    os.utime(export, (now - 2, now - 2))
    dest = cookies_import.auto_import_youtube_cookies(cfg, data_dir, search_dirs=[downloads], now=now)
    assert dest is not None
    assert cfg.get("ytdlp_cookies_last_import_mtime") == os.path.getmtime(export)


def test_auto_import_disabled_does_nothing(tmp_path):
    downloads, data_dir = _make_dirs(tmp_path)
    export = os.path.join(downloads, "cookies.txt")
    with open(export, "w", encoding="utf-8") as fh:
        fh.write(_YT_JAR)
    now = time.time()
    os.utime(export, (now - 5, now - 5))

    cfg = _FakeConfig({"auto_import_browser_cookies": False})
    assert cookies_import.auto_import_youtube_cookies(cfg, data_dir, search_dirs=[downloads], now=now) is None
    assert not cfg.get("ytdlp_cookies_file")


def test_auto_import_ignores_managed_file_in_search(tmp_path):
    downloads, data_dir = _make_dirs(tmp_path)
    # The managed file itself must never be re-imported as if it were an export.
    managed = os.path.join(data_dir, cookies_import.IMPORTED_COOKIE_FILENAME)
    with open(managed, "w", encoding="utf-8") as fh:
        fh.write(_YT_JAR)
    now = time.time()
    os.utime(managed, (now - 5, now - 5))

    cfg = _FakeConfig({"auto_import_browser_cookies": True})
    dest = cookies_import.auto_import_youtube_cookies(
        cfg, data_dir, search_dirs=[data_dir], now=now
    )
    assert dest is None
