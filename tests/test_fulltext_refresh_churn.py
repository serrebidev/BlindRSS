# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regressions for full-text extraction racing refresh top-up merges.

During a refresh, _quick_merge_articles rebuilds the article list every
~120ms and the physical list selection is transiently vacant while row
batches are re-inserted. The fulltext pipeline must not discard finished
extractions, leak the in-flight guard, or fetch the wrong article when it
runs against that churn.
"""
import types

import gui.mainframe as mainframe

MF = mainframe.MainFrame


class _ListCtrl:
    def __init__(self, selected=-1):
        self.selected = selected

    def GetFirstSelected(self):
        return self.selected


def _article(aid, url):
    return types.SimpleNamespace(
        id=aid, cache_id=aid, url=url, title=f"T {aid}", author="A", content="<p>c</p>"
    )


def _frame(articles, selected=-1, selected_id=None):
    d = types.SimpleNamespace()
    d.current_articles = articles
    d.list_ctrl = _ListCtrl(selected)
    d.selected_article_id = selected_id
    d._fulltext_cache = {}
    d._fulltext_cache_source = {}
    d._fulltext_loading_url = None
    d._fulltext_token = 0
    d._translation_fulltext_cache_suffix = lambda: ""
    d._article_cache_id = lambda a: MF._article_cache_id(d, a)
    d._fulltext_cache_key_for_article = lambda a, i: MF._fulltext_cache_key_for_article(d, a, i)
    d._index_of_selected_article = lambda: MF._index_of_selected_article(d)
    d._build_fulltext_request = lambda a, i, **kw: MF._build_fulltext_request(d, a, i, **kw)
    d.applied = []
    d._set_article_reader_text = (
        lambda article, text, reset_insertion=False: d.applied.append((article, text))
    )
    return d


def test_index_of_selected_article_resolves_by_id():
    arts = [_article("a1", "https://example.com/a1"), _article("b1", "https://example.com/b1")]
    d = _frame(arts, selected=-1, selected_id="b1")
    assert d._index_of_selected_article() == 1

    d.selected_article_id = None
    assert d._index_of_selected_article() is None

    d.selected_article_id = "gone"
    assert d._index_of_selected_article() is None


def test_apply_result_caches_and_releases_guard_when_list_mid_rebuild():
    a = _article("a1", "https://example.com/a1")
    d = _frame([a], selected=-1, selected_id=None)
    key, _url, _aid = d._fulltext_cache_key_for_article(a, 0)
    d._fulltext_loading_url = key

    MF._fulltext_apply_result(d, key, "FULL TEXT", True, "web", 0)

    # The finished extraction must survive the vacant selection...
    assert d._fulltext_cache[key] == "FULL TEXT"
    assert d._fulltext_cache_source[key] == "web"
    # ...and the guard must be released so a retry is not a silent no-op.
    assert d._fulltext_loading_url is None
    assert d.applied == []


def test_apply_result_renders_via_logical_selection_during_rebuild():
    a = _article("a1", "https://example.com/a1")
    d = _frame(
        [_article("new", "https://example.com/new"), a], selected=-1, selected_id="a1"
    )
    key, _url, _aid = d._fulltext_cache_key_for_article(a, 1)
    d._fulltext_loading_url = key

    MF._fulltext_apply_result(d, key, "FULL TEXT", True, "web", 0)

    assert d.applied == [(a, "FULL TEXT")]
    assert d._fulltext_cache[key] == "FULL TEXT"
    assert d._fulltext_loading_url is None


def test_apply_result_prefers_logical_selection_over_stale_physical_row():
    wrong = _article("wrong", "https://example.com/wrong")
    target = _article("a1", "https://example.com/a1")
    d = _frame([wrong, target], selected=0, selected_id="a1")
    key, _url, _aid = d._fulltext_cache_key_for_article(target, 1)

    MF._fulltext_apply_result(d, key, "FULL TEXT", True, "web", 0)

    assert d.applied == [(target, "FULL TEXT")]


def test_rich_result_prefers_logical_selection_over_stale_physical_row():
    wrong = _article("wrong", "https://example.com/wrong")
    target = _article("a1", "https://example.com/a1")
    d = _frame([wrong, target], selected=0, selected_id="a1")
    key, _url, _aid = d._fulltext_cache_key_for_article(target, 1)
    d._fulltext_html_cache = {}
    d.rendered = []
    d._render_rich_html = lambda html, **kwargs: d.rendered.append((html, kwargs))
    d._announce_fulltext_loaded_macos = lambda: None

    MF._apply_rich_result(d, key, "<article>FULL</article>", 0)

    assert d.rendered == [
        ("<article>FULL</article>", {"refresh_accessibility": True})
    ]


def test_apply_result_with_stale_token_still_caches_and_releases_guard():
    a = _article("a1", "https://example.com/a1")
    d = _frame([a], selected=0, selected_id="a1")
    d._fulltext_token = 5
    key, _url, _aid = d._fulltext_cache_key_for_article(a, 0)
    d._fulltext_loading_url = key

    MF._fulltext_apply_result(d, key, "FULL TEXT", True, "web", 4)

    assert d._fulltext_cache[key] == "FULL TEXT"
    assert d._fulltext_loading_url is None
    assert d.applied == []


def test_apply_result_leaves_other_inflight_guard_alone():
    a = _article("a1", "https://example.com/a1")
    b = _article("b1", "https://example.com/b1")
    d = _frame([a, b], selected=1, selected_id="b1")
    key_a, _u, _i = d._fulltext_cache_key_for_article(a, 0)
    key_b, _u2, _i2 = d._fulltext_cache_key_for_article(b, 1)
    d._fulltext_loading_url = key_b  # b's load is genuinely in flight

    MF._fulltext_apply_result(d, key_a, "A TEXT", True, "web", 0)

    assert d._fulltext_loading_url == key_b
    assert d._fulltext_cache[key_a] == "A TEXT"
    assert d.applied == []  # selection is on b, whose key differs


def test_apply_result_uncacheable_clears_stale_cache_entry():
    a = _article("a1", "https://example.com/a1")
    d = _frame([a], selected=-1, selected_id=None)
    key, _url, _aid = d._fulltext_cache_key_for_article(a, 0)
    d._fulltext_cache[key] = "OLD"
    d._fulltext_cache_source[key] = "web"
    d._fulltext_loading_url = key

    MF._fulltext_apply_result(d, key, "fallback text", False, "fallback", 0)

    assert key not in d._fulltext_cache
    assert key not in d._fulltext_cache_source
    assert d._fulltext_loading_url is None


def test_start_fulltext_load_targets_logical_selection_after_merge_shift():
    target = _article("a1", "https://example.com/a1")
    merged = [_article("new", "https://example.com/new"), target]
    d = _frame(merged, selected=-1, selected_id="a1")
    submitted = []
    d._fulltext_submit_request = lambda req, priority=False: submitted.append((req, priority))

    # Scheduled with index 0 before the merge inserted a new row on top.
    MF._start_fulltext_load(d, 0, 0)

    assert len(submitted) == 1
    req, priority = submitted[0]
    assert priority is True
    assert req["url"] == "https://example.com/a1"
    assert d._fulltext_loading_url == req["cache_key"]


def test_start_fulltext_load_skips_when_selected_article_left_view():
    d = _frame(
        [_article("other", "https://example.com/other")], selected=-1, selected_id="gone"
    )
    submitted = []
    d._fulltext_submit_request = lambda req, priority=False: submitted.append(req)

    MF._start_fulltext_load(d, 0, 0)

    assert submitted == []
    assert d._fulltext_loading_url is None


def test_start_fulltext_load_positional_fallback_without_logical_selection():
    a = _article("a1", "https://example.com/a1")
    d = _frame([a], selected=0, selected_id=None)
    submitted = []
    d._fulltext_submit_request = lambda req, priority=False: submitted.append(req)

    MF._start_fulltext_load(d, 0, 0)

    assert len(submitted) == 1
    assert submitted[0]["url"] == "https://example.com/a1"
