# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import threading
import inspect


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe
from core import i18n, translation_updates as tu


class _Config:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)


class _StopAfterTick:
    def __init__(self, wait_results=None):
        self.wait_results = list(wait_results or [True])
        self.wait_intervals = []

    def is_set(self):
        return False

    def wait(self, interval):
        self.wait_intervals.append(interval)
        if self.wait_results:
            return self.wait_results.pop(0)
        return True


class _TickProvider:
    """Provider stub exposing only scheduled_refresh_tick."""

    def __init__(self, tick=None):
        self._tick = tick

    def scheduled_refresh_tick(self, global_interval_s):
        return self._tick if self._tick is not None else global_interval_s


class _RefreshLoopHost:
    refresh_loop = mainframe.MainFrame.refresh_loop
    _scheduled_refresh_tick_seconds = mainframe.MainFrame._scheduled_refresh_tick_seconds

    def __init__(self, *, refresh_on_startup=True, interval=30, wait_results=None, provider_tick=None):
        self.config_manager = _Config(
            {
                "refresh_on_startup": refresh_on_startup,
                "refresh_interval": interval,
            }
        )
        self.stop_event = _StopAfterTick(wait_results)
        self.refresh_calls = []
        self.provider = _TickProvider(provider_tick)

    def _run_refresh(self, block, force=False, scheduled=False):
        self.refresh_calls.append(
            {"block": bool(block), "force": bool(force), "scheduled": bool(scheduled)}
        )
        return True


def test_refresh_loop_runs_startup_refresh_without_force_when_enabled():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=30, wait_results=[True])

    host.refresh_loop()

    assert host.refresh_calls == [{"block": False, "force": False, "scheduled": False}]


def test_refresh_loop_periodic_refresh_is_not_forced_after_startup():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=30, wait_results=[False, True])

    host.refresh_loop()

    assert host.refresh_calls == [
        {"block": False, "force": False, "scheduled": False},
        {"block": False, "force": False, "scheduled": True},
    ]


def test_refresh_loop_runs_enabled_startup_refresh_when_periodic_refresh_is_never():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=0, wait_results=[True])

    host.refresh_loop()

    assert host.refresh_calls == [{"block": False, "force": False, "scheduled": False}]
    assert host.stop_event.wait_intervals == [5]


def test_refresh_loop_startup_disabled_waits_then_uses_normal_refresh():
    host = _RefreshLoopHost(refresh_on_startup=False, interval=30, wait_results=[False, True])

    host.refresh_loop()

    assert host.stop_event.wait_intervals[0] == 30
    # Startup refresh was skipped, so the first actual refresh is an ordinary
    # scheduled tick (per-feed intervals apply; a fresh provider has no
    # recorded attempts, so every feed is due anyway).
    assert host.refresh_calls == [{"block": False, "force": False, "scheduled": True}]


def test_refresh_loop_uses_provider_tick_for_sleep_interval():
    # A per-feed override shorter than the global interval shortens the loop tick.
    host = _RefreshLoopHost(
        refresh_on_startup=True, interval=300, wait_results=[False, True], provider_tick=60
    )

    host.refresh_loop()

    assert host.stop_event.wait_intervals == [60, 60]


def test_refresh_loop_falls_back_to_global_interval_without_provider_support():
    host = _RefreshLoopHost(refresh_on_startup=True, interval=45, wait_results=[True])
    host.provider = object()  # no scheduled_refresh_tick

    host.refresh_loop()

    assert host.stop_event.wait_intervals == [45]


class _StartupWorkHost:
    _start_startup_background_work = mainframe.MainFrame._start_startup_background_work

    def __init__(self):
        self._startup_background_work_started = False
        self.stop_event = threading.Event()
        self.refresh_thread = None
        self.config_manager = _Config({"refresh_on_startup": True, "refresh_interval": 30})
        self.provider = _TickProvider()
        self.tree_loads = 0

    def refresh_loop(self):
        return None

    def refresh_feeds(self):
        self.tree_loads += 1


def test_startup_background_work_starts_once_after_queued_first_turn(monkeypatch):
    started = []

    class _Thread:
        def __init__(self, *, target, daemon, name):
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append(self)

    monkeypatch.setattr(mainframe.threading, "Thread", _Thread)
    host = _StartupWorkHost()

    host._start_startup_background_work()
    host._start_startup_background_work()

    assert host._startup_background_work_started is True
    assert host.tree_loads == 1
    assert len(started) == 1
    assert started[0].daemon is True
    assert started[0].name == "BlindRSSRefreshLoop"


def test_mainframe_queues_startup_workers_for_first_event_loop_turn():
    source = inspect.getsource(mainframe.MainFrame.__init__)

    assert "wx.CallLater(1, self._start_startup_background_work)" in source
    assert "self.refresh_thread = None" in source


