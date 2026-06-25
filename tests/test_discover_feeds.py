import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import discovery


class _DummyResp:
    def __init__(self, text: str, url: str = "") -> None:
        self.text = text
        self.url = url
        self.status_code = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def raise_for_status(self) -> None:
        return None


class _DummyHeadResp:
    def __init__(self, status_code: int = 200, content_type: str = "application/rss+xml") -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}


class DiscoverFeedsTests(unittest.TestCase):
    def test_discover_feeds_returns_existing_feed_url(self) -> None:
        self.assertEqual(discovery.discover_feeds("https://example.com/feed.xml"), ["https://example.com/feed.xml"])

    def test_discover_feeds_collects_link_and_anchor_candidates(self) -> None:
        html = """
        <html><head>
          <link rel="alternate" type="application/rss+xml" href="/feed.xml" />
          <link rel="alternate" type="application/atom+xml" href="https://example.com/atom.xml" />
        </head><body>
          <a href="/rss">RSS</a>
          <a href="/not-a-feed">No</a>
        </body></html>
        """

        def head_side_effect(url: str, **_kwargs):
            if url.endswith("/rss.xml"):
                return _DummyHeadResp(200, "application/rss+xml")
            return _DummyHeadResp(404, "text/html")

        with patch("core.discovery.utils.safe_requests_get", return_value=_DummyResp(html)):
            with patch("core.discovery.utils.safe_requests_head", side_effect=head_side_effect):
                feeds = discovery.discover_feeds("https://example.com")

        self.assertIn("https://example.com/feed.xml", feeds)
        self.assertIn("https://example.com/atom.xml", feeds)
        self.assertIn("https://example.com/rss", feeds)
        # From common-path probing via HEAD (stubbed above).
        self.assertIn("https://example.com/rss.xml", feeds)

    def test_discover_feeds_deduplicates(self) -> None:
        html = """
        <html><head>
          <link rel="alternate" type="application/rss+xml" href="/feed.xml" />
          <link rel="alternate" type="application/rss+xml" href="/feed.xml" />
        </head><body>
          <a href="/feed.xml">Feed</a>
        </body></html>
        """
        with patch("core.discovery.utils.safe_requests_get", return_value=_DummyResp(html)):
            with patch("core.discovery.utils.safe_requests_head", return_value=_DummyHeadResp(404, "text/html")):
                feeds = discovery.discover_feeds("https://example.com")

        self.assertEqual(feeds.count("https://example.com/feed.xml"), 1)

    def test_discover_feed_prefers_page_specific_alternate_feed_over_site_feed(self) -> None:
        html = """
        <html><head>
          <link rel="alternate" type="application/rss+xml" title="The Verge" href="/rss/index.xml" />
          <link rel="alternate" type="application/rss+xml" title="Vergecast" href="/rss/the-vergecast/index.xml" />
        </head><body></body></html>
        """

        with patch("core.discovery.utils.safe_requests_get", return_value=_DummyResp(html)):
            out = discovery.discover_feed("https://www.theverge.com/the-vergecast")

        self.assertEqual(out, "https://www.theverge.com/rss/the-vergecast/index.xml")

    def test_discover_feeds_orders_page_specific_alternate_feed_first(self) -> None:
        html = """
        <html><head>
          <link rel="alternate" type="application/rss+xml" title="The Verge" href="/rss/index.xml" />
          <link rel="alternate" type="application/rss+xml" title="Vergecast" href="/rss/the-vergecast/index.xml" />
        </head><body></body></html>
        """

        with patch("core.discovery.utils.safe_requests_get", return_value=_DummyResp(html)):
            with patch("core.discovery.utils.safe_requests_head", return_value=_DummyHeadResp(404, "text/html")):
                feeds = discovery.discover_feeds("https://www.theverge.com/the-vergecast")

        self.assertGreaterEqual(len(feeds), 2)
        self.assertEqual(feeds[0], "https://www.theverge.com/rss/the-vergecast/index.xml")
        self.assertIn("https://www.theverge.com/rss/index.xml", feeds)

    def test_discover_feed_ignores_generic_json_alternate_links(self) -> None:
        html = """
        <html><head>
          <link rel="alternate" type="application/json" href="/wp-json/wp/v2/pages/2042942" />
          <link rel="alternate" type="application/rss+xml" href="/feed.xml" />
        </head><body></body></html>
        """

        with patch("core.discovery.utils.safe_requests_get", return_value=_DummyResp(html)):
            out = discovery.discover_feed("https://example.com/tech")

        self.assertEqual(out, "https://example.com/feed.xml")

    def test_feedback_page_is_not_mistaken_for_a_feed(self) -> None:
        html = '<link rel="alternate" type="application/rss+xml" href="/actual.xml">'
        with patch(
            "core.discovery.utils.safe_requests_get",
            return_value=_DummyResp(html, url="https://example.com/feedback"),
        ):
            out = discovery.discover_feed("https://example.com/feedback")

        self.assertEqual(out, "https://example.com/actual.xml")

    def test_discovery_uses_final_redirect_url_for_relative_links(self) -> None:
        html = '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        response = _DummyResp(html, url="https://www.example.com/articles/")
        with patch("core.discovery.utils.safe_requests_get", return_value=response):
            out = discovery.discover_feed("http://example.com/latest")

        self.assertEqual(out, "https://www.example.com/feed.xml")

    def test_direct_feed_body_returns_effective_url_without_feed_suffix(self) -> None:
        response = _DummyResp(
            "<?xml version='1.0'?><rss version='2.0'><channel /></rss>",
            url="https://example.com/latest",
        )
        response.headers = {"Content-Type": "application/rss+xml"}
        with patch("core.discovery.utils.safe_requests_get", return_value=response):
            self.assertEqual(
                discovery.discover_feeds("https://example.com/latest"),
                ["https://example.com/latest"],
            )

    def test_feed_content_type_does_not_override_html_root(self) -> None:
        response = _DummyResp(
            "<html><body><p>application/rss+xml is only text here.</p></body></html>",
            url="https://example.com/latest",
        )
        response.headers = {"Content-Type": "application/rss+xml"}
        with patch("core.discovery.utils.safe_requests_get", return_value=response), patch(
            "core.discovery.utils.safe_requests_head",
            return_value=_DummyHeadResp(404, "text/html"),
        ):
            self.assertEqual(discovery.discover_feeds("https://example.com/latest"), [])

    def test_feed_tokens_inside_html_do_not_count_as_feed_root(self) -> None:
        html = "<html><body><pre>&lt;rss&gt;</pre><feed>custom element</feed></body></html>"
        response = _DummyResp(html, url="https://example.com/latest")
        with patch("core.discovery.utils.safe_requests_get", return_value=response), patch(
            "core.discovery.utils.safe_requests_head",
            return_value=_DummyHeadResp(404, "text/html"),
        ):
            self.assertIsNone(discovery.discover_feed("https://example.com/latest"))
        self.assertFalse(discovery._body_looks_like_feed("<feed><title>Custom</title></feed>"))

    def test_atom_rdf_and_structured_json_feed_bodies_are_detected(self) -> None:
        atom = "<feed xmlns='http://www.w3.org/2005/Atom'><title>Example</title></feed>"
        rdf = (
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
            "xmlns='http://purl.org/rss/1.0/'><channel /></rdf:RDF>"
        )
        json_feed = '{"version":"https://jsonfeed.org/version/1.1","title":"Example","items":[]}'
        self.assertTrue(discovery._body_looks_like_feed(atom, "text/plain"))
        self.assertTrue(discovery._body_looks_like_feed(rdf, "application/xml"))
        self.assertTrue(discovery._body_looks_like_feed(json_feed, "application/feed+json"))

    def test_invalid_json_feed_header_or_structure_is_rejected(self) -> None:
        self.assertFalse(discovery._body_looks_like_feed("<html></html>", "application/feed+json"))
        self.assertFalse(
            discovery._body_looks_like_feed(
                '{"version":"https://jsonfeed.org/version/1.1","title":"Example"}',
                "application/feed+json",
            )
        )

    def test_false_feed_query_flags_do_not_bypass_network_discovery(self) -> None:
        html = '<link rel="alternate" type="application/rss+xml" href="/actual.xml">'
        for url in (
            "https://example.com/page?feed=false",
            "https://example.com/page?rss=0",
        ):
            with self.subTest(url=url), patch(
                "core.discovery.utils.safe_requests_get",
                return_value=_DummyResp(html, url=url),
            ) as mock_get:
                self.assertEqual(discovery.discover_feed(url), "https://example.com/actual.xml")
                mock_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()

