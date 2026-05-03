import os
import sys
import time
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


FAST_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Fast Feed</title>
    <item>
      <guid>fast-1</guid>
      <title>Fast Item</title>
      <link>http://example.com/fast-1</link>
      <description>fast body</description>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

SLOW_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Slow Feed</title>
    <item>
      <guid>slow-1</guid>
      <title>Slow Item</title>
      <link>http://example.com/slow-1</link>
      <description>slow body</description>
      <pubDate>Fri, 05 Dec 2025 10:00:01 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class FeedHandler(BaseHTTPRequestHandler):
    delays = {
        "/fast": 0,
        "/slow": 0.4,
    }

    def do_GET(self):
        if self.path == "/fast":
            self._respond(FAST_FEED)
        elif self.path == "/slow":
            time.sleep(self.delays[self.path])
            self._respond(SLOW_FEED)
        elif self.path == "/fail":
            self.send_response(500)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args, **kwargs):
        # Silence default logging
        return

    def _respond(self, body: str):
        body_bytes = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


def start_test_server():
    # Bind to an ephemeral port on localhost
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FeedHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


class LocalProviderParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        
        # Patch DB location to use the temp dir
        import core.db
        self.orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(self.tmp.name, "rss.db")

        self.httpd, self.http_thread, self.port = start_test_server()

        self.config = {
            "providers": {"local": {}},
            "max_concurrent_refreshes": 4,
            "per_host_max_connections": 2,
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
        }

        init_db()

        self.feed_ids = {
            "fast": "fast-feed",
            "slow": "slow-feed",
            "fail": "fail-feed",
        }

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM chapters")
        c.execute("DELETE FROM articles")
        c.execute("DELETE FROM feeds")
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_ids["fast"], f"http://127.0.0.1:{self.port}/fast", "Fast", "Tests", ""),
        )
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_ids["slow"], f"http://127.0.0.1:{self.port}/slow", "Slow", "Tests", ""),
        )
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_ids["fail"], f"http://127.0.0.1:{self.port}/fail", "Fail", "Tests", ""),
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

    def test_parallel_refresh_orders_and_survives_failures(self):
        provider = LocalProvider(self.config)
        progress_order = []

        def progress_cb(state):
            progress_order.append((state.get("id"), state.get("status")))

        provider.refresh(progress_cb)

        ids_in_order = [item[0] for item in progress_order]
        self.assertIn(self.feed_ids["fast"], ids_in_order)
        self.assertIn(self.feed_ids["slow"], ids_in_order)
        # Fast feed should complete before slow feed
        self.assertLess(ids_in_order.index(self.feed_ids["fast"]), ids_in_order.index(self.feed_ids["slow"]))

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_ids["fast"],))
        fast_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_ids["slow"],))
        slow_count = c.fetchone()[0]
        conn.close()

        self.assertGreaterEqual(fast_count, 1)
        self.assertGreaterEqual(slow_count, 1)

        # Failure should be reported but not stop others
        status_map = {fid: status for fid, status in progress_order}
        self.assertEqual(status_map.get(self.feed_ids["fail"]), "error")

    def test_refresh_feeds_by_ids_refreshes_requested_subset_only(self):
        provider = LocalProvider(self.config)
        progress_order = []

        def progress_cb(state):
            progress_order.append((state.get("id"), state.get("status")))

        ok = provider.refresh_feeds_by_ids(
            [self.feed_ids["slow"], self.feed_ids["fast"]],
            progress_cb=progress_cb,
            force=True,
        )

        self.assertTrue(ok)

        ids_in_order = [item[0] for item in progress_order]
        self.assertIn(self.feed_ids["fast"], ids_in_order)
        self.assertIn(self.feed_ids["slow"], ids_in_order)
        self.assertNotIn(self.feed_ids["fail"], ids_in_order)
        self.assertLess(ids_in_order.index(self.feed_ids["fast"]), ids_in_order.index(self.feed_ids["slow"]))

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_ids["fast"],))
        fast_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_ids["slow"],))
        slow_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_ids["fail"],))
        fail_count = c.fetchone()[0]
        conn.close()

        self.assertGreaterEqual(fast_count, 1)
        self.assertGreaterEqual(slow_count, 1)
        self.assertEqual(fail_count, 0)


if __name__ == "__main__":
    unittest.main()
