# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Recover podcast episodes from historical RSS snapshots in the Wayback Machine.

The scanner is GUI-free.  LocalProvider uses it in a refresh worker and appends
the recovered entries to the ordinary parsed feed, so archived episodes become
normal BlindRSS articles rather than a separate library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import queue
import re
import threading
import time
from typing import Callable, Iterable, Sequence
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import feedparser

from core import utils


log = logging.getLogger(__name__)

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PREFIX = "https://web.archive.org/web"
DEFAULT_MAX_SNAPSHOTS = 5000
MAX_FEED_LINEAGE = 12
MAX_FEED_BYTES = 10 * 1024 * 1024
_ARCHIVE_TIMEOUT = (10, 45)

# Keep automatic recovery polite across the whole process.  A refresh may have
# dozens of feed workers, but archive.org should see only one history walk at a
# time.  The lock is acquired non-blocking by LocalProvider; feeds which miss a
# turn remain due and are picked up by a later refresh.
AUTOMATIC_SCAN_LOCK = threading.Lock()
_JOB_QUEUE: queue.Queue = queue.Queue()
_JOB_WORKER_LOCK = threading.Lock()
_JOB_WORKER_STARTED = False

_WAYBACK_URL_RE = re.compile(
    r"^https?://web\.archive\.org/web/\d{1,14}(?:[a-z]{2}_)?/(https?://.+)$",
    re.IGNORECASE,
)
_TRACKING_QUERY_NAMES = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
}
_VOLATILE_MEDIA_QUERY_NAMES = {
    "expires", "key-pair-id", "policy", "signature", "sig", "token",
    "x-amz-algorithm", "x-amz-credential", "x-amz-date", "x-amz-expires",
    "x-amz-security-token", "x-amz-signature", "x-amz-signedheaders",
}
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
_AUDIO_EXTENSIONS = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac")
_VIDEO_EXTENSIONS = (".mp4", ".m4v", ".webm", ".mkv", ".mov")


class PodcastArchiveError(RuntimeError):
    """A user-safe archive discovery failure."""


def enqueue_archive_job(job: Callable[[], None]) -> None:
    """Run archive jobs serially on one daemon without delaying feed refresh."""
    global _JOB_WORKER_STARTED
    with _JOB_WORKER_LOCK:
        if not _JOB_WORKER_STARTED:
            worker = threading.Thread(
                target=_archive_job_worker,
                name="PodcastArchiveWorker",
                daemon=True,
            )
            worker.start()
            _JOB_WORKER_STARTED = True
    _JOB_QUEUE.put(job)


def _archive_job_worker() -> None:
    while True:
        job = _JOB_QUEUE.get()
        try:
            job()
        except Exception:
            log.exception("Unhandled podcast archive background-job failure")
        finally:
            _JOB_QUEUE.task_done()


@dataclass
class ArchiveEpisode:
    title: str
    page_url: str = ""
    media_url: str = ""
    media_type: str = ""
    published: str = ""
    author: str = ""
    description: str = ""
    guid: str = ""
    duration: str = ""
    source_feed_url: str = ""
    snapshot_timestamp: str = ""
    identity_keys: set[str] = field(default_factory=set, repr=False)

    @property
    def stable_id(self) -> str:
        seed = self.guid or self.media_url or self.page_url
        if not seed:
            seed = "|".join((self.title, self.published, self.duration))
        return "podcast-archive:" + sha256(seed.encode("utf-8", "replace")).hexdigest()

    def as_feedparser_entry(self):
        """Return the subset of FeedParserDict consumed by LocalProvider."""
        entry = feedparser.FeedParserDict()
        entry["id"] = self.guid or self.stable_id
        entry["guid"] = self.guid or self.stable_id
        entry["title"] = self.title or "Untitled episode"
        entry["link"] = self.page_url or self.media_url
        entry["summary"] = self.description
        entry["author"] = self.author
        # LocalProvider still applies filters and stores the article unread, but
        # it must not announce years of recovered history as brand-new episodes.
        entry["blindrss_archive_recovered"] = True
        if self.published and not self.published.startswith("0001-"):
            entry["published"] = self.published
        if self.duration:
            entry["itunes_duration"] = self.duration
        if self.media_url:
            enclosure = feedparser.FeedParserDict()
            enclosure["href"] = self.media_url
            enclosure["type"] = self.media_type or _media_type_from_url(self.media_url)
            entry["enclosures"] = [enclosure]
            entry["links"] = [
                feedparser.FeedParserDict(
                    href=self.media_url,
                    rel="enclosure",
                    type=enclosure["type"],
                )
            ]
        return entry


