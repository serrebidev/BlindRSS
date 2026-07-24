# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.dialogs as dialogs


class _Host:
    _get_selected_action_availability = dialogs.YtdlpGlobalSearchDialog._get_selected_action_availability

    def __init__(self, item):
        self._item = item

    def _get_selected_result(self):
        return self._item


class _StatusLabel:
    def __init__(self):
        self.label = ""

    def SetLabel(self, label):
        self.label = label


class _SearchResultsHost:
    _on_site_search_results = dialogs.YtdlpGlobalSearchDialog._on_site_search_results
    _result_key_for_item = dialogs.YtdlpGlobalSearchDialog._result_key_for_item
    _title_needs_enrichment = dialogs.YtdlpGlobalSearchDialog._title_needs_enrichment

    def __init__(self):
        self._stop_event = None
        self._completed_sites = 0
        self._total_sites = 0
        self._seen_result_keys = set()
        self._result_arrival_counter = 0
        self._all_results = []
        self._search_generation = 1
        self.status_lbl = _StatusLabel()
        self.refresh_scheduled = False
        self.enrichment_requests = []

    def _schedule_results_refresh(self):
        self.refresh_scheduled = True

    def _queue_title_enrichment(self, item, generation):
        self.enrichment_requests.append((item, generation))


def test_selected_action_availability_when_result_has_play_and_subscribe_targets():
    host = _Host(
        {
            "url": "https://example.com/watch/1",
            "native_subscribe_url": "https://example.com/feed.xml",
            "source_subscribe_url": "",
        }
    )

    assert host._get_selected_action_availability() == (True, True, True)


def test_selected_action_availability_when_nothing_is_selected():
    host = _Host(None)
    assert host._get_selected_action_availability() == (False, False, False)


def test_site_search_results_auto_queue_quick_title_enrichment_for_supported_fallback_rows():
    # Rows with placeholder titles and a cheap oEmbed-style fast path (YouTube,
    # Rokfin) get the quick title stage queued as soon as they arrive; rows with
    # real titles and rows on unsupported hosts are left alone (no heavy yt-dlp
    # enrichment is ever auto-queued from arriving results).
    host = _SearchResultsHost()
    items = [
        {
            "title": "YouTube video abc123",
            "url": "https://www.youtube.com/watch?v=abc123",
            "site_id": "yvsearch",
            "_title_is_fallback": True,
        },
        {
            "title": "A Real Title",
            "url": "https://www.youtube.com/watch?v=def456",
            "site_id": "yvsearch",
            "_title_is_fallback": False,
        },
        {
            "title": "Facebook reel 42",
            "url": "https://www.facebook.com/reel/42/",
            "site_id": "yvsearch",
            "_title_is_fallback": True,
        },
    ]

    host._on_site_search_results({"id": "yvsearch", "label": "Yahoo Video"}, items, 1, 1)

    assert len(host._all_results) == 3
    assert host.refresh_scheduled is True
    queued_urls = [str(item.get("url") or "") for item, _gen in host.enrichment_requests]
    assert queued_urls == ["https://www.youtube.com/watch?v=abc123"]
    assert all(gen == 1 for _item, gen in host.enrichment_requests)


def test_site_search_results_dedupe_same_video_across_sites_keeps_best():
    # The same YouTube video arriving from two different search backends must
    # collapse to one row, keeping the copy with the richer metadata.
    host = _SearchResultsHost()

    host._on_site_search_results(
        {"id": "ytsearch", "label": "YouTube"},
        [
            {
                "title": "vid123",
                "url": "https://www.youtube.com/watch?v=vid123",
                "_title_is_fallback": True,
            }
        ],
        1,
        2,
    )
    # Duplicate of the same video (different URL form) with a real title + plays.
    host._on_site_search_results(
        {"id": "scsearch", "label": "SoundCloud"},
        [
            {
                "title": "A Real Title",
                "url": "https://youtu.be/vid123",
                "_title_is_fallback": False,
                "play_count": 4242,
            }
        ],
        2,
        2,
    )

    assert len(host._all_results) == 1
    kept = host._all_results[0]
    assert kept["title"] == "A Real Title"
    assert kept["play_count"] == 4242
    # Kept its original arrival slot so ordering stays stable.
    assert kept["_arrival_order"] == 1
