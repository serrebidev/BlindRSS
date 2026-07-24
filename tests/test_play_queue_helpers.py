# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Unit tests for the play-queue / media-time helpers that don't need a wx.App.

Both helpers under test are staticmethods on MainFrame, so they can be exercised
on the class without constructing the window.
"""

from gui.mainframe import MainFrame


def test_format_media_time():
    fmt = MainFrame._format_media_time
    assert fmt(0) == "0:00"
    assert fmt(5000) == "0:05"
    assert fmt(65000) == "1:05"
    assert fmt(3600000) == "1:00:00"
    assert fmt(3661000) == "1:01:01"
    # Robust against junk input.
    assert fmt(None) == "0:00"
    assert fmt(-1000) == "0:00"


def test_queue_entry_key_prefers_article_id():
    key = MainFrame._queue_entry_key
    assert key({"article_id": "abc", "media_url": "u"}) == "id:abc"
    assert key({"article_id": "", "media_url": "http://x/y.mp3"}) == "url:http://x/y.mp3"
    assert key({"article_id": None, "media_url": "http://x/y.mp3"}) == "url:http://x/y.mp3"
