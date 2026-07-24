# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import threading
import time
from queue import Queue
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui.dialogs as dialogs


class _ExplodingCtrl:
    def Enable(self):
        raise AssertionError("UI control should not be touched after close")

    def SetLabel(self, _label):
        raise AssertionError("UI control should not be touched after close")

    def SetFocus(self):
        raise AssertionError("UI control should not be touched after close")

    def InsertItem(self, *_args, **_kwargs):
        raise AssertionError("UI control should not be touched after close")

    def SetItem(self, *_args, **_kwargs):
        raise AssertionError("UI control should not be touched after close")


class _DeletedCtrl:
    def Enable(self):
        raise RuntimeError("wrapped C/C++ object of type SearchCtrl has been deleted")

    def SetLabel(self, _label):
        raise RuntimeError("wrapped C/C++ object deleted")

    def SetFocus(self):
        raise RuntimeError("wrapped C/C++ object deleted")

    def InsertItem(self, *_args, **_kwargs):
        raise RuntimeError("wrapped C/C++ object deleted")

    def SetItem(self, *_args, **_kwargs):
        raise RuntimeError("wrapped C/C++ object deleted")


class _Host:
    _on_search_complete = dialogs.FeedSearchDialog._on_search_complete

    def __init__(self):
        self._stop_event = threading.Event()
        self.search_ctrl = _ExplodingCtrl()
        self.search_btn = _ExplodingCtrl()
        self.status_lbl = _ExplodingCtrl()
        self.results_list = _ExplodingCtrl()
        self.results_data = []

class _YoutubeSearchHost:
    _search_youtube_channels = dialogs.FeedSearchDialog._search_youtube_channels

class _UnifiedSearchHost:
    _SOURCE_ALL = dialogs.FeedSearchDialog._SOURCE_ALL
    _unified_search_manager = dialogs.FeedSearchDialog._unified_search_manager

    def __init__(self, slow_sleep: float = 0.4):
        self._stop_event = threading.Event()
        self.completed_results = None
        self._SEARCH_POLL_INTERVAL_S = 0.02
        self._SEARCH_TOTAL_TIMEOUT_ALL_SOURCES_S = 0.25
        self._SEARCH_TOTAL_TIMEOUT_SINGLE_SOURCE_S = 0.25
        self._slow_sleep = slow_sleep

    def _build_search_targets(self, _term, _source_key):
        return [
            ("YouTube", self._fast_provider),
            ("SlowProvider", self._slow_provider),
        ]

    def _fast_provider(self, _term, q):
        q.put(("YouTube", [{"title": "Fast hit", "detail": "from youtube", "url": "https://example.com/yt"}]))

    def _slow_provider(self, _term, q):
        time.sleep(self._slow_sleep)
        q.put(("SlowProvider", [{"title": "Slow hit", "detail": "from slow", "url": "https://example.com/slow"}]))

    def _on_search_complete(self, results):
        self.completed_results = list(results or [])


class _UnifiedSearchOrderHost:
    _SOURCE_ALL = dialogs.FeedSearchDialog._SOURCE_ALL
    _unified_search_manager = dialogs.FeedSearchDialog._unified_search_manager

    def __init__(self):
        self._stop_event = threading.Event()
        self.completed_results = None
        self._SEARCH_POLL_INTERVAL_S = 0.02
        self._SEARCH_TOTAL_TIMEOUT_ALL_SOURCES_S = 0.2
        self._SEARCH_TOTAL_TIMEOUT_SINGLE_SOURCE_S = 0.2

    def _build_search_targets(self, _term, _source_key):
        # Intentionally put non-YouTube provider first to verify final ordering.
        return [
            ("SlowProvider", self._slow_provider),
            ("YouTube", self._youtube_provider),
        ]

    def _slow_provider(self, _term, q):
        q.put(("SlowProvider", [{"title": "slow", "detail": "", "url": "https://example.com/slow"}]))

    def _youtube_provider(self, _term, q):
        time.sleep(0.01)
        q.put(("YouTube", [{"title": "yt", "detail": "", "url": "https://example.com/yt"}]))

    def _on_search_complete(self, results):
        self.completed_results = list(results or [])


def test_feed_search_on_search_complete_returns_when_dialog_closed():
    host = _Host()
    host._stop_event.set()

    host._on_search_complete([{"title": "x", "provider": "YouTube", "detail": "", "url": "u"}])

    assert host.results_data == []


def test_feed_search_on_search_complete_swallows_deleted_widget_error():
    host = _Host()
    host.search_ctrl = _DeletedCtrl()
    host.search_btn = _DeletedCtrl()
    host.status_lbl = _DeletedCtrl()
    host.results_list = _DeletedCtrl()

    host._on_search_complete([{"title": "x", "provider": "YouTube", "detail": "", "url": "u"}])

    # No exception is the regression check.
    assert host.results_data == []


def test_feed_search_youtube_requests_100_results():
    host = _YoutubeSearchHost()
    q = Queue()
    expected = [{"title": "x", "detail": "YouTube playlist", "url": "https://example.com/feed"}]

    with patch("gui.dialogs.search_youtube_feeds", return_value=expected) as mock_search:
        host._search_youtube_channels("rimworld", q)

    mock_search.assert_called_once_with("rimworld", limit=100, timeout=15)
    provider, results = q.get_nowait()
    assert provider == "YouTube"
    assert results == expected


def test_feed_search_global_timeout_matches_single_source_timeout():
    assert dialogs.FeedSearchDialog._SEARCH_TOTAL_TIMEOUT_ALL_SOURCES_S == (
        dialogs.FeedSearchDialog._SEARCH_TOTAL_TIMEOUT_SINGLE_SOURCE_S
    )


def test_unified_search_manager_returns_fast_results_without_waiting_per_thread_timeout():
    host = _UnifiedSearchHost(slow_sleep=0.8)

    with patch("gui.dialogs.wx.CallAfter", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
        started = time.monotonic()
        host._unified_search_manager("term", host._SOURCE_ALL)
        elapsed = time.monotonic() - started

    assert elapsed < 0.6
    assert host.completed_results is not None
    assert any(item.get("provider") == "YouTube" for item in host.completed_results)


def test_unified_search_manager_collects_slow_results_when_they_finish_before_deadline():
    host = _UnifiedSearchHost(slow_sleep=0.05)

    with patch("gui.dialogs.wx.CallAfter", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
        host._unified_search_manager("term", host._SOURCE_ALL)

    assert host.completed_results is not None
    providers = {item.get("provider") for item in host.completed_results}
    assert "YouTube" in providers
    assert "SlowProvider" in providers


def test_unified_search_manager_puts_youtube_results_first_in_all_sources():
    host = _UnifiedSearchOrderHost()

    with patch("gui.dialogs.wx.CallAfter", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
        host._unified_search_manager("term", host._SOURCE_ALL)

    assert host.completed_results is not None
    assert len(host.completed_results) == 2
    assert host.completed_results[0].get("provider") == "YouTube"
