# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Filter Rules: an ordered pipeline of user-defined rules over incoming (and
existing) articles — BlindRSS's article-categorization engine.

Each rule pairs a Smart-Folders boolean rule tree (see ``core.smart_folders``)
with an *action set*. Rules run in ``position`` order like email filters: every
enabled rule whose condition matches contributes its actions; a rule flagged
``stop`` halts the pipeline for that article once it has matched.

This module is GUI-free and side-effect-light so it stays unit-testable:

    evaluate_pipeline(rules, article) -> aggregate
        Pure. Which actions fire for one article, honoring order + stop.
    resolve_effective_actions(aggregate, delete_behavior) -> effective
        Pure. Folds the abstract "delete" action into concrete operations
        (move-to-category / permanent purge / soft delete) per the configured
        delete behavior.
    apply_effective_actions(cursor, article_id, effective, *, snapshot, feed_id)
        The only DB-touching entry point; every write goes through db helpers.

Action set schema (actions_json per rule); all keys optional::

    {
        "move": "Parent / Child" | null,   # MOVE the article to this category
        "label": "Parent / Child" | null,  # ALSO show it under this category
        "mark_read": bool,
        "mark_favorite": bool,
        "delete": bool,                     # honors the delete-behavior setting
        "skip_notification": bool,          # suppress the new-article toast
    }
