import os
import sys
import threading


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


class _DummyMainFrame:
    _snapshot_feed_ids = mainframe.MainFrame._snapshot_feed_ids
    _import_opml_thread = mainframe.MainFrame._import_opml_thread
    _post_import_opml = mainframe.MainFrame._post_import_opml
    _refresh_imported_feed_ids_thread = mainframe.MainFrame._refresh_imported_feed_ids_thread

    def __init__(self, provider):
        self.provider = provider
        self._refresh_guard = threading.Lock()
        self.title_updates = []
        self.refresh_feeds_calls = 0
        self.manual_refresh_calls = 0
        self.progress_states = []
        self.flush_calls = 0
        self.post_calls = []

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


def test_post_import_falls_back_to_full_refresh_when_targeted_refresh_unavailable(monkeypatch):
    host = _DummyMainFrame(_ProviderNoTargetedRefresh())

    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: None)
    monkeypatch.setattr(mainframe.threading, "Thread", _ImmediateThread)

    host._post_import_opml(True, ["feed-b"])

    assert host.manual_refresh_calls == 1
    assert host.refresh_feeds_calls >= 1
