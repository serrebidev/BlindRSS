# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import sys
import queue
import types
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gui.dialogs as dialogs


class _JsonResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return self._payload


class _Host:
    _SOURCE_ALL = dialogs.FeedSearchDialog._SOURCE_ALL
    _SOURCE_ALL_PODCAST = dialogs.FeedSearchDialog._SOURCE_ALL_PODCAST
    _SOURCE_ALL_RSS = dialogs.FeedSearchDialog._SOURCE_ALL_RSS
    _PODCAST_SOURCE_KEYS = dialogs.FeedSearchDialog._PODCAST_SOURCE_KEYS
    _RSS_SOURCE_KEYS = dialogs.FeedSearchDialog._RSS_SOURCE_KEYS
    _build_search_targets = dialogs.FeedSearchDialog._build_search_targets
    _is_url_like_term = staticmethod(dialogs.FeedSearchDialog._is_url_like_term)

    def _search_itunes(self, term, queue):
        _ = (term, queue)

    def _search_gpodder(self, term, queue):
        _ = (term, queue)

    def _search_fyyd(self, term, queue):
        _ = (term, queue)

    def _search_podverse(self, term, queue):
        _ = (term, queue)

    def _search_feedly(self, term, queue):
        _ = (term, queue)

    def _search_feedspot(self, term, queue):
        _ = (term, queue)

    def _search_googlenews(self, term, queue):
        _ = (term, queue)

    def _search_bingnews(self, term, queue):
        _ = (term, queue)

    def _search_youtube_channels(self, term, queue):
        _ = (term, queue)

    def _search_soundcloud(self, term, queue):
        _ = (term, queue)

    def _search_mixcloud(self, term, queue):
        _ = (term, queue)

    def _search_newsblur(self, term, queue):
        _ = (term, queue)

    def _search_reddit(self, term, queue):
        _ = (term, queue)

    def _search_fediverse(self, term, queue):
        _ = (term, queue)

    def _search_feedsearch(self, term, queue):
        _ = (term, queue)

    def _search_blindrss(self, term, queue):
        _ = (term, queue)

    def _search_mastodon(self, term, queue):
        _ = (term, queue)

    def _search_bluesky(self, term, queue):
        _ = (term, queue)

    def _search_piefed(self, term, queue):
        _ = (term, queue)

    def _search_lemmy(self, term, queue):
        _ = (term, queue)


def _target_names(targets):
    return [name for name, _ in targets]


def test_feed_search_all_sources_excludes_url_only_targets_for_keyword():
    host = _Host()
    targets = host._build_search_targets("blue sky", host._SOURCE_ALL)

    assert _target_names(targets) == [
        "NewsBlur",
        "iTunes",
        "gPodder",
        "fyyd",
        "Podverse",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "Reddit",
        "Fediverse",
    ]


def test_feed_search_all_sources_excludes_feedly():
    # Feedly is selectable on its own but no longer part of the "all" groups.
    host = _Host()
    names = _target_names(host._build_search_targets("example.com", host._SOURCE_ALL))
    assert "Feedly" not in names
    assert "NewsBlur" in names


def test_feed_search_all_sources_includes_url_only_targets_for_url_like_terms():
    host = _Host()
    targets = host._build_search_targets("example.com", host._SOURCE_ALL)

    assert _target_names(targets) == [
        "NewsBlur",
        "iTunes",
        "gPodder",
        "fyyd",
        "Podverse",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "Reddit",
        "Fediverse",
        "Feedsearch",
        "BlindRSS",
    ]


def test_feed_search_all_podcast_sources_group():
    host = _Host()
    targets = host._build_search_targets("history", host._SOURCE_ALL_PODCAST)

    assert _target_names(targets) == ["iTunes", "gPodder", "fyyd", "Podverse", "SoundCloud", "Mixcloud"]


def test_feed_search_all_rss_sources_group_excludes_url_only_targets_for_keyword():
    host = _Host()
    targets = host._build_search_targets("tech news", host._SOURCE_ALL_RSS)

    assert _target_names(targets) == [
        "NewsBlur",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "Reddit",
        "Fediverse",
    ]


def test_feed_search_all_rss_sources_group_includes_url_only_targets_for_url_like_terms():
    host = _Host()
    targets = host._build_search_targets("example.com", host._SOURCE_ALL_RSS)

    assert _target_names(targets) == [
        "NewsBlur",
        "Feedspot",
        "Google News",
        "Bing News",
        "YouTube",
        "SoundCloud",
        "Mixcloud",
        "Reddit",
        "Fediverse",
        "Feedsearch",
        "BlindRSS",
    ]


def test_feed_search_feedly_still_selectable_explicitly():
    host = _Host()
    targets = host._build_search_targets("tech news", "feedly")

    assert _target_names(targets) == ["Feedly"]


def test_google_news_remains_selectable_explicitly():
    host = _Host()
    targets = host._build_search_targets("tech news", "googlenews")

    assert _target_names(targets) == ["Google News"]


