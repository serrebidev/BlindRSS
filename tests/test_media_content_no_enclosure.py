# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from providers.local import LocalProvider
from core.db import init_db, get_connection


MEDIA_CONTENT_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0' xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Media Content Only</title>
    <item>
      <guid>mc-1</guid>
      <title>Media Content Item</title>
      <link>http://example.com/mc-1</link>
      <description>media content item</description>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
      <media:content url="http://example.com/audio.mp3" type="audio/mpeg" />
    </item>
  </channel>
</rss>
"""


class FeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/media-content":
            body = MEDIA_CONTENT_FEED.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args, **kwargs):
        return


def start_test_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FeedHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


class MediaContentNoEnclosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

        import core.db
        self.orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(self.tmp.name, "rss.db")

        self.httpd, self.http_thread, self.port = start_test_server()

        self.config = {
            "providers": {"local": {}},
            "max_concurrent_refreshes": 2,
            "per_host_max_connections": 1,
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
        }

        init_db()

        self.feed_id = "media-content-feed"
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_id, f"http://127.0.0.1:{self.port}/media-content", "Media Content", "Tests", ""),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.http_thread.join(timeout=1)

        import core.db
        core.db.DB_FILE = self.orig_db_file

        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_media_content_without_enclosure_inserts_article(self):
        provider = LocalProvider(self.config)

        states = []

        def progress_cb(state):
            states.append(state)

        provider.refresh_feed(self.feed_id, progress_cb=progress_cb)

        self.assertTrue(states)
        self.assertEqual(states[-1].get("status"), "ok")

        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT media_url, media_type FROM articles WHERE feed_id = ?",
            (self.feed_id,),
        )
        row = c.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "http://example.com/audio.mp3")
        self.assertEqual(row[1], "audio/mpeg")


if __name__ == "__main__":
    unittest.main()
