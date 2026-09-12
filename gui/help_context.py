# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Context-sensitive F1: work out what the user is looking at, then show it.

F1 arrives by two different routes on Windows, and both are needed:

* ``wxEVT_CHAR_HOOK`` — the ordinary case. Every window and dialog sees the
  key, and this is also how a user-remapped ``help.user_guide`` binding (Tools,
  Keyboard Shortcuts) reaches us.
* ``wxEVT_HELP`` — Windows' own WM_HELP. This is the *only* route while a menu
  is open: a menu runs its own modal message loop and no key event is delivered
  to the application at all. wxMSW turns WM_HELP into a help event carrying the
  highlighted menu item's id, which is exactly what "F1 on Import OPML" needs.

Both are caught with a ``wx.EventFilter`` (the same mechanism
``GlobalMediaKeyFilter`` uses in main.py) rather than per-window bindings,
because a per-window binding would have to be repeated on every dialog, panel,
and control in the application and would silently miss the next one added.

Resolution order, most specific first:

1. The menu item highlighted right now (context menus before the menu bar).
2. A ``_help_topic`` attribute on the focused window, or on any of its parents
   — this is how a notebook page or a single control claims its own section.
3. The class name of the focused window or any parent, via
   ``core.help_topics.DIALOG_TOPICS`` — so every dialog gets its section
   without touching its constructor.
