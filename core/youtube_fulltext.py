# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Accessible YouTube descriptions, transcripts, comments, and chapters.

This module deliberately uses yt-dlp's maintained YouTube extractor instead of
scraping YouTube's progressively-hydrated HTML.  The regular page never contains
all replies or a complete subtitle track, so DOM extraction cannot satisfy the
full-text reader's completeness contract.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections import defaultdict
from urllib.parse import parse_qs, urlsplit

from core import utils


LOG = logging.getLogger(__name__)
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def video_id_from_url(url: str) -> str:
    """Return a strict YouTube video id, or an empty string for non-video URLs."""
    try:
        parsed = urlsplit(str(url or "").strip())
    except Exception:
        return ""
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return ""
    path = parsed.path or ""
    if host.endswith("youtu.be"):
        candidate = path.strip("/").split("/", 1)[0]
    elif path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    else:
        match = re.match(r"^/(?:shorts|embed|live)/([^/?#]+)", path)
        candidate = match.group(1) if match else ""
    candidate = str(candidate or "").strip()
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate) else ""


def is_youtube_video_url(url: str) -> bool:
    return bool(video_id_from_url(url))


class _YtdlpLogger:
    def __init__(self):
        self.incomplete_data = False

    def debug(self, message):
        LOG.debug("yt-dlp: %s", message)

    def info(self, message):
        LOG.debug("yt-dlp: %s", message)

    def warning(self, message):
        if "incomplete data received" in str(message or "").lower():
            self.incomplete_data = True
        LOG.warning("yt-dlp: %s", message)

    def error(self, message):
        LOG.warning("yt-dlp: %s", message)


# ponytail: fixed ceilings, not progress-aware. Comment-heavy videos ("all"
# comments) can take minutes; a hung CLI must still end eventually.
_CLI_TIMEOUT_WITH_COMMENTS_S = 900
_CLI_TIMEOUT_S = 120


def _extract_info_via_cli(extract_url: str, *, timeout: int, include_comments: bool):
    """Run one extraction in the yt-dlp CLI; ``None`` when no CLI can be launched.

    yt-dlp is pure Python: a video with a few hundred comments costs 2-5 s of
    CPU (measured). In-process that work holds the GIL, and every message
    NVDA sends the article list waits behind it, which is the arrowing lag
    on YouTube rows (selection triggers chapter and full-text loads). A child
    process does the same work without touching this interpreter.
    Returns ``(info, incomplete_comment_data)``; raises on a failed extraction.
    """
    import subprocess

    from core.dependency_check import _get_startup_info
    from core.discovery import _resolve_ytdlp_cli_path, youtube_player_client_arg

    extractor_args = youtube_player_client_arg()
    if include_comments:
        # Omitted max_comments values mean unlimited parents, replies,
        # per-thread replies and depth; spelled out so a future yt-dlp default
        # cannot silently collapse discussions.
        extractor_args += ";max_comments=all,all,all,all,all"
    cmd = [
        _resolve_ytdlp_cli_path(),
        "-J",
        "--ignore-config",
        # A watch URL carrying &list= must still resolve to the one video.
        "--no-playlist",
        "--skip-download",
        "--socket-timeout", str(max(5, int(timeout or 20))),
        "--retries", "2",
        "--extractor-retries", "6",
        "--extractor-args", extractor_args,
    ]
    if include_comments:
        cmd.append("--write-comments")
    cmd += ["--", extract_url]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=_get_startup_info(),
            timeout=_CLI_TIMEOUT_WITH_COMMENTS_S if include_comments else _CLI_TIMEOUT_S,
        )
    except OSError:
        return None
    errors = (result.stderr or b"").decode("utf-8", "replace")
    for line in errors.splitlines():
        if line.strip():
            LOG.debug("yt-dlp: %s", line)
    if result.returncode != 0:
        lines = [line.strip() for line in errors.splitlines() if line.strip()]
        raise RuntimeError(lines[-1] if lines else f"yt-dlp exited with code {result.returncode}")
    info = json.loads(result.stdout or b"{}")
    return (info if isinstance(info, dict) else {}), "incomplete data received" in errors.lower()


def _extract_info_in_process(extract_url: str, options: dict):
    import yt_dlp

    logger = _YtdlpLogger()
    with yt_dlp.YoutubeDL(dict(options, logger=logger)) as ydl:
        info = ydl.extract_info(extract_url, download=False)
    return info, logger.incomplete_data


