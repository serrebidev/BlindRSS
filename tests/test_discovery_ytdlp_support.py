# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.discovery import is_ytdlp_supported


class YtDlpSupportDetectionTests(unittest.TestCase):
    def test_article_page_with_embeds_is_not_auto_supported(self) -> None:
        # 9to5mac pages commonly embed YouTube/audio players. We should not treat
        # arbitrary article URLs as playable media just because yt-dlp could
        # extract an embedded player after downloading the webpage.
        self.assertFalse(
            is_ytdlp_supported("https://9to5mac.com/2025/12/30/some-article/")
        )

    def test_publisher_articles_are_not_supported(self) -> None:
        # Some publishers have dedicated extractors (e.g. NYTimesArticle, CNN, BBC)
        # but standard news articles should not be treated as playable media.
        self.assertFalse(
            is_ytdlp_supported(
                "https://www.nytimes.com/2026/01/03/world/americas/maduro-last-interview-before-capture.html"
            )
        )
        self.assertFalse(
            is_ytdlp_supported("https://www.cnn.com/2026/01/03/world/example/index.html")
        )
        self.assertFalse(is_ytdlp_supported("https://www.bbc.com/news/world-00000000"))

    def test_publisher_video_pages_are_supported(self) -> None:
        self.assertTrue(
            is_ytdlp_supported(
                "https://www.nytimes.com/video/world/100000009000000/some-video.html"
            )
        )
        self.assertTrue(
            is_ytdlp_supported("https://www.cnn.com/videos/world/2026/01/03/example.cnn")
        )
        self.assertTrue(
            is_ytdlp_supported(
                "https://www.bbc.com/news/av/world-00000000/some-video"
            )
        )

    def test_voxmedia_articles_are_not_supported(self) -> None:
        # VoxMedia's extractor matches most publisher pages (including articles)
        # on sites like The Verge. Don't treat arbitrary articles as playable.
        self.assertFalse(
            is_ytdlp_supported(
                "https://www.theverge.com/tech/854082/lg-cloid-home-robot-fold-laundry-ces"
            )
        )

    def test_voxmedia_video_pages_are_supported(self) -> None:
        self.assertTrue(
            is_ytdlp_supported("https://www.theverge.com/videos/123456/some-video")
        )

    def test_youtube_is_supported(self) -> None:
        self.assertTrue(is_ytdlp_supported("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_random_site_is_not_supported(self) -> None:
        self.assertFalse(is_ytdlp_supported("https://example.com/some/path"))

    def test_non_http_scheme_is_not_supported(self) -> None:
        self.assertFalse(is_ytdlp_supported("ftp://example.com/video"))


if __name__ == "__main__":
    unittest.main()
