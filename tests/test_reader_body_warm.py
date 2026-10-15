# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Arrowing the article list must not parse HTML on the UI thread twice."""

from types import SimpleNamespace

from core import utils
from gui import mainframe


class _Host:
    _reader_body = mainframe.MainFrame._reader_body
    _warm_reader_bodies_worker = mainframe.MainFrame._warm_reader_bodies_worker
    _flush_deferred_status_cells = mainframe.MainFrame._flush_deferred_status_cells
    _article_cache_id = mainframe.MainFrame._article_cache_id

    def __init__(self):
        self._fulltext_token = 0
        self.strip_calls = 0
        self.current_articles = []

    def _strip_html(self, html, include_images=None):
        self.strip_calls += 1
        return utils.html_to_text(html)


def _art(aid, content="<p>Hello <b>world</b></p>"):
    return SimpleNamespace(id=aid, content=content, url="https://example.com/" + aid)


def test_reader_body_is_memoized_across_article_objects():
    host = _Host()
    assert "Hello world" in host._reader_body(_art("a"), rich=False)
    # A refresh builds a new Article object with the same content: no reparse.
    assert "Hello world" in host._reader_body(_art("a"), rich=False)
    assert host.strip_calls == 1
    # Changed content is converted again.
    host._reader_body(_art("a", "<p>Edited</p>"), rich=False)
    assert host.strip_calls == 2


def test_warm_worker_fills_cache_and_stops_when_selection_moves():
    host = _Host()
    host._warm_reader_bodies_worker([(_art("n1"), False), (_art("n2"), False)], False, 0)
    assert host.strip_calls == 2
    host._reader_body(_art("n1"), rich=False)
    assert host.strip_calls == 2  # the next arrow is a cache hit

    host._fulltext_token = 5  # user arrowed away before the warm job ran
    host._warm_reader_bodies_worker([(_art("n3"), False)], False, 4)
    assert host.strip_calls == 2


def test_rich_body_uses_cleaner_and_is_cached():
    host = _Host()
    first = host._reader_body(_art("r"), rich=True)
    assert "world" in first
    assert host._reader_body(_art("r"), rich=True) is first
    assert host.strip_calls == 0


def test_deferred_status_for_rows_outside_the_view_is_dropped():
    host = _Host()
    host.current_articles = [_art("x")]
    host._deferred_status_cells = {"gone": "Read"}
    host.list_ctrl = SimpleNamespace(GetItemCount=lambda: 1)
    host._flush_deferred_status_cells(except_idx=0)
    assert host._deferred_status_cells == {}