4. The generic user guide.
"""
from __future__ import annotations

import logging
import re
import sys
import time

import wx

from core import help_topics

log = logging.getLogger(__name__)

# Menu item id -> topic. The menu bar is registered once when the frame builds
# it; context menus are rebuilt on every right-click, so they go in a separate
# map that is replaced wholesale each time (wx recycles auto-generated ids when
# a menu is destroyed, and a stale entry would answer for the wrong item).
_MENUBAR_TOPICS: dict = {}
_CONTEXT_MENU_TOPICS: dict = {}

# Two routes can report the same F1 press (a CHAR_HOOK we did not consume can
# still reach DefWindowProc, which posts WM_HELP). Collapse anything closer
# together than this into one.
_DUPLICATE_WINDOW_S = 0.4
_last_shown = [0.0]

_filter = None


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

def set_help_topic(window, topic) -> None:
    """Mark ``window`` (and, by inheritance, its children) as documented by ``topic``."""
    if window is None:
        return
    try:
        window._help_topic = help_topics.normalize(topic)
    except Exception:
        log.debug("Could not tag a window with help topic %r", topic, exc_info=True)


def register_menu_topic(item, topic) -> None:
    """Map a menu-bar item to ``topic``. ``item`` may be a wx.MenuItem or an id."""
    item_id = _menu_item_id(item)
    if item_id is None:
        return
    _MENUBAR_TOPICS[item_id] = help_topics.normalize(topic)


def register_menu_command(item, command_id) -> None:
    """Map a menu-bar item to whatever documents shortcut ``command_id``."""
    register_menu_topic(item, help_topics.topic_for_command(command_id))


def set_context_menu_topics(mapping) -> None:
    """Replace the transient popup-menu map with ``{item or id: topic}``."""
    _CONTEXT_MENU_TOPICS.clear()
    for item, topic in (mapping or {}).items():
        item_id = _menu_item_id(item)
        if item_id is None:
            continue
        _CONTEXT_MENU_TOPICS[item_id] = help_topics.normalize(topic)


def register_menu_labels(menu, replace=True) -> None:
    """Map every item of a freshly built popup ``menu`` to its topic.

    Context menus are rebuilt from scratch on each right-click, with labels that
    are already translated, so items are matched by label against both the
    English msgid and its translation in
    ``core.help_topics.CONTEXT_MENU_TOPICS``. One call at the end of a menu
    builder keeps the mapping from drifting as items are added over time — the
    alternative, a registration line beside every Append, is exactly the kind of
    thing that is right once and stale forever after.
    """
    if replace:
        _CONTEXT_MENU_TOPICS.clear()
    exact, templates = _label_index()
    _walk_menu(menu, exact, templates, depth=0)


def _walk_menu(menu, exact, templates, depth, inherited=None):
    if menu is None or depth > 4:
        return
    try:
        items = list(menu.GetMenuItems())
    except Exception:
        return
    for item in items:
        try:
            label = _normalize_menu_label(item.GetItemLabel())
        except Exception:
            label = ""
        topic = exact.get(label)
        if topic is None and label:
            for prefix, suffix, candidate in templates:
                if label.startswith(prefix) and label.endswith(suffix):
                    topic = candidate
                    break
        # A submenu's own items inherit its topic, so the chapters listed under
        # "Chapter Links" answer F1 with the Chapters section rather than
        # needing one mapping per generated item.
        effective = topic or inherited
        if effective:
            item_id = _menu_item_id(item)
            if item_id is not None:
                _CONTEXT_MENU_TOPICS[item_id] = effective
        try:
            submenu = item.GetSubMenu()
        except Exception:
            submenu = None
        if submenu is not None:
            _walk_menu(submenu, exact, templates, depth + 1, inherited=effective)


# A trailing "(Ctrl+D)" is the rendered shortcut, not part of the label; a
# trailing "(3 articles)" is part of it. Parenthesised text with no space is
# always the former.
_TRAILING_PAREN_RE = re.compile(r"\s*\(([^()]*)\)\s*$")


def _normalize_menu_label(label):
    """Strip mnemonics, accelerators, and trailing ellipses for comparison."""
    text = str(label or "").split("\t", 1)[0]
    text = text.replace("&&", "\x00").replace("&", "").replace("\x00", "&")
    text = text.strip()
    match = _TRAILING_PAREN_RE.search(text)
    if match and " " not in match.group(1):
        text = text[: match.start()].strip()
    for ellipsis in ("...", "…"):
        if text.endswith(ellipsis):
            text = text[: -len(ellipsis)].strip()
    return " ".join(text.split()).lower()


_LABEL_INDEX = {"language": None, "exact": {}, "templates": []}


def _label_index():
    """``({label: topic}, [(prefix, suffix, topic)])`` for the active language."""
    try:
        from core.i18n import current_language

        language = current_language()
    except Exception:
        language = "en"
    if _LABEL_INDEX["language"] == language:
        return _LABEL_INDEX["exact"], _LABEL_INDEX["templates"]

    try:
        from core.i18n import _ as translate
    except Exception:
        def translate(text):
            return text

    exact = {}
    templates = []
    for english, topic in help_topics.CONTEXT_MENU_TOPICS.items():
        variants = {english}
        try:
            variants.add(translate(english))
        except Exception:
            pass
        for variant in variants:
            if "{" in variant:
                # e.g. "Mark {count} as &Read" -- the count is filled in at
                # build time, so match on the fixed halves around it.
                head, _sep, tail = variant.partition("{")
                _name, _sep2, rest = tail.partition("}")
                prefix = _normalize_menu_label(head)
                suffix = _normalize_menu_label(rest)
                if prefix or suffix:
                    templates.append((prefix, suffix, topic))
            else:
                exact[_normalize_menu_label(variant)] = topic

    _LABEL_INDEX["language"] = language
    _LABEL_INDEX["exact"] = exact
    _LABEL_INDEX["templates"] = templates
    return exact, templates


def clear_context_menu_topics() -> None:
    _CONTEXT_MENU_TOPICS.clear()


# Menu-bar menus themselves, for F1 pressed on an open menu before any item is
# highlighted (Alt+T with nothing arrowed to yet). Keyed by the wx.Menu object,
# whose Python wrapper wx keeps stable for the life of the menu.
_MENU_TITLE_TOPICS: dict = {}
_open_menu_topic = [None]


def register_menu_title(menu, english_title) -> None:
    """Map a whole menu (by its English menu-bar title) to a topic."""
    topic = help_topics.MENU_TITLE_TOPICS.get(str(english_title or ""))
    if menu is None or not topic:
        return
    _MENU_TITLE_TOPICS[id(menu)] = topic


def note_menu_opened(menu) -> None:
    """Remember which menu is open, for F1 with no item highlighted."""
    _open_menu_topic[0] = _MENU_TITLE_TOPICS.get(id(menu)) if menu is not None else None


def note_menu_closed() -> None:
    _open_menu_topic[0] = None


def open_menu_topic():
    """Topic of the menu that is open right now, or None.

    Double-checked against Windows' own menu-mode flag: a missed
    ``EVT_MENU_CLOSE`` would otherwise leave a stale answer behind that
    hijacks the next ordinary F1.
    """
    topic = _open_menu_topic[0]
    if not topic:
        return None
    if _native_menu_mode_supported() and not _in_native_menu_mode():
        _open_menu_topic[0] = None
        return None
    return topic


def _native_menu_mode_supported():
    return sys.platform.startswith("win")


def _in_native_menu_mode():
    """True while Windows is running a menu's own modal loop."""
    try:
        import ctypes
        from ctypes import wintypes

        class _GuiThreadInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT),
            ]

        info = _GuiThreadInfo()
        info.cbSize = ctypes.sizeof(_GuiThreadInfo)
        if not ctypes.windll.user32.GetGUIThreadInfo(0, ctypes.byref(info)):
            return False
        return bool(info.flags & 0x00000004)  # GUI_INMENUMODE
    except Exception:
        return False


