# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import feedparser
import sys
import unittest

xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><description>News about international broadcasting. &#xA;&#xA;Retired VOA audience research/media news broadcaster.&#xA;&#xA;Gradually migrating from eponymous account on X.&#xA;&#xA;See also: &#xA;mediafreedomusa.bsky.social&#xA;swradiogram.bsky.social</description><link>https://bsky.app/profile/kaedotcom.bsky.social</link><title>@kaedotcom.bsky.social - Kim Andrew Elliott</title><item><link>https://bsky.app/profile/kaedotcom.bsky.social/post/3mcfiov2e7k2r</link><description>But the Starlink hardware must be somehow acquired …&#xA;&#xA;[contains quote post or other embedded content]</description><pubDate>14 Jan 2026 16:33 +0000</pubDate><guid isPermaLink="false">at://did:plc:mtxycyvfj7hpfhzakyv2pq6d/app.bsky.feed.post/3mcfiov2e7k2r</guid></item></channel></rss>"""

class TestBlueSkyParsing(unittest.TestCase):
    def test_bluesky_parsing(self):
        d = feedparser.parse(xml_content)
        feed_title = d.feed.get('title', 'Unknown')
        print(f"Feed Title: {feed_title}")
        
        for entry in d.entries:
            title = entry.get('title', '')
            author = entry.get('author', 'Unknown')
            description = entry.get('description', '')
            
            print(f"Original Title: '{title}'")
            print(f"Original Author: '{author}'")
            print(f"Description: '{description}'")
            
            # Logic from providers/local.py
            if not title or title.strip() == "No Title":
                 snippet = description or ""
                 # (BS logic omitted for simplicity, just simple strip)
                 if len(snippet) > 80:
                     snippet = snippet[:80] + "..."
                 title = snippet or "No Title"
            
            print(f"Computed Title: '{title}'")
            
            # Proposed Author Fix
            if author == 'Unknown' and feed_title:
                # heuristic: extract handle from feed title "@handle - Name"
                if feed_title.startswith('@'):
                    parts = feed_title.split(' ', 1)
                    if parts:
                        author = parts[0]
                else:
                    author = feed_title
            
            print(f"Computed Author: '{author}'")

            self.assertNotEqual(title, "No Title")
            self.assertNotEqual(author, "Unknown")
            self.assertTrue("Starlink" in title)

if __name__ == "__main__":
    unittest.main()
