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
        assert cmd[merge_index + 1] == "mp4/mkv"
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
        if merge_format == "mp4/mkv":
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

    assert merge_formats == ["mp4/mkv", "mkv"]
    assert host._downloaded_media_path_for_article(article).endswith("YouTube Video.mkv")
    assert messages and messages[-1][1] == "Download complete"
