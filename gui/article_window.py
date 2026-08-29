# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The window File > Open Article puts a pasted web page into.

A separate frame rather than the main reading pane, on purpose: the page has
no feed, no article row and no read state, so putting it in the pane would
mean either inventing a fake article row or throwing away whatever the user
was reading. A window of its own also lets several pages stay open at once.

It carries both readers the app has -- the plain full-text control and the
rich HTML WebView -- and can switch between them without closing and reopening
the window. Each rendered mode is cached after its first load.
"""

from __future__ import annotations

import logging
import threading
import webbrowser

import wx

from core import article_lang
from core import open_article
from core import utils
from core.i18n import _
from . import rich_view_links
from .clipboard_utils import copy_textctrl_selection_to_clipboard
from .menu_mnemonics import apply_menubar_mnemonics
from .reader_performance import (
    notify_reader_content_changed,
    replace_text_control_value,
    set_accessible_webview_content,
)
from .widgets import force_ltr_reading

log = logging.getLogger(__name__)


class ArticleWindow(wx.Frame):
    """One pasted URL, rendered in whichever reader the user asked for."""

    def __init__(self, parent, url: str, rich: bool = False, translate=None):
        super().__init__(parent, title=_("Article"), size=(900, 700))
        self.url = str(url or "")
        self._want_rich = bool(rich)
        self._translate = translate
        self._rich_view = None
        self._rich_view_unavailable = False
        # Rendered content per reader, so switching back to a reader that has
        # already loaded is instant.
        self._loaded = {}
        self._title = ""
        # Bumped on every load so a slow fetch the user has already switched
        # away from cannot overwrite the view that replaced it.
        self._token = 0

        self._panel = wx.Panel(self)
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self.rich_ctrl = wx.CheckBox(self._panel, label=_("Show in &HTML view"))
        self.rich_ctrl.SetName(_("HTML view"))
        self.rich_ctrl.SetValue(bool(self._want_rich))
        self.rich_ctrl.Bind(wx.EVT_CHECKBOX, self.on_rich_checkbox)
        self._sizer.Add(self.rich_ctrl, 0, wx.ALL, 8)
        self.content_ctrl = wx.TextCtrl(
            self._panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        self.content_ctrl.SetName(_("Article text"))
        self.content_ctrl.Bind(wx.EVT_TEXT_COPY, self._on_copy)
        self._sizer.Add(self.content_ctrl, 1, wx.EXPAND)
        self._panel.SetSizer(self._sizer)

        self.CreateStatusBar()
        self._build_menu_bar()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._apply_reader_mode()
        self.Centre()
        self.Show()
        self.start_load()

    # -- reader surfaces ---------------------------------------------------

    def _ensure_rich_view(self):
        """Create the AccessibleWebView on first use; None if no backend exists."""
        if self._rich_view is not None:
            return self._rich_view
        if self._rich_view_unavailable:
            return None
        try:
            from wx_accessible_webview import AccessibleWebView
        except Exception:
            self._rich_view_unavailable = True
            return None
        try:
            rv = AccessibleWebView(
                self._panel,
                title=_("Article text"),
                lang=article_lang.app_ui_language(),
                live_region=False,
                # Ours, not the library's: its option diverts every navigation,
                # <iframe> loads included, which sent embeds to a browser
                # window instead of rendering them inline (issue #102).
                open_links_externally=False,
                on_return=self._on_rich_view_return,
            )
        except Exception:
            log.exception("Failed to create the rich reader for the article window")
            self._rich_view_unavailable = True
            return None
        if not getattr(rv, "using_webview", False):
            # The library fell back to a degraded text control; ours is better.
            self._rich_view_unavailable = True
            try:
                rv.control.Destroy()
            except Exception:
                pass
            return None
        self._rich_view = rv
        rich_view_links.attach(rv.view)
        self._sizer.Add(rv.control, 1, wx.EXPAND)
        rv.control.Hide()
        self._panel.Layout()
        return rv

    def _rich_ready(self) -> bool:
        """True when the rich reader was asked for AND a WebView backend exists."""
        return bool(self._want_rich and self._ensure_rich_view() is not None)

    def _apply_reader_mode(self) -> bool:
        """Show the reader the current mode calls for; return True if rich."""
        use_rich = self._rich_ready()
        try:
            self.content_ctrl.Show(not use_rich)
            if self._rich_view is not None:
                self._rich_view.control.Show(use_rich)
            self._panel.Layout()
        except Exception:
            log.exception("Failed to switch the article window's reader")
        item = getattr(self, "_rich_menu_item", None)
        if item is not None:
            try:
                item.Check(use_rich)
            except Exception:
                pass
        ctrl = getattr(self, "rich_ctrl", None)
        if ctrl is not None:
            try:
                ctrl.SetValue(use_rich)
            except Exception:
                pass
        if self._want_rich and not use_rich:
            # A silent downgrade would read as "the checkbox did nothing".
            self.SetStatusText(
                _("The HTML view is not available on this system; showing plain text.")
            )
        return use_rich

    def _on_rich_view_return(self) -> None:
        """Escape inside the web view closes the window, as it does elsewhere."""
        self.Close()

    def _focus_reader(self) -> None:
        try:
            if self._rich_ready() and self._rich_view is not None:
                self._rich_view.focus()
            else:
                self.content_ctrl.SetFocus()
        except Exception:
            log.debug("Could not focus the article window's reader", exc_info=True)

    # -- loading -----------------------------------------------------------

    def start_load(self) -> None:
        """Show what is already loaded for this reader, or fetch the page."""
        rich = self._rich_ready()
        cached = self._loaded.get(rich)
        if cached is not None:
            self._show(cached, announce=False)
            self._focus_reader()
            return
        self._token += 1
        token = self._token
        loading = _("Loading article...")
        self._render(
            "<article><p>" + loading + "</p></article>" if rich else loading, rich
        )
        self.SetTitle(_("Opening article..."))
        self.SetStatusText(_("Loading: {url}").format(url=self.url))
        self._focus_reader()
        threading.Thread(
            target=self._load_worker, args=(self.url, rich, token), daemon=True
        ).start()

    def _load_worker(self, url: str, rich: bool, token: int) -> None:
        result = open_article.load_article(url, rich=rich)
        if result.ok and not rich and callable(self._translate):
            try:
                result = result._replace(content=self._translate(result.content))
            except Exception:
                log.debug("Translating the opened article failed", exc_info=True)
        try:
            wx.CallAfter(self._apply_result, result, token)
        except Exception:
            pass

    def _apply_result(self, result, token: int) -> None:
        if token != self._token or not self:
            return
        self._loaded[bool(result.rich)] = result
        self._show(result, announce=True)

    def _show(self, result, announce: bool) -> None:
        self._title = result.title or self._title
        self.SetTitle(self._title or self.url or _("Article"))
        self._render(result.content, bool(result.rich), refresh_accessibility=announce)
        if not announce:
            return
        message = (
            _("Article loaded.") if result.ok else _("This page could not be read.")
        )
        self.SetStatusText(message)
        self._announce(message)

    def _announce(self, message: str) -> None:
        """Say that the load finished, on every platform.

        The reader pane can stay quiet about an async full-text swap because
        the user got there by focusing it and the screen reader re-reads the
        control. Here nothing moves: the window opened saying "Loading
        article...", focus is already in the reader, and the text is replaced
        underneath it. Without a cue there is no way to tell a page that is
        still loading from one that arrived — or from one that failed.
        """
        announce = getattr(self.GetParent(), "_announce_event", None)
        if not callable(announce):
            return
        try:
            announce("general", message)
        except Exception:
            log.debug("Could not announce the article window's load", exc_info=True)

    def _render(self, content: str, rich: bool, refresh_accessibility: bool = False) -> None:
        if rich:
            rv = self._ensure_rich_view()
            if rv is None:
                return
            try:
                set_accessible_webview_content(rv, content)
                if refresh_accessibility:
                    notify_reader_content_changed(rv.control, tree_changed=True)
            except Exception:
                log.exception("Failed to set the article window's rich content")
            return
        try:
            if replace_text_control_value(self.content_ctrl, content):
                force_ltr_reading(self.content_ctrl)
                self.content_ctrl.SetInsertionPoint(0)
            if refresh_accessibility:
                notify_reader_content_changed(self.content_ctrl)
        except Exception:
            log.exception("Failed to set the article window's text")

    # -- menus and commands ------------------------------------------------

    def _menu_item(self, menu, label, handler, help_text=""):
        item = menu.Append(wx.ID_ANY, label, help_text)
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def _build_menu_bar(self):
        mb = wx.MenuBar()

        file_menu = wx.Menu()
        self._menu_item(
            file_menu, _("Open in &Browser"), self.on_open_in_browser,
            _("Open this address in your web browser"),
        )
        self._menu_item(
            file_menu, _("Re&load"), self.on_reload, _("Fetch this page again"),
        )
        file_menu.AppendSeparator()
        self._menu_item(
            file_menu, _("Close &Window\tCtrl+W"), lambda e: self.Close(),
            _("Close this article window"),
        )
        mb.Append(file_menu, _("&File"))

        edit_menu = wx.Menu()
        self._menu_item(
            edit_menu, _("&Copy Text"), self.on_copy_text,
            _("Copy the whole article to the clipboard"),
        )
        self._menu_item(
            edit_menu, _("Copy &Link"), self.on_copy_link,
            _("Copy this article's address to the clipboard"),
        )
        mb.Append(edit_menu, _("&Edit"))

        view_menu = wx.Menu()
        self._rich_menu_item = view_menu.AppendCheckItem(
            wx.ID_ANY, _("&HTML View") + "\tCtrl+Shift+H",
            _("Show the page as formatted HTML instead of plain text"),
        )
        self._rich_menu_item.Check(bool(self._want_rich))
        self.Bind(wx.EVT_MENU, self.on_toggle_rich_view, self._rich_menu_item)
        mb.Append(view_menu, _("&View"))

        self.SetMenuBar(mb)
        apply_menubar_mnemonics(mb)
        return mb

    def on_toggle_rich_view(self, _event=None) -> None:
        """View > HTML View: swap readers, reusing whatever is already loaded."""
        self._want_rich = not self._want_rich
        self._apply_reader_mode()
        self.start_load()

    def on_rich_checkbox(self, _event=None) -> None:
        """Result-window checkbox: switch readers without closing the page."""
        self._want_rich = bool(self.rich_ctrl.GetValue())
        self._apply_reader_mode()
        self.start_load()

    def on_reload(self, _event=None) -> None:
        self._loaded.clear()
        self.start_load()

    def on_open_in_browser(self, _event=None) -> None:
        if not self.url:
            return
        try:
            webbrowser.open(self.url)
        except Exception:
            log.exception("Could not open %s in a browser", self.url)
            wx.MessageBox(
                _("The link could not be opened in your browser."),
                _("Open Article"), wx.ICON_ERROR,
            )

    def on_copy_link(self, _event=None) -> None:
        self._to_clipboard(self.url, _("Link copied."))

    def on_copy_text(self, _event=None) -> None:
        """Copy the article as text, from whichever reader is showing it."""
        result = self._loaded.get(self._rich_ready())
        if result is None:
            result = next(iter(self._loaded.values()), None)
        if result is None:
            return
        text = str(result.content or "")
        if result.rich:
            text = utils.collapse_blank_lines(utils.html_to_text(text))
        self._to_clipboard(text, _("Article text copied."))

    def _to_clipboard(self, text: str, status: str) -> None:
        if not str(text or "").strip():
            return
        try:
            clipboard = wx.TheClipboard
            if not clipboard.Open():
                return
            try:
                clipboard.SetData(wx.TextDataObject(str(text)))
                clipboard.Flush()
            finally:
                clipboard.Close()
        except Exception:
            log.exception("Could not copy from the article window")
            return
        self.SetStatusText(status)

    def _on_copy(self, event) -> None:
        if copy_textctrl_selection_to_clipboard(self.content_ctrl):
            return
        event.Skip()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
            return
        event.Skip()

    def _on_close(self, event) -> None:
        # Stop any in-flight fetch from touching a destroyed window.
        self._token += 1
        event.Skip()
        self.Destroy()
