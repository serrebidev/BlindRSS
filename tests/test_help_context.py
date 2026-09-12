# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Resolution behind context-sensitive F1 (gui.help_context).

These exercise the part that decides *which* section F1 opens: the walk up from
the focused control, the class-name fallback that gives every dialog its
section for free, and the label matching that maps a freshly built context menu
— including the multi-selection labels that carry a count — onto topics.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

wx = pytest.importorskip("wx")

from core import help_topics  # noqa: E402
import gui.help_context as help_context  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app


@pytest.fixture
def frame(wx_app):
    frame = wx.Frame(None)
    yield frame
    try:
        frame.Destroy()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clean_menu_maps():
    help_context.clear_context_menu_topics()
    yield
    help_context.clear_context_menu_topics()


# --------------------------------------------------------------------------
# Walking up from the focused window
# --------------------------------------------------------------------------

def test_explicit_topic_on_the_control_wins(frame):
    panel = wx.Panel(frame)
    ctrl = wx.TextCtrl(panel)
    help_context.set_help_topic(panel, "settings")
    help_context.set_help_topic(ctrl, "equalizer")
    assert help_context.topic_for_window(ctrl) == "equalizer"


def test_topic_is_inherited_from_an_ancestor(frame):
    panel = wx.Panel(frame)
    inner = wx.Panel(panel)
    ctrl = wx.Button(inner, label="x")
    help_context.set_help_topic(panel, "settings-advanced")
    assert help_context.topic_for_window(ctrl) == "settings-advanced"


def test_set_help_topic_rejects_unknown_ids(frame):
    panel = wx.Panel(frame)
    help_context.set_help_topic(panel, "not-a-real-topic")
    assert panel._help_topic == help_topics.DEFAULT_TOPIC


def test_class_name_gives_a_dialog_its_section(wx_app):
    class SettingsDialog(wx.Dialog):
        pass

    dialog = SettingsDialog(None)
    try:
        ctrl = wx.TextCtrl(dialog)
        assert help_context.topic_for_window(ctrl) == "settings"
    finally:
        dialog.Destroy()


def test_subclass_inherits_its_base_class_topic(wx_app):
    class EqualizerDialog(wx.Dialog):
        pass

    class FancyEqualizerDialog(EqualizerDialog):
        pass

    dialog = FancyEqualizerDialog(None)
    try:
        assert help_context.topic_for_window(dialog) == "equalizer"
    finally:
        dialog.Destroy()


def test_undocumented_window_resolves_to_nothing(frame):
    panel = wx.Panel(frame)
    assert help_context.topic_for_window(panel) is None


def test_resolve_topic_falls_back_to_the_user_guide(frame):
    panel = wx.Panel(frame)
    assert help_context.resolve_topic(focus=panel) in help_topics.topic_ids()


# --------------------------------------------------------------------------
# Menu items
# --------------------------------------------------------------------------

def test_menu_bar_items_are_registered_by_command(wx_app):
    menu = wx.Menu()
    item = menu.Append(wx.ID_ANY, "Import OPML...")
    help_context.register_menu_command(item, "feeds.import_opml")
    assert help_context.topic_for_menu_id(item.GetId()) == "import-opml"
    assert help_context.resolve_topic(menu_id=item.GetId()) == "import-opml"


def test_unknown_menu_id_is_not_claimed():
    assert help_context.topic_for_menu_id(-4242) is None


def test_context_menu_labels_are_matched(wx_app):
    menu = wx.Menu()
    takeout = menu.Append(wx.ID_ANY, "Import OPML Here...")
    cookies = menu.Append(wx.ID_ANY, "Remove Feed")
    help_context.register_menu_labels(menu)
    assert help_context.topic_for_menu_id(takeout.GetId()) == "import-opml"
    assert help_context.topic_for_menu_id(cookies.GetId()) == "removing-feeds"


