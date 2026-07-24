# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Article-list column layout: which columns show, and in what order (article list columns).

The layout is a list of ``{"key": <column key>, "visible": <bool>}`` entries in
display order. It is stored globally in config under ``"article_columns"`` and,
optionally, per feed under the ``"columns"`` key of that feed's ``feed_settings``
row (the same override channel as the per-feed refresh interval). A per-feed
value of ``None``/absent means "use the global layout".

Title is pinned first and always visible: in a wx ListCtrl report view column 0
is the item label -- it is what ``InsertItem`` writes, what ``GetItemText(row)``
reads, and what a screen reader announces as the row itself. Letting it move or
disappear would change what the row *is*, not just how it is decorated, so
``normalize_layout`` re-pins it rather than trusting stored input.

Labels are deliberately NOT stored: they are translated at display time via
``label_for()``, so a language change re-labels existing layouts (the keys are
the stable identity, the label is presentation).
"""

from __future__ import annotations

from typing import List, Optional

from core.i18n import _

# Column keys in their default display order. Order here is the fallback layout
# and the order in which columns added by a future version get appended to a
# layout saved by an older one.
KEY_TITLE = "title"
KEY_AUTHOR = "author"
KEY_MEDIA = "media"
KEY_DATE = "date"
KEY_FEED = "feed"
KEY_DESCRIPTION = "description"
KEY_STATUS = "status"

DEFAULT_ORDER = (
    KEY_TITLE,
    KEY_AUTHOR,
    KEY_MEDIA,
    KEY_DATE,
    KEY_FEED,
    KEY_DESCRIPTION,
    KEY_STATUS,
)

# The pinned first column (see module docstring).
PINNED_KEY = KEY_TITLE

DEFAULT_WIDTHS = {
    KEY_TITLE: 320,
    KEY_AUTHOR: 110,
    KEY_MEDIA: 110,
    KEY_DATE: 120,
    KEY_FEED: 140,
    KEY_DESCRIPTION: 260,
    KEY_STATUS: 80,
}


def label_for(key: str) -> str:
    """Translated header label for ``key`` (English key -> localized label)."""
    labels = {
        KEY_TITLE: _("Title"),
        KEY_AUTHOR: _("Author"),
        KEY_MEDIA: _("Media"),
        KEY_DATE: _("Date"),
        KEY_FEED: _("Feed"),
        KEY_DESCRIPTION: _("Description"),
        KEY_STATUS: _("Status"),
    }
    return labels.get(key, key)


def width_for(key: str) -> int:
    return int(DEFAULT_WIDTHS.get(key, 120))


def default_layout() -> List[dict]:
    """Every known column, in default order, all visible."""
    return [{"key": key, "visible": True} for key in DEFAULT_ORDER]


def normalize_layout(value) -> List[dict]:
    """Coerce stored/UI input into a valid layout.

    Tolerates anything: unknown keys are dropped, duplicates collapse to their
    first appearance, missing keys are appended in ``DEFAULT_ORDER`` order (so a
    layout saved before a new column existed gains it rather than losing it),
    and the pinned Title column is forced first and visible.
    """
    normalized: List[dict] = []
    seen = set()

    if isinstance(value, (list, tuple)):
        for entry in value:
            key = None
            visible = True
            if isinstance(entry, dict):
                key = entry.get("key")
                visible = bool(entry.get("visible", True))
            elif isinstance(entry, str):
                # Bare key list -- treat as "visible".
                key = entry
            if not isinstance(key, str):
                continue
            key = key.strip().lower()
            if key not in DEFAULT_ORDER or key in seen:
                continue
            seen.add(key)
            normalized.append({"key": key, "visible": visible})

    # Append any column the stored layout never mentioned, in default order.
    for key in DEFAULT_ORDER:
        if key not in seen:
            normalized.append({"key": key, "visible": True})

    # Pin Title first and visible regardless of what was stored.
    normalized = [e for e in normalized if e["key"] != PINNED_KEY]
    normalized.insert(0, {"key": PINNED_KEY, "visible": True})
    return normalized


def visible_keys(layout) -> List[str]:
    """Ordered keys of the columns that should actually be shown."""
    return [e["key"] for e in normalize_layout(layout) if e.get("visible", True)]


def is_default(layout) -> bool:
    return normalize_layout(layout) == default_layout()


def resolve_layout(global_layout, feed_layout=None) -> List[dict]:
    """The layout to display: the per-feed override when set, else the global."""
    if feed_layout is None:
        return normalize_layout(global_layout)
    return normalize_layout(feed_layout)


def move_key(layout, key: str, delta: int) -> List[dict]:
    """Move ``key`` ``delta`` places within ``layout`` (clamped; Title is fixed).

    Returns a new normalized layout. Used by the reorder buttons in Settings and
    the Feed Properties dialog.
    """
    entries = normalize_layout(layout)
    if key == PINNED_KEY:
        return entries
    index = next((i for i, e in enumerate(entries) if e["key"] == key), None)
    if index is None:
        return entries
    # Index 0 is the pinned column: movable columns live in [1, len-1].
    target = max(1, min(len(entries) - 1, index + int(delta)))
    if target == index:
        return entries
    entry = entries.pop(index)
    entries.insert(target, entry)
    return entries


def set_visible(layout, key: str, visible: bool) -> List[dict]:
    """Show/hide ``key``; the pinned Title column ignores hide requests."""
    entries = normalize_layout(layout)
    if key == PINNED_KEY:
        return entries
    for entry in entries:
        if entry["key"] == key:
            entry["visible"] = bool(visible)
    return entries


def feed_layout_from_settings(settings) -> Optional[List[dict]]:
    """Per-feed override out of a ``feed_settings`` dict, or None to inherit."""
    if not isinstance(settings, dict):
        return None
    raw = settings.get("columns")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    return normalize_layout(raw)
