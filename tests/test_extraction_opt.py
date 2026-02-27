
import unittest
from core import article_extractor

class TestExtractionOptimizations(unittest.TestCase):
    def test_json_ld_priority(self):
        # Mock HTML with both JSON-LD and regular text
        # Construct a valid JSON string with a long body
        long_body = "This is the JSON-LD body content. " * 50
        html = f"""
        <html>
        <head>
            <script type="application/ld+json">
            {{
                "@context": "https://schema.org",
                "@type": "NewsArticle",
                "headline": "JSON-LD Title",
                "articleBody": "{long_body}"
            }}
            </script>
        </head>
        <body>
            <article>This is the visible text content.</article>
        </body>
        </html>
        """
        # Should return JSON-LD because it's long enough (> 1000 chars)
        extracted = article_extractor._extract_text_any(html, "http://example.com")
        self.assertTrue("JSON-LD body content" in extracted)
        self.assertFalse("visible text content" in extracted)

    def test_wired_pagination_prevention(self):
        # HTML with a "Next Story" link
        html = """
        <html>
        <body>
            <p>Some content</p>
            <a href="/story/next-story" class="button">Next Story</a>
            <a href="/story/page-2">Next Page</a>
        </body>
        </html>
        """
        
        # 1. Wired host -> should return None
        next_url = article_extractor._find_next_page(html, "https://www.wired.com/story/current-story")
        self.assertIsNone(next_url)
        
        # 2. Other host, generic "Next Page" -> should find it
        # (Assuming the logic for "Next Page" works - my mock HTML above has "Next Page" text)
        next_url = article_extractor._find_next_page(html, "https://example.com/story/current-story")
        self.assertEqual(next_url, "https://example.com/story/page-2")
        
        # 3. Other host, "Next Story" -> should be skipped
        html_story = """
        <html><body><a href="/next">Next Story</a></body></html>
        """
        next_url = article_extractor._find_next_page(html_story, "https://example.com/story")
        self.assertIsNone(next_url)

    def test_ning_pagination_prevention(self):
        html = """
        <html>
        <body>
            <a href="/forum/topics/another-topic" class="next">Next</a>
            <a href="/activity/log/list" class="older">Older</a>
        </body>
        </html>
        """
        next_url = article_extractor._find_next_page(
            html,
            "https://creators.ning.com/forum/topics/current-topic",
        )
        self.assertIsNone(next_url)

if __name__ == '__main__':
    unittest.main()
