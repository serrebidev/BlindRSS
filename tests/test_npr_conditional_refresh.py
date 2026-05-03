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
    <title>NPR Test Feed</title>
    <item>
      <guid>npr-test-1</guid>
      <title>NPR Test Item</title>
      <link>http://example.com/npr-test-item</link>
      <description>test body</description>
      <pubDate>Tue, 27 Jan 2026 05:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class NprConditionalHandler(BaseHTTPRequestHandler):
    saw_ims = False

    def do_GET(self):
        if self.headers.get("If-Modified-Since") or self.headers.get("If-None-Match"):
            type(self).saw_ims = True
            self.send_response(304)
            self.end_headers()
            return

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
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), NprConditionalHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


class NprConditionalRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

        import core.db
        self.orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(self.tmp.name, "rss.db")

        self.httpd, self.http_thread, self.port = start_test_server()
        NprConditionalHandler.saw_ims = False

        self.config = {
            "providers": {"local": {}},
            "max_concurrent_refreshes": 2,
            "per_host_max_connections": 1,
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
        }

        init_db()

        self.feed_id = "npr-feed"
        self.feed_url = f"http://127.0.0.1:{self.port}/rss?source=npr.org"

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM chapters")
        c.execute("DELETE FROM articles")
        c.execute("DELETE FROM feeds")
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url, etag, last_modified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self.feed_id,
                self.feed_url,
                "NPR Test",
                "Tests",
                "",
                "etag-test",
                "Mon, 01 Jan 2024 00:00:00 GMT",
            ),
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

    def test_npr_skips_conditional_headers(self):
        provider = LocalProvider(self.config)
        provider.refresh()

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_id,))
        count = int(c.fetchone()[0] or 0)
        conn.close()

        self.assertGreaterEqual(count, 1)
        self.assertFalse(NprConditionalHandler.saw_ims)


if __name__ == "__main__":
    unittest.main()
