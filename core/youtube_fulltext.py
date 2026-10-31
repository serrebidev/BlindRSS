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
import os
import re
import signal
import subprocess
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
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

# Chapters live in the watch page's initial data, so a chapters-only lookup
# can skip the player JavaScript (the deno signature challenge) and the
# DASH/HLS manifests. Measured: same chapters, about 30% faster.
_CHAPTERS_ONLY_EXTRACTOR_ARGS = ";player_skip=js;skip=dash,hls,translated_subs"


class ExtractionCancelled(Exception):
    """The caller no longer wants this extraction (the user moved on)."""


_cancel_state = threading.local()


@contextmanager
def cancel_when(check):
    """Kill yt-dlp CLI work started in this thread once ``check()`` is true.

    Arrowing over YouTube rows starts a chapter lookup and a full-text load for
    each row the user pauses on; without this, every abandoned row kept its
    yt-dlp process running to the end.
    """
    previous = getattr(_cancel_state, "check", None)
    _cancel_state.check = check
    try:
        yield
    finally:
        _cancel_state.check = previous


def _cancel_requested() -> bool:
    check = getattr(_cancel_state, "check", None)
    try:
        return bool(check is not None and check())
    except Exception:
        return False


def _kill_process_tree(proc) -> None:
    # yt-dlp release binaries are PyInstaller one-file executables: the process
    # we started is a bootloader whose child does the work, so kill the tree.
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
        proc.communicate(timeout=5)
    except Exception:
        pass


def _extract_info_via_cli(
    extract_url: str, *, timeout: int, include_comments: bool, chapters_only: bool = False
):
    """Run one extraction in the yt-dlp CLI; ``None`` when no CLI can be launched.

    yt-dlp is pure Python: a video with a few hundred comments costs 2-5 s of
    CPU (measured). In-process that work holds the GIL, and every message
    NVDA sends the article list waits behind it, which is the arrowing lag
    on YouTube rows (selection triggers chapter and full-text loads). A child
    process does the same work without touching this interpreter.
    Returns ``(info, incomplete_comment_data)``; raises on a failed extraction
    and ``ExtractionCancelled`` when the thread's ``cancel_when`` check fires.
    """
    from core.dependency_check import _get_startup_info
    from core.discovery import _resolve_ytdlp_cli_path, youtube_player_client_arg

    if _cancel_requested():
        raise ExtractionCancelled()
    extractor_args = youtube_player_client_arg()
    if include_comments:
        # Omitted max_comments values mean unlimited parents, replies,
        # per-thread replies and depth; spelled out so a future yt-dlp default
        # cannot silently collapse discussions.
        extractor_args += ";max_comments=all,all,all,all,all"
    elif chapters_only:
        extractor_args += _CHAPTERS_ONLY_EXTRACTOR_ARGS
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
    elif chapters_only:
        cmd.append("--ignore-no-formats-error")
    cmd += ["--", extract_url]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=_get_startup_info(),
            start_new_session=(os.name != "nt"),
        )
    except OSError:
        return None
    deadline = time.monotonic() + (
        _CLI_TIMEOUT_WITH_COMMENTS_S if include_comments else _CLI_TIMEOUT_S
    )
    while True:
        try:
            # Retrying communicate() after a timeout loses no output.
            stdout, stderr = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if _cancel_requested():
                _kill_process_tree(proc)
                raise ExtractionCancelled() from None
            if time.monotonic() > deadline:
                _kill_process_tree(proc)
                raise TimeoutError("yt-dlp did not finish in time") from None
    errors = (stderr or b"").decode("utf-8", "replace")
    for line in errors.splitlines():
        if line.strip():
            LOG.debug("yt-dlp: %s", line)
    if proc.returncode != 0:
        lines = [line.strip() for line in errors.splitlines() if line.strip()]
        raise RuntimeError(lines[-1] if lines else f"yt-dlp exited with code {proc.returncode}")
    info = json.loads(stdout or b"{}")
    return (info if isinstance(info, dict) else {}), "incomplete data received" in errors.lower()


def _extract_info_in_process(extract_url: str, options: dict):
    import yt_dlp

    logger = _YtdlpLogger()
    with yt_dlp.YoutubeDL(dict(options, logger=logger)) as ydl:
        info = ydl.extract_info(extract_url, download=False)
    return info, logger.incomplete_data