@dataclass
class PodcastArchiveResult:
    feed_title: str = ""
    episodes: list[ArchiveEpisode] = field(default_factory=list)
    feed_urls: list[str] = field(default_factory=list)
    snapshots_found: int = 0
    snapshots_loaded: int = 0
    failed_snapshots: int = 0
    truncated: bool = False
    canceled: bool = False
    warnings: list[str] = field(default_factory=list)


def _public_http_url(url: str, *, purpose: str = "podcast feed") -> str:
    value = str(url or "").strip()
    utils._validated_public_http_url(value, purpose=purpose)
    return value


def _unwrap_wayback_url(url: str) -> str:
    value = str(url or "").strip()
    match = _WAYBACK_URL_RE.match(value)
    return match.group(1) if match else value


def canonical_url(url: str, *, media: bool = False) -> str:
    """Canonical identity URL; it is never used as the request destination."""
    value = _unwrap_wayback_url(url)
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return value.strip()
        host = parts.hostname.lower().rstrip(".")
        port = parts.port
        netloc = host
        if ":" in host and not host.startswith("["):
            netloc = f"[{host}]"
        if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
            netloc += f":{port}"
        path = re.sub(r"/{2,}", "/", parts.path or "/")
        if not media and path != "/":
            path = path.rstrip("/")
        kept = []
        for key, val in parse_qsl(parts.query, keep_blank_values=True):
            low = key.lower()
            if low.startswith("utm_") or low in _TRACKING_QUERY_NAMES:
                continue
            if media and low in _VOLATILE_MEDIA_QUERY_NAMES:
                continue
            kept.append((key, val))
        query = urlencode(sorted(kept))
        return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    except Exception:
        return value.strip()


