# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Configurable screen-reader announcements for key events (issue #67).

BlindRSS confirms critical keyboard actions (filter change, read/unread toggle,
start/stop update, playback-speed change, media/chapter navigation) with an
explicit speech and/or Braille announcement so a screen-reader user gets
immediate, direct feedback instead of having to infer success from indirect
cues.

This module is deliberately GUI-free so the event table, mode resolution, and
the emit path are unit-testable without wx. Output is produced through the
``accessible-output2`` library when it is installed (which reaches NVDA/JAWS
speech AND Braille), and falls back to the direct NVDA/JAWS adapters in
``core.screen_reader_announce`` (plus NVDA Braille via the controller client)
when it is not, so announcements keep working even in a stripped environment.

Each event has its own output mode so the user can tune notification behavior
per event in Settings > Announcements:

* ``none``    - no automatic announcement for this event
* ``speech``  - text-to-speech only
* ``braille`` - Braille display only
* ``both``    - speech and Braille (the default)
"""

from __future__ import annotations

import logging
from collections import OrderedDict, namedtuple
from typing import Callable, Dict, List, Optional, Tuple

from core import screen_reader_announce

LOG = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Output modes (persisted config strings — do NOT rename)
# --------------------------------------------------------------------------
MODE_NONE = "none"
MODE_SPEECH = "speech"
MODE_BRAILLE = "braille"
MODE_BOTH = "both"

MODE_ORDER: List[str] = [MODE_NONE, MODE_SPEECH, MODE_BRAILLE, MODE_BOTH]

# mode -> English label (msgid). The GUI wraps these with _() at display time.
MODE_LABELS: "OrderedDict[str, str]" = OrderedDict(
    (
        (MODE_NONE, "None"),
        (MODE_SPEECH, "Only speech"),
        (MODE_BRAILLE, "Only Braille"),
        (MODE_BOTH, "Speech and Braille"),
    )
)

DEFAULT_MODE = MODE_BOTH


# --------------------------------------------------------------------------
# Event table
# --------------------------------------------------------------------------

# id: stable key persisted under config["announcements"] and used by callers.
# label/help are English msgids; the Settings dialog wraps them with _().
Event = namedtuple("Event", "id label help default")

# NOTE: keep ids stable — they are persisted in config under "announcements".
EVENTS: List[Event] = [
    Event(
        "filter_change",
        "Filter change",
        "Announce the applied article filter (Ctrl+1 to Ctrl+6).",
        DEFAULT_MODE,
    ),
    Event(
        "status_toggle",
        "Read/unread status change",
        "Announce the new status when toggling read/unread (Backspace).",
        DEFAULT_MODE,
    ),
    Event(
        "start_update",
        "Start update",
        "Announce when a feed refresh is started (F5).",
        DEFAULT_MODE,
    ),
    Event(
        "stop_update",
        "Stop update",
        "Announce when a feed refresh is stopped (Shift+F5).",
        DEFAULT_MODE,
    ),
    Event(
        "favorite_toggle",
        "Favorites change",
        "Announce when an article is added to or removed from favorites (Ctrl+D).",
        DEFAULT_MODE,
    ),
    Event(
        "playback_speed",
        "Playback speed change",
        "Announce the current playback speed when it is changed by keyboard.",
        DEFAULT_MODE,
    ),
    Event(
        "media_navigation",
        "Media and chapter navigation",
        "Announce the item or chapter when moving to the next/previous one.",
        DEFAULT_MODE,
    ),
    Event(
        "general",
        "Other notifications",
        "Announce other significant interface changes and notifications.",
        DEFAULT_MODE,
    ),
]

_EVENTS_BY_ID: "OrderedDict[str, Event]" = OrderedDict((e.id, e) for e in EVENTS)


def _(text):  # noqa: A001 - gettext-noop marker for tools/extract_strings.py
    """Identity gettext marker.

    This module is GUI-free and does its gettext at display time in the GUI
    (``_(event.label)`` etc.), which the AST-based POT extractor cannot follow.
    Listing every displayed msgid through this no-op ``_`` below records them in
    ``locale/blindrss.pot`` so translators can localize the Announcements tab.
    """
    return text


# Translation anchors — displayed via real gettext in gui/dialogs.py. Keep in
# sync with EVENTS and MODE_LABELS above.
_POT_ANCHORS = (
    _("Filter change"),
    _("Announce the applied article filter (Ctrl+1 to Ctrl+6)."),
    _("Read/unread status change"),
    _("Announce the new status when toggling read/unread (Backspace)."),
    _("Start update"),
    _("Announce when a feed refresh is started (F5)."),
    _("Stop update"),
    _("Announce when a feed refresh is stopped (Shift+F5)."),
    _("Favorites change"),
    _("Announce when an article is added to or removed from favorites (Ctrl+D)."),
    _("Playback speed change"),
    _("Announce the current playback speed when it is changed by keyboard."),
    _("Media and chapter navigation"),
    _("Announce the item or chapter when moving to the next/previous one."),
    _("Other notifications"),
    _("Announce other significant interface changes and notifications."),
    _("None"),
    _("Only speech"),
    _("Only Braille"),
    _("Speech and Braille"),
)


def iter_events() -> List[Event]:
    return list(EVENTS)


def event_by_id(event_id: str) -> Optional[Event]:
    return _EVENTS_BY_ID.get(str(event_id))


def is_valid_mode(mode) -> bool:
    return str(mode) in MODE_ORDER


def mode_choices() -> List[Tuple[str, str]]:
    """Return ``[(mode, english_label)]`` in display order for the UI dropdown."""
    return [(mode, MODE_LABELS[mode]) for mode in MODE_ORDER]


def default_modes() -> "OrderedDict[str, str]":
    """Return the default ``{event_id: mode}`` mapping (everything ``both``)."""
    return OrderedDict((e.id, e.default) for e in EVENTS)


def normalize_modes(raw: Optional[Dict[str, object]]) -> "OrderedDict[str, str]":
    """Merge a stored/user mapping over the defaults, dropping unknown keys.

    Every known event id is present in the result mapped to a valid mode; an
    invalid or missing value falls back to that event's default.
    """
    src = raw if isinstance(raw, dict) else {}
    out: "OrderedDict[str, str]" = OrderedDict()
    for event in EVENTS:
        value = src.get(event.id)
        out[event.id] = str(value) if is_valid_mode(value) else event.default
    return out


def mode_for(modes: Optional[Dict[str, object]], event_id: str) -> str:
    """Resolve the output mode for ``event_id`` from a (possibly partial) map."""
    event = event_by_id(event_id)
    default = event.default if event is not None else DEFAULT_MODE
    if not isinstance(modes, dict):
        return default
    value = modes.get(str(event_id))
    return str(value) if is_valid_mode(value) else default


# --------------------------------------------------------------------------
# Announcer
# --------------------------------------------------------------------------


class Announcer:
    """Emit per-event announcements resolved against the user's config.

    ``modes_getter`` is a zero-arg callable returning the current
    ``{event_id: mode}`` mapping (usually ``config_manager.get("announcements")``
    wrapped in a lambda) so live Settings changes take effect without rebuilding
    the announcer.
    """

    def __init__(self, modes_getter: Optional[Callable[[], Dict[str, object]]] = None):
        self._modes_getter = modes_getter
        self._ao2 = None
        self._ao2_attempted = False

    # -- output backend -----------------------------------------------------
    def _get_ao2(self):
        """Return an accessible_output2 Auto output, or None (cached, fail-closed)."""
        if self._ao2_attempted:
            return self._ao2
        self._ao2_attempted = True
        try:
            import accessible_output2.outputs.auto  # type: ignore

            self._ao2 = accessible_output2.outputs.auto.Auto()
        except Exception as exc:  # library missing or no usable output
            LOG.debug("accessible_output2 unavailable: %s", exc)
            self._ao2 = None
        return self._ao2

    def _current_modes(self) -> Dict[str, object]:
        if self._modes_getter is None:
            return {}
        try:
            value = self._modes_getter()
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    # -- public API ---------------------------------------------------------
    def resolve_mode(self, event_id: str) -> str:
        return mode_for(self._current_modes(), event_id)

    def announce(self, event_id: str, message: str) -> bool:
        """Announce ``message`` for ``event_id`` using the configured mode.

        Returns True if any output path reported success. Fully guarded and
        non-blocking: every failure falls through so a caller never breaks a
        keyboard action because speech/Braille was unavailable.
        """
        text = str(message or "").strip()
        if not text:
            return False
        mode = self.resolve_mode(event_id)
        if mode == MODE_NONE:
            return False
        want_speech = mode in (MODE_SPEECH, MODE_BOTH)
        want_braille = mode in (MODE_BRAILLE, MODE_BOTH)
        return self._emit(text, want_speech, want_braille)

    def announce_test(self, message: str) -> bool:
        """Emit ``message`` through speech AND Braille, ignoring configuration.

        Backs the Settings > Announcements test button (issue #71). It
        deliberately does not consult the per-event modes: the button exists to
        prove the output pipeline reaches the screen reader, and honoring a
        "none" would make a working setup indistinguishable from a broken one.
        The caller can surface the False return as "no output path available".
        """
        text = str(message or "").strip()
        if not text:
            return False
        return self._emit(text, want_speech=True, want_braille=True)

    def _emit(self, text: str, want_speech: bool, want_braille: bool) -> bool:
        handled = False
        out = self._get_ao2()
        if out is not None:
            if want_speech:
                handled = self._ao2_speak(out, text) or handled
            if want_braille:
                handled = self._ao2_braille(out, text) or handled
            if handled:
                return True
        # accessible_output2 missing or produced nothing — use the direct
        # NVDA/JAWS adapters so announcements still reach the screen reader.
        if want_speech and screen_reader_announce.speak_status(text, interrupt=True):
            handled = True
        if want_braille and screen_reader_announce.braille_message(text):
            handled = True
        return handled

    @staticmethod
    def _ao2_speak(out, text: str) -> bool:
        try:
            out.speak(text, interrupt=True)
            return True
        except TypeError:
            # Some outputs don't accept the interrupt kwarg.
            try:
                out.speak(text)
                return True
            except Exception:
                return False
        except Exception:
            return False

    @staticmethod
    def _ao2_braille(out, text: str) -> bool:
        try:
            out.braille(text)
            return True
        except Exception:
            return False
