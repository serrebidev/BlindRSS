import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")

from gui.player import _extract_ytdlp_info_via_cli, _is_googlevideo_url, _should_force_local_stream_proxy


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = int(returncode)
        self.stdout = str(stdout)
        self.stderr = str(stderr)


def test_extract_ytdlp_info_via_cli_returns_first_playlist_entry_and_uses_browser_name():
    captured_cmd = {}

    def _fake_run(cmd, **_kwargs):
        captured_cmd["cmd"] = list(cmd)
        return _FakeCompletedProcess(
            returncode=0,
            stdout='{"entries":[{"url":"https://cdn.example/audio.m4a","title":"Example"}]}',
            stderr="",
        )

    with patch("gui.player.subprocess.run", side_effect=_fake_run), patch(
        "gui.player.platform.system", return_value="Windows"
    ), patch("core.dependency_check._get_startup_info", return_value=None):
        info = _extract_ytdlp_info_via_cli(
            "https://www.youtube.com/watch?v=abc123",
            headers={"Accept-Language": "en-US,en;q=0.9", "Origin": "https://www.youtube.com"},
            cookie_source=("edge", r"C:\Users\alice\AppData\Local\Microsoft\Edge\User Data"),
            timeout_s=20,
        )

    assert info["url"] == "https://cdn.example/audio.m4a"
    assert info["title"] == "Example"

    cmd = captured_cmd["cmd"]
    assert "--cookies-from-browser" in cmd
    assert "edge" in cmd
    assert r"C:\Users\alice\AppData\Local\Microsoft\Edge\User Data" not in cmd
    assert "--dump-single-json" in cmd
    assert "--format" in cmd
    assert "--add-header" in cmd
    assert "Accept-Language: en-US,en;q=0.9" in cmd


def test_extract_ytdlp_info_via_cli_raises_on_nonzero_exit():
    with patch(
        "gui.player.subprocess.run",
        return_value=_FakeCompletedProcess(returncode=1, stdout="", stderr="Extractor error"),
    ), patch("gui.player.platform.system", return_value="Windows"), patch(
        "core.dependency_check._get_startup_info", return_value=None
    ):
        with pytest.raises(RuntimeError, match="Extractor error"):
            _extract_ytdlp_info_via_cli("https://example.com/video")


def test_is_googlevideo_url_true_for_youtube_media_host():
    assert _is_googlevideo_url("https://rr4---sn-uxa0n-t8gl.googlevideo.com/videoplayback?itag=140")


def test_is_googlevideo_url_false_for_non_googlevideo_hosts():
    assert _is_googlevideo_url("https://www.youtube.com/watch?v=abc123") is False
    assert _is_googlevideo_url("https://example.com/audio.mp3") is False


def test_should_force_local_stream_proxy_for_googlevideo_when_frozen():
    assert _should_force_local_stream_proxy(
        "https://rr1---sn-uxa0n-t8ge7.googlevideo.com/videoplayback?itag=140",
        is_frozen=True,
    ) is True


def test_should_not_force_local_stream_proxy_when_not_frozen():
    assert _should_force_local_stream_proxy(
        "https://rr1---sn-uxa0n-t8ge7.googlevideo.com/videoplayback?itag=140",
        is_frozen=False,
    ) is False
