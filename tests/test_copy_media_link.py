# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _FakeTextDataObject:
    def __init__(self, text=""):
        self.text = text

    def GetText(self):
        return self.text


class _FakeClipboard:
    def __init__(self):
        self.opened = 0
        self.closed = 0
        self.flushed = 0
        self.set_texts = []

    def Open(self):
        self.opened += 1
        return True

    def Close(self):
        self.closed += 1

    def SetData(self, data):
        self.set_texts.append(data.GetText())
        return True

    def Flush(self):
        self.flushed += 1
        return True


def _fake_wx(fake_clipboard):
    return SimpleNamespace(
        TheClipboard=fake_clipboard,
        TextDataObject=_FakeTextDataObject,
    )


class _Host:
    on_copy_media_link = mainframe.MainFrame.on_copy_media_link
    _has_direct_media_link = mainframe.MainFrame._has_direct_media_link
    _ytdlp_download_target = mainframe.MainFrame._ytdlp_download_target

    def __init__(self, articles):
        self.current_articles = articles


def _article(media_url):
    return SimpleNamespace(url="https://example.com/episode-1", media_url=media_url)


YT_WATCH = "https://www.youtube.com/watch?v=s-59p7kUAaE"


def _yt_article():
    # Mirrors how providers/local.py stores YouTube items: media_url == url.
    return SimpleNamespace(url=YT_WATCH, media_url=YT_WATCH, media_type="video/youtube")


def test_copy_media_link_copies_direct_audio_url(monkeypatch):
    fake_clipboard = _FakeClipboard()
    monkeypatch.setattr(mainframe, "wx", _fake_wx(fake_clipboard))
    host = _Host([_article("https://media.example.com/episode-1.mp3")])

    host.on_copy_media_link(0)

    assert fake_clipboard.set_texts == ["https://media.example.com/episode-1.mp3"]
    assert fake_clipboard.flushed == 1
    assert fake_clipboard.closed == 1


def test_copy_media_link_noop_without_media_url(monkeypatch):
    fake_clipboard = _FakeClipboard()
    monkeypatch.setattr(mainframe, "wx", _fake_wx(fake_clipboard))
    host = _Host([_article("")])

    host.on_copy_media_link(0)

    assert fake_clipboard.set_texts == []
    assert fake_clipboard.opened == 0


def test_copy_media_link_ignores_out_of_range_index(monkeypatch):
    fake_clipboard = _FakeClipboard()
    monkeypatch.setattr(mainframe, "wx", _fake_wx(fake_clipboard))
    host = _Host([_article("https://media.example.com/episode-1.mp3")])

    host.on_copy_media_link(5)

    assert fake_clipboard.set_texts == []
    assert fake_clipboard.opened == 0


def test_direct_media_link_true_for_real_file():
    host = _Host([])
    article = _article("https://media.example.com/episode-1.mp3")
    assert host._has_direct_media_link(article) is True


def test_direct_media_link_false_for_youtube_item():
    # YouTube items store the watch-page URL as media_url; there is no single
    # combined audio+video direct link, so "Copy Media Link" must be unavailable.
    host = _Host([])
    assert host._has_direct_media_link(_yt_article()) is False


def test_direct_media_link_false_when_media_url_is_ytdlp_page():
    # Even if media_url differs from the article link, a yt-dlp page URL is not a
    # direct, copyable media file.
    host = _Host([])
    article = SimpleNamespace(url="https://example.com/article", media_url=YT_WATCH)
    assert host._has_direct_media_link(article) is False


def test_direct_media_link_false_without_media_url():
    host = _Host([])
    assert host._has_direct_media_link(_article("")) is False


def test_ytdlp_download_target_for_youtube_item():
    host = _Host([])
    assert host._ytdlp_download_target(_yt_article()) == YT_WATCH


def test_ytdlp_download_target_none_for_direct_file():
    host = _Host([])
    article = _article("https://media.example.com/episode-1.mp3")
    assert host._ytdlp_download_target(article) is None