def test_context_menu_matches_counted_labels(wx_app):
    menu = wx.Menu()
    marked = menu.Append(wx.ID_ANY, "Mark 3 as &Read")
    deleted = menu.Append(wx.ID_ANY, "Delete 3 Articles\tDel")
    help_context.register_menu_labels(menu)
    assert help_context.topic_for_menu_id(marked.GetId()) == "read-status"
    assert help_context.topic_for_menu_id(deleted.GetId()) == "deleted-articles"


def test_context_menu_ignores_a_rendered_shortcut_suffix(wx_app):
    menu = wx.Menu()
    item = menu.Append(wx.ID_ANY, "Copy Link (Ctrl+L)")
    help_context.register_menu_labels(menu)
    assert help_context.topic_for_menu_id(item.GetId()) == "clipboard"


def test_submenu_items_inherit_the_submenu_topic(wx_app):
    submenu = wx.Menu()
    chapter = submenu.Append(wx.ID_ANY, "00:12  Opening remarks")
    menu = wx.Menu()
    menu.AppendSubMenu(submenu, "Chapter Links")
    help_context.register_menu_labels(menu)
    assert help_context.topic_for_menu_id(chapter.GetId()) == "chapters"


def test_context_menu_registration_replaces_the_previous_menu(wx_app):
    first = wx.Menu()
    stale = first.Append(wx.ID_ANY, "Remove Feed")
    help_context.register_menu_labels(first)
    stale_id = stale.GetId()

    second = wx.Menu()
    second.Append(wx.ID_ANY, "Copy Feed URL")
    help_context.register_menu_labels(second)
    assert help_context.topic_for_menu_id(stale_id) is None


def test_context_menu_items_win_over_the_menu_bar(wx_app):
    menubar_item = wx.Menu().Append(wx.ID_ANY, "Anything")
    help_context.register_menu_topic(menubar_item, "settings")
    help_context.set_context_menu_topics({menubar_item.GetId(): "player"})
    assert help_context.topic_for_menu_id(menubar_item.GetId()) == "player"


# --------------------------------------------------------------------------
# Label normalisation
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label,expected",
    [
        ("&Remove Feed", "remove feed"),
        ("Remove Feed\tCtrl+R", "remove feed"),
        ("Import OPML Here...", "import opml here"),
        ("Import OPML Here…", "import opml here"),
        ("Copy Link (Ctrl+Shift+L)", "copy link"),
        ("Copy Text (3 articles)", "copy text (3 articles)"),
        ("Feeds && Articles", "feeds & articles"),
    ],
)
def test_menu_label_normalisation(label, expected):
    assert help_context._normalize_menu_label(label) == expected


# --------------------------------------------------------------------------
# The help window itself
# --------------------------------------------------------------------------

def test_help_window_opens_at_the_requested_topic(frame):
    from gui.help_viewer import HelpWindow

    window = HelpWindow(frame, topic="equalizer")
    try:
        assert window.text_ctrl.GetValue().strip()
        contents = window.contents_list.GetString(window.contents_list.GetSelection())
        assert "Equalizer" in contents
        line = window._anchor_lines["equalizer"]
        assert window._plain_text.split("\n")[line].strip() == "Equalizer"
        # The caret really sits on that heading, not merely near it.
        caret = window._caret_offset()
        assert window._plain_text[caret:caret + len("Equalizer")] == "Equalizer"
    finally:
        window.Destroy()


def test_help_window_falls_back_for_an_unknown_topic(frame):
    from gui.help_viewer import HelpWindow

    window = HelpWindow(frame, topic="no-such-topic")
    try:
        index = window.contents_list.GetSelection()
        assert index == 0
    finally:
        window.Destroy()


def test_help_window_find_moves_the_caret(frame):
    from gui.help_viewer import HelpWindow

    window = HelpWindow(frame, topic=help_topics.DEFAULT_TOPIC)
    try:
        window.find_ctrl.SetValue("equalizer")
        window.on_find_next()
        offset = window._caret_offset()
        assert window._search_text[offset:offset + len("equalizer")] == "equalizer"

        # Finding again moves on to the next occurrence rather than sitting still.
        window.on_find_next()
        assert window._caret_offset() > offset
    finally:
        window.Destroy()