def test_startup_background_work_does_nothing_after_shutdown_begins(monkeypatch):
    monkeypatch.setattr(
        mainframe.threading,
        "Thread",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("refresh thread must not start")),
    )
    host = _StartupWorkHost()
    host.stop_event.set()

    host._start_startup_background_work()

    assert host._startup_background_work_started is False
    assert host.tree_loads == 0


class _TranslationUpdateHost:
    _maybe_auto_update_translations = mainframe.MainFrame._maybe_auto_update_translations

    def __init__(self, values=None):
        self.config_manager = _Config(values or {})
        self.stop_event = threading.Event()
        self._translation_update_inflight = False
        self._translation_update_timer = None


def test_translation_update_scheduler_rechecks_every_ten_minutes(monkeypatch):
    timers = []
    monkeypatch.setattr(
        mainframe.wx,
        "CallLater",
        lambda delay, callback, *args: timers.append((delay, callback, args)),
    )
    monkeypatch.setattr(tu, "is_due", lambda _frequency: False)
    host = _TranslationUpdateHost({tu.CFG_FREQUENCY: "daily"})

    host._maybe_auto_update_translations()

    assert len(timers) == 1
    assert timers[0][0] == 10 * 60 * 1000
    assert timers[0][1] == host._maybe_auto_update_translations


