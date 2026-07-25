# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""A URL that resolves to a web page must fail loudly, not stall in silence.

Field log (v1.124.0): playing an item whose media URL was a Miniflux entry page
redirected to the login form and returned ``text/html``. VLC sat in ``Opening``,
the stall watchdog fired at 8.1s, retried, fired again at 14.1s, fell back to the
same HTML, and the user was told nothing at all.
"""

import os
import sys
import types

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gui.player import PlayerFrame


def _probe_host():
    """A bare object carrying just the attributes the probe helpers touch."""
    host = types.SimpleNamespace()
    host._non_media_probe = None
    host._active_load_seq = 7
    host._last_orig_url = "https://rss.example.test/unread/entry/354307"
    host.current_url = host._last_orig_url
    host._NON_MEDIA_CONTENT_TYPES = PlayerFrame._NON_MEDIA_CONTENT_TYPES
    host._note_seek_probe_content = types.MethodType(
        PlayerFrame._note_seek_probe_content, host
    )
    host._pending_non_media_reason = types.MethodType(
        PlayerFrame._pending_non_media_reason, host
    )
    return host


def test_html_content_type_is_recorded_as_non_media():
    host = _probe_host()

    host._note_seek_probe_content(
        host._last_orig_url, "text/html; charset=utf-8", "1985", False
    )

    assert host._non_media_probe is not None
    assert host._non_media_probe["content_type"] == "text/html"
    assert host._non_media_probe["load_seq"] == 7

    reason = host._pending_non_media_reason()
    assert reason
    assert "text/html" in reason
    assert "web page" in reason.lower()


def test_audio_content_type_is_not_flagged():
    host = _probe_host()

    host._note_seek_probe_content(host._last_orig_url, "audio/mpeg", "9000000", False)

    assert host._non_media_probe is None
    assert host._pending_non_media_reason() == ""


def test_hls_playlist_is_not_flagged_even_though_it_is_text():
    host = _probe_host()

    host._note_seek_probe_content(
        host._last_orig_url, "application/vnd.apple.mpegurl", "412", True
    )

    assert host._non_media_probe is None
    assert host._pending_non_media_reason() == ""


def test_stale_probe_from_a_previous_load_is_ignored():
    """The user moved on; the old probe must not abort the new item."""
    host = _probe_host()
    host._note_seek_probe_content(
        host._last_orig_url, "text/html; charset=utf-8", "1985", False
    )
    assert host._pending_non_media_reason()

    host._active_load_seq = 8

    assert host._pending_non_media_reason() == ""


def test_probe_for_a_url_we_are_no_longer_loading_is_dropped():
    host = _probe_host()

    host._note_seek_probe_content(
        "https://elsewhere.example.test/other", "text/html", "120", False
    )

    assert host._non_media_probe is None
