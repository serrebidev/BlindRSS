# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""self.duration must not be shrunk by a bogus libVLC length.

libVLC's get_length() on a remote googlevideo stream can settle on a value far
shorter than the real track. Because that was the only source of self.duration,
seek_relative_ms clamped forward seeks to the bogus "end" — and refused them
silently, so the key just looked dead.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")

from gui.player import PlayerFrame


def _frame():
    frame = PlayerFrame.__new__(PlayerFrame)
    frame.duration = 0
    frame._known_duration_ms = 0
    frame._set_total_time_label = lambda value: None
    frame._format_time = lambda ms: str(ms)
    return frame


def test_known_duration_from_ytdlp_is_adopted():
    frame = _frame()
    frame._set_known_duration_ms(754)  # seconds, as yt-dlp reports it
    assert frame._known_duration_ms == 754000
    assert frame.duration == 754000


@pytest.mark.parametrize("bad", [None, "", "abc", 0, -5])
def test_missing_or_absurd_ytdlp_duration_is_ignored(bad):
    frame = _frame()
    frame._set_known_duration_ms(bad)
    assert frame._known_duration_ms == 0
    assert frame.duration == 0


def test_short_vlc_length_is_rejected_when_ytdlp_duration_is_known():
    """The actual bug: a 3:30 length on a 12:34 track killed forward seeking."""
    frame = _frame()
    frame._set_known_duration_ms(754)
    assert not frame._duration_is_plausible(210_000)


def test_longer_vlc_length_is_accepted():
    # Live/growing streams legitimately exceed the announced duration.
    frame = _frame()
    frame._set_known_duration_ms(754)
    assert frame._duration_is_plausible(900_000)


def test_rounding_differences_are_tolerated():
    frame = _frame()
    frame._set_known_duration_ms(754)
    assert frame._duration_is_plausible(753_500)
    assert frame._duration_is_plausible(754_000)


def test_any_length_is_accepted_without_a_known_duration():
    frame = _frame()
    assert frame._duration_is_plausible(210_000)
    assert frame._duration_is_plausible(1)


def test_known_duration_does_not_leak_into_the_next_track():
    """A long YouTube item must not veto a short local file's real length."""
    frame = _frame()
    frame._set_known_duration_ms(754)
    assert not frame._duration_is_plausible(210_000)

    # load_media clears the hint before resolving the next item.
    frame._known_duration_ms = 0
    assert frame._duration_is_plausible(210_000)