def _normal_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _published_day(value: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return match.group(1) if match and not match.group(1).startswith("0001-") else ""


def _episode_identity_keys(episode: ArchiveEpisode) -> set[str]:
    keys: set[str] = set()
    guid = str(episode.guid or "").strip()
    if guid:
        if "://" in guid:
            guid = canonical_url(guid)
        keys.add("guid:" + guid.casefold())
    if episode.media_url:
        keys.add("media:" + canonical_url(episode.media_url, media=True))
    if episode.page_url:
        keys.add("page:" + canonical_url(episode.page_url))
    title = _normal_text(episode.title)
    day = _published_day(episode.published)
    if title and day:
        keys.add(f"title-date:{title}|{day}")
    elif title and episode.duration:
        keys.add(f"title-duration:{title}|{episode.duration}")
    return {key for key in keys if key.rsplit(":", 1)[-1]}


def _media_type_from_url(url: str) -> str:
    path = urlsplit(str(url or "")).path.lower()
    if path.endswith((".m4a", ".m4b")):
        return "audio/mp4"
    if path.endswith(".mp3"):
        return "audio/mpeg"
    if path.endswith(".aac"):
        return "audio/aac"
    if path.endswith((".ogg", ".opus")):
        return "audio/ogg"
    if path.endswith(".wav"):
        return "audio/wav"
    if path.endswith(".flac"):
        return "audio/flac"
    if path.endswith((".mp4", ".m4v")):
        return "video/mp4"
    if path.endswith(".webm"):
        return "video/webm"
    return "audio/mpeg"


def _entry_text(entry, *names: str) -> str:
    for name in names:
        value = entry.get(name)
        if isinstance(value, dict):
            value = value.get("value")
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _entry_content(entry) -> str:
    content = entry.get("content") or []
    if isinstance(content, list):
        for item in content:
            value = item.get("value") if isinstance(item, dict) else getattr(item, "value", "")
            if value:
                return str(value)
    return _entry_text(entry, "summary", "description")


def _entry_media(entry, feed_url: str) -> tuple[str, str]:
    candidates = []
    for enclosure in entry.get("enclosures") or []:
        candidates.append((
            enclosure.get("href") or enclosure.get("url"),
            enclosure.get("type") or "",
        ))
    for link in entry.get("links") or []:
        if str(link.get("rel") or "").lower() == "enclosure":
            candidates.append((link.get("href"), link.get("type") or ""))
    for media in entry.get("media_content") or []:
        candidates.append((media.get("url"), media.get("type") or ""))

    fallback = ("", "")
    for raw_url, raw_type in candidates:
        media_url = urljoin(feed_url, str(raw_url or "").strip())
        if not media_url:
            continue
        media_type = utils.canonical_media_type(raw_type) or str(raw_type or "")
        path = urlsplit(media_url).path.lower()
        if media_type.startswith("image/") or path.endswith(_IMAGE_EXTENSIONS):
            continue
        if utils.media_type_is_audio_video_or_podcast(media_type) or path.endswith(_AUDIO_EXTENSIONS + _VIDEO_EXTENSIONS):
            return media_url, media_type or _media_type_from_url(media_url)
        if not fallback[0]:
            fallback = (media_url, media_type)
    return fallback


def _feed_lineage_urls(document: bytes | str, parsed, source_url: str) -> list[str]:
    found = []

    def add(value):
        candidate = urljoin(source_url, str(value or "").strip())
        if not candidate or candidate == source_url:
            return
        try:
            candidate = _public_http_url(candidate)
        except ValueError:
            return
        if candidate not in found:
            found.append(candidate)

    feed = getattr(parsed, "feed", {}) or {}
    for key in ("itunes_new-feed-url", "itunes_new_feed_url", "new-feed-url", "new_feed_url"):
        add(feed.get(key))
    for link in feed.get("links") or []:
        if str(link.get("rel") or "").lower() == "self":
            add(link.get("href"))

    raw = document.encode("utf-8", "replace") if isinstance(document, str) else bytes(document or b"")
    if len(raw) > MAX_FEED_BYTES:
        return found
    try:
        root = ET.fromstring(raw)
        for element in root.iter():
            name = str(element.tag or "").rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()
            if name == "new-feed-url":
                add("".join(element.itertext()).strip())
            elif name == "link" and str(element.attrib.get("rel") or "").lower() == "self":
                add(element.attrib.get("href"))
    except (ET.ParseError, ValueError):
        pass
    return found


def parse_feed_document(
    document: bytes | str,
    source_url: str,
    *,
    snapshot_timestamp: str = "",
) -> tuple[str, list[ArchiveEpisode], list[str]]:
    raw = document.encode("utf-8", "replace") if isinstance(document, str) else bytes(document or b"")
    if not raw or len(raw) > MAX_FEED_BYTES:
        return "", [], []
    parsed = feedparser.parse(raw)
    feed_title = str((getattr(parsed, "feed", {}) or {}).get("title") or "").strip()
    episodes = []
    for entry in getattr(parsed, "entries", []) or []:
        page_url = urljoin(source_url, _entry_text(entry, "link"))
        media_url, media_type = _entry_media(entry, source_url)
        content = _entry_content(entry)
        title = _entry_text(entry, "title") or "Untitled episode"
        raw_date = _entry_text(entry, "published", "updated", "created", "date")
        published = utils.normalize_date(raw_date, title, content, page_url)
        episode = ArchiveEpisode(
            title=title,
            page_url=page_url,
            media_url=media_url,
            media_type=media_type,
            published=published,
            author=_entry_text(entry, "author", "itunes_author"),
            description=content,
            guid=_entry_text(entry, "id", "guid"),
            duration=_entry_text(entry, "itunes_duration", "duration"),
            source_feed_url=source_url,
            snapshot_timestamp=snapshot_timestamp,
        )
        episode.identity_keys = _episode_identity_keys(episode)
        if episode.identity_keys:
            episodes.append(episode)
    return feed_title, episodes, _feed_lineage_urls(raw, parsed, source_url)


def feed_has_podcast_media(parsed_feed) -> bool:
    """True when a parsed feed carries at least one playable enclosure."""
    for entry in getattr(parsed_feed, "entries", []) or []:
        media_url, _media_type = _entry_media(entry, "")
        if media_url:
            return True
    return False


def _merge_episode(preferred: ArchiveEpisode, other: ArchiveEpisode) -> None:
    """Fill gaps without replacing newer/current-feed metadata."""
    for attr in (
        "title", "page_url", "media_url", "media_type", "published", "author",
        "description", "guid", "duration", "source_feed_url", "snapshot_timestamp",
    ):
        current = getattr(preferred, attr)
        incoming = getattr(other, attr)
        if (not current or (attr == "published" and str(current).startswith("0001-"))) and incoming:
            setattr(preferred, attr, incoming)
    preferred.identity_keys.update(other.identity_keys)
    preferred.identity_keys.update(_episode_identity_keys(preferred))


def deduplicate_episodes(episodes: Iterable[ArchiveEpisode]) -> list[ArchiveEpisode]:
    kept: list[ArchiveEpisode] = []
    by_key: dict[str, ArchiveEpisode] = {}
    for episode in episodes:
        keys = episode.identity_keys or _episode_identity_keys(episode)
        matches = []
        for key in keys:
            match = by_key.get(key)
            if match is not None and match not in matches:
                matches.append(match)
        if not matches:
            episode.identity_keys = set(keys)
            kept.append(episode)
            target = episode
        else:
            target = matches[0]
            _merge_episode(target, episode)
            # If two previously separate rows are bridged by a stronger key,
            # fold both into the first rather than leaving a hidden duplicate.
            for duplicate in matches[1:]:
                _merge_episode(target, duplicate)
                if duplicate in kept:
                    kept.remove(duplicate)
        for key in target.identity_keys:
            by_key[key] = target
    return kept


def _cdx_request_url(feed_url: str, max_snapshots: int) -> str:
    params = [
        ("url", feed_url),
        ("output", "json"),
        ("fl", "timestamp,original,digest,statuscode,mimetype"),
        ("filter", "statuscode:200"),
        ("collapse", "digest"),
        ("limit", str(max(1, int(max_snapshots)) + 1)),
    ]
    return CDX_ENDPOINT + "?" + urlencode(params)


def _parse_cdx_rows(payload, max_snapshots: int) -> tuple[list[tuple[str, str]], bool]:
    if not isinstance(payload, list) or not payload:
        return [], False
    header = payload[0]
    if not isinstance(header, list):
        return [], False
    columns = {str(name): idx for idx, name in enumerate(header)}
    if "timestamp" not in columns or "original" not in columns:
        return [], False
    rows = []
    seen = set()
    for raw in payload[1:]:
        if not isinstance(raw, list):
            continue
        try:
            timestamp = str(raw[columns["timestamp"]] or "")
            original = str(raw[columns["original"]] or "")
        except (IndexError, TypeError):
            continue
        key = (timestamp, original)
        if not re.fullmatch(r"\d{1,14}", timestamp) or not original or key in seen:
            continue
        seen.add(key)
        rows.append(key)
    rows.sort(reverse=True)
    truncated = len(rows) > max_snapshots
    return rows[:max_snapshots], truncated


def list_snapshots(
    feed_url: str,
    *,
    max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    fetcher: Callable = utils.safe_requests_get,
) -> tuple[list[tuple[str, str]], bool]:
    feed_url = _public_http_url(feed_url)
    response = _fetch_with_retry(
        fetcher,
        _cdx_request_url(feed_url, max_snapshots),
        timeout=_ARCHIVE_TIMEOUT,
        site_cookies=False,
    )
    try:
        response.raise_for_status()
    except Exception as exc:
        raise PodcastArchiveError(
            f"The Wayback Machine snapshot index returned {getattr(response, 'status_code', 'an error')}."
        ) from exc
    try:
        payload = response.json()
    except Exception as exc:
        raise PodcastArchiveError("The Wayback Machine returned an unreadable snapshot index.") from exc
    return _parse_cdx_rows(payload, max(1, int(max_snapshots)))


def _snapshot_url(timestamp: str, original_url: str) -> str:
    return f"{WAYBACK_PREFIX}/{timestamp}id_/{original_url}"


def _response_bytes(response) -> bytes:
    content = bytes(getattr(response, "content", b"") or b"")
    if len(content) > MAX_FEED_BYTES:
        raise PodcastArchiveError("An archived feed snapshot was unexpectedly large.")
    return content


def _fetch_with_retry(fetcher: Callable, url: str, *, cancel_event=None, **kwargs):
    """Bounded retry for Archive.org's transient 429/5xx responses."""
    last_error = None
    for attempt in range(3):
        if cancel_event is not None and cancel_event.is_set():
            raise PodcastArchiveError("Podcast archive scan canceled.")
        try:
            response = fetcher(url, **kwargs)
            status = int(getattr(response, "status_code", 0) or 0)
            if status not in {429, 500, 502, 503, 504}:
                return response
            last_error = PodcastArchiveError(f"Archive.org returned HTTP {status}.")
        except Exception as exc:
            last_error = exc
            response = None
        if attempt < 2:
            delay = float(2 ** attempt)
            if cancel_event is not None and cancel_event.wait(delay):
                raise PodcastArchiveError("Podcast archive scan canceled.")
            if cancel_event is None:
                time.sleep(delay)
    if last_error:
        raise last_error
    return response


def scan_podcast_archive(
    feed_urls: str | Sequence[str],
    *,
    current_document: bytes | str | None = None,
    max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    include_without_media: bool = False,
    fetcher: Callable = utils.safe_requests_get,
    cancel_event: threading.Event | None = None,
    progress: Callable[[dict], None] | None = None,
) -> PodcastArchiveResult:
    """Recover and deduplicate a podcast's current and archived entries.

    Feed migrations advertised by ``itunes:new-feed-url``, Atom ``rel=self``,
    or an HTTP redirect are followed with a strict lineage cap.  Current entries
    are processed first, so their metadata wins over older snapshots.
    """
    if isinstance(feed_urls, str):
        seed_urls = [line.strip() for line in feed_urls.splitlines() if line.strip()]
    else:
        seed_urls = [str(value or "").strip() for value in feed_urls if str(value or "").strip()]
    if not seed_urls:
        raise PodcastArchiveError("Enter a podcast feed URL.")
    max_snapshots = max(1, min(DEFAULT_MAX_SNAPSHOTS, int(max_snapshots or DEFAULT_MAX_SNAPSHOTS)))

    result = PodcastArchiveResult()
    pending = []
    seen_feed_keys = set()
    for value in seed_urls:
        clean = _public_http_url(value)
        key = canonical_url(clean)
        if key not in seen_feed_keys:
            seen_feed_keys.add(key)
            pending.append(clean)

    all_episodes: list[ArchiveEpisode] = []
    processed_current_document = False
    remaining_snapshots = max_snapshots

    def emit(stage: str, **extra):
        if progress:
            payload = {
                "stage": stage,
                "feed_urls": len(result.feed_urls),
                "snapshots_found": result.snapshots_found,
                "snapshots_loaded": result.snapshots_loaded,
                "episodes_found": len(deduplicate_episodes(all_episodes)),
            }
            payload.update(extra)
            progress(payload)

    while pending and len(result.feed_urls) < MAX_FEED_LINEAGE:
        if cancel_event is not None and cancel_event.is_set():
            break
        feed_url = pending.pop(0)
        result.feed_urls.append(feed_url)
        emit("current", url=feed_url)

        document = None
        final_url = feed_url
        if current_document is not None and not processed_current_document:
            document = current_document
            processed_current_document = True
        else:
            try:
                response = _fetch_with_retry(
                    fetcher,
                    feed_url,
                    timeout=_ARCHIVE_TIMEOUT,
                    site_cookies=False,
                    cancel_event=cancel_event,
                )
                response.raise_for_status()
                document = _response_bytes(response)
                response_url = str(getattr(response, "url", "") or "").strip()
                if response_url:
                    try:
                        final_url = _public_http_url(response_url)
                    except ValueError:
                        final_url = feed_url
            except Exception as exc:
                result.warnings.append(f"Could not read current feed {feed_url}: {exc}")

        if document:
            title, episodes, discovered = parse_feed_document(document, final_url)
            if title and not result.feed_title:
                result.feed_title = title
            all_episodes.extend(episodes)
            for discovered_url in [final_url, *discovered]:
                key = canonical_url(discovered_url)
                if key not in seen_feed_keys and len(seen_feed_keys) < MAX_FEED_LINEAGE:
                    seen_feed_keys.add(key)
                    pending.append(discovered_url)

        if remaining_snapshots <= 0:
            result.truncated = True
            continue
        emit("index", url=feed_url)
        try:
            snapshots, truncated = list_snapshots(
                feed_url,
                max_snapshots=remaining_snapshots,
                fetcher=fetcher,
            )
        except PodcastArchiveError as exc:
            result.warnings.append(str(exc))
            continue
        result.snapshots_found += len(snapshots)
        result.truncated = result.truncated or truncated
        remaining_snapshots -= len(snapshots)

        for timestamp, original in snapshots:
            if cancel_event is not None and cancel_event.is_set():
                break
            emit("snapshot", url=original, timestamp=timestamp)
            try:
                response = _fetch_with_retry(
                    fetcher,
                    _snapshot_url(timestamp, original),
                    timeout=_ARCHIVE_TIMEOUT,
                    site_cookies=False,
                    cancel_event=cancel_event,
                )
                response.raise_for_status()
                snapshot_doc = _response_bytes(response)
                title, episodes, discovered = parse_feed_document(
                    snapshot_doc,
                    original,
                    snapshot_timestamp=timestamp,
                )
                if title and not result.feed_title:
                    result.feed_title = title
                all_episodes.extend(episodes)
                result.snapshots_loaded += 1
                for discovered_url in discovered:
                    key = canonical_url(discovered_url)
                    if key not in seen_feed_keys and len(seen_feed_keys) < MAX_FEED_LINEAGE:
                        seen_feed_keys.add(key)
                        pending.append(discovered_url)
            except Exception:
                result.failed_snapshots += 1
                log.debug("Could not load podcast feed snapshot %s", timestamp, exc_info=True)

    deduped = deduplicate_episodes(all_episodes)
    if not include_without_media:
        deduped = [episode for episode in deduped if episode.media_url]
    deduped.sort(
        key=lambda episode: (
            episode.published if not episode.published.startswith("0001-") else "",
            episode.title.casefold(),
        ),
        reverse=True,
    )
    result.episodes = deduped
    result.canceled = bool(cancel_event is not None and cancel_event.is_set())
    emit("complete")
    return result


def archive_only_entries(result: PodcastArchiveResult, current_document: bytes | str) -> list:
    """Convert episodes absent from the current document to feedparser entries."""
    _title, current, _lineage = parse_feed_document(current_document, result.feed_urls[0] if result.feed_urls else "")
    current_keys = set()
    for episode in current:
        current_keys.update(episode.identity_keys)
    entries = []
    for episode in result.episodes:
        if episode.identity_keys & current_keys:
            continue
        entries.append(episode.as_feedparser_entry())
    return entries
