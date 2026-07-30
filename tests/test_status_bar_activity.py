# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Status bar activity field (issue: status bar shows nothing while feed
refresh / downloads are in progress).

The status bar gained a second field (field 1) dedicated to ambient
background-activity text, kept separate from field 0 (existing filter-match
counts and other transient messages) so a refresh or download in progress
never clobbers what a screen-reader user just heard. These tests cover:

(a) field 0 / field 1 isolation,
(b) the feed-refresh begin -> per-feed -> end sequence, and
(c) the download begin -> success / begin -> failure sequences.

No real GUI-backed MainFrame is instantiated (see test_mainframe_issue22_shortcuts.py
for the established pattern this follows): tests either use a plain stand-in
object that borrows the real unbound MainFrame methods under test, or - for
the download tests, which need the real download plumbing
(_record_article_download, _apply_download_retention, _get_feed_title, etc.)
- a MainFrame.__new__() instance the same way test_offline_download_playback.py
does, with SetStatusText shadowed by an instance attribute so the activity
text is observable instead of hitting the real (uninitialized) wx.Frame method.
"""

import os
import subprocess
import sys
import threading
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe
from gui.tray import MAX_TRAY_LABEL_LENGTH, format_tray_label


def _sync_call_after(monkeypatch):
    """Run wx.CallAfter callbacks synchronously (precedent: test_opml_import_refresh.py)."""
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))


class _FakeTree:
    def GetSelection(self):
        return None


class _FakeTray:
    def __init__(self):
        self.updates = []
        self.label = "BlindRSS"

    def update_status_label(self, unread_count=0, activity=""):
        self.updates.append((unread_count, activity))
        self.label = format_tray_label(unread_count, activity)
        return True


class _StatusBarHost:
    """Stand-in for the refresh-activity status methods (borrows real unbound
    MainFrame methods; records SetStatusText(text, field) calls instead of
    touching a real wx status bar)."""

    _set_activity_status = mainframe.MainFrame._set_activity_status
    _post_activity_status = mainframe.MainFrame._post_activity_status
    _begin_refresh_activity = mainframe.MainFrame._begin_refresh_activity
    _end_refresh_activity = mainframe.MainFrame._end_refresh_activity
    _set_feed_activity_status = mainframe.MainFrame._set_feed_activity_status
    _reset_refresh_progress_counter = mainframe.MainFrame._reset_refresh_progress_counter
    _note_refresh_progress_feed = mainframe.MainFrame._note_refresh_progress_feed
    _refresh_progress_counts = mainframe.MainFrame._refresh_progress_counts
    _expected_refresh_feed_count = mainframe.MainFrame._expected_refresh_feed_count
    _apply_feed_refresh_progress = mainframe.MainFrame._apply_feed_refresh_progress
    _on_feed_refresh_progress = mainframe.MainFrame._on_feed_refresh_progress
    _flush_feed_refresh_progress = mainframe.MainFrame._flush_feed_refresh_progress
    _set_tray_activity_label = mainframe.MainFrame._set_tray_activity_label
    _update_tray_status_label = mainframe.MainFrame._update_tray_status_label
    _total_unread_count_for_tray = mainframe.MainFrame._total_unread_count_for_tray

    def __init__(self):
        self.fields = {0: "", 1: ""}
        self.field_history = {0: [], 1: []}
        self.feed_map = {}
        self.feed_nodes = {}
        self.tray_icon = _FakeTray()
        self._tray_activity_label = ""
        self.tree = _FakeTree()
        self._refresh_progress_pending = {}
        self._refresh_progress_lock = threading.Lock()
        self._refresh_progress_flush_scheduled = False

    def SetStatusText(self, text, number=0):
        number = int(number)
        self.fields[number] = text
        self.field_history[number].append(text)

    def _update_category_unread_chain_ui(self, _category, _delta):
        return None


# --- (a) field 0 / field 1 isolation ---------------------------------------


def test_activity_status_writes_only_field_1(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    host._post_activity_status("Refreshing feeds...")

    assert host.fields[1] == "Refreshing feeds..."
    assert host.fields[0] == ""
    assert host.field_history[0] == []
    assert host.tray_icon.label == "Refreshing feeds..."


def test_activity_status_does_not_clobber_existing_filter_count(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    # Mirrors the existing field-0 behavior at gui/mainframe.py call sites
    # like `self.SetStatusText(f"Filter: {n} of {m}")` (no field index -> field 0).
    host.SetStatusText("Filter: 3 of 12")

    host._begin_refresh_activity()
    assert host.fields[0] == "Filter: 3 of 12"
    assert host.fields[1] == "Refreshing feeds..."

    host._apply_feed_refresh_progress({"id": "feed-1", "title": "Example Feed", "status": "ok"})
    assert host.fields[0] == "Filter: 3 of 12"
    assert host.fields[1] == "Checked: Example Feed"

    host._end_refresh_activity()
    assert host.fields[0] == "Filter: 3 of 12"
    assert host.fields[1] == "Refresh complete"

    # Field 0 was never written by any activity-status call.
    assert host.field_history[0] == ["Filter: 3 of 12"]


# --- (b) refresh begin -> per-feed -> end sequence --------------------------


def test_refresh_activity_begin_per_feed_end_sequence(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    host._begin_refresh_activity()
    host._apply_feed_refresh_progress(
        {"id": "feed-1", "title": "Example Feed", "unread_count": 2, "category": "News", "status": "ok"}
    )
    host._apply_feed_refresh_progress(
        {
            "id": "feed-2",
            "title": "Broken Feed",
            "unread_count": 0,
            "category": "News",
            "status": "error",
            "error": "timed out",
        }
    )
    host._end_refresh_activity()

    assert host.field_history[1] == [
        "Refreshing feeds...",
        "Checked: Example Feed",
        "Error checking: Broken Feed",
        "Refresh complete",
    ]


def test_begin_refresh_activity_detail_wording_for_targeted_refreshes(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    # Targeted refreshes pass complete, already-localized wording; only the
    # full-feed refresh relies on the default.  (The real call sites' wording
    # is asserted end-to-end in test_category_opml_export /
    # test_opml_import_refresh.)
    host._begin_refresh_activity()
    host._begin_refresh_activity("Refreshing feed: Example Feed...")
    host._begin_refresh_activity("Refreshing category: Tech...")
    host._begin_refresh_activity("Refreshing imported feeds...")

    assert host.field_history[1] == [
        "Refreshing feeds...",
        "Refreshing feed: Example Feed...",
        "Refreshing category: Tech...",
        "Refreshing imported feeds...",
    ]


# --- (b2) "checked X out of Y" refresh progress (issue #85) ----------------


def _feed_state(feed_id, title, **extra):
    state = {"id": feed_id, "title": title, "unread_count": 0, "category": "News", "status": "ok"}
    state.update(extra)
    return state


def test_refresh_progress_counts_feeds_against_the_batch_total(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    host._begin_refresh_activity(total=3)
    assert host.fields[1] == "Refreshing feeds..."

    host._on_feed_refresh_progress(_feed_state("feed-1", "First"))
    assert host.fields[1] == "Checked 1 out of 3"

    host._on_feed_refresh_progress(_feed_state("feed-2", "Second"))
    assert host.fields[1] == "Checked 2 out of 3"

    # The tray follows the batch count, not the last feed's title.
    assert host.tray_icon.label == "Refreshing: 2 out of 3"

    host._end_refresh_activity()
    assert host.fields[1] == "Refresh complete"
    assert host.tray_icon.label == "BlindRSS"


def test_refresh_progress_keeps_the_failing_feed_title(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    host._begin_refresh_activity(total=2)
    host._on_feed_refresh_progress(_feed_state("feed-1", "Broken Feed", status="error", error="timed out"))

    assert host.fields[1] == "Error checking: Broken Feed (1 out of 2)"


def test_refresh_progress_counts_each_feed_once(monkeypatch):
    """A provider that reports the same feed twice (a retry pass) must not
    advance the count, and one that reports more feeds than predicted must not
    announce "3 out of 2"."""
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    host._begin_refresh_activity(total=2)
    host._on_feed_refresh_progress(_feed_state("feed-1", "First", status="error", error="timed out"))
    host._on_feed_refresh_progress(_feed_state("feed-1", "First"))
    assert host.fields[1] == "Checked 1 out of 2"

    host._on_feed_refresh_progress(_feed_state("feed-2", "Second"))
    host._on_feed_refresh_progress(_feed_state("feed-3", "Third"))
    assert host.fields[1] == "Checked 3 out of 3"


def test_refresh_without_a_known_total_keeps_the_feed_title_wording(monkeypatch):
    """A single-feed refresh names the feed: "1 out of 1" says less."""
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    host._begin_refresh_activity("Refreshing feed: Example Feed...")
    host._on_feed_refresh_progress(_feed_state("feed-1", "Example Feed"))

    assert host.fields[1] == "Checked: Example Feed"


def test_progress_count_resets_between_refresh_batches(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()

    host._begin_refresh_activity(total=2)
    host._on_feed_refresh_progress(_feed_state("feed-1", "First"))
    host._on_feed_refresh_progress(_feed_state("feed-2", "Second"))
    host._end_refresh_activity()

    host._begin_refresh_activity(total=2)
    host._on_feed_refresh_progress(_feed_state("feed-1", "First"))
    assert host.fields[1] == "Checked 1 out of 2"


def test_expected_refresh_feed_count_prefers_the_tree_snapshot():
    host = _StatusBarHost()
    host.provider = SimpleNamespace(get_feeds=lambda: [SimpleNamespace(id="feed-9")])

    assert host._expected_refresh_feed_count() == 1

    host.feed_map = {
        "feed-1": SimpleNamespace(id="feed-1", unread_count=0),
        "feed-2": SimpleNamespace(id="feed-2", unread_count=0),
    }
    assert host._expected_refresh_feed_count() == 2


def test_feed_activity_status_falls_back_to_generic_title():
    host = _StatusBarHost()
    host._set_feed_activity_status({"id": "feed-1", "title": ""})
    assert host.fields[1] == "Checked: feed"


def test_feed_activity_status_treats_error_field_as_error_even_without_status():
    host = _StatusBarHost()
    host._set_feed_activity_status({"id": "feed-1", "title": "Example Feed", "error": "boom"})
    assert host.fields[1] == "Error checking: Example Feed"


def test_tray_label_formatter_includes_unread_and_activity():
    assert format_tray_label(0, "") == "BlindRSS"
    # No "BlindRSS" prefix on status labels: the OS/screen reader already
    # announces the app name for the tray icon (issue #38).
    assert format_tray_label(103, "") == "Unread: 103"
    assert format_tray_label(103, "Checked: Supernews") == "Unread: 103, Checked: Supernews"
    assert len(format_tray_label(3, "Checked: " + ("Very Long Feed " * 20))) <= MAX_TRAY_LABEL_LENGTH


def test_refresh_activity_updates_and_clears_tray_label(monkeypatch):
    _sync_call_after(monkeypatch)
    host = _StatusBarHost()
    host.feed_map = {
        "feed-1": SimpleNamespace(id="feed-1", title="Example Feed", category="News", unread_count=3),
        "feed-2": SimpleNamespace(id="feed-2", title="Other Feed", category="News", unread_count=2),
    }

    host._update_tray_status_label()
    assert host.tray_icon.label == "Unread: 5"

    host._begin_refresh_activity()
    assert host.tray_icon.label == "Unread: 5, Refreshing feeds..."

    # Route through the real progress pipeline: the tray/unread total is
    # updated once per flush chunk (not per feed) to stay linear in feed count.
    host._on_feed_refresh_progress(
        {"id": "feed-1", "title": "Example Feed", "unread_count": 4, "category": "News", "status": "ok"}
    )
    # Per-feed detail stays in the status bar; keeping the tray activity stable
    # avoids a native tray-icon redraw for every completed feed.
    assert host.tray_icon.label == "Unread: 6, Refreshing feeds..."

    host._end_refresh_activity()
    assert host.tray_icon.label == "Unread: 6"


def test_progress_flush_updates_native_tray_once_for_multiple_feed_states():
    """A progress chunk keeps its final activity text but performs only one
    feed-total/native-tray update, rather than one expensive update per feed.
    """
    host = _StatusBarHost()
    host.feed_map = {
        "feed-1": SimpleNamespace(id="feed-1", title="First", category="News", unread_count=1),
        "feed-2": SimpleNamespace(id="feed-2", title="Second", category="News", unread_count=2),
    }
    host._refresh_progress_pending = {
        "feed-1": {"id": "feed-1", "title": "First", "unread_count": 4, "category": "News", "status": "ok"},
        "feed-2": {"id": "feed-2", "title": "Second", "unread_count": 6, "category": "News", "status": "ok"},
    }
    host._refresh_progress_flush_scheduled = True

    host._flush_feed_refresh_progress()

    assert host.fields[1] == "Checked: Second"
    assert host.tray_icon.updates == [(10, "")]


def test_progress_flush_announces_only_the_latest_state_in_a_chunk():
    host = _StatusBarHost()
    host._refresh_progress_pending = {
        "feed-1": {"id": "feed-1", "title": "First", "unread_count": 1, "category": "News", "status": "ok"},
        "feed-2": {"id": "feed-2", "title": "Second", "unread_count": 2, "category": "News", "status": "ok"},
    }
    host._refresh_progress_flush_scheduled = True

    host._flush_feed_refresh_progress()

    assert host.field_history[1] == ["Checked: Second"]


def test_feed_metadata_change_marks_an_active_refresh_batch_dirty():
    host = _StatusBarHost()
    host.feed_map = {
        "feed-1": SimpleNamespace(
            id="feed-1",
            title="Example Feed",
            category="News",
            unread_count=3,
        )
    }
    host._refresh_ui_batch_active = True
    host._refresh_ui_batch_dirty = False

    host._apply_feed_refresh_progress(
        {
            "id": "feed-1",
            "title": "Example Feed",
            "category": "News",
            "unread_count": 3,
            "status": "ok",
            "feed_metadata_changed": True,
        }
    )

    assert host._refresh_ui_batch_dirty is True


# --- (c) downloads: begin -> success / begin -> failure ---------------------


class _Config:
    def __init__(self, download_path):
        self.values = {
            "active_provider": "local",
            "download_path": str(download_path),
            "download_retention": "Unlimited",
            "downloaded_media": {},
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _Response:
    headers = {"Content-Type": "audio/mpeg"}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield b"episode-bytes"


def _host(tmp_path):
    # Matches the harness in test_offline_download_playback.py: a real (but
    # __init__-bypassed) MainFrame instance gives us the real download
    # plumbing (_record_article_download, _apply_download_retention,
    # _get_feed_title, etc.) without building a GUI.
    host = mainframe.MainFrame.__new__(mainframe.MainFrame)
    host.config_manager = _Config(tmp_path)
    host.provider = SimpleNamespace(get_name=lambda: "local")
    host.feed_map = {"feed-1": SimpleNamespace(title="Example Podcast")}
    host.view_cache = {}
    host._view_cache_lock = threading.Lock()
    status_updates = []
    host._activity_status_updates = status_updates
    host.SetStatusText = lambda text, number=0, _u=status_updates: _u.append(text) if int(number) == 1 else None
    return host


def _article(title="Episode 1"):
    return SimpleNamespace(
        id="episode-1",
        cache_id="feed-1:episode-1",
        feed_id="feed-1",
        title=title,
        url="https://example.com/episode-1",
        media_url="https://cdn.example.com/episode-1.mp3",
        media_type="audio/mpeg",
        chapters=[],
    )


def _fake_wx(monkeypatch, messages):
    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )


def test_direct_download_status_sequence_on_success(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article()
    messages = []

    monkeypatch.setattr(mainframe.utils, "safe_requests_get", lambda *a, **k: _Response())
    _fake_wx(monkeypatch, messages)

    host._download_article_thread(article)

    assert host._activity_status_updates == ["Downloading: Episode 1", "Download complete: Episode 1"]
    assert messages and messages[-1][1] == "Download complete"


def test_direct_download_status_sequence_on_failure(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article()
    messages = []

    def fail_request(*_args, **_kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(mainframe.utils, "safe_requests_get", fail_request)
    _fake_wx(monkeypatch, messages)

    host._download_article_thread(article)

    assert host._activity_status_updates == ["Downloading: Episode 1", "Download failed: Episode 1"]
    assert messages == [("Download failed: network unavailable", "Download error", 1)]


def test_ytdlp_download_status_sequence_on_success(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=s-59p7kUAaE"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []

    _fake_wx(monkeypatch, messages)
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")

    def fake_run(cmd, **_kwargs):
        target_dir = host._download_dir_for_article(article)
        with open(os.path.join(target_dir, "YouTube Video.mp4"), "wb") as f:
            f.write(b"merged-video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert host._activity_status_updates == ["Download complete: YouTube Video"]
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_status_sequence_on_failure(tmp_path, monkeypatch):
    from core import youtube_browser_session, youtube_pytubefix

    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=s-59p7kUAaE"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []

    _fake_wx(monkeypatch, messages)
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: None)
    monkeypatch.setattr(youtube_pytubefix, "resolve_stream", lambda *_a, **_k: None)
    monkeypatch.setattr(
        youtube_browser_session,
        "bootstrap_youtube_session",
        lambda *_a, **_k: None,
    )

    def fake_run(cmd, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: unsupported format")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert host._activity_status_updates == [
        "Trying pytubefix: YouTube Video",
        "Preparing YouTube browser session: YouTube Video",
        "Download failed: YouTube Video",
    ]
    assert messages and messages[-1][1] == "Download error"


def test_ytdlp_download_not_installed_sets_failed_status(tmp_path, monkeypatch):
    from core import youtube_browser_session, youtube_pytubefix

    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=s-59p7kUAaE"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []

    _fake_wx(monkeypatch, messages)
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: None)
    monkeypatch.setattr(youtube_pytubefix, "resolve_stream", lambda *_a, **_k: None)
    monkeypatch.setattr(
        youtube_browser_session,
        "bootstrap_youtube_session",
        lambda *_a, **_k: None,
    )

    def fake_run(cmd, **_kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert host._activity_status_updates == ["Download failed: YouTube Video"]
    assert messages and messages[-1][1] == "Download error"


def test_download_activity_title_falls_back_when_blank():
    host = mainframe.MainFrame.__new__(mainframe.MainFrame)
    assert host._download_activity_title(SimpleNamespace(title="")) == "episode"
    assert host._download_activity_title(SimpleNamespace(title="  ")) == "episode"
    assert host._download_activity_title(SimpleNamespace(title="My Episode")) == "My Episode"
