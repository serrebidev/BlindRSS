# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The offline user-guide window (Help > User Guide, and every F1 press).

Deliberately plain: a contents list, a read-only text area, and a find box.
There is no rendering engine and no web view, because the guide has to work
with a screen reader first — a wx.TextCtrl with TE_RICH2 is the same control
the article reading pane uses, so NVDA, JAWS, and VoiceOver already read it
line by line, word by word, and character by character, and its text can be
selected and copied.

Positions are character offsets into the flattened text, never wx's X/Y line
functions: on wxMSW those count *wrapped* display lines, so line 518 of the
document is nowhere near line 518 of the control and ``XYToPosition`` simply
returns -1. With TE_RICH2 the control's offsets match the Python string one for
one, which is both simpler and correct.
"""
from __future__ import annotations

import logging

import wx

from core import help_docs, help_topics
from core.i18n import _

log = logging.getLogger(__name__)


class HelpWindow(wx.Dialog):
    """Reader for ``docs/help/<lang>.md``, opened at a topic.

    A wx.Dialog rather than a wx.Frame so it can be shown modally when it is
    opened from a modal dialog: a modeless window raised while a modal dialog
    is up is disabled by wx's modal loop, which would leave a blind user with a
    help window they can hear but not focus.
    """

    def __init__(self, parent, topic=None, language=None):
        super().__init__(
            parent,
            title=_("BlindRSS User Guide"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
            size=(860, 620),
        )
        self._help_topic = "help-window"

        if language is None:
            try:
                from core.i18n import current_language

                language = current_language()
            except Exception:
                language = help_docs.FALLBACK_LANGUAGE

        self._document = help_docs.load_document(language)
        (
            self._plain_text,
            self._anchor_lines,
            self._section_lines,
        ) = help_docs.render_plain_text(self._document)
        self._search_text = self._plain_text.lower()
        self._line_starts = _line_start_offsets(self._plain_text)
        self._entries = help_docs.contents_entries(self._document)
        self._last_term = ""

        self._build_ui()
        self.show_topic(topic, announce=False)

    # -- construction ------------------------------------------------------

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        if self._document.is_fallback:
            # Say it out loud rather than silently showing English: a reader who
            # asked for Hungarian help should know why the text is in English.
            notice = wx.StaticText(
                self,
                label=_(
                    "This guide has not been translated into your language yet, "
                    "so it is shown in English."
                ),
            )
            notice.SetName(_("Guide language"))
            outer.Add(notice, 0, wx.EXPAND | wx.ALL, 6)

        find_row = wx.BoxSizer(wx.HORIZONTAL)
        find_row.Add(
            wx.StaticText(self, label=_("&Find:")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6,
        )
        self.find_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.find_ctrl.SetName(_("Find in guide"))
        try:
            self.find_ctrl.SetHint(_("Type a word and press Enter"))
        except Exception:
            pass
        find_row.Add(self.find_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.find_next_btn = wx.Button(self, label=_("Find &Next"))
        find_row.Add(self.find_next_btn, 0, wx.RIGHT, 4)
        self.find_prev_btn = wx.Button(self, label=_("Find &Previous"))
        find_row.Add(self.find_prev_btn, 0)
        outer.Add(find_row, 0, wx.EXPAND | wx.ALL, 6)

        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)

        contents_panel = wx.Panel(splitter)
        contents_sizer = wx.BoxSizer(wx.VERTICAL)
        contents_sizer.Add(
            wx.StaticText(contents_panel, label=_("&Contents:")), 0, wx.BOTTOM, 2
        )
        self.contents_list = wx.ListBox(contents_panel, choices=self._contents_labels())
        self.contents_list.SetName(_("Guide contents"))
        contents_sizer.Add(self.contents_list, 1, wx.EXPAND)
        contents_panel.SetSizer(contents_sizer)

        text_panel = wx.Panel(splitter)
        text_sizer = wx.BoxSizer(wx.VERTICAL)
        text_sizer.Add(wx.StaticText(text_panel, label=_("&Guide:")), 0, wx.BOTTOM, 2)
        self.text_ctrl = wx.TextCtrl(
            text_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        self.text_ctrl.SetName(_("User guide text"))
        self.text_ctrl.ChangeValue(self._plain_text or _("The user guide could not be loaded."))
        text_sizer.Add(self.text_ctrl, 1, wx.EXPAND)
        text_panel.SetSizer(text_sizer)

        splitter.SplitVertically(contents_panel, text_panel, 260)
        splitter.SetMinimumPaneSize(150)
        outer.Add(splitter, 1, wx.EXPAND | wx.ALL, 6)

        btn_sizer = self.CreateButtonSizer(wx.CLOSE)
        if btn_sizer is not None:
            outer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 6)

        self.SetSizer(outer)
        self.Centre()

        self.find_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_find_next)
        self.find_next_btn.Bind(wx.EVT_BUTTON, self.on_find_next)
        self.find_prev_btn.Bind(wx.EVT_BUTTON, self.on_find_prev)
        self.contents_list.Bind(wx.EVT_LISTBOX, self.on_contents_select)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        # wx.CLOSE maps to wx.ID_CLOSE, which the default dialog handling does
        # not end the modal loop for.
        self.Bind(wx.EVT_BUTTON, self.on_close_button, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_CLOSE, self.on_close_window)

    def _contents_labels(self):
        """Contents entries indented by heading level, for the list box."""
        labels = []
        for _anchor, title, level in self._entries:
            labels.append(("    " * max(0, int(level) - 2)) + str(title))
        return labels or [_("(The user guide could not be loaded.)")]

    # -- navigation --------------------------------------------------------

    def show_topic(self, topic, announce=True):
        """Scroll to ``topic``'s section, falling back to the top of the guide."""
        anchor = help_topics.normalize(topic)
        line = self._anchor_lines.get(anchor)
        if line is None:
            line = self._anchor_lines.get(help_topics.DEFAULT_TOPIC, 0)
        self._goto_line(int(line or 0))

        for index, (entry_anchor, title, _level) in enumerate(self._entries):
            if entry_anchor == anchor:
                if self.contents_list.GetSelection() != index:
                    self.contents_list.SetSelection(index)
                if announce:
                    _speak(title)
                break

    def _goto_line(self, line):
        index = max(0, int(line))
        offset = self._line_starts[index] if index < len(self._line_starts) else 0
        self._goto_offset(offset)

    def _goto_offset(self, offset, selection_length=0):
        """Move the caret to a character offset in ``self._plain_text``.

        Character offsets, not XYToPosition: on wxMSW the X/Y line functions
        count *wrapped* display lines, so line 518 of the document is not line
        518 of the control and the position comes back as -1. With TE_RICH2 the
        control's own offsets match the Python string exactly, so this is both
        simpler and correct.
        """
        position = max(0, min(int(offset), len(self._plain_text)))
        try:
            self.text_ctrl.SetInsertionPoint(position)
            if selection_length > 0:
                self.text_ctrl.SetSelection(position, position + int(selection_length))
            self.text_ctrl.ShowPosition(position)
        except Exception:
            log.debug("Could not move the guide caret to %s", position, exc_info=True)

    def _caret_offset(self):
        """Caret position as an offset into ``self._plain_text``."""
        try:
            return max(0, int(self.text_ctrl.GetInsertionPoint()))
        except Exception:
            return 0

    def on_contents_select(self, event):
        index = self.contents_list.GetSelection()
        event.Skip()
        if index < 0 or index >= len(self._entries):
            return
        _anchor, _title, _level = self._entries[index]
        # _section_lines is parallel to _entries, so an unanchored heading is
        # just as reachable as an anchored one.
        line = self._section_lines[index] if index < len(self._section_lines) else 0
        self._goto_line(int(line or 0))
        # wx.ListBox already reports its new selection to screen readers.  A
        # second explicit announcement made NVDA speak every contents title
        # twice while people navigate with Up/Down.

    # -- searching ---------------------------------------------------------

    def on_find_next(self, event=None):
        self._find(forward=True)

    def on_find_prev(self, event=None):
        self._find(forward=False)

    def _find(self, forward=True):
        term = self.find_ctrl.GetValue().strip().lower()
        if not term:
            self.find_ctrl.SetFocus()
            return
        self._last_term = term
        start = self._caret_offset()

        if forward:
            index = self._search_text.find(term, start + 1)
            wrapped = index < 0
            if wrapped:
                index = self._search_text.find(term, 0)
        else:
            index = self._search_text.rfind(term, 0, max(0, start))
            wrapped = index < 0
            if wrapped:
                index = self._search_text.rfind(term)

        if index < 0:
            _speak(_("Not found: {term}").format(term=term))
            return

        self._goto_offset(index, selection_length=len(term))
        try:
            self.text_ctrl.SetFocus()
        except Exception:
            pass
        if wrapped:
            _speak(_("Wrapped to the start of the guide.") if forward
                   else _("Wrapped to the end of the guide."))

    # -- keyboard ----------------------------------------------------------

    def on_char_hook(self, event):
        key = event.GetKeyCode()
        ctrl = event.ControlDown()
        shift = event.ShiftDown()

        if key == wx.WXK_ESCAPE:
            self._dismiss()
            return
        if key == wx.WXK_F3:
            self._find(forward=not shift)
            return
        if ctrl and not shift and key in (ord("F"), ord("f")):
            self.find_ctrl.SetFocus()
            self.find_ctrl.SelectAll()
            return
        event.Skip()

    def on_close_button(self, event):
        self._dismiss()

    def on_close_window(self, event):
        self._dismiss()

    def _dismiss(self):
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            self.Hide()


def _line_start_offsets(text):
    """Offset of the first character of each line in ``text``."""
    starts = [0]
    for index, character in enumerate(text):
        if character == "\n":
            starts.append(index + 1)
    return starts


def _speak(message):
    """Announce ``message`` straight to the screen reader (best effort)."""
    if not message:
        return
    try:
        from core import screen_reader_announce

        screen_reader_announce.speak_status(str(message))
    except Exception:
        log.debug("Could not announce a help message", exc_info=True)
