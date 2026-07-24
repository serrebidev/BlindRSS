# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import sys
import os
import yt_dlp

url = "https://www.bbc.com/news/articles/crmlz7r0zrxo?at_medium=RSS&at_campaign=rss"

ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'referer': url,
    'noprogress': True,
}

print(f"Extracting: {url}")
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        if 'entries' in info:
            entries = list(info['entries'])
            if entries:
                info = entries[0]
        
        url = info.get('url')
        print(f"Success. Title: {info.get('title')}")
        print(f"URL: {url}")
except Exception as e:
    print(f"Failed: {e}")