def _focused_window():
    try:
        return wx.Window.FindFocus()
    except Exception:
        return None


def _menu_item_id(item):
    if item is None:
        return None
    if isinstance(item, int):
        return item
    try:
        return int(item.GetId())
    except Exception:
        return None


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def topic_for_menu_id(item_id):
    """Topic for a menu item id, or None when the id is not a mapped item."""
    if item_id is None:
        return None
    try:
        key = int(item_id)
    except Exception:
        return None
    for candidate in _menu_id_candidates(key):
        topic = _CONTEXT_MENU_TOPICS.get(candidate) or _MENUBAR_TOPICS.get(candidate)
        if topic:
            return topic
    return None


def _menu_id_candidates(value):
    """The id as given, plus its signed reading.

    wx generates menu ids from a negative pool (wxID_AUTO_LOWEST..HIGHEST),
    but Windows carries a menu item's id in ``HELPINFO.iCtrlId``, a UINT, and
    wxMSW passes that straight into the help event. An id of -31923 therefore
    arrives as 33613, matches nothing, and F1 in a menu quietly falls back to
    the generic guide. Measured on wxPython 4.2 / wxMSW 3.3.
    """
    yield value
    if 0x8000 <= value <= 0xFFFF:
        yield value - 0x10000


def topic_for_window(window):
    """Topic documenting ``window``, walking up to its top-level parent."""
    seen = 0
    current = window
    while current is not None and seen < 64:
        seen += 1
        explicit = getattr(current, "_help_topic", None)
        if explicit and help_topics.is_known_topic(explicit):
            return explicit

        by_class = _topic_for_instance(current)
        if by_class:
            return by_class

        try:
            parent = current.GetParent()
        except Exception:
            parent = None
        if parent is current:
            break
        current = parent
    return None


# Dialogs that record raw keystrokes, where F1 is a key the user is trying to
# assign rather than a request for help. A window may also opt out by setting
# ``_captures_keys = True``.
_KEY_CAPTURE_CLASSES = frozenset({"ShortcutCaptureDialog"})


def is_capturing_keys(window):
    """True while ``window`` sits inside a dialog that records keystrokes.

    Tools, Keyboard Shortcuts lets a command be bound to a bare function key,
    F1 included. Swallowing F1 there would make it the one key in the registry
    that cannot be assigned.
    """
    seen = 0
    current = window
    while current is not None and seen < 64:
        seen += 1
        if getattr(current, "_captures_keys", False):
            return True
        try:
            if _KEY_CAPTURE_CLASSES.intersection(
                klass.__name__ for klass in type(current).__mro__
            ):
                return True
        except Exception:
            pass
        try:
            parent = current.GetParent()
        except Exception:
            parent = None
        if parent is current:
            break
        current = parent
    return False


