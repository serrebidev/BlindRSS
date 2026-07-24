# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Smart Folders: user-defined, rule-based virtual folders over local articles.

A rule is a boolean tree of groups and leaf conditions:

    group = {"match": "all" | "any", "conditions": [ <leaf> | <group>, ... ]}
    leaf  = {"field": <field>, "op": <op>, "value": <value>}

    match "all" = AND, "any" = OR. Groups nest, so (A AND B) OR C is expressible.

Fields:
    Boolean (op "is", value truthy/falsy):
        read, favorite, opened, updated
    Text (op contains | not_contains | equals | starts_with, value str):
        title, content, description, author, feed, url

The same rule is evaluated two equivalent ways, kept deliberately in lock-step:

    build_where(rule) -> (sql, params)
        A SQL boolean expression over an articles query that aliases the
        `articles` table as `a` and LEFT JOINs `feeds` as `f`.
    rule_matches(rule, article) -> bool
        Pure-Python evaluation against a dict of the same fields, used for tests
        and any in-memory filtering.

Unknown/empty leaves are skipped in BOTH paths so the two never diverge. An empty
"all" group matches everything; an empty "any" group matches nothing.
"""
from __future__ import annotations

BOOL_FIELDS = ("read", "favorite", "opened", "updated")
# "tag" matches the newline-separated site tags/categories stored in
# articles.tags (see providers.local tag extraction). In the Python evaluator the
# article dict carries them under the same "tag" key.
TEXT_FIELDS = ("title", "content", "description", "author", "feed", "url", "tag")
TEXT_OPS = ("contains", "not_contains", "equals", "starts_with")

# Text field -> SQL column (articles aliased `a`, feeds aliased `f`).
_TEXT_COLS = {
    "title": "a.title",
    "content": "a.content",
    "description": "a.description",
    "author": "a.author",
    "feed": "f.title",
    "url": "a.url",
    "tag": "a.tags",
}
_BOOL_COLS = {
    "read": "a.is_read",
    "favorite": "a.is_favorite",
}
_UPDATED_EXPR = "(SELECT COUNT(*) FROM article_versions v WHERE v.article_id = a.id)"


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _is_group(node) -> bool:
    return isinstance(node, dict) and ("conditions" in node or "match" in node) and "field" not in node


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --------------------------------------------------------------------------
# SQL compilation
# --------------------------------------------------------------------------

def _compile_leaf(cond):
    field = str(cond.get("field") or "").lower()
    op = str(cond.get("op") or "").lower()
    value = cond.get("value")

    if field in BOOL_FIELDS:
        want = _as_bool(value)
        if field == "opened":
            return ("a.opened_at IS NOT NULL" if want else "a.opened_at IS NULL"), []
        if field == "updated":
            return (f"{_UPDATED_EXPR} > 1" if want else f"{_UPDATED_EXPR} <= 1"), []
        col = _BOOL_COLS[field]
        return f"{col} = ?", [1 if want else 0]

    if field in _TEXT_COLS:
        col = _TEXT_COLS[field]
        low = str(value or "").lower()
        # py_lower (registered in db.get_connection) is Unicode-aware; SQLite's
        # built-in LOWER() only folds ASCII, which would diverge from the
        # Python-lowercased needle on accented/non-Latin terms.
        if op == "equals":
            return f"py_lower({col}) = ?", [low]
        esc = _like_escape(low)
        if op == "starts_with":
            return f"py_lower({col}) LIKE ? ESCAPE '\\'", [esc + "%"]
        if op == "not_contains":
            return f"({col} IS NULL OR py_lower({col}) NOT LIKE ? ESCAPE '\\')", ["%" + esc + "%"]
        # default / "contains"
        return f"py_lower({col}) LIKE ? ESCAPE '\\'", ["%" + esc + "%"]

    return "", []  # unknown field -> skip


def _compile_group(group):
    match = str(group.get("match") or "all").lower()
    joiner = " OR " if match == "any" else " AND "
    parts = []
    params: list = []
    for cond in group.get("conditions") or []:
        if _is_group(cond):
            sub_sql, sub_params = _compile_group(cond)
        else:
            sub_sql, sub_params = _compile_leaf(cond)
        if sub_sql:
            parts.append(sub_sql)
            params.extend(sub_params)
    if not parts:
        return ("1=0" if match == "any" else "1=1"), []
    return "(" + joiner.join(parts) + ")", params


def build_where(rule):
    """Compile a rule into a (sql_expression, params) pair.

    The SQL references `a` (articles) and `f` (feeds, LEFT JOINed). The caller is
    responsible for the surrounding SELECT/FROM/JOIN and ORDER BY.
    """
    if not isinstance(rule, dict):
        return "1=1", []
    return _compile_group(rule)


# --------------------------------------------------------------------------
# Pure-Python evaluation (mirror of the SQL semantics)
# --------------------------------------------------------------------------

def _match_leaf(cond, art):
    """Return True/False, or None to skip (unknown field)."""
    field = str(cond.get("field") or "").lower()
    op = str(cond.get("op") or "").lower()
    value = cond.get("value")

    if field in BOOL_FIELDS:
        return bool(art.get(field)) == _as_bool(value)

    if field in TEXT_FIELDS:
        hay = str(art.get(field) or "").lower()
        needle = str(value or "").lower()
        if op == "equals":
            return hay == needle
        if op == "starts_with":
            return hay.startswith(needle)
        if op == "not_contains":
            return needle not in hay
        return needle in hay  # contains

    return None


def _match_group(group, art):
    match = str(group.get("match") or "all").lower()
    results = []
    for cond in group.get("conditions") or []:
        if _is_group(cond):
            results.append(_match_group(cond, art))
        else:
            r = _match_leaf(cond, art)
            if r is None:
                continue
            results.append(r)
    if not results:
        return match != "any"  # empty all -> True, empty any -> False
    return any(results) if match == "any" else all(results)


def rule_matches(rule, article) -> bool:
    """Evaluate a rule against an article dict.

    `article` keys: title, content, description, author, feed, url (str) and
    read, favorite, opened, updated (bool).
    """
    if not isinstance(rule, dict):
        return True
    return bool(_match_group(rule, article))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Flat builder UI <-> rule conversion (pure, so the dialog stays testable)
# --------------------------------------------------------------------------

# Self-contained boolean row keys used by the flat builder: key -> (field, value).
BOOL_ROW_KEYS = {
    "read_no": ("read", False),
    "read_yes": ("read", True),
    "fav_yes": ("favorite", True),
    "fav_no": ("favorite", False),
    "opened_yes": ("opened", True),
    "opened_no": ("opened", False),
    "updated_yes": ("updated", True),
    "updated_no": ("updated", False),
}


def condition_from_row(field_key, op, value):
    """Map one flat builder row to a rule condition, or None to skip the row."""
    field_key = str(field_key or "")
    if not field_key:
        return None
    if field_key in TEXT_FIELDS:
        val = value.strip() if isinstance(value, str) else value
        if (val is None or val == "") and op != "equals":
            return None
        return {"field": field_key, "op": op or "contains", "value": val or ""}
    if field_key in BOOL_ROW_KEYS:
        bf, bv = BOOL_ROW_KEYS[field_key]
        return {"field": bf, "op": "is", "value": bool(bv)}
    return None


def rule_from_rows(match, rows) -> dict:
    """Build a rule from (field_key, op, value) rows + a top-level match mode."""
    conditions = []
    for field_key, op, value in rows:
        cond = condition_from_row(field_key, op, value)
        if cond is not None:
            conditions.append(cond)
    match = str(match or "all").lower()
    return {"match": "any" if match == "any" else "all", "conditions": conditions}


def row_from_condition(cond):
    """Map a rule condition back to a (field_key, op, value) row, or None if it
    cannot be shown in the flat builder (e.g. a nested group)."""
    if _is_group(cond) or not isinstance(cond, dict) or "field" not in cond:
        return None
    field = str(cond.get("field") or "").lower()
    if field in TEXT_FIELDS:
        value = cond.get("value")
        return field, str(cond.get("op") or "contains").lower(), ("" if value is None else str(value))
    value = cond.get("value")
    want = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
    for rk, (bf, bv) in BOOL_ROW_KEYS.items():
        if bf == field and bool(bv) == bool(want):
            return rk, "is", ""
    return None


def rows_from_rule(rule):
    """Split a rule into (match, [(field_key, op, value), ...]) for the flat builder."""
    match = str((rule or {}).get("match") or "all").lower()
    if match not in ("all", "any"):
        match = "all"
    rows = []
    for cond in (rule or {}).get("conditions") or []:
        row = row_from_condition(cond)
        if row is not None:
            rows.append(row)
    return match, rows


def normalize_rule(rule) -> dict:
    """Coerce arbitrary input into a well-formed top-level group."""
    if not isinstance(rule, dict):
        return {"match": "all", "conditions": []}
    match = str(rule.get("match") or "all").lower()
    if match not in ("all", "any"):
        match = "all"
    conditions = rule.get("conditions")
    if not isinstance(conditions, list):
        conditions = []
    return {"match": match, "conditions": conditions}


def _describe_leaf(cond) -> str:
    field = str(cond.get("field") or "").lower()
    op = str(cond.get("op") or "").lower()
    value = cond.get("value")
    if field in BOOL_FIELDS:
        want = _as_bool(value)
        labels = {
            ("read", True): "is read",
            ("read", False): "is unread",
            ("favorite", True): "is a favorite",
            ("favorite", False): "is not a favorite",
            ("opened", True): "has been opened",
            ("opened", False): "has not been opened",
            ("updated", True): "was updated",
            ("updated", False): "was not updated",
        }
        return labels.get((field, want), field)
    if field in TEXT_FIELDS:
        verb = {
            "contains": "contains",
            "not_contains": "does not contain",
            "equals": "equals",
            "starts_with": "starts with",
        }.get(op, "contains")
        return f'{field} {verb} "{value}"'
    return ""


def describe_rule(rule) -> str:
    """A short, screen-reader-friendly summary of a rule."""
    if not isinstance(rule, dict):
        return "all articles"

    def _describe_group(group):
        match = str(group.get("match") or "all").lower()
        joiner = " OR " if match == "any" else " AND "
        parts = []
        for cond in group.get("conditions") or []:
            if _is_group(cond):
                inner = _describe_group(cond)
                if inner:
                    parts.append(f"({inner})")
            else:
                d = _describe_leaf(cond)
                if d:
                    parts.append(d)
        return joiner.join(parts)

    text = _describe_group(rule)
    return text or "all articles"
