import os
import shutil
import sys
import types
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.db
from core import utils


class _FakeResponse:
    def __init__(self, *, content: bytes = b"", json_data=None, status_code: int = 200):
        self._content = bytes(content or b"")
        self._json_data = json_data
        self.status_code = int(status_code)
        self.ok = self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data

    def iter_content(self, chunk_size=65536):
        _ = chunk_size
        yield self._content

    def close(self):
        return None


def test_fetch_and_store_chapters_returns_json_chapters_when_fk_insert_fails(monkeypatch):
    tmp_root = Path(".tmp_test")
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = tmp_root / f"test_chapter_fetch_fk_json_{uuid.uuid4().hex}"
    tmp.mkdir(parents=True, exist_ok=True)

    orig_db_file = core.db.DB_FILE
    core.db.DB_FILE = os.path.join(str(tmp), "rss.db")
    try:
        core.db.init_db()

        def _fake_get(url, **kwargs):
            _ = kwargs
            assert "chapters.json" in str(url)
            return _FakeResponse(
                json_data={
                    "version": "1.2.0",
                    "chapters": [
                        {"startTime": 0, "title": "Intro"},
                        {"startTime": 65, "title": "Segment 1"},
                    ]
                }
            )

        monkeypatch.setattr(utils, "safe_requests_get", _fake_get)

        missing_article_id = f"missing-{uuid.uuid4().hex}"
        chapters = utils.fetch_and_store_chapters(
            missing_article_id,
            media_url=None,
            media_type=None,
            chapter_url="https://example.com/chapters.json",
            allow_id3=False,
        )

        assert [c["title"] for c in chapters] == ["Intro", "Segment 1"]

        conn = core.db.get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM chapters WHERE article_id = ?", (missing_article_id,))
            count = int(c.fetchone()[0] or 0)
        finally:
            conn.close()
        assert count == 0
    finally:
        core.db.DB_FILE = orig_db_file
        shutil.rmtree(tmp, ignore_errors=True)


def test_fetch_and_store_chapters_returns_id3_chapters_when_fk_insert_fails(monkeypatch):
    tmp_root = Path(".tmp_test")
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = tmp_root / f"test_chapter_fetch_fk_id3_{uuid.uuid4().hex}"
    tmp.mkdir(parents=True, exist_ok=True)

    orig_db_file = core.db.DB_FILE
    core.db.DB_FILE = os.path.join(str(tmp), "rss.db")
    try:
        core.db.init_db()

        def _fake_get(url, headers=None, **kwargs):
            _ = url
            _ = kwargs
            rng = str((headers or {}).get("Range", ""))
            if "bytes=0-9" in rng:
                return _FakeResponse(content=b"ID3\x03\x00\x00\x00\x00\x00\x10", status_code=206)
            return _FakeResponse(content=(b"ID3" + b"\x00" * 64), status_code=206)

        monkeypatch.setattr(utils, "safe_requests_get", _fake_get)

        fake_mod = types.ModuleType("mutagen.id3")

        class _FakeID3Error(Exception):
            pass

        class _FakeTIT2:
            def __init__(self, value):
                self.text = [value]

        class _FakeCHAP:
            def __init__(self, start_time, title):
                self.start_time = int(start_time)
                self.sub_frames = {"TIT2": _FakeTIT2(title)}

        class _FakeID3:
            def __init__(self, _stream):
                pass

            def getall(self, name):
                if name != "CHAP":
                    return []
                return [
                    _FakeCHAP(0, "Intro"),
                    _FakeCHAP(65000, "Part 2"),
                ]

        fake_mod.ID3 = _FakeID3
        fake_mod.error = _FakeID3Error

        fake_pkg = types.ModuleType("mutagen")
        fake_pkg.id3 = fake_mod

        monkeypatch.setitem(sys.modules, "mutagen", fake_pkg)
        monkeypatch.setitem(sys.modules, "mutagen.id3", fake_mod)

        missing_article_id = f"missing-{uuid.uuid4().hex}"
        chapters = utils.fetch_and_store_chapters(
            missing_article_id,
            media_url="https://example.com/audio.mp3",
            media_type="audio/mpeg",
            chapter_url=None,
            allow_id3=True,
        )

        assert [c["title"] for c in chapters] == ["Intro", "Part 2"]
        assert [c["start"] for c in chapters] == [0.0, 65.0]

        conn = core.db.get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM chapters WHERE article_id = ?", (missing_article_id,))
            count = int(c.fetchone()[0] or 0)
        finally:
            conn.close()
        assert count == 0
    finally:
        core.db.DB_FILE = orig_db_file
        shutil.rmtree(tmp, ignore_errors=True)
