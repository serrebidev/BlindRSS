# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Download format presets for yt-dlp items."""

import pytest

from core import download_formats as df


def test_default_is_a_known_choice():
    assert df.DOWNLOAD_FORMAT_DEFAULT in df.DOWNLOAD_FORMAT_CHOICES


def test_every_choice_has_args_and_a_label():
    for ident in df.DOWNLOAD_FORMAT_CHOICES:
        assert df.ytdlp_args(ident)
        label = df.download_format_label(ident)
        assert label and label != ident


def test_labels_match_choice_order():
    labels = df.download_format_labels()
    assert len(labels) == len(df.DOWNLOAD_FORMAT_CHOICES)
    assert labels[0] == df.download_format_label(df.DOWNLOAD_FORMAT_CHOICES[0])


@pytest.mark.parametrize("bogus", ["", None, "not_a_format", "1 week", 42])
def test_unknown_values_fall_back_to_default(bogus):
    assert df.normalize_download_format(bogus) == df.DOWNLOAD_FORMAT_DEFAULT


def test_audio_presets_are_flagged_and_video_presets_are_not():
    assert df.is_audio_only("audio_mp3_192")
    assert df.is_audio_only("audio_best")
    assert not df.is_audio_only("video_best")
    assert not df.is_audio_only("video_max")


@pytest.mark.parametrize(
    "ident,bitrate",
    [("audio_mp3_320", 320), ("audio_mp3_192", 192), ("audio_mp3_128", 128)],
)
def test_mp3_presets_request_their_bitrate(ident, bitrate):
    assert df.mp3_bitrate(ident) == bitrate
    args = df.ytdlp_args(ident)
    assert "-x" in args
    assert args[args.index("--audio-format") + 1] == "mp3"
    assert args[args.index("--audio-quality") + 1] == f"{bitrate}K"


def test_best_audio_does_not_re_encode():
    assert df.mp3_bitrate("audio_best") is None
    args = df.ytdlp_args("audio_best")
    assert "-x" in args
    assert args[args.index("--audio-format") + 1] == "best"
    assert "--audio-quality" not in args


def test_audio_presets_never_ask_for_a_merge_format():
    for ident in df.DOWNLOAD_FORMAT_CHOICES:
        if df.is_audio_only(ident):
            assert "--merge-output-format" not in df.ytdlp_args(ident)


def test_mp4_presets_prefer_h264_and_aac():
    """The AV1/Opus "best" pair is what silently produced MKV files."""
    for ident in ("video_best", "video_720", "video_480"):
        selector = df.format_selector(ident)
        assert selector.startswith("bv*[vcodec^=avc1]")
        assert "ba[acodec^=mp4a]" in selector
        assert df.ytdlp_args(ident)[-1] == "mp4"


def test_mp4_selector_has_no_duplicate_alternatives():
    parts = df.format_selector("video_best").split("/")
    assert len(parts) == len(set(parts))


@pytest.mark.parametrize("ident,height", [("video_720", 720), ("video_480", 480)])
def test_capped_presets_apply_a_non_strict_height_filter(ident, height):
    # "<=?" keeps renditions that do not report a height eligible.
    assert f"[height<=?{height}]" in df.format_selector(ident)


def test_max_preset_takes_the_uncapped_best_pair():
    assert df.format_selector("video_max") == "bv*+ba/b"
    assert "height" not in df.format_selector("video_max")


def test_merge_format_override_is_honored_for_video_only():
    assert df.ytdlp_args("video_best", merge_output_format="mkv")[-1] == "mkv"
    assert "mkv" not in df.ytdlp_args("audio_mp3_192", merge_output_format="mkv")