def extract_video_info(
    url: str, *, timeout: int = 20, include_comments: bool = True, chapters_only: bool = False
) -> dict:
    """Extract current YouTube metadata; comment extraction expands all public replies.

    ``chapters_only`` (without comments) skips player and stream data that
    chapters do not need; the result has no usable formats.
    """
    if not is_youtube_video_url(url):
        return {}
    chapters_only = bool(chapters_only and not include_comments)

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
    if chapters_only:
        options["extractor_args"]["youtube"].update(
            {"player_skip": ["js"], "skip": ["dash", "hls", "translated_subs"]}
        )
        options["ignore_no_formats_error"] = True

    def run():
        via_cli = _extract_info_via_cli(
            extract_url,
            timeout=timeout,
            include_comments=include_comments,
            chapters_only=chapters_only,
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
        except ExtractionCancelled:
            raise
        except Exception:
            LOG.debug("YouTube comment completeness retry failed", exc_info=True)
        if incomplete:
            info["_blindrss_comments_incomplete"] = True
            LOG.warning(
                "YouTube returned an incomplete public-comment continuation after retry; "
                "preserving all comments received"
            )
    _remember_chapters(url, info)
    return info


# Chapters seen by any recent extraction (full text included), so revisiting a
# row or opening the player does not launch yt-dlp again. Expires so chapters
# an uploader adds later are still picked up.
_CHAPTER_MEMO_TTL_S = 30 * 60
_chapter_memo = utils.LRUDict(512)


def _remember_chapters(url: str, info: dict) -> None:
    video_id = str(info.get("id") or video_id_from_url(url) or "").strip()
    if video_id:
        _chapter_memo[video_id] = (time.monotonic(), chapters_from_info(info, url))


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


# YouTube labels Chinese tracks by script; a UI locale's region implies it.
_ZH_SCRIPT_FOR_REGION = {
    "zh-tw": "zh-hant", "zh-hk": "zh-hant", "zh-mo": "zh-hant", "zh-cn": "zh-hans", "zh-sg": "zh-hans",
}


def _language_match(code, wanted):
    """How well subtitle language ``code`` fits ``wanted``: 0 same tag, 1 same
    script, 2 the bare base language, 3 another variant of it; None otherwise."""
    code = str(code or "").lower().replace("_", "-").removesuffix("-orig")
    wanted = str(wanted or "").lower().replace("_", "-")
    if not code or not wanted:
        return None
    if code == wanted:
        return 0
    if code == _ZH_SCRIPT_FOR_REGION.get(wanted):
        return 1
    base = wanted.split("-")[0]
    if code == base:
        return 2
    return 3 if code.split("-")[0] == base else None


def _track_translation(track) -> str:
    """Language YouTube machine-translates ``track`` into ("" when it does not)."""
    return (parse_qs(urlsplit(str(track.get("url") or "")).query).get("tlang") or [""])[0]


def _subtitle_candidates(info: dict):
    """Yield subtitle tracks best first.

    An untranslated track in the UI language (closest tag first), untranslated
    English, YouTube's machine translation into the UI language, the video's
    original language, then other authored tracks; authored before automatic
    within each step. Translations into any other language are never offered.
    """
    from core.article_lang import app_ui_language

    authored = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    ui = app_ui_language()
    original = ""
    if isinstance(automatic, dict):
        original = next((str(key)[:-5] for key in automatic if str(key).endswith("-orig")), "")

    candidates = []
    for tracks, kind_rank in ((authored, 0), (automatic, 1)):
        if not isinstance(tracks, dict):
            continue
        for language in tracks:
            formats = tracks.get(language) or []
            if not isinstance(formats, list):
                continue
            # A format with a "protocol" is no subtitle file: a livestream
            # replay's "live_chat" entry points at the watch page (no cues).
            ranked = sorted(
                (
                    item for item in formats
                    if isinstance(item, dict) and item.get("url") and not item.get("protocol")
                ),
                key=lambda item: 0 if item.get("ext") == "json3" else 1 if item.get("ext") == "vtt" else 2,
            )
            if not ranked:
                continue
            # Creator before automatic within each step keeps the old rule that a
            # creator Spanish track never beats English captions for an English
            # UI. YouTube may rate-limit machine translations (tlang=, HTTP 429),
            # so only a translation into the UI language is offered; it still
            # beats the original, which may be in a language the reader does not know.
            translation = _track_translation(ranked[0])
            if translation:
                match = _language_match(translation, ui)
                if match is None:
                    continue
                rank = (2, match)
            elif (match := _language_match(language, ui)) is not None:
                rank = (0, match)
            elif (match := _language_match(language, "en")) is not None:
                rank = (1, match)
            else:
                rank = (3 if _language_match(language, original) is not None else 4, 0)
            candidates.append((rank, kind_rank, str(language), ranked[0]))
    for _rank, kind_rank, language, track in sorted(candidates):
        # "pl-orig" names the spoken-language track; the heading says just "pl".
        yield kind_rank, language.removesuffix("-orig"), track


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
    first_language = ""
    tried = set()
    for kind, language, track in _subtitle_candidates(info):
        if track["url"] in tried:
            continue  # "pl-orig" and "pl" are the same track
        if len(tried) == 2:
            break
        if _cancel_requested():
            raise ExtractionCancelled()
        tried.add(track["url"])
        first_language = first_language or str(language)
        translation = _track_translation(track)
        # Never the URL or its other query parameters (signed).
        LOG.debug(
            "YouTube subtitle attempt %d: %s (%s)%s",
            len(tried),
            language,
            "auto" if kind else "manual",
            f", translated to {translation}" if translation else "",
        )
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
        except Exception as exc:
            # Type and HTTP status only: the error text carries the signed URL.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            LOG.debug("YouTube subtitle download failed (%s): %s %s", language, type(exc).__name__, status or "")
            if status == 429 and not translation:
                break  # rate-limited on the plain track: another request would be too
    return first_language, []


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


_INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/{}?prettyPrint=false"
# ponytail: pinned WEB client version; YouTube accepts old versions for years.
# Bump it if watch-next starts refusing requests (the CLI fallback covers it).
_INNERTUBE_CLIENT = {"clientName": "WEB", "clientVersion": "2.20251010.01.00", "hl": "en"}
# yt-dlp's description-chapter grammar (common._extract_chapters_from_description).
_DESCRIPTION_DURATION_RE = r"(?:\d+:)?\d{1,2}:\d{2}"
_DESCRIPTION_LINE_RE = r"(?m)^\s*({})\b\W*\s({})\s*$"
_http_local = threading.local()


def _find_values(node, key: str, out: list) -> list:
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                out.append(value)
            else:
                _find_values(value, key, out)
    elif isinstance(node, list):
        for value in node:
            _find_values(value, key, out)
    return out


def _runs_text(node) -> str:
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return str(node.get("simpleText") or "")
    return "".join(str(run.get("text") or "") for run in node.get("runs") or [] if isinstance(run, dict))


def _parse_clock(text) -> float | None:
    parts = str(text or "").strip().split(":")
    try:
        if not 1 <= len(parts) <= 3:
            return None
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    except ValueError:
        return None


def _innertube(endpoint: str, video_id: str, timeout: int):
    """One InnerTube JSON call (WEB client) on this thread's kept-alive session."""
    import requests

    session = getattr(_http_local, "session", None)
    if session is None:
        session = _http_local.session = requests.Session()
    response = session.post(
        _INNERTUBE_URL.format(endpoint),
        json={"context": {"client": _INNERTUBE_CLIENT}, "videoId": video_id},
        headers={
            "User-Agent": utils.HEADERS.get("User-Agent", ""),
            "Origin": "https://www.youtube.com",
        },
        timeout=max(3, min(int(timeout or 10), 15)),
    )
    if response.status_code != 200:
        return None
    data = response.json()
    return data if isinstance(data, dict) else None


def _valid_chapters(pairs, duration):
    """yt-dlp's _extract_chapters_helper: ordered starts within the video."""
    out = []
    last = 0.0
    for start, title in pairs:
        if start is None:
            continue
        if last <= start and (duration is None or start <= duration):
            out.append((start, title))
            last = start
    return out


def _chapters_from_watch_next(video_id: str, *, timeout: int):
    """Chapters without yt-dlp: one watch-next request, about 0.7 s.

    The yt-dlp CLI needs 3-4 s for the same answer (process start plus player
    requests). Mirrors yt-dlp's three sources in its order: player-bar chapter
    markers, the "key moments" panel, then timestamps in the description
    (validated against the length from one extra ``player`` request, only
    when the description has timestamps). Returns ``None`` when YouTube's
    responses cannot settle it, so the caller falls back to yt-dlp.
    """
    data = _innertube("next", video_id, timeout)
    if not data or "contents" not in data:
        return None

    pairs = []
    overlays = data.get("playerOverlays") or {}
    lists = _find_values(overlays, "chapteredPlayerBarRenderer", [])
    by_key = {}
    for markers_map in _find_values(overlays, "markersMap", []):
        for entry in markers_map if isinstance(markers_map, list) else []:
            if isinstance(entry, dict) and (entry.get("value") or {}).get("chapters"):
                by_key.setdefault(str(entry.get("key") or ""), entry["value"])
    candidates = [*lists, by_key.get("DESCRIPTION_CHAPTERS"), by_key.get("AUTO_CHAPTERS"), *by_key.values()]
    for candidate in candidates:
        chapters = (candidate or {}).get("chapters") if isinstance(candidate, dict) else None
        for chapter in chapters or []:
            renderer = chapter.get("chapterRenderer") if isinstance(chapter, dict) else None
            if not isinstance(renderer, dict):
                continue
            try:
                start = int(renderer.get("timeRangeStartMillis") or 0) / 1000.0
            except (TypeError, ValueError):
                start = None
            pairs.append((start, _runs_text(renderer.get("title"))))
        if pairs:
            break
    chapters = _valid_chapters(pairs, None)

    if not chapters:
        for contents in _find_values(data.get("engagementPanels") or [], "macroMarkersListRenderer", []):
            items = _find_values((contents or {}).get("contents") or [], "macroMarkersListItemRenderer", [])
            chapters = _valid_chapters(
                [(_parse_clock(_runs_text(i.get("timeDescription"))), _runs_text(i.get("title"))) for i in items],
                None,
            )
            if chapters:
                break

    if not chapters:
        descriptions = _find_values(data, "attributedDescription", [])
        text = "\n".join(str(d.get("content") or "") for d in descriptions if isinstance(d, dict))
        time_first = re.findall(_DESCRIPTION_LINE_RE.format(_DESCRIPTION_DURATION_RE, r".+?"), text)
        title_first = re.findall(_DESCRIPTION_LINE_RE.format(r".+?", _DESCRIPTION_DURATION_RE), text)
        if not time_first and not title_first:
            return []
        player = _innertube("player", video_id, timeout)
        details = (player or {}).get("videoDetails") or {}
        try:
            duration = float(details.get("lengthSeconds") or 0)
        except (TypeError, ValueError):
            duration = 0
        if not duration:
            return None
        text = str(details.get("shortDescription") or text)
        for found, clock_index in (
            (re.findall(_DESCRIPTION_LINE_RE.format(_DESCRIPTION_DURATION_RE, r".+?"), text), 0),
            (re.findall(_DESCRIPTION_LINE_RE.format(r".+?", _DESCRIPTION_DURATION_RE), text), 1),
        ):
            pairs = sorted(
                ((_parse_clock(m[clock_index]), m[1 - clock_index]) for m in found),
                key=lambda pair: pair[0] or 0,
            )
            chapters = _valid_chapters(pairs, duration)
            if chapters:
                break

    if chapters and chapters[0][0] > 0:
        # yt-dlp's YoutubeDL fills the gap before a late first chapter the same way.
        chapters.insert(0, (0.0, "<Untitled Chapter 1>"))
    base_url = f"https://www.youtube.com/watch?v={video_id}"
    return [
        {"start": max(0.0, start), "title": str(title or "").strip() or "Chapter",
         "href": f"{base_url}&t={int(start)}s"}
        for start, title in chapters
    ]


def extract_chapters(url: str, *, timeout: int = 20) -> list[dict]:
    video_id = video_id_from_url(url)
    if not video_id:
        return []
    remembered = _chapter_memo.get(video_id)
    if remembered and time.monotonic() - remembered[0] < _CHAPTER_MEMO_TTL_S:
        return list(remembered[1])
    if _cancel_requested():
        raise ExtractionCancelled()
    try:
        chapters = _chapters_from_watch_next(video_id, timeout=timeout)
    except Exception:
        LOG.debug("YouTube watch-next chapter lookup failed for %s", video_id, exc_info=True)
        chapters = None
    if chapters is not None:
        _chapter_memo[video_id] = (time.monotonic(), chapters)
        return list(chapters)
    info = extract_video_info(url, timeout=timeout, include_comments=False, chapters_only=True)
    return chapters_from_info(info, url) if info else []