def test_help_window_declares_its_own_topic(frame):
    from gui.help_viewer import HelpWindow

    window = HelpWindow(frame, topic=help_topics.DEFAULT_TOPIC)
    try:
        assert help_context.topic_for_window(window) == "help-window"
    finally:
        window.Destroy()


# --------------------------------------------------------------------------
# F1 on an open menu with nothing highlighted
# --------------------------------------------------------------------------

def test_open_menu_answers_for_itself(wx_app, monkeypatch):
    monkeypatch.setattr(help_context, "_native_menu_mode_supported", lambda: False)
    menu = wx.Menu()
    help_context.register_menu_title(menu, "&Tools")
    help_context.note_menu_opened(menu)
    try:
        assert help_context.open_menu_topic() == "settings"
        assert help_context.resolve_topic() == "settings"
    finally:
        help_context.note_menu_closed()
    assert help_context.open_menu_topic() is None


def test_stale_open_menu_is_dropped_when_no_menu_is_up(wx_app, monkeypatch):
    monkeypatch.setattr(help_context, "_native_menu_mode_supported", lambda: True)
    monkeypatch.setattr(help_context, "_in_native_menu_mode", lambda: False)
    menu = wx.Menu()
    help_context.register_menu_title(menu, "&Player")
    help_context.note_menu_opened(menu)
    assert help_context.open_menu_topic() is None


def test_menu_item_beats_the_open_menu(wx_app, monkeypatch):
    monkeypatch.setattr(help_context, "_native_menu_mode_supported", lambda: False)
    menu = wx.Menu()
    item = menu.Append(wx.ID_ANY, "Settings...")
    help_context.register_menu_title(menu, "&Tools")
    help_context.register_menu_command(item, "tools.import_site_cookies")
    help_context.note_menu_opened(menu)
    try:
        assert help_context.resolve_topic(menu_id=item.GetId()) == "site-cookies"
    finally:
        help_context.note_menu_closed()


def test_unmapped_menu_title_is_ignored(wx_app):
    menu = wx.Menu()
    help_context.register_menu_title(menu, "&Nonexistent")
    help_context.note_menu_opened(menu)
    try:
        assert help_context.open_menu_topic() is None
    finally:
        help_context.note_menu_closed()


# --------------------------------------------------------------------------
# The global F1 filter
# --------------------------------------------------------------------------

class _FakeFrame:
    def __init__(self, cmd_map=None):
        self._shortcut_cmd_map = dict(cmd_map or {"F1": "help.user_guide"})


@pytest.fixture
def filter_calls(monkeypatch):
    """Record show_context_help() calls instead of opening a window."""
    calls = []

    def _record(focus=None, menu_id=None, from_menu=False):
        calls.append({"focus": focus, "menu_id": menu_id, "from_menu": from_menu})
        return True

    monkeypatch.setattr(help_context, "show_context_help", _record)
    return calls


def _key_event(keycode, *, ctrl=False, shift=False, alt=False):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(keycode)
    event.SetControlDown(ctrl)
    event.SetShiftDown(shift)
    event.SetAltDown(alt)
    return event


def test_filter_handles_f1(wx_app, filter_calls):
    handler = help_context.HelpKeyFilter(_FakeFrame())
    result = handler.FilterEvent(_key_event(wx.WXK_F1))
    assert result == wx.EventFilter.Event_Processed
    assert len(filter_calls) == 1


def test_filter_ignores_other_keys(wx_app, filter_calls):
    handler = help_context.HelpKeyFilter(_FakeFrame())
    assert handler.FilterEvent(_key_event(ord("A"))) == wx.EventFilter.Event_Skip
    assert handler.FilterEvent(_key_event(ord("P"), ctrl=True)) == wx.EventFilter.Event_Skip
    assert handler.FilterEvent(_key_event(wx.WXK_F1, shift=True)) == wx.EventFilter.Event_Skip
    assert filter_calls == []


