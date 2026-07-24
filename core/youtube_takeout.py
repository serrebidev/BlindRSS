# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Parse Google Takeout YouTube exports into subscribable RSS feeds.

The parser is GUI-free so archive validation and source discovery remain easy to
test.  It never extracts archive members to disk; only bounded CSV/HTML members
are read from the ZIP.
"""
from __future__ import annotations

import csv
import io
import os
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree as ET


_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 20_000
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


@dataclass(frozen=True)
class TakeoutFeed:
    title: str
    url: str
    source: str


@dataclass(frozen=True)
class TakeoutImport:
    feeds: tuple[TakeoutFeed, ...]
    subscriptions: int = 0
    history_channels: int = 0
    owner_channels: int = 0
    playlists: int = 0

    def selected(self, sources: set[str] | tuple[str, ...] | list[str]) -> "TakeoutImport":
        """Return a URL-deduplicated subset containing only chosen source types."""
        wanted = {str(source) for source in sources}
        unique: dict[str, TakeoutFeed] = {}
        source_counts = {"subscriptions": 0, "history": 0, "owner": 0, "playlists": 0}
        for feed in self.feeds:
            if feed.source not in wanted:
                continue
            source_counts[feed.source] += 1
            unique.setdefault(feed.url, feed)
        return TakeoutImport(
            feeds=tuple(unique.values()),
            subscriptions=source_counts["subscriptions"],
            history_channels=source_counts["history"],
            owner_channels=source_counts["owner"],
            playlists=source_counts["playlists"],
        )


class TakeoutError(ValueError):
    """Raised when a file is not a usable YouTube Takeout archive."""


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    if info.file_size > _MAX_MEMBER_BYTES:
        raise TakeoutError(f"Takeout member is too large: {info.filename}")
    return zf.read(info).decode("utf-8-sig", errors="replace")


def _channel_feed(channel_id: str) -> str:
    value = str(channel_id or "").strip()
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={value}" if value else ""


def _playlist_feed(playlist_id: str) -> str:
    value = str(playlist_id or "").strip()
    return f"https://www.youtube.com/feeds/videos.xml?playlist_id={value}" if value else ""


def _channel_id_from_url(url: str) -> str:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return ""
    if (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() == "channel":
        return parts[1]
    return ""


def _rows(text: str):
    return csv.DictReader(io.StringIO(text))


class _HistoryChannelParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.channels: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href", "")
        self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self._href:
            return
        channel_id = _channel_id_from_url(self._href)
        if channel_id:
            self.channels.append((channel_id, "".join(self._text).strip() or channel_id))
        self._href = ""
        self._text = []


def parse_youtube_takeout(path: str | os.PathLike[str]) -> TakeoutImport:
    """Return all deduplicated channel and playlist feeds in a Takeout ZIP."""
    archive_path = os.fspath(path)
    if not zipfile.is_zipfile(archive_path):
        raise TakeoutError("The selected file is not a valid ZIP archive.")

    discovered: list[TakeoutFeed] = []
    seen_by_source: set[tuple[str, str]] = set()
    counts = {"subscriptions": 0, "history": 0, "owner": 0, "playlists": 0}

    def add(title: str, url: str, source: str) -> None:
        clean_url = str(url or "").strip()
        key = (source, clean_url)
        if not clean_url or key in seen_by_source:
            return
        seen_by_source.add(key)
        discovered.append(TakeoutFeed(str(title or "").strip() or clean_url, clean_url, source))
        counts[source] += 1

    try:
        with zipfile.ZipFile(archive_path) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ARCHIVE_MEMBERS:
                raise TakeoutError("The selected archive contains too many files.")
            youtube_infos = [
                info for info in infos
                if "/youtube and youtube music/" in ("/" + info.filename.lower())
            ]
            if not youtube_infos:
                raise TakeoutError("No YouTube and YouTube Music export was found in this archive.")

            for info in youtube_infos:
                name = info.filename.replace("\\", "/").lower()
                if name.endswith("/subscriptions/subscriptions.csv"):
                    for row in _rows(_read_member(zf, info)):
                        channel_id = row.get("Channel ID", "")
                        add(row.get("Channel title", ""), _channel_feed(channel_id), "subscriptions")
                elif name.endswith("/channels/channel.csv"):
                    for row in _rows(_read_member(zf, info)):
                        channel_id = row.get("Channel ID", "")
                        add(row.get("Channel title (Original)", ""), _channel_feed(channel_id), "owner")
                elif name.endswith("/playlists/playlists.csv"):
                    for row in _rows(_read_member(zf, info)):
                        playlist_id = row.get("Playlist ID", "")
                        add(row.get("Playlist title (original)", ""), _playlist_feed(playlist_id), "playlists")
                elif name.endswith("/history/watch-history.html"):
                    parser = _HistoryChannelParser()
                    parser.feed(_read_member(zf, info))
                    for channel_id, title in parser.channels:
                        add(title, _channel_feed(channel_id), "history")
    except (OSError, zipfile.BadZipFile) as exc:
        raise TakeoutError(f"Could not read the Takeout archive: {exc}") from exc

    if not discovered:
        raise TakeoutError("No subscribable YouTube channels or playlists were found.")
    return TakeoutImport(
        feeds=tuple(discovered),
        subscriptions=counts["subscriptions"],
        history_channels=counts["history"],
        owner_channels=counts["owner"],
        playlists=counts["playlists"],
    )


def write_takeout_opml(result: TakeoutImport, path: str | os.PathLike[str]) -> None:
    """Write parsed feeds as a compact OPML document for any RSS provider."""
    root = ET.Element("opml", version="2.0")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = "YouTube Takeout"
    body = ET.SubElement(root, "body")
    unique: dict[str, TakeoutFeed] = {}
    for feed in result.feeds:
        unique.setdefault(feed.url, feed)
    for feed in unique.values():
        ET.SubElement(body, "outline", text=feed.title, title=feed.title, type="rss", xmlUrl=feed.url)
    ET.ElementTree(root).write(os.fspath(path), encoding="utf-8", xml_declaration=True)
