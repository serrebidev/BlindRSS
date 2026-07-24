# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

# Ensure repo root on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe
from core.db import get_connection, init_db
from providers.local import LocalProvider


FLAC_ALIAS_FEED = """<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'>
  <channel>
    <title>FLAC Alias Feed</title>
    <item>
      <guid>flac-1</guid>
      <title>Episode in FLAC</title>
      <link>https://example.com/post/1</link>
      <description>FLAC podcast</description>
      <pubDate>Fri, 05 Dec 2025 10:00:00 GMT</pubDate>
      <enclosure url="https://media.example.com/download?id=abc123" type="application/flac" length="12345" />
    </item>
  </channel>
</rss>
"""


class _FeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/feed":
            body = FLAC_ALIAS_FEED.encode("utf-8")
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


def _start_test_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FeedHandler)
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


class _DummyMain:
    _should_play_in_player = mainframe.MainFrame._should_play_in_player


def test_mainframe_treats_flac_mime_alias_as_playable(monkeypatch):
    monkeypatch.setattr(mainframe.core.discovery, "is_ytdlp_supported", lambda _url: False)
    host = _DummyMain()
    article = SimpleNamespace(
        url="https://example.com/post/1",
        media_url="https://media.example.com/download?id=abc123",
        media_type="application/flac",
    )
    assert host._should_play_in_player(article) is True


class LocalProviderFlacAliasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

        import core.db

        self.orig_db_file = core.db.DB_FILE
        core.db.DB_FILE = os.path.join(self.tmp.name, "rss.db")

        self.httpd, self.http_thread, self.port = _start_test_server()

        self.config = {
            "providers": {"local": {}},
            "max_concurrent_refreshes": 2,
            "per_host_max_connections": 1,
            "feed_timeout_seconds": 2,
            "feed_retry_attempts": 0,
        }

        init_db()

        self.feed_id = "flac-alias-feed"
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
            (self.feed_id, f"http://127.0.0.1:{self.port}/feed", "FLAC Alias", "Tests", ""),
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

    def test_local_provider_accepts_application_flac_enclosure(self):
        provider = LocalProvider(self.config)
        provider.refresh_feed(self.feed_id)

        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT media_url, media_type FROM articles WHERE feed_id = ?",
            (self.feed_id,),
        )
        row = c.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "https://media.example.com/download?id=abc123")
        self.assertEqual(row[1], "audio/flac")


if __name__ == "__main__":
    unittest.main()
