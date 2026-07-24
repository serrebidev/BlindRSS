# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import csv
import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from core.youtube_takeout import TakeoutError, parse_youtube_takeout, write_takeout_opml


ROOT = "Takeout/YouTube and YouTube Music"


def _csv(headers, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(headers)
    writer.writerows(rows)
    return out.getvalue()


def _archive(tmp_path):
    path = tmp_path / "takeout.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            f"{ROOT}/subscriptions/subscriptions.csv",
            _csv(
                ["Channel ID", "Channel URL", "Channel title"],
                [["UCsub", "https://www.youtube.com/channel/UCsub", "Subscribed"]],
            ),
        )
        zf.writestr(
            f"{ROOT}/channels/channel.csv",
            _csv(
                ["Channel ID", "Channel title (Original)"],
                [["UCowner", "My channel"]],
            ),
        )
        zf.writestr(
            f"{ROOT}/playlists/playlists.csv",
            _csv(
                ["Playlist ID", "Playlist title (original)", "Playlist visibility"],
                [["PLpublic", "Public list", "Public"], ["PLprivate", "Private list", "Private"]],
            ),
        )
        zf.writestr(
            f"{ROOT}/history/watch-history.html",
            '<div>Watched <a href="https://www.youtube.com/watch?v=abc">Video</a><br>'
            '<a href="https://www.youtube.com/channel/UChistory">History channel</a></div>'
            '<a href="https://www.youtube.com/channel/UCsub">Duplicate subscription</a>',
        )
    return path


def test_parse_takeout_finds_all_subscribable_sources_and_deduplicates(tmp_path):
    result = parse_youtube_takeout(_archive(tmp_path))

    assert len(result.feeds) == 6
    assert result.subscriptions == 1
    assert result.owner_channels == 1
    assert result.history_channels == 2
    assert result.playlists == 2
    assert any(feed.title == "Private list" and "playlist_id=PLprivate" in feed.url for feed in result.feeds)


def test_write_takeout_opml_preserves_titles_and_urls(tmp_path):
    result = parse_youtube_takeout(_archive(tmp_path))
    target = tmp_path / "takeout.opml"
    write_takeout_opml(result, target)

    outlines = ET.parse(target).findall("./body/outline")
    assert len(outlines) == 5
    assert outlines[0].attrib["text"] == "Subscribed"
    assert outlines[0].attrib["xmlUrl"].endswith("channel_id=UCsub")


def test_source_selection_happens_before_cross_source_deduplication(tmp_path):
    result = parse_youtube_takeout(_archive(tmp_path))

    history = result.selected({"history"})
    assert len(history.feeds) == 2
    assert history.history_channels == 2
    assert any(feed.url.endswith("channel_id=UCsub") for feed in history.feeds)

    combined = result.selected({"subscriptions", "history"})
    assert len(combined.feeds) == 2


def test_rejects_zip_without_youtube_export(tmp_path):
    path = tmp_path / "other.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Takeout/Drive/file.txt", "nothing")
    with pytest.raises(TakeoutError, match="No YouTube"):
        parse_youtube_takeout(path)
