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


FEED_XML = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Shared Feed</title>
    <item>
      <guid>shared-1</guid>
      <title>Shared Item</title>
      <link>http://example.com/shared-1</link>
      <description>shared body</description>
      <pubDate>Tue, 27 Jan 2026 05:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class SharedFeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = FEED_XML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):
        # Silence default logging
        return


def start_test_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SharedFeedHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


class DuplicateItemIdAcrossFeedsTests(unittest.TestCase):
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

        self.feed_a = "feed-a"
        self.feed_b = "feed-b"
        url = f"http://127.0.0.1:{self.port}/rss"

        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_a, url, "Feed A", "Tests", ""),
        )
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_b, url, "Feed B", "Tests", ""),
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

    def test_duplicate_ids_are_scoped_per_feed(self):
        provider = LocalProvider(self.config)
        progress = []

        def progress_cb(state):
            progress.append(state)

        provider.refresh(progress_cb)

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_a,))
        count_a = int(c.fetchone()[0] or 0)
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_b,))
        count_b = int(c.fetchone()[0] or 0)
        c.execute("SELECT id FROM articles")
        ids = [row[0] for row in c.fetchall()]
        conn.close()

        self.assertEqual(count_a, 1)
        self.assertEqual(count_b, 1)
        self.assertEqual(len(set(ids)), 2)

        status_map = {item.get("id"): item.get("status") for item in progress}
        self.assertEqual(status_map.get(self.feed_a), "ok")
        self.assertEqual(status_map.get(self.feed_b), "ok")


if __name__ == "__main__":
    unittest.main()
