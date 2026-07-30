# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import platform
import subprocess
import sys
import threading
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe
import gui.player as player_mod


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
    host = mainframe.MainFrame.__new__(mainframe.MainFrame)
    host.config_manager = _Config(tmp_path)
    host.provider = SimpleNamespace(get_name=lambda: "local")
    host.feed_map = {"feed-1": SimpleNamespace(title="Example Podcast")}
    host.view_cache = {}
    host._view_cache_lock = threading.Lock()
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


def test_direct_download_records_local_path_for_offline_playback(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article()
    messages = []

    monkeypatch.setattr(mainframe.utils, "safe_requests_get", lambda *a, **k: _Response())
    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )

    host._download_article_thread(article)

    local_path = host._downloaded_media_path_for_article(article)
    assert local_path is not None
    assert os.path.isfile(local_path)
    assert local_path.endswith(os.path.join("Example Podcast", "Episode 1.mp3"))
    assert messages and messages[-1][1] == "Download complete"


def test_direct_download_failure_callback_keeps_exception_message(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article()
    callbacks = []
    messages = []

    def fail_request(*_args, **_kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(mainframe.utils, "safe_requests_get", fail_request)
    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: callbacks.append(
                lambda: fn(*args, **kwargs)
            ),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )

    host._download_article_thread(article)

    # The failure path also posts begin/end activity-status updates via
    # CallAfter alongside the MessageBox; run every deferred callback instead
    # of assuming the MessageBox is the only thing scheduled.
    assert callbacks
    for callback in callbacks:
        callback()
    assert messages == [
        ("Download failed: network unavailable", "Download error", 1)
    ]


def test_playback_target_prefers_recorded_download(tmp_path):
    host = _host(tmp_path)
    article = _article()
    local_dir = tmp_path / "Example Podcast"
    local_dir.mkdir()
    local_file = local_dir / "Episode 1.mp3"
    local_file.write_bytes(b"episode")

    host._record_article_download(article, str(local_file))
    reloaded_article = _article()

    target, use_ytdlp = host._playback_target_for_article(reloaded_article)

    assert target == str(local_file)
    assert use_ytdlp is False


def test_playback_target_finds_legacy_download_without_index(tmp_path):
    host = _host(tmp_path)
    article = _article(title="Episode: One")
    legacy_dir = tmp_path / "Example Podcast"
    legacy_dir.mkdir()
    legacy_file = legacy_dir / f"{host._safe_name(article.title)}.mp3"
    legacy_file.write_bytes(b"episode")

    target, use_ytdlp = host._playback_target_for_article(article)

    assert target == str(legacy_file)
    assert use_ytdlp is False
    assert host.config_manager.get("downloaded_media")


def test_player_uses_vlc_path_api_for_local_download(tmp_path):
    local_file = tmp_path / "Episode One.mp3"
    local_file.write_bytes(b"episode")
    calls = []

    class _Instance:
        def media_new_path(self, path):
            calls.append(("path", path))
            return "path-media"

        def media_new(self, url):
            calls.append(("mrl", url))
            return "mrl-media"

    frame = player_mod.PlayerFrame.__new__(player_mod.PlayerFrame)
    frame.instance = _Instance()

    assert frame._new_vlc_media(str(local_file)) == "path-media"
    assert calls == [("path", str(local_file))]


def test_ytdlp_download_allows_mkv_when_youtube_codecs_are_not_mp4_compatible(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=s-59p7kUAaE"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []
    commands = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        merge_index = cmd.index("--merge-output-format")
        assert cmd[merge_index + 1] == "mp4"
        assert _kwargs["creationflags"] == 0
        assert _kwargs["startupinfo"] is None
        target_dir = host._download_dir_for_article(article)
        with open(os.path.join(target_dir, "YouTube Video.mkv"), "wb") as f:
            f.write(b"merged-video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert commands
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mkv")
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_retries_conversion_failure_as_mkv(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=s-59p7kUAaE"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []
    merge_formats = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")

    def fake_run(cmd, **_kwargs):
        merge_format = cmd[cmd.index("--merge-output-format") + 1]
        merge_formats.append(merge_format)
        if merge_format == "mp4":
            target_dir = host._download_dir_for_article(article)
            with open(os.path.join(target_dir, "YouTube Video.temp.mp4"), "wb") as f:
                f.write(b"failed-merge")
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Postprocessing: Conversion failed!")
        target_dir = host._download_dir_for_article(article)
        with open(os.path.join(target_dir, "YouTube Video.mkv"), "wb") as f:
            f.write(b"merged-video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert merge_formats == ["mp4", "mkv"]
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mkv")
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_honors_an_mp3_format_preset(tmp_path, monkeypatch):
    """An MP3 preset must extract audio and never ask ffmpeg to mux video."""
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=s-59p7kUAaE"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []
    commands = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        assert "--merge-output-format" not in cmd
        assert "-x" in cmd
        assert cmd[cmd.index("--audio-format") + 1] == "mp3"
        assert cmd[cmd.index("--audio-quality") + 1] == "192K"
        target_dir = host._download_dir_for_article(article)
        with open(os.path.join(target_dir, "YouTube Video.mp3"), "wb") as f:
            f.write(b"audio")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url, "audio_mp3_192")

    # One attempt only: audio presets have no MKV rescue pass to make.
    assert len(commands) == 1
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mp3")
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_retries_with_wider_player_client_pool(tmp_path, monkeypatch):
    """A 'Video unavailable' from the primary client pool must trigger the
    wider YOUTUBE_PLAYER_CLIENTS_FALLBACK pool before giving up."""
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=A3TU_p5kLJI&list=RDA3TU_p5kLJI&start_radio=1"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []
    client_args = []
    commands = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")

    primary_arg = mainframe.core.discovery.youtube_player_client_arg()
    fallback_arg = mainframe.core.discovery.youtube_player_client_arg(
        mainframe.core.discovery.YOUTUBE_PLAYER_CLIENTS_FALLBACK
    )

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        client_args.append(cmd[cmd.index("--extractor-args") + 1])
        if len(client_args) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="ERROR: [youtube] A3TU_p5kLJI: Video unavailable. This video is not available",
            )
        target_dir = host._download_dir_for_article(article)
        with open(os.path.join(target_dir, "YouTube Video.mp4"), "wb") as f:
            f.write(b"merged-video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert client_args == [primary_arg, fallback_arg]
    assert all(
        cmd[-1] == "https://www.youtube.com/watch?v=A3TU_p5kLJI"
        for cmd in commands
    )
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mp4")
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_recovers_through_youtube_music_frontend(tmp_path, monkeypatch):
    """If both canonical client pools say unavailable, retry an official
    alternate frontend with browser impersonation before failing."""
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = (
        "https://www.youtube.com/watch?v=A3TU_p5kLJI"
        "&list=RDA3TU_p5kLJI&start_radio=1"
    )
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []
    commands = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        if cmd[-1].startswith("https://music.youtube.com/watch?"):
            target_dir = host._download_dir_for_article(article)
            with open(os.path.join(target_dir, "YouTube Video.mp4"), "wb") as f:
                f.write(b"merged-video")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="ERROR: [youtube] A3TU_p5kLJI: Video unavailable",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert len(commands) == 3
    assert commands[0][-1] == "https://www.youtube.com/watch?v=A3TU_p5kLJI"
    assert commands[1][-1] == "https://www.youtube.com/watch?v=A3TU_p5kLJI"
    assert commands[2][-1] == "https://music.youtube.com/watch?v=A3TU_p5kLJI"
    assert commands[2][commands[2].index("--impersonate") + 1] == "chrome"
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mp4")
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_keeps_firefox_after_chromium_dpapi(tmp_path, monkeypatch):
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=A3TU_p5kLJI"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []
    commands = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(
        mainframe.core.discovery,
        "get_ytdlp_cookie_sources",
        lambda _url: [("chrome",), ("edge",), ("firefox",)],
    )
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        if "--cookies-from-browser" not in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Video unavailable")
        source = cmd[cmd.index("--cookies-from-browser") + 1]
        if source == "chrome":
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="ERROR: Failed to decrypt with DPAPI",
            )
        assert source == "firefox"
        target_dir = host._download_dir_for_article(article)
        with open(os.path.join(target_dir, "YouTube Video.mp4"), "wb") as f:
            f.write(b"merged-video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    cookie_calls = [c for c in commands if "--cookies-from-browser" in c]
    cookie_sources = [c[c.index("--cookies-from-browser") + 1] for c in cookie_calls]
    assert cookie_sources == ["chrome", "firefox"]
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mp4")
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_recovers_with_hidden_browser_visitor_session(
    tmp_path,
    monkeypatch,
):
    from core import youtube_browser_session

    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=A3TU_p5kLJI"
    article.media_url = article.url
    article.media_type = "video/youtube"
    cookie_file = tmp_path / "browser-youtube-cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    commands = []
    messages = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")
    monkeypatch.setattr(
        youtube_browser_session,
        "bootstrap_youtube_session",
        lambda *_args, **_kwargs: youtube_browser_session.YouTubeBrowserSession(
            cookie_file=str(cookie_file),
            visitor_data="visitor%3D%3D",
            user_agent="Mozilla/5.0 Test Chrome",
        ),
    )

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        extractor_arg = cmd[cmd.index("--extractor-args") + 1]
        if "visitor_data=visitor%3D%3D" in extractor_arg:
            target_dir = host._download_dir_for_article(article)
            with open(os.path.join(target_dir, "YouTube Video.mp4"), "wb") as f:
                f.write(b"merged-video")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Video unavailable")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    browser_cmd = commands[-1]
    assert browser_cmd[browser_cmd.index("--cookies") + 1] == str(cookie_file)
    assert browser_cmd[browser_cmd.index("--user-agent") + 1] == "Mozilla/5.0 Test Chrome"
    assert browser_cmd[browser_cmd.index("--impersonate") + 1] == "chrome"
    assert "visitor_data=visitor%3D%3D" in browser_cmd[
        browser_cmd.index("--extractor-args") + 1
    ]
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mp4")
    assert messages and messages[-1][1] == "Download complete"


def test_ytdlp_download_skips_fallback_pool_when_primary_succeeds(tmp_path, monkeypatch):
    """The wider client pool is a last resort: a working primary attempt
    must not pay for a second extraction."""
    host = _host(tmp_path)
    article = _article(title="YouTube Video")
    article.url = "https://www.youtube.com/watch?v=s-59p7kUAaE"
    article.media_url = article.url
    article.media_type = "video/youtube"
    messages = []
    commands = []

    monkeypatch.setattr(
        mainframe,
        "wx",
        SimpleNamespace(
            CallAfter=lambda fn, *args, **kwargs: fn(*args, **kwargs),
            MessageBox=lambda *args, **kwargs: messages.append(args),
            ICON_ERROR=1,
        ),
    )
    monkeypatch.setattr(mainframe.core.discovery, "_resolve_ytdlp_cli_path", lambda: "/tmp/yt-dlp")
    monkeypatch.setattr(mainframe.core.discovery, "get_ytdlp_cookie_sources", lambda _url: [])
    monkeypatch.setattr(mainframe.dependency_check, "_find_executable_path", lambda _name: "/tmp/ffmpeg")

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        target_dir = host._download_dir_for_article(article)
        with open(os.path.join(target_dir, "YouTube Video.mp4"), "wb") as f:
            f.write(b"merged-video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    host._download_article_via_ytdlp(article, article.url)

    assert len(commands) == 1
    assert commands[0][commands[0].index("--extractor-args") + 1] == (
        mainframe.core.discovery.youtube_player_client_arg()
    )
    assert messages and messages[-1][1] == "Download complete"
