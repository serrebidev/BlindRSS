# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""GUI-free tests for the media filter and the play-queue play/pause helpers.

Binds the real MainFrame methods onto lightweight hosts (same pattern as
test_mainframe_shortcut_registry.py) so the logic is covered without a wx.App.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


# --------------------------------------------------------------------------
# Media filter
# --------------------------------------------------------------------------

class _Art:
    def __init__(self, has_media):
        self.has_media = has_media


class _MediaHost:
    _apply_media_filter = mainframe.MainFrame._apply_media_filter

    def __init__(self, mode):
        self._article_media_filter = mode

    def _should_play_in_player(self, article, include_downloads=True):
        return bool(getattr(article, "has_media", False))


def test_media_filter_modes():
    arts = [_Art(True), _Art(False), _Art(True)]
    assert len(_MediaHost("all")._apply_media_filter(arts)) == 3
    with_only = _MediaHost("with")._apply_media_filter(arts)
    assert len(with_only) == 2 and all(a.has_media for a in with_only)
    without_only = _MediaHost("without")._apply_media_filter(arts)
    assert len(without_only) == 1 and not without_only[0].has_media


def test_media_filter_all_is_identity_and_cheap():
    # "all" must not even call the predicate (it returns immediately).
    class _Boom(_MediaHost):
        def _should_play_in_player(self, article, include_downloads=True):
            raise AssertionError("predicate should not run when filter is 'all'")

    arts = [_Art(True), _Art(False)]
    assert _Boom("all")._apply_media_filter(arts) == arts


# --------------------------------------------------------------------------
# Play-queue play/pause helpers
# --------------------------------------------------------------------------

class _PW:
    def __init__(self, current_id=None, playing=False, loaded=True):
        self._cur = current_id
        self._playing = playing
        self._loaded = loaded

    def has_media_loaded(self):
        return self._loaded

    def is_current_media(self, article_id, media_url):
        return self._cur is not None and str(article_id) == str(self._cur)

    def is_audio_playing(self):
        return self._playing


class _QHost:
    queue_entry_is_current = mainframe.MainFrame.queue_entry_is_current
    queue_entry_is_playing = mainframe.MainFrame.queue_entry_is_playing
    toggle_queue_entry_play_pause = mainframe.MainFrame.toggle_queue_entry_play_pause

    def __init__(self, queue, pw):
        self._queue = queue
        self.player_window = pw
        self.toggled = 0
        self.played = []

    def _get_play_queue(self):
        return list(self._queue)

    def on_player_play_pause(self, event):
        self.toggled += 1

    def play_queue_index(self, index):
        self.played.append(int(index))
        return True


_QUEUE = [
    {"article_id": "a", "media_url": "u1", "title": "One"},
    {"article_id": "b", "media_url": "u2", "title": "Two"},
]


def test_toggle_pauses_the_currently_playing_item():
    host = _QHost(_QUEUE, _PW(current_id="a", playing=True))
    assert host.queue_entry_is_current(0) is True
    assert host.queue_entry_is_playing(0) is True
    host.toggle_queue_entry_play_pause(0)
    assert host.toggled == 1        # paused via play/pause toggle
    assert host.played == []        # did NOT restart the item


def test_toggle_plays_a_non_current_item():
    host = _QHost(_QUEUE, _PW(current_id="a", playing=True))
    # Index 1 is a different item -> should start it, not toggle pause.
    assert host.queue_entry_is_current(1) is False
    host.toggle_queue_entry_play_pause(1)
    assert host.played == [1]
    assert host.toggled == 0


def test_current_but_paused_is_not_playing():
    host = _QHost(_QUEUE, _PW(current_id="a", playing=False))
    assert host.queue_entry_is_current(0) is True
    assert host.queue_entry_is_playing(0) is False
    # Toggling the current-but-paused item resumes via play/pause.
    host.toggle_queue_entry_play_pause(0)
    assert host.toggled == 1 and host.played == []


def test_no_player_means_not_current():
    host = _QHost(_QUEUE, None)
    assert host.queue_entry_is_current(0) is False
    assert host.queue_entry_is_playing(0) is False


# --------------------------------------------------------------------------
# Queue entry source (feed) resolution
# --------------------------------------------------------------------------

class _Feed:
    def __init__(self, title):
        self.title = title


class _SourceHost:
    queue_entry_source = mainframe.MainFrame.queue_entry_source

    def __init__(self, feed_map):
        self.feed_map = feed_map


def test_queue_entry_source_prefers_stored_feed_title():
    h = _SourceHost({})
    assert h.queue_entry_source({"feed_title": "The Daily"}) == "The Daily"


def test_queue_entry_source_resolves_from_feed_id():
    h = _SourceHost({"f1": _Feed("Radiolab")})
    # Falls back to feed_id lookup when no stored title (older queue entries).
    assert h.queue_entry_source({"feed_id": "f1"}) == "Radiolab"
    assert h.queue_entry_source({"feed_id": "missing"}) == ""
    assert h.queue_entry_source({}) == ""
    assert h.queue_entry_source("not-a-dict") == ""
