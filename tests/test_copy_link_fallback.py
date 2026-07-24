# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Copy Link must never hand out a bare homepage for a playable episode.

Podcast feeds like Simplecast's (e.g. Double Tap) set every item's <link> to
the show's homepage; the copyable URL for such items is the enclosure.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe
from core import utils


def test_is_bare_site_root():
    assert utils.is_bare_site_root("https://www.doubletaponair.com")
    assert utils.is_bare_site_root("https://www.doubletaponair.com/")
    assert not utils.is_bare_site_root("https://www.doubletaponair.com/episodes/1")
    assert not utils.is_bare_site_root("https://example.com/?p=1")
    assert not utils.is_bare_site_root("https://example.com/#anchor")
    assert not utils.is_bare_site_root("")
    assert not utils.is_bare_site_root("not a url")


class _Article:
    def __init__(self, url, media_url):
        self.url = url
        self.media_url = media_url


class _Host:
    _article_copy_url = mainframe.MainFrame._article_copy_url
    _has_direct_media_link = mainframe.MainFrame._has_direct_media_link


_MP3 = (
    "https://op3.dev/e/injector.simplecastaudio.com/abc/episodes/def/audio/128/"
    "default.mp3?aid=rss_feed"
)


def test_homepage_link_falls_back_to_enclosure():
    h = _Host()
    art = _Article("https://www.doubletaponair.com", _MP3)
    assert h._article_copy_url(art) == _MP3


def test_real_episode_link_is_kept():
    h = _Host()
    art = _Article("https://example.com/episodes/42", _MP3)
    assert h._article_copy_url(art) == "https://example.com/episodes/42"


def test_missing_link_uses_enclosure():
    h = _Host()
    art = _Article("", _MP3)
    assert h._article_copy_url(art) == _MP3


def test_no_media_keeps_homepage_link():
    h = _Host()
    art = _Article("https://www.doubletaponair.com", None)
    assert h._article_copy_url(art) == "https://www.doubletaponair.com"
