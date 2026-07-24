# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.db
import providers.local as local_mod
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


class _DiscoveryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/site":
            body = (
                "<html><head>"
                '<link rel="alternate" type="application/rss+xml" href="/feed1" />'
                "</head><body>Homepage</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/feed1":
            body = _feed_xml("Resolved Feed Title").encode("utf-8")
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


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _DiscoveryHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, port


def _get_feed_row_by_id(feed_id: str):
    conn = core.db.get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT url, title, COALESCE(title_is_custom, 0) FROM feeds WHERE id = ?",
            (feed_id,),
        )
        return c.fetchone()
    finally:
        conn.close()


def _get_feed_row_by_url(url: str):
    conn = core.db.get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, url, title, COALESCE(title_is_custom, 0) FROM feeds WHERE url = ?",
            (url,),
        )
        return c.fetchone()
    finally:
        conn.close()


def test_opml_import_keeps_homepage_xmlurl_without_network_discovery(monkeypatch):
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

            homepage_url = f"http://127.0.0.1:{port}/site"
            feed_url = f"http://127.0.0.1:{port}/feed1"
            custom_title = "Imported Homepage Feed"
            opml_path = os.path.join(tmp, "feeds.opml")

            def _discover_should_not_run(_url: str):
                raise AssertionError("discover_feed should not be called during OPML import")

            monkeypatch.setattr(local_mod, "discover_feed", _discover_should_not_run)

            with open(opml_path, "w", encoding="utf-8") as f:
                f.write(
                    f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="News">
      <outline text="{custom_title}" xmlUrl="{homepage_url}" />
    </outline>
  </body>
</opml>
"""
                )

            assert provider.import_opml(opml_path) is True

            row = _get_feed_row_by_url(homepage_url)
            assert row is not None
            _feed_id, stored_url, title, title_is_custom = row
            assert stored_url == homepage_url
            assert title == custom_title
            assert int(title_is_custom or 0) == 1
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=1)
            core.db.DB_FILE = orig_db_file


def test_refresh_feed_repairs_homepage_url_and_loads_articles():
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

            homepage_url = f"http://127.0.0.1:{port}/site"
            feed_url = f"http://127.0.0.1:{port}/feed1"
            feed_id = str(uuid.uuid4())

            conn = core.db.get_connection()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO feeds (id, url, title, category, icon_url) VALUES (?, ?, ?, ?, ?)",
                    (feed_id, homepage_url, "Homepage Import", "News", ""),
                )
                conn.commit()
            finally:
                conn.close()

            assert provider.refresh_feed(feed_id) is True

            row = _get_feed_row_by_id(feed_id)
            assert row is not None
            stored_url, _title, _title_is_custom = row
            assert stored_url == feed_url

            articles = provider.get_articles(feed_id=feed_id)
            assert len(articles) == 1
            assert articles[0].title == "Episode 1"
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=1)
            core.db.DB_FILE = orig_db_file
