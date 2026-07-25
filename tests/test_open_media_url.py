# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""File > Open Media URL: paste any supported link and stream or download it.

Feeds drop older items, so a video that has scrolled out of a subscription is
unreachable from the article list. These tests cover the two halves: what
counts as a usable URL (core.media_url, GUI-free) and how the command routes a
URL to the player or the downloader (gui.mainframe), including the refusals —
a rejected action has to say so rather than quietly do nothing.
"""

import os
import sys
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import media_url  # noqa: E402
import gui.mainframe as mainframe  # noqa: E402


YT_WATCH = "https://www.youtube.com/watch?v=s-59p7kUAaE"
DIRECT_MP3 = "https://media.example.com/shows/episode-42.mp3"


# --- core.media_url --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (YT_WATCH, YT_WATCH),
        ("  " + YT_WATCH + "  ", YT_WATCH),
        ("<" + YT_WATCH + ">", YT_WATCH),
        ('"' + YT_WATCH + '"', YT_WATCH),
        ("\u201c" + YT_WATCH + "\u201d", YT_WATCH),
        ("https://youtu.be/s-59p7kUAaE", "https://youtu.be/s-59p7kUAaE"),
        ("http://example.com/a.mp3", "http://example.com/a.mp3"),
    ],
)
def test_normalize_keeps_real_urls(raw, expected):
    assert media_url.normalize_media_url(raw) == expected


def test_normalize_adds_scheme_to_bare_host():
    assert media_url.normalize_media_url("www.youtube.com/watch?v=abc") == (
        "https://www.youtube.com/watch?v=abc"
    )


def test_normalize_handles_protocol_relative_url():
    assert media_url.normalize_media_url("//example.com/a.mp3") == "https://example.com/a.mp3"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "how to bake bread",            # a search phrase, not a link
        "C:\\videos\\clip.mp4",         # a local path
        "mailto:someone@example.com",   # not fetchable media
        "magnet:?xt=urn:btih:abc",
        "ftp://example.com/a.mp3",      # scheme we do not fetch
        "notahost/watch",               # no dot => not a hostname
    ],
)
def test_normalize_rejects_non_urls(raw):
    assert media_url.normalize_media_url(raw) == ""
    assert media_url.is_media_url(raw) is False


def test_looks_like_direct_media_file():
    assert media_url.looks_like_direct_media_file(DIRECT_MP3) is True
    assert media_url.looks_like_direct_media_file("https://example.com/live/index.m3u8") is True
    assert media_url.looks_like_direct_media_file(YT_WATCH) is False


def test_title_from_url_uses_the_filename():
    assert media_url.title_from_url(DIRECT_MP3) == "episode-42"
    assert media_url.title_from_url("https://example.com/shows/my_great_show.mp3") == "my great show"


def test_title_from_url_never_returns_empty():
    # A URL with no usable path still has to name a file on disk.
    assert media_url.title_from_url("https://media.example.com/") == "media.example.com"
    assert media_url.title_from_url("not a url") == "media"


# --- gui.mainframe routing -------------------------------------------------


class _FakeConfig:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _FakePlayer:
    def __init__(self):
        self.loaded = []

    def load_media(self, url, use_ytdlp=False, chapters=None, title=None, article_id=None):
        self.loaded.append(
            {"url": url, "use_ytdlp": use_ytdlp, "title": title, "article_id": article_id}
        )


class _Host:
    """The Open Media URL surface of MainFrame, without wx."""

    MEDIA_URL_DOWNLOAD_FOLDER = mainframe.MainFrame.MEDIA_URL_DOWNLOAD_FOLDER
    stream_media_url = mainframe.MainFrame.stream_media_url
    download_media_url = mainframe.MainFrame.download_media_url
    _media_url_article = mainframe.MainFrame._media_url_article
    _download_media_url_thread = mainframe.MainFrame._download_media_url_thread
    _download_dir_for_article = mainframe.MainFrame._download_dir_for_article
    _safe_name = mainframe.MainFrame._safe_name

    def __init__(self, **config):
        self.config_manager = _FakeConfig(**config)
        self.player = _FakePlayer()
        self.statuses = []
        self.shown = []
        self.ytdlp_downloads = []
        self.direct_downloads = []

    def _ensure_player_window(self):
        return self.player

    def _post_activity_status(self, text):
        self.statuses.append(text)

    def toggle_player_visibility(self, force_show=None):
        self.shown.append(force_show)

    def _get_feed_title(self, feed_id):
        return None

    def _download_article_via_ytdlp(self, article, url, download_format=None):
        self.ytdlp_downloads.append((article, url, download_format))

    def _download_article_thread(self, article, download_format=None):
        self.direct_downloads.append((article, download_format))


class _FakeWx:
    ICON_ERROR = 1
    ICON_INFORMATION = 2

    def __init__(self):
        self.messages = []

    def MessageBox(self, message, caption="", style=0):
        self.messages.append((message, caption, style))


@pytest.fixture
def fake_wx(monkeypatch):
    fake = _FakeWx()
    monkeypatch.setattr(mainframe, "wx", fake)
    return fake


def test_stream_youtube_url_uses_ytdlp_and_shows_the_player(fake_wx):
    host = _Host(show_player_on_play=True)

    host.stream_media_url(YT_WATCH)

    assert host.player.loaded == [
        {"url": YT_WATCH, "use_ytdlp": True, "title": None, "article_id": None}
    ]
    # No title is forced on a yt-dlp page: extraction resolves the real one.
    assert host.shown == [True]


def test_stream_direct_file_skips_ytdlp_and_names_it(fake_wx):
    host = _Host(show_player_on_play=False)

    host.stream_media_url(DIRECT_MP3)

    loaded = host.player.loaded[0]
    assert loaded["use_ytdlp"] is False
    assert loaded["title"] == "episode-42"
    assert host.shown == [False]


def test_stream_normalizes_before_playing(fake_wx):
    host = _Host()
    host.stream_media_url("  <" + DIRECT_MP3 + ">  ")
    assert host.player.loaded[0]["url"] == DIRECT_MP3


def test_stream_rejects_a_non_url_without_touching_the_player(fake_wx):
    host = _Host()
    host.stream_media_url("how to bake bread")
    assert host.player.loaded == []


def test_stream_says_so_when_the_player_cannot_open(fake_wx):
    host = _Host()
    host._ensure_player_window = lambda: None

    host.stream_media_url(YT_WATCH)

    # Silent early-return would read as "the app is broken" to a screen reader.
    assert len(fake_wx.messages) == 1
    assert "cannot be streamed" in fake_wx.messages[0][0]


def test_download_refuses_and_explains_when_downloads_are_disabled(fake_wx):
    host = _Host(downloads_enabled=False)

    host.download_media_url(YT_WATCH, "audio_mp3_192")

    assert host.ytdlp_downloads == []
    assert len(fake_wx.messages) == 1
    assert "Downloads are disabled" in fake_wx.messages[0][0]


def test_download_thread_routes_a_youtube_url_through_ytdlp(monkeypatch, fake_wx):
    monkeypatch.setattr(
        mainframe.core.discovery, "resolve_ytdlp_url_title", lambda url, timeout=10: "Real Title"
    )
    host = _Host(downloads_enabled=True)

    host._download_media_url_thread(YT_WATCH, "audio_mp3_320")

    assert host.direct_downloads == []
    article, url, fmt = host.ytdlp_downloads[0]
    assert (url, fmt) == (YT_WATCH, "audio_mp3_320")
    assert article.title == "Real Title"


def test_download_thread_falls_back_to_a_url_title(monkeypatch, fake_wx):
    def _boom(url, timeout=10):
        raise RuntimeError("network down")

    monkeypatch.setattr(mainframe.core.discovery, "resolve_ytdlp_url_title", _boom)
    host = _Host(downloads_enabled=True)

    host._download_media_url_thread(YT_WATCH, None)

    article = host.ytdlp_downloads[0][0]
    # Never empty: an empty title would write "None.mp4".
    assert article.title


def test_download_thread_saves_a_direct_file_as_is(fake_wx):
    host = _Host(downloads_enabled=True)

    host._download_media_url_thread(DIRECT_MP3, "video_720")

    assert host.ytdlp_downloads == []
    article, fmt = host.direct_downloads[0]
    assert article.media_url == DIRECT_MP3
    assert article.title == "episode-42"


def test_media_url_article_has_no_article_identity(fake_wx):
    host = _Host()
    article = host._media_url_article(YT_WATCH, "Some Video")

    # No id/feed_id => the download index keys it by media URL alone, so the
    # saved file is still found if this video later arrives in a feed.
    assert article.id == ""
    assert article.feed_id == ""
    assert article.url == article.media_url == YT_WATCH
    assert article.download_folder == _Host.MEDIA_URL_DOWNLOAD_FOLDER


def test_pasted_link_downloads_into_its_own_folder(tmp_path, fake_wx):
    host = _Host(download_path=str(tmp_path))
    article = host._media_url_article(YT_WATCH, "Some Video")

    target = host._download_dir_for_article(article)

    assert target == os.path.join(str(tmp_path), _Host.MEDIA_URL_DOWNLOAD_FOLDER)
    assert os.path.isdir(target)


def test_feed_items_still_use_the_feed_folder(tmp_path, fake_wx):
    host = _Host(download_path=str(tmp_path))
    host._get_feed_title = lambda feed_id: "My Podcast"
    article = SimpleNamespace(feed_id="f1", title="Episode")

    target = host._download_dir_for_article(article)

    assert target == os.path.join(str(tmp_path), "My Podcast")
