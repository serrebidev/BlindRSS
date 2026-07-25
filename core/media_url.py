# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""URL handling for the File > Open Media URL command.

The command takes any URL the app can already play or download — a yt-dlp page
(YouTube and the ~1800 other extractor sites) or a direct media file — and
either streams it or saves it. This module is the GUI-free half: what counts as
an openable URL, and how a pasted string is cleaned up before anything touches
the network. The dialog, the dispatcher in gui.mainframe and the tests all go
through these functions so "is this a usable URL" has exactly one definition.

Nothing here talks to yt-dlp; whether an accepted URL has a *supported
extractor* is core.discovery.is_ytdlp_supported's job, and an unsupported one
still downloads fine as a plain file.
"""

from __future__ import annotations

import os
import re
from urllib.parse import unquote, urlsplit

# Characters people paste around a URL: angle brackets from mail clients, plain
# and curly quotes, plus surrounding whitespace.
_WRAPPERS = " \t\r\n<>\"'\u201c\u201d\u2018\u2019"

ALLOWED_SCHEMES = ("http", "https")

# Streams the player opens directly but that no browser-style extension check
# would catch; kept out of the filename guesser below.
_STREAM_EXTENSIONS = (".m3u8", ".mpd")

_MEDIA_EXTENSIONS = (
    ".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac",
    ".wma", ".aiff", ".aif", ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi",
    ".wmv", ".flv", ".ts",
) + _STREAM_EXTENSIONS


def _has_other_scheme(raw: str) -> bool:
    """True for "mailto:x" / "magnet:?..." style schemes we do not fetch.

    Told apart from a host:port ("example.com:8080", "localhost:8080") by the
    scheme having no dot in it and not being followed by a port number.
    """
    head, sep, rest = raw.partition(":")
    if not sep or "." in head or "/" in head:
        return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", head):
        return False
    return not rest[:1].isdigit()


def normalize_media_url(text) -> str:
    """Clean a pasted string into an http(s) URL, or return "" if it is not one.

    Accepts what a user actually pastes: a full URL, a scheme-less one
    ("www.youtube.com/watch?v=..."), or a protocol-relative one ("//host/x").
    Anything else — a search phrase, a file path, a mailto:/magnet: link — is
    rejected here rather than being handed to yt-dlp to fail obscurely.
    """
    raw = str(text or "").strip().strip(_WRAPPERS).strip()
    if not raw or any(ch.isspace() for ch in raw):
        return ""

    if raw.startswith("//"):
        raw = "https:" + raw
    elif "://" not in raw:
        if _has_other_scheme(raw):
            return ""
        # Only guess a scheme when the leading segment looks like a hostname;
        # "how to bake bread" and "C:\videos" must not become URLs.
        head = raw.split("/", 1)[0].split("?", 1)[0].split("@")[-1]
        host = head.split(":", 1)[0]
        if not re.fullmatch(r"[A-Za-z0-9._~-]+", host) or "." not in host:
            return ""
        raw = "https://" + raw

    parts = urlsplit(raw)
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
        return ""
    host = parts.hostname
    if "." not in host and host.lower() not in ("localhost",):
        return ""
    return raw


def is_media_url(text) -> bool:
    """True when :func:`normalize_media_url` would accept this string."""
    return bool(normalize_media_url(text))


def looks_like_direct_media_file(url) -> bool:
    """True when the URL path ends in a media extension we can save as-is.

    Only a hint for wording and for choosing the download path; the actual
    fallback is "not a yt-dlp page" (see gui.mainframe), so an extension-less
    direct file still downloads correctly.
    """
    normalized = normalize_media_url(url)
    if not normalized:
        return False
    path = unquote(urlsplit(normalized).path or "").lower()
    return path.endswith(_MEDIA_EXTENSIONS)


def title_from_url(url) -> str:
    """Best-effort human title from a URL, for when metadata lookup fails.

    Used to name a downloaded file and to label playback, so it never returns
    an empty string: callers would otherwise write "None.mp4".
    """
    normalized = normalize_media_url(url)
    if not normalized:
        return "media"
    parts = urlsplit(normalized)
    name = os.path.basename(unquote(parts.path or "").rstrip("/"))
    stem = os.path.splitext(name)[0].strip()
    if stem:
        return re.sub(r"[_+]+", " ", stem).strip() or "media"
    # No usable path (e.g. "https://youtu.be/?v=ID"): fall back to the host.
    return (parts.hostname or "media").replace("www.", "") or "media"
