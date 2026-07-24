# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Stable identity and display-only localization for Uncategorized."""

from types import SimpleNamespace

from core import categories
from gui import accessibility


def _translate(message):
    return "Без категории" if message == "Uncategorized" else message


def test_display_translation_never_changes_persisted_identity(monkeypatch):
    monkeypatch.setattr(categories, "_", _translate)

    assert categories.UNCATEGORIZED == "Uncategorized"
    assert categories.category_display_name(categories.UNCATEGORIZED) == "Без категории"
    assert categories.normalize_category_input("Без категории") == categories.UNCATEGORIZED
    assert categories.is_uncategorized("Без категории") is True


def test_real_category_named_like_translation_is_preserved(monkeypatch):
    monkeypatch.setattr(categories, "_", _translate)

    assert (
        categories.normalize_category_input(
            "Без категории", existing_categories=["Без категории"]
        )
        == "Без категории"
    )


def test_blank_input_keeps_optional_category_fields_blank(monkeypatch):
    monkeypatch.setattr(categories, "_", _translate)

    assert categories.normalize_category_input("") == ""


def test_accessible_tree_localizes_label_but_keeps_view_id(monkeypatch):
    monkeypatch.setattr(categories, "_", _translate)
    feed = SimpleNamespace(
        id="feed-1",
        title="Loose Feed",
        category=categories.UNCATEGORIZED,
        unread_count=0,
    )

    entries = accessibility.build_accessible_view_entries(
        [feed], [categories.UNCATEGORIZED]
    )

    category_entry = next(entry for entry in entries if entry["kind"] == "category")
    feed_entry = next(entry for entry in entries if entry["kind"] == "feed")
    assert category_entry["label"] == "Category: Без категории"
    assert category_entry["view_id"] == "category:Uncategorized"
    assert feed_entry["label"] == "Feed: Loose Feed (Без категории)"