def _topic_for_instance(window):
    """Topic for ``window``'s class, honouring subclasses via the MRO."""
    try:
        names = [klass.__name__ for klass in type(window).__mro__]
    except Exception:
        try:
            names = [type(window).__name__]
        except Exception:
            return None
    return help_topics.topic_for_class_names(names)


def resolve_topic(focus=None, menu_id=None):
    """Best topic for the current context; never returns an unknown id."""
    topic = topic_for_menu_id(menu_id)
    if topic:
        return topic

    # A menu is open but nothing in it is highlighted yet: answer for the menu
    # itself rather than for whatever had focus before it opened.
    topic = open_menu_topic()
    if topic:
        return topic

    if focus is None:
        focus = _focused_window()
    topic = topic_for_window(focus)
    if topic:
        return topic

    # Nothing focused (or focus is on something undocumented): fall back to the
    # active top-level window, which at least identifies the dialog or frame.
    try:
        active = wx.GetActiveWindow()
    except Exception:
        active = None
    topic = topic_for_window(active)
    if topic:
        return topic

    return help_topics.DEFAULT_TOPIC


# --------------------------------------------------------------------------
# Showing the window
# --------------------------------------------------------------------------

def _modal_top_level():
    """The modal dialog currently running, if any."""
    try:
        windows = list(wx.GetTopLevelWindows())
    except Exception:
        return None
    for window in reversed(windows):
        try:
            if isinstance(window, wx.Dialog) and window.IsShown() and window.IsModal():
                return window
        except Exception:
            continue
    return None


def _pick_parent():
    modal = _modal_top_level()
    if modal is not None:
        return modal, True
    try:
        active = wx.GetActiveWindow()
    except Exception:
        active = None
    if active is not None:
        try:
            return wx.GetTopLevelParent(active), False
        except Exception:
            pass
    try:
        return wx.GetApp().GetTopWindow(), False
    except Exception:
        return None, False


_modeless_window = None


def show_help(topic=None, parent=None) -> bool:
    """Open the user guide at ``topic``. Returns True when a window was shown.

    Shown modally when a modal dialog is up, because wx disables every other
    top-level window for the duration of a modal loop — a modeless help window
    raised from inside Settings would be visible, announced, and unfocusable.
    """
    global _modeless_window
    from gui.help_viewer import HelpWindow

    resolved = help_topics.normalize(topic)
    owner, must_be_modal = _pick_parent()
    if parent is not None:
        owner = parent

    if must_be_modal:
        dialog = HelpWindow(owner, topic=resolved)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
        return True

    window = _modeless_window
    if window is not None:
        try:
            alive = bool(window) and not window.IsBeingDeleted() and window.GetParent() == owner
        except Exception:
            alive = False
        if not alive:
            window = None
            _modeless_window = None

    if window is None:
        window = HelpWindow(owner, topic=resolved)
        _modeless_window = window
        window.Bind(wx.EVT_WINDOW_DESTROY, _on_help_window_destroyed)
    else:
        window.show_topic(resolved, announce=False)

    window.Show()
    window.Raise()
    try:
        window.text_ctrl.SetFocus()
    except Exception:
        pass
    return True


def _on_help_window_destroyed(event):
    global _modeless_window
    if _modeless_window is not None and event.GetEventObject() == _modeless_window:
        _modeless_window = None
    event.Skip()


def _cancel_native_menu_mode():
    """Close an open native menu so the help window can take focus.

    Windows posts WM_HELP while its own modal menu loop is running; without
    this the menu stays up, owns the input queue, and the help window opens
    behind it. WM_CANCELMODE is the documented way out of menu mode.
    """
    if not _native_menu_mode_supported():
        return
    try:
        import ctypes

        for window in list(wx.GetTopLevelWindows() or []):
            try:
                if not window.IsShown():
                    continue
                handle = int(window.GetHandle())
            except Exception:
                continue
            if handle:
                ctypes.windll.user32.PostMessageW(handle, 0x001F, 0, 0)  # WM_CANCELMODE
    except Exception:
        log.debug("Could not cancel native menu mode", exc_info=True)


