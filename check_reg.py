# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import requests
import feedparser

def check_register():
    url = "https://www.theregister.com/headlines.rss"
    try:
        resp = requests.get(url, timeout=10)
        d = feedparser.parse(resp.text)
        if not d.entries:
            print("No entries found")
            return
        
        entry = d.entries[0]
        print(f"Title: {entry.get('title')}")
        print(f"Published: {entry.get('published')}")
        print(f"Updated: {entry.get('updated')}")
        print(f"pubDate: {entry.get('pubDate')}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_register()
