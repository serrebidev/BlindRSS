# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Stable category identities and display-time localization helpers.

``Uncategorized`` is persisted in SQLite, provider APIs, OPML logic, filter
rules, and configuration.  It must remain an English sentinel regardless of
the active UI language; only its presentation is translated.
"""

from collections.abc import Iterable

from core.i18n import _


UNCATEGORIZED = "Uncategorized"


def category_display_name(category) -> str:
    """Return a user-facing category name without changing its identity."""
    value = str(category or "").strip()
    if not value or value == UNCATEGORIZED:
        return _("Uncategorized")
    return value


def normalize_category_input(value, existing_categories: Iterable[str] = ()) -> str:
    """Map the localized system-folder label back to its stable sentinel.

    A real category whose stored name equals the current translation wins over
    the display alias.  This keeps editable category fields usable even in the
    unusual case where a user created a category with that exact name.
    Blank input remains blank because several callers use it to mean "none".
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if text.casefold() == UNCATEGORIZED.casefold():
        return UNCATEGORIZED

    translated = _("Uncategorized").strip()
    if translated and text.casefold() == translated.casefold():
        real_names = {
            str(category or "").strip().casefold()
            for category in (existing_categories or ())
            if str(category or "").strip() != UNCATEGORIZED
        }
        if text.casefold() not in real_names:
            return UNCATEGORIZED
    return text


def is_uncategorized(value) -> bool:
    """Accept the stable identity and the current display translation."""
    text = str(value or "").strip()
    if not text:
        return True
    return text.casefold() in {
        UNCATEGORIZED.casefold(),
        _("Uncategorized").strip().casefold(),
    }
