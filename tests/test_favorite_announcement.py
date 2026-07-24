# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Ctrl+D announces the new favorite state (issue #70).

Ctrl+D changes no visible row text, so without an announcement the action is
silent for a screen-reader user -- they cannot tell success from a no-op. These
drive MainFrame.on_toggle_favorite on a lightweight host (the fake-object
pattern used by tests/test_article_list_render.py) and assert the announcement
is routed through the configurable "favorite_toggle" event.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _Article:
    def __init__(self, article_id="a1", is_favorite=False):
        self.id = article_id
        self.is_favorite = is_favorite


class _Provider:
    """Toggles and reports the new state, like the real providers do."""

    def __init__(self, new_state=True):
        self.new_state = new_state
        self.calls = []

    def supports_favorites(self):
        return True

    def toggle_favorite(self, article_id):
        self.calls.append(article_id)
        return self.new_state


class _Host:
    on_toggle_favorite = mainframe.MainFrame.on_toggle_favorite
    _supports_favorites = mainframe.MainFrame._supports_favorites
    _is_favorites_view = mainframe.MainFrame._is_favorites_view

    def __init__(self, *, new_state=True, article=None, view_id="all"):
        self.provider = _Provider(new_state=new_state)
        self.current_articles = [article or _Article()]
        self.current_feed_id = view_id
        self.announced = []
        self._selected_index = 0

    # -- collaborators reduced to spies -------------------------------------
    def _announce_event(self, event_id, message):
        self.announced.append((event_id, message))

    def _get_selected_article_index(self):
        return self._selected_index

    def _is_load_more_row(self, idx):
        return False

    def _article_cache_id(self, article):
        return article.id

    def _sync_favorite_flag_in_cached_views(self, article_id, is_favorite):
        pass

    def _update_cached_favorites_view(self, article, is_favorite):
        pass

    def _remove_article_from_current_list(self, idx):
        del self.current_articles[idx]

    def _show_empty_articles_state(self):
        pass

    def _update_current_view_cache(self, fid):
        pass

    def _decrement_view_total_if_present(self, fid):
        pass


def test_adding_to_favorites_announces():
    host = _Host(new_state=True, article=_Article(is_favorite=False))

    host.on_toggle_favorite()

    assert host.announced == [("favorite_toggle", "Added to favorites")]
    assert host.current_articles[0].is_favorite is True


def test_removing_from_favorites_announces():
    host = _Host(new_state=False, article=_Article(is_favorite=True))

    host.on_toggle_favorite()

    assert host.announced == [("favorite_toggle", "Removed from favorites")]
    assert host.current_articles[0].is_favorite is False


def test_removal_announces_before_the_row_disappears():
    """In the Favorites view an un-favorited article is dropped from the list.
    The announcement must already have happened, or the user gets silence plus a
    vanished row."""
    host = _Host(new_state=False, article=_Article(is_favorite=True), view_id="favorites:all")

    host.on_toggle_favorite()

    assert host.announced == [("favorite_toggle", "Removed from favorites")]
    assert host.current_articles == []  # row really was removed


def test_no_announcement_when_the_provider_refuses():
    """A failed toggle must stay silent rather than claim a state change."""
    host = _Host(new_state=None)

    host.on_toggle_favorite()

    assert host.announced == []


def test_no_announcement_without_favorites_support():
    host = _Host()
    host.provider.supports_favorites = lambda: False

    host.on_toggle_favorite()

    assert host.announced == []
    assert host.provider.calls == []
