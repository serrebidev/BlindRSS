# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""GUI-free tests for what Stop Refresh does beyond cancelling the batch.

Cancelling the in-flight batch is not enough for the user-visible promise: the
periodic loop restarts within one refresh interval (30 seconds for some users),
a manual refresh queued behind the refresh guard takes over the moment the
stopped one releases it, and per-feed progress already on the wire keeps walking
the status bar forward after "Refresh stopped".

The real methods are bound onto a lightweight host (same pattern as
test_mainframe_shortcut_registry.py) so no wx.App is needed.
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _FakeConfig:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class _FakeProvider:
    """Provider whose refresh blocks until released, like a real slow batch."""

    def __init__(self):
        self.refresh_calls = 0
        self.cancelled = threading.Event()
        self.release = threading.Event()
        self.entered = threading.Event()
        self.has_scope = True

    def refresh(self, progress_cb=None, force=False, scheduled=False):
        self.refresh_calls += 1
        self.entered.set()
        self.release.wait(5.0)
        return True

    def cancel_refresh(self):
        if not self.has_scope:
            return False
        self.cancelled.set()
        return True

    def scheduled_refresh_tick(self, global_interval_s):
        return int(global_interval_s)

    def get_feeds(self):
        return []


class _Host:
    on_stop_refresh = mainframe.MainFrame.on_stop_refresh
    _cmd_stop_refresh = mainframe.MainFrame._cmd_stop_refresh
    _auto_refresh_pause_seconds = mainframe.MainFrame._auto_refresh_pause_seconds
    _auto_refresh_pause_remaining = mainframe.MainFrame._auto_refresh_pause_remaining
    _auto_refresh_pause_note = mainframe.MainFrame._auto_refresh_pause_note
    _resume_auto_refresh = mainframe.MainFrame._resume_auto_refresh
    _refresh_stopped_status = mainframe.MainFrame._refresh_stopped_status
    _mute_refresh_progress = mainframe.MainFrame._mute_refresh_progress
    _is_feed_refresh_active = mainframe.MainFrame._is_feed_refresh_active
    _scheduled_refresh_tick_seconds = mainframe.MainFrame._scheduled_refresh_tick_seconds
    _begin_refresh_activity = mainframe.MainFrame._begin_refresh_activity
    _end_refresh_activity = mainframe.MainFrame._end_refresh_activity
    _reset_refresh_progress_counter = mainframe.MainFrame._reset_refresh_progress_counter
    _note_refresh_progress_feed = mainframe.MainFrame._note_refresh_progress_feed
    _refresh_progress_counts = mainframe.MainFrame._refresh_progress_counts
    _on_feed_refresh_progress = mainframe.MainFrame._on_feed_refresh_progress
    _run_refresh = mainframe.MainFrame._run_refresh

    def __init__(self, config=None):
        self.config_manager = _FakeConfig(
            {"refresh_interval": 30, "refresh_stop_pause_seconds": 300, **(config or {})}
        )
        self.provider = _FakeProvider()
        self._refresh_guard = threading.Lock()
        self._refresh_stop_requested = False
        self._refresh_stop_epoch = 0
        self._auto_refresh_paused_until = 0.0
        self._refresh_progress_muted = False
        self._refresh_progress_lock = threading.Lock()
        self._refresh_progress_pending = {}
        self._refresh_progress_flush_scheduled = False
        self._refresh_progress_total = 0
        self._refresh_progress_seen = set()
        self._refresh_ui_batch_active = False
        self._refresh_ui_batch_dirty = False
        self._refresh_ui_batch_token = 0
        self._last_retention_cleanup_monotonic = 0.0
        self.feed_map = {}
        self.statuses = []
        self.announcements = []

    # --- stubs for the parts of a refresh run this file does not exercise ---
    def _post_activity_status(self, text):
        self.statuses.append(text)

    def _announce_event(self, event_id, message):
        self.announcements.append((event_id, message))

    def _expected_refresh_feed_count(self):
        return 3

    def _perform_retention_cleanup(self):
        pass

    def _capture_unread_snapshot(self):
        return {}

    def _extract_new_items(self, state, snapshot, seen_ids):
        return 0

    def _queue_new_article_notifications_from_state(self, *args, **kwargs):
        return None

    def _begin_refresh_ui_batch(self):
        self._refresh_ui_batch_token += 1
        self._refresh_ui_batch_active = True
        self._refresh_ui_batch_dirty = False
        return self._refresh_ui_batch_token

    def _finish_refresh_ui_batch(self, refresh_tree, batch_token=None):
        self._refresh_ui_batch_active = False

    def _play_sound(self, key):
        pass