"""
from __future__ import annotations

from core import smart_folders as _sf

# Boolean action keys OR-combined across matching rules.
BOOL_ACTIONS = ("mark_read", "mark_favorite", "delete", "skip_notification")


def normalize_actions(actions) -> dict:
    """Coerce arbitrary input into a well-formed action set."""
    if not isinstance(actions, dict):
        actions = {}
    move = actions.get("move")
    move = str(move).strip() if move not in (None, "") else None
    label = actions.get("label")
    label = str(label).strip() if label not in (None, "") else None
    out = {"move": move or None, "label": label or None}
    for key in BOOL_ACTIONS:
        out[key] = _as_bool(actions.get(key))
    return out


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def actions_are_empty(actions) -> bool:
    """True when a rule would do nothing (used to reject blank rules in the UI)."""
    a = normalize_actions(actions)
    return not (a["move"] or a["label"] or any(a[k] for k in BOOL_ACTIONS))


def evaluate_pipeline(rules, article) -> dict:
    """Run the ordered rule pipeline against one article dict.

    ``rules`` is a list of dicts as returned by ``db.list_filter_rules`` (keys
    ``rule``, ``actions``, ``enabled``, ``stop``). Disabled rules are skipped.
    Returns an aggregate::

        {
            "move": str | None,       # last matching move wins
            "labels": [str, ...],     # union of matching labels, in first-seen order
            "mark_read": bool, "mark_favorite": bool,
            "delete": bool, "skip_notification": bool,
            "matched_rule_ids": [str, ...],
        }
    """
    agg = {
        "move": None,
        "labels": [],
        "mark_read": False,
        "mark_favorite": False,
        "delete": False,
        "skip_notification": False,
        "matched_rule_ids": [],
    }
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        if not rule.get("enabled", True):
            continue
        condition = rule.get("rule")
        if not _sf.rule_matches(condition, article):
            continue
        agg["matched_rule_ids"].append(rule.get("id"))
        actions = normalize_actions(rule.get("actions"))
        if actions["move"]:
            agg["move"] = actions["move"]
        if actions["label"] and actions["label"] not in agg["labels"]:
            agg["labels"].append(actions["label"])
        for key in BOOL_ACTIONS:
            if actions[key]:
                agg[key] = True
        if rule.get("stop"):
            break
    return agg


# ── Delete behavior ──────────────────────────────────────────────────────────

def parse_delete_behavior(value):
    """Parse a delete-behavior string into ``(kind, category)``.

    ``kind`` is "deleted" (soft delete / tombstone, the default), "purge"
    (permanent), or "category" (move to ``category``). Unknown/empty values fall
    back to the safe default ("deleted", None).
    """
    text = str(value or "").strip()
    if not text:
        return ("deleted", None)
    low = text.lower()
    if low == "purge":
        return ("purge", None)
    if low == "deleted":
        return ("deleted", None)
    if low.startswith("category:"):
        cat = text.split(":", 1)[1].strip()
        return ("category", cat) if cat else ("deleted", None)
    return ("deleted", None)


def resolve_effective_actions(aggregate, delete_behavior) -> dict:
    """Fold the abstract "delete" action into concrete operations.

    Returns::

        {
            "move": str | None,     # includes delete->category
            "labels": [str, ...],
            "mark_read": bool, "mark_favorite": bool,
            "remove": bool,         # tombstone + physically remove the row
            "purge": bool,          # tombstone marked purged=1
            "skip_notification": bool,
        }

    Delete-to-category takes precedence over an explicit "move" so a rule that
    both moves and deletes ends up in the delete target (the more specific of the
    two user intents), matching the "Delete moves to <category>" setting.
    """
    agg = dict(aggregate or {})
    eff = {
        "move": agg.get("move") or None,
        "labels": list(agg.get("labels") or []),
        "mark_read": bool(agg.get("mark_read")),
        "mark_favorite": bool(agg.get("mark_favorite")),
        "remove": False,
        "purge": False,
        "skip_notification": bool(agg.get("skip_notification")),
    }
    if agg.get("delete"):
        kind, category = parse_delete_behavior(delete_behavior)
        if kind == "category" and category:
            eff["move"] = category
        elif kind == "purge":
            eff["purge"] = True
        else:
            eff["remove"] = True
    return eff


def effective_removes_article(effective) -> bool:
    """True when the effective actions take the article out of normal views."""
    return bool(effective.get("remove") or effective.get("purge"))


# ── DB application ───────────────────────────────────────────────────────────

def apply_effective_actions(cursor, article_id, effective, *, snapshot=None, feed_id=None):
    """Apply resolved actions to a stored local article using a live cursor.

    Every write goes through ``core.db`` helpers (passing the cursor so the whole
    thing stays inside the caller's transaction). ``snapshot`` and ``feed_id``
    are only needed when the article is removed/purged (to write the tombstone).
    Returns True if the article was removed from normal views.
    """
    from core import db as _db

    aid = str(article_id or "").strip()
    if not aid or not isinstance(effective, dict):
        return False

    if effective.get("mark_read"):
        cursor.execute("UPDATE articles SET is_read = 1 WHERE id = ?", (aid,))
    if effective.get("mark_favorite"):
        cursor.execute("UPDATE articles SET is_favorite = 1 WHERE id = ?", (aid,))
    if effective.get("move"):
        _db.set_article_category_override(aid, effective["move"], cursor=cursor)
    for label in effective.get("labels") or []:
        _db.add_article_label(aid, label, cursor=cursor)

    if effective.get("remove") or effective.get("purge"):
        _tombstone_and_remove(
            cursor,
            aid,
            snapshot=snapshot,
            feed_id=feed_id,
            purged=bool(effective.get("purge")),
        )
        return True
    return False


def _tombstone_and_remove(cursor, article_id, *, snapshot=None, feed_id=None, purged=False):
    """Record a delete tombstone (so refresh never resurrects it) then drop the
    article row and its local chapter data — the same invariant the interactive
    delete path upholds."""
    from core import db as _db

    fid = feed_id
    url = None
    snap = snapshot
    if snap is None or fid is None:
        cursor.execute(
            "SELECT feed_id, url, title, content, description, date, author, "
            "media_url, media_type, chapter_url, is_read, is_favorite "
            "FROM articles WHERE id = ? LIMIT 1",
            (article_id,),
        )
        row = cursor.fetchone()
        if not row:
            return
        fid = fid or row[0]
        url = row[1]
        snap = {
            "title": row[2], "content": row[3], "description": row[4], "date": row[5],
            "author": row[6], "media_url": row[7], "media_type": row[8],
            "chapter_url": row[9], "is_read": row[10], "is_favorite": row[11],
        }
    else:
        url = snap.get("url")
    _db.remember_deleted_article(fid, article_id, url, snapshot=snap, purged=purged, cursor=cursor)
    cursor.execute("DELETE FROM article_labels WHERE article_id = ?", (article_id,))
    cursor.execute("DELETE FROM chapters WHERE article_id = ?", (article_id,))
    local_cache_key = f"local:{article_id}"
    cursor.execute("DELETE FROM chapter_cache WHERE cache_key = ?", (local_cache_key,))
    cursor.execute("DELETE FROM chapter_sources WHERE cache_key = ?", (local_cache_key,))
    cursor.execute("DELETE FROM articles WHERE id = ?", (article_id,))


# ── Screen-reader-friendly summaries ─────────────────────────────────────────

def describe_actions(actions) -> str:
    """A short, screen-reader-friendly summary of a rule's actions."""
    a = normalize_actions(actions)
    parts = []
    if a["move"]:
        parts.append(f'move to "{a["move"]}"')
    if a["label"]:
        parts.append(f'label "{a["label"]}"')
    if a["mark_read"]:
        parts.append("mark as read")
    if a["mark_favorite"]:
        parts.append("mark as favorite")
    if a["delete"]:
        parts.append("delete")
    if a["skip_notification"]:
        parts.append("skip notification")
    return ", ".join(parts) if parts else "do nothing"
