import os
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db
from providers.local import LocalProvider


def _feed_xml(title: str) -> str:
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>{title}</title>
    <item>
      <guid>{title}-ep1</guid>
      <title>Episode 1</title>
      <link>https://example.com/{title}/1</link>
      <description>Test item</description>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class _FeedHandler(BaseHTTPRequestHandler):
    titles = {
        "/feed1": "Original Feed Title",
        "/feed2": "Remote Title A",
    }

    def do_GET(self):
        title = self.titles.get(self.path)
        if title is None:
            self.send_response(404)
            self.end_headers()
            return
        body = _feed_xml(title).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):
        return


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FeedHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


def _get_feed_row(feed_id: str):
    conn = core.db.get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT title, COALESCE(title_is_custom, 0) FROM feeds WHERE id = ?", (feed_id,))
        return c.fetchone()
    finally:
        conn.close()


def _get_feed_row_by_url(url: str):
    conn = core.db.get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, title, COALESCE(title_is_custom, 0) FROM feeds WHERE url = ?",
            (url,),
        )
        return c.fetchone()
    finally:
        conn.close()


def test_local_feed_custom_title_persists_after_refresh():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        httpd, thread, port = _start_server()
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )

            feed_id = str(uuid.uuid4())
            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
                    (feed_id, f"http://127.0.0.1:{port}/feed1", "Original Feed Title", "Podcasts", ""),
                )
                conn.commit()
            finally:
                conn.close()

            assert provider.refresh_feed(feed_id) is True
            assert provider.update_feed(feed_id, title="My Custom Podcasts") is True

            before = _get_feed_row(feed_id)
            assert before == ("My Custom Podcasts", 1)

            _FeedHandler.titles["/feed1"] = "Remote Feed Title Changed"
            assert provider.refresh_feed(feed_id) is True

            after = _get_feed_row(feed_id)
            assert after == ("My Custom Podcasts", 1)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=1)
            core.db.DB_FILE = orig_db_file


def test_local_feed_title_still_updates_on_refresh_when_not_custom():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        httpd, thread, port = _start_server()
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )

            feed_id = str(uuid.uuid4())
            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
                    (feed_id, f"http://127.0.0.1:{port}/feed2", "Remote Title A", "News", ""),
                )
                conn.commit()
            finally:
                conn.close()

            assert provider.refresh_feed(feed_id) is True
            _FeedHandler.titles["/feed2"] = "Remote Title B"
            assert provider.refresh_feed(feed_id) is True

            title, title_is_custom = _get_feed_row(feed_id)
            assert title == "Remote Title B"
            assert int(title_is_custom or 0) == 0
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=1)
            core.db.DB_FILE = orig_db_file


def test_local_feed_reset_title_restores_remote_title_on_refresh():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        httpd, thread, port = _start_server()
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )

            feed_id = str(uuid.uuid4())
            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
                    (feed_id, f"http://127.0.0.1:{port}/feed1", "Original Feed Title", "Podcasts", ""),
                )
                conn.commit()
            finally:
                conn.close()

            assert provider.refresh_feed(feed_id) is True
            assert provider.update_feed(feed_id, title="My Custom Podcasts") is True
            assert provider.reset_feed_title(feed_id) is True

            title, title_is_custom = _get_feed_row(feed_id)
            assert title == "My Custom Podcasts"
            assert int(title_is_custom or 0) == 0

            _FeedHandler.titles["/feed1"] = "Remote Feed Title Reset"
            assert provider.refresh_feed(feed_id) is True

            title, title_is_custom = _get_feed_row(feed_id)
            assert title == "Remote Feed Title Reset"
            assert int(title_is_custom or 0) == 0
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=1)
            core.db.DB_FILE = orig_db_file


def test_opml_imported_feed_title_is_preserved_on_refresh():
    with tempfile.TemporaryDirectory() as tmp:
        orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(tmp, "rss.db")
        httpd, thread, port = _start_server()
        try:
            provider = LocalProvider(
                {
                    "providers": {"local": {}},
                    "feed_timeout_seconds": 2,
                    "feed_retry_attempts": 0,
                }
            )

            feed_url = f"http://127.0.0.1:{port}/feed1"
            custom_title = "My OPML Custom Name"
            opml_path = os.path.join(tmp, "feeds.opml")
            with open(opml_path, "w", encoding="utf-8") as f:
                f.write(
                    f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="Podcasts">
      <outline text="{custom_title}" xmlUrl="{feed_url}" />
    </outline>
  </body>
</opml>
"""
                )

            assert provider.import_opml(opml_path) is True

            row = _get_feed_row_by_url(feed_url)
            assert row is not None
            feed_id, title, title_is_custom = row
            assert title == custom_title
            assert int(title_is_custom or 0) == 1

            _FeedHandler.titles["/feed1"] = "Remote Feed Title Changed"
            assert provider.refresh_feed(feed_id) is True

            row = _get_feed_row_by_url(feed_url)
            assert row is not None
            _feed_id2, title, title_is_custom = row
            assert title == custom_title
            assert int(title_is_custom or 0) == 1
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=1)
            core.db.DB_FILE = orig_db_file
