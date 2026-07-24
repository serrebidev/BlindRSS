# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for the feed-tree rebuild fast path (skip/patch on unchanged ticks)."""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe
from core.models import Feed


class _SigHost:
    _tree_content_signatures = mainframe.MainFrame._tree_content_signatures

    def __init__(self, filter_mode="all", smart_folders=None):
        self._article_read_filter = filter_mode
        if smart_folders is None:
            self.provider = object()  # no smart-folder support
        else:
            folders = list(smart_folders)

            class _P:
                def supports_smart_folders(self):
                    return True

                def get_smart_folders(self):
                    return folders

            self.provider = _P()


def _feed(fid, title="Feed", category="News", unread=0):
    f = Feed(id=fid, title=title, url=f"https://x/{fid}", category=category)
    f.unread_count = unread
    return f


def test_identical_content_produces_identical_signatures():
    host = _SigHost()
    a = [_feed("1", unread=2), _feed("2", title="Other")]
    b = [_feed("2", title="Other"), _feed("1", unread=2)]  # order must not matter

    assert host._tree_content_signatures(a, ["News"], {}) == host._tree_content_signatures(
        b, ["News"], {}
    )


def test_unread_change_only_changes_counts_signature():
    host = _SigHost()
    before = [_feed("1", unread=0)]
    after = [_feed("1", unread=5)]

    s1, c1 = host._tree_content_signatures(before, ["News"], {})
    s2, c2 = host._tree_content_signatures(after, ["News"], {})
    assert s1 == s2
    assert c1 != c2


def test_structural_changes_change_structural_signature():
    host = _SigHost()
    base = [_feed("1"), _feed("2")]
    s_base, _ = host._tree_content_signatures(base, ["News"], {})

    renamed = [_feed("1", title="Renamed"), _feed("2")]
    moved = [_feed("1", category="Tech"), _feed("2")]
    removed = [_feed("1")]

    assert host._tree_content_signatures(renamed, ["News"], {})[0] != s_base
    assert host._tree_content_signatures(moved, ["News"], {})[0] != s_base
    assert host._tree_content_signatures(removed, ["News"], {})[0] != s_base
    assert host._tree_content_signatures(base, ["News", "Tech"], {})[0] != s_base
    assert host._tree_content_signatures(base, ["News"], {"News": "Top"})[0] != s_base


def test_filter_mode_and_smart_folders_are_structural():
    feeds = [_feed("1")]
    s_all, _ = _SigHost("all")._tree_content_signatures(feeds, ["News"], {})
    s_unread, _ = _SigHost("unread")._tree_content_signatures(feeds, ["News"], {})
    assert s_all != s_unread

    s_none, _ = _SigHost()._tree_content_signatures(feeds, ["News"], {})
    s_folders, _ = _SigHost(smart_folders=[{"id": 1, "name": "F"}])._tree_content_signatures(
        feeds, ["News"], {}
    )
    assert s_none != s_folders
