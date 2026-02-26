import unittest
from unittest.mock import patch

from core import article_extractor


class TestNingActivityFullText(unittest.TestCase):
    def test_should_prefer_feed_content_for_ning_activity_html(self):
        html = """
        <span class="feed-string"><a href="https://example.ning.com/profile/User?xg_source=activity">User</a> posted a video</span>
        <div class="rich">
          <h3 class="feed-story-title"><a href="https://example.ning.com/xn/detail/1:Video:123?xg_source=activity">Actual Title</a></h3>
          <div class="rich-excerpt">This is the useful feed excerpt.</div>
        </div>
        """
        self.assertTrue(
            article_extractor._should_prefer_feed_content(
                "https://example.ning.com/xn/detail/1:Video:123?xg_source=activity",
                html,
            )
        )

    def test_should_prefer_feed_content_for_ning_creators_plain_activity_fragment(self):
        html = """
        <div><a href="https://creators.ning.com/members/ScottBishop">Scott Bishop</a>
        <a href="https://creators.ning.com/forum/topics/foo?commentId=6651893%3AComment%3A2107942">replied</a>
        to <a href="https://creators.ning.com/members/Alex">Alex</a>'s discussion
        <br/> <strong><a href="https://creators.ning.com/forum/topics/foo">Topic title</a></strong></div>
        <div><div>Reply excerpt text.</div></div>
        """
        self.assertTrue(
            article_extractor._should_prefer_feed_content(
                "https://creators.ning.com/forum/topics/foo?commentId=6651893%3AComment%3A2107942",
                html,
            )
        )

    def test_render_full_article_uses_feed_content_for_ning_activity(self):
        html = """
        <div class="feed-string">Someone posted a discussion</div>
        <div class="rich-detail"><div class="rich-excerpt">Useful Ning feed description text.</div></div>
        """
        feed_art = article_extractor.FullArticle(
            url="https://example.ning.com/forum/topics/test",
            title="Some Activity Title",
            author="",
            text="Useful Ning feed description text.",
        )

        with patch("core.article_extractor.extract_from_html", return_value=feed_art) as p_feed:
            with patch("core.article_extractor.extract_full_article") as p_web:
                rendered = article_extractor.render_full_article(
                    "https://example.ning.com/forum/topics/test?xg_source=activity",
                    fallback_html=html,
                    fallback_title="Some Activity Title",
                    fallback_author="",
                    prefer_feed_content=True,
                )

        self.assertIsNotNone(rendered)
        self.assertIn("Useful Ning feed description text.", rendered)
        p_feed.assert_called()
        p_web.assert_not_called()

    def test_postprocess_strips_ning_activity_wrapper_lines_and_more_noise(self):
        text = "\n".join(
            [
                "Shakti Meditation",
                "posted a video",
                "Breaking Free from the Stream of Thought",
                "Useful excerpt text from the activity feed.",
                "1 more…",
            ]
        )
        out = article_extractor._postprocess_extracted_text(
            text,
            "https://example.ning.com/xn/detail/1:Video:123?xg_source=activity",
        )
        self.assertNotIn("posted a video", out)
        self.assertNotIn("1 more", out)
        self.assertIn("Breaking Free from the Stream of Thought", out)
        self.assertIn("Useful excerpt text from the activity feed.", out)

    def test_postprocess_keeps_short_profile_update_activity_text(self):
        text = "\n".join(["Kathleen (SunKat)", "updated their", "profile"])
        out = article_extractor._postprocess_extracted_text(
            text,
            "https://creators.ning.com/members/Kathleen_aka_SunKat",
        )
        self.assertIn("Kathleen (SunKat)", out)
        self.assertIn("updated their", out)
        self.assertIn("profile", out)


if __name__ == "__main__":
    unittest.main()
