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
    def debug(self, message):
        LOG.debug("yt-dlp: %s", message)

    def info(self, message):
        LOG.debug("yt-dlp: %s", message)

    def warning(self, message):
        LOG.warning("yt-dlp: %s", message)

    def error(self, message):
        LOG.warning("yt-dlp: %s", message)


def extract_video_info(url: str, *, timeout: int = 20, include_comments: bool = True) -> dict:
    """Extract current YouTube metadata; comment extraction expands all public replies."""
    if not is_youtube_video_url(url):
        return {}
    import yt_dlp

    from core.discovery import youtube_player_client_list

    options = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": max(5, int(timeout or 20)),
        "retries": 2,
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
        "logger": _YtdlpLogger(),
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    return info if isinstance(info, dict) else {}


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
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
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
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        if text and (not entries or entries[-1][1] != text):
            entries.append((start, text))
    return entries


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
