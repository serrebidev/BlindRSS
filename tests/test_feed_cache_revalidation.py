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


FEED_V1 = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Cache Test Feed</title>
    <item>
      <guid>cache-test-1</guid>
      <title>Episode 1</title>
      <link>http://example.com/1</link>
      <description>test body</description>
      <pubDate>Sat, 14 Feb 2026 17:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


FEED_V2 = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>Cache Test Feed</title>
    <item>
      <guid>cache-test-2</guid>
      <title>Episode 2</title>
      <link>http://example.com/2</link>
      <description>test body</description>
      <pubDate>Sat, 14 Feb 2026 18:00:00 GMT</pubDate>
    </item>
    <item>
      <guid>cache-test-1</guid>
      <title>Episode 1</title>
      <link>http://example.com/1</link>
      <description>test body</description>
      <pubDate>Sat, 14 Feb 2026 17:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class StaleCacheHandler(BaseHTTPRequestHandler):
    """Simulate a CDN that serves a stale cached representation unless revalidated.

    - Without Cache-Control/Pragma "no-cache": reply using cached_* validators/body.
    - With "no-cache": reply using origin_* validators/body (fresh content).
    """

    cached_etag = "v1"
    cached_body = FEED_V1.encode("utf-8")
    origin_etag = "v1"
    origin_body = FEED_V1.encode("utf-8")
    saw_no_cache = False
    saw_conditional = False

    def do_GET(self):
        cache_control = (self.headers.get("Cache-Control") or "").lower()
        pragma = (self.headers.get("Pragma") or "").lower()
        no_cache = ("no-cache" in cache_control) or ("no-cache" in pragma)
        if no_cache:
            type(self).saw_no_cache = True
            etag = type(self).origin_etag
            body = type(self).origin_body
        else:
            etag = type(self).cached_etag
            body = type(self).cached_body

        inm = self.headers.get("If-None-Match")
        if inm or self.headers.get("If-Modified-Since"):
            type(self).saw_conditional = True
        if inm and inm.strip() == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):
        # Silence default logging
        return


def start_test_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), StaleCacheHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


class FeedCacheRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

        import core.db

        self.orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(self.tmp.name, "rss.db")

        self.httpd, self.http_thread, self.port = start_test_server()
        StaleCacheHandler.cached_etag = "v1"
        StaleCacheHandler.cached_body = FEED_V1.encode("utf-8")
        StaleCacheHandler.origin_etag = "v1"
        StaleCacheHandler.origin_body = FEED_V1.encode("utf-8")
        StaleCacheHandler.saw_no_cache = False
        StaleCacheHandler.saw_conditional = False

        self.config = {
            "providers": {"local": {}},
            "max_concurrent_refreshes": 2,
            "per_host_max_connections": 1,
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
        }

        init_db()

        self.feed_id = "cache-feed"
        self.feed_url = f"http://127.0.0.1:{self.port}/rss"

        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM chapters")
        c.execute("DELETE FROM articles")
        c.execute("DELETE FROM feeds")
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url, etag, last_modified) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.feed_id, self.feed_url, "Cache Test Feed", "Tests", "", None, None),
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

    def test_refresh_revalidates_through_stale_cache(self):
        provider = LocalProvider(self.config)

        # Initial refresh: populate the DB with v1 and store the feed's ETag.
        provider.refresh(force=False)

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_id,))
        count1 = int(c.fetchone()[0] or 0)
        c.execute("SELECT etag FROM feeds WHERE id = ?", (self.feed_id,))
        etag1 = c.fetchone()[0]
        conn.close()

        self.assertEqual(count1, 1)
        self.assertEqual(etag1, "v1")

        # Origin updates to v2, but the "cache" still serves v1 unless we force revalidation.
        StaleCacheHandler.origin_etag = "v2"
        StaleCacheHandler.origin_body = FEED_V2.encode("utf-8")

        provider.refresh(force=False)

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_id,))
        count2 = int(c.fetchone()[0] or 0)
        c.execute("SELECT etag FROM feeds WHERE id = ?", (self.feed_id,))
        etag2 = c.fetchone()[0]
        conn.close()

        self.assertTrue(StaleCacheHandler.saw_no_cache)
        self.assertEqual(count2, 2)
        self.assertEqual(etag2, "v2")

    def test_initial_refresh_sends_revalidation_without_validators(self):
        provider = LocalProvider(self.config)

        provider.refresh(force=False)

        self.assertTrue(StaleCacheHandler.saw_no_cache)
        self.assertFalse(StaleCacheHandler.saw_conditional)

    def test_force_refresh_bypasses_conditional_validators(self):
        provider = LocalProvider(self.config)

        provider.refresh(force=False)

        StaleCacheHandler.saw_no_cache = False
        StaleCacheHandler.saw_conditional = False
        provider.refresh(force=True)

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM articles WHERE feed_id = ?", (self.feed_id,))
        count = int(c.fetchone()[0] or 0)
        c.execute("SELECT etag FROM feeds WHERE id = ?", (self.feed_id,))
        etag = c.fetchone()[0]
        conn.close()

        self.assertTrue(StaleCacheHandler.saw_no_cache)
        self.assertFalse(StaleCacheHandler.saw_conditional)
        self.assertEqual(count, 1)
        self.assertEqual(etag, "v1")


if __name__ == "__main__":
    unittest.main()