def show_context_help(focus=None, menu_id=None, from_menu=False) -> bool:
    """Resolve the current context and open the guide there (de-duplicated).

    The context is resolved *now* — the focused window and the highlighted menu
    item are only meaningful while the F1 press is being handled — but the
    window is opened from the next event loop turn, so a modal help dialog is
    never created from inside an event filter.
    """
    now = time.monotonic()
    if now - _last_shown[0] < _DUPLICATE_WINDOW_S:
        return True
    _last_shown[0] = now
    try:
        topic = resolve_topic(focus=focus, menu_id=menu_id)
    except Exception:
        log.debug("Help topic resolution failed", exc_info=True)
        topic = help_topics.DEFAULT_TOPIC
    log.debug(
        "F1 help: topic=%s menu_id=%s from_menu=%s focus=%s",
        topic, menu_id, from_menu, type(focus).__name__ if focus is not None else None,
    )
    if from_menu:
        _cancel_native_menu_mode()
    try:
        wx.CallAfter(_show_help_safely, topic)
    except Exception:
        log.exception("Could not open the user guide")
        return False
    return True


def _show_help_safely(topic):
    try:
        show_help(topic)
    except Exception:
        log.exception("Could not open the user guide")


# --------------------------------------------------------------------------
# The global filter
# --------------------------------------------------------------------------

class HelpKeyFilter(wx.EventFilter):
    """Catches F1 (and WM_HELP) anywhere in the application."""

    def __init__(self, frame=None):
        super().__init__()
        self.frame = frame

    def FilterEvent(self, event):
        try:
            event_type = int(event.GetEventType())
        except Exception:
            return wx.EventFilter.Event_Skip

        if event_type == wx.wxEVT_HELP:
            if is_capturing_keys(_focused_window()):
                return wx.EventFilter.Event_Skip
            try:
                menu_id = int(event.GetId())
            except Exception:
                menu_id = None
            # Only treat the id as a menu item when it really is one: for the
            # window flavour of WM_HELP wx walks the parent chain passing each
            # window's id, which is not a menu id at all.
            if topic_for_menu_id(menu_id) is None:
                menu_id = None
            show_context_help(
                menu_id=menu_id,
                from_menu=_native_menu_mode_supported() and _in_native_menu_mode(),
            )
            return wx.EventFilter.Event_Processed

        if event_type != wx.wxEVT_CHAR_HOOK:
            return wx.EventFilter.Event_Skip
        if not isinstance(event, wx.KeyEvent):
            return wx.EventFilter.Event_Skip
        if not self._is_help_key(event):
            return wx.EventFilter.Event_Skip

        focus = _focused_window()
        if is_capturing_keys(focus):
            return wx.EventFilter.Event_Skip
        show_context_help(focus=focus)
        return wx.EventFilter.Event_Processed

    def _is_help_key(self, event):
        """True for F1, or for whatever key ``help.user_guide`` is bound to.

        F1 keeps working even when the user has moved the User Guide command
        elsewhere, because F1 is the platform's help key — unless they have
        bound F1 to some *other* command, in which case that command wins and
        this returns False so the normal dispatcher sees it.
        """
        try:
            from gui.shortcut_keys import event_to_accel

            accel = event_to_accel(event)
        except Exception:
            accel = None
        if not accel:
            return False

        try:
            bound = (getattr(self.frame, "_shortcut_cmd_map", None) or {}).get(accel)
        except Exception:
            bound = None
        if bound == "help.user_guide":
            return True
        return accel == "F1" and not bound


def install(frame=None):
    """Install the global F1 filter (idempotent)."""
    global _filter
    if _filter is not None:
        _filter.frame = frame or _filter.frame
        return _filter
    _filter = HelpKeyFilter(frame)
    try:
        wx.EvtHandler.AddFilter(_filter)
    except Exception:
        log.exception("Could not install the F1 help filter")
        _filter = None
    return _filter


def uninstall():
    global _filter
    if _filter is None:
        return
    try:
        wx.EvtHandler.RemoveFilter(_filter)
    except Exception:
        log.debug("Could not remove the F1 help filter", exc_info=True)
    _filter = None
