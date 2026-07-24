# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.rumble import extract_embed_id_from_video_html, parse_listing_html
from core import rumble as rumble_mod


class RumbleParsingTests(unittest.TestCase):
    def test_extract_embed_id_from_rumble_play_snippet(self) -> None:
        html = """
        <html><head></head><body>
        <script>
        Rumble("play", {"video":"v71gjmm","rel":11});
        </script>
        </body></html>
        """
        self.assertEqual(extract_embed_id_from_video_html(html), "v71gjmm")

    def test_parse_listing_card(self) -> None:
        html = """
        <div class="videostream thumbnail__grid--item" data-video-id="425714782">
          <a class="videostream__link" href="/v73n7mu-some-video.html?e9s=tracking"></a>
          <h3 class="thumbnail__title">Some Title</h3>
          <time class="videostream__time" datetime="2025-12-30T11:13:00-04:00">Dec 30</time>
        </div>
        """
        items = parse_listing_html(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Some Title")
        self.assertEqual(items[0].published, "2025-12-30T11:13:00-04:00")
        self.assertEqual(items[0].url, "https://rumble.com/v73n7mu-some-video.html")

    def test_pick_best_url_prefers_mp4(self) -> None:
        video = {
            "ua": {
                "mp4": {
                    "360": {"url": "https://cdn.example/360.mp4", "meta": {"h": 360, "bitrate": 500}},
                    "720": {"url": "https://cdn.example/720.mp4", "meta": {"h": 720, "bitrate": 800}},
                }
            }
        }
        picked = rumble_mod._pick_best_direct_url(video)  # intentional: internal selection logic
        self.assertEqual(picked, "https://cdn.example/720.mp4")

    def test_pick_best_url_avoids_rumble_hls_when_tar_available(self) -> None:
        video = {
            "ua": {
                "hls": {
                    "vod": {"url": "https://rumble.com/hls-vod/abcd/playlist.m3u8", "meta": {"h": 1080, "bitrate": 999}},
                },
                "tar": {
                    "1080": {
                        "url": "https://1a-1791.com/video/x/y/z.tar?r_file=chunklist.m3u8&r_range=1-2",
                        "meta": {"h": 1080, "bitrate": 1234},
                    }
                },
            }
        }
        picked = rumble_mod._pick_best_direct_url(video)
        self.assertTrue(picked.startswith("https://1a-1791.com/"))

    def test_pick_stream_rendition_caps_height(self) -> None:
        # Recorded live streams expose only combined video+audio renditions;
        # picking the top one (1080p+) stalls playback start (yt-dlp policy
        # is best[height<=480]/worst).
        video = {
            "ua": {
                "tar": {
                    "240": {"url": "https://1a-1791.com/x.tar?f=240", "meta": {"h": 240, "bitrate": 300}},
                    "480": {"url": "https://1a-1791.com/x.tar?f=480", "meta": {"h": 480, "bitrate": 700}},
                    "1080": {"url": "https://1a-1791.com/x.tar?f=1080", "meta": {"h": 1080, "bitrate": 3000}},
                }
            }
        }
        picked = rumble_mod._pick_best_direct_url(video)
        self.assertEqual(picked, "https://1a-1791.com/x.tar?f=480")

    def test_pick_stream_rendition_falls_back_to_smallest(self) -> None:
        video = {
            "ua": {
                "hls": {
                    "720": {"url": "https://1a-1791.com/x.m3u8?f=720", "meta": {"h": 720, "bitrate": 1500}},
                    "1080": {"url": "https://1a-1791.com/x.m3u8?f=1080", "meta": {"h": 1080, "bitrate": 3000}},
                }
            }
        }
        picked = rumble_mod._pick_best_direct_url(video)
        self.assertEqual(picked, "https://1a-1791.com/x.m3u8?f=720")


if __name__ == "__main__":
    unittest.main()

