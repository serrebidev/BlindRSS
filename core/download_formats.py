# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Download format presets for yt-dlp items (YouTube and friends).

Config stores stable identifiers such as ``"video_best"`` or ``"audio_mp3_192"``;
the UI maps them to localized labels at display time. Internal logic (the
yt-dlp argument builder) must only ever see identifiers, never display labels —
the same rule the retention identifiers follow in :mod:`core.retention`.

Why the video selectors ask for avc1/mp4a explicitly: YouTube's *best* video and
audio streams are usually AV1 (or VP9) and Opus, which ffmpeg cannot safely mux
into MP4, so ``--merge-output-format mp4/mkv`` silently produced an MKV. Asking
for the H.264 + AAC ladder first yields a real MP4 that every player opens, and
the generic ``bv*+ba/b`` tail still covers the rare video with no avc1 rendition.

GUI-free and unit tested so the Settings dialog, the download picker and the
downloader can share it.
"""

from __future__ import annotations

from core.i18n import _

# Ordered identifiers offered in the Settings combobox and the "Download As..."
# picker. Order is the display order: video presets first, then audio.
DOWNLOAD_FORMAT_CHOICES: tuple[str, ...] = (
    "video_best",
    "video_max",
    "video_720",
    "video_480",
    "audio_mp3_320",
    "audio_mp3_192",
    "audio_mp3_128",
    "audio_best",
)

DOWNLOAD_FORMAT_DEFAULT = "video_best"

# MP4-first ladder: H.264 video + AAC audio, then any MP4 progressive rendition,
# then whatever yt-dlp considers best. Height caps use the non-strict ``<=?``
# form so a rendition that does not report a height is still eligible.
_AVC_PREFIX = "bv*[vcodec^=avc1]"
_AAC = "ba[acodec^=mp4a]"


def _video_selector(max_height: int | None) -> str:
    cap = "" if max_height is None else f"[height<=?{int(max_height)}]"
    # Ordered fallbacks: MP4-muxable pair, then any pair, then any progressive
    # rendition at the cap, then anything at all. Without a height cap the last
    # two collapse into the same "b", so drop the duplicate.
    alternatives = [
        f"{_AVC_PREFIX}{cap}+{_AAC}",
        f"bv*{cap}+ba",
        f"b{cap}",
        "b",
    ]
    deduped = list(dict.fromkeys(alternatives))
    return "/".join(deduped)


# identifier -> (yt-dlp format selector, mp3 bitrate or None)
_SPECS = {
    "video_best": (_video_selector(None), None),
    # Deliberately not the MP4 ladder: this is the preset for people who want
    # 1440p/4K and accept an MKV, since YouTube only publishes those in AV1/VP9.
    "video_max": ("bv*+ba/b", None),
    "video_720": (_video_selector(720), None),
    "video_480": (_video_selector(480), None),
    "audio_mp3_320": ("ba/b", 320),
    "audio_mp3_192": ("ba/b", 192),
    "audio_mp3_128": ("ba/b", 128),
    "audio_best": ("ba/b", None),
}


def normalize_download_format(value) -> str:
    """Map a stored config value to a known identifier.

    Unknown/missing values fall back to :data:`DOWNLOAD_FORMAT_DEFAULT` so a
    config written by a newer build (or hand-edited) never breaks downloading.
    """
    text = str(value or "").strip()
    return text if text in _SPECS else DOWNLOAD_FORMAT_DEFAULT


def is_audio_only(value) -> bool:
    """True when this preset extracts audio instead of keeping the video."""
    return normalize_download_format(value).startswith("audio_")


def mp3_bitrate(value) -> int | None:
    """Target MP3 bitrate in kbps, or ``None`` when the preset is not MP3."""
    return _SPECS[normalize_download_format(value)][1]


def format_selector(value) -> str:
    """The ``-f`` expression for a preset."""
    return _SPECS[normalize_download_format(value)][0]


def ytdlp_args(value, *, merge_output_format: str = "mp4") -> list[str]:
    """Full yt-dlp argument list for a preset (format selection + output kind).

    ``merge_output_format`` lets the caller retry a video preset as MKV when
    ffmpeg refuses the MP4 mux; it is ignored for audio-only presets.
    """
    ident = normalize_download_format(value)
    selector, bitrate = _SPECS[ident]
    args = ["-f", selector]
    if is_audio_only(ident):
        args.append("-x")
        if bitrate is None:
            # Keep the source codec (M4A/Opus): no re-encode, no quality loss.
            args.extend(["--audio-format", "best"])
        else:
            args.extend(["--audio-format", "mp3", "--audio-quality", f"{int(bitrate)}K"])
    else:
        args.extend(["--merge-output-format", str(merge_output_format or "mp4")])
    return args


def download_format_label(ident: str) -> str:
    """Localized display label for a download-format identifier.

    Called at display time so the active gettext catalog applies. The msgid
    literals below are what tools/extract_strings.py collects into the POT.
    """
    labels = {
        "video_best": _("Video - MP4, best quality (up to 1080p)"),
        "video_max": _("Video - highest resolution, may produce MKV"),
        "video_720": _("Video - MP4, up to 720p (smaller)"),
        "video_480": _("Video - MP4, up to 480p (smallest)"),
        "audio_mp3_320": _("Audio only - MP3, 320 kbps"),
        "audio_mp3_192": _("Audio only - MP3, 192 kbps"),
        "audio_mp3_128": _("Audio only - MP3, 128 kbps"),
        "audio_best": _("Audio only - best quality, no re-encoding (M4A or Opus)"),
    }
    return labels.get(normalize_download_format(ident), ident)


def download_format_labels() -> list[str]:
    """Localized labels for :data:`DOWNLOAD_FORMAT_CHOICES`, in display order."""
    return [download_format_label(ident) for ident in DOWNLOAD_FORMAT_CHOICES]