def test_google_news_merged_results_sort_below_direct_feed_matches():
    results = [
        {"provider": "Google News", "title": "Broad query subscription"},
        {"provider": "NewsBlur", "title": "Publisher feed"},
        {"provider": "Feedspot", "title": "Curated publisher feed"},
        {"provider": "YouTube", "title": "YouTube channel"},
    ]

    results.sort(key=dialogs.FeedSearchDialog._merged_result_sort_key)

    # YouTube deliberately keeps its existing convenience placement; direct feed matches preserve
    # their stable arrival order ahead of Google News' broad search subscription.
    assert [item["provider"] for item in results] == [
        "YouTube",
        "NewsBlur",
        "Feedspot",
        "Google News",
    ]


_NEWSBLUR_FEEDS = [
    {"id": 11145, "value": "https://feeds.feedburner.com/techspot/news",
     "label": "TechSpot", "tagline": "TechSpot News - All Stories", "num_subscribers": 802},
    {"id": 4349, "value": "https://www.youtube.com/channel/UCzWQYUVCpZqtN93H8RR44Qw",
     "label": "Seeker", "tagline": "", "num_subscribers": 0},
    {"id": 999, "value": "1234", "label": "Internal id only", "num_subscribers": 5},
]


def _run_newsblur(payload, status_code=200):
    q = queue.Queue()
    resp = _JsonResp(payload, status_code=status_code)
    with patch("gui.dialogs.utils.safe_requests_get", return_value=resp):
        dialogs.FeedSearchDialog._search_newsblur(types.SimpleNamespace(), "TechSpot", q)
    try:
        provider, results = q.get_nowait()
    except queue.Empty:
        return None, []
    return provider, results


def test_newsblur_parses_v2_dict_shape():
    provider, results = _run_newsblur({"feeds": _NEWSBLUR_FEEDS})
    assert provider == "NewsBlur"
    urls = [r["url"] for r in results]
    # Real feed URLs kept; the numeric-id-only entry is dropped.
    assert "https://feeds.feedburner.com/techspot/news" in urls
    assert "1234" not in urls
    techspot = next(r for r in results if r["title"] == "TechSpot")
    assert "802 subscribers" in techspot["detail"]


def test_newsblur_uses_public_v2_autocomplete_endpoint():
    q = queue.Queue()
    with patch(
        "gui.dialogs.utils.safe_requests_get",
        return_value=_JsonResp({"feeds": _NEWSBLUR_FEEDS}),
    ) as request_get:
        dialogs.FeedSearchDialog._search_newsblur(types.SimpleNamespace(), "tech & science", q)

    request_get.assert_called_once_with(
        "https://www.newsblur.com/discover/autocomplete?term=tech%20%26%20science&v=2",
        timeout=10,
    )


def test_newsblur_non_success_response_yields_nothing():
    provider, results = _run_newsblur({"feeds": _NEWSBLUR_FEEDS}, status_code=503)

    assert provider is None
    assert results == []


def test_newsblur_parses_legacy_list_shape():
    provider, results = _run_newsblur(_NEWSBLUR_FEEDS)
    assert provider == "NewsBlur"
    assert any(r["url"] == "https://feeds.feedburner.com/techspot/news" for r in results)


def test_newsblur_unexpected_shape_yields_nothing():
    provider, results = _run_newsblur({"unexpected": True})
    assert provider is None
    assert results == []


def test_feed_search_bluesky_only_source_is_supported():
    host = _Host()
    targets = host._build_search_targets("tech", "bluesky")

    assert _target_names(targets) == ["Bluesky"]


def test_feed_search_explicit_feedsearch_selection_runs_for_keyword():
    # Explicitly picking a website-scan source must always run it: the source
    # itself guesses "<term>.com" for bare site names (the "techspot" case).
    host = _Host()
    targets = host._build_search_targets("keyword", "feedsearch")

    assert _target_names(targets) == ["Feedsearch"]


def test_feed_search_explicit_blindrss_selection_runs_for_keyword():
    host = _Host()
    targets = host._build_search_targets("techspot", "blindrss")

    assert _target_names(targets) == ["BlindRSS"]


def test_feed_search_all_sources_single_word_includes_local_site_scan():
    # A single-word term ("techspot") runs the local website scan (which tries
    # techspot.com) but keeps the external Feedsearch service URL-gated.
    host = _Host()
    targets = host._build_search_targets("techspot", host._SOURCE_ALL)

    names = _target_names(targets)
    assert "BlindRSS" in names
    assert "Feedsearch" not in names


def test_feed_search_all_rss_single_word_includes_local_site_scan():
    host = _Host()
    targets = host._build_search_targets("techspot", host._SOURCE_ALL_RSS)

    names = _target_names(targets)
    assert "BlindRSS" in names
    assert "Feedsearch" not in names


def test_site_scan_targets_normalization():
    fn = dialogs.FeedSearchDialog._site_scan_targets

    assert fn("https://www.techspot.com") == ["https://www.techspot.com"]
    assert fn("techspot.com") == ["https://techspot.com"]
    assert fn("techspot") == ["https://techspot.com"]
    assert fn("TechSpot") == ["https://techspot.com"]
    assert fn("blue sky") == []
    assert fn("") == []