@pytest.fixture(autouse=True)
def _no_wx_callafter(monkeypatch):
    """wx.CallAfter needs a running app; record the call instead."""
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda *a, **k: None)


def _run_in_thread(fn):
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    return t


def test_stop_pauses_the_periodic_refresh_loop():
    host = _Host()
    host.on_stop_refresh()

    assert host._auto_refresh_pause_remaining() > 0
    # The tick the loop would have fired seconds later must not run.
    assert host._run_refresh(block=False, scheduled=True) is False
    assert host.provider.refresh_calls == 0


def test_a_user_requested_refresh_lifts_the_pause():
    host = _Host()
    host.on_stop_refresh()
    host.provider.release.set()

    assert host._run_refresh(block=True, force=True, scheduled=False) is True
    assert host.provider.refresh_calls == 1
    # ...and the periodic loop is free again.
    assert host._auto_refresh_pause_remaining() == 0
    assert host._run_refresh(block=False, scheduled=True) is True


def test_stop_abandons_a_refresh_queued_behind_the_guard():
    host = _Host()
    host.config_manager.set("refresh_stop_pause_seconds", 0)
    first_done = threading.Event()

    def _first():
        try:
            host._run_refresh(block=True, force=True)
        finally:
            first_done.set()

    queued_result = {}

    def _queued():
        queued_result["ran"] = host._run_refresh(block=True, force=True)

    first = _run_in_thread(_first)
    assert host.provider.entered.wait(5.0)
    queued = _run_in_thread(_queued)
    time.sleep(0.05)  # let the second run block on the guard

    host.on_stop_refresh()
    host.provider.release.set()
    first.join(timeout=5.0)
    queued.join(timeout=5.0)

    assert first_done.is_set()
    assert queued_result.get("ran") is False
    # Only the stopped run reached the provider; the queued one did not take over.
    assert host.provider.refresh_calls == 1


def test_stop_drops_progress_still_arriving_from_the_stopped_batch():
    host = _Host()
    host._begin_refresh_activity(total=51)
    host._refresh_ui_batch_active = True
    for i in range(44):
        host._on_feed_refresh_progress({"id": str(i), "title": "t"})
    assert host._refresh_progress_counts() == (44, 51)

    host.on_stop_refresh()

    # Feeds already on the wire land after the stop: they must not walk the
    # "Checked 44 out of 51" status forward.
    for i in range(44, 51):
        host._on_feed_refresh_progress({"id": str(i), "title": "t"})
    assert host._refresh_progress_counts() == (44, 51)
    assert host._refresh_progress_pending == {}
    # The one final tree reload still runs, so the counts that did arrive are
    # not left half-applied.
    assert host._refresh_ui_batch_dirty is True


def test_stop_says_so_when_nothing_is_refreshing():
    host = _Host()
    host.provider.has_scope = False

    host._cmd_stop_refresh()

    assert host.statuses, "Stop Refresh answered with silence"
    assert "No refresh in progress" in host.statuses[-1]
    assert host.announcements[-1][0] == "stop_update"


def test_stopped_status_mentions_the_pause_only_when_it_delays_a_tick():
    host = _Host({"refresh_interval": 30, "refresh_stop_pause_seconds": 300})
    host.on_stop_refresh()
    assert "paused" in host._refresh_stopped_status("Refresh stopped").lower()

    # A pause shorter than the interval delays no tick the user would have seen.
    far = _Host({"refresh_interval": 14400, "refresh_stop_pause_seconds": 300})
    far.on_stop_refresh()
    assert far._refresh_stopped_status("Refresh stopped") == "Refresh stopped"

    # Neither does one with automatic refresh turned off entirely.
    never = _Host({"refresh_interval": 0, "refresh_stop_pause_seconds": 300})
    never.on_stop_refresh()
    assert never._refresh_stopped_status("Refresh stopped") == "Refresh stopped"


def test_end_of_a_stopped_batch_reports_stopped_not_complete():
    host = _Host()
    host._refresh_stop_requested = True
    host._auto_refresh_paused_until = time.monotonic() + 300

    host._end_refresh_activity()

    assert host.statuses[-1].startswith("Refresh stopped")
    assert host._refresh_stop_requested is False
    # A later, normal batch is unaffected.
    host._end_refresh_activity()
    assert host.statuses[-1] == "Refresh complete"
