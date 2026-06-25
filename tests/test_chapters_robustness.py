import json
import os
import sqlite3
import sys
import types
import uuid

import pytest

import core.db
from core import utils


class _Response:
    def __init__(self, payload, *, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        raw = json.dumps(self.payload).encode()
        for index in range(0, len(raw), chunk_size):
            yield raw[index:index + chunk_size]

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


@pytest.fixture
def chapter_db(tmp_path):
    original = core.db.DB_FILE
    core.db.DB_FILE = os.path.join(tmp_path, "rss.db")
    core.db.init_db()
    try:
        yield
    finally:
        core.db.DB_FILE = original


def _insert_article(article_id):
    conn = core.db.get_connection()
    try:
        conn.execute(
            "INSERT INTO articles (id, title) VALUES (?, ?)",
            (article_id, "Episode"),
        )
        conn.commit()
    finally:
        conn.close()


def test_json_chapters_normalize_sort_dedupe_and_preserve_metadata(monkeypatch, chapter_db):
    article_id = str(uuid.uuid4())
    _insert_article(article_id)
    response = _Response(
        {
            "version": "1.2.0",
            "chapters": [
                {"startTime": "01:02.500", "title": " Later ", "url": "https://example.com/later"},
                {"startTime": 0, "title": "Intro", "url": "https://example.com/intro"},
                {"startTime": "62.5", "title": "", "url": ""},
                {"start_time": "00:30", "title": 123, "link": "https://example.com/middle"},
                {"startTime": -1, "title": "Negative"},
                {"startTime": "nan", "title": "Not finite"},
                {"startTime": "00:60", "title": "Invalid clock"},
                {"title": "Missing timestamp"},
                {"startTime": 45, "title": "Silent metadata", "toc": False},
                "not a chapter",
            ],
        }
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    chapters = utils.fetch_and_store_chapters(
        article_id,
        None,
        None,
        chapter_url="https://example.com/chapters.json",
        allow_id3=False,
    )

    assert chapters == [
        {"start": 0.0, "title": "Intro", "href": "https://example.com/intro"},
        {"start": 30.0, "title": "123", "href": "https://example.com/middle"},
        {"start": 62.5, "title": " Later ", "href": "https://example.com/later"},
    ]
    assert utils.get_chapters_from_db(article_id) == chapters
    assert calls[0][1]["timeout"] == (5, 10)
    assert calls[0][1]["stream"] is True
    assert response.closed is True


@pytest.mark.parametrize(
    ("payload", "content_type"),
    [
        ({"chapters": []}, "application/json+chapters"),
        ({"version": "1.2.0"}, "application/json"),
        ({"version": "1.2.0", "chapters": {}}, "application/json"),
        ({"version": "1.2.0", "chapters": []}, "text/html"),
    ],
)
def test_json_chapters_require_standard_structure_and_compatible_mime(
    monkeypatch,
    payload,
    content_type,
):
    monkeypatch.setattr(
        utils,
        "safe_requests_get",
        lambda *_args, **_kwargs: _Response(
            payload,
            headers={"Content-Type": content_type},
        ),
    )

    assert utils.fetch_and_store_chapters(
        "article",
        None,
        None,
        chapter_url="https://example.com/chapters.json",
        allow_id3=False,
    ) == []


def test_external_chapter_cache_conditionally_revalidates_and_keeps_304_data(
    monkeypatch,
    chapter_db,
):
    article_id = str(uuid.uuid4())
    _insert_article(article_id)
    responses = [
        _Response(
            {
                "version": "1.2.0",
                "chapters": [{"startTime": 0, "title": "Intro"}],
            },
            headers={
                "Content-Type": "application/json+chapters",
                "ETag": '"chapter-v1"',
            },
        ),
        _Response(None, status_code=304, headers={"ETag": '"chapter-v1"'}),
    ]
    seen_headers = []

    def fake_get(_url, **kwargs):
        seen_headers.append(kwargs["headers"])
        return responses.pop(0)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)
    first = utils.fetch_and_store_chapters(
        article_id,
        None,
        None,
        chapter_url="https://example.com/chapters.json",
        allow_id3=False,
    )
    second = utils.fetch_and_store_chapters(
        article_id,
        None,
        None,
        chapter_url="https://example.com/chapters.json",
        allow_id3=False,
        force_refresh=True,
    )

    assert first == second == [{"start": 0.0, "title": "Intro", "href": None}]
    assert seen_headers[1]["If-None-Match"] == '"chapter-v1"'
    assert seen_headers[1]["Cache-Control"] == "no-cache, max-age=0"


def test_chapter_redirect_rejects_private_target_before_following(monkeypatch):
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        return _Response(
            None,
            status_code=302,
            headers={"Location": "http://127.0.0.1/private.json"},
        )

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    assert utils.fetch_and_store_chapters(
        "article",
        None,
        None,
        chapter_url="https://example.com/chapters.json",
        allow_id3=False,
    ) == []
    assert calls == ["https://example.com/chapters.json"]


def test_hosted_chapter_cache_is_provider_scoped_without_local_article(
    monkeypatch,
    chapter_db,
):
    response = _Response(
        {
            "version": "1.2.0",
            "chapters": [{"startTime": 5, "title": "Hosted"}],
        },
        headers={"Content-Type": "application/json"},
    )
    monkeypatch.setattr(utils, "safe_requests_get", lambda *_args, **_kwargs: response)
    inoreader_key = utils.build_chapter_cache_key("Inoreader", "shared-id")
    bazqux_key = utils.build_chapter_cache_key("BazQux", "shared-id")

    chapters = utils.fetch_and_store_chapters(
        "shared-id",
        None,
        None,
        chapter_url="https://example.com/hosted.json",
        allow_id3=False,
        cache_key=inoreader_key,
    )

    assert utils.get_chapters_from_db("shared-id", cache_key=inoreader_key) == chapters
    assert utils.get_chapters_from_db("shared-id", cache_key=bazqux_key) == []
    assert utils.get_chapters_batch(
        ["shared-id"],
        cache_keys={"shared-id": inoreader_key},
    ) == {"shared-id": chapters}


def test_json_chapter_fetch_rejects_non_http_url_without_request(monkeypatch):
    monkeypatch.setattr(
        utils,
        "safe_requests_get",
        lambda *_args, **_kwargs: pytest.fail("request should not be made"),
    )

    assert utils.fetch_and_store_chapters(
        "article",
        None,
        None,
        chapter_url="file:///tmp/chapters.json",
        allow_id3=False,
    ) == []


def test_atomic_replacement_rolls_back_and_preserves_previous_rows(monkeypatch, chapter_db):
    article_id = str(uuid.uuid4())
    other_article_id = str(uuid.uuid4())
    _insert_article(article_id)
    _insert_article(other_article_id)
    old_id = str(uuid.uuid4())
    conflicting_id = str(uuid.uuid4())
    conn = core.db.get_connection()
    try:
        conn.execute(
            "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
            (old_id, article_id, 0.0, "Existing", "https://example.com/old"),
        )
        conn.execute(
            "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
            (conflicting_id, other_article_id, 0.0, "Other", None),
        )
        conn.commit()

        monkeypatch.setattr(utils.uuid, "uuid4", lambda: uuid.UUID(conflicting_id))
        assert utils._replace_stored_chapters(
            article_id,
            [{"start": 10.0, "title": "New", "href": None}],
        ) is False
    finally:
        conn.close()

    assert utils.get_chapters_from_db(article_id) == [
        {"start": 0.0, "title": "Existing", "href": "https://example.com/old"}
    ]


def test_article_delete_cascades_to_chapters(chapter_db):
    article_id = str(uuid.uuid4())
    _insert_article(article_id)
    conn = core.db.get_connection()
    try:
        conn.execute(
            "INSERT INTO chapters (id, article_id, start, title, href) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), article_id, 0.0, "Intro", None),
        )
        conn.commit()
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM chapters WHERE article_id = ?",
            (article_id,),
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_init_db_migrates_non_cascading_chapter_fk(tmp_path):
    original = core.db.DB_FILE
    core.db.DB_FILE = os.path.join(tmp_path, "rss.db")
    try:
        core.db.init_db()
        conn = sqlite3.connect(core.db.DB_FILE)
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("ALTER TABLE chapters RENAME TO chapters_cascade")
            conn.execute(
                "CREATE TABLE chapters ("
                "id TEXT PRIMARY KEY, article_id TEXT, start REAL, title TEXT, href TEXT, "
                "FOREIGN KEY(article_id) REFERENCES articles(id))"
            )
            conn.execute("DROP TABLE chapters_cascade")
            conn.execute("INSERT INTO articles (id, title) VALUES ('article', 'Episode')")
            conn.execute(
                "INSERT INTO chapters (id, article_id, start, title) "
                "VALUES ('chapter', 'article', 0, 'Intro')"
            )
            conn.commit()
        finally:
            conn.close()

        core.db.init_db()
        conn = core.db.get_connection()
        try:
            fk = conn.execute("PRAGMA foreign_key_list(chapters)").fetchone()
            assert fk[2] == "articles"
            assert fk[6] == "CASCADE"
            assert conn.execute("SELECT title FROM chapters").fetchone()[0] == "Intro"
        finally:
            conn.close()
    finally:
        core.db.DB_FILE = original


def test_id3_inline_chapters_sort_dedupe_and_keep_url(monkeypatch, chapter_db):
    article_id = str(uuid.uuid4())
    _insert_article(article_id)

    header = b"ID3\x03\x00\x00\x00\x00\x00\x10"

    def fake_get(_url, headers=None, **_kwargs):
        range_value = (headers or {}).get("Range")
        return _BinaryResponse(header if range_value == "bytes=0-9" else header + b"\0" * 16)

    monkeypatch.setattr(utils, "safe_requests_get", fake_get)

    fake_module = types.ModuleType("mutagen.id3")

    class FakeID3Error(Exception):
        pass

    class TextFrame:
        def __init__(self, text):
            self.text = [text]

    class UrlFrame:
        def __init__(self, url):
            self.url = url

    class ChapterFrame:
        def __init__(self, start, title="", url=None):
            self.start_time = start
            self.sub_frames = SubFrames({"TIT2": TextFrame(title)})
            if url:
                self.sub_frames["WXXX:site"] = UrlFrame(url)

    class SubFrames(dict):
        def getall(self, frame_name):
            return [
                frame
                for key, frame in self.items()
                if key == frame_name or key.startswith(f"{frame_name}:")
            ]

    class FakeID3:
        def __init__(self, _data):
            pass

        def getall(self, name):
            assert name == "CHAP"
            return [
                ChapterFrame(65000, "", "https://example.com/part"),
                ChapterFrame(0, "Intro"),
                ChapterFrame(65000, "Part 2"),
                ChapterFrame(-1000, "Bad"),
            ]

    fake_module.ID3 = FakeID3
    fake_module.error = FakeID3Error
    fake_package = types.ModuleType("mutagen")
    fake_package.id3 = fake_module
    monkeypatch.setitem(sys.modules, "mutagen", fake_package)
    monkeypatch.setitem(sys.modules, "mutagen.id3", fake_module)

    chapters = utils.fetch_and_store_chapters(
        article_id,
        "https://example.com/audio.mp3",
        "audio/mpeg",
    )

    assert chapters == [
        {"start": 0.0, "title": "Intro", "href": None},
        {"start": 65.0, "title": "Part 2", "href": "https://example.com/part"},
    ]
    assert utils.get_chapters_from_db(article_id) == chapters


def test_local_mp4_chapters_use_mutagen_native_chapter_support(
    monkeypatch,
    chapter_db,
    tmp_path,
):
    article_id = str(uuid.uuid4())
    _insert_article(article_id)
    media_path = tmp_path / "episode.m4b"
    media_path.write_bytes(b"placeholder")

    fake_mp4_module = types.ModuleType("mutagen.mp4")

    class _Chapter:
        def __init__(self, start, title):
            self.start = start
            self.title = title

    class _MP4:
        def __init__(self, path):
            assert path == str(media_path)
            self.chapters = [_Chapter(30, "Part 2"), _Chapter(0, "Intro")]

    fake_mp4_module.MP4 = _MP4
    monkeypatch.setitem(sys.modules, "mutagen.mp4", fake_mp4_module)

    chapters = utils.fetch_and_store_chapters(
        article_id,
        str(media_path),
        "audio/mp4",
    )

    assert chapters == [
        {"start": 0.0, "title": "Intro", "href": None},
        {"start": 30.0, "title": "Part 2", "href": None},
    ]


class _BinaryResponse:
    def __init__(self, content):
        self.content = content
        self.ok = True

    def iter_content(self, chunk_size=65536):
        yield self.content[:chunk_size]

    def close(self):
        pass