def test_filter_honours_a_remapped_user_guide_binding(wx_app, filter_calls):
    handler = help_context.HelpKeyFilter(_FakeFrame({"Ctrl+Shift+H": "help.user_guide"}))
    assert handler.FilterEvent(
        _key_event(ord("H"), ctrl=True, shift=True)
    ) == wx.EventFilter.Event_Processed
    # F1 is no longer claimed by any command, so it still opens help.
    assert handler.FilterEvent(_key_event(wx.WXK_F1)) == wx.EventFilter.Event_Processed
    assert len(filter_calls) == 2


def test_filter_yields_f1_to_another_command(wx_app, filter_calls):
    """A user who binds F1 elsewhere gets their command, not the guide."""
    handler = help_context.HelpKeyFilter(_FakeFrame({"F1": "feeds.refresh_all"}))
    assert handler.FilterEvent(_key_event(wx.WXK_F1)) == wx.EventFilter.Event_Skip
    assert filter_calls == []


def test_filter_passes_a_highlighted_menu_item_through(wx_app, filter_calls):
    menu = wx.Menu()
    item = menu.Append(wx.ID_ANY, "Import OPML...")
    help_context.register_menu_command(item, "feeds.import_opml")

    handler = help_context.HelpKeyFilter(_FakeFrame())
    event = wx.HelpEvent(wx.wxEVT_HELP, item.GetId())
    assert handler.FilterEvent(event) == wx.EventFilter.Event_Processed
    assert filter_calls[0]["menu_id"] == item.GetId()


def test_filter_drops_a_help_event_id_that_is_not_a_menu_item(wx_app, filter_calls):
    handler = help_context.HelpKeyFilter(_FakeFrame())
    assert handler.FilterEvent(
        wx.HelpEvent(wx.wxEVT_HELP, -31337)
    ) == wx.EventFilter.Event_Processed
    assert filter_calls[0]["menu_id"] is None


def test_show_context_help_is_debounced(wx_app, monkeypatch):
    """Two routes can report one F1 press; the window must open once."""
    opened = []
    monkeypatch.setattr(help_context, "_last_shown", [0.0])
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: opened.append(a))
    help_context.show_context_help()
    help_context.show_context_help()
    assert len(opened) == 1


def test_menu_id_arrives_unsigned_from_wm_help(wx_app):
    """wxMSW passes WM_HELP's UINT menu id straight through (16-bit wrapped)."""
    menu = wx.Menu()
    item = menu.Append(wx.ID_ANY, "Settings...")
    help_context.register_menu_command(item, "tools.settings")
    item_id = item.GetId()
    assert item_id < 0, "wx should be allocating ids from its negative auto pool"
    unsigned = item_id + 0x10000
    assert help_context.topic_for_menu_id(unsigned) == "settings"
    assert help_context.topic_for_menu_id(item_id) == "settings"


# --------------------------------------------------------------------------
# The shortcut capture dialog must still be able to record F1
# --------------------------------------------------------------------------

def test_shortcut_capture_dialog_keeps_f1(wx_app, filter_calls, monkeypatch):
    class ShortcutCaptureDialog(wx.Dialog):
        pass

    dialog = ShortcutCaptureDialog(None)
    try:
        ctrl = wx.TextCtrl(dialog)
        assert help_context.is_capturing_keys(ctrl)
        monkeypatch.setattr(help_context, "_focused_window", lambda: ctrl)
        handler = help_context.HelpKeyFilter(_FakeFrame())
        assert handler.FilterEvent(_key_event(wx.WXK_F1)) == wx.EventFilter.Event_Skip
        assert filter_calls == []
    finally:
        dialog.Destroy()


def test_capturing_flag_opts_a_window_out(frame):
    panel = wx.Panel(frame)
    inner = wx.TextCtrl(panel)
    assert not help_context.is_capturing_keys(inner)
    panel._captures_keys = True
    assert help_context.is_capturing_keys(inner)
