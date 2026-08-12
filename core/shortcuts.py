# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Central registry of user-editable keyboard shortcuts (NVDA-gestures style).

This module is deliberately pure (no wx) so the command table and the
accelerator-string parsing/normalization are unit-testable without a GUI.

An *accelerator string* is a ``+``-joined list of modifier tokens followed by a
single key token, e.g. ``"Ctrl+Shift+P"``, ``"Ctrl+Left"``, ``"Ctrl+Shift+."``.
Modifiers are normalized to the canonical order Ctrl, Alt, Shift, Cmd. An
empty/blank string means the command is *unbound*.

The GUI layer (``gui.shortcut_keys``) maps these strings to/from wx key events
and dispatches commands from the global char-hook; the editable dialog
(Keyboard Shortcuts) reads/writes user overrides which are merged over the
defaults here.
"""
from __future__ import annotations

from collections import namedtuple, OrderedDict
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Command table
# --------------------------------------------------------------------------

# label/category are English msgids; the dialog wraps them with _() at display
# time. `id` is the stable key used in config overrides and dispatch handlers.
Command = namedtuple("Command", "id category label default")

# NOTE: keep ids stable — they are persisted in config under "keyboard_shortcuts".
# An empty default means the command ships unbound; the user can give it any
# key from Tools > Keyboard Shortcuts. Defaults that used to be hard-coded
# accelerators (F5, Ctrl+N, Ctrl+1..6, ...) keep their historical keys.
COMMANDS: List[Command] = [
    Command("feeds.add", "Feeds", "Add Feed", "Ctrl+N"),
    Command("feeds.detect_page", "Feeds", "Detect Feeds on Page", ""),
    Command("feeds.remove", "Feeds", "Remove Feed", ""),
    Command("feeds.refresh_all", "Feeds", "Refresh Feeds", "F5"),
    Command("feeds.stop_refresh", "Feeds", "Stop Refresh", "Shift+F5"),
    Command("feeds.refresh_selected", "Feeds", "Refresh Feed", "Ctrl+F5"),
    Command("feeds.edit_selected", "Feeds", "Edit Feed or Category", "F2"),
    Command("feeds.mark_all_read", "Feeds", "Mark All Items as Read", "Ctrl+Shift+R"),
    Command("feeds.view_errors", "Feeds", "View Feed Errors", ""),
    Command("feeds.copy_url", "Feeds", "Copy Feed URL", ""),
    Command("feeds.add_category", "Feeds", "Add Category", ""),
    Command("feeds.remove_category", "Feeds", "Remove Category", ""),
    Command("feeds.import_opml", "Feeds", "Import OPML", ""),
    Command("feeds.import_youtube_takeout", "Feeds", "Import YouTube Takeout", ""),
    Command("feeds.export_opml", "Feeds", "Export OPML", ""),
    Command("feeds.find_podcast", "Feeds", "Find a Podcast or RSS Feed", "Ctrl+Shift+F"),
    Command("feeds.video_search", "Feeds", "Video Search", ""),

    Command("media.open_url", "Media", "Open Media URL", ""),

    Command("article.open_browser", "Articles", "Open in Browser", ""),
    Command("article.copy_link", "Articles", "Copy Link", ""),
    Command("article.copy_media_link", "Articles", "Copy Media Link", ""),
    Command("article.copy_text", "Articles", "Copy Text", ""),
    Command("article.toggle_read", "Articles", "Toggle Read/Unread", ""),
    Command("article.toggle_favorite", "Articles", "Add to or Remove from Favorites", "Ctrl+D"),
    Command("article.delete", "Articles", "Delete Article", ""),
    Command("article.download", "Articles", "Download", ""),
    Command("article.download_as", "Articles", "Download As", ""),
    Command("article.toggle_queue", "Articles", "Add to or Remove from Play Queue", ""),
    Command("article.view_description", "Articles", "View Feed Description", ""),

    Command("view.focus_search", "View", "Focus Search Field", "Ctrl+E"),
    Command("view.toggle_search", "View", "Show or Hide Search Field", ""),
    Command("view.rich_view", "View", "Rich Full-Text View", "Ctrl+Shift+H"),
    Command("view.accessible_browser", "View", "Open Accessible Browser", ""),

    Command("filter.read_all", "Article Filter", "All Articles", "Ctrl+1"),
    Command("filter.read_unread", "Article Filter", "Unread Only", "Ctrl+2"),
    Command("filter.read_read", "Article Filter", "Read Only", "Ctrl+3"),
    Command("filter.media_all", "Article Filter", "Media and Non-media", "Ctrl+4"),
    Command("filter.media_with", "Article Filter", "With Media Only", "Ctrl+5"),
    Command("filter.media_without", "Article Filter", "Without Media Only", "Ctrl+6"),

    Command("sort.date", "Sorting", "Sort by Date", ""),
    Command("sort.name", "Sorting", "Sort by Name", ""),
    Command("sort.author", "Sorting", "Sort by Author", ""),
    Command("sort.description", "Sorting", "Sort by Description", ""),
    Command("sort.feed", "Sorting", "Sort by Feed", ""),
    Command("sort.status", "Sorting", "Sort by Status", ""),
    Command("sort.ascending", "Sorting", "Toggle Ascending Sort", ""),

    Command("player.play_pause", "Player", "Play/Pause", "Ctrl+P"),
    Command("player.stop", "Player", "Stop", "Ctrl+S"),
    Command("player.show_hide", "Player", "Show/Hide Player", "Ctrl+Shift+P"),
    Command("player.equalizer", "Player", "Open Equalizer", "Ctrl+Shift+E"),
    Command("player.chapters", "Player", "Show Chapters", ""),

    Command("queue.open", "Play Queue", "Open Play Queue", "Ctrl+Shift+C"),
    Command("queue.next", "Play Queue", "Play Next in Queue", "Ctrl+Shift+T"),
    Command("queue.prev", "Play Queue", "Play Previous in Queue", "Ctrl+Shift+V"),

    # Speed defaults are letters, not punctuation/digits: Ctrl+Shift+. is a
    # popular NVDA add-on gesture (e.g. windowsOfProcess "switch process") and
    # Windows registers Ctrl+Shift+<digit> as input-language direct-switch
    # hotkeys ("Ctrl+Shift+0 does nothing" is a classic) — both are consumed
    # system-wide before any app sees the key, so those combos can be dead on a
    # user's machine while the same handlers work fine from the menu.
    Command("speed.up", "Playback Speed", "Increase Playback Speed", "Ctrl+Shift+U"),
    Command("speed.down", "Playback Speed", "Decrease Playback Speed", "Ctrl+Shift+D"),
    Command("speed.reset", "Playback Speed", "Reset Playback Speed (1x)", "Ctrl+Shift+N"),

    Command("tools.filter_rules", "Tools", "Filter Rules", ""),
    Command("tools.import_site_cookies", "Tools", "Import Site Cookies", ""),
    Command("tools.persistent_search", "Tools", "Configure Persistent Search", ""),
    Command("tools.keyboard_shortcuts", "Tools", "Keyboard Shortcuts", ""),
    Command("tools.settings", "Tools", "Settings", "Ctrl+,"),
    Command("tools.check_updates", "Tools", "Check for Updates", ""),
    # Speaks the running version outright. A screen reader's own app-version
    # command (NVDA, JAWS) reads the exe's VERSIONINFO resource, which the
    # build stamps and verifies; this is the in-app answer to the same
    # question, and it works from a source checkout too, where the process is
    # python.exe and the screen reader would report Python's version instead.
    Command("tools.announce_version", "Tools", "Announce Version", "Ctrl+Shift+A"),
]

_COMMANDS_BY_ID: "OrderedDict[str, Command]" = OrderedDict((c.id, c) for c in COMMANDS)


def _(text):  # noqa: A001 - gettext-noop marker for tools/extract_strings.py
    """Identity gettext marker.

    This module is GUI-free and does its gettext at display time in the GUI
    (``_(cmd.label)`` / ``_(cmd.category)`` in the Keyboard Shortcuts dialog),
    which the AST-based POT extractor cannot follow. Listing every displayed
    msgid through this no-op ``_`` records them in ``locale/blindrss.pot`` so
    the dialog is translatable. Keep in sync with COMMANDS above.
    """
    return text


_POT_ANCHORS = (
    # Categories
    _("Feeds"),
    _("Articles"),
    _("Media"),
    _("View"),
    _("Article Filter"),
    _("Sorting"),
    _("Player"),
    _("Play Queue"),
    _("Playback Speed"),
    _("Tools"),
    # Command labels
    _("Add Feed"),
    _("Detect Feeds on Page"),
    _("Remove Feed"),
    _("Refresh Feeds"),
    _("Stop Refresh"),
    _("Refresh Feed"),
    _("Edit Feed or Category"),
    _("Mark All Items as Read"),
    _("View Feed Errors"),
    _("Copy Feed URL"),
    _("Add Category"),
    _("Remove Category"),
    _("Import OPML"),
    _("Import YouTube Takeout"),
    _("Export OPML"),
    _("Find a Podcast or RSS Feed"),
    _("Video Search"),
    _("Open Media URL"),
    _("Open in Browser"),
    _("Copy Link"),
    _("Copy Media Link"),
    _("Copy Text"),
    _("Toggle Read/Unread"),
    _("Add to or Remove from Favorites"),
    _("Delete Article"),
    _("Download"),
    _("Download As"),
    _("Add to or Remove from Play Queue"),
    _("View Feed Description"),
    _("Focus Search Field"),
    _("Show or Hide Search Field"),
    _("Rich Full-Text View"),
    _("Open Accessible Browser"),
    _("All Articles"),
    _("Unread Only"),
    _("Read Only"),
    _("Media and Non-media"),
    _("With Media Only"),
    _("Without Media Only"),
    _("Sort by Date"),
    _("Sort by Name"),
    _("Sort by Author"),
    _("Sort by Description"),
    _("Sort by Feed"),
    _("Sort by Status"),
    _("Toggle Ascending Sort"),
    _("Play/Pause"),
    _("Stop"),
    _("Show/Hide Player"),
    _("Open Equalizer"),
    _("Show Chapters"),
    _("Open Play Queue"),
    _("Play Next in Queue"),
    _("Play Previous in Queue"),
    _("Increase Playback Speed"),
    _("Decrease Playback Speed"),
    _("Reset Playback Speed (1x)"),
    _("Filter Rules"),
    _("Import Site Cookies"),
    _("Configure Persistent Search"),
    _("Keyboard Shortcuts"),
    _("Settings"),
    _("Check for Updates"),
    _("Announce Version"),
)


def iter_commands() -> List[Command]:
    return list(COMMANDS)


def command_by_id(command_id: str) -> Optional[Command]:
    return _COMMANDS_BY_ID.get(str(command_id))


def categories() -> List[str]:
    """Distinct categories in first-seen (display) order."""
    seen: List[str] = []
    for c in COMMANDS:
        if c.category not in seen:
            seen.append(c.category)
    return seen


def commands_in_category(category: str) -> List[Command]:
    return [c for c in COMMANDS if c.category == category]


# --------------------------------------------------------------------------
# Accelerator-string parsing / normalization
# --------------------------------------------------------------------------

_MOD_ALIASES = {
    "ctrl": "Ctrl", "control": "Ctrl", "ctl": "Ctrl",
    "alt": "Alt", "option": "Alt", "opt": "Alt",
    "shift": "Shift",
    "cmd": "Cmd", "command": "Cmd", "win": "Cmd", "meta": "Cmd", "super": "Cmd",
}
# Canonical display + comparison order.
_MOD_ORDER = ["Ctrl", "Alt", "Shift", "Cmd"]

# Named keys: lowercased spelling -> canonical token.
_NAMED_KEYS = {
    "space": "Space",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "home": "Home", "end": "End",
    "pageup": "PageUp", "pgup": "PageUp",
    "pagedown": "PageDown", "pgdn": "PageDown",
    "insert": "Insert", "ins": "Insert",
    "delete": "Delete", "del": "Delete",
    "backspace": "Backspace", "back": "Backspace",
    "enter": "Enter", "return": "Enter",
    "tab": "Tab",
    "escape": "Escape", "esc": "Escape",
    # Punctuation spellings that some callers may pass.
    "comma": ",", "period": ".", "dot": ".",
    "slash": "/", "minus": "-", "dash": "-",
    "equals": "=", "equal": "=", "plus": "+",
    "semicolon": ";", "quote": "'",
    "leftbracket": "[", "rightbracket": "]",
    "backslash": "\\", "backtick": "`", "grave": "`",
}


def _normalize_key(token: str) -> Optional[str]:
    """Return the canonical key token, or None if it is not a usable key."""
    if token is None:
        return None
    raw = str(token).strip()
    if not raw:
        return None
    low = raw.lower()
    if low in _NAMED_KEYS:
        return _NAMED_KEYS[low]
    # Function keys F1..F24
    if low[0] == "f" and low[1:].isdigit():
        n = int(low[1:])
        if 1 <= n <= 24:
            return "F" + str(n)
    if len(raw) == 1:
        ch = raw
        if ch.isalpha():
            return ch.upper()
        # digit or punctuation kept literal
        return ch
    return None


def parse_accel(accel: Optional[str]) -> Optional[Tuple[Tuple[str, ...], str]]:
    """Parse an accelerator string into ``(ordered_mods, key_token)``.

    Returns None for an empty/blank string (unbound) or a malformed value.
    """
    if accel is None:
        return None
    raw = str(accel).strip()
    if not raw:
        return None

    # Special-case a literal '+' key so "Ctrl+Shift++" parses correctly.
    if raw.endswith("+") and len(raw) > 1:
        mod_part = raw[:-1].rstrip("+")
        mods_raw = [m for m in mod_part.split("+") if m.strip()]
        key_raw = "+"
    else:
        parts = raw.split("+")
        key_raw = parts[-1]
        mods_raw = parts[:-1]

    mods: List[str] = []
    for m in mods_raw:
        canon = _MOD_ALIASES.get(m.strip().lower())
        if canon is None:
            return None
        if canon not in mods:
            mods.append(canon)

    key = _normalize_key(key_raw)
    if not key:
        return None

    ordered = tuple(m for m in _MOD_ORDER if m in mods)
    return ordered, key


def format_accel(mods, key: str) -> str:
    """Build a canonical accelerator string from modifiers + a key token."""
    if not key:
        return ""
    present = set(mods or ())
    ordered = [m for m in _MOD_ORDER if m in present]
    return "+".join(ordered + [str(key)])


def normalize_accel(accel: Optional[str]) -> str:
    """Return the canonical form of an accelerator string, or "" if unbound/invalid."""
    parsed = parse_accel(accel)
    if parsed is None:
        return ""
    mods, key = parsed
    return format_accel(mods, key)


# --------------------------------------------------------------------------
# Binding resolution (defaults + user overrides)
# --------------------------------------------------------------------------

def default_bindings() -> "OrderedDict[str, str]":
    return OrderedDict((c.id, normalize_accel(c.default)) for c in COMMANDS)


def resolve_bindings(overrides: Optional[Dict[str, object]]) -> "OrderedDict[str, str]":
    """Merge user overrides over the defaults.

    An override value may be a string (custom binding), "" or None (explicitly
    unbound). Unknown ids in `overrides` are ignored. Result maps every known
    command id -> canonical accel string ("" meaning unbound).
    """
    ov = overrides if isinstance(overrides, dict) else {}
    out: "OrderedDict[str, str]" = OrderedDict()
    for c in COMMANDS:
        if c.id in ov:
            out[c.id] = normalize_accel(ov.get(c.id))
        else:
            out[c.id] = normalize_accel(c.default)
    return out


def find_conflicts(bindings: Dict[str, str]) -> "OrderedDict[str, List[str]]":
    """Return accel -> [command_ids] for any accel bound to more than one command."""
    by_accel: "OrderedDict[str, List[str]]" = OrderedDict()
    for cmd_id, accel in (bindings or {}).items():
        norm = normalize_accel(accel)
        if not norm:
            continue
        by_accel.setdefault(norm, []).append(cmd_id)
    return OrderedDict((a, ids) for a, ids in by_accel.items() if len(ids) > 1)


def invert_bindings(bindings: Dict[str, str]) -> Dict[str, str]:
    """Map canonical accel -> command_id (last write wins on conflicts)."""
    out: Dict[str, str] = {}
    for cmd_id, accel in (bindings or {}).items():
        norm = normalize_accel(accel)
        if norm:
            out[norm] = cmd_id
    return out
