# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regression tests for two failures on a YouTube "start radio" watch URL.

A URL such as ``watch?v=<id>&list=RD<id>&start_radio=1`` streams fine in a
browser but used to fail in BlindRSS two different ways:

* Streaming: the embedded yt-dlp options never set ``noplaylist``, so yt-dlp
  routed to the playlist extractor and walked the endless radio mix instead of
  resolving the one video. Playback timed out and fell back to the browser.
* Downloading: the anonymous attempt's real error was overwritten by the
  Windows browser-cookie DPAPI failure of the *next* attempt, so the user was
  shown "Failed to decrypt with DPAPI" for a public video.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import discovery

RADIO_URL = "https://www.youtube.com/watch?v=A3TU_p5kLJI&list=RDA3TU_p5kLJI&start_radio=1"
DPAPI_ERR = (
    "ERROR: Failed to decrypt with DPAPI. See  "
    "https://github.com/yt-dlp/yt-dlp/issues/10927  for more info"
)


def test_dpapi_cookie_error_detected():
    assert discovery.is_ytdlp_dpapi_cookie_error(DPAPI_ERR) is True
    assert discovery.is_ytdlp_dpapi_cookie_error(RuntimeError(DPAPI_ERR)) is True


def test_non_cookie_errors_are_not_dpapi():
    assert discovery.is_ytdlp_dpapi_cookie_error("") is False
    assert discovery.is_ytdlp_dpapi_cookie_error(None) is False
    assert discovery.is_ytdlp_dpapi_cookie_error("ERROR: Video unavailable") is False


def test_youtube_fulltext_extraction_never_walks_the_playlist():
    """A watch URL carrying &list= must resolve one video, not the whole mix."""
    import core.youtube_fulltext as yft

    captured = {}

    class _FakeYDL:
        def __init__(self, options):
            captured["options"] = dict(options)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def extract_info(self, _url, download=False):
            captured["url"] = _url
            return {"id": "A3TU_p5kLJI", "title": "Example"}

    fake_mod = type("_FakeYtDlp", (), {"YoutubeDL": _FakeYDL})
    sys.modules["yt_dlp"] = fake_mod
    try:
        info = yft.extract_video_info(RADIO_URL, include_comments=False)
    finally:
        sys.modules.pop("yt_dlp", None)

    assert info["id"] == "A3TU_p5kLJI"
    assert captured["options"].get("noplaylist") is True
    assert captured["url"] == "https://www.youtube.com/watch?v=A3TU_p5kLJI"


def test_player_stream_options_set_noplaylist():
    """The embedded playback resolve must match the CLI helper's --no-playlist."""
    pytest.importorskip("wx")
    pytest.importorskip("vlc")

    source = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "player.py"),
        encoding="utf-8",
    ).read()
    # base_opts is built inline inside the (very large) load worker, so assert on
    # the option itself rather than standing up a PlayerFrame.
    assert "'noplaylist': True," in source
    # Materializing a lazy playlist would extract every entry in the radio mix.
    assert "list(info['entries'])" not in source


def test_download_to_play_reports_the_anonymous_error_not_dpapi(monkeypatch, tmp_path):
    """A DPAPI cookie failure must not become the reported download error."""
    pytest.importorskip("wx")
    pytest.importorskip("vlc")

    import gui.player as player_mod
    from core import youtube_browser_session

    calls = []

    class _Res:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if "--cookies-from-browser" in cmd:
            source = cmd[cmd.index("--cookies-from-browser") + 1]
            if source == "chrome":
                return _Res(1, stderr=DPAPI_ERR)
            return _Res(1, stderr="ERROR: Video unavailable")
        return _Res(1, stderr="ERROR: Video unavailable")

    monkeypatch.setattr(player_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(player_mod.discovery, "_resolve_ytdlp_cli_path", lambda: "yt-dlp")
    monkeypatch.setattr(
        player_mod.discovery,
        "get_ytdlp_cookie_sources",
        lambda _url: [("chrome",), ("edge",), ("firefox",)],
    )
    monkeypatch.setattr(player_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        youtube_browser_session,
        "bootstrap_youtube_session",
        lambda *_args, **_kwargs: None,
    )

    reported = {}
    monkeypatch.setattr(
        player_mod.wx, "CallAfter", lambda fn, *a, **kw: reported.setdefault("args", a)
    )

    class _Stub:
        _active_load_seq = 7
        config_manager = type("_Cfg", (), {"get": staticmethod(lambda *a, **kw: "")})()

        def _ytdlp_play_cache_dir(self):
            return str(tmp_path)

        def _resolve_printed_filepath(self, _stdout, _cache_dir):
            return None

        def _handle_media_load_error(self, *_a, **_kw):
            return None

    player_mod.PlayerFrame._ytdlp_download_and_play_worker(_Stub(), 7, RADIO_URL)

    cookie_calls = [c for c in calls if "--cookies-from-browser" in c]
    # Edge is skipped after Chrome's DPAPI failure, but Firefox uses a different
    # cookie store and must still be attempted.
    assert len(cookie_calls) == 2
    cookie_sources = [c[c.index("--cookies-from-browser") + 1] for c in cookie_calls]
    assert cookie_sources == ["chrome", "firefox"]
    # And the surfaced reason is the anonymous attempt's, not the cookie noise.
    message = " ".join(str(a) for a in reported.get("args", ()))
    assert "Video unavailable" in message
    assert "DPAPI" not in message
    # The radio-mix wrapper is never sent to yt-dlp, and a final failure stays
    # inside BlindRSS instead of opening the webpage in the browser.
    assert calls and calls[0][-1] == "https://www.youtube.com/watch?v=A3TU_p5kLJI"
    assert any(c[-1].startswith("https://music.youtube.com/watch?") for c in calls)
    assert any(c[-1].startswith("https://www.youtube-nocookie.com/embed/") for c in calls)
    recovery_calls = [c for c in calls if c[-1] != "https://www.youtube.com/watch?v=A3TU_p5kLJI"]
    assert recovery_calls and all("--impersonate" in c for c in recovery_calls)
    assert reported.get("args", ())[-1] is False
