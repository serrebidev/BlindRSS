from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from core.utils import parse_datetime_utc

class Article:
    def __init__(self, title: str, url: str, content: str, date: str, author: str, feed_id: str, is_read: bool = False, id: str = None, media_url: str = None, media_type: str = None, chapters: list = None, is_favorite: bool = False, cache_id: str = None, description: str = None):
        self.id = id or url  # Use URL as ID if generic ID not provided
        self.title = title
        self.url = url
        self.content = content
        self.description = description
        self.date = date
        self.author = author
        self.feed_id = feed_id
        self.is_read = is_read
        self.is_favorite = bool(is_favorite)
        self.media_url = media_url
        self.media_type = media_type
        self.chapters = chapters or []
        if cache_id:
            self.cache_id = cache_id
        else:
            if self.feed_id and self.id:
                feed_prefix = f"{self.feed_id}:"
                if str(self.id).startswith(feed_prefix):
                    self.cache_id = self.id
                else:
                    self.cache_id = f"{self.feed_id}:{self.id}"
            else:
                self.cache_id = self.id
        
        self.timestamp = 0.0
        if self.date:
            dt = parse_datetime_utc(self.date)
            if dt:
                self.timestamp = dt.timestamp()

class Feed:
    def __init__(self, id: str, title: str, url: str, category: str = "Uncategorized", icon_url: str = None):
        self.id = id
        self.title = title
        self.url = url
        self.category = category
        self.icon_url = icon_url
        self.unread_count = 0