def extract_video_info(url: str, *, timeout: int = 20, include_comments: bool = True) -> dict:
    """Extract current YouTube metadata; comment extraction expands all public replies."""
    if not is_youtube_video_url(url):
        return {}

    from core.discovery import (
        normalize_ytdlp_single_item_url,
        youtube_player_client_list,
    )

    extract_url = normalize_ytdlp_single_item_url(url)

    options = {
        "skip_download": True,
        "quiet": True,
        # A watch URL carrying &list= must still resolve to the one video; without
        # this yt-dlp routes to the playlist extractor and walks the whole list.
        "noplaylist": True,
        "no_warnings": True,
        "socket_timeout": max(5, int(timeout or 20)),
        "retries": 2,
        "extractor_retries": 6,
        "extractor_args": {
            "youtube": {
                "player_client": youtube_player_client_list(),
                # yt-dlp's omitted max_comments values mean unlimited parents,
                # replies, per-thread replies, and depth. Spell it out so a
                # future yt-dlp default cannot silently collapse discussions.
                "max_comments": ["all", "all", "all", "all", "all"],
            }
        },
        "getcomments": bool(include_comments),
    }

    def run():
        via_cli = _extract_info_via_cli(
            extract_url, timeout=timeout, include_comments=include_comments
        )
        if via_cli is not None:
            return via_cli
        # No runnable CLI (e.g. a source checkout without yt-dlp on PATH).
        return _extract_info_in_process(extract_url, options)

    info, incomplete = run()
    if not isinstance(info, dict):
        return {}

    # YouTube occasionally cuts off a comment continuation with "Incomplete
    # data received" while still returning a partial document. Retry the whole
    # extraction once and union comments by id so a transient failure does not
    # silently truncate the accessible discussion.
    if include_comments and incomplete:
        try:
            retry_info, incomplete = run()
            if isinstance(retry_info, dict):
                merged = []
                seen = set()
                for item in list(info.get("comments") or []) + list(retry_info.get("comments") or []):
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("id") or "").strip() or json.dumps(item, sort_keys=True, default=str)
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(item)
                retry_info["comments"] = merged
                info = retry_info
        except Exception:
            LOG.debug("YouTube comment completeness retry failed", exc_info=True)
        if incomplete:
            info["_blindrss_comments_incomplete"] = True
            LOG.warning(
                "YouTube returned an incomplete public-comment continuation after retry; "
                "preserving all comments received"
            )
    return info


def chapters_from_info(info: dict, url: str = "") -> list[dict]:
    video_id = str(info.get("id") or video_id_from_url(url) or "").strip()
    base_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else str(url or "")
    chapters = []
    for chapter in info.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        try:
            start = max(0.0, float(chapter.get("start_time") or 0))
        except (TypeError, ValueError):
            continue
        title = str(chapter.get("title") or "Chapter").strip() or "Chapter"
        separator = "&" if "?" in base_url else "?"
        chapters.append({"start": start, "title": title, "href": f"{base_url}{separator}t={int(start)}s"})
    return chapters


def _timestamp(seconds) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _subtitle_candidates(info: dict):
    """Yield one best subtitle track: authored before automatic, English first."""
    authored = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}

    def language_rank(language):
        low = str(language or "").lower()
        if low == "en":
            return 0
        if low.startswith("en-"):
            return 1
        if low.endswith("-orig"):
            return 2
        return 3

    candidates = []
    for tracks, kind_rank in ((authored, 0), (automatic, 1)):
        if not isinstance(tracks, dict):
            continue
        for language in tracks:
            formats = tracks.get(language) or []
            if not isinstance(formats, list):
                continue
            ranked = sorted(
                (item for item in formats if isinstance(item, dict) and item.get("url")),
                key=lambda item: 0 if item.get("ext") == "json3" else 1 if item.get("ext") == "vtt" else 2,
            )
            if ranked:
                lang_rank = language_rank(language)
                # Creator English, automatic English, creator other, automatic
                # other. This avoids choosing a creator Spanish track over an
                # available English automatic transcript for an English UI.
                english = lang_rank <= 1
                overall_rank = kind_rank if english else 2 + kind_rank
                candidates.append((overall_rank, lang_rank, str(language), kind_rank, ranked[0]))
    for _overall, _lang_rank, language, kind_rank, track in sorted(candidates):
        yield kind_rank, language, track


def _transcript_from_json3(payload: dict) -> list[tuple[float, str]]:
    entries = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict) or not event.get("segs"):
            continue
        text = "".join(str(seg.get("utf8") or "") for seg in event["segs"] if isinstance(seg, dict))
        text = _clean_subtitle_text(text)
        if not text or text == "[Music]" and entries and entries[-1][1] == text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000.0
        if entries and entries[-1][1] == text:
            continue
        entries.append((start, text))
    return entries


def _transcript_from_vtt(body: str) -> list[tuple[float, str]]:
    entries = []
    blocks = re.split(r"\r?\n\s*\r?\n", str(body or ""))
    cue_re = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s+-->")
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        cue_index = next((i for i, line in enumerate(lines) if cue_re.search(line)), -1)
        if cue_index < 0:
            continue
        match = cue_re.search(lines[cue_index])
        hours = int(match.group(1) or 0)
        start = hours * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + int(match.group(4)) / 1000
        text = " ".join(lines[cue_index + 1 :])
        text = re.sub(r"<[^>]+>", "", text)
        text = _clean_subtitle_text(text)
        if text and (not entries or entries[-1][1] != text):
            entries.append((start, text))
    return entries


