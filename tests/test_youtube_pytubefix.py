# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from contextlib import nullcontext
from types import SimpleNamespace
import sys

from core import youtube_pytubefix as ypf


class _Query:
    def __init__(self, audio, progressive):
        self.audio = audio
        self.progressive = progressive

    def filter(self, **kwargs):
        if kwargs.get("only_audio"):
            return list(self.audio)
        if kwargs.get("progressive"):
            return list(self.progressive)
        return []


def test_pick_stream_prefers_best_non_sabr_audio_and_progressive_video():
    low = SimpleNamespace(abr="64kbps", bitrate=64_000, is_sabr=False)
    high = SimpleNamespace(abr="160kbps", bitrate=160_000, is_sabr=False)
    sabr = SimpleNamespace(abr="256kbps", bitrate=256_000, is_sabr=True)
    video_480 = SimpleNamespace(resolution="480p", fps=30, bitrate=800_000, is_sabr=False)
    video_720 = SimpleNamespace(resolution="720p", fps=30, bitrate=1_500_000, is_sabr=False)
    query = _Query([low, sabr, high], [video_480, video_720])

    assert ypf._pick_stream(query, audio_only=True) is high
    assert ypf._pick_stream(query, audio_only=False) is video_720


def test_resolve_stream_returns_ytdlp_compatible_info_without_node(monkeypatch):
    stream = SimpleNamespace(
        url="https://media.example/audio.webm?sig=ok",
        itag=251,
        subtype="webm",
        abr="160kbps",
        bitrate=160_000,
        is_sabr=False,
    )

    class _Video:
        title = "Example"
        length = 123
        watch_url = "https://youtube.com/watch?v=abc123def45"
        streams = _Query([stream], [])

    calls = []

    class _YouTube:
        def __new__(cls, url, **kwargs):
            calls.append((url, kwargs))
            return _Video()

    fake_package = SimpleNamespace(YouTube=_YouTube)
    monkeypatch.setitem(sys.modules, "pytubefix", fake_package)
    monkeypatch.setattr(ypf, "_find_executable_path", lambda _name: "C:/BlindRSS/bin/deno.exe")
    monkeypatch.setattr(ypf, "_configure_deno_runner", lambda path: calls.append(("deno", path)))
    monkeypatch.setattr(ypf, "_bounded_requests", lambda _timeout: nullcontext())

    info = ypf.resolve_stream(
        "https://www.youtube.com/watch?v=abc123def45",
        timeout_s=12,
    )

    assert info["url"].startswith("https://media.example/")
    assert info["duration"] == 123
    assert info["format_id"] == "251"
    assert info["pytubefix"] is True
    assert calls[0] == ("deno", "C:/BlindRSS/bin/deno.exe")
    assert calls[1][1]["client"] == "ANDROID_VR"


def test_specs_exclude_duplicate_node_runtime_and_collect_pytubefix():
    for path in ("main.spec", "portable.spec"):
        text = open(path, encoding="utf-8").read()
        assert "pytubefix" in text
        assert "nodejs_wheel" in text
        assert "excludes=" in text
