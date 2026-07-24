# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import threading
from types import SimpleNamespace


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args or ()
        self._kwargs = kwargs or {}

    def start(self):
        if callable(self._target):
            self._target(*self._args, **self._kwargs)


class _Feed:
    def __init__(self, feed_id):
        self.id = feed_id


class _ProviderWithTargetedRefresh:
    def __init__(self):
        self._feeds = [_Feed("feed-1")]
        self.import_called = False
        self.refreshed_ids = []

    def get_feeds(self):
        return list(self._feeds)

    def import_opml(self, path, target_category=None):
        self.import_called = True
        self._feeds.extend([_Feed("feed-2"), _Feed("feed-3")])
        return True

    def refresh_feed(self, feed_id, progress_cb=None):
        self.refreshed_ids.append(str(feed_id))
        if callable(progress_cb):
            progress_cb({"id": str(feed_id), "status": "ok"})
        return True


class _ProviderNoTargetedRefresh:
    def __init__(self):
        self._feeds = [_Feed("feed-a")]

    def get_feeds(self):
        return list(self._feeds)

    def import_opml(self, path, target_category=None):
        self._feeds.append(_Feed("feed-b"))
        return True


class _ProviderWithBatchRefresh:
    def __init__(self):
        self.batch_calls = []

    def refresh_feeds_by_ids(self, feed_ids, progress_cb=None, force=True):
        self.batch_calls.append(
            {
                "feed_ids": list(feed_ids or []),
                "force": bool(force),
            }
        )
        if callable(progress_cb):
            for fid in list(feed_ids or []):
                progress_cb({"id": str(fid), "status": "ok"})
        return True


class _DummyMainFrame:
    _snapshot_feed_ids = mainframe.MainFrame._snapshot_feed_ids
    _import_opml_thread = mainframe.MainFrame._import_opml_thread
    _post_import_opml = mainframe.MainFrame._post_import_opml
    _post_import_youtube_takeout = mainframe.MainFrame._post_import_youtube_takeout
    _refresh_imported_feed_ids_thread = mainframe.MainFrame._refresh_imported_feed_ids_thread
    _begin_refresh_activity = mainframe.MainFrame._begin_refresh_activity
    _reset_refresh_progress_counter = mainframe.MainFrame._reset_refresh_progress_counter
    _end_refresh_activity = mainframe.MainFrame._end_refresh_activity
    _post_activity_status = mainframe.MainFrame._post_activity_status
    _set_activity_status = mainframe.MainFrame._set_activity_status

    def __init__(self, provider):
        self.provider = provider
        self._refresh_guard = threading.Lock()
        self.title_updates = []
        self.refresh_feeds_calls = 0
        self.manual_refresh_calls = 0
        self.progress_states = []
        self.flush_calls = 0
        self.post_calls = []
        self.activity_status_updates = []

    def SetTitle(self, title):
        self.title_updates.append(str(title))

    def refresh_feeds(self):
        self.refresh_feeds_calls += 1

    def _manual_refresh_thread(self):
        self.manual_refresh_calls += 1

    def _on_feed_refresh_progress(self, state):
        self.progress_states.append(dict(state or {}))

    def _flush_feed_refresh_progress(self):
        self.flush_calls += 1

    def SetStatusText(self, text, number=0):
        if number == 1:
            self.activity_status_updates.append(text)


def test_import_opml_thread_passes_new_feed_ids_to_post_handler(monkeypatch):
    host = _DummyMainFrame(_ProviderWithTargetedRefresh())
    captured = {}

    def _fake_post(success, new_feed_ids):
        captured["success"] = bool(success)
        captured["new_feed_ids"] = list(new_feed_ids or [])

    host._post_import_opml = _fake_post
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))

    host._import_opml_thread("dummy.opml", None)

    assert captured["success"] is True
    assert captured["new_feed_ids"] == ["feed-2", "feed-3"]


def test_post_import_runs_targeted_refresh_for_new_feeds(monkeypatch):
    provider = _ProviderWithTargetedRefresh()
    host = _DummyMainFrame(provider)
    message_calls = []

    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: message_calls.append((a, k)))
    monkeypatch.setattr(mainframe.threading, "Thread", _ImmediateThread)

    host._post_import_opml(True, ["feed-2", "feed-3"])

    assert provider.refreshed_ids == ["feed-2", "feed-3"]
    assert host.flush_calls == 1
    assert host.refresh_feeds_calls >= 2  # once immediately, once after targeted refresh completes
    assert host.manual_refresh_calls == 0
    assert len(message_calls) == 1
    assert host.activity_status_updates == ["Refreshing imported feeds...", "Refresh complete"]


def test_post_import_falls_back_to_full_refresh_when_targeted_refresh_unavailable(monkeypatch):
    host = _DummyMainFrame(_ProviderNoTargetedRefresh())

    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: None)
    monkeypatch.setattr(mainframe.threading, "Thread", _ImmediateThread)

    host._post_import_opml(True, ["feed-b"])

    assert host.manual_refresh_calls == 1
    assert host.refresh_feeds_calls >= 1


def test_post_import_prefers_batch_refresh_when_available(monkeypatch):
    provider = _ProviderWithBatchRefresh()
    host = _DummyMainFrame(provider)

    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: None)
    monkeypatch.setattr(mainframe.threading, "Thread", _ImmediateThread)

    host._post_import_opml(True, ["feed-2", "feed-3"])

    assert provider.batch_calls == [{"feed_ids": ["feed-2", "feed-3"], "force": True}]
    assert host.flush_calls == 1
    assert host.manual_refresh_calls == 0


def test_takeout_import_does_not_eagerly_refresh_thousands_of_feeds(monkeypatch):
    provider = _ProviderWithTargetedRefresh()
    host = _DummyMainFrame(provider)
    message_calls = []

    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: message_calls.append((a, k)))
    monkeypatch.setattr(mainframe.threading, "Thread", _ImmediateThread)
    result = SimpleNamespace(
        subscriptions=557,
        history_channels=2023,
        owner_channels=1,
        playlists=143,
    )

    host._post_import_youtube_takeout(True, result, [f"feed-{i}" for i in range(2348)])

    assert provider.refreshed_ids == []
    assert host.refresh_feeds_calls == 1  # rebuild the tree only; no network refresh
    assert len(message_calls) == 1
    assert "normal background refreshes" in message_calls[0][0][0]