def _clean_subtitle_text(value: str) -> str:
    """Normalize a cue and remove spoken WebVTT speaker chevrons.

    YouTube captions commonly prefix speaker changes with ``>>``.  Those are
    visual transcript markers rather than spoken content, and NVDA announces
    each character as "greater".  Strip only leading chevrons from subtitle
    cues; comparison operators and greater-than signs elsewhere are retained.
    """
    text = html.unescape(re.sub(r"\s+", " ", str(value or ""))).strip()
    return re.sub(r"^(?:>\s*)+(?=\S)", "", text).strip()


def transcript_from_info(info: dict, *, timeout: int = 20) -> tuple[str, list[tuple[float, str]]]:
    candidate = next(_subtitle_candidates(info), None)
    if not candidate:
        return "", []
    _kind, language, track = candidate
    try:
        response = utils.safe_requests_get(
            track["url"],
            timeout=max(5, int(timeout or 20)),
            headers=dict(info.get("http_headers") or {}),
        )
        response.raise_for_status()
        if track.get("ext") == "json3":
            entries = _transcript_from_json3(response.json())
        else:
            entries = _transcript_from_vtt(response.text)
        return str(language), entries
    except Exception:
        LOG.debug("YouTube subtitle download failed", exc_info=True)
        return str(language), []


def _comment_text(comment: dict) -> str:
    value = comment.get("text") or comment.get("html") or ""
    return html.unescape(re.sub(r"\s+", " ", str(value))).strip()


def format_comments(comments) -> list[str]:
    """Format a flat yt-dlp comment list as stable parent/reply subtrees."""
    normalized = [item for item in (comments or []) if isinstance(item, dict) and _comment_text(item)]
    by_parent = defaultdict(list)
    roots = []
    known_ids = {str(item.get("id") or "") for item in normalized}
    for index, item in enumerate(normalized):
        item = dict(item)
        item["_index"] = index
        parent = str(item.get("parent") or "root")
        if parent in {"", "root", "None"} or parent not in known_ids:
            roots.append(item)
        else:
            by_parent[parent].append(item)

    output = []
    seen = set()

    def append_tree(item, depth):
        comment_id = str(item.get("id") or f"index:{item['_index']}")
        if comment_id in seen:
            return
        seen.add(comment_id)
        author = str(item.get("author") or "Unknown author").strip()
        label = "Comment" if depth == 0 else f"Reply level {depth}"
        output.extend((f"{label} by {author}:", _comment_text(item)))
        for child in by_parent.get(str(item.get("id") or ""), []):
            append_tree(child, depth + 1)

    for root in roots:
        append_tree(root, 0)
    for item in normalized:
        append_tree(item, max(0, int(item.get("depth") or 0)))
    return output


def article_fields_from_info(info: dict, url: str, *, timeout: int = 20) -> dict:
    """Build the accessible full-text fields in the required reading order."""
    sections = []
    description = str(info.get("description") or "").strip()
    sections.extend(("Description", description or "No video description was provided."))

    chapters = chapters_from_info(info, url)
    sections.append("Chapters")
    if chapters:
        sections.extend(f"{_timestamp(item['start'])} {item['title']}" for item in chapters)
    else:
        sections.append("No chapters were provided.")

    language, transcript = transcript_from_info(info, timeout=timeout)
    sections.append(f"Subtitles ({language})" if language else "Subtitles")
    if transcript:
        # Subtitles are presented as continuous readable text. Timecodes add a
        # noisy announcement before every cue in screen readers; chapter
        # timestamps remain available separately for navigation.
        sections.extend(text for _start, text in transcript)
    else:
        sections.append("No subtitles were available.")

    sections.append("Comments")
    if info.get("_blindrss_comments_incomplete"):
        sections.append(
            "YouTube returned an incomplete comment page after retry; all comments received are shown below."
        )
    comment_lines = format_comments(info.get("comments"))
    sections.extend(comment_lines or ["No public comments were available."])
    return {
        "title": str(info.get("title") or "").strip(),
        "author": str(info.get("channel") or info.get("uploader") or "").strip(),
        "text": "\n\n".join(str(item).strip() for item in sections if str(item).strip()),
        "chapters": chapters,
    }


def extract_article(url: str, *, timeout: int = 20) -> dict:
    info = extract_video_info(url, timeout=timeout, include_comments=True)
    return article_fields_from_info(info, url, timeout=timeout) if info else {}


def extract_chapters(url: str, *, timeout: int = 20) -> list[dict]:
    info = extract_video_info(url, timeout=timeout, include_comments=False)
    return chapters_from_info(info, url) if info else []
