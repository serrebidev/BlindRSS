# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import unittest
from core.article_extractor import _should_prefer_feed_content

class TestWiredOptimizations(unittest.TestCase):
    def test_wired_optimization(self):
        # Wired URL with decent content -> True
        url = "https://www.wired.com/story/beats-solo-4-deal-126/"
        content = "x" * 500
        self.assertTrue(_should_prefer_feed_content(url, content))
        
        # Wired URL with short content -> False
        content = "x" * 100
        self.assertFalse(_should_prefer_feed_content(url, content))
        
        # Non-wired URL with decent content -> False (unless super long)
        url = "https://example.com/story"
        content = "x" * 500
        self.assertFalse(_should_prefer_feed_content(url, content))
        
        # Any URL with huge content -> True
        url = "https://example.com/story"
        content = "x" * 3000
        self.assertTrue(_should_prefer_feed_content(url, content))

if __name__ == '__main__':
    unittest.main()