def test_translation_update_scheduler_runs_due_check_single_flight(monkeypatch):
    checked = []
    threads = []
    monkeypatch.setattr(mainframe.wx, "CallLater", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(tu, "is_due", lambda _frequency: True)
    monkeypatch.setattr(tu, "installed_languages", lambda: ["fr", "ru"])
    monkeypatch.setattr(i18n, "current_language", lambda: "ru")
    monkeypatch.setattr(
        tu,
        "check_and_update",
        lambda languages: checked.append(languages) or tu.UpdateResult(updated=["ru"]),
    )

    class _Thread:
        def __init__(self, *, target, daemon, name):
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            threads.append(self)
            self.target()

    monkeypatch.setattr(mainframe.threading, "Thread", _Thread)
    host = _TranslationUpdateHost({tu.CFG_FREQUENCY: "ten_minutes"})

    host._maybe_auto_update_translations()

    assert checked == [["ru", "fr"]]
    assert len(threads) == 1
    assert threads[0].name == "BlindRSSTranslationUpdate"
    assert host._translation_update_inflight is False


class _RefreshUiBatchHost:
    _begin_refresh_ui_batch = mainframe.MainFrame._begin_refresh_ui_batch
    _finish_refresh_ui_batch = mainframe.MainFrame._finish_refresh_ui_batch
    _maybe_finish_refresh_ui_batch = mainframe.MainFrame._maybe_finish_refresh_ui_batch
    _request_article_reload = mainframe.MainFrame._request_article_reload
    _schedule_article_reload = mainframe.MainFrame._schedule_article_reload
    _cancel_pending_article_reload = mainframe.MainFrame._cancel_pending_article_reload
    _run_pending_article_reload = mainframe.MainFrame._run_pending_article_reload
    _read_filter_mode_for_view = mainframe.MainFrame._read_filter_mode_for_view
    _has_stale_read_filter_rows = mainframe.MainFrame._has_stale_read_filter_rows

    def __init__(self):
        # No read-status filter here, so the end-of-refresh stale-row re-render
        # (issue #96) never triggers in these tests.
        self.current_feed_id = "all"
        self.current_articles = []
        self._refresh_progress_lock = threading.Lock()
        self._refresh_progress_pending = {}
        self._refresh_progress_flush_scheduled = False
        self._refresh_ui_batch_active = False
        self._refresh_ui_batch_ending = False
        self._refresh_ui_batch_refresh_tree = False
        self._refresh_ui_batch_end_activity = False
        self._refresh_ui_batch_token = 0
        self._article_refresh_dirty = False
        self._article_refresh_pending = False
        self._article_refresh_timer = None
        self._article_refresh_debounce_ms = 250
        self._article_refresh_batch_ms = 2500
        self.tree_loads = 0
        self.article_reloads = 0

    def refresh_feeds(self):
        self.tree_loads += 1

    def _reload_selected_articles(self):
        self.article_reloads += 1

    def _end_refresh_activity(self):
        return None


def test_full_refresh_throttles_selected_list_reload(monkeypatch):
    timers = []
    monkeypatch.setattr(
        mainframe.wx,
        "CallLater",
        lambda delay, callback, *args, **kwargs: timers.append((delay, callback, args, kwargs)),
    )
    host = _RefreshUiBatchHost()

    host._begin_refresh_ui_batch()
    host._request_article_reload()
    host._request_article_reload()

    # Mid-refresh progress schedules exactly ONE slow-throttled reload of the
    # visible list, so new articles appear while the batch is still running
    # without one loader per completed feed.
    assert host._article_refresh_dirty is True
    assert host._article_refresh_pending is True
    assert [t[0] for t in timers] == [2500]

    # The throttled timer fires while the batch is still active: the visible
    # list reloads immediately instead of waiting for the final tree update.
    timers[0][1]()
    assert host.article_reloads == 1
    assert host._article_refresh_dirty is False

    host._finish_refresh_ui_batch(refresh_tree=True)

    assert host.tree_loads == 1
    assert host._refresh_ui_batch_active is False


def test_reload_during_batch_ending_defers_to_final_update(monkeypatch):
    timers = []
    monkeypatch.setattr(
        mainframe.wx,
        "CallLater",
        lambda delay, callback, *args, **kwargs: timers.append((delay, callback)),
    )
    host = _RefreshUiBatchHost()

    host._begin_refresh_ui_batch()
    host._request_article_reload()
    assert [d for d, _cb in timers] == [2500]

    # Worker finished; the batch enters its ending drain while the throttled
    # reload timer is still queued.
    with host._refresh_progress_lock:
        host._refresh_progress_pending = {"feed-1": {"id": "feed-1"}}
        host._refresh_progress_flush_scheduled = True
    host._finish_refresh_ui_batch(refresh_tree=False)
    assert host._refresh_ui_batch_ending is True

    # Progress during the drain only marks dirty, and the stale throttled
    # timer is a no-op that keeps the dirty flag for the final update.
    host._request_article_reload()
    timers[0][1]()
    assert host.article_reloads == 0
    assert host._article_refresh_dirty is True

    # Drain completes: the final update schedules the short-debounce reload
    # for the still-dirty view.
    with host._refresh_progress_lock:
        host._refresh_progress_pending.clear()
        host._refresh_progress_flush_scheduled = False
    host._maybe_finish_refresh_ui_batch()
    assert [d for d, _cb in timers] == [2500, 250]
    timers[1][1]()
    assert host.article_reloads == 1
    assert host._article_refresh_dirty is False


def test_no_change_refresh_skips_final_tree_reload(monkeypatch):
    """A successful all-304/no-change refresh must not rebuild the whole tree."""
    monkeypatch.setattr(mainframe.wx, "CallLater", lambda *_args, **_kwargs: None)
    host = _RefreshUiBatchHost()
    host.feed_map = {"feed-1": object()}

    host._begin_refresh_ui_batch()
    host._finish_refresh_ui_batch(refresh_tree=True)

    assert host.tree_loads == 0
    assert host._refresh_ui_batch_active is False


def test_changed_refresh_keeps_final_tree_reload(monkeypatch):
    monkeypatch.setattr(mainframe.wx, "CallLater", lambda *_args, **_kwargs: None)
    host = _RefreshUiBatchHost()
    host.feed_map = {"feed-1": object()}

    host._begin_refresh_ui_batch()
    host._refresh_ui_batch_dirty = True
    host._finish_refresh_ui_batch(refresh_tree=True)

    assert host.tree_loads == 1


def test_late_progress_change_keeps_final_tree_reload(monkeypatch):
    """Evaluate dirty only after queued progress has drained.

    The worker may signal completion while a later bounded wx progress chunk
    remains queued.  That late chunk must still be able to request the final
    tree reload.
    """
    monkeypatch.setattr(mainframe.wx, "CallLater", lambda *_args, **_kwargs: None)
    host = _RefreshUiBatchHost()
    host.feed_map = {"feed-1": object()}

    host._begin_refresh_ui_batch()
    with host._refresh_progress_lock:
        host._refresh_progress_pending = {"feed-1": {"id": "feed-1"}}
        host._refresh_progress_flush_scheduled = True
    host._finish_refresh_ui_batch(refresh_tree=True)

    assert host.tree_loads == 0
    assert host._refresh_ui_batch_ending is True

    # This mirrors a later progress chunk applying a real model change.
    host._refresh_ui_batch_dirty = True
    with host._refresh_progress_lock:
        host._refresh_progress_pending.clear()
        host._refresh_progress_flush_scheduled = False
    host._maybe_finish_refresh_ui_batch()

    assert host.tree_loads == 1


def test_stale_refresh_completion_cannot_finish_a_newer_ui_batch():
    host = _RefreshUiBatchHost()

    first_token = host._begin_refresh_ui_batch()
    second_token = host._begin_refresh_ui_batch()

    host._finish_refresh_ui_batch(refresh_tree=True, batch_token=first_token)
    assert host.tree_loads == 0
    assert host._refresh_ui_batch_active is True

    host._finish_refresh_ui_batch(refresh_tree=True, batch_token=second_token)
    assert host.tree_loads == 1
    assert host._refresh_ui_batch_active is False
