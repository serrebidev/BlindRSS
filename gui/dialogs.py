import wx
import wx.adv
import concurrent.futures
import copy
import queue
import re
import threading
import webbrowser
import time
import logging
import sys
from urllib.parse import urlparse
from core.discovery import (
    discover_feed,
    is_ytdlp_supported,
    get_ytdlp_searchable_sites,
    get_adult_searchable_sites,
    canonical_search_result_key,
    search_result_quality_score,
    resolve_quick_url_title,
    resolve_ytdlp_url_enrichment,
    search_ytdlp_site,
    supports_quick_url_title,
    search_youtube_feeds,
    search_soundcloud_feeds,
    search_mixcloud_feeds,
    search_mastodon_feeds,
    search_bluesky_feeds,
    search_piefed_feeds,
)
from core import article_columns
from core import utils
from core import config as config_mod
from core import equalizer as equalizer_mod
from core import shortcuts as shortcuts_mod
from core import announcements as announcements_mod
from .shortcut_keys import event_to_accel
from .menu_mnemonics import apply_menu_mnemonics
from .widgets import CheckListCtrl
from core import windows_integration
from core.casting import CastingManager
from core import inoreader_oauth
from core import translation as translation_mod
from core import filters as filters_mod
from core.vlc_options import build_vlc_instance_args
from core.retention import (
    RETENTION_CHOICES,
    RETENTION_DEFAULT,
    normalize_retention,
    retention_label,
)
from core.i18n import _, ngettext
from core.categories import (
    UNCATEGORIZED,
    category_display_name,
    normalize_category_input,
)

log = logging.getLogger(__name__)


class ColumnLayoutPanel(wx.Panel):
    """Reorder/show/hide the article-list columns (article list columns).

    Shared by the Settings dialog (global layout) and the Feed Properties dialog
    (per-feed override), so both places behave identically. With
    ``allow_inherit`` the panel grows a "use the global layout" checkbox and
    ``get_layout()`` returns None while it is ticked, meaning "inherit".

    A CheckListCtrl carries both jobs at once for a screen reader: the item
    order IS the column order, and the checkbox IS visibility, so NVDA
    announces position and state together without a separate widget to
    correlate. (wx.CheckListBox is unusable here: NVDA cannot see its painted
    checkboxes at all — see gui.widgets.CheckListCtrl.)
    """

    def __init__(self, parent, layout=None, allow_inherit: bool = False):
        super().__init__(parent)
        self._allow_inherit = bool(allow_inherit)
        self._layout = article_columns.normalize_layout(layout)

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.inherit_ctrl = None
        if self._allow_inherit:
            self.inherit_ctrl = wx.CheckBox(self, label=_("&Use the global column layout"))
            self.inherit_ctrl.SetName(_("Use the global column layout"))
            self.inherit_ctrl.SetValue(layout is None)
            self.inherit_ctrl.Bind(wx.EVT_CHECKBOX, lambda e: self._sync_enabled())
            sizer.Add(self.inherit_ctrl, 0, wx.ALL, 5)

        sizer.Add(
            wx.StaticText(self, label=_(
                "Columns (checked = shown). Press Space to show or hide a column; "
                "use Move up / Move down to reorder:"
            )),
            0, wx.ALL, 5,
        )
        self.list_box = CheckListCtrl(self)
        self.list_box.SetName(_("Article list columns"))
        self.list_box.on_user_check = self._on_check
        sizer.Add(self.list_box, 1, wx.EXPAND | wx.ALL, 5)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        # Reuse the exact msgids the Keyboard Shortcuts and Equalizer dialogs
        # already use -- a case-variant near-duplicate ("Move &up") would be a
        # second msgid meaning the same thing, which every translator then has
        # to translate again and which msgmerge only ever fuzzy-matches.
        self.up_btn = wx.Button(self, label=_("Move &Up"))
        self.down_btn = wx.Button(self, label=_("Move &Down"))
        self.reset_btn = wx.Button(self, label=_("Reset All to &Defaults"))
        self.up_btn.Bind(wx.EVT_BUTTON, lambda e: self._move(-1))
        self.down_btn.Bind(wx.EVT_BUTTON, lambda e: self._move(1))
        self.reset_btn.Bind(wx.EVT_BUTTON, lambda e: self._reset())
        btn_row.Add(self.up_btn, 0, wx.ALL, 5)
        btn_row.Add(self.down_btn, 0, wx.ALL, 5)
        btn_row.Add(self.reset_btn, 0, wx.ALL, 5)
        sizer.Add(btn_row, 0)

        sizer.Add(
            wx.StaticText(self, label=_("Title is always the first column and cannot be hidden.")),
            0, wx.ALL, 5,
        )

        self.SetSizer(sizer)
        self._rebuild()
        self._sync_enabled()

    def _item_label(self, entry) -> str:
        label = article_columns.label_for(entry["key"])
        if entry["key"] == article_columns.PINNED_KEY:
            return _("{column} (always first)").format(column=label)
        return label

    def _rebuild(self, select_key: str | None = None) -> None:
        """Repaint the list from self._layout, keeping `select_key` focused."""
        self.list_box.Set([self._item_label(e) for e in self._layout])
        for i, entry in enumerate(self._layout):
            self.list_box.Check(i, bool(entry.get("visible", True)))
        if select_key is not None:
            index = next((i for i, e in enumerate(self._layout) if e["key"] == select_key), 0)
            self.list_box.SetSelection(index)
            # Keep the moved row focused so a screen reader announces its new
            # position instead of dropping the user back at the top.
            self.list_box.EnsureVisible(index)
        elif self._layout:
            self.list_box.SetSelection(0)

    def _selected_key(self) -> str | None:
        index = self.list_box.GetSelection()
        if index is None or index < 0 or index >= len(self._layout):
            return None
        return self._layout[index]["key"]

    def _on_check(self, index: int, checked: bool) -> None:
        if 0 <= index < len(self._layout):
            key = self._layout[index]["key"]
            if key == article_columns.PINNED_KEY:
                # Title cannot be hidden: undo the tick rather than let the
                # checkbox disagree with what set_visible will actually store.
                self.list_box.Check(index, True)
                return
            self._layout = article_columns.set_visible(self._layout, key, checked)

    def _move(self, delta: int) -> None:
        key = self._selected_key()
        if not key or key == article_columns.PINNED_KEY:
            return
        self._layout = article_columns.move_key(self._layout, key, delta)
        self._rebuild(select_key=key)

    def _reset(self) -> None:
        self._layout = article_columns.default_layout()
        self._rebuild()

    def _sync_enabled(self) -> None:
        enabled = not (self.inherit_ctrl is not None and self.inherit_ctrl.GetValue())
        for ctrl in (self.list_box, self.up_btn, self.down_btn, self.reset_btn):
            ctrl.Enable(enabled)

    def get_layout(self):
        """The edited layout, or None when it should inherit the global one."""
        if self.inherit_ctrl is not None and self.inherit_ctrl.GetValue():
            return None
        return article_columns.normalize_layout(self._layout)


class AddFeedDialog(wx.Dialog):
    def __init__(self, parent, categories=None, initial_url: str = ""):
        super().__init__(parent, title=_("Add Feed"), size=(400, 250))
        
        self.category_identities = list(categories or [UNCATEGORIZED])
        self.categories = [category_display_name(category) for category in self.category_identities]
        self._check_timer = None
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # URL Input
        sizer.Add(wx.StaticText(self, label=_("Feed or Media URL:")), 0, wx.ALL, 5)
        self.url_ctrl = wx.TextCtrl(self)
        self.url_ctrl.SetName("Feed or Media URL")
        self.url_ctrl.SetHint(_("https://example.com/feed or a YouTube/podcast URL"))
        if initial_url:
            # Prefill from "Detect Feeds on Page" (issue #76). SetValue fires
            # EVT_TEXT, so the compatibility hint updates as if typed.
            self.url_ctrl.SetValue(str(initial_url))
        wx.CallAfter(self.url_ctrl.SetFocus)
        sizer.Add(self.url_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Compatibility Hint
        self.status_lbl = wx.StaticText(self, label="")
        self.status_lbl.SetForegroundColour(wx.Colour(0, 128, 0)) # Greenish
        sizer.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # Category Input
        sizer.Add(wx.StaticText(self, label=_("Category:")), 0, wx.ALL, 5)
        self.cat_ctrl = wx.ComboBox(self, choices=self.categories, style=wx.CB_DROPDOWN)
        self.cat_ctrl.SetName("Category")
        if self.categories:
            # Try to select 'YouTube' if it exists
            yt_idx = self.cat_ctrl.FindString("YouTube")
            if yt_idx != wx.NOT_FOUND:
                self.cat_ctrl.SetSelection(yt_idx)
            else:
                self.cat_ctrl.SetSelection(0)
        sizer.Add(self.cat_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        
        self.SetSizer(sizer)
        self.Centre()
        
        self.url_ctrl.Bind(wx.EVT_TEXT, self.on_url_text)

    def on_url_text(self, event):
        url = self.url_ctrl.GetValue().strip()
        if not url:
            self.status_lbl.SetLabel("")
            return
            
        if self._check_timer:
            self._check_timer.Stop()
            
        self._check_timer = wx.CallLater(500, self._perform_compatibility_check, url)

    def _perform_compatibility_check(self, url):
        # Quick check first
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        if "youtube.com" in domain or "youtu.be" in domain:
            self.status_lbl.SetLabel(_("OK: Recognized as YouTube source"))
            # Auto-switch category to YouTube if available
            yt_idx = self.cat_ctrl.FindString("YouTube")
            if yt_idx != wx.NOT_FOUND:
                self.cat_ctrl.SetSelection(yt_idx)
            return

        self.status_lbl.SetLabel(_("Checking compatibility..."))
        # Background thread for heavier yt-dlp check
        threading.Thread(target=self._heavy_check, args=(url,), daemon=True).start()

    def _heavy_check(self, url):
        if is_ytdlp_supported(url):
            wx.CallAfter(self.status_lbl.SetLabel, "OK: Supported by yt-dlp")
        else:
            wx.CallAfter(self.status_lbl.SetLabel, "")

    def get_data(self):
        category = normalize_category_input(
            self.cat_ctrl.GetValue(), self.category_identities
        )
        return utils.normalize_user_submitted_url(self.url_ctrl.GetValue()), category


class AddShortcutsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Add BlindRSS Shortcuts"), size=(460, 280))

        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = (
            _(
                "Choose where to add BlindRSS shortcuts.\n"
                "Taskbar pinning may be limited by your Windows version/policies."
            )
        )
        sizer.Add(wx.StaticText(self, label=intro), 0, wx.ALL, 10)

        self.desktop_chk = wx.CheckBox(self, label=_("Desktop"))
        self.desktop_chk.SetValue(True)
        sizer.Add(self.desktop_chk, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.start_menu_chk = wx.CheckBox(self, label=_("Start Menu"))
        self.start_menu_chk.SetValue(True)
        sizer.Add(self.start_menu_chk, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.taskbar_chk = wx.CheckBox(self, label=_("Taskbar"))
        self.taskbar_chk.SetValue(False)
        sizer.Add(self.taskbar_chk, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        if not sys.platform.startswith("win"):
            self.desktop_chk.Disable()
            self.start_menu_chk.Disable()
            self.taskbar_chk.Disable()

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.SetSizer(sizer)
        self.Centre()

    def get_data(self):
        return {
            "desktop": bool(self.desktop_chk.GetValue()),
            "start_menu": bool(self.start_menu_chk.GetValue()),
            "taskbar": bool(self.taskbar_chk.GetValue()),
        }


class ExcludeNotificationFeedsDialog(wx.Dialog):
    def __init__(self, parent, feed_entries=None, excluded_ids=None):
        super().__init__(parent, title=_("Exclude Feeds from Notifications"), size=(480, 420))
        self._feed_entries = list(feed_entries or [])
        self._excluded_ids = {str(x) for x in (excluded_ids or []) if str(x or "").strip()}
        self._feed_id_by_index = {}
        self._feed_base_labels = []

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            wx.StaticText(
                self,
                label=_(
                    "Feeds are checked by default.\n"
                    "Uncheck feeds that should not send notifications."
                ),
            ),
            0,
            wx.ALL,
            10,
        )

        labels = []
        for idx, (feed_id, title) in enumerate(self._feed_entries):
            fid = str(feed_id or "").strip()
            t = str(title or "").strip() or fid
            if not fid:
                continue
            self._feed_id_by_index[len(labels)] = fid
            self._feed_base_labels.append(t)
            labels.append(t)

        self.feed_list = CheckListCtrl(self)
        self.feed_list.SetName("Feeds (checked feeds send notifications)")
        self.feed_list.Set(labels)
        sizer.Add(self.feed_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        for idx, fid in self._feed_id_by_index.items():
            should_notify = fid not in self._excluded_ids
            try:
                self.feed_list.Check(idx, should_notify)
            except Exception:
                pass

        self._selection_status = wx.StaticText(self, label="")
        sizer.Add(self._selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.feed_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_feed_selected)
        self.feed_list.on_user_check = self.on_feed_toggled

        actions = wx.BoxSizer(wx.HORIZONTAL)
        check_all_btn = wx.Button(self, label=_("Check All"))
        uncheck_all_btn = wx.Button(self, label=_("Uncheck All"))
        actions.Add(check_all_btn, 0, wx.RIGHT, 8)
        actions.Add(uncheck_all_btn, 0)
        sizer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        check_all_btn.Bind(wx.EVT_BUTTON, self.on_check_all)
        uncheck_all_btn.Bind(wx.EVT_BUTTON, self.on_uncheck_all)

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.SetSizer(sizer)
        self.Centre()

        if not labels:
            self.feed_list.Disable()
            check_all_btn.Disable()
            uncheck_all_btn.Disable()
            self._selection_status.SetLabel(_("No feeds available."))
        else:
            try:
                self.feed_list.SetSelection(0)
            except Exception:
                pass
            self._update_selection_status()

    def _is_checked(self, index):
        try:
            return bool(self.feed_list.IsChecked(index))
        except Exception:
            return True

    def _update_selection_status(self, index=None):
        if index is None or index == wx.NOT_FOUND:
            try:
                index = self.feed_list.GetSelection()
            except Exception:
                index = wx.NOT_FOUND
        if index == wx.NOT_FOUND:
            self._selection_status.SetLabel(_("No feed selected."))
            return
        if index < 0 or index >= len(self._feed_base_labels):
            self._selection_status.SetLabel("")
            return
        checked = self._is_checked(index)
        check_state = _("checked") if checked else _("unchecked")
        self._selection_status.SetLabel(
            _(
                "Selected feed: {name}. {state}."
            ).format(name=self._feed_base_labels[index], state=check_state)
        )

    def on_feed_selected(self, event):
        self._update_selection_status(event.GetIndex())
        event.Skip()

    def on_feed_toggled(self, index, checked):
        self._update_selection_status(index)

    def on_check_all(self, event):
        try:
            for i in range(self.feed_list.GetCount()):
                self.feed_list.Check(i, True)
        except Exception:
            pass
        self._update_selection_status()

    def on_uncheck_all(self, event):
        try:
            for i in range(self.feed_list.GetCount()):
                self.feed_list.Check(i, False)
        except Exception:
            pass
        self._update_selection_status()

    def get_excluded_feed_ids(self):
        excluded = []
        for idx, fid in self._feed_id_by_index.items():
            try:
                checked = bool(self.feed_list.IsChecked(idx))
            except Exception:
                checked = True
            if not checked:
                excluded.append(fid)
        return excluded


class ImportSiteCookiesDialog(wx.Dialog):
    """Import a browser cookies.txt so challenge-protected sites open (issue #79).

    Sites behind a Cloudflare-style "checking your browser" interstitial only
    answer to a session that already passed the challenge in a real browser.
    The user exports cookies with a cookies.txt extension and imports them
    here; the fetch layer then sends the matching cookies plus the browser's
    User-Agent string (Cloudflare requires the exact UA the cookie was issued
    to).
    """

    def __init__(self, parent):
        super().__init__(parent, title=_("Import Site Cookies"))
        from core import site_cookies as site_cookies_mod
        self._site_cookies = site_cookies_mod

        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            self,
            label=_(
                "Some websites show a browser verification page (for example a "
                "Cloudflare challenge) before their feeds. To read them in "
                "BlindRSS:\n"
                "1. Open the website in your web browser and wait for it to load.\n"
                "2. Export its cookies with a \"cookies.txt\" browser extension.\n"
                "3. Choose the exported file below.\n"
                "Also paste your browser's User-Agent string (search the web for "
                "\"what is my user agent\" to see it) so the site accepts the "
                "cookies."
            ),
        )
        intro.Wrap(520)
        sizer.Add(intro, 0, wx.ALL, 10)

        # One-click path for Firefox-family browsers: their cookies.sqlite is
        # unencrypted and readable directly. Chromium's App-Bound Encryption
        # blocks direct reads, hence the extension link below.
        import_browser_btn = wx.Button(self, label=_("Import from &Browser..."))
        import_browser_btn.Bind(wx.EVT_BUTTON, self._on_import_from_browser)
        sizer.Add(import_browser_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        extension_link = wx.adv.HyperlinkCtrl(
            self,
            label=_('Get the "Get cookies.txt LOCALLY" extension for Chrome-based browsers'),
            url=(
                "https://chromewebstore.google.com/detail/get-cookiestxt-locally/"
                "cclelndahbckbenkjhflpdbgdldlbecc?hl=en"
            ),
        )
        extension_link.SetName("Get cookies.txt LOCALLY extension link")
        sizer.Add(extension_link, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        file_row = wx.BoxSizer(wx.HORIZONTAL)
        file_row.Add(
            wx.StaticText(self, label=_("Cookies file:")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6,
        )
        self.file_ctrl = wx.TextCtrl(self)
        self.file_ctrl.SetName("Cookies file path")
        file_row.Add(self.file_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        browse_btn = wx.Button(self, label=_("&Browse..."))
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse)
        file_row.Add(browse_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(file_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        ua_row = wx.BoxSizer(wx.HORIZONTAL)
        ua_row.Add(
            wx.StaticText(self, label=_("Browser User-Agent (recommended):")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6,
        )
        self.ua_ctrl = wx.TextCtrl(self)
        self.ua_ctrl.SetName("Browser User-Agent")
        self.ua_ctrl.SetValue(self._site_cookies.get_user_agent())
        ua_row.Add(self.ua_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(ua_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.status_lbl = wx.StaticText(self, label="")
        sizer.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if btn_sizer:
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        ok_btn = self.FindWindow(wx.ID_OK)
        if ok_btn:
            ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)

        self.SetSizerAndFit(sizer)
        self.Centre()
        wx.CallAfter(self.file_ctrl.SetFocus)

    def _on_browse(self, event):
        dlg = wx.FileDialog(
            self,
            _("Choose the exported cookies.txt"),
            wildcard=f'{_("Cookies")} (*.txt)|*.txt|{_("All files")} (*.*)|*.*',
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self.file_ctrl.SetValue(dlg.GetPath())
        finally:
            dlg.Destroy()

    def _on_import_from_browser(self, event):
        try:
            profiles = self._site_cookies.list_browser_profiles()
        except Exception:
            log.exception("Browser profile discovery failed")
            profiles = []
        if not profiles:
            wx.MessageBox(
                _(
                    "No supported browser profiles were found.\n\n"
                    "Cookies can be read directly from Firefox-based browsers "
                    "(Firefox, LibreWolf, Waterfox, Floorp, Zen). Chrome-based "
                    "browsers encrypt their cookies; use the "
                    "\"Get cookies.txt LOCALLY\" extension linked above and "
                    "import the exported file instead."
                ),
                _("Import Site Cookies"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        chosen = profiles[0]
        if len(profiles) > 1:
            labels = [f'{p["browser"]} — {p["profile"]}' for p in profiles]
            dlg = wx.SingleChoiceDialog(
                self,
                _("Choose the browser profile to import cookies from:"),
                _("Import Site Cookies"),
                labels,
            )
            try:
                if dlg.ShowModal() != wx.ID_OK:
                    return
                chosen = profiles[dlg.GetSelection()]
            finally:
                dlg.Destroy()

        try:
            count = self._site_cookies.import_from_browser_profile(chosen["path"])
        except Exception:
            log.exception("Browser cookie import failed for %s", chosen["path"])
            wx.MessageBox(
                _("Could not read cookies from {browser}.").format(browser=chosen["browser"]),
                _("Import Site Cookies"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return

        # Cloudflare only honors a clearance cookie together with the exact
        # UA it was issued to, so pre-fill the browser's own UA string.
        try:
            ua = self._site_cookies.firefox_profile_user_agent(chosen["path"])
        except Exception:
            ua = ""
        if ua:
            self.ua_ctrl.SetValue(ua)
            self._site_cookies.set_user_agent(ua)
        message = ngettext("Imported {count} cookies from {browser}.", "Imported {count} cookies from {browser}.", count).format(
            count=count, browser=chosen["browser"]
        )
        self.status_lbl.SetLabel(message)
        wx.MessageBox(message, _("Import Site Cookies"), wx.OK | wx.ICON_INFORMATION, self)

    def _on_ok(self, event):
        path = (self.file_ctrl.GetValue() or "").strip()
        ua = (self.ua_ctrl.GetValue() or "").strip()
        if not path:
            # Allow saving just an updated UA when a jar was imported earlier.
            self._site_cookies.set_user_agent(ua)
            event.Skip()
            return
        ok, message = self._site_cookies.validate_jar_file(path)
        if not ok:
            self.status_lbl.SetLabel(message)
            wx.MessageBox(message, _("Import Site Cookies"), wx.OK | wx.ICON_ERROR, self)
            return
        try:
            self._site_cookies.import_jar(path)
        except (ValueError, OSError) as exc:
            wx.MessageBox(str(exc), _("Import Site Cookies"), wx.OK | wx.ICON_ERROR, self)
            return
        self._site_cookies.set_user_agent(ua)
        event.Skip()


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, config, notification_feeds=None):
        super().__init__(parent, title=_("Settings"), size=(500, 450))
        
        self._TRANSLATION_LANGUAGE_PRESETS = [
            (_("Abkhazian"), "ab"),
            (_("Afar"), "aa"),
            (_("Afrikaans"), "af"),
            (_("Akan"), "ak"),
            (_("Albanian"), "sq"),
            (_("Amharic"), "am"),
            (_("Arabic"), "ar"),
            (_("Aragonese"), "an"),
            (_("Armenian"), "hy"),
            (_("Assamese"), "as"),
            (_("Avaric"), "av"),
            (_("Avestan"), "ae"),
            (_("Aymara"), "ay"),
            (_("Azerbaijani"), "az"),
            (_("Bambara"), "bm"),
            (_("Bashkir"), "ba"),
            (_("Basque"), "eu"),
            (_("Belarusian"), "be"),
            (_("Bengali"), "bn"),
            (_("Bislama"), "bi"),
            (_("Bosnian"), "bs"),
            (_("Breton"), "br"),
            (_("Bulgarian"), "bg"),
            (_("Burmese"), "my"),
            (_("Catalan"), "ca"),
            (_("Chamorro"), "ch"),
            (_("Chechen"), "ce"),
            (_("Chichewa"), "ny"),
            (_("Chinese (Simplified)"), "zh-CN"),
            (_("Chinese (Traditional)"), "zh-TW"),
            (_("Chinese"), "zh"),
            (_("Church Slavic"), "cu"),
            (_("Chuvash"), "cv"),
            (_("Cornish"), "kw"),
            (_("Corsican"), "co"),
            (_("Cree"), "cr"),
            (_("Croatian"), "hr"),
            (_("Czech"), "cs"),
            (_("Danish"), "da"),
            (_("Divehi"), "dv"),
            (_("Dutch (Belgium)"), "nl-BE"),
            (_("Dutch"), "nl"),
            (_("Dzongkha"), "dz"),
            (_("English"), "en"),
            (_("Esperanto"), "eo"),
            (_("Estonian"), "et"),
            (_("Ewe"), "ee"),
            (_("Faroese"), "fo"),
            (_("Fijian"), "fj"),
            (_("Finnish"), "fi"),
            (_("French"), "fr"),
            (_("Fulah"), "ff"),
            (_("Galician"), "gl"),
            (_("Ganda"), "lg"),
            (_("Georgian"), "ka"),
            (_("German"), "de"),
            (_("Guarani"), "gn"),
            (_("Gujarati"), "gu"),
            (_("Haitian"), "ht"),
            (_("Hausa"), "ha"),
            (_("Hebrew"), "he"),
            (_("Herero"), "hz"),
            (_("Hindi"), "hi"),
            (_("Hiri Motu"), "ho"),
            (_("Hungarian"), "hu"),
            (_("Icelandic"), "is"),
            (_("Ido"), "io"),
            (_("Igbo"), "ig"),
            (_("Indonesian"), "id"),
            (_("Interlingua (International Auxiliary Language Association)"), "ia"),
            (_("Interlingue"), "ie"),
            (_("Inuktitut"), "iu"),
            (_("Inupiaq"), "ik"),
            (_("Irish"), "ga"),
            (_("Italian"), "it"),
            (_("Japanese"), "ja"),
            (_("Javanese"), "jv"),
            (_("Kalaallisut"), "kl"),
            (_("Kannada"), "kn"),
            (_("Kanuri"), "kr"),
            (_("Kashmiri"), "ks"),
            (_("Kazakh"), "kk"),
            (_("Khmer"), "km"),
            (_("Kikuyu"), "ki"),
            (_("Kinyarwanda"), "rw"),
            (_("Kirghiz"), "ky"),
            (_("Komi"), "kv"),
            (_("Kongo"), "kg"),
            (_("Korean"), "ko"),
            (_("Kuanyama"), "kj"),
            (_("Kurdish"), "ku"),
            (_("Lao"), "lo"),
            (_("Latin"), "la"),
            (_("Latvian"), "lv"),
            (_("Limburgan"), "li"),
            (_("Lingala"), "ln"),
            (_("Lithuanian"), "lt"),
            (_("Luba-Katanga"), "lu"),
            (_("Luxembourgish"), "lb"),
            (_("Macedonian"), "mk"),
            (_("Malagasy"), "mg"),
            (_("Malay (macrolanguage)"), "ms"),
            (_("Malayalam"), "ml"),
            (_("Maltese"), "mt"),
            (_("Manx"), "gv"),
            (_("Maori"), "mi"),
            (_("Marathi"), "mr"),
            (_("Marshallese"), "mh"),
            (_("Modern Greek (1453-)"), "el"),
            (_("Mongolian"), "mn"),
            (_("Nauruan"), "na"),
            (_("Navajo"), "nv"),
            (_("Ndonga"), "ng"),
            (_("Nepali (macrolanguage)"), "ne"),
            (_("North Ndebele"), "nd"),
            (_("Northern Sami"), "se"),
            (_("Norwegian"), "no"),
            (_("Norwegian Bokmal"), "nb"),
            (_("Norwegian Nynorsk"), "nn"),
            (_("Occitan (post 1500)"), "oc"),
            (_("Ojibwa"), "oj"),
            (_("Oriya (macrolanguage)"), "or"),
            (_("Oromo"), "om"),
            (_("Ossetian"), "os"),
            (_("Pali"), "pi"),
            (_("Panjabi"), "pa"),
            (_("Persian"), "fa"),
            (_("Polish"), "pl"),
            (_("Portuguese (Brazil)"), "pt-BR"),
            (_("Portuguese (Portugal)"), "pt-PT"),
            (_("Portuguese"), "pt"),
            (_("Pushto"), "ps"),
            (_("Quechua"), "qu"),
            (_("Romanian"), "ro"),
            (_("Romansh"), "rm"),
            (_("Rundi"), "rn"),
            (_("Russian"), "ru"),
            (_("Samoan"), "sm"),
            (_("Sango"), "sg"),
            (_("Sanskrit"), "sa"),
            (_("Sardinian"), "sc"),
            (_("Scottish Gaelic"), "gd"),
            (_("Serbian"), "sr"),
            (_("Serbo-Croatian"), "sh"),
            (_("Shona"), "sn"),
            (_("Sichuan Yi"), "ii"),
            (_("Sindhi"), "sd"),
            (_("Sinhala"), "si"),
            (_("Slovak"), "sk"),
            (_("Slovenian"), "sl"),
            (_("Somali"), "so"),
            (_("South Ndebele"), "nr"),
            (_("Southern Sotho"), "st"),
            (_("Spanish"), "es"),
            (_("Sundanese"), "su"),
            (_("Swahili (macrolanguage)"), "sw"),
            (_("Swati"), "ss"),
            (_("Swedish"), "sv"),
            (_("Tagalog"), "tl"),
            (_("Tahitian"), "ty"),
            (_("Tajik"), "tg"),
            (_("Tamil"), "ta"),
            (_("Tatar"), "tt"),
            (_("Telugu"), "te"),
            (_("Thai"), "th"),
            (_("Tibetan"), "bo"),
            (_("Tigrinya"), "ti"),
            (_("Tonga (Tonga Islands)"), "to"),
            (_("Tsonga"), "ts"),
            (_("Tswana"), "tn"),
            (_("Turkish"), "tr"),
            (_("Turkmen"), "tk"),
            (_("Twi"), "tw"),
            (_("Uighur"), "ug"),
            (_("Ukrainian"), "uk"),
            (_("Urdu"), "ur"),
            (_("Uzbek"), "uz"),
            (_("Venda"), "ve"),
            (_("Vietnamese"), "vi"),
            (_("Volapuk"), "vo"),
            (_("Walloon"), "wa"),
            (_("Welsh"), "cy"),
            (_("Western Frisian"), "fy"),
            (_("Wolof"), "wo"),
            (_("Xhosa"), "xh"),
            (_("Yiddish"), "yi"),
            (_("Yoruba"), "yo"),
            (_("Zhuang"), "za"),
            (_("Zulu"), "zu"),
        ]

        self.config = config
        self._notification_feed_entries = list(notification_feeds or [])
        self._notification_excluded_feed_ids = {
            str(x) for x in (config.get("windows_notifications_excluded_feeds", []) or []) if str(x or "").strip()
        }
        
        notebook = wx.Notebook(self)
        self.notebook = notebook
        
        # General Tab
        general_panel = wx.Panel(notebook)
        general_sizer = wx.BoxSizer(wx.VERTICAL)

        feeds_panel = wx.Panel(notebook)
        feeds_sizer = wx.BoxSizer(wx.VERTICAL)
        downloads_panel = wx.Panel(notebook)
        downloads_sizer = wx.BoxSizer(wx.VERTICAL)
        startup_panel = wx.Panel(notebook)
        startup_sizer = wx.BoxSizer(wx.VERTICAL)
        youtube_panel = wx.Panel(notebook)
        youtube_sizer = wx.BoxSizer(wx.VERTICAL)
        
        refresh_sizer = wx.BoxSizer(wx.HORIZONTAL)
        refresh_sizer.Add(wx.StaticText(feeds_panel, label=_("Refresh Interval:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.refresh_map = {
            _("Never"): 0,
            _("30 seconds"): 30,
            _("1 minute"): 60,
            _("2 minutes"): 120,
            _("3 minutes"): 180,
            _("4 minutes"): 240,
            _("5 minutes"): 300,
            _("10 minutes"): 600,
            _("15 minutes"): 900,
            _("30 minutes"): 1800,
            _("60 minutes"): 3600,
            _("2 hours"): 7200,
            _("3 hours"): 10800,
            _("4 hours"): 14400
        }
        self.refresh_choices = list(self.refresh_map.keys())
        self.refresh_ctrl = wx.Choice(feeds_panel, choices=self.refresh_choices)
        
        # Set initial selection
        current_interval = int(config.get("refresh_interval", 300))
        # Find closest match
        best_choice = "5 minutes"
        min_diff = float('inf')
        for k, v in self.refresh_map.items():
            if v == 0 and current_interval == 0:
                best_choice = k
                break
            if v > 0:
                diff = abs(v - current_interval)
                if diff < min_diff:
                    min_diff = diff
                    best_choice = k
        self.refresh_ctrl.SetStringSelection(best_choice)
        
        refresh_sizer.Add(self.refresh_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(refresh_sizer, 0, wx.EXPAND | wx.ALL, 5)

        search_mode_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_mode_sizer.Add(wx.StaticText(general_panel, label=_("Search Matches:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.search_mode_map = {
            _("Titles only"): "title_only",
            _("Titles and article text"): "title_content",
        }
        self.search_mode_choices = list(self.search_mode_map.keys())
        self.search_mode_ctrl = wx.Choice(general_panel, choices=self.search_mode_choices)
        current_search_mode = str(config.get("search_mode", "title_content") or "title_content")
        selected_label = None
        for label, value in self.search_mode_map.items():
            if value == current_search_mode:
                selected_label = label
                break
        if not selected_label:
            selected_label = next(
                (
                    label
                    for label, value in self.search_mode_map.items()
                    if value == "title_content"
                ),
                self.search_mode_choices[0] if self.search_mode_choices else "",
            )
        self.search_mode_ctrl.SetStringSelection(selected_label)
        search_mode_sizer.Add(self.search_mode_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(search_mode_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        concurrency_sizer = wx.BoxSizer(wx.HORIZONTAL)
        concurrency_sizer.Add(wx.StaticText(feeds_panel, label=_("Max Concurrent Refreshes:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.concurrent_ctrl = wx.SpinCtrl(feeds_panel, min=1, max=50, initial=int(config.get("max_concurrent_refreshes", 6)))
        concurrency_sizer.Add(self.concurrent_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(concurrency_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        per_host_sizer = wx.BoxSizer(wx.HORIZONTAL)
        per_host_sizer.Add(wx.StaticText(feeds_panel, label=_("Max Connections Per Host:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.per_host_ctrl = wx.SpinCtrl(feeds_panel, min=1, max=10, initial=int(config.get("per_host_max_connections", 2)))
        per_host_sizer.Add(self.per_host_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(per_host_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        timeout_sizer = wx.BoxSizer(wx.HORIZONTAL)
        timeout_sizer.Add(wx.StaticText(feeds_panel, label=_("Feed Timeout (seconds):")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.timeout_ctrl = wx.SpinCtrl(feeds_panel, min=5, max=120, initial=int(config.get("feed_timeout_seconds", 15)))
        timeout_sizer.Add(self.timeout_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(timeout_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        retry_sizer = wx.BoxSizer(wx.HORIZONTAL)
        retry_sizer.Add(wx.StaticText(feeds_panel, label=_("Feed Retry Attempts:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.retry_ctrl = wx.SpinCtrl(feeds_panel, min=0, max=5, initial=int(config.get("feed_retry_attempts", 1)))
        retry_sizer.Add(self.retry_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(retry_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Cache views
        cache_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cache_sizer.Add(wx.StaticText(feeds_panel, label=_("Max Cached Views:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.cache_ctrl = wx.SpinCtrl(feeds_panel, min=5, max=100, initial=int(config.get("max_cached_views", 15)))
        cache_sizer.Add(self.cache_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(cache_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Full-text caching
        self.cache_full_text_chk = wx.CheckBox(feeds_panel, label=_("Cache full text in background"))
        self.cache_full_text_chk.SetValue(bool(config.get("cache_full_text", False)))
        feeds_sizer.Add(self.cache_full_text_chk, 0, wx.ALL, 5)
        
        # Downloads
        self.downloads_chk = wx.CheckBox(downloads_panel, label=_("Enable Downloads"))
        self.downloads_chk.SetValue(config.get("downloads_enabled", False))
        downloads_sizer.Add(self.downloads_chk, 0, wx.ALL, 5)

        self.confirm_delete_chk = wx.CheckBox(general_panel, label=_("Confirm before deleting articles"))
        self.confirm_delete_chk.SetValue(bool(config.get("confirm_article_delete", True)))
        general_sizer.Add(self.confirm_delete_chk, 0, wx.ALL, 5)

        # What Delete does to a local article (global default; feeds can override
        # this in Feed Properties). Maps to the delete_behavior config string.
        del_sizer = wx.BoxSizer(wx.HORIZONTAL)
        del_sizer.Add(wx.StaticText(general_panel, label=_("When I delete an article:")), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self._delete_behavior_choices = [
            ("deleted", _("Move it to Deleted Articles (restorable)")),
            ("purge", _("Remove it permanently")),
            ("category", _("Move it to a category")),
        ]
        self.delete_behavior_ctrl = wx.Choice(
            general_panel, choices=[lbl for _k, lbl in self._delete_behavior_choices]
        )
        self.delete_behavior_ctrl.SetName("Delete behavior")
        del_sizer.Add(self.delete_behavior_ctrl, 0, wx.ALL, 5)
        self.delete_category_ctrl = wx.TextCtrl(general_panel)
        self.delete_category_ctrl.SetName("Delete target category (full path)")
        self.delete_category_ctrl.SetHint(_("Category / Path"))
        del_sizer.Add(self.delete_category_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        general_sizer.Add(del_sizer, 0, wx.EXPAND | wx.ALL, 5)

        kind, category = filters_mod.parse_delete_behavior(config.get("delete_behavior", "deleted"))
        self._delete_category_identities = (
            [category] if category and category != UNCATEGORIZED else []
        )
        self.delete_behavior_ctrl.SetSelection(
            next((i for i, (k, _l) in enumerate(self._delete_behavior_choices) if k == kind), 0)
        )
        if category:
            self.delete_category_ctrl.SetValue(category_display_name(category))
        self.delete_behavior_ctrl.Bind(wx.EVT_CHOICE, lambda e: self._sync_delete_category_enabled())
        self._sync_delete_category_enabled()

        dl_path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dl_path_sizer.Add(wx.StaticText(downloads_panel, label=_("Download Path:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.dl_path_ctrl = wx.TextCtrl(downloads_panel, value=config.get("download_path", ""))
        self.dl_path_ctrl.SetName("Download path")
        dl_path_sizer.Add(self.dl_path_ctrl, 1, wx.ALL, 5)
        browse_btn = wx.Button(downloads_panel, label=_("Browse..."))
        browse_btn.SetName("Browse for download folder")
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_dl_path)
        dl_path_sizer.Add(browse_btn, 0, wx.ALL, 5)
        downloads_sizer.Add(dl_path_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        def _make_retention_combo(parent, cfg_value):
            # Config stores stable identifiers ("1_week"); the combobox shows
            # localized labels. Selection index maps back to the identifier on
            # save so display language never leaks into the config (issue #63).
            ids = [ident for ident, _days in RETENTION_CHOICES]
            current = normalize_retention(cfg_value)
            if current not in ids:
                # Legacy value no longer offered in the UI (e.g. "3_months"):
                # keep it selectable so opening Settings doesn't change it.
                ids.append(current)
            combo = wx.ComboBox(
                parent,
                choices=[retention_label(ident) for ident in ids],
                style=wx.CB_READONLY,
            )
            combo.SetSelection(ids.index(current))
            return combo, ids

        retention_sizer = wx.BoxSizer(wx.HORIZONTAL)
        retention_sizer.Add(wx.StaticText(downloads_panel, label=_("Retention Policy:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.retention_ctrl, self._retention_ids_download = _make_retention_combo(
            downloads_panel, config.get("download_retention", RETENTION_DEFAULT)
        )
        retention_sizer.Add(self.retention_ctrl, 0, wx.ALL, 5)
        downloads_sizer.Add(retention_sizer, 0, wx.EXPAND | wx.ALL, 5)

        art_retention_sizer = wx.BoxSizer(wx.HORIZONTAL)
        art_retention_sizer.Add(wx.StaticText(feeds_panel, label=_("Article Retention:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.art_retention_ctrl, self._retention_ids_article = _make_retention_combo(
            feeds_panel, config.get("article_retention", RETENTION_DEFAULT)
        )
        art_retention_sizer.Add(self.art_retention_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(art_retention_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Tray settings
        self.close_tray_chk = wx.CheckBox(startup_panel, label=_("Close to system tray"))
        self.close_tray_chk.SetValue(config.get("close_to_tray", False))
        startup_sizer.Add(self.close_tray_chk, 0, wx.ALL, 5)
        
        self.min_tray_chk = wx.CheckBox(startup_panel, label=_("Minimize to system tray"))
        self.min_tray_chk.SetValue(config.get("minimize_to_tray", True))        
        startup_sizer.Add(self.min_tray_chk, 0, wx.ALL, 5)

        self.start_in_tray_chk = wx.CheckBox(
            startup_panel, label=_("Start BlindRSS in the system tray")
        )
        self.start_in_tray_chk.SetValue(bool(config.get("start_in_system_tray", False)))
        startup_sizer.Add(self.start_in_tray_chk, 0, wx.ALL, 5)

        self.start_maximized_chk = wx.CheckBox(startup_panel, label=_("Always start maximized"))
        self.start_maximized_chk.SetValue(bool(config.get("start_maximized", False)))
        startup_sizer.Add(self.start_maximized_chk, 0, wx.ALL, 5)

        self.debug_mode_chk = wx.CheckBox(general_panel, label=_("Debug mode (show console on startup)"))
        self.debug_mode_chk.SetValue(bool(config.get("debug_mode", False)))     
        general_sizer.Add(self.debug_mode_chk, 0, wx.ALL, 5)

        self.auto_update_chk = wx.CheckBox(startup_panel, label=_("Check for updates on startup"))
        self.auto_update_chk.SetValue(bool(config.get("auto_check_updates", True)))
        startup_sizer.Add(self.auto_update_chk, 0, wx.ALL, 5)

        self.refresh_startup_chk = wx.CheckBox(feeds_panel, label=_("Automatically refresh feeds upon start"))
        self.refresh_startup_chk.SetValue(bool(config.get("refresh_on_startup", True)))
        feeds_sizer.Add(self.refresh_startup_chk, 0, wx.ALL, 5)

        refresh_workload_sizer = wx.BoxSizer(wx.HORIZONTAL)
        refresh_workload_sizer.Add(
            wx.StaticText(feeds_panel, label=_("Local RSS automatic refresh workload:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.ALL,
            5,
        )
        self.automatic_refresh_workload_map = {
            _("Use feed cache (fastest)"): "cached",
            _("Fully refresh feeds at startup"): "startup_full",
            _("Always fully refresh feeds"): "always_full",
        }
        self.automatic_refresh_workload_choices = list(self.automatic_refresh_workload_map.keys())
        self.automatic_refresh_workload_ctrl = wx.Choice(
            feeds_panel,
            choices=self.automatic_refresh_workload_choices,
        )
        self.automatic_refresh_workload_ctrl.SetName(_("Local RSS automatic feed refresh workload"))
        configured_refresh_workload = str(
            config.get("automatic_feed_refresh_workload", "") or ""
        ).strip().lower()
        if configured_refresh_workload not in self.automatic_refresh_workload_map.values():
            configured_refresh_workload = (
                "always_full"
                if bool(config.get("ignore_feed_cache", False))
                else "startup_full"
            )
        for label, value in self.automatic_refresh_workload_map.items():
            if value == configured_refresh_workload:
                self.automatic_refresh_workload_ctrl.SetStringSelection(label)
                break
        refresh_workload_sizer.Add(self.automatic_refresh_workload_ctrl, 0, wx.ALL, 5)
        feeds_sizer.Add(refresh_workload_sizer, 0, wx.EXPAND | wx.ALL, 0)
        feeds_sizer.Add(
            wx.StaticText(
                feeds_panel,
                label=_(
                    "Using the Local RSS feed cache lowers CPU and network use. Manual Refresh All always checks every feed."
                ),
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            10,
        )

        structure_label = wx.StaticText(
            feeds_panel,
            label=_(
                "Article formatting: preserve structure from the original page as spoken text "
                "markers. Applies to newly loaded articles and full text."
            ),
        )
        feeds_sizer.Add(structure_label, 0, wx.LEFT | wx.TOP, 5)
        self.structure_tables_chk = wx.CheckBox(
            feeds_panel,
            label=_("Describe tables (\"Table with 3 rows...\" and one line per row)"),
        )
        self.structure_tables_chk.SetValue(bool(config.get("article_structure_tables", True)))
        feeds_sizer.Add(self.structure_tables_chk, 0, wx.ALL, 5)
        self.structure_headings_chk = wx.CheckBox(
            feeds_panel,
            label=_("Announce headings (\"Heading level 2:\" before each heading)"),
        )
        self.structure_headings_chk.SetValue(bool(config.get("article_structure_headings", False)))
        feeds_sizer.Add(self.structure_headings_chk, 0, wx.ALL, 5)
        self.structure_lists_chk = wx.CheckBox(
            feeds_panel,
            label=_("Mark list items with bullets and numbers"),
        )
        self.structure_lists_chk.SetValue(bool(config.get("article_structure_lists", False)))
        feeds_sizer.Add(self.structure_lists_chk, 0, wx.ALL, 5)
        self.structure_quotes_chk = wx.CheckBox(
            feeds_panel,
            label=_("Mark quotations (\"Quote:\" before and \"End of quote.\" after)"),
        )
        self.structure_quotes_chk.SetValue(bool(config.get("article_structure_quotes", False)))
        feeds_sizer.Add(self.structure_quotes_chk, 0, wx.ALL, 5)
        self.structure_links_chk = wx.CheckBox(
            feeds_panel,
            label=_("Show links as \"text (address)\" and open the link at the cursor with Enter"),
        )
        self.structure_links_chk.SetValue(bool(config.get("article_structure_links", False)))
        feeds_sizer.Add(self.structure_links_chk, 0, wx.ALL, 5)
        self.rich_view_chk = wx.CheckBox(
            feeds_panel,
            label=_(
                "Rich full-text view: show links, embedded videos, and tweets in a web view "
                "(instead of plain text). Falls back to plain text if unavailable."
            ),
        )
        self.rich_view_chk.SetValue(bool(config.get("full_text_rich_view", False)))
        feeds_sizer.Add(self.rich_view_chk, 0, wx.ALL, 5)

        self.show_image_alt_chk = wx.CheckBox(
            general_panel,
            label=_("Include image alt text in articles (announces images, can override per feed)"),
        )
        self.show_image_alt_chk.SetValue(bool(config.get("show_image_alt", False)))
        general_sizer.Add(self.show_image_alt_chk, 0, wx.ALL, 5)

        cookies_label = wx.StaticText(
            youtube_panel,
            label=_(
                "yt-dlp cookies file (cookies.txt) — only needed for age-restricted, private, or "
                "members-only YouTube content. Installed browsers are detected automatically; Firefox "
                "is recommended. Chrome, Edge, and Brave may fail on Windows because their cookies can "
                "be encrypted in a way yt-dlp cannot read, so a cookies.txt is the reliable fallback. "
                "LibreWolf uses Firefox-compatible cookies. Chrome \"Nightly\" means Chrome Canary; "
                "Edge \"Nightly\" means Edge Canary."
            ),
        )
        youtube_sizer.Add(cookies_label, 0, wx.LEFT | wx.TOP, 5)
        cookies_row = wx.BoxSizer(wx.HORIZONTAL)
        self.ytdlp_cookies_ctrl = wx.TextCtrl(youtube_panel, value=str(config.get("ytdlp_cookies_file", "") or ""))
        self.ytdlp_cookies_ctrl.SetName("yt-dlp cookies file path")
        self.ytdlp_cookies_ctrl.SetHint(_("Path to a cookies.txt file"))
        cookies_row.Add(self.ytdlp_cookies_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        cookies_browse = wx.Button(youtube_panel, label=_("Browse..."))
        cookies_browse.SetName("Browse for cookies file")
        cookies_browse.Bind(wx.EVT_BUTTON, self._on_browse_cookies_file)
        cookies_row.Add(cookies_browse, 0, wx.RIGHT, 5)
        cookies_import = wx.Button(youtube_panel, label=_("Import from browser..."))
        cookies_import.Bind(wx.EVT_BUTTON, self._on_import_cookies_from_browser)
        cookies_row.Add(cookies_import, 0)
        youtube_sizer.Add(cookies_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.auto_import_cookies_chk = wx.CheckBox(
            youtube_panel,
            label=_("Automatically import browser cookies.txt exports from Downloads"),
        )
        self.auto_import_cookies_chk.SetValue(bool(config.get("auto_import_browser_cookies", True)))
        youtube_sizer.Add(self.auto_import_cookies_chk, 0, wx.ALL, 5)

        self.youtube_play_via_download_chk = wx.CheckBox(
            youtube_panel,
            label=_("Play YouTube by downloading first (most reliable; slower to start)"),
        )
        self.youtube_play_via_download_chk.SetValue(bool(config.get("youtube_play_via_download", False)))
        youtube_sizer.Add(self.youtube_play_via_download_chk, 0, wx.ALL, 5)

        cache_label = wx.StaticText(
            youtube_panel,
            label=_("YouTube playback cache folder (blank = default, next to your data):"),
        )
        youtube_sizer.Add(cache_label, 0, wx.LEFT | wx.TOP, 5)
        cache_row = wx.BoxSizer(wx.HORIZONTAL)
        self.youtube_play_cache_dir_ctrl = wx.TextCtrl(
            youtube_panel, value=str(config.get("youtube_play_cache_dir", "") or "")
        )
        self.youtube_play_cache_dir_ctrl.SetName("YouTube playback cache folder")
        self.youtube_play_cache_dir_ctrl.SetHint(_("Leave blank for the default location"))
        cache_row.Add(self.youtube_play_cache_dir_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        cache_browse = wx.Button(youtube_panel, label=_("Browse..."))
        cache_browse.SetName("Browse for playback cache folder")
        cache_browse.Bind(wx.EVT_BUTTON, self._on_browse_play_cache_dir)
        cache_row.Add(cache_browse, 0, wx.RIGHT, 5)
        cache_clear = wx.Button(youtube_panel, label=_("Clear cache now"))
        cache_clear.Bind(wx.EVT_BUTTON, self._on_clear_play_cache)
        cache_row.Add(cache_clear, 0)
        youtube_sizer.Add(cache_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        size_row = wx.BoxSizer(wx.HORIZONTAL)
        size_row.Add(
            wx.StaticText(youtube_panel, label=_("Max cache size (MB, 0 = unlimited):")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5,
        )
        self.youtube_play_cache_max_mb_ctrl = wx.SpinCtrl(
            youtube_panel, min=0, max=1000000,
            initial=int(config.get("youtube_play_cache_max_mb", 500) or 0),
        )
        size_row.Add(self.youtube_play_cache_max_mb_ctrl, 0)
        youtube_sizer.Add(size_row, 0, wx.LEFT | wx.BOTTOM, 5)

        self.prompt_missing_deps_chk = wx.CheckBox(
            youtube_panel,
            label=_("Ask to install missing media dependencies on startup"),
        )
        self.prompt_missing_deps_chk.SetValue(
            bool(config.get("prompt_missing_dependencies_on_startup", True))
        )
        youtube_sizer.Add(self.prompt_missing_deps_chk, 0, wx.ALL, 5)

        self.start_on_login_chk = wx.CheckBox(startup_panel, label=windows_integration.startup_setting_label())
        self.start_on_login_chk.SetValue(bool(config.get("start_on_windows_login", False)))
        if not windows_integration.startup_supported():
            self.start_on_login_chk.Disable()
        startup_sizer.Add(self.start_on_login_chk, 0, wx.ALL, 5)

        self.remember_last_feed_chk = wx.CheckBox(general_panel, label=_("Remember last selected feed/folder on startup"))
        self.remember_last_feed_chk.SetValue(bool(config.get("remember_last_feed", False)))
        general_sizer.Add(self.remember_last_feed_chk, 0, wx.ALL, 5)

        # Interface language (issue #44). "Auto" follows the OS locale; the
        # list only offers languages that ship a compiled translation catalog.
        # gettext falls back to the built-in English strings otherwise.
        language_sizer = wx.BoxSizer(wx.HORIZONTAL)
        language_sizer.Add(
            wx.StaticText(general_panel, label=_("Interface language (requires restart):")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )

        try:
            from core.i18n import available_languages
            _lang_codes = list(available_languages())
        except Exception:
            _lang_codes = []

        # Ensure 'en' is present, since gettext always has English as fallback
        if "en" not in _lang_codes:
            _lang_codes.append("en")

        # Create dictionary: code -> name (based on self._TRANSLATION_LANGUAGE_PRESETS)
        code_to_name_map = {code: name for name, code in self._TRANSLATION_LANGUAGE_PRESETS}

        # Two parallel lists: one for UI (human-readable strings), the other for internal logic (codes)
        ui_choices = []
        logic_codes = []

        # Always the first option: "auto"
        ui_choices.append(_("Automatic (system language)"))
        logic_codes.append("auto")

        # Collect the remaining languages
        sortable_items = []
        for code in _lang_codes:
            if code == "auto":
                continue

            # Trying to find a human-readable name. If not, leave the code.
            # Locale directories use underscores (pt_BR, zh_CN) while the
            # presets use BCP-47 hyphens (pt-BR, zh-CN); regional locales with
            # no preset of their own (nl_BE) fall back to the base language.
            name = (
                code_to_name_map.get(code)
                or code_to_name_map.get(code.replace("_", "-"))
                or code_to_name_map.get(code.split("_")[0].split("-")[0])
            )
            display_text = f"{name} ({code})" if name else code

            sortable_items.append((display_text, code))

        # Sort by displayed text (already translated)
        sortable_items.sort(key=lambda x: x[0])

        # Fill parallel lists with sorted data
        for text, code in sortable_items:
            ui_choices.append(text)
            logic_codes.append(code)

        # Save the list of codes so that you can later get the correct code by index.
        self.language_choices = logic_codes

        self.language_choice = wx.Choice(
            general_panel,
            choices=ui_choices,
        )
        self.language_choice.SetName("Interface language")

        # Restore saved value
        current_language = str(config.get("language", "auto") or "auto")
        try:
            idx = self.language_choices.index(current_language)
            self.language_choice.SetSelection(idx)
        except ValueError:
            # If the saved language is deleted from the system, set it to "auto"
            self.language_choice.SetSelection(0)

        language_sizer.Add(self.language_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        general_sizer.Add(language_sizer, 0, wx.ALL, 0)

        # Default expansion state of the feed category tree on launch (issue #33).
        tree_state_sizer = wx.BoxSizer(wx.HORIZONTAL)
        tree_state_sizer.Add(
            wx.StaticText(general_panel, label=_("Feed category tree on startup:")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )
        self.tree_expand_map = {
            _("All items expanded"): True,
            _("All items collapsed"): False,
        }
        self.tree_expand_choices = list(self.tree_expand_map.keys())
        self.tree_expand_ctrl = wx.Choice(general_panel, choices=self.tree_expand_choices)
        self.tree_expand_ctrl.SetName("Feed category tree default state on startup")
        current_tree_expanded = bool(config.get("category_tree_default_expanded", True))
        self.tree_expand_ctrl.SetStringSelection(
            _("All items expanded") if current_tree_expanded else _("All items collapsed")
        )
        tree_state_sizer.Add(self.tree_expand_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(tree_state_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Article opening method (issue #31): default browser vs a custom command.
        article_open_sizer = wx.BoxSizer(wx.HORIZONTAL)
        article_open_sizer.Add(
            wx.StaticText(general_panel, label=_("Article opening method:")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )
        self.article_open_method_map = {
            _("Default browser"): "default",
            _("Custom command"): "custom",
        }
        self.article_open_method_choices = list(self.article_open_method_map.keys())
        self.article_open_method_ctrl = wx.Choice(general_panel, choices=self.article_open_method_choices)
        self.article_open_method_ctrl.SetName("Article opening method")
        current_open_method = str(config.get("article_open_method", "default") or "default").lower()
        self.article_open_method_ctrl.SetStringSelection(
            _("Custom command") if current_open_method == "custom" else _("Default browser")
        )
        article_open_sizer.Add(self.article_open_method_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(article_open_sizer, 0, wx.EXPAND | wx.ALL, 5)

        cmd_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cmd_sizer.Add(
            wx.StaticText(general_panel, label=_("Custom command:")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )
        self.article_open_command_ctrl = wx.TextCtrl(
            general_panel, value=str(config.get("article_open_command", "") or "")
        )
        self.article_open_command_ctrl.SetName("Custom article open command")
        cmd_sizer.Add(self.article_open_command_ctrl, 1, wx.ALL, 5)
        self.article_open_test_btn = wx.Button(general_panel, label=_("Test"))
        self.article_open_test_btn.SetName("Test custom article open command")
        cmd_sizer.Add(self.article_open_test_btn, 0, wx.ALL, 5)
        general_sizer.Add(cmd_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.article_open_help_lbl = wx.StaticText(
            general_panel,
            label=_("Use %1 for the article URL. Example: chrome --incognito %1"),
        )
        general_sizer.Add(self.article_open_help_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.article_open_method_ctrl.Bind(wx.EVT_CHOICE, self._on_article_open_method_changed)
        self.article_open_test_btn.Bind(wx.EVT_BUTTON, self.on_test_article_command)
        self._sync_article_open_controls()

        general_panel.SetSizer(general_sizer)
        notebook.AddPage(general_panel, _("General"))
        feeds_panel.SetSizer(feeds_sizer)
        notebook.AddPage(feeds_panel, _("Feeds && Articles"))
        downloads_panel.SetSizer(downloads_sizer)
        notebook.AddPage(downloads_panel, _("Downloads"))
        startup_panel.SetSizer(startup_sizer)
        notebook.AddPage(startup_panel, _("Startup && Tray"))
        youtube_panel.SetSizer(youtube_sizer)
        notebook.AddPage(youtube_panel, _("YouTube"))

        # Media Player Tab
        media_panel = wx.Panel(notebook)
        media_sizer = wx.BoxSizer(wx.VERTICAL)

        # Preferred soundcard (enumerated in background to avoid blocking dialog open)
        soundcard_sizer = wx.BoxSizer(wx.HORIZONTAL)
        soundcard_sizer.Add(wx.StaticText(media_panel, label=_("Preferred Soundcard:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self._current_soundcard = str(config.get("preferred_soundcard", "") or "")
        self._soundcard_choices = [(_("System Default"), "")]
        self._soundcard_labels = [_("Loading soundcards...")]
        self.soundcard_ctrl = wx.Choice(media_panel, choices=self._soundcard_labels)
        self.soundcard_ctrl.SetSelection(0)
        soundcard_sizer.Add(self.soundcard_ctrl, 1, wx.ALL, 5)
        media_sizer.Add(soundcard_sizer, 0, wx.EXPAND | wx.ALL, 5)
        threading.Thread(target=self._load_soundcards_async, daemon=True).start()

        self.skip_silence_chk = wx.CheckBox(media_panel, label=_("Skip Silence (Experimental)"))
        self.skip_silence_chk.SetValue(config.get("skip_silence", False))
        media_sizer.Add(self.skip_silence_chk, 0, wx.ALL, 5)

        # Playback speed
        speed_sizer = wx.BoxSizer(wx.HORIZONTAL)
        speed_sizer.Add(wx.StaticText(media_panel, label=_("Default Playback Speed:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        # Build speed choices using utils
        speeds = utils.build_playback_speeds()
        self.speed_choices = [f"{s:.2f}x" for s in speeds]
        current_speed = float(config.get("playback_speed", 1.0))

        self.speed_ctrl = wx.ComboBox(media_panel, choices=self.speed_choices, style=wx.CB_READONLY)

        # Find nearest selection
        sel_idx = 0
        min_diff = 999.0
        for i, s in enumerate(speeds):
            diff = abs(s - current_speed)
            if diff < min_diff:
                min_diff = diff
                sel_idx = i
        self.speed_ctrl.SetSelection(sel_idx)

        speed_sizer.Add(self.speed_ctrl, 0, wx.ALL, 5)
        media_sizer.Add(speed_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Player window behavior
        self.show_player_on_play_chk = wx.CheckBox(media_panel, label=_("Show player window when starting playback"))
        self.show_player_on_play_chk.SetValue(bool(config.get("show_player_on_play", True)))
        media_sizer.Add(self.show_player_on_play_chk, 0, wx.ALL, 5)

        # VLC network caching (helps on high latency streams)
        cache_net_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cache_net_sizer.Add(wx.StaticText(media_panel, label=_("Network Cache (ms):")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.vlc_cache_ctrl = wx.SpinCtrl(media_panel, min=500, max=60000, initial=int(config.get("vlc_network_caching_ms", 5000)))
        cache_net_sizer.Add(self.vlc_cache_ctrl, 0, wx.ALL, 5)
        media_sizer.Add(cache_net_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.range_cache_debug_chk = wx.CheckBox(media_panel, label=_("Verbose range-cache proxy debug logs"))
        self.range_cache_debug_chk.SetValue(bool(config.get("range_cache_debug", False)))
        media_sizer.Add(self.range_cache_debug_chk, 0, wx.ALL, 5)

        # Media tool executables: detected paths plus optional manual overrides.
        # Leaving a field blank auto-detects (PATH, Scoop/Choco/WinGet, portable
        # layouts, etc.). Detection runs in the background to keep the dialog snappy.
        tools_box = wx.StaticBoxSizer(
            wx.VERTICAL, media_panel, _("Media tools (ffmpeg, ffprobe, yt-dlp)")
        )
        tools_box.Add(
            wx.StaticText(
                media_panel,
                label=_("Leave a path blank to auto-detect. A set path overrides detection."),
            ),
            0, wx.ALL, 4,
        )
        self._media_tool_path_ctrls = {}
        self._media_tool_detected_lbls = {}
        _media_tool_specs = [
            ("ffmpeg", "FFmpeg", "custom_ffmpeg_path"),
            ("ffprobe", "FFprobe", "custom_ffprobe_path"),
            ("yt-dlp", "yt-dlp", "custom_ytdlp_path"),
        ]
        for tool_key, tool_label, cfg_key in _media_tool_specs:
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(
                wx.StaticText(media_panel, label=_("{tool} path:").format(tool=tool_label)),
                0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4,
            )
            ctrl = wx.TextCtrl(media_panel, value=str(config.get(cfg_key, "") or ""))
            ctrl.SetName(f"{tool_label} executable path override")
            row.Add(ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            browse = wx.Button(media_panel, label=_("Browse..."))
            browse.Bind(
                wx.EVT_BUTTON,
                lambda evt, c=ctrl, lbl=tool_label: self._on_browse_media_tool(c, lbl),
            )
            row.Add(browse, 0)
            tools_box.Add(row, 0, wx.EXPAND | wx.ALL, 2)
            detected = wx.StaticText(media_panel, label=f"Detected {tool_label}: checking…")
            detected.SetName(f"Detected {tool_label}")
            tools_box.Add(detected, 0, wx.LEFT | wx.BOTTOM, 12)
            self._media_tool_path_ctrls[cfg_key] = ctrl
            self._media_tool_detected_lbls[tool_key] = detected
        media_sizer.Add(tools_box, 0, wx.EXPAND | wx.ALL, 5)
        threading.Thread(target=self._detect_media_tools_async, daemon=True).start()

        media_panel.SetSizer(media_sizer)
        notebook.AddPage(media_panel, _("Media Player"))
        
        # Provider Tab
        provider_panel = wx.Panel(notebook)
        provider_sizer = wx.BoxSizer(wx.VERTICAL)

        provider_sizer.Add(wx.StaticText(provider_panel, label=_("Active Provider:")), 0, wx.ALL, 5)

        # Build provider list from config (keeps future providers visible).
        cfg_providers = list((config.get("providers") or {}).keys()) if isinstance(config, dict) else []
        if not cfg_providers:
            cfg_providers = ["local", "miniflux", "bazqux", "theoldreader", "inoreader"]
        preferred_order = ["local", "miniflux", "bazqux", "theoldreader", "inoreader"]
        providers_sorted = [p for p in preferred_order if p in cfg_providers] + [p for p in cfg_providers if p not in preferred_order]

        self.provider_choice = wx.Choice(provider_panel, choices=providers_sorted)
        self.provider_choice.SetStringSelection(config.get("active_provider", "local"))
        provider_sizer.Add(self.provider_choice, 0, wx.EXPAND | wx.ALL, 5)

        # Provider-specific settings panels
        self._provider_panels = {}  # name -> (panel, controls_dict)

        def _add_simple_info_panel(name: str, info_text: str):
            pnl = wx.Panel(provider_panel)
            s = wx.BoxSizer(wx.VERTICAL)
            # Read-only text control instead of a StaticText: it participates
            # in the tab order, so keyboard/screen-reader users reach the
            # explanation without object navigation.
            info = wx.TextCtrl(
                pnl,
                value=info_text,
                style=wx.TE_MULTILINE | wx.TE_READONLY,
                size=(-1, 60),
            )
            info.SetName(_("Provider information"))
            s.Add(info, 0, wx.EXPAND | wx.ALL, 5)
            pnl.SetSizer(s)
            provider_sizer.Add(pnl, 0, wx.EXPAND | wx.ALL, 5)
            self._provider_panels[name] = (pnl, {})
            pnl.Hide()

        def _add_fields_panel(name: str, fields):
            # fields: [(label, key, style)]
            pnl = wx.Panel(provider_panel)
            fg = wx.FlexGridSizer(cols=2, hgap=8, vgap=8)
            fg.AddGrowableCol(1, 1)
            ctrls = {}
            p_cfg = (config.get("providers") or {}).get(name, {}) if isinstance(config, dict) else {}
            for label, key, style in fields:
                fg.Add(wx.StaticText(pnl, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
                tc = wx.TextCtrl(pnl, style=style)
                tc.SetName(label.rstrip(":").strip())
                tc.SetValue(str(p_cfg.get(key, "") or ""))
                fg.Add(tc, 1, wx.EXPAND | wx.ALL, 2)
                ctrls[key] = tc
            pnl.SetSizer(fg)
            provider_sizer.Add(pnl, 0, wx.EXPAND | wx.ALL, 5)
            self._provider_panels[name] = (pnl, ctrls)
            pnl.Hide()

        def _add_inoreader_panel(name: str):
            pnl = wx.Panel(provider_panel)
            outer = wx.BoxSizer(wx.VERTICAL)
            fg = wx.FlexGridSizer(cols=2, hgap=8, vgap=8)
            fg.AddGrowableCol(1, 1)
            ctrls = {}
            p_cfg = (config.get("providers") or {}).get(name, {}) if isinstance(config, dict) else {}

            fg.Add(wx.StaticText(pnl, label=_("Inoreader App ID:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
            app_id_ctrl = wx.TextCtrl(pnl)
            app_id_ctrl.SetName("Inoreader App ID")
            app_id_ctrl.SetValue(str(p_cfg.get("app_id", "") or ""))
            fg.Add(app_id_ctrl, 1, wx.EXPAND | wx.ALL, 2)
            ctrls["app_id"] = app_id_ctrl

            fg.Add(wx.StaticText(pnl, label=_("Inoreader App Key:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
            app_key_ctrl = wx.TextCtrl(pnl, style=wx.TE_PASSWORD)
            app_key_ctrl.SetName("Inoreader App Key")
            app_key_ctrl.SetValue(str(p_cfg.get("app_key", "") or ""))
            fg.Add(app_key_ctrl, 1, wx.EXPAND | wx.ALL, 2)
            ctrls["app_key"] = app_key_ctrl

            default_redirect_uri = inoreader_oauth.get_redirect_uri(scheme="https")
            redirect_uri_ctrl = wx.TextCtrl(pnl)
            redirect_uri_ctrl.SetName("Redirect URI")
            redirect_uri_ctrl.SetValue(str(p_cfg.get("redirect_uri", "") or "").strip() or default_redirect_uri)
            fg.Add(wx.StaticText(pnl, label=_("Redirect URI:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
            fg.Add(redirect_uri_ctrl, 1, wx.EXPAND | wx.ALL, 2)
            ctrls["redirect_uri"] = redirect_uri_ctrl

            outer.Add(fg, 0, wx.EXPAND | wx.ALL, 2)

            help_lbl = wx.StaticText(
                pnl,
                label=_(
                    "Note: If your Redirect URI uses HTTPS (common/required), your browser may fail to load\n"
                    "localhost after authorization. Copy the full redirected URL from the address bar and paste it\n"
                    "when prompted."
                ),
            )
            outer.Add(help_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)

            status_lbl = wx.StaticText(pnl, label="")
            outer.Add(status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)

            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            auth_btn = wx.Button(pnl, label=_("Authorize Inoreader"))
            clear_btn = wx.Button(pnl, label=_("Clear Authorization"))
            btn_sizer.Add(auth_btn, 0, wx.ALL, 2)
            btn_sizer.Add(clear_btn, 0, wx.ALL, 2)
            outer.Add(btn_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)

            pnl.SetSizer(outer)
            provider_sizer.Add(pnl, 0, wx.EXPAND | wx.ALL, 5)
            self._provider_panels[name] = (pnl, ctrls)
            pnl.Hide()

            self._inoreader_app_id_ctrl = app_id_ctrl
            self._inoreader_app_key_ctrl = app_key_ctrl
            self._inoreader_redirect_uri_ctrl = redirect_uri_ctrl
            self._inoreader_status_lbl = status_lbl
            self._inoreader_authorize_btn = auth_btn
            self._inoreader_clear_btn = clear_btn
            self._inoreader_tokens = None
            self._inoreader_auth_original = {
                "app_id": str(p_cfg.get("app_id", "") or ""),
                "app_key": str(p_cfg.get("app_key", "") or ""),
            }

            has_token = bool((p_cfg.get("token") or "") or (p_cfg.get("refresh_token") or ""))
            self._set_inoreader_status(
                "Authorized" if has_token else "Not authorized",
                ok=has_token,
            )

            auth_btn.Bind(wx.EVT_BUTTON, self._start_inoreader_authorize)
            clear_btn.Bind(wx.EVT_BUTTON, self._clear_inoreader_authorization)

        _add_simple_info_panel("local", _("Local provider uses the feeds you add inside the app (Add Feed / Import OPML)."))
        _add_fields_panel("miniflux", [
            ("Miniflux URL:", "url", 0),
            ("Miniflux API Key:", "api_key", 0),
        ])
        _add_fields_panel("theoldreader", [
            ("The Old Reader Email:", "email", 0),
            ("The Old Reader Password:", "password", wx.TE_PASSWORD),
        ])
        _add_inoreader_panel("inoreader")
        _add_fields_panel("bazqux", [
            ("BazQux Email:", "email", 0),
            ("BazQux Password:", "password", wx.TE_PASSWORD),
        ])

        self.provider_choice.Bind(wx.EVT_CHOICE, self.on_provider_choice)
        self._update_provider_panels()

        provider_panel.SetSizer(provider_sizer)
        notebook.AddPage(provider_panel, _("Provider"))
        
        # Sounds Tab
        sounds_panel = wx.Panel(notebook)
        sounds_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.sounds_enabled_chk = wx.CheckBox(sounds_panel, label=_("Enable Sound Notifications"))
        self.sounds_enabled_chk.SetValue(config.get("sounds_enabled", True))
        sounds_sizer.Add(self.sounds_enabled_chk, 0, wx.ALL, 5)
        
        def _add_sound_field(label, key):
            field_name = label.rstrip(":").strip()
            s = wx.BoxSizer(wx.HORIZONTAL)
            s.Add(wx.StaticText(sounds_panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
            val = config.get(key, "")
            ctrl = wx.TextCtrl(sounds_panel, value=str(val))
            ctrl.SetName(field_name)
            s.Add(ctrl, 1, wx.ALL, 5)
            browse_btn = wx.Button(sounds_panel, label=_("Browse..."))
            browse_btn.SetName(f"Browse for {field_name}")

            def _on_browse(evt):
                dlg = wx.FileDialog(self, f"Choose {label}", defaultFile=ctrl.GetValue(), wildcard=f'{_("WAV files")} (*.wav)|*.wav|{_("All files")} (*.*)|*.*', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
                if dlg.ShowModal() == wx.ID_OK:
                    ctrl.SetValue(dlg.GetPath())
                dlg.Destroy()
            
            browse_btn.Bind(wx.EVT_BUTTON, _on_browse)
            s.Add(browse_btn, 0, wx.ALL, 5)
            sounds_sizer.Add(s, 0, wx.EXPAND | wx.ALL, 5)
            return ctrl
            
        self.sound_complete_ctrl = _add_sound_field(_("Refresh Complete Sound:"), "sound_refresh_complete")
        self.sound_error_ctrl = _add_sound_field(_("Refresh Error Sound:"), "sound_refresh_error")
        
        sounds_panel.SetSizer(sounds_sizer)
        notebook.AddPage(sounds_panel, _("Sounds"))

        # Notifications Tab
        notifications_panel = wx.Panel(notebook)
        notifications_sizer = wx.BoxSizer(wx.VERTICAL)

        notice_txt = (
            "Windows toast notifications for new articles.\n"
            "Disabled by default."
        )
        notifications_sizer.Add(wx.StaticText(notifications_panel, label=notice_txt), 0, wx.ALL, 8)

        self.windows_notifications_chk = wx.CheckBox(
            notifications_panel,
            label=_("Enable notifications for new articles"),
        )
        self.windows_notifications_chk.SetValue(bool(config.get("windows_notifications_enabled", False)))
        if not utils.platform_supports_notifications():
            self.windows_notifications_chk.Disable()
        notifications_sizer.Add(self.windows_notifications_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.windows_notifications_feed_chk = wx.CheckBox(
            notifications_panel,
            label=_("Include feed name in notification text"),
        )
        self.windows_notifications_feed_chk.SetValue(
            bool(config.get("windows_notifications_include_feed_name", True))
        )
        notifications_sizer.Add(self.windows_notifications_feed_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        cap_row = wx.BoxSizer(wx.HORIZONTAL)
        cap_row.Add(
            wx.StaticText(notifications_panel, label=_("Max notifications per refresh (0 = no limit):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.windows_notifications_max_ctrl = wx.SpinCtrl(
            notifications_panel,
            min=0,
            max=200,
            initial=int(config.get("windows_notifications_max_per_refresh", 0)),
        )
        cap_row.Add(self.windows_notifications_max_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        notifications_sizer.Add(cap_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.windows_notifications_summary_chk = wx.CheckBox(
            notifications_panel,
            label=_("Show a summary notification when notification cap is reached"),
        )
        self.windows_notifications_summary_chk.SetValue(
            bool(config.get("windows_notifications_show_summary_when_capped", True))
        )
        notifications_sizer.Add(self.windows_notifications_summary_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.test_notification_btn = wx.Button(notifications_panel, label=_("Test Notification"))
        self.test_notification_btn.Bind(wx.EVT_BUTTON, self.on_test_notification)
        notifications_sizer.Add(self.test_notification_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.exclude_feeds_btn = wx.Button(notifications_panel, label=_("Exclude Feeds..."))
        self.exclude_feeds_btn.Bind(wx.EVT_BUTTON, self.on_exclude_notification_feeds)
        notifications_sizer.Add(self.exclude_feeds_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.exclude_feeds_lbl = wx.StaticText(notifications_panel, label="")
        notifications_sizer.Add(self.exclude_feeds_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._update_excluded_feeds_label()

        self.windows_notifications_chk.Bind(wx.EVT_CHECKBOX, self._on_toggle_windows_notifications)
        self._update_notification_controls()

        notifications_panel.SetSizer(notifications_sizer)
        notebook.AddPage(notifications_panel, _("Notifications"))

        # Announcements Tab (issue #67): per-event screen-reader announcement mode.
        announcements_panel = wx.ScrolledWindow(notebook)
        announcements_panel.SetScrollRate(0, 12)
        announcements_sizer = wx.BoxSizer(wx.VERTICAL)

        announce_note = (
            "Screen-reader announcements for key keyboard actions.\n"
            "Each event can announce via speech, Braille, both, or neither.\n"
            "Braille output is most reliable on Windows with NVDA or JAWS."
        )
        announcements_sizer.Add(
            wx.StaticText(announcements_panel, label=announce_note), 0, wx.ALL, 8
        )

        mode_labels = [_(label) for _mode, label in announcements_mod.mode_choices()]
        mode_values = [mode for mode, _label in announcements_mod.mode_choices()]
        current_modes = announcements_mod.normalize_modes(
            config.get("announcements", {})
        )
        self._announcement_mode_values = mode_values
        self._announcement_choice_ctrls = {}

        announce_grid = wx.FlexGridSizer(0, 2, 6, 10)
        announce_grid.AddGrowableCol(0, 1)
        for event in announcements_mod.iter_events():
            label = wx.StaticText(announcements_panel, label=_(event.label))
            label.SetToolTip(_(event.help))
            choice = wx.Choice(announcements_panel, choices=mode_labels)
            choice.SetName(_(event.label))
            choice.SetToolTip(_(event.help))
            try:
                sel = mode_values.index(current_modes.get(event.id, event.default))
            except ValueError:
                sel = mode_values.index(announcements_mod.DEFAULT_MODE)
            choice.SetSelection(sel)
            self._announcement_choice_ctrls[event.id] = choice
            announce_grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            announce_grid.Add(choice, 0, wx.EXPAND)
        announcements_sizer.Add(announce_grid, 0, wx.EXPAND | wx.ALL, 8)

        # Test button (issue #71), mirroring "Test Notification" on the
        # Notifications tab. Speaks and brailles regardless of the per-event
        # modes above -- see Announcer.announce_test.
        self.test_announcement_btn = wx.Button(announcements_panel, label=_("Test Announcement"))
        self.test_announcement_btn.SetName(_("Test Announcement"))
        self.test_announcement_btn.SetToolTip(
            _("Send a test announcement to your screen reader via speech and Braille.")
        )
        self.test_announcement_btn.Bind(wx.EVT_BUTTON, self.on_test_announcement)
        announcements_sizer.Add(self.test_announcement_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        announcements_panel.SetSizer(announcements_sizer)
        notebook.AddPage(announcements_panel, _("Announcements"))

        # Translate Tab (automatic article translation via Grok/Groq/OpenAI/OpenRouter/Gemini/Qwen)
        translate_panel = wx.Panel(notebook)
        translate_sizer = wx.BoxSizer(wx.VERTICAL)

        translate_note = (
            "Configure automatic article translation.\n"
            "Your API key is stored locally in config.json."
        )
        translate_sizer.Add(wx.StaticText(translate_panel, label=translate_note), 0, wx.ALL, 8)

        self.translation_enabled_chk = wx.CheckBox(
            translate_panel,
            label=_("Enable automatic translation for article content"),
        )
        self.translation_enabled_chk.SetValue(bool(config.get("translation_enabled", False)))
        translate_sizer.Add(self.translation_enabled_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Display name → internal config key mapping for translation providers.
        self._translation_provider_display_to_key = {
            "Grok (xAI)": "grok",
            "Groq (LLaMA, Mistral)": "groq",
            "OpenAI (GPT)": "openai",
            "OpenRouter": "openrouter",
            "Gemini (Google)": "gemini",
            "Qwen (Alibaba)": "qwen",
        }
        self._translation_provider_key_to_display = {
            v: k for k, v in self._translation_provider_display_to_key.items()
        }
        _provider_display_names = list(self._translation_provider_display_to_key.keys())

        provider_row = wx.BoxSizer(wx.HORIZONTAL)
        provider_row.Add(wx.StaticText(translate_panel, label=_("Provider:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.translation_provider_ctrl = wx.Choice(translate_panel, choices=_provider_display_names)
        _saved_provider = str(config.get("translation_provider", "grok") or "grok").strip().lower()
        _saved_display = self._translation_provider_key_to_display.get(_saved_provider, _provider_display_names[0])
        if not self.translation_provider_ctrl.SetStringSelection(_saved_display):
            self.translation_provider_ctrl.SetSelection(0)
        provider_row.Add(self.translation_provider_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(provider_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._translation_language_label_to_code = {
            str(label): str(code)
            for label, code in self._TRANSLATION_LANGUAGE_PRESETS
        }
        self._translation_language_code_to_label = {
            str(code).lower(): str(label)
            for label, code in self._TRANSLATION_LANGUAGE_PRESETS
        }

        target_row = wx.BoxSizer(wx.HORIZONTAL)
        target_row.Add(
            wx.StaticText(translate_panel, label=_("Target language:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        choices = [f"{label} ({_code})" for label, _code in self._TRANSLATION_LANGUAGE_PRESETS]
        choices.sort()
        self.translation_target_language_ctrl = wx.ComboBox(
            translate_panel,
            choices=choices,
            style=wx.CB_DROPDOWN,
        )
        self.translation_target_language_ctrl.SetName("Target language")
        self.translation_target_language_ctrl.SetValue(
            self._translation_language_display_value(
                str(config.get("translation_target_language", "en") or "en")
            )
        )
        target_row.Add(self.translation_target_language_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(target_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        translate_sizer.Add(
            wx.StaticText(
                translate_panel,
                label=_("Choose a language or type a code (e.g. en, es, fr, pt-BR)."),
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        model_row = wx.BoxSizer(wx.HORIZONTAL)
        model_row.Add(
            wx.StaticText(translate_panel, label=_("Grok (xAI) model (optional):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        model_choices = [
            str(m)
            for m in getattr(translation_mod, "_DEFAULT_MODEL_CANDIDATES", ())
            if str(m or "").strip()
        ]
        self.translation_grok_model_ctrl = wx.ComboBox(
            translate_panel,
            choices=list(dict.fromkeys(model_choices)),
            style=wx.CB_DROPDOWN,
        )
        self.translation_grok_model_ctrl.SetName("Grok (xAI) model")
        self.translation_grok_model_ctrl.SetValue(str(config.get("translation_grok_model", "") or ""))
        model_row.Add(self.translation_grok_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.translation_grok_model_hint_lbl = wx.StaticText(
            translate_panel,
            label=_("Grok is by xAI. Get a key at console.x.ai. For Groq (LLaMA/Mistral), select 'Groq (LLaMA, Mistral)' instead."),
        )
        translate_sizer.Add(
            self.translation_grok_model_hint_lbl,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        api_key_row.Add(wx.StaticText(translate_panel, label=_("Grok (xAI) API key (starts with xai-):")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.translation_grok_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_grok_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        self.translation_grok_api_key_ctrl.SetName("Grok (xAI) API key")
        api_key_row.Add(self.translation_grok_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        groq_model_row = wx.BoxSizer(wx.HORIZONTAL)
        groq_model_row.Add(
            wx.StaticText(translate_panel, label=_("Groq model (optional) - hosts LLaMA and Mistral:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        groq_model_choices = [
            str(m)
            for m in getattr(translation_mod, "_DEFAULT_GROQ_MODEL_CANDIDATES", ())
            if str(m or "").strip()
        ]
        self.translation_groq_model_ctrl = wx.ComboBox(
            translate_panel,
            choices=list(dict.fromkeys(groq_model_choices)),
            style=wx.CB_DROPDOWN,
        )
        self.translation_groq_model_ctrl.SetName("Groq model")
        self.translation_groq_model_ctrl.SetValue(str(config.get("translation_groq_model", "") or ""))
        groq_model_row.Add(self.translation_groq_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(groq_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        groq_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        groq_api_key_row.Add(
            wx.StaticText(translate_panel, label=_("Groq API key (starts with gsk_):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_groq_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_groq_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        self.translation_groq_api_key_ctrl.SetName("Groq API key")
        groq_api_key_row.Add(self.translation_groq_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(groq_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.translation_groq_hint_lbl = wx.StaticText(
            translate_panel,
            label=_("Groq is NOT Grok. Get a free Groq key at console.groq.com/keys (runs LLaMA and Mistral models)."),
        )
        translate_sizer.Add(
            self.translation_groq_hint_lbl,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        openai_model_row = wx.BoxSizer(wx.HORIZONTAL)
        openai_model_row.Add(
            wx.StaticText(translate_panel, label=_("OpenAI model (optional):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        openai_model_choices = [
            str(m)
            for m in getattr(translation_mod, "_DEFAULT_OPENAI_MODEL_CANDIDATES", ())
            if str(m or "").strip()
        ]
        self.translation_openai_model_ctrl = wx.ComboBox(
            translate_panel,
            choices=list(dict.fromkeys(openai_model_choices)),
            style=wx.CB_DROPDOWN,
        )
        self.translation_openai_model_ctrl.SetName("OpenAI model")
        self.translation_openai_model_ctrl.SetValue(str(config.get("translation_openai_model", "") or ""))
        openai_model_row.Add(self.translation_openai_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openai_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openai_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        openai_api_key_row.Add(
            wx.StaticText(translate_panel, label=_("OpenAI API key:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_openai_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_openai_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        self.translation_openai_api_key_ctrl.SetName("OpenAI API key")
        openai_api_key_row.Add(self.translation_openai_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openai_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openrouter_model_row = wx.BoxSizer(wx.HORIZONTAL)
        openrouter_model_row.Add(
            wx.StaticText(translate_panel, label=_("OpenRouter model (optional):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        openrouter_model_choices = [
            str(m)
            for m in getattr(translation_mod, "_DEFAULT_OPENROUTER_MODEL_CANDIDATES", ())
            if str(m or "").strip()
        ]
        self.translation_openrouter_model_ctrl = wx.ComboBox(
            translate_panel,
            choices=list(dict.fromkeys(openrouter_model_choices)),
            style=wx.CB_DROPDOWN,
        )
        self.translation_openrouter_model_ctrl.SetName("OpenRouter model")
        self.translation_openrouter_model_ctrl.SetValue(str(config.get("translation_openrouter_model", "") or ""))
        openrouter_model_row.Add(self.translation_openrouter_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openrouter_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openrouter_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        openrouter_api_key_row.Add(
            wx.StaticText(translate_panel, label=_("OpenRouter API key:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_openrouter_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_openrouter_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        self.translation_openrouter_api_key_ctrl.SetName("OpenRouter API key")
        openrouter_api_key_row.Add(self.translation_openrouter_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openrouter_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openrouter_tools_row = wx.BoxSizer(wx.HORIZONTAL)
        self.translation_openrouter_load_models_btn = wx.Button(translate_panel, label=_("Load OpenRouter Models"))
        openrouter_tools_row.Add(self.translation_openrouter_load_models_btn, 0, wx.RIGHT, 8)
        self.translation_openrouter_models_status_lbl = wx.StaticText(
            translate_panel,
            label=_("Loads all available model IDs from OpenRouter."),
        )
        openrouter_tools_row.Add(self.translation_openrouter_models_status_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openrouter_tools_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        gemini_model_row = wx.BoxSizer(wx.HORIZONTAL)
        gemini_model_row.Add(
            wx.StaticText(translate_panel, label=_("Gemini model (optional):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        gemini_model_choices = [
            str(m)
            for m in getattr(translation_mod, "_DEFAULT_GEMINI_MODEL_CANDIDATES", ())
            if str(m or "").strip()
        ]
        self.translation_gemini_model_ctrl = wx.ComboBox(
            translate_panel,
            choices=list(dict.fromkeys(gemini_model_choices)),
            style=wx.CB_DROPDOWN,
        )
        self.translation_gemini_model_ctrl.SetName("Gemini model")
        self.translation_gemini_model_ctrl.SetValue(str(config.get("translation_gemini_model", "") or ""))
        gemini_model_row.Add(self.translation_gemini_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(gemini_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        gemini_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        gemini_api_key_row.Add(
            wx.StaticText(translate_panel, label=_("Gemini API key:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_gemini_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_gemini_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        self.translation_gemini_api_key_ctrl.SetName("Gemini API key")
        gemini_api_key_row.Add(self.translation_gemini_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(gemini_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        qwen_model_row = wx.BoxSizer(wx.HORIZONTAL)
        qwen_model_row.Add(
            wx.StaticText(translate_panel, label=_("Qwen model (optional):")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        qwen_model_choices = [
            str(m)
            for m in getattr(translation_mod, "_DEFAULT_QWEN_MODEL_CANDIDATES", ())
            if str(m or "").strip()
        ]
        self.translation_qwen_model_ctrl = wx.ComboBox(
            translate_panel,
            choices=list(dict.fromkeys(qwen_model_choices)),
            style=wx.CB_DROPDOWN,
        )
        self.translation_qwen_model_ctrl.SetName("Qwen model")
        self.translation_qwen_model_ctrl.SetValue(str(config.get("translation_qwen_model", "") or ""))
        qwen_model_row.Add(self.translation_qwen_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(qwen_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        qwen_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        qwen_api_key_row.Add(
            wx.StaticText(translate_panel, label=_("Qwen API key:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_qwen_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_qwen_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        self.translation_qwen_api_key_ctrl.SetName("Qwen API key")
        qwen_api_key_row.Add(self.translation_qwen_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(qwen_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._translation_layout_panel = translate_panel
        self._translation_layout_sizer = translate_sizer
        self._translation_provider_rows = {
            "grok": [model_row, self.translation_grok_model_hint_lbl, api_key_row],
            "groq": [groq_model_row, groq_api_key_row, self.translation_groq_hint_lbl],
            "openai": [openai_model_row, openai_api_key_row],
            "openrouter": [openrouter_model_row, openrouter_api_key_row, openrouter_tools_row],
            "gemini": [gemini_model_row, gemini_api_key_row],
            "qwen": [qwen_model_row, qwen_api_key_row],
        }
        self.translation_provider_ctrl.Bind(wx.EVT_CHOICE, self.on_translation_provider_choice)
        self.translation_openrouter_load_models_btn.Bind(wx.EVT_BUTTON, self.on_load_openrouter_models)
        self._openrouter_models_loading = False
        self._update_translation_provider_controls()

        translate_panel.SetSizer(translate_sizer)
        notebook.AddPage(translate_panel, _("Translate"))

        # Global article-list column layout (article list columns); individual feeds can
        # override it from their Feed Properties dialog. Appended near the end
        # rather than next to "Feeds && Articles" on purpose: inserting a page
        # mid-notebook renumbers every tab after it, and the Ctrl+Tab position
        # of these pages is muscle memory for screen-reader users.
        self.columns_panel = ColumnLayoutPanel(
            notebook, layout=config.get("article_columns", None)
        )
        notebook.AddPage(self.columns_panel, _("List Headers"))

        # Advanced Tab
        advanced_panel = wx.Panel(notebook)
        advanced_sizer = wx.BoxSizer(wx.VERTICAL)

        storage_group = wx.StaticBox(advanced_panel, label=_("Data Storage Location"))
        storage_sizer = wx.StaticBoxSizer(storage_group, wx.VERTICAL)

        storage_help = wx.StaticText(
            advanced_panel,
            label=_(
                "Where BlindRSS stores config.json and rss.db.\n"
                "User Data Folder keeps your settings and feeds across app upgrades,\n"
                "especially on macOS where the installed app bundle is replaced."
            ),
        )
        storage_sizer.Add(storage_help, 0, wx.ALL, 6)

        self._storage_location_map = {
            _("User Data Folder"): "user_data",
            _("App Install Folder"): "app_folder",
        }
        storage_choices = list(self._storage_location_map.keys())
        storage_row = wx.BoxSizer(wx.HORIZONTAL)
        storage_row.Add(
            wx.StaticText(advanced_panel, label=_("Storage Location:")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.ALL,
            5,
        )
        self.storage_location_ctrl = wx.Choice(advanced_panel, choices=storage_choices)
        current_storage = str(config.get("data_location", "app_folder") or "app_folder")
        selected_label = "App Install Folder"
        for lbl, val in self._storage_location_map.items():
            if val == current_storage:
                selected_label = lbl
                break
        self.storage_location_ctrl.SetStringSelection(selected_label)
        storage_row.Add(self.storage_location_ctrl, 0, wx.ALL, 5)
        storage_sizer.Add(storage_row, 0, wx.EXPAND | wx.ALL, 4)

        try:
            paths = config_mod.ConfigManager.location_paths()
        except Exception:
            paths = {"user_data": "", "app_folder": ""}
        paths_lbl = wx.StaticText(
            advanced_panel,
            label=(
                _("User Data Folder path:\n  {path}\n").format(path=paths.get('user_data', ''))
                + _("App Install Folder path:\n  {path}").format(path=paths.get('app_folder', ''))
            ),
        )
        storage_sizer.Add(paths_lbl, 0, wx.ALL, 6)

        self._initial_storage_location = current_storage
        advanced_sizer.Add(storage_sizer, 0, wx.EXPAND | wx.ALL, 8)

        updates_group = wx.StaticBox(advanced_panel, label=_("Updates"))
        updates_sizer = wx.StaticBoxSizer(updates_group, wx.VERTICAL)
        self.install_updates_automatically_chk = wx.CheckBox(
            advanced_panel,
            label=_("Automatically install updates without confirmation"),
        )
        self.install_updates_automatically_chk.SetValue(
            bool(config.get("install_updates_automatically", False))
        )
        updates_sizer.Add(self.install_updates_automatically_chk, 0, wx.ALL, 6)
        advanced_sizer.Add(updates_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # Video Search content controls.
        search_group = wx.StaticBox(advanced_panel, label=_("Video Search"))
        search_sizer = wx.StaticBoxSizer(search_group, wx.VERTICAL)
        self.enable_adult_search_chk = wx.CheckBox(
            advanced_panel,
            label=_("Enable adult sites in Video Search"),
        )
        self.enable_adult_search_chk.SetValue(bool(config.get("enable_adult_search", False)))
        self.enable_adult_search_chk.SetName("Enable adult sites in Video Search")
        search_sizer.Add(self.enable_adult_search_chk, 0, wx.ALL, 6)
        search_sizer.Add(
            wx.StaticText(
                advanced_panel,
                label=_(
                    "When off, adult sites never appear in the Video Search site list.\n"
                    "When on, adult sites are added and must still be selected explicitly to search them."
                ),
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            6,
        )
        advanced_sizer.Add(search_sizer, 0, wx.EXPAND | wx.ALL, 8)

        advanced_panel.SetSizer(advanced_sizer)
        notebook.AddPage(advanced_panel, _("Advanced"))

        # Main Sizer
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)
        
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        
        self.SetSizer(main_sizer)
        self.Centre()
        
        wx.CallAfter(self.refresh_ctrl.SetFocus)

    def on_provider_choice(self, event):
        self._update_provider_panels()

    def on_translation_provider_choice(self, event):
        self._update_translation_provider_controls()
        try:
            event.Skip()
        except Exception:
            pass

    def on_load_openrouter_models(self, event):
        if bool(getattr(self, "_openrouter_models_loading", False)):
            return

        try:
            api_key = str(self.translation_openrouter_api_key_ctrl.GetValue() or "").strip()
        except Exception:
            api_key = ""

        try:
            self._openrouter_models_loading = True
            self.translation_openrouter_load_models_btn.Disable()
        except Exception:
            pass
        try:
            self.translation_openrouter_models_status_lbl.SetLabel(_("Loading OpenRouter models..."))
        except Exception:
            pass

        threading.Thread(
            target=self._load_openrouter_models_worker,
            args=(api_key,),
            daemon=True,
        ).start()
        try:
            event.Skip()
        except Exception:
            pass

    def _load_openrouter_models_worker(self, api_key: str) -> None:
        models = []
        error = ""
        try:
            models = list(translation_mod.list_openrouter_models(api_key=api_key, timeout_s=25) or [])
        except Exception as e:
            error = str(e or "").strip() or "Unknown error"
        try:
            wx.CallAfter(self._on_openrouter_models_loaded, models, error)
        except Exception:
            pass

    def _on_openrouter_models_loaded(self, models: list[str], error: str = "") -> None:
        try:
            self._openrouter_models_loading = False
            self.translation_openrouter_load_models_btn.Enable()
        except Exception:
            pass

        if error:
            try:
                self.translation_openrouter_models_status_lbl.SetLabel(f"OpenRouter model load failed: {error}")
            except Exception:
                pass
            return

        try:
            existing_value = str(self.translation_openrouter_model_ctrl.GetValue() or "").strip()
        except Exception:
            existing_value = ""
        choices = [
            str(m)
            for m in getattr(translation_mod, "_DEFAULT_OPENROUTER_MODEL_CANDIDATES", ())
            if str(m or "").strip()
        ]
        choices.extend([str(m).strip() for m in (models or []) if str(m or "").strip()])

        deduped = []
        seen = set()
        for item in choices:
            key = str(item).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(str(item))

        try:
            self.translation_openrouter_model_ctrl.Clear()
            for item in deduped:
                self.translation_openrouter_model_ctrl.Append(item)
        except Exception:
            pass
        try:
            if existing_value and not self.translation_openrouter_model_ctrl.SetStringSelection(existing_value):
                self.translation_openrouter_model_ctrl.SetValue(existing_value)
        except Exception:
            pass
        try:
            self.translation_openrouter_models_status_lbl.SetLabel(f"Loaded {len(models)} OpenRouter models.")
        except Exception:
            pass

    def _translation_provider_key_from_ui(self) -> str:
        """Return the internal provider key (e.g. 'grok') from the UI display name."""
        try:
            display = str(self.translation_provider_ctrl.GetStringSelection() or "").strip()
        except Exception:
            display = ""
        mapping = getattr(self, "_translation_provider_display_to_key", {}) or {}
        provider = mapping.get(display, display.lower())
        if provider not in ("grok", "groq", "openai", "openrouter", "gemini", "qwen"):
            provider = "grok"
        return provider

    def _update_translation_provider_controls(self):
        provider = self._translation_provider_key_from_ui()

        rows_map = getattr(self, "_translation_provider_rows", {}) or {}
        layout_sizer = getattr(self, "_translation_layout_sizer", None)
        layout_panel = getattr(self, "_translation_layout_panel", None)
        if not layout_sizer:
            return

        for name, rows in rows_map.items():
            show = bool(name == provider)
            for row in (rows or []):
                try:
                    layout_sizer.Show(row, show, recursive=True)
                except Exception:
                    pass

        try:
            if layout_panel:
                layout_panel.Layout()
                layout_panel.Refresh()
        except Exception:
            pass

    def _on_toggle_windows_notifications(self, event):
        self._update_notification_controls()

    def _sorted_notification_feed_entries(self):
        entries = []
        seen = set()
        for item in (self._notification_feed_entries or []):
            try:
                feed_id, title = item
            except Exception:
                continue
            fid = str(feed_id or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            label = str(title or "").strip() or fid
            entries.append((fid, label))
        entries.sort(key=lambda x: (x[1] or "").lower())
        return entries

    def _update_excluded_feeds_label(self):
        total = len(self._sorted_notification_feed_entries())
        excluded = len(getattr(self, "_notification_excluded_feed_ids", set()) or set())
        if total <= 0:
            text = "No feeds available."
        else:
            text = f"Excluded feeds: {excluded} of {total}"
        try:
            self.exclude_feeds_lbl.SetLabel(text)
        except Exception:
            pass

    def on_exclude_notification_feeds(self, event):
        entries = self._sorted_notification_feed_entries()
        dlg = ExcludeNotificationFeedsDialog(
            self,
            feed_entries=entries,
            excluded_ids=self._notification_excluded_feed_ids,
        )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self._notification_excluded_feed_ids = {
                    str(x) for x in (dlg.get_excluded_feed_ids() or []) if str(x or "").strip()
                }
                self._update_excluded_feeds_label()
        finally:
            dlg.Destroy()

    def on_test_notification(self, event):
        if not utils.platform_supports_notifications():
            wx.MessageBox(_("Notifications are not supported on this platform."), _("Notifications"), wx.ICON_INFORMATION)
            return

        title = _("BlindRSS notification test")
        body = _("If you can read this, notifications are working.")
        shown = False

        parent = self.GetParent()
        try:
            tray = getattr(parent, "tray_icon", None)
            if tray and hasattr(tray, "show_notification"):
                shown = bool(tray.show_notification(title, body))
        except Exception:
            shown = False

        if not shown:
            try:
                note = wx.adv.NotificationMessage(title, body, parent=parent if parent else self)
                try:
                    note.SetFlags(wx.ICON_INFORMATION)
                except Exception:
                    pass
                shown = bool(note.Show(timeout=wx.adv.NotificationMessage.Timeout_Auto))
            except Exception:
                shown = False

        if not shown:
            hint = (
                "Check Windows notification permissions and Focus Assist."
                if sys.platform.startswith("win")
                else "Check the app's notification permission in System Settings > Notifications and that Do Not Disturb is off."
            )
            wx.MessageBox(
                f"Notification APIs were unavailable. {hint}",
                _("Notifications"),
                wx.ICON_WARNING,
            )

    def on_test_announcement(self, event):
        """Send a test announcement to the screen reader (issue #71).

        Reuses the running MainFrame's announcer when there is one so the test
        exercises the exact object that announces real events; only falls back
        to a fresh Announcer if the dialog has no such parent.
        """
        announcer = getattr(self.GetParent(), "announcer", None)
        if announcer is None:
            try:
                announcer = announcements_mod.Announcer()
            except Exception:
                announcer = None

        delivered = False
        if announcer is not None:
            try:
                delivered = bool(
                    announcer.announce_test(
                        _("BlindRSS announcement test. If you can hear or read this, announcements are working.")
                    )
                )
            except Exception:
                logging.getLogger(__name__).debug("Test announcement failed", exc_info=True)
                delivered = False

        if delivered:
            return

        # Nothing reached speech or Braille. Say so in a dialog: staying silent
        # is exactly the failure being tested for, so a silent no-op would be
        # indistinguishable from success to the user who needs this button.
        wx.MessageBox(
            _(
                "The announcement could not be delivered.\n\n"
                "No screen reader output was available. Check that your screen "
                "reader is running, and that the accessible-output2 library is "
                "installed for full speech and Braille support."
            ),
            _("Announcements"),
            wx.ICON_WARNING,
        )

    def _update_notification_controls(self):
        supported = utils.platform_supports_notifications()
        enabled = bool(getattr(self, "windows_notifications_chk", None) and self.windows_notifications_chk.GetValue())
        if not supported:
            enabled = False
        controls = [
            getattr(self, "windows_notifications_feed_chk", None),
            getattr(self, "windows_notifications_max_ctrl", None),
            getattr(self, "windows_notifications_summary_chk", None),
        ]
        for ctrl in controls:
            if not ctrl:
                continue
            try:
                ctrl.Enable(enabled)
            except Exception:
                pass
        try:
            test_btn = getattr(self, "test_notification_btn", None)
            if test_btn:
                test_btn.Enable(supported)
        except Exception:
            pass
        try:
            exclude_btn = getattr(self, "exclude_feeds_btn", None)
            if exclude_btn:
                exclude_btn.Enable(supported)
        except Exception:
            pass

    def _update_provider_panels(self):
        try:
            sel = self.provider_choice.GetStringSelection()
        except Exception:
            sel = "local"
        for name, (pnl, _ctrls) in getattr(self, "_provider_panels", {}).items():
            try:
                pnl.Show(name == sel)
            except Exception:
                pass
        try:
            # Refresh layout so controls become reachable in tab order immediately.
            self.Layout()
            self.FitInside() if hasattr(self, "FitInside") else None
        except Exception:
            pass

    def _set_inoreader_status(self, text: str, ok: bool = False) -> None:
        lbl = getattr(self, "_inoreader_status_lbl", None)
        if not lbl:
            return
        try:
            lbl.SetLabel(text)
        except Exception:
            return
        try:
            color = wx.Colour(0, 128, 0) if ok else wx.Colour(160, 0, 0)
            lbl.SetForegroundColour(color)
        except Exception:
            pass

    def _start_inoreader_authorize(self, event):
        app_id_ctrl = getattr(self, "_inoreader_app_id_ctrl", None)
        app_key_ctrl = getattr(self, "_inoreader_app_key_ctrl", None)
        redirect_uri_ctrl = getattr(self, "_inoreader_redirect_uri_ctrl", None)
        if not app_id_ctrl or not app_key_ctrl or not redirect_uri_ctrl:
            return
        app_id = (app_id_ctrl.GetValue() or "").strip()
        app_key = (app_key_ctrl.GetValue() or "").strip()
        redirect_uri = (redirect_uri_ctrl.GetValue() or "").strip()
        if not app_id or not app_key:
            wx.MessageBox(_("Enter your Inoreader App ID and App Key first."), "Inoreader", wx.ICON_INFORMATION)
            return
        btn = getattr(self, "_inoreader_authorize_btn", None)
        if btn:
            try:
                btn.Disable()
            except Exception:
                pass
        self._set_inoreader_status("Waiting for authorization...", ok=False)
        threading.Thread(
            target=self._inoreader_oauth_worker,
            args=(app_id, app_key, redirect_uri),
            daemon=True,
        ).start()

    def _prompt_inoreader_redirect_paste(self, redirect_uri: str, result_q) -> None:
        result = None
        try:
            dlg = wx.Dialog(self, title=_("Inoreader Authorization"), size=(580, 320))
            sizer = wx.BoxSizer(wx.VERTICAL)
            msg = (
                "After authorizing in your browser, it will redirect to your Redirect URI.\n"
                "If the redirected page fails to load (common for HTTPS localhost), copy the full URL from the\n"
                "browser address bar and paste it below.\n\n"
                f"Redirect URI:\n{redirect_uri}"
            )
            sizer.Add(wx.StaticText(dlg, label=msg), 0, wx.ALL, 10)
            tc = wx.TextCtrl(dlg, style=wx.TE_MULTILINE)
            tc.SetName("Redirected URL")
            tc.SetHint(_("Paste the full URL from your browser address bar"))
            sizer.Add(tc, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
            btns = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
            sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
            dlg.SetSizer(sizer)
            dlg.CentreOnParent()
            try:
                tc.SetFocus()
            except Exception:
                pass
            if dlg.ShowModal() == wx.ID_OK:
                result = (tc.GetValue() or "").strip()
            dlg.Destroy()
        except Exception:
            result = None
        try:
            result_q.put_nowait(result)
        except Exception:
            pass

    def _inoreader_oauth_worker(self, app_id: str, app_key: str, redirect_uri: str) -> None:
        redirect_uri = (redirect_uri or "").strip() or inoreader_oauth.get_redirect_uri(scheme="https")
        try:
            auth_url, state = inoreader_oauth.create_authorization_url(app_id, redirect_uri)
            parsed = urlparse(redirect_uri)
            scheme = (parsed.scheme or "").lower()
            host = (parsed.hostname or "").lower()

            use_local_http_callback = scheme == "http" and host in {"127.0.0.1", "localhost"}
            if use_local_http_callback:
                ready_event = threading.Event()

                def _open_browser():
                    try:
                        ready_event.wait(5)
                    except Exception:
                        pass
                    webbrowser.open(auth_url)

                threading.Thread(target=_open_browser, daemon=True).start()
                code = inoreader_oauth.wait_for_oauth_code(
                    state,
                    ready_event=ready_event,
                    host=parsed.hostname or "127.0.0.1",
                    port=parsed.port or 80,
                    path=parsed.path or "/",
                )
            else:
                webbrowser.open(auth_url)
                wx.CallAfter(
                    self._set_inoreader_status,
                    "Complete authorization in your browser, then paste the redirected URL...",
                    False,
                )
                result_q = queue.Queue(maxsize=1)
                wx.CallAfter(self._prompt_inoreader_redirect_paste, redirect_uri, result_q)
                try:
                    pasted = result_q.get(timeout=300)
                except queue.Empty as exc:
                    raise TimeoutError("Timed out waiting for the redirected URL.") from exc
                if not pasted:
                    raise RuntimeError("Authorization cancelled.")

                code, returned_state, err = inoreader_oauth.parse_oauth_redirect(pasted)
                if err:
                    raise RuntimeError(f"Inoreader authorization failed: {err}")
                if not code:
                    raise RuntimeError("No authorization code found in the pasted URL.")
                if not returned_state:
                    raise RuntimeError("Missing state parameter; paste the full redirected URL from your browser address bar.")
                if state and returned_state != state:
                    raise RuntimeError("Invalid state (redirect does not match this authorization attempt).")

            token_data = inoreader_oauth.exchange_code_for_tokens(app_id, app_key, code, redirect_uri)
            access_token = token_data.get("access_token")
            if not access_token:
                raise RuntimeError("No access token returned from Inoreader.")

            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                try:
                    refresh_token = (
                        (self.config.get("providers") or {})
                        .get("inoreader", {})
                        .get("refresh_token", "")
                    )
                except Exception:
                    refresh_token = ""

            expires_in = token_data.get("expires_in", 0)
            expires_at = 0
            try:
                expires_in_int = int(expires_in or 0)
                if expires_in_int > 0:
                    expires_at = int(time.time() + max(0, expires_in_int - 60))
            except Exception:
                expires_at = 0

            token_payload = {
                "token": access_token,
                "refresh_token": refresh_token or "",
                "token_expires_at": expires_at,
            }
            wx.CallAfter(self._on_inoreader_oauth_success, token_payload)
        except Exception as exc:
            wx.CallAfter(self._on_inoreader_oauth_error, str(exc))

    def _on_inoreader_oauth_success(self, token_payload: dict) -> None:
        self._inoreader_tokens = dict(token_payload or {})
        self._set_inoreader_status("Authorized", ok=True)
        btn = getattr(self, "_inoreader_authorize_btn", None)
        if btn:
            try:
                btn.Enable()
            except Exception:
                pass

    def _on_inoreader_oauth_error(self, message: str) -> None:
        self._set_inoreader_status("Authorization failed", ok=False)
        btn = getattr(self, "_inoreader_authorize_btn", None)
        if btn:
            try:
                btn.Enable()
            except Exception:
                pass
        wx.MessageBox(
            _("Inoreader authorization failed:\n{message}").format(message=message),
            "Inoreader",
            wx.ICON_ERROR,
        )

    def _clear_inoreader_authorization(self, event) -> None:
        self._inoreader_tokens = {
            "token": "",
            "refresh_token": "",
            "token_expires_at": 0,
        }
        self._set_inoreader_status("Not authorized", ok=False)

    @staticmethod
    def _decode_vlc_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode("utf-8", errors="ignore")
            except Exception:
                return ""
        try:
            return str(value)
        except Exception:
            return ""

    def _translation_language_display_value(self, raw_value: str) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return f'{_("English")} (en)'
        try:
            mapped = (self._translation_language_code_to_label or {}).get(value.lower())
        except Exception:
            mapped = None
        return mapped or value

    def _translation_language_code_from_ui(self) -> str:
        try:
            raw = str(self.translation_target_language_ctrl.GetValue() or "").strip()
        except Exception:
            raw = ""
        if not raw:
            return "en"

        try:
            direct = (self._translation_language_label_to_code or {}).get(raw)
        except Exception:
            direct = None
        if direct:
            return str(direct)

        # Accept manually typed values that include a label suffix like "Spanish (es)".
        if raw.endswith(")") and "(" in raw:
            try:
                maybe = raw[raw.rfind("(") + 1:-1].strip()
            except Exception:
                maybe = ""
            if maybe:
                return maybe
        return raw

    def _load_soundcards_async(self):
        """Background thread: enumerate VLC soundcards, then update the UI."""
        choices = self._build_soundcard_choices(self._current_soundcard)
        try:
            # The dialog/app can be destroyed while enumeration is still in
            # flight (notably during fast test or shutdown paths).
            wx.CallAfter(self._populate_soundcard_ctrl, choices)
        except (AssertionError, RuntimeError):
            return

    def _populate_soundcard_ctrl(self, choices):
        """Called on main thread to fill the soundcard dropdown."""
        self._soundcard_choices = choices
        self._soundcard_labels = [label for label, _device_id in choices]
        self.soundcard_ctrl.Set(self._soundcard_labels)
        sel_idx = 0
        for i, (_label, device_id) in enumerate(choices):
            if str(device_id or "") == self._current_soundcard:
                sel_idx = i
                break
        self.soundcard_ctrl.SetSelection(sel_idx)

    def _build_soundcard_choices(self, selected_device_id: str) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = [(_("System Default"), "")]
        seen_ids = {""}
        preferred = str(selected_device_id or "")
        devices_ptr = None
        try:
            import vlc

            instance = vlc.Instance(*build_vlc_instance_args("--no-video", "--aout=mmdevice"))
            devices_ptr = instance.audio_output_device_list_get("mmdevice")
            cur = devices_ptr
            while cur:
                device_id = self._decode_vlc_text(cur.contents.device).strip()
                description = self._decode_vlc_text(cur.contents.description).strip()
                label = description or device_id or "Unnamed Device"
                if device_id not in seen_ids:
                    choices.append((label, device_id))
                    seen_ids.add(device_id)
                cur = cur.contents.next
        except Exception:
            log.exception("Failed to enumerate VLC soundcards")
        finally:
            if devices_ptr is not None:
                try:
                    import vlc
                    vlc.libvlc_audio_output_device_list_release(devices_ptr)
                except Exception:
                    pass

        # Keep unknown saved IDs visible so opening settings does not silently reset them.
        if preferred and preferred not in seen_ids:
            choices.append((f"Saved device (currently unavailable): {preferred}", preferred))
        return choices

    def _sync_delete_category_enabled(self):
        """Enable the delete-target category field only for the 'Move to a
        category' delete behavior."""
        idx = self.delete_behavior_ctrl.GetSelection()
        kind = self._delete_behavior_choices[idx][0] if idx >= 0 else "deleted"
        self.delete_category_ctrl.Enable(kind == "category")

    def _selected_retention_id(self, combo, ids):
        """Stable identifier for the retention combobox selection (issue #63)."""
        idx = combo.GetSelection()
        if 0 <= idx < len(ids):
            return ids[idx]
        return RETENTION_DEFAULT

    def _delete_behavior_setting(self):
        """Encode the delete-behavior choice + category into the config string."""
        idx = self.delete_behavior_ctrl.GetSelection()
        kind = self._delete_behavior_choices[idx][0] if idx >= 0 else "deleted"
        if kind == "category":
            category = normalize_category_input(
                self.delete_category_ctrl.GetValue(), self._delete_category_identities
            )
            return f"category:{category}" if category else "deleted"
        return kind

    def on_browse_dl_path(self, event):
        dlg = wx.DirDialog(self, "Choose download directory", self.dl_path_ctrl.GetValue(), style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.dl_path_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_browse_cookies_file(self, event):
        dlg = wx.FileDialog(
            self,
            _("Choose yt-dlp cookies.txt"),
            defaultFile=self.ytdlp_cookies_ctrl.GetValue(),
            wildcard=f'{_("Cookies")} (*.txt)|*.txt|{_("All files")} (*.*)|*.*',
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.ytdlp_cookies_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _current_play_cache_dir(self):
        """The cache dir reflecting the (possibly unsaved) location field."""
        from core import play_cache
        loc = (self.youtube_play_cache_dir_ctrl.GetValue() or "").strip()
        return loc or play_cache.default_cache_dir()

    def _on_browse_play_cache_dir(self, event):
        dlg = wx.DirDialog(
            self,
            "Choose YouTube playback cache folder",
            self.youtube_play_cache_dir_ctrl.GetValue(),
            style=wx.DD_DEFAULT_STYLE,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.youtube_play_cache_dir_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_clear_play_cache(self, event):
        from core import play_cache
        cache_dir = self._current_play_cache_dir()
        size = play_cache.cache_size_bytes(cache_dir)
        count = play_cache.cache_file_count(cache_dir)
        if count == 0:
            wx.MessageBox(
                f'{_("The playback cache is already empty.")}\n\n{cache_dir}',
                _("Playback cache"),
                wx.ICON_INFORMATION,
            )
            return
        confirm = wx.MessageBox(
            ngettext("Delete {n} cached file ({size})?", "Delete {n} cached files ({size})?", count).format(n=count, size=play_cache.human_size(size))
            + f"\n\n{cache_dir}",
            _("Clear playback cache"),
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if confirm != wx.YES:
            return
        removed, freed = play_cache.clear_cache(cache_dir)
        wx.MessageBox(
            ngettext("Removed {n} file, freed {size}.", "Removed {n} files, freed {size}.", removed).format(n=removed, size=play_cache.human_size(freed)),
            _("Playback cache cleared"),
            wx.ICON_INFORMATION,
        )

    _COOKIES_EXTENSION_URL = "https://github.com/kairi003/Get-cookies.txt-LOCALLY"

    def _on_import_cookies_from_browser(self, event):
        """Guide the user through exporting cookies.txt, then auto-import it.

        We cannot read Chromium App-Bound-encrypted cookies directly, so the user
        exports a cookies.txt with a browser extension and we detect/import it.
        """
        import os
        from core import cookies_import

        steps = (
            "To use your YouTube login with yt-dlp:\n\n"
            "1. Install a cookies.txt exporter extension in your browser, e.g. "
            "\"Get cookies.txt LOCALLY\".\n"
            "2. Open youtube.com and make sure you are signed in.\n"
            "3. Click the extension and Export to download a cookies.txt.\n"
            "4. Come back here and choose \"Find my export\".\n\n"
            "Cookies are only needed for age-restricted, private, or members-only "
            "videos. Firefox and LibreWolf do not need this — their cookies are "
            "detected automatically."
        )
        dlg = wx.MessageDialog(
            self,
            steps,
            "Import cookies from browser",
            style=wx.YES_NO | wx.CANCEL | wx.ICON_INFORMATION,
        )
        dlg.SetYesNoCancelLabels(_("Find my export"), _("Open extension page"), _("Cancel"))
        choice = dlg.ShowModal()
        dlg.Destroy()

        if choice == wx.ID_NO:
            try:
                webbrowser.open(self._COOKIES_EXTENSION_URL)
            except Exception:
                pass
            return
        if choice != wx.ID_YES:
            return

        # Search the user's current cookies-path directory first (in case they
        # exported straight there), then the usual Downloads locations.
        extra_dirs = []
        current = (self.ytdlp_cookies_ctrl.GetValue() or "").strip()
        if current:
            extra_dirs.append(os.path.dirname(current))
        search_dirs = cookies_import.default_download_dirs(extra_dirs)
        found = cookies_import.find_latest_youtube_cookie_export(search_dirs)

        if not found:
            # Fall back to letting the user point us at the file directly.
            pick = wx.MessageDialog(
                self,
                "No recent YouTube cookies.txt export was found in your Downloads.\n\n"
                "Export one with the extension first, or choose the file manually.",
                "No export found",
                style=wx.OK | wx.CANCEL | wx.ICON_WARNING,
            )
            pick.SetOKCancelLabels(_("Choose file..."), _("Cancel"))
            do_pick = pick.ShowModal()
            pick.Destroy()
            if do_pick != wx.ID_OK:
                return
            fdlg = wx.FileDialog(
                self,
                _("Choose exported cookies.txt"),
                wildcard=f'{_("Cookies")} (*.txt)|*.txt|{_("All files")} (*.*)|*.*',
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            )
            if fdlg.ShowModal() != wx.ID_OK:
                fdlg.Destroy()
                return
            found = fdlg.GetPath()
            fdlg.Destroy()

        try:
            dest = cookies_import.import_cookie_file(found, config_mod.get_data_dir())
        except ValueError as e:
            wx.MessageBox(
                f"That file is not a usable YouTube cookie export:\n\n{e}",
                _("Import failed"),
                wx.ICON_ERROR,
            )
            return
        except OSError as e:
            wx.MessageBox(
                f"Could not import the cookies file:\n\n{e}",
                _("Import failed"),
                wx.ICON_ERROR,
            )
            return

        self.ytdlp_cookies_ctrl.SetValue(dest)
        wx.MessageBox(
            f"Imported YouTube cookies from:\n{found}\n\n"
            f"Saved as:\n{dest}\n\n"
            "Save settings to start using it.",
            _("Cookies imported"),
            wx.ICON_INFORMATION,
        )

    def _on_browse_media_tool(self, ctrl, label):
        if sys.platform.startswith("win"):
            wildcard = f'{_("Executables")} (*.exe)|*.exe|{_("All files")} (*.*)|*.*'
        else:
            wildcard = f'{_("All files")} (*.*)|*.*'
        dlg = wx.FileDialog(
            self,
            f"Choose {label} executable",
            defaultFile=ctrl.GetValue(),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _detect_media_tools_async(self):
        try:
            from core import dependency_check
            detected = dependency_check.detect_media_tool_paths(validate=True)
        except Exception:
            detected = {}
        try:
            wx.CallAfter(self._apply_detected_media_tools, detected)
        except Exception:
            pass

    def _apply_detected_media_tools(self, detected):
        labels = getattr(self, "_media_tool_detected_lbls", {}) or {}
        names = {"ffmpeg": "FFmpeg", "ffprobe": "FFprobe", "yt-dlp": "yt-dlp"}
        for key, lbl in labels.items():
            if not lbl:
                continue
            info = (detected or {}).get(key) or {}
            path = info.get("path")
            nm = names.get(key, key)
            if not path:
                text = f"Detected {nm}: not found"
            elif info.get("valid") is False:
                text = f"Detected {nm}: {path} (failed version check)"
            else:
                text = f"Detected {nm}: {path}"
            try:
                lbl.SetLabel(text)
            except Exception:
                # Dialog may have been closed before detection finished.
                pass

    def _on_article_open_method_changed(self, event=None):
        self._sync_article_open_controls()
        if event is not None:
            event.Skip()

    def _sync_article_open_controls(self):
        """Enable the custom-command field/Test button only in 'Custom command' mode (issue #31)."""
        is_custom = self.article_open_method_ctrl.GetStringSelection() == _("Custom command")
        self.article_open_command_ctrl.Enable(is_custom)
        self.article_open_test_btn.Enable(is_custom)

    def on_test_article_command(self, event=None):
        """Validate and launch the custom open-article command with a sample URL (issue #31)."""
        template = (self.article_open_command_ctrl.GetValue() or "").strip()
        if not template:
            wx.MessageBox(
                _("Enter a command to test. Use %1 where the article URL should go."),
                _("Nothing to test"), wx.ICON_INFORMATION, self,
            )
            return
        test_url = "https://example.com/"
        from core import utils as _utils
        try:
            argv = _utils.build_open_command(template, test_url)
        except ValueError as exc:
            wx.MessageBox(
                f"The command could not be parsed:\n\n{exc}",
                _("Invalid command"), wx.ICON_ERROR, self,
            )
            return
        ok, err = _utils.launch_open_command(template, test_url)
        if ok:
            wx.MessageBox(
                "Launched the test command with a sample URL:\n\n"
                f"{' '.join(argv)}\n\n"
                "Check that your browser opened https://example.com/ as expected.",
                _("Test launched"), wx.ICON_INFORMATION, self,
            )
        else:
            wx.MessageBox(
                f"The command could not be run:\n\n{err}",
                _("Test failed"), wx.ICON_ERROR, self,
            )

    def _collect_announcement_modes(self) -> dict:
        """Read the Announcements tab dropdowns into a {event_id: mode} map."""
        modes = {}
        values = getattr(self, "_announcement_mode_values", []) or []
        for event_id, choice in getattr(self, "_announcement_choice_ctrls", {}).items():
            try:
                idx = int(choice.GetSelection())
                if 0 <= idx < len(values):
                    modes[event_id] = values[idx]
            except Exception:
                continue
        return announcements_mod.normalize_modes(modes)

    def get_data(self):
        # Parse speed back to float
        speed_str = self.speed_ctrl.GetValue().replace("x", "")
        try:
            speed = float(speed_str)
        except ValueError:
            speed = 1.0

        preferred_soundcard = ""
        try:
            idx = int(self.soundcard_ctrl.GetSelection())
            if idx != wx.NOT_FOUND and 0 <= idx < len(getattr(self, "_soundcard_choices", [])):
                preferred_soundcard = str(self._soundcard_choices[idx][1] or "")
        except Exception:
            preferred_soundcard = ""
            
        providers = {}
        try:
            providers = copy.deepcopy(self.config.get("providers", {})) if isinstance(self.config, dict) else {}
        except Exception:
            providers = {}

        # Collect provider settings from UI controls (preserves existing keys like local feeds).
        for name, (_pnl, ctrls) in getattr(self, "_provider_panels", {}).items():
            if not ctrls:
                continue
            p_cfg = providers.get(name, {})
            if not isinstance(p_cfg, dict):
                p_cfg = {}
            for key, tc in ctrls.items():
                try:
                    p_cfg[key] = (tc.GetValue() or "").strip()
                except Exception:
                    p_cfg[key] = ""
            providers[name] = p_cfg

        if "inoreader" in providers:
            p_cfg = providers.get("inoreader", {})
            tokens = getattr(self, "_inoreader_tokens", None)
            if tokens is not None:
                try:
                    p_cfg.update(tokens)
                except Exception:
                    pass
            else:
                original = getattr(self, "_inoreader_auth_original", {}) or {}
                if (
                    str(p_cfg.get("app_id", "") or "") != str(original.get("app_id", "") or "")
                    or str(p_cfg.get("app_key", "") or "") != str(original.get("app_key", "") or "")
                ):
                    p_cfg["token"] = ""
                    p_cfg["refresh_token"] = ""
                    p_cfg["token_expires_at"] = 0
            providers["inoreader"] = p_cfg

        return {
            "refresh_interval": self.refresh_map.get(self.refresh_ctrl.GetStringSelection(), 300),
            "search_mode": self.search_mode_map.get(self.search_mode_ctrl.GetStringSelection(), "title_content"),
            "category_tree_default_expanded": self.tree_expand_map.get(self.tree_expand_ctrl.GetStringSelection(), True),
            "article_open_method": self.article_open_method_map.get(self.article_open_method_ctrl.GetStringSelection(), "default"),
            "article_open_command": self.article_open_command_ctrl.GetValue().strip(),
            "max_concurrent_refreshes": self.concurrent_ctrl.GetValue(),
            "per_host_max_connections": self.per_host_ctrl.GetValue(),
            "feed_timeout_seconds": self.timeout_ctrl.GetValue(),
            "feed_retry_attempts": self.retry_ctrl.GetValue(),
            "preferred_soundcard": preferred_soundcard,
            "skip_silence": self.skip_silence_chk.GetValue(),
            "playback_speed": speed,
            "show_player_on_play": self.show_player_on_play_chk.GetValue(),
            "vlc_network_caching_ms": self.vlc_cache_ctrl.GetValue(),
            "range_cache_debug": self.range_cache_debug_chk.GetValue(),
            "max_cached_views": self.cache_ctrl.GetValue(),
            "cache_full_text": self.cache_full_text_chk.GetValue(),
            "downloads_enabled": self.downloads_chk.GetValue(),
            "confirm_article_delete": self.confirm_delete_chk.GetValue(),
            "delete_behavior": self._delete_behavior_setting(),
            "download_path": self.dl_path_ctrl.GetValue(),
            "download_retention": self._selected_retention_id(
                self.retention_ctrl, self._retention_ids_download
            ),
            "article_retention": self._selected_retention_id(
                self.art_retention_ctrl, self._retention_ids_article
            ),
            "close_to_tray": self.close_tray_chk.GetValue(),
            "minimize_to_tray": self.min_tray_chk.GetValue(),
            "start_in_system_tray": self.start_in_tray_chk.GetValue(),
            "start_maximized": self.start_maximized_chk.GetValue(),
            "debug_mode": self.debug_mode_chk.GetValue(),
            "refresh_on_startup": self.refresh_startup_chk.GetValue(),
            "automatic_feed_refresh_workload": self.automatic_refresh_workload_map.get(
                self.automatic_refresh_workload_ctrl.GetStringSelection(),
                "startup_full",
            ),
            # Keep the former boolean in sync so a user can safely return to
            # an older build without losing the always-full choice.
            "ignore_feed_cache": self.automatic_refresh_workload_map.get(
                self.automatic_refresh_workload_ctrl.GetStringSelection(),
                "startup_full",
            ) == "always_full",
            "show_image_alt": self.show_image_alt_chk.GetValue(),
            "article_structure_tables": self.structure_tables_chk.GetValue(),
            "article_structure_headings": self.structure_headings_chk.GetValue(),
            "article_structure_lists": self.structure_lists_chk.GetValue(),
            "article_structure_quotes": self.structure_quotes_chk.GetValue(),
            "article_structure_links": self.structure_links_chk.GetValue(),
            "full_text_rich_view": self.rich_view_chk.GetValue(),
            "ytdlp_cookies_file": self.ytdlp_cookies_ctrl.GetValue().strip(),
            "auto_import_browser_cookies": self.auto_import_cookies_chk.GetValue(),
            "youtube_play_via_download": self.youtube_play_via_download_chk.GetValue(),
            "youtube_play_cache_dir": self.youtube_play_cache_dir_ctrl.GetValue().strip(),
            "youtube_play_cache_max_mb": int(self.youtube_play_cache_max_mb_ctrl.GetValue()),
            "custom_ffmpeg_path": self._media_tool_path_ctrls["custom_ffmpeg_path"].GetValue().strip(),
            "custom_ffprobe_path": self._media_tool_path_ctrls["custom_ffprobe_path"].GetValue().strip(),
            "custom_ytdlp_path": self._media_tool_path_ctrls["custom_ytdlp_path"].GetValue().strip(),
            "prompt_missing_dependencies_on_startup": self.prompt_missing_deps_chk.GetValue(),
            "start_on_windows_login": self.start_on_login_chk.GetValue(),
            "remember_last_feed": self.remember_last_feed_chk.GetValue(),
            "language": self.language_choices[max(0, self.language_choice.GetSelection())],
            "auto_check_updates": self.auto_update_chk.GetValue(),
            "install_updates_automatically": self.install_updates_automatically_chk.GetValue(),
            "sounds_enabled": self.sounds_enabled_chk.GetValue(),
            "sound_refresh_complete": self.sound_complete_ctrl.GetValue(),
            "sound_refresh_error": self.sound_error_ctrl.GetValue(),
            "windows_notifications_enabled": self.windows_notifications_chk.GetValue(),
            "windows_notifications_include_feed_name": self.windows_notifications_feed_chk.GetValue(),
            "windows_notifications_max_per_refresh": self.windows_notifications_max_ctrl.GetValue(),
            "windows_notifications_show_summary_when_capped": self.windows_notifications_summary_chk.GetValue(),
            "windows_notifications_excluded_feeds": sorted(self._notification_excluded_feed_ids),
            "announcements": self._collect_announcement_modes(),
            "translation_enabled": self.translation_enabled_chk.GetValue(),
            "translation_provider": self._translation_provider_key_from_ui(),
            "translation_target_language": self._translation_language_code_from_ui(),
            "translation_grok_model": (self.translation_grok_model_ctrl.GetValue() or "").strip(),
            "translation_grok_api_key": (self.translation_grok_api_key_ctrl.GetValue() or "").strip(),
            "translation_groq_model": (self.translation_groq_model_ctrl.GetValue() or "").strip(),
            "translation_groq_api_key": (self.translation_groq_api_key_ctrl.GetValue() or "").strip(),
            "translation_openai_model": (self.translation_openai_model_ctrl.GetValue() or "").strip(),
            "translation_openai_api_key": (self.translation_openai_api_key_ctrl.GetValue() or "").strip(),
            "translation_openrouter_model": (self.translation_openrouter_model_ctrl.GetValue() or "").strip(),
            "translation_openrouter_api_key": (self.translation_openrouter_api_key_ctrl.GetValue() or "").strip(),
            "translation_gemini_model": (self.translation_gemini_model_ctrl.GetValue() or "").strip(),
            "translation_gemini_api_key": (self.translation_gemini_api_key_ctrl.GetValue() or "").strip(),
            "translation_qwen_model": (self.translation_qwen_model_ctrl.GetValue() or "").strip(),
            "translation_qwen_api_key": (self.translation_qwen_api_key_ctrl.GetValue() or "").strip(),
            "enable_adult_search": self.enable_adult_search_chk.GetValue(),
            "article_columns": self.columns_panel.get_layout(),
            "active_provider": self.provider_choice.GetStringSelection(),
            "providers": providers,
            "data_location": self._storage_location_map.get(
                self.storage_location_ctrl.GetStringSelection(),
                self._initial_storage_location,
            ),
        }


class FeedPropertiesDialog(wx.Dialog):
    def __init__(self, parent, feed, categories, allow_url_edit: bool = True):
        super().__init__(parent, title=_("Feed Properties"), size=(540, 620))

        self.feed = feed
        self.category_identities = list(categories or [UNCATEGORIZED])
        self.categories = [category_display_name(category) for category in self.category_identities]
        # Per-feed HTTP overrides (issue #29). Loaded here, saved in on_ok.
        try:
            from core import db as _db
            self._feed_settings = _db.get_feed_settings(getattr(feed, "id", "") or "")
        except Exception:
            self._feed_settings = {}
        if not isinstance(self._feed_settings, dict):
            self._feed_settings = {}
        self._impersonate_values = ["auto", "always", "never"]

        # Tabbed so the per-feed column layout gets room without burying the
        # fields people actually open this dialog for (article list columns). Everything
        # that was previously parented to the dialog now lives on general_panel.
        outer = wx.BoxSizer(wx.VERTICAL)
        notebook = wx.Notebook(self)
        self.notebook = notebook
        general_panel = wx.Panel(notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        title_sizer = wx.BoxSizer(wx.HORIZONTAL)
        title_sizer.Add(wx.StaticText(general_panel, label=_("Title:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.title_ctrl = wx.TextCtrl(general_panel, value=str(feed.title or ""))
        self.title_ctrl.SetName("Feed title")
        title_sizer.Add(self.title_ctrl, 1, wx.ALL, 5)
        sizer.Add(title_sizer, 0, wx.EXPAND)

        url_sizer = wx.BoxSizer(wx.HORIZONTAL)
        url_sizer.Add(wx.StaticText(general_panel, label=_("URL:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.url_ctrl = wx.TextCtrl(general_panel, value=str(feed.url or ""))
        self.url_ctrl.SetName("Feed URL")
        if not bool(allow_url_edit):
            try:
                self.url_ctrl.SetEditable(False)
            except Exception:
                pass
        url_sizer.Add(self.url_ctrl, 1, wx.ALL, 5)
        sizer.Add(url_sizer, 0, wx.EXPAND)

        sizer.Add(wx.StaticText(general_panel, label=_("Category:")), 0, wx.ALL, 5)
        self.cat_ctrl = wx.ComboBox(general_panel, choices=self.categories, style=wx.CB_DROPDOWN)
        self.cat_ctrl.SetName("Category")
        self.cat_ctrl.SetValue(category_display_name(feed.category or UNCATEGORIZED))
        sizer.Add(self.cat_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        # Per-feed refresh interval override. "Use global setting" (None) follows
        # the Settings dialog interval; 0 means the feed only refreshes manually.
        sizer.Add(wx.StaticText(general_panel, label=_("Refresh interval for this feed:")), 0, wx.ALL, 5)
        self._refresh_interval_choices = [
            (None, _("Use global setting")),
            (0, _("Never (manual refresh only)")),
            (30, _("30 seconds")),
            (60, _("1 minute")),
            (120, _("2 minutes")),
            (180, _("3 minutes")),
            (240, _("4 minutes")),
            (300, _("5 minutes")),
            (600, _("10 minutes")),
            (900, _("15 minutes")),
            (1800, _("30 minutes")),
            (3600, _("60 minutes")),
            (7200, _("2 hours")),
            (10800, _("3 hours")),
            (14400, _("4 hours")),
        ]
        self.refresh_interval_ctrl = wx.Choice(general_panel, choices=[lbl for _v, lbl in self._refresh_interval_choices])
        self.refresh_interval_ctrl.SetName(_("Refresh interval for this feed"))
        try:
            current_interval = self._feed_settings.get("refresh_interval_seconds")
        except Exception:
            current_interval = None
        interval_idx = 0
        if isinstance(current_interval, (int, float)) and not isinstance(current_interval, bool):
            current_interval = max(0, int(current_interval))
            best_diff = None
            for i, (value, _label) in enumerate(self._refresh_interval_choices):
                if value is None:
                    continue
                if value == current_interval:
                    interval_idx = i
                    break
                if current_interval > 0 and value > 0:
                    diff = abs(value - current_interval)
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        interval_idx = i
        self.refresh_interval_ctrl.SetSelection(interval_idx)
        sizer.Add(self.refresh_interval_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        # --- Per-feed HTTP fetch overrides (issue #29) ---
        sizer.Add(
            wx.StaticText(general_panel, label=_("Custom request headers (one per line, Name: Value):")),
            0, wx.ALL, 5,
        )
        headers_value = ""
        try:
            existing_headers = self._feed_settings.get("custom_headers") or {}
            if isinstance(existing_headers, dict):
                headers_value = "\n".join(f"{k}: {v}" for k, v in existing_headers.items())
        except Exception:
            headers_value = ""
        self.headers_ctrl = wx.TextCtrl(general_panel, value=headers_value, style=wx.TE_MULTILINE, size=(-1, 110))
        self.headers_ctrl.SetName("Custom request headers")
        sizer.Add(self.headers_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        timeout_sizer = wx.BoxSizer(wx.HORIZONTAL)
        timeout_sizer.Add(
            wx.StaticText(general_panel, label=_("Request timeout in seconds (blank = default):")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )
        timeout_value = ""
        try:
            ts = self._feed_settings.get("timeout_seconds")
            if ts is not None:
                timeout_value = str(int(ts))
        except Exception:
            timeout_value = ""
        self.timeout_ctrl = wx.TextCtrl(general_panel, value=timeout_value)
        self.timeout_ctrl.SetName("Request timeout seconds")
        timeout_sizer.Add(self.timeout_ctrl, 1, wx.ALL, 5)
        sizer.Add(timeout_sizer, 0, wx.EXPAND)

        sizer.Add(wx.StaticText(general_panel, label=_("Browser impersonation:")), 0, wx.ALL, 5)
        self.impersonate_ctrl = wx.Choice(general_panel, choices=[_("Auto"), _("Always"), _("Never")])
        self.impersonate_ctrl.SetName("Browser impersonation")
        try:
            current_imp = str(self._feed_settings.get("impersonate") or "auto").lower()
            imp_idx = self._impersonate_values.index(current_imp) if current_imp in self._impersonate_values else 0
        except Exception:
            imp_idx = 0
        self.impersonate_ctrl.SetSelection(imp_idx)
        sizer.Add(self.impersonate_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        proxy_sizer = wx.BoxSizer(wx.HORIZONTAL)
        proxy_sizer.Add(
            wx.StaticText(general_panel, label=_("Proxy URL (optional, e.g. http://host:port):")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )
        proxy_value = ""
        try:
            proxy_value = str(self._feed_settings.get("proxy") or "")
        except Exception:
            proxy_value = ""
        self.proxy_ctrl = wx.TextCtrl(general_panel, value=proxy_value)
        self.proxy_ctrl.SetName("Proxy URL")
        proxy_sizer.Add(self.proxy_ctrl, 1, wx.ALL, 5)
        sizer.Add(proxy_sizer, 0, wx.EXPAND)

        # Per-feed text encoding overrides (issue #75). Blank means automatic
        # detection; a codec name (utf-8, windows-1251, koi8-r, ...) pins it.
        feed_enc_sizer = wx.BoxSizer(wx.HORIZONTAL)
        feed_enc_sizer.Add(
            wx.StaticText(general_panel, label=_("Feed encoding (blank = automatic, e.g. utf-8, windows-1251):")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )
        feed_enc_value = ""
        try:
            feed_enc_value = str(self._feed_settings.get("encoding") or "")
        except Exception:
            feed_enc_value = ""
        self.feed_encoding_ctrl = wx.TextCtrl(general_panel, value=feed_enc_value)
        self.feed_encoding_ctrl.SetName("Feed encoding")
        feed_enc_sizer.Add(self.feed_encoding_ctrl, 1, wx.ALL, 5)
        sizer.Add(feed_enc_sizer, 0, wx.EXPAND)

        fulltext_enc_sizer = wx.BoxSizer(wx.HORIZONTAL)
        fulltext_enc_sizer.Add(
            wx.StaticText(general_panel, label=_("Full text extraction encoding (blank = automatic):")),
            0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5,
        )
        fulltext_enc_value = ""
        try:
            fulltext_enc_value = str(self._feed_settings.get("fulltext_encoding") or "")
        except Exception:
            fulltext_enc_value = ""
        self.fulltext_encoding_ctrl = wx.TextCtrl(general_panel, value=fulltext_enc_value)
        self.fulltext_encoding_ctrl.SetName("Full text extraction encoding")
        fulltext_enc_sizer.Add(self.fulltext_encoding_ctrl, 1, wx.ALL, 5)
        sizer.Add(fulltext_enc_sizer, 0, wx.EXPAND)

        # Per-feed delete-behavior override. "Use global setting" leaves
        # feeds.delete_behavior NULL so the global setting applies. Kept last so
        # the dialog opens on Title rather than on this combo box.
        try:
            from core import db as _db
            self._feed_delete_behavior = _db.get_feed_delete_behavior(getattr(feed, "id", "") or "")
        except Exception:
            self._feed_delete_behavior = None
        sizer.Add(wx.StaticText(general_panel, label=_("When I delete an article from this feed:")), 0, wx.ALL, 5)
        del_row = wx.BoxSizer(wx.HORIZONTAL)
        self._feed_delete_choices = [
            (None, _("Use global setting")),
            ("deleted", _("Move it to Deleted Articles")),
            ("purge", _("Remove it permanently")),
            ("category", _("Move it to a category")),
        ]
        self.feed_delete_ctrl = wx.Choice(general_panel, choices=[lbl for _k, lbl in self._feed_delete_choices])
        self.feed_delete_ctrl.SetName("Delete behavior for this feed")
        del_row.Add(self.feed_delete_ctrl, 0, wx.ALL, 5)
        self.feed_delete_category_ctrl = wx.TextCtrl(general_panel)
        self.feed_delete_category_ctrl.SetName("Delete target category (full path)")
        self.feed_delete_category_ctrl.SetHint(_("Category / Path"))
        del_row.Add(self.feed_delete_category_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        sizer.Add(del_row, 0, wx.EXPAND)

        fd_kind, fd_category = filters_mod.parse_delete_behavior(self._feed_delete_behavior)
        self._feed_delete_category_identities = (
            [fd_category] if fd_category and fd_category != UNCATEGORIZED else []
        )
        if self._feed_delete_behavior is None:
            self.feed_delete_ctrl.SetSelection(0)
        else:
            self.feed_delete_ctrl.SetSelection(
                next((i for i, (k, _l) in enumerate(self._feed_delete_choices) if k == fd_kind), 0)
            )
        if fd_category:
            self.feed_delete_category_ctrl.SetValue(category_display_name(fd_category))
        self.feed_delete_ctrl.Bind(wx.EVT_CHOICE, lambda e: self._sync_feed_delete_category_enabled())
        self._sync_feed_delete_category_enabled()

        general_panel.SetSizer(sizer)
        notebook.AddPage(general_panel, _("General"))

        # Per-feed column override (article list columns): None = follow the global layout.
        self.columns_panel = ColumnLayoutPanel(
            notebook,
            layout=article_columns.feed_layout_from_settings(self._feed_settings),
            allow_inherit=True,
        )
        notebook.AddPage(self.columns_panel, _("List Headers"))

        outer.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        outer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        self.SetSizer(outer)
        self.Centre()

        # Fix tab order within the General page: Title -> URL -> Category ->
        # Refresh interval -> Headers -> Timeout -> Impersonate -> Proxy ->
        # Delete behavior -> Delete category. MoveAfterInTabOrder only works
        # between siblings, so the chain stops at the page boundary: OK/Cancel
        # are children of the dialog, and wx already tabs notebook -> buttons.
        self.title_ctrl.SetFocus()
        if self.url_ctrl.AcceptsFocus():
            self.url_ctrl.MoveAfterInTabOrder(self.title_ctrl)

        self.cat_ctrl.MoveAfterInTabOrder(self.url_ctrl)
        self.refresh_interval_ctrl.MoveAfterInTabOrder(self.cat_ctrl)
        self.headers_ctrl.MoveAfterInTabOrder(self.refresh_interval_ctrl)
        self.timeout_ctrl.MoveAfterInTabOrder(self.headers_ctrl)
        self.impersonate_ctrl.MoveAfterInTabOrder(self.timeout_ctrl)
        self.proxy_ctrl.MoveAfterInTabOrder(self.impersonate_ctrl)
        self.feed_encoding_ctrl.MoveAfterInTabOrder(self.proxy_ctrl)
        self.fulltext_encoding_ctrl.MoveAfterInTabOrder(self.feed_encoding_ctrl)
        self.feed_delete_ctrl.MoveAfterInTabOrder(self.fulltext_encoding_ctrl)
        self.feed_delete_category_ctrl.MoveAfterInTabOrder(self.feed_delete_ctrl)

        ok_btn = self.FindWindow(wx.ID_OK)
        cancel_btn = self.FindWindow(wx.ID_CANCEL)

        if ok_btn:
            ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        if cancel_btn and ok_btn:
            cancel_btn.MoveAfterInTabOrder(ok_btn)

    def _sync_feed_delete_category_enabled(self):
        idx = self.feed_delete_ctrl.GetSelection()
        kind = self._feed_delete_choices[idx][0] if idx >= 0 else None
        self.feed_delete_category_ctrl.Enable(kind == "category")

    def _feed_delete_behavior_setting(self):
        """Encode the per-feed delete override, or None to inherit the global."""
        idx = self.feed_delete_ctrl.GetSelection()
        kind = self._feed_delete_choices[idx][0] if idx >= 0 else None
        if kind is None:
            return None
        if kind == "category":
            category = normalize_category_input(
                self.feed_delete_category_ctrl.GetValue(),
                self._feed_delete_category_identities,
            )
            return f"category:{category}" if category else None
        return kind

    def on_ok(self, event):
        # Validate encoding overrides up front (issue #75): keep the dialog
        # open on an unknown codec name instead of silently persisting it.
        invalid = self._first_invalid_encoding_field()
        if invalid is not None:
            bad_value, ctrl = invalid
            wx.MessageBox(
                _("Unknown text encoding: %s. Use a Python codec name such as utf-8, windows-1251 or koi8-r, or leave the field blank for automatic detection.") % bad_value,
                _("Feed Properties"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            try:
                ctrl.SetFocus()
            except Exception:
                pass
            return
        self._save_feed_settings()
        try:
            from core import db as _db
            _db.set_feed_delete_behavior(
                getattr(self.feed, "id", "") or "", self._feed_delete_behavior_setting()
            )
        except Exception:
            logging.getLogger(__name__).debug("Failed to save per-feed delete behavior", exc_info=True)
        self.EndModal(wx.ID_OK)

    def _first_invalid_encoding_field(self):
        """Return (bad_value, ctrl) for the first unknown encoding override, else None."""
        import codecs as _codecs
        for ctrl in (self.feed_encoding_ctrl, self.fulltext_encoding_ctrl):
            try:
                value = (ctrl.GetValue() or "").strip()
            except Exception:
                continue
            if not value:
                continue
            try:
                _codecs.lookup(value)
            except (LookupError, TypeError, ValueError):
                return value, ctrl
        return None

    def _save_feed_settings(self):
        """Parse the per-feed HTTP override controls and persist them (issue #29)."""
        settings = dict(self._feed_settings) if isinstance(getattr(self, "_feed_settings", None), dict) else {}

        custom_headers = {}
        try:
            for line in (self.headers_ctrl.GetValue() or "").splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                name, value = line.split(":", 1)
                name = name.strip()
                if name:
                    custom_headers[name] = value.strip()
        except Exception:
            custom_headers = {}
        settings["custom_headers"] = custom_headers

        try:
            raw_timeout = (self.timeout_ctrl.GetValue() or "").strip()
            settings["timeout_seconds"] = int(raw_timeout) if raw_timeout else None
        except (ValueError, TypeError):
            settings["timeout_seconds"] = None

        try:
            sel = self.impersonate_ctrl.GetSelection()
            settings["impersonate"] = self._impersonate_values[sel] if 0 <= sel < len(self._impersonate_values) else "auto"
        except Exception:
            settings["impersonate"] = "auto"

        try:
            settings["proxy"] = (self.proxy_ctrl.GetValue() or "").strip()
        except Exception:
            settings["proxy"] = ""

        # Per-feed encoding overrides (issue #75). Stored lowercase; "" = automatic.
        try:
            settings["encoding"] = (self.feed_encoding_ctrl.GetValue() or "").strip().lower()
        except Exception:
            settings["encoding"] = ""
        try:
            settings["fulltext_encoding"] = (self.fulltext_encoding_ctrl.GetValue() or "").strip().lower()
        except Exception:
            settings["fulltext_encoding"] = ""

        try:
            sel = self.refresh_interval_ctrl.GetSelection()
            settings["refresh_interval_seconds"] = (
                self._refresh_interval_choices[sel][0]
                if 0 <= sel < len(self._refresh_interval_choices)
                else None
            )
        except Exception:
            settings["refresh_interval_seconds"] = None

        # None means "inherit the global layout" -- store it as such rather than
        # freezing today's global layout into this feed (article list columns).
        try:
            settings["columns"] = self.columns_panel.get_layout()
        except Exception:
            settings["columns"] = None

        try:
            from core import db as _db
            _db.set_feed_settings(getattr(self.feed, "id", "") or "", settings)
        except Exception:
            logging.getLogger(__name__).debug("Failed to save per-feed settings", exc_info=True)

    def get_data(self):
        title = ""
        url = ""
        category = ""
        try:
            title = (self.title_ctrl.GetValue() or "").strip()
        except Exception:
            title = ""
        try:
            url = (self.url_ctrl.GetValue() or "").strip()
        except Exception:
            url = ""
        try:
            category = normalize_category_input(
                self.cat_ctrl.GetValue(), self.category_identities
            )
        except Exception:
            category = ""
        return title, url, category


class FeedErrorsDialog(wx.Dialog):
    """Accessible viewer for feeds whose latest update attempt failed (issue #32).

    RSS feeds break over time (dead URLs, HTTP 404/500, timeouts, anti-bot
    blocks, invalid feed formats) and the app would otherwise give no signal —
    the user just sees no new articles and assumes the feed is quiet. This
    dialog lists every feed with a recorded error and, for each one, shows the
    feed name, the time of the last attempt, a consecutive-failure count (so a
    one-off network blip is distinguishable from a permanently broken feed), and
    the full error message. From here the user can refresh a feed to retry,
    copy the details, open Feed Properties to fix the URL or adjust settings, or
    remove the feed entirely.
    """

    def __init__(self, parent, errors, provider=None):
        super().__init__(
            parent,
            title=_("Feeds with Errors"),
            size=(840, 580),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._parent_frame = parent
        self._provider = provider
        self._errors = list(errors or [])
        self._busy = False

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.heading = wx.StaticText(self, label=self._heading_text())
        sizer.Add(self.heading, 0, wx.ALL, 8)

        # Report-view list: each row is one broken feed. NVDA reads every column
        # as the user arrows through, so the row itself conveys the essentials.
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.SetName("Feeds with errors")
        self.list.InsertColumn(0, _("Feed"), width=250)
        self.list.InsertColumn(1, _("Last attempt"), width=160)
        self.list.InsertColumn(2, _("Failures"), width=80)
        self.list.InsertColumn(3, _("Error"), width=320)
        sizer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        detail_label = wx.StaticText(self, label=_("Error &details:"))
        sizer.Add(detail_label, 0, wx.LEFT | wx.TOP, 8)
        self.detail = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 140),
        )
        self.detail.SetName("Error details")
        sizer.Add(self.detail, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(self, label=_("&Refresh Selected"))
        self.copy_btn = wx.Button(self, label=_("&Copy Details"))
        self.props_btn = wx.Button(self, label=_("Feed &Properties..."))
        self.remove_btn = wx.Button(self, label=_("Re&move Feed"))
        self.close_btn = wx.Button(self, wx.ID_CLOSE, "&Close")
        for b in (self.refresh_btn, self.copy_btn, self.props_btn, self.remove_btn):
            btn_sizer.Add(b, 0, wx.RIGHT, 6)
        btn_sizer.AddStretchSpacer()
        btn_sizer.Add(self.close_btn, 0)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(sizer)
        self.Centre()
        self.SetEscapeId(wx.ID_CLOSE)

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.list.Bind(wx.EVT_LIST_ITEM_FOCUSED, self.on_select)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_refresh)  # Enter retries
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        self.copy_btn.Bind(wx.EVT_BUTTON, self.on_copy)
        self.props_btn.Bind(wx.EVT_BUTTON, self.on_properties)
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove)
        self.close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

        self._populate()
        wx.CallAfter(self._focus_initial)

    # ── helpers ──────────────────────────────────────────────────────────
    def _heading_text(self) -> str:
        n = len(self._errors)
        if n == 0:
            return _("No feeds reported errors during their most recent update.")
        return ngettext(
            "{n} feed failed to update during its most recent attempt:",
            "{n} feeds failed to update during their most recent attempt:",
            n).format(n=n)

    @staticmethod
    def _format_timestamp(ts) -> str:
        if ts is None:
            return _("Unknown")
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
        except (ValueError, TypeError, OverflowError, OSError):
            return _("Unknown")

    @staticmethod
    def _one_line(text: str, limit: int = 220) -> str:
        collapsed = " ".join(str(text or "").split())
        if len(collapsed) > limit:
            collapsed = collapsed[: limit - 1].rstrip() + "…"
        return collapsed

    def _populate(self):
        self.list.DeleteAllItems()
        for err in self._errors:
            row = self.list.InsertItem(self.list.GetItemCount(), str(err.get("title") or "Untitled feed"))
            self.list.SetItem(row, 1, self._format_timestamp(err.get("last_error_at")))
            self.list.SetItem(row, 2, str(int(err.get("consecutive_failures") or 0)))
            self.list.SetItem(row, 3, self._one_line(err.get("last_error")))
        self.heading.SetLabel(self._heading_text())
        has_rows = bool(self._errors)
        for b in (self.refresh_btn, self.copy_btn, self.props_btn, self.remove_btn):
            b.Enable(has_rows)
        if not has_rows:
            self.detail.SetValue(
                _(
                    "No feeds reported errors during their most recent update attempt.\n\n"
                    "Feeds appear here automatically when an update fails (for example a "
                    "dead URL, an HTTP error, a timeout, or an invalid feed format)."
                )
            )

    def _selected_index(self) -> int:
        return self.list.GetFirstSelected()

    def _selected_error(self):
        idx = self._selected_index()
        if 0 <= idx < len(self._errors):
            return self._errors[idx]
        return None

    def _build_detail_text(self, err) -> str:
        failures = int(err.get("consecutive_failures") or 0)
        if failures <= 1:
            failures_line = _("1 failed attempt so far (this may be a one-off glitch).")
        else:
            failures_line = ngettext(
                "{n} consecutive failed attempt (likely a persistent problem).",
                "{n} consecutive failed attempts (likely a persistent problem).",
                failures).format(n=failures)
        last_success = err.get("last_success_at")
        title = err.get('title') or _("Untitled feed")
        url = err.get('url') or _("(unknown)")
        category = category_display_name(err.get('category') or UNCATEGORIZED)
        attempt = self._format_timestamp(err.get('last_error_at'))
        successful = self._format_timestamp(last_success) if last_success else _("No successful update recorded.")
        description = failures_line
        error = err.get('last_error') or _("Unknown error")
        return _(
            "Feed: {title}\n"
            "URL: {url}\n"
            "Category: {category}\n"
            "Last update attempt: {attempt}\n"
            "Last successful update: {successful}\n"
            "{description}\n\n"
            "Error:\n{error}"
        ).format(
            title=title,
            url=url,
            category=category,
            attempt=attempt,
            successful=successful,
            description=description,
            error=error
        )

    def on_select(self, event=None):
        err = self._selected_error()
        if err is not None:
            self.detail.SetValue(self._build_detail_text(err))
        if event is not None:
            event.Skip()

    def _focus_initial(self):
        if self._errors:
            self.list.SetFocus()
            self.list.Select(0)
            self.list.Focus(0)
        else:
            self.close_btn.SetFocus()

    def _select_row(self, idx: int):
        if not self._errors:
            self.detail.SetValue("")
            self.close_btn.SetFocus()
            return
        idx = max(0, min(idx, len(self._errors) - 1))
        self.list.SetFocus()
        self.list.Select(idx)
        self.list.Focus(idx)
        self.on_select()

    def _reload_errors(self):
        prov = self._provider or getattr(self._parent_frame, "provider", None)
        try:
            self._errors = list(prov.get_feed_errors()) if prov is not None else []
        except Exception:
            log.debug("Failed to reload feed errors", exc_info=True)
            self._errors = []
        self._populate()

    # ── actions ──────────────────────────────────────────────────────────
    def on_copy(self, event=None):
        err = self._selected_error()
        if err is None:
            return
        try:
            from gui.clipboard_utils import copy_text_to_clipboard
            copy_text_to_clipboard(self._build_detail_text(err))
        except Exception:
            log.debug("Failed to copy feed error details", exc_info=True)

    def on_refresh(self, event=None):
        if self._busy:
            return
        err = self._selected_error()
        if err is None:
            return
        feed_id = err.get("id")
        if not feed_id:
            return
        prior_index = self._selected_index()
        self._busy = True
        self.heading.SetLabel(_("Refreshing '{title}'...").format(title=err.get('title') or _("feed")))

        def worker():
            try:
                frame = self._parent_frame
                fn = getattr(frame, "_refresh_single_feed_thread", None)
                if callable(fn):
                    fn(feed_id)
                else:
                    prov = self._provider or getattr(frame, "provider", None)
                    if prov is not None:
                        prov.refresh_feed(feed_id)
            except Exception:
                log.debug("Refresh from errors dialog failed", exc_info=True)
            wx.CallAfter(self._after_refresh, feed_id, prior_index)

        threading.Thread(target=worker, daemon=True, name="errors-dialog-refresh").start()

    def _after_refresh(self, feed_id, prior_index):
        self._busy = False
        self._reload_errors()
        if not self._errors:
            # The feed was fixed and no others are broken.
            self.close_btn.SetFocus()
            return
        # Re-select the same feed if it still errors; otherwise land on the row
        # that now occupies its slot so NVDA announces the updated state.
        new_index = next((i for i, e in enumerate(self._errors) if e.get("id") == feed_id), None)
        self._select_row(new_index if new_index is not None else prior_index)

    def on_properties(self, event=None):
        err = self._selected_error()
        if err is None:
            return
        feed_id = err.get("id")
        if not feed_id:
            return
        frame = self._parent_frame
        fn = getattr(frame, "edit_feed_by_id", None)
        if not callable(fn):
            wx.MessageBox(
                _("Editing feed properties is not available here."),
                _("Not available"),
                wx.ICON_INFORMATION,
                self,
            )
            return
        try:
            fn(feed_id)
        except Exception:
            log.debug("Edit feed from errors dialog failed", exc_info=True)
        # The recorded error only clears on the next successful refresh, so the
        # list is unchanged; the user can now use Refresh Selected to retry.

    def on_remove(self, event=None):
        if self._busy:
            return
        err = self._selected_error()
        if err is None:
            return
        feed_id = err.get("id")
        if not feed_id:
            return
        title = err.get("title") or "this feed"
        if wx.MessageBox(
            f"Remove the feed “{title}”?\n\nThis deletes the feed and all of its articles.",
            _("Confirm Remove"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) != wx.YES:
            return
        frame = self._parent_frame
        fn = getattr(frame, "remove_feed_by_id", None)
        if callable(fn):
            try:
                fn(feed_id, title)
            except Exception:
                log.debug("Remove feed from errors dialog failed", exc_info=True)
        # The main window owns the asynchronous removal and tree refresh; close
        # so its state stays authoritative.
        self.EndModal(wx.ID_OK)


class FeedSearchDialog(wx.Dialog):
    _SEARCH_POLL_INTERVAL_S = 0.1
    _SEARCH_TOTAL_TIMEOUT_ALL_SOURCES_S = 60.0
    _SEARCH_TOTAL_TIMEOUT_SINGLE_SOURCE_S = 60.0
    _SOURCE_ALL = "__all__"
    _SOURCE_ALL_PODCAST = "__all_podcast__"
    _SOURCE_ALL_RSS = "__all_rss__"
    _PODCAST_SOURCE_KEYS = ["itunes", "gpodder", "fyyd", "podverse", "soundcloud", "mixcloud"]
    # NewsBlur's autocomplete is the primary feed-name directory (it searches
    # feed names AND addresses and needs no auth). Feedly is kept selectable
    # but is no longer one of the aggregated default sources, so no single
    # directory is relied on. Feedsearch + the local website scan cover
    # domain/site-name discovery.
    _RSS_SOURCE_KEYS = ["newsblur", "feedspot", "googlenews", "bingnews", "youtube", "soundcloud", "mixcloud", "reddit", "fediverse", "feedsearch", "blindrss"]
    _SOURCE_CHOICES = [
        ("All sources", _SOURCE_ALL),
        ("All podcast sources", _SOURCE_ALL_PODCAST),
        ("All RSS feed sources", _SOURCE_ALL_RSS),
        ("NewsBlur", "newsblur"),
        ("iTunes", "itunes"),
        ("gPodder", "gpodder"),
        ("fyyd", "fyyd"),
        ("Podverse", "podverse"),
        ("Feedspot", "feedspot"),
        ("Google News", "googlenews"),
        ("Bing News", "bingnews"),
        ("YouTube", "youtube"),
        ("SoundCloud", "soundcloud"),
        ("Mixcloud", "mixcloud"),
        ("Feedly", "feedly"),
        ("Reddit", "reddit"),
        ("Fediverse (all)", "fediverse"),
        ("Mastodon", "mastodon"),
        ("Bluesky", "bluesky"),
        ("PieFed", "piefed"),
        ("Lemmy/Kbin", "lemmy"),
        ("Feedsearch (URL or site name)", "feedsearch"),
        ("Website scan (URL or site name)", "blindrss"),
    ]

    @staticmethod
    def _merged_result_sort_key(item):
        """Keep broad Google News query feeds below direct feed-discovery results.

        Search providers run concurrently, so their queue-arrival order is not a relevance signal.
        An explicitly selected Google News search remains untouched; this key is used only by the
        combined All sources / All RSS views.  Preserve the existing YouTube-first convenience.
        """
        provider = str((item or {}).get("provider") or "").strip().lower()
        if provider == "youtube":
            return 0
        if provider == "google news":
            return 2
        return 1

    def __init__(self, parent):
        super().__init__(parent, title=_("Find a Podcast or RSS Feed"), size=(800, 600))
        
        self.selected_url = None
        self._threads = []
        self._stop_event = threading.Event()
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Search Box
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        input_sizer.Add(wx.StaticText(self, label=_("Search:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.ShowCancelButton(True)
        self.search_ctrl.SetName("Search for a podcast or RSS feed")
        self.search_ctrl.SetHint(_("Podcast name, topic, or site URL"))
        wx.CallAfter(self.search_ctrl.SetFocus)
        input_sizer.Add(self.search_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        input_sizer.Add(wx.StaticText(self, label=_("Source:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        source_labels = [label for label, _ in self._SOURCE_CHOICES]
        self.source_combo = wx.ComboBox(self, choices=source_labels, style=wx.CB_READONLY)
        self.source_combo.SetName("Search source")
        self.source_combo.SetSelection(0)
        input_sizer.Add(self.source_combo, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)

        self.search_btn = wx.Button(self, label=_("Search"))
        input_sizer.Add(self.search_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        sizer.Add(input_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Provider Status (optional, to show what's happening)
        self.status_lbl = wx.StaticText(self, label=_("Ready."))
        sizer.Add(self.status_lbl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # Results List
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.results_list.SetName("Search results")
        self.results_list.InsertColumn(0, _("Title"), width=350)
        self.results_list.InsertColumn(1, _("Provider"), width=120)
        self.results_list.InsertColumn(2, _("Details"), width=250)
        self.results_list.InsertColumn(3, _("URL"), width=0) # Hidden
        
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 5)

        # Attribution / Help
        help_sizer = wx.BoxSizer(wx.HORIZONTAL)
        help_sizer.Add(wx.StaticText(self, label=_("Sources: NewsBlur, iTunes, gPodder, fyyd, Podverse, YouTube, Feedspot, Google News, Bing News, Feedsearch, Website scan, Reddit, Fediverse (Lemmy/Kbin/Mastodon/Bluesky/PieFed). Feedly is available as an explicit source.")), 0, wx.ALL, 5)
        sizer.Add(help_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        
        # Buttons
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        
        self.SetSizer(sizer)
        self.Centre()
        
        # Bindings
        self.search_btn.Bind(wx.EVT_BUTTON, self.on_search)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self.on_search)
        self.results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self.results_data = [] # List of dicts: title, provider, detail, url

    def _on_char_hook(self, event):
        try:
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                self.EndModal(wx.ID_CANCEL)
                return
        except Exception:
            pass
        event.Skip()

    def on_close(self, event):
        self._stop_event.set()
        event.Skip()

    @staticmethod
    def _is_url_like_term(term):
        t = str(term or "").strip().lower()
        return bool("." in t or "://" in t or t.startswith("lbry:"))

    def _get_selected_source(self):
        try:
            label = str(self.source_combo.GetValue() or "").strip()
        except Exception:
            return ("All sources", self._SOURCE_ALL)

        for source_label, source_key in self._SOURCE_CHOICES:
            if source_label == label:
                return (source_label, source_key)
        return ("All sources", self._SOURCE_ALL)

    def _build_search_targets(self, term, source_key):
        all_targets = [
            ("NewsBlur", "newsblur", self._search_newsblur),
            ("iTunes", "itunes", self._search_itunes),
            ("gPodder", "gpodder", self._search_gpodder),
            ("fyyd", "fyyd", self._search_fyyd),
            ("Podverse", "podverse", self._search_podverse),
            ("Feedspot", "feedspot", self._search_feedspot),
            ("Google News", "googlenews", self._search_googlenews),
            ("Bing News", "bingnews", self._search_bingnews),
            ("YouTube", "youtube", self._search_youtube_channels),
            ("SoundCloud", "soundcloud", self._search_soundcloud),
            ("Mixcloud", "mixcloud", self._search_mixcloud),
            ("Reddit", "reddit", self._search_reddit),
            ("Fediverse", "fediverse", self._search_fediverse),
            ("Feedsearch", "feedsearch", self._search_feedsearch),
            ("BlindRSS", "blindrss", self._search_blindrss),
        ]
        # Feedly is still selectable on its own but excluded from the "all"
        # groups (NewsBlur is the primary directory now). Fediverse per-network
        # sources are likewise explicit-only.
        specific_targets = {
            "feedly": ("Feedly", "feedly", self._search_feedly),
            "mastodon": ("Mastodon", "mastodon", self._search_mastodon),
            "bluesky": ("Bluesky", "bluesky", self._search_bluesky),
            "piefed": ("PieFed", "piefed", self._search_piefed),
            "lemmy": ("Lemmy/Kbin", "lemmy", self._search_lemmy),
        }

        by_key = {key: (name, key, fn) for name, key, fn in all_targets}
        by_key.update(specific_targets)

        if source_key == self._SOURCE_ALL:
            target_keys = [key for _, key, _ in all_targets]
        elif source_key == self._SOURCE_ALL_PODCAST:
            target_keys = [key for _, key, _ in all_targets if key in self._PODCAST_SOURCE_KEYS]
        elif source_key == self._SOURCE_ALL_RSS:
            target_keys = [key for _, key, _ in all_targets if key in self._RSS_SOURCE_KEYS]
        elif source_key in by_key:
            target_keys = [source_key]
        else:
            target_keys = [key for _, key, _ in all_targets]

        url_like = self._is_url_like_term(term)
        single_word = bool(str(term or "").strip()) and " " not in str(term or "").strip()
        filtered = []
        for key in target_keys:
            name, _, fn = by_key[key]
            if key in ("feedsearch", "blindrss") and not url_like:
                # Both sources scan a website rather than a directory. When the
                # user picks one explicitly, always run it — the source guesses
                # "<term>.com" for bare site names (e.g. "techspot"). In the
                # grouped modes, run the local website scan for single-word
                # terms too, but keep the external Feedsearch service URL-gated.
                if source_key == key:
                    pass
                elif key == "blindrss" and single_word:
                    pass
                else:
                    continue
            filtered.append((name, fn))
        return filtered

    def on_search(self, event):
        term = (self.search_ctrl.GetValue() or "").strip()
        if not term:
            return

        source_label, source_key = self._get_selected_source()

        self.results_list.DeleteAllItems()
        self.results_data = []
        self._stop_event.clear()

        # Update UI
        self.search_ctrl.Disable()
        self.source_combo.Disable()
        self.search_btn.Disable()
        if source_key == self._SOURCE_ALL:
            self.status_lbl.SetLabel(_("Searching all sources..."))
        else:
            self.status_lbl.SetLabel(f"Searching {source_label}...")

        # Start unified search thread
        threading.Thread(target=self._unified_search_manager, args=(term, source_key), daemon=True).start()

    def _unified_search_manager(self, term, source_key):
        from queue import Queue
        from queue import Empty

        results_queue = Queue()
        active_threads = []

        # Helper to launch a provider thread
        def launch(target, name):
            t = threading.Thread(target=target, args=(term, results_queue), name=name, daemon=True)
            t.start()
            active_threads.append(t)

        for provider_name, target in self._build_search_targets(term, source_key):
            launch(target, provider_name)

        all_results = []
        seen_urls = set()

        def _consume_queue_entry(provider, items):
            for item in (items or []):
                url = str(item.get("url", "") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append({
                    "title": item.get("title", url),
                    "provider": provider,
                    "detail": item.get("detail", ""),
                    "url": url
                })

        try:
            poll_interval = max(0.05, min(1.0, float(getattr(self, "_SEARCH_POLL_INTERVAL_S", 0.1) or 0.1)))
        except Exception:
            poll_interval = 0.1
        try:
            if source_key == self._SOURCE_ALL:
                total_timeout = float(getattr(self, "_SEARCH_TOTAL_TIMEOUT_ALL_SOURCES_S", 60.0) or 60.0)
            else:
                total_timeout = float(getattr(self, "_SEARCH_TOTAL_TIMEOUT_SINGLE_SOURCE_S", 60.0) or 60.0)
            total_timeout = max(0.5, min(90.0, total_timeout))
        except Exception:
            total_timeout = 60.0

        deadline = time.monotonic() + total_timeout
        while True:
            if self._stop_event.is_set():
                return

            now = time.monotonic()
            if now >= deadline:
                break

            alive = any(t.is_alive() for t in active_threads)
            if not alive and results_queue.empty():
                break

            wait_s = min(poll_interval, max(0.01, deadline - now))
            try:
                provider, items = results_queue.get(timeout=wait_s)
                _consume_queue_entry(provider, items)
            except Empty:
                pass
            except Exception:
                pass

        # Final best-effort drain for late-arriving completed providers.
        while True:
            try:
                provider, items = results_queue.get_nowait()
                _consume_queue_entry(provider, items)
            except Empty:
                break
            except Exception:
                break

        # Use class-level fallbacks here: lightweight test/search hosts can
        # intentionally implement only the selected-source constants and the
        # manager method itself.
        all_rss_source = getattr(self, "_SOURCE_ALL_RSS", FeedSearchDialog._SOURCE_ALL_RSS)
        if source_key in (self._SOURCE_ALL, all_rss_source) and all_results:
            # Google News creates a broad query subscription rather than finding the publisher's
            # own feed.  Do not let its typically fast response jump ahead of direct matches.
            all_results.sort(key=FeedSearchDialog._merged_result_sort_key)

        if self._stop_event.is_set():
            return
        try:
            wx.CallAfter(self._on_search_complete, all_results)
        except Exception:
            pass

    # --- Provider Implementations ---

    def _search_itunes(self, term, queue):
        try:
            import urllib.parse
            url = f"https://itunes.apple.com/search?media=podcast&term={urllib.parse.quote(term)}"
            resp = utils.safe_requests_get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data.get("results", []):
                    results.append({
                        "title": item.get("collectionName", "Unknown"),
                        "detail": item.get("artistName", "Unknown"),
                        "url": item.get("feedUrl")
                    })
                queue.put(("iTunes", results))
        except Exception:
            pass

    def _search_gpodder(self, term, queue):
        try:
            import urllib.parse
            url = f"https://gpodder.net/search.json?q={urllib.parse.quote(term)}"
            resp = utils.safe_requests_get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for it in data:
                    if not isinstance(it, dict): continue
                    results.append({
                        "title": it.get("title") or it.get("url"),
                        "detail": it.get("author") or "",
                        "url": it.get("url")
                    })
                queue.put(("gPodder", results))
        except Exception:
            pass

    def _search_fyyd(self, term, queue):
        try:
            import urllib.parse
            url = f"https://api.fyyd.de/0.2/search/podcast?term={urllib.parse.quote(term)}&count=20"
            resp = utils.safe_requests_get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for it in data.get("data", []):
                    if not isinstance(it, dict): continue
                    feed_url = it.get("xmlURL")
                    if not feed_url: continue
                    results.append({
                        "title": it.get("title") or feed_url,
                        "detail": it.get("author") or it.get("subtitle") or "",
                        "url": feed_url
                    })
                queue.put(("fyyd", results))
        except Exception:
            pass

    def _search_podverse(self, term, queue):
        try:
            import urllib.parse
            url = f"https://api.podverse.fm/api/v1/podcast?searchTitle={urllib.parse.quote(term)}"
            resp = utils.safe_requests_get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                # Response shape: [ [items...], total_count ]
                items = data[0] if isinstance(data, list) and data else []
                results = []
                for it in items:
                    if not isinstance(it, dict): continue
                    feed_url = ""
                    for fu in (it.get("feedUrls") or []):
                        if isinstance(fu, dict) and fu.get("url"):
                            feed_url = fu["url"]
                            break
                    if not feed_url: continue
                    results.append({
                        "title": it.get("title") or feed_url,
                        "detail": it.get("subtitle") or it.get("description") or "",
                        "url": feed_url
                    })
                queue.put(("Podverse", results))
        except Exception:
            pass

    def _search_feedspot(self, term, queue):
        # Feedspot has no public search API (search requires a logged-in
        # account), but its curated topic pages are public and list real feed
        # URLs, so map the search term onto the topic-page URL scheme.
        try:
            import re as _re
            from urllib.parse import urlparse as _urlparse
            from bs4 import BeautifulSoup

            slug = _re.sub(r"[^a-z0-9]+", "_", str(term or "").strip().lower()).strip("_")
            if not slug:
                return
            url = f"https://rss.feedspot.com/{slug}_rss_feeds/"
            resp = utils.safe_requests_get(url, timeout=12)
            if resp.status_code != 200:
                return
            soup = BeautifulSoup(resp.text or "", "html.parser")
            results = []
            seen = set()
            pending_title = ""
            # Each entry is a title anchor inside a .feed_heading element
            # followed by the feed-URL anchor (class "ext" without
            # "extdomain"); pair them in document order. Every entry sits in
            # the initial HTML (even 200+ item pages), though some only show
            # their feed URL to logged-in users and are skipped.
            for a in soup.find_all("a", href=True):
                if a.find_parent(class_="feed_heading") is not None:
                    pending_title = a.get_text(strip=True)
                    continue
                classes = a.get("class") or []
                if "ext" not in classes or "extdomain" in classes:
                    continue
                href = str(a.get("href") or "").strip()
                host = str(_urlparse(href).netloc or "").lower()
                if not host or host.endswith("feedspot.com") or href in seen:
                    continue
                seen.add(href)
                results.append({
                    "title": pending_title or host,
                    "detail": host,
                    "url": href,
                })
                pending_title = ""
                if len(results) >= 150:
                    break
            if results:
                queue.put(("Feedspot", results))
        except Exception:
            pass

    _GOOGLE_NEWS_TOPICS = {
        "world": "WORLD",
        "nation": "NATION",
        "national": "NATION",
        "business": "BUSINESS",
        "technology": "TECHNOLOGY",
        "tech": "TECHNOLOGY",
        "entertainment": "ENTERTAINMENT",
        "science": "SCIENCE",
        "sports": "SPORTS",
        "sport": "SPORTS",
        "health": "HEALTH",
    }

    def _search_googlenews(self, term, queue):
        # Google News serves keyless RSS feeds for any query (and for its
        # topic sections), so offer them as subscribable results directly.
        try:
            import urllib.parse
            t = str(term or "").strip()
            if not t:
                return
            results = [{
                "title": f"Google News: {t}",
                "detail": _("News search feed"),
                "url": "https://news.google.com/rss/search?q="
                       + urllib.parse.quote(t) + "&hl=en-US&gl=US&ceid=US:en",
            }]
            topic = self._GOOGLE_NEWS_TOPICS.get(t.lower())
            if topic:
                results.append({
                    "title": f"Google News: {topic.capitalize()} headlines",
                    "detail": _("News topic feed"),
                    "url": f"https://news.google.com/rss/headlines/section/topic/{topic}"
                           "?hl=en-US&gl=US&ceid=US:en",
                })
            queue.put(("Google News", results))
        except Exception:
            pass

    def _search_bingnews(self, term, queue):
        # Bing News serves a keyless RSS feed for any query via format=rss.
        try:
            import urllib.parse
            t = str(term or "").strip()
            if not t:
                return
            queue.put(("Bing News", [{
                "title": f"Bing News: {t}",
                "detail": _("News search feed"),
                "url": "https://www.bing.com/news/search?q="
                       + urllib.parse.quote(t) + "&format=rss",
            }]))
        except Exception:
            pass

    def _search_feedly(self, term, queue):
        try:
            import urllib.parse
            url = f"https://cloud.feedly.com/v3/search/feeds?q={urllib.parse.quote(term)}"
            resp = utils.safe_requests_get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                items = data.get("results", [])
                for it in items:
                    feed_id = it.get("feedId")
                    if feed_id and feed_id.startswith("feed/"):
                        results.append({
                            "title": it.get("title") or feed_id[5:],
                            "detail": it.get("description") or "Feedly",
                            "url": feed_id[5:]
                        })
                queue.put(("Feedly", results))
        except Exception:
            pass

    def _search_youtube_channels(self, term, queue):
        try:
            results = list(search_youtube_feeds(term, limit=100, timeout=15) or [])
            if results:
                queue.put(("YouTube", results))
        except Exception:
            pass

    def _search_soundcloud(self, term, queue):
        try:
            results = list(search_soundcloud_feeds(term, limit=30, timeout=15) or [])
            if results:
                queue.put(("SoundCloud", results))
        except Exception:
            pass

    def _search_mixcloud(self, term, queue):
        try:
            results = list(search_mixcloud_feeds(term, limit=30, timeout=15) or [])
            if results:
                queue.put(("Mixcloud", results))
        except Exception:
            pass

    def _search_mastodon(self, term, queue):
        try:
            results = list(search_mastodon_feeds(term, limit=12, timeout=15) or [])
            if results:
                queue.put(("Mastodon", results))
        except Exception:
            pass

    def _search_bluesky(self, term, queue):
        try:
            results = list(search_bluesky_feeds(term, limit=12, timeout=15) or [])
            if results:
                queue.put(("Bluesky", results))
        except Exception:
            pass

    def _search_piefed(self, term, queue):
        try:
            results = list(search_piefed_feeds(term, limit=12, timeout=15) or [])
            if results:
                queue.put(("PieFed", results))
        except Exception:
            pass

    def _search_lemmy_items(self, term):
        import urllib.parse

        results = []
        # Query lemmy.world as a gateway to the Fediverse
        url = f"https://lemmy.world/api/v3/search?q={urllib.parse.quote(term)}&type_=Communities&sort=TopAll&limit=15"
        headers = {"User-Agent": "BlindRSS/1.0"}
        resp = utils.safe_requests_get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return results

        data = resp.json()
        # Structure: { "communities": [ { "community": { ... }, "counts": { ... } } ] }
        comms = data.get("communities", [])
        for c in comms:
            comm = c.get("community", {})
            counts = c.get("counts", {})

            title = comm.get("title")
            name = comm.get("name")
            actor_id = comm.get("actor_id")

            if not actor_id:
                continue

            # Actor ID is usually community URL: https://instance/c/name or https://instance/m/name.
            rss_url = ""
            provider_label = "Fediverse"

            if "/c/" in actor_id:
                # Lemmy actor URL to RSS URL.
                base = actor_id.split("/c/")[0]
                comm_name = actor_id.split("/c/")[1]
                rss_url = f"{base}/feeds/c/{comm_name}.xml"
                provider_label = "Lemmy"
            elif "/m/" in actor_id:
                # Kbin actor URL to RSS URL.
                rss_url = f"{actor_id}/rss"
                provider_label = "Kbin"
            else:
                continue

            subs = counts.get("subscribers")
            desc = f"{name} ({subs} subs)" if subs else name

            results.append({
                "title": title or name,
                "detail": f"{provider_label} - {desc}",
                "url": rss_url
            })
        return results

    def _search_lemmy(self, term, queue):
        try:
            results = list(self._search_lemmy_items(term) or [])
            if results:
                queue.put(("Lemmy/Kbin", results))
        except Exception:
            pass

    def _search_newsblur(self, term, queue):
        # NewsBlur's public discover autocomplete searches feed names AND feed
        # addresses (falling back to a DB search when its index is empty),
        # needs no authentication, and returns up to ~20 feeds with real feed
        # URLs. This is BlindRSS's primary feed-name directory.
        try:
            import urllib.parse
            url = (
                "https://www.newsblur.com/discover/autocomplete?"
                f"term={urllib.parse.quote(term)}&v=2"
            )
            resp = utils.safe_requests_get(url, timeout=10)
            if resp.status_code != 200:
                return
            data = resp.json()
            # v2 returns {"feeds": [...]}; the older endpoint returned a bare
            # list. Accept either so a response-shape change can't break search.
            if isinstance(data, dict):
                feeds = data.get("feeds") or []
            elif isinstance(data, list):
                feeds = data
            else:
                feeds = []

            results = []
            seen = set()
            for it in feeds:
                if not isinstance(it, dict):
                    continue
                # "value" is the feed address (URL); "id" is NewsBlur's internal
                # numeric id, which we cannot subscribe to without auth.
                feed_url = str(it.get("value") or it.get("address") or "").strip()
                if not feed_url or feed_url.isdigit() or "://" not in feed_url:
                    continue
                if feed_url in seen:
                    continue
                seen.add(feed_url)
                tagline = str(it.get("tagline") or "").strip()
                subs = it.get("num_subscribers")
                detail = tagline
                if isinstance(subs, int) and subs > 0:
                    detail = f"{tagline} ({subs} subscribers)".strip() if tagline else f"{subs} subscribers"
                results.append({
                    "title": str(it.get("label") or feed_url).strip(),
                    "detail": detail or "NewsBlur",
                    "url": feed_url,
                })
                if len(results) >= 20:
                    break
            if results:
                queue.put(("NewsBlur", results))
        except Exception:
            pass

    def _search_reddit(self, term, queue):
        try:
            import urllib.parse
            # Search subreddits
            url = f"https://www.reddit.com/subreddits/search.json?q={urllib.parse.quote(term)}&limit=10"
            headers = {"User-Agent": "BlindRSS/1.0"}
            resp = utils.safe_requests_get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                # Reddit API structure: data -> children -> [ { data: { display_name, public_description, subscribers, ... } } ]
                children = data.get("data", {}).get("children", [])
                for child in children:
                    d = child.get("data", {})
                    name = d.get("display_name")
                    if not name: continue
                    
                    # Construct RSS URL
                    rss_url = f"https://www.reddit.com/r/{name}/.rss"
                    desc = d.get("public_description") or d.get("title") or f"r/{name}"
                    subs = d.get("subscribers")
                    if subs:
                        desc = f"{desc} ({subs} subs)"
                        
                    results.append({
                        "title": f"r/{name}",
                        "detail": desc,
                        "url": rss_url
                    })
                queue.put(("Reddit", results))
        except Exception:
            pass

    def _search_fediverse(self, term, queue):
        all_results = []
        seen_urls = set()

        def _extend(items):
            for item in (items or []):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_results.append(item)

        try:
            _extend(search_mastodon_feeds(term, limit=12, timeout=15))
        except Exception:
            pass
        try:
            _extend(search_bluesky_feeds(term, limit=12, timeout=15))
        except Exception:
            pass
        try:
            _extend(search_piefed_feeds(term, limit=12, timeout=15))
        except Exception:
            pass

        try:
            _extend(self._search_lemmy_items(term))
        except Exception:
            pass

        if all_results:
            queue.put(("Fediverse", all_results))

    @staticmethod
    def _site_scan_targets(term):
        """Normalize a search term into website URLs worth scanning for feeds.

        Full URLs pass through, bare domains get https://, and single-word
        site names are guessed as <name>.com (the "techspot" case — the site
        has a feed at /backend.xml that no directory indexes).
        """
        t = str(term or "").strip()
        if not t:
            return []
        if "://" in t:
            return [t]
        if " " not in t and "." in t:
            return ["https://" + t]
        if " " not in t:
            slug = re.sub(r"[^a-z0-9-]", "", t.lower())
            if slug:
                return [f"https://{slug}.com"]
        return []

    @staticmethod
    def _fetch_feed_title(feed_url, timeout=8):
        """Best-effort feed title so results read as names, not raw URLs."""
        try:
            resp = utils.safe_requests_get(feed_url, timeout=timeout)
            if int(getattr(resp, "status_code", 0) or 0) != 200:
                return ""
            import feedparser
            parsed = feedparser.parse(resp.text or "")
            return str(getattr(parsed.feed, "title", "") or "").strip()
        except Exception:
            return ""

    def _search_feedsearch(self, term, queue):
        try:
            import urllib.parse
            t = str(term or "").strip()
            if t and "://" not in t and "." not in t and " " not in t:
                # Bare site name (explicit source selection): guess <name>.com.
                t = re.sub(r"[^a-z0-9-]", "", t.lower()) + ".com"
            url = f"https://feedsearch.dev/api/v1/search?url={urllib.parse.quote(t)}"
            resp = utils.safe_requests_get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for it in data:
                    results.append({
                        "title": it.get("title") or it.get("url"),
                        "detail": it.get("site_name", "Feedsearch"),
                        "url": it.get("url")
                    })
                queue.put(("Feedsearch", results))
        except Exception:
            pass

    def _search_blindrss(self, term, queue):
        # Local website scan: fetch the site itself and discover its feeds
        # (link rel=alternate, on-page links, well-known paths like /feed and
        # /backend.xml, with WAF-impersonation retries). The only source that
        # can surface feeds no directory indexes — e.g. techspot.com/backend.xml.
        try:
            from core.discovery import discover_feeds

            candidates = []
            for target in self._site_scan_targets(term):
                try:
                    candidates = discover_feeds(target)
                except Exception:
                    candidates = []
                if candidates:
                    break

            results = []
            seen = set()
            for c in candidates:
                if not c or c in seen:
                    continue
                seen.add(c)
                # Titles make results readable for screen readers; cap the
                # extra fetches so a long candidate list stays fast.
                title = self._fetch_feed_title(c) if len(results) < 5 else ""
                results.append({
                    "title": title or c,
                    "detail": "Website scan",
                    "url": c
                })
            if results:
                queue.put(("BlindRSS", results))

        except Exception:
            pass


    def _on_search_complete(self, results):
        # Dialog may have been closed while background search threads were running.
        if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
            return

        try:
            self.search_ctrl.Enable()
            self.search_btn.Enable()
            if getattr(self, "source_combo", None):
                self.source_combo.Enable()
            self.status_lbl.SetLabel(f"Found {len(results)} results.")
            self.search_ctrl.SetFocus()
        except Exception:
            # wx raises when the underlying C++ widgets were already destroyed.
            return

        self.results_data = results

        try:
            for i, item in enumerate(self.results_data):
                idx = self.results_list.InsertItem(i, item["title"])
                self.results_list.SetItem(idx, 1, item["provider"])
                self.results_list.SetItem(idx, 2, item["detail"])
        except Exception:
            return

    def on_item_activated(self, event):
        # Select item and close
        try:
            self._stop_event.set()
        except Exception:
            pass
        self.EndModal(wx.ID_OK)

    def get_selected_url(self):
        # Check selection
        idx = self.results_list.GetFirstSelected()
        if idx != -1:
            return self.results_data[idx]["url"]
        return None


class YtdlpGlobalSearchDialog(wx.Dialog):
    _ALL_SITES_TOKEN = "__all__"
    _ADULT_ALL_TOKEN = "__adult__"
    _SEARCH_CONCURRENCY = 8
    _PER_SITE_LIMIT = 80
    _LOAD_MORE_STEP = 80
    _PER_SITE_TIMEOUT_S = 12
    _TITLE_ENRICH_CONCURRENCY = 2
    _TITLE_ENRICH_TIMEOUT_S = 10
    # Quick title lookups are a single lightweight HTTP GET (YouTube oEmbed /
    # Rokfin public API) — purely network-bound, so a wide pool is cheap and
    # makes placeholder rows resolve to real titles almost immediately.
    _QUICK_TITLE_ENRICH_CONCURRENCY = 16
    _QUICK_TITLE_ENRICH_TIMEOUT_S = 4
    _RESULTS_REFRESH_THROTTLE_MS = 200
    _RESULTS_REFRESH_THROTTLE_FOCUSED_MS = 500
    _RESULTS_REFRESH_NAV_COOLDOWN_MS = 1200
    _TITLE_ENRICH_WORKER_THREADS = 16
    _TITLE_ENRICH_HEAVY_WORKER_THREADS = 2
    _DEFAULT_SORT_COLUMN = None  # None => default (mainstream-first then arrival)
    _DEFAULT_SORT_DESC = False
    _MAINSTREAM_SITE_PRIORITY = {
        "ytsearch": 0,
        "youtube": 0,
        "scsearch": 1,
        "soundcloud": 1,
        "gvsearch": 2,
        "yvsearch": 2,
        "bilisearch": 3,
        "vimeosearch": 4,
        "tiktoksearch": 4,
        "nicosearch": 5,
        "nicosearchdate": 5,
    }

    def __init__(self, parent):
        super().__init__(parent, title=_("Video Search"), size=(980, 680))

        # Resolve the config manager from the owning frame so adult sites can be
        # gated behind the "Enable adult sites in Video Search" setting.
        self._config_manager = None
        try:
            self._config_manager = getattr(parent, "config_manager", None)
        except Exception:
            self._config_manager = None

        self._stop_event = threading.Event()
        self._search_thread = None
        self._search_running = False
        self._site_rows = []
        self._safe_site_rows = []
        self._adult_site_rows = []
        self._scope_values = [self._ALL_SITES_TOKEN]
        self._filter_values = [self._ALL_SITES_TOKEN]
        self._all_results = []
        self._visible_results = []
        self._seen_result_keys = set()
        # Cross-site dedupe: canonical content key -> the kept (best) result dict.
        self._result_by_dedupe_key = {}
        self._completed_sites = 0
        self._total_sites = 0
        self._search_generation = 0
        self._result_arrival_counter = 0
        self._title_enrich_pending = set()
        self._title_enrich_heavy_pending = set()
        self._title_enrich_lock = threading.Lock()
        self._title_enrich_sem = threading.BoundedSemaphore(self._TITLE_ENRICH_CONCURRENCY)
        self._quick_title_enrich_sem = threading.BoundedSemaphore(self._QUICK_TITLE_ENRICH_CONCURRENCY)
        self._title_enrich_queue = queue.Queue()
        self._title_enrich_heavy_queue = queue.Queue()
        self._title_enrich_workers = []
        self._title_enrich_heavy_workers = []
        self._title_enrich_url_cache = {}
        self._title_enrich_url_cache_lock = threading.Lock()
        self._results_refresh_later = None
        self._dialog_nav_ts = 0.0
        self._results_list_nav_ts = 0.0
        self._applying_results_refresh = False
        self._last_search_term = ""
        self._last_search_sites = []
        self._last_search_per_site_limit = 0
        self._sort_column = self._DEFAULT_SORT_COLUMN
        self._sort_desc = self._DEFAULT_SORT_DESC

        root = wx.BoxSizer(wx.VERTICAL)

        query_row = wx.BoxSizer(wx.HORIZONTAL)
        query_row.Add(wx.StaticText(self, label=_("Search:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.ShowCancelButton(True)
        self.search_ctrl.SetName("Video search")
        self.search_ctrl.SetHint(_("Search videos across sites"))
        query_row.Add(self.search_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.search_btn = wx.Button(self, label=_("Search"))
        query_row.Add(self.search_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.load_more_btn = wx.Button(self, label=_("Load More Results (+80/site)"))
        self.load_more_btn.Disable()
        query_row.Add(self.load_more_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        root.Add(query_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        opts_row = wx.BoxSizer(wx.HORIZONTAL)
        opts_row.Add(wx.StaticText(self, label=_("Search Sites:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.scope_choice = wx.Choice(self)
        self.scope_choice.SetName("Search sites")
        opts_row.Add(self.scope_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        opts_row.Add(wx.StaticText(self, label=_("Filter Results:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.filter_choice = wx.Choice(self)
        self.filter_choice.SetName("Filter results by site")
        opts_row.Add(self.filter_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        opts_row.Add(wx.StaticText(self, label=_("Sort by:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        # Maps combo positions to the existing _sort_column machinery:
        # None = default relevance order (mainstream-first, then arrival).
        self._sort_choice_columns = [None, 0, 1, 3]
        self.sort_choice = wx.Choice(self)
        self.sort_choice.SetName("Sort results")
        for label in (_("Relevance"), _("Title"), _("Site"), _("Plays")):
            self.sort_choice.Append(label)
        self.sort_choice.SetSelection(0)
        opts_row.Add(self.sort_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        root.Add(opts_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        self.status_lbl = wx.StaticText(
            self,
            label=_("Ready."),
        )
        try:
            self.status_lbl.SetToolTip(
                f"yt-dlp global search (max {self._SEARCH_CONCURRENCY} concurrent)"
            )
        except Exception:
            pass

        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        try:
            self.results_list.SetName("Search results")
        except Exception:
            pass
        self.results_list.InsertColumn(0, _("Title"), width=340)
        self.results_list.InsertColumn(1, _("Site"), width=140)
        self.results_list.InsertColumn(2, _("Kind"), width=90)
        self.results_list.InsertColumn(3, _("Plays"), width=100)
        self.results_list.InsertColumn(4, _("Details"), width=220)
        self.results_list.InsertColumn(5, _("URL"), width=0)  # Hidden storage column
        root.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 5)

        action_row = wx.BoxSizer(wx.HORIZONTAL)
        self.close_btn = wx.Button(self, wx.ID_CLOSE, _("Close"))
        action_row.AddStretchSpacer(1)
        action_row.Add(self.close_btn, 0, wx.ALL, 5)
        root.Add(action_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        # Keep dynamic status after focusable controls so it doesn't become the
        # accessible label for the results list while it updates during search.
        root.Add(self.status_lbl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.SetSizer(root)
        self.Centre()
        wx.CallAfter(self.search_ctrl.SetFocus)

        self._refresh_site_choices()
        self._update_action_buttons()
        self._start_title_enrich_workers()

        self.search_btn.Bind(wx.EVT_BUTTON, self.on_search)
        self.load_more_btn.Bind(wx.EVT_BUTTON, self.on_load_more)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self.on_search)
        self.scope_choice.Bind(wx.EVT_CHOICE, self.on_scope_changed)
        self.filter_choice.Bind(wx.EVT_CHOICE, self.on_filter_changed)
        self.sort_choice.Bind(wx.EVT_CHOICE, self.on_sort_choice_changed)
        self.results_list.Bind(wx.EVT_LIST_COL_CLICK, self.on_results_col_click)
        self.results_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_result_selected)
        self.results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_result_activated)
        self.results_list.Bind(wx.EVT_CONTEXT_MENU, self.on_results_context_menu)
        self.close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.Close())
        self.Bind(wx.EVT_CHAR_HOOK, self.on_dialog_char_hook)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def on_close(self, event):
        try:
            self._stop_event.set()
        except Exception:
            pass
        try:
            if getattr(self, "_results_refresh_later", None):
                self._results_refresh_later.Stop()
        except Exception:
            pass
        try:
            self._unregister_player_status_callback()
        except Exception:
            pass
        event.Skip()

    def on_dialog_char_hook(self, event):
        try:
            key = event.GetKeyCode()
            if key == wx.WXK_ESCAPE:
                self.Close()
                return
            if bool(getattr(self, "_search_running", False)):
                nav_keys = {
                    wx.WXK_TAB,
                    wx.WXK_UP,
                    wx.WXK_DOWN,
                    wx.WXK_LEFT,
                    wx.WXK_RIGHT,
                    wx.WXK_PAGEUP,
                    wx.WXK_PAGEDOWN,
                    wx.WXK_HOME,
                    wx.WXK_END,
                }
                if key in nav_keys:
                    self._dialog_nav_ts = time.monotonic()
        except Exception:
            pass
        try:
            event.Skip()
        except Exception:
            pass

    def _start_title_enrich_workers(self) -> None:
        if getattr(self, "_title_enrich_workers", None):
            return
        workers = []
        try:
            count = max(1, int(self._TITLE_ENRICH_WORKER_THREADS))
        except Exception:
            count = 4
        for i in range(count):
            t = threading.Thread(
                target=self._title_enrich_queue_worker_loop,
                name=f"yt-title-enrich-{i+1}",
                daemon=True,
            )
            t.start()
            workers.append(t)
        self._title_enrich_workers = workers

        heavy_workers = []
        try:
            heavy_count = max(1, int(self._TITLE_ENRICH_HEAVY_WORKER_THREADS))
        except Exception:
            heavy_count = 2
        for i in range(heavy_count):
            t = threading.Thread(
                target=self._title_enrich_heavy_queue_worker_loop,
                name=f"yt-title-enrich-heavy-{i+1}",
                daemon=True,
            )
            t.start()
            heavy_workers.append(t)
        self._title_enrich_heavy_workers = heavy_workers

    def _title_enrich_queue_worker_loop(self) -> None:
        while True:
            try:
                if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
                    return
            except Exception:
                pass
            try:
                job = self._title_enrich_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if not isinstance(job, tuple) or len(job) != 3:
                    continue
                key, url, generation = job
                self._title_enrich_quick_stage(str(key or ""), str(url or ""), int(generation or 0))
            except Exception:
                pass
            finally:
                try:
                    self._title_enrich_queue.task_done()
                except Exception:
                    pass

    def _title_enrich_heavy_queue_worker_loop(self) -> None:
        while True:
            try:
                if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
                    return
            except Exception:
                pass
            try:
                job = self._title_enrich_heavy_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if not isinstance(job, tuple) or len(job) != 3:
                    continue
                key, url, generation = job
                self._title_enrich_heavy_stage(str(key or ""), str(url or ""), int(generation or 0))
            except Exception:
                pass
            finally:
                try:
                    self._title_enrich_heavy_queue.task_done()
                except Exception:
                    pass

    def _has_last_search(self) -> bool:
        return bool(str(getattr(self, "_last_search_term", "") or "").strip() and list(getattr(self, "_last_search_sites", []) or []))

    def _is_current_search_generation(self, generation: int) -> bool:
        try:
            return int(generation) == int(getattr(self, "_search_generation", 0) or 0)
        except Exception:
            return False

    def _item_needs_heavy_enrichment(self, item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        if not str(item.get("url") or "").strip():
            return False
        if self._title_needs_enrichment(item):
            return True
        native = str(item.get("native_subscribe_url") or "").strip()
        source = str(item.get("source_subscribe_url") or "").strip()
        return not (native or source)

    def _update_load_more_button(self) -> None:
        try:
            enabled = (not bool(getattr(self, "_search_running", False))) and self._has_last_search()
            self.load_more_btn.Enable(bool(enabled))
        except Exception:
            pass

    def _result_key_for_item(self, item: dict) -> str:
        site_id = str(item.get("site_id") or "").strip()
        url = str(item.get("url") or "").strip()
        return f"{site_id}|{url}" if site_id else url

    def _is_results_list_focused(self) -> bool:
        try:
            return wx.Window.FindFocus() == self.results_list
        except Exception:
            return False

    def _find_visible_result_index_by_key(self, key: str) -> int:
        if not key:
            return -1
        try:
            for i, item in enumerate(self._visible_results or []):
                if self._result_key_for_item(item) == key:
                    return int(i)
        except Exception:
            return -1
        return -1

    def _update_visible_result_row_title(self, key: str) -> bool:
        idx = self._find_visible_result_index_by_key(key)
        if idx < 0:
            return False
        try:
            if idx >= int(self.results_list.GetItemCount()):
                return False
        except Exception:
            return False
        try:
            item = self._visible_results[idx]
        except Exception:
            return False
        try:
            self.results_list.SetItem(idx, 0, str(item.get("title") or ""))
            return True
        except Exception:
            return False

    def _title_needs_enrichment(self, item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if bool(item.get("_title_is_fallback")):
            return bool(url)
        if not url:
            return False
        if not title:
            return True
        if title == url:
            return True
        low = title.lower()
        if low.startswith(("http://", "https://")):
            return True
        return False

    def _queue_title_enrichment(self, item: dict, generation: int) -> None:
        if not self._title_needs_enrichment(item):
            return
        key = self._result_key_for_item(item)
        if not key:
            return
        url = str(item.get("url") or "").strip()
        if not url:
            return

        try:
            with self._title_enrich_url_cache_lock:
                cached = self._title_enrich_url_cache.get(url)
        except Exception:
            cached = None
        if isinstance(cached, dict):
            try:
                wx.CallAfter(
                    self._apply_enriched_result,
                    key,
                    str(cached.get("title") or ""),
                    str(cached.get("native_subscribe_url") or ""),
                    str(cached.get("source_subscribe_url") or ""),
                    int(generation),
                    str(cached.get("owner_label") or ""),
                )
            except Exception:
                pass
            # If we still need title enrichment and cache has no title, allow quick-stage retry.
            if str(cached.get("title") or "").strip():
                return

        with self._title_enrich_lock:
            if key in self._title_enrich_pending:
                return
            self._title_enrich_pending.add(key)
        try:
            self._title_enrich_queue.put((key, url, int(generation)))
        except Exception:
            with self._title_enrich_lock:
                try:
                    self._title_enrich_pending.discard(key)
                except Exception:
                    pass

    def _title_enrich_quick_stage(self, key: str, url: str, generation: int) -> None:
        quick_acquired = False
        quick_title = ""
        try:
            if self._stop_event.is_set():
                return
            if not self._is_current_search_generation(generation):
                return

            # Fast path: get human-readable titles for common URL-only rows (especially
            # YouTube wrappers like yvsearch) before the heavier yt-dlp enrichment runs.
            try:
                self._quick_title_enrich_sem.acquire()
                quick_acquired = True
                if not self._stop_event.is_set():
                    quick_title = str(resolve_quick_url_title(url, timeout=self._QUICK_TITLE_ENRICH_TIMEOUT_S) or "").strip()
                    if quick_title:
                        try:
                            with self._title_enrich_url_cache_lock:
                                cached = dict(self._title_enrich_url_cache.get(url) or {})
                                cached["title"] = quick_title
                                self._title_enrich_url_cache[url] = cached
                        except Exception:
                            pass
                        try:
                            wx.CallAfter(self._apply_enriched_result, key, quick_title, "", "", int(generation), "")
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                if quick_acquired:
                    try:
                        self._quick_title_enrich_sem.release()
                    except Exception:
                        pass
                    quick_acquired = False
        finally:
            with self._title_enrich_lock:
                try:
                    self._title_enrich_pending.discard(key)
                except Exception:
                    pass

    def _queue_heavy_enrichment_for_item(self, item: dict, generation: int | None = None) -> None:
        if not self._item_needs_heavy_enrichment(item):
            return
        key = self._result_key_for_item(item)
        if not key:
            return
        url = str(item.get("url") or "").strip()
        if not url:
            return
        try:
            gen = int(self._search_generation if generation is None else generation)
        except Exception:
            gen = int(getattr(self, "_search_generation", 0) or 0)
        if not self._is_current_search_generation(gen):
            return

        cache = None
        try:
            with self._title_enrich_url_cache_lock:
                cache = dict(self._title_enrich_url_cache.get(url) or {})
        except Exception:
            cache = None
        if isinstance(cache, dict) and cache:
            try:
                wx.CallAfter(
                    self._apply_enriched_result,
                    key,
                    str(cache.get("title") or ""),
                    str(cache.get("native_subscribe_url") or ""),
                    str(cache.get("source_subscribe_url") or ""),
                    int(gen),
                    str(cache.get("owner_label") or ""),
                )
            except Exception:
                pass
            if bool(cache.get("_heavy_done")):
                return

        with self._title_enrich_lock:
            if key in self._title_enrich_heavy_pending:
                return
            self._title_enrich_heavy_pending.add(key)
        try:
            self._title_enrich_heavy_queue.put((key, url, int(gen)))
        except Exception:
            with self._title_enrich_lock:
                try:
                    self._title_enrich_heavy_pending.discard(key)
                except Exception:
                    pass

    def _title_enrich_heavy_stage(self, key: str, url: str, generation: int) -> None:
        acquired = False
        try:
            if self._stop_event.is_set():
                return
            if not self._is_current_search_generation(generation):
                return
            self._title_enrich_sem.acquire()
            acquired = True
            if self._stop_event.is_set():
                return
            if not self._is_current_search_generation(generation):
                return

            enrich = resolve_ytdlp_url_enrichment(url, timeout=self._TITLE_ENRICH_TIMEOUT_S) or {}
            title = str(enrich.get("title") or "").strip()
            native_sub = str(enrich.get("native_subscribe_url") or "").strip()
            source_sub = str(enrich.get("source_subscribe_url") or "").strip()
            owner_label = str(enrich.get("owner_label") or "").strip()
            cached_title = ""
            try:
                with self._title_enrich_url_cache_lock:
                    cached_prev = dict(self._title_enrich_url_cache.get(url) or {})
                    cached_title = str(cached_prev.get("title") or "").strip()
                    merged = {
                        "title": title or cached_title or "",
                        "native_subscribe_url": native_sub or str(cached_prev.get("native_subscribe_url") or ""),
                        "source_subscribe_url": source_sub or str(cached_prev.get("source_subscribe_url") or ""),
                        "owner_label": owner_label or str(cached_prev.get("owner_label") or ""),
                        "_heavy_done": True,
                    }
                    self._title_enrich_url_cache[url] = merged
            except Exception:
                cached_title = ""
            if not title:
                title = cached_title

            if not title and not native_sub and not source_sub and not owner_label:
                return
            try:
                wx.CallAfter(self._apply_enriched_result, key, title, native_sub, source_sub, int(generation), owner_label)
            except Exception:
                pass
        finally:
            with self._title_enrich_lock:
                try:
                    self._title_enrich_heavy_pending.discard(key)
                except Exception:
                    pass
            if acquired:
                try:
                    self._title_enrich_sem.release()
                except Exception:
                    pass

    def _apply_enriched_result(
        self,
        key: str,
        title: str,
        native_subscribe_url: str,
        source_subscribe_url: str,
        generation: int,
        owner_label: str = "",
    ) -> None:
        if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
            return
        try:
            if int(generation) != int(getattr(self, "_search_generation", 0) or 0):
                return
        except Exception:
            return

        changed = False
        title_changed = False
        subscribe_changed = False
        detail_changed = False
        for item in (self._all_results or []):
            if self._result_key_for_item(item) != key:
                continue
            cur_title = str(item.get("title") or "").strip()
            if title:
                if (
                    not bool(item.get("_title_is_fallback"))
                    and cur_title
                    and cur_title != str(item.get("url") or "").strip()
                    and not cur_title.lower().startswith(("http://", "https://"))
                ):
                    # Keep existing real title.
                    pass
                else:
                    item["title"] = title
                    item["_title_is_fallback"] = False
                    changed = True
                    title_changed = True
            if native_subscribe_url and not str(item.get("native_subscribe_url") or "").strip():
                item["native_subscribe_url"] = native_subscribe_url
                changed = True
                subscribe_changed = True
            if source_subscribe_url and not str(item.get("source_subscribe_url") or "").strip():
                item["source_subscribe_url"] = source_subscribe_url
                changed = True
                subscribe_changed = True
            if owner_label:
                cur_detail = str(item.get("detail") or "").strip()
                low_detail = cur_detail.lower()
                low_owner = str(owner_label).strip().lower()
                if low_owner and low_owner not in low_detail:
                    if cur_detail:
                        item["detail"] = f"{cur_detail} | {owner_label}"
                    else:
                        item["detail"] = owner_label
                    changed = True
                    detail_changed = True
            break

        if not changed:
            return

        # Title enrichment usually doesn't affect filtering or row order unless sorting by title.
        # Update in-place to avoid rebuilding the entire list (which is slow with NVDA), but
        # avoid spamming row accessibility updates while a search is still streaming in.
        if (
            title_changed
            and not bool(getattr(self, "_search_running", False))
            and int(getattr(self, "_sort_column", -1) if getattr(self, "_sort_column", None) is not None else -1) != 0
        ):
            if self._update_visible_result_row_title(key):
                if subscribe_changed:
                    self._update_action_buttons()
                return

        if subscribe_changed and not title_changed and not detail_changed:
            self._update_action_buttons()
            return

        self._schedule_results_refresh()

    def _schedule_results_refresh(self, delay_ms: int | None = None, immediate: bool = False) -> None:
        if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
            return
        if immediate:
            delay_ms = 0
        if delay_ms is None:
            delay_ms = int(self._RESULTS_REFRESH_THROTTLE_MS)
        try:
            delay_ms = max(0, int(delay_ms))
        except Exception:
            delay_ms = int(self._RESULTS_REFRESH_THROTTLE_MS)

        if delay_ms > 0:
            try:
                if bool(getattr(self, "_search_running", False)):
                    nav_ts = float(getattr(self, "_dialog_nav_ts", 0.0) or 0.0)
                    if nav_ts > 0.0:
                        elapsed_ms = int(max(0.0, (time.monotonic() - nav_ts) * 1000.0))
                        remaining_ms = int(self._RESULTS_REFRESH_NAV_COOLDOWN_MS) - elapsed_ms
                        if remaining_ms > 0:
                            delay_ms = max(delay_ms, remaining_ms)
                if self._is_results_list_focused():
                    if bool(getattr(self, "_search_running", False)):
                        delay_ms = max(delay_ms, int(self._RESULTS_REFRESH_THROTTLE_FOCUSED_MS))
                    nav_ts = float(getattr(self, "_results_list_nav_ts", 0.0) or 0.0)
                    if nav_ts > 0.0:
                        elapsed_ms = int(max(0.0, (time.monotonic() - nav_ts) * 1000.0))
                        remaining_ms = int(self._RESULTS_REFRESH_NAV_COOLDOWN_MS) - elapsed_ms
                        if remaining_ms > 0:
                            delay_ms = max(delay_ms, remaining_ms)
            except Exception:
                pass

        try:
            later = getattr(self, "_results_refresh_later", None)
            if delay_ms <= 0:
                if later is not None:
                    try:
                        later.Stop()
                    except Exception:
                        pass
                    self._results_refresh_later = None
                self._apply_result_filter()
                return

            if later is not None:
                try:
                    if bool(later.IsRunning()):
                        return
                except Exception:
                    pass
            self._results_refresh_later = wx.CallLater(delay_ms, self._flush_scheduled_results_refresh)
        except Exception:
            self._apply_result_filter()

    def _flush_scheduled_results_refresh(self) -> None:
        self._results_refresh_later = None
        if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
            return
        self._apply_result_filter()

    def _refresh_site_choices(self) -> None:
        prev_scope = self._get_choice_value(self.scope_choice, self._scope_values)
        prev_filter = self._get_choice_value(self.filter_choice, self._filter_values)

        try:
            safe_sites = list(get_ytdlp_searchable_sites(include_adult=False) or [])
        except Exception:
            safe_sites = []
        adult_sites = []
        if self._adult_search_enabled():
            try:
                adult_sites = list(get_adult_searchable_sites() or [])
            except Exception:
                adult_sites = []
        self._safe_site_rows = safe_sites
        self._adult_site_rows = adult_sites
        # Combined lookup table so a scope/filter id resolves to either kind.
        self._site_rows = list(safe_sites) + list(adult_sites)

        # Scope: "All searchable sites" covers only safe sites — adult sites are
        # never included implicitly. Adult sites are reachable only by choosing the
        # explicit "Adult sites (all)" group or an individual adult site.
        scope_values = [self._ALL_SITES_TOKEN] + [str(s.get("id") or "") for s in safe_sites]
        scope_labels = ["All searchable sites"] + [str(s.get("label") or s.get("id") or "") for s in safe_sites]
        if adult_sites:
            scope_values.append(self._ADULT_ALL_TOKEN)
            scope_labels.append("Adult sites (all)")
            for s in adult_sites:
                scope_values.append(str(s.get("id") or ""))
                scope_labels.append(f"Adult: {s.get('label') or s.get('id') or ''}")
        self._scope_values = scope_values

        # Result filter can narrow to any site that produced results, adult included.
        filter_values = [self._ALL_SITES_TOKEN] + [str(s.get("id") or "") for s in self._site_rows]
        filter_labels = ["All sites"] + [str(s.get("label") or s.get("id") or "") for s in self._site_rows]
        self._filter_values = filter_values

        self.scope_choice.Clear()
        self.filter_choice.Clear()
        for label in scope_labels:
            self.scope_choice.Append(label)
        for label in filter_labels:
            self.filter_choice.Append(label)

        self._set_choice_value(self.scope_choice, self._scope_values, prev_scope)
        self._set_choice_value(self.filter_choice, self._filter_values, prev_filter)
        self._schedule_results_refresh(immediate=True)

    def _get_choice_value(self, choice, values):
        try:
            idx = int(choice.GetSelection())
        except Exception:
            idx = wx.NOT_FOUND
        if idx == wx.NOT_FOUND or idx < 0 or idx >= len(values or []):
            return self._ALL_SITES_TOKEN
        return values[idx]

    def _set_choice_value(self, choice, values, target_value):
        target = str(target_value or self._ALL_SITES_TOKEN)
        idx = 0
        for i, val in enumerate(values or []):
            if str(val or "") == target:
                idx = i
                break
        try:
            choice.SetSelection(idx)
        except Exception:
            pass

    def _adult_search_enabled(self) -> bool:
        cm = getattr(self, "_config_manager", None)
        if cm is None:
            return False
        try:
            return bool(cm.get("enable_adult_search", False))
        except Exception:
            return False

    def _get_scope_sites(self) -> list[dict]:
        selected = self._get_choice_value(self.scope_choice, self._scope_values)
        if selected == self._ALL_SITES_TOKEN:
            # Safe sites only; adult sites are never searched implicitly.
            return list(self._safe_site_rows or [])
        if selected == self._ADULT_ALL_TOKEN:
            return list(self._adult_site_rows or [])
        return [s for s in (self._site_rows or []) if str(s.get("id") or "") == selected]

    def _get_result_filter_site_id(self) -> str:
        return str(self._get_choice_value(self.filter_choice, self._filter_values) or self._ALL_SITES_TOKEN)

    def _passes_result_filter(self, item: dict) -> bool:
        site_filter = self._get_result_filter_site_id()
        if site_filter == self._ALL_SITES_TOKEN:
            return True
        return str(item.get("site_id") or "") == site_filter

    def _format_play_count(self, value) -> str:
        if value is None:
            return ""
        try:
            return f"{int(value):,}"
        except Exception:
            return str(value or "")

    def _mainstream_priority_for_result(self, item: dict) -> int:
        site_id = str(item.get("site_id") or "").strip().lower()
        best = int(self._MAINSTREAM_SITE_PRIORITY.get(site_id, 999))
        try:
            parsed = urlparse(str(item.get("url") or "").strip())
            host = (parsed.netloc or "").lower()
        except Exception:
            host = ""
        host = host[4:] if host.startswith("www.") else host

        # URL host can be more useful than wrapper site IDs (e.g. Yahoo Video -> YouTube URL).
        host_priority = (
            0 if ("youtube.com" in host or "youtu.be" in host) else
            1 if "soundcloud.com" in host else
            2 if "googlevideo.com" in host else
            3 if "bilibili.com" in host else
            4 if ("vimeo.com" in host or "tiktok.com" in host) else
            5 if ("facebook.com" in host or "instagram.com" in host or "x.com" in host or "twitter.com" in host) else
            6 if ("twitch.tv" in host or "rumble.com" in host or "odysee.com" in host) else
            999
        )
        return min(best, host_priority)

    def _default_result_sort_key(self, item: dict):
        return (
            int(self._mainstream_priority_for_result(item)),
            int(item.get("_arrival_order") or 0),
        )

    def _interleaved_results(self, rows: list[dict]) -> list[dict]:
        """Round-robin results across sites so every searched site is represented
        near the top instead of one site (YouTube) filling the whole first page.

        Within each round we emit sites in mainstream-priority order; within a
        site we keep arrival order. Rank 0 of every site comes first, then rank 1,
        and so on.
        """
        by_site: dict[str, list[dict]] = {}
        for it in rows:
            sid = str(it.get("site_id") or "")
            by_site.setdefault(sid, []).append(it)
        for lst in by_site.values():
            lst.sort(key=lambda it: int(it.get("_arrival_order") or 0))

        ranked: list[tuple] = []
        for lst in by_site.values():
            for rank, it in enumerate(lst):
                ranked.append(
                    (
                        int(rank),
                        int(self._mainstream_priority_for_result(it)),
                        int(it.get("_arrival_order") or 0),
                        it,
                    )
                )
        ranked.sort(key=lambda t: (t[0], t[1], t[2]))
        return [t[3] for t in ranked]

    def _sorted_results(self, items: list[dict]) -> list[dict]:
        rows = list(items or [])
        col = getattr(self, "_sort_column", self._DEFAULT_SORT_COLUMN)
        desc = bool(getattr(self, "_sort_desc", self._DEFAULT_SORT_DESC))

        if col is None:
            return self._interleaved_results(rows)

        if int(col) == 3:
            # Numeric plays/views sort; keep unknown counts at the end.
            def _plays_key(it: dict):
                raw = it.get("play_count")
                try:
                    val = int(raw)
                    missing = 0
                except Exception:
                    val = 0
                    missing = 1
                # Encode direction in key so "missing last" is preserved for both asc/desc.
                ord_val = -val if desc else val
                return (missing, ord_val, int(it.get("_arrival_order") or 0))

            rows.sort(key=_plays_key)
            return rows

        if int(col) == 0:
            def _s(it): return str(it.get("title") or "").lower()
        elif int(col) == 1:
            def _s(it): return str(it.get("site") or "").lower()
        elif int(col) == 2:
            def _s(it): return str(it.get("kind") or "").lower()
        elif int(col) == 4:
            def _s(it): return str(it.get("detail") or "").lower()
        else:
            def _s(it): return str(it.get("title") or "").lower()

        rows.sort(key=lambda it: (_s(it), int(it.get("_arrival_order") or 0)), reverse=desc)
        return rows

    def _sync_sort_choice_to_state(self) -> None:
        """Reflect the current _sort_column in the Sort by combo when possible."""
        choice = getattr(self, "sort_choice", None)
        if choice is None:
            return
        col = getattr(self, "_sort_column", self._DEFAULT_SORT_COLUMN)
        cols = list(getattr(self, "_sort_choice_columns", [None]))
        try:
            idx = cols.index(col)
        except ValueError:
            idx = 0
        try:
            choice.SetSelection(int(idx))
        except Exception:
            pass

    def on_sort_choice_changed(self, event):
        try:
            idx = int(self.sort_choice.GetSelection())
        except Exception:
            idx = 0
        cols = list(getattr(self, "_sort_choice_columns", [None]))
        col = cols[idx] if 0 <= idx < len(cols) else None
        self._sort_column = col
        # Plays is most useful descending; Title/Site ascending; Relevance uses
        # the default mainstream-first then arrival order.
        self._sort_desc = bool(col == 3)
        self._schedule_results_refresh(immediate=True)
        try:
            event.Skip()
        except Exception:
            pass

    def on_results_col_click(self, event):
        try:
            col = int(event.GetColumn())
        except Exception:
            col = -1
        # Ignore hidden URL column
        if col < 0 or col >= 5:
            try:
                event.Skip()
            except Exception:
                pass
            return

        cur_col = getattr(self, "_sort_column", self._DEFAULT_SORT_COLUMN)
        cur_desc = bool(getattr(self, "_sort_desc", self._DEFAULT_SORT_DESC))

        if cur_col == col:
            self._sort_desc = (not cur_desc)
        else:
            self._sort_column = col
            # Plays is most useful descending by default.
            self._sort_desc = bool(col == 3)

        self._sync_sort_choice_to_state()
        self._schedule_results_refresh(immediate=True)
        try:
            event.Skip()
        except Exception:
            pass

    def _apply_result_filter(self) -> None:
        self._applying_results_refresh = True
        try:
            selected = self._get_selected_result()
            selected_url = str(selected.get("url") or "") if selected else ""
        except Exception:
            selected_url = ""

        filtered = [it for it in (self._all_results or []) if self._passes_result_filter(it)]
        self._visible_results = self._sorted_results(filtered)
        try:
            self.results_list.Freeze()
        except Exception:
            pass
        try:
            self.results_list.DeleteAllItems()
            for i, item in enumerate(self._visible_results):
                idx = self.results_list.InsertItem(i, str(item.get("title") or ""))
                self.results_list.SetItem(idx, 1, str(item.get("site") or ""))
                self.results_list.SetItem(idx, 2, str(item.get("kind") or ""))
                self.results_list.SetItem(idx, 3, self._format_play_count(item.get("play_count")))
                self.results_list.SetItem(idx, 4, str(item.get("detail") or ""))
                self.results_list.SetItem(idx, 5, str(item.get("url") or ""))
        except Exception:
            return
        finally:
            try:
                self.results_list.Thaw()
            except Exception:
                pass
            self._applying_results_refresh = False

        if selected_url:
            for i, item in enumerate(self._visible_results):
                if str(item.get("url") or "") == selected_url:
                    try:
                        self.results_list.Select(i)
                        self.results_list.Focus(i)
                    except Exception:
                        pass
                    break

        self._update_action_buttons()

    def on_scope_changed(self, event):
        # Scope change affects the next search run; keep current results visible.
        event.Skip()

    def on_filter_changed(self, event):
        self._schedule_results_refresh(immediate=True)
        event.Skip()

    def on_search(self, event):
        if self._search_running:
            return

        term = str(self.search_ctrl.GetValue() or "").strip()
        if not term:
            return

        sites = self._get_scope_sites()
        if not sites:
            self.status_lbl.SetLabel(_("No searchable sites."))
            return
        self._last_search_term = term
        self._last_search_sites = list(sites or [])
        self._last_search_per_site_limit = int(self._PER_SITE_LIMIT)
        self._start_search_run(reset=True, term=term, sites=self._last_search_sites, per_site_limit=self._last_search_per_site_limit)

    def on_load_more(self, event):
        if self._search_running:
            return
        if not self._has_last_search():
            return
        try:
            self._last_search_per_site_limit = max(
                int(self._PER_SITE_LIMIT),
                int(self._last_search_per_site_limit or self._PER_SITE_LIMIT) + int(self._LOAD_MORE_STEP),
            )
        except Exception:
            self._last_search_per_site_limit = int(self._PER_SITE_LIMIT) + int(self._LOAD_MORE_STEP)
        self._start_search_run(
            reset=False,
            term=str(self._last_search_term or "").strip(),
            sites=list(self._last_search_sites or []),
            per_site_limit=int(self._last_search_per_site_limit or self._PER_SITE_LIMIT),
        )

    def _start_search_run(self, *, reset: bool, term: str, sites: list[dict], per_site_limit: int) -> None:
        if self._search_running:
            return
        if not term or not sites:
            return

        try:
            per_site_limit = max(1, int(per_site_limit or self._PER_SITE_LIMIT))
        except Exception:
            per_site_limit = int(self._PER_SITE_LIMIT)

        if reset:
            self._all_results = []
            self._visible_results = []
            self._seen_result_keys = set()
            self._result_by_dedupe_key = {}
            self._search_generation = int(getattr(self, "_search_generation", 0) or 0) + 1
            self._result_arrival_counter = 0
            try:
                if getattr(self, "_results_refresh_later", None):
                    self._results_refresh_later.Stop()
            except Exception:
                pass
            self._results_refresh_later = None
            with self._title_enrich_lock:
                self._title_enrich_pending.clear()
                self._title_enrich_heavy_pending.clear()
            self.results_list.DeleteAllItems()
            self._update_action_buttons()
        self._completed_sites = 0
        self._total_sites = len(sites)
        self._stop_event.clear()
        self._search_running = True

        self.search_ctrl.Disable()
        self.search_btn.Disable()
        self.load_more_btn.Disable()
        self.scope_choice.Disable()
        action = "Searching" if reset else "Loading more"
        self.status_lbl.SetLabel(f"{action} {self._total_sites} sites...")

        self._search_thread = threading.Thread(
            target=self._search_manager,
            args=(term, list(sites), int(per_site_limit), bool(not reset)),
            daemon=True,
        )
        self._search_thread.start()

    def _search_manager(self, term: str, sites: list[dict], per_site_limit: int, append_mode: bool = False) -> None:
        total = len(sites or [])
        completed = 0
        cancelled = False

        max_workers = max(1, min(self._SEARCH_CONCURRENCY, total or 1))
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {}
                for site in (sites or []):
                    if self._stop_event.is_set():
                        cancelled = True
                        break
                    fut = pool.submit(
                        search_ytdlp_site,
                        term,
                        site,
                        int(per_site_limit),
                        self._PER_SITE_TIMEOUT_S,
                    )
                    future_map[fut] = site

                for fut in concurrent.futures.as_completed(list(future_map.keys())):
                    site = future_map.get(fut) or {}
                    completed += 1
                    if self._stop_event.is_set():
                        cancelled = True
                    items = []
                    error_msg = ""
                    try:
                        items = list(fut.result() or [])
                    except Exception as e:
                        error_msg = str(e) or type(e).__name__
                    try:
                        wx.CallAfter(self._on_site_search_results, site, items, completed, total, error_msg)
                    except Exception:
                        pass
                    if cancelled:
                        break
        finally:
            try:
                wx.CallAfter(self._on_search_finished, completed, total, cancelled, bool(append_mode), int(per_site_limit))
            except Exception:
                pass

    def _on_site_search_results(self, site: dict, items: list[dict], completed: int, total: int, error_msg: str = ""):
        if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
            return

        try:
            self._completed_sites = max(int(self._completed_sites or 0), int(completed or 0))
        except Exception:
            self._completed_sites = completed
        try:
            self._total_sites = max(int(self._total_sites or 0), int(total or 0))
        except Exception:
            self._total_sites = total

        if getattr(self, "_result_by_dedupe_key", None) is None:
            self._result_by_dedupe_key = {}

        new_count = 0
        upgraded = False
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            if not str(item.get("site_id") or "").strip():
                item["site_id"] = str((site or {}).get("id") or "").strip()

            # Cross-site dedupe: collapse the same underlying video seen from
            # different search backends, keeping only the best-scoring copy.
            try:
                dkey = canonical_search_result_key(item)
            except Exception:
                dkey = url.lower()

            existing = self._result_by_dedupe_key.get(dkey) if dkey else None
            if existing is not None:
                try:
                    better = search_result_quality_score(item) > search_result_quality_score(existing)
                except Exception:
                    better = False
                if better:
                    # Replace content in place so the row keeps its arrival slot.
                    arrival = existing.get("_arrival_order")
                    existing.clear()
                    existing.update(item)
                    existing["_arrival_order"] = arrival
                    upgraded = True
                    try:
                        if self._title_needs_enrichment(existing) and supports_quick_url_title(url):
                            self._queue_title_enrichment(existing, int(getattr(self, "_search_generation", 0) or 0))
                    except Exception:
                        pass
                continue

            try:
                self._result_arrival_counter = int(self._result_arrival_counter or 0) + 1
            except Exception:
                self._result_arrival_counter = 1
            item["_arrival_order"] = int(self._result_arrival_counter or 0)
            if dkey:
                self._result_by_dedupe_key[dkey] = item
            self._all_results.append(item)
            new_count += 1
            # Eagerly queue the quick (oEmbed-style, single HTTP GET) title stage
            # for URL-only rows so real titles appear fast. Only rows with a cheap
            # fast path are queued; the heavy yt-dlp stage stays selection-driven.
            try:
                if self._title_needs_enrichment(item) and supports_quick_url_title(url):
                    self._queue_title_enrichment(item, int(getattr(self, "_search_generation", 0) or 0))
            except Exception:
                pass

        if new_count or upgraded:
            self._schedule_results_refresh()

        site_label = str((site or {}).get("label") or (site or {}).get("id") or "site")
        if error_msg:
            self.status_lbl.SetLabel(
                f"{self._completed_sites}/{self._total_sites} sites, {len(self._all_results)} results. {site_label}: error"
            )
            return

        self.status_lbl.SetLabel(
            f"{self._completed_sites}/{self._total_sites} sites, {len(self._all_results)} results. {site_label} +{new_count}"
        )

    def _on_search_finished(
        self,
        completed: int,
        total: int,
        cancelled: bool,
        append_mode: bool = False,
        per_site_limit: int = 0,
    ) -> None:
        self._search_running = False
        if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
            return

        try:
            self.search_ctrl.Enable()
            self.search_btn.Enable()
            self.scope_choice.Enable()
            self._update_load_more_button()
            self.search_ctrl.SetFocus()
        except Exception:
            return

        try:
            self._completed_sites = max(int(self._completed_sites or 0), int(completed or 0))
            self._total_sites = max(int(self._total_sites or 0), int(total or 0))
        except Exception:
            pass

        if cancelled:
            self.status_lbl.SetLabel(f"Stopped. {len(self._all_results)} results.")
        else:
            if append_mode:
                self.status_lbl.SetLabel(f"Loaded more. {len(self._all_results)} results.")
            else:
                self.status_lbl.SetLabel(f"{len(self._all_results)} results.")
        self._schedule_results_refresh(immediate=True)

    def _get_selected_result(self):
        idx = wx.NOT_FOUND
        try:
            idx = self.results_list.GetFirstSelected()
        except Exception:
            idx = wx.NOT_FOUND
        if idx == wx.NOT_FOUND:
            return None
        try:
            if 0 <= idx < len(self._visible_results):
                return self._visible_results[idx]
        except Exception:
            return None
        return None

    def _get_selected_action_availability(self) -> tuple[bool, bool, bool]:
        item = self._get_selected_result()
        play_ok = bool(item and str(item.get("url") or "").strip())
        native_ok = bool(item and str(item.get("native_subscribe_url") or "").strip())
        source_ok = bool(item and str(item.get("source_subscribe_url") or "").strip())
        subscribe_ok = bool(native_ok or source_ok)
        copy_ok = play_ok
        return (play_ok, subscribe_ok, copy_ok)

    def _update_action_buttons(self) -> None:
        play_ok, subscribe_ok, copy_ok = self._get_selected_action_availability()
        self._play_action_enabled = bool(play_ok)
        self._subscribe_action_enabled = bool(subscribe_ok)
        self._copy_action_enabled = bool(copy_ok)

    def _show_results_context_menu(self, client_pos=None) -> None:
        play_ok, subscribe_ok, copy_ok = self._get_selected_action_availability()

        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, _("Play"))
        subscribe_item = menu.Append(wx.ID_ANY, _("Subscribe"))
        copy_item = menu.Append(wx.ID_ANY, _("Copy URL"))
        play_item.Enable(bool(play_ok))
        subscribe_item.Enable(bool(subscribe_ok))
        copy_item.Enable(bool(copy_ok))

        menu.Bind(wx.EVT_MENU, self.on_play_selected, play_item)
        menu.Bind(wx.EVT_MENU, self.on_subscribe_best, subscribe_item)
        menu.Bind(wx.EVT_MENU, self.on_copy_selected_url, copy_item)

        try:
            apply_menu_mnemonics(menu)
            if client_pos is None:
                idx = self.results_list.GetFirstSelected()
                if idx != wx.NOT_FOUND:
                    rect = self.results_list.GetItemRect(idx)
                    client_pos = wx.Point(max(0, int(rect.x) + 8), max(0, int(rect.y) + 8))
            if client_pos is None:
                self.results_list.PopupMenu(menu)
            else:
                self.results_list.PopupMenu(menu, client_pos)
        finally:
            try:
                menu.Destroy()
            except Exception:
                pass

    def on_results_context_menu(self, event):
        client_pos = None
        try:
            screen_pos = event.GetPosition()
            if isinstance(screen_pos, wx.Point) and int(screen_pos.x) >= 0 and int(screen_pos.y) >= 0:
                client_pos = self.results_list.ScreenToClient(screen_pos)
        except Exception:
            client_pos = None

        if client_pos is not None:
            try:
                idx, _flags = self.results_list.HitTest(client_pos)
            except Exception:
                idx = wx.NOT_FOUND
            if idx != wx.NOT_FOUND:
                try:
                    self.results_list.Select(idx)
                    self.results_list.Focus(idx)
                except Exception:
                    pass

        self._show_results_context_menu(client_pos)

    def on_result_selected(self, event):
        try:
            if not bool(getattr(self, "_applying_results_refresh", False)) and self._is_results_list_focused():
                self._results_list_nav_ts = time.monotonic()
        except Exception:
            pass
        try:
            item = self._get_selected_result()
            if item:
                self._queue_heavy_enrichment_for_item(item)
        except Exception:
            pass
        self._update_action_buttons()
        event.Skip()

    def on_result_activated(self, event):
        self.on_play_selected(event)

    def _get_parent_mainframe(self):
        try:
            return self.GetParent()
        except Exception:
            return None

    def _register_player_status_callback(self, parent, title: str) -> None:
        """Register a callback so the player status updates this dialog's label."""
        try:
            pw = getattr(parent, "player_window", None)
            if pw is None:
                return
            cbs = getattr(pw, "_status_change_callbacks", None)
            if cbs is None:
                return

            # Remove any previous callback we registered
            prev = getattr(self, "_player_status_cb", None)
            if prev is not None:
                try:
                    cbs.remove(prev)
                except ValueError:
                    pass

            title_str = str(title or "").strip()

            def _on_player_status(status_text: str) -> None:
                try:
                    lbl = getattr(self, "status_lbl", None)
                    if lbl is None:
                        return
                    st = str(status_text or "").strip()
                    if st.lower() in ("playing",):
                        lbl.SetLabel(f"Playing: {title_str}" if title_str else "Playing")
                    elif st.lower() in ("paused",):
                        lbl.SetLabel(f"Paused: {title_str}" if title_str else "Paused")
                    elif st.lower() in ("stopped",):
                        lbl.SetLabel(_("Ready."))
                    elif st.lower().startswith("buffering"):
                        lbl.SetLabel(f"Buffering: {title_str}" if title_str else "Buffering...")
                    elif st.lower().startswith("connecting"):
                        lbl.SetLabel(f"Connecting: {title_str}" if title_str else "Connecting...")
                except Exception:
                    pass

            self._player_status_cb = _on_player_status
            cbs.append(_on_player_status)
        except Exception:
            pass

    def _unregister_player_status_callback(self) -> None:
        """Remove our callback from the player, if any."""
        try:
            cb = getattr(self, "_player_status_cb", None)
            if cb is None:
                return
            parent = self._get_parent_mainframe()
            if parent is None:
                return
            pw = getattr(parent, "player_window", None)
            if pw is None:
                return
            cbs = getattr(pw, "_status_change_callbacks", None)
            if cbs is not None:
                try:
                    cbs.remove(cb)
                except ValueError:
                    pass
            self._player_status_cb = None
        except Exception:
            pass

    def on_play_selected(self, event):
        item = self._get_selected_result()
        if not item:
            return
        try:
            self._queue_heavy_enrichment_for_item(item)
        except Exception:
            pass
        parent = self._get_parent_mainframe()
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip() or url
        if not url:
            return
        if parent and hasattr(parent, "play_ytdlp_search_result"):
            try:
                parent.play_ytdlp_search_result(url, title=title)
            except Exception as e:
                wx.MessageBox(
                    _("Could not start playback: {error}").format(error=e),
                    _("Playback Error"),
                    wx.ICON_ERROR,
                )
                return
            self.status_lbl.SetLabel(f"Playing: {title}")
            self._register_player_status_callback(parent, title)
        else:
            webbrowser.open(url)

    def _subscribe_selected(self, key: str, label: str) -> None:
        item = self._get_selected_result()
        if not item:
            return
        url = str(item.get(key) or "").strip()
        if not url:
            return
        parent = self._get_parent_mainframe()
        if not parent or not hasattr(parent, "add_feed_from_url_prompt"):
            wx.MessageBox(_("Parent window does not support subscribing from this dialog."), _("Subscribe"), wx.ICON_ERROR)
            return
        try:
            parent.add_feed_from_url_prompt(url)
            self.status_lbl.SetLabel(f"{label}: {url}")
        except Exception as e:
            wx.MessageBox(
                _("Could not subscribe: {error}").format(error=e),
                _("Subscribe Error"),
                wx.ICON_ERROR,
            )

    def on_subscribe_best(self, event):
        item = self._get_selected_result()
        if not item:
            return
        try:
            self._queue_heavy_enrichment_for_item(item)
        except Exception:
            pass
        native = str(item.get("native_subscribe_url") or "").strip()
        source = str(item.get("source_subscribe_url") or "").strip()
        if native:
            self._subscribe_selected("native_subscribe_url", "Subscribed")
            return
        if source:
            self._subscribe_selected("source_subscribe_url", "Subscribed")

    def on_subscribe_native(self, event):
        self._subscribe_selected("native_subscribe_url", "Subscribed (native)")

    def on_subscribe_source(self, event):
        self._subscribe_selected("source_subscribe_url", "Subscribed (source)")

    def on_copy_selected_url(self, event):
        item = self._get_selected_result()
        if not item:
            return
        url = str(item.get("url") or "").strip()
        if not url:
            return
        try:
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(url))
                wx.TheClipboard.Flush()
                wx.TheClipboard.Close()
                self.status_lbl.SetLabel(_("Copied URL."))
        except Exception:
            pass


class PersistentSearchDialog(wx.Dialog):
    def __init__(self, parent, searches=None):
        super().__init__(parent, title=_("Configure Persistent Search"), size=(420, 320))

        self._searches = list(searches or [])

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label=_("Saved searches:")), 0, wx.ALL, 5)

        self.list_ctrl = wx.ListBox(self, choices=self._searches)
        self.list_ctrl.SetName("Saved searches")
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(self, label=_("Add..."))
        remove_btn = wx.Button(self, label=_("Remove"))
        btn_row.Add(add_btn, 0, wx.ALL, 5)
        btn_row.Add(remove_btn, 0, wx.ALL, 5)
        sizer.Add(btn_row, 0, wx.ALIGN_LEFT | wx.ALL, 0)

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        self.SetSizer(sizer)
        self.Centre()

        add_btn.Bind(wx.EVT_BUTTON, self.on_add)
        remove_btn.Bind(wx.EVT_BUTTON, self.on_remove)

    def _normalize_query(self, text: str) -> str:
        return (text or "").strip()

    def _has_query(self, query: str) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return True
        for existing in self._searches:
            if (existing or "").strip().lower() == q:
                return True
        return False

    def on_add(self, event):
        dlg = wx.TextEntryDialog(self, _("Search query:"), _("Add Search"))
        if dlg.ShowModal() == wx.ID_OK:
            query = self._normalize_query(dlg.GetValue())
            if query and not self._has_query(query):
                self._searches.append(query)
                self.list_ctrl.Append(query)
        dlg.Destroy()

    def on_remove(self, event):
        idx = self.list_ctrl.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        try:
            self.list_ctrl.Delete(idx)
        except Exception:
            pass
        try:
            self._searches.pop(idx)
        except Exception:
            pass

    def get_searches(self):
        return list(self._searches or [])


class AboutDialog(wx.Dialog):
    def __init__(self, parent, version_str):
        super().__init__(parent, title=_("About BlindRSS"), size=(430, 340))

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Title / Version
        title_font = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title_txt = wx.StaticText(self, label=f"BlindRSS {version_str}")
        title_txt.SetFont(title_font)
        sizer.Add(title_txt, 0, wx.ALIGN_CENTER | wx.TOP, 15)

        # Copyright
        copy_txt = wx.StaticText(self, label=_("Copyright (c) 2024-2026 serrebidev and contributors"))
        sizer.Add(copy_txt, 0, wx.ALIGN_CENTER | wx.TOP, 10)

        sizer.AddSpacer(20)

        # Buttons
        github_btn = wx.Button(self, label=_("Follow me on GitHub (@serrebidev)"))
        repo_btn = wx.Button(self, label=_("Visit Repository"))
        changelog_btn = wx.Button(self, label=_("View Changelog"))

        sizer.Add(github_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        sizer.Add(repo_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        sizer.Add(changelog_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        sizer.AddSpacer(20)

        close_btn = wx.Button(self, wx.ID_CLOSE, _("Close"))
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)

        self.SetSizer(sizer)
        self.Centre()

        # Bindings
        github_btn.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://github.com/serrebidev"))
        repo_btn.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://github.com/serrebidev/BlindRSS"))
        changelog_btn.Bind(
            wx.EVT_BUTTON,
            lambda e: webbrowser.open("https://github.com/serrebidev/BlindRSS/blob/main/CHANGELOG.md"),
        )
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

# Backwards-compatible name (menu item was historically called "Search Podcast").
PodcastSearchDialog = FeedSearchDialog


class QueueDialog(wx.Dialog):
    """Manage the media play queue: play, reorder, and remove items.

    `controller` is the MainFrame; it exposes get_play_queue(),
    play_queue_index(i), remove_queue_indices([i]), move_queue_item(i, delta),
    and clear_play_queue(). The dialog is keyboard-first and screen-reader
    friendly: a single list with labeled action buttons, Enter to play, Delete
    to remove, and Alt+Up/Alt+Down to reorder.
    """

    def __init__(self, parent, controller):
        super().__init__(
            parent,
            title=_("Play Queue"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.controller = controller

        outer = wx.BoxSizer(wx.VERTICAL)

        self.info_lbl = wx.StaticText(self, label="")
        outer.Add(self.info_lbl, 0, wx.ALL, 8)

        self.list_box = wx.ListBox(self, style=wx.LB_SINGLE)
        self.list_box.SetName(_("Queued media"))
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self.on_play)
        self.list_box.Bind(wx.EVT_LISTBOX, lambda e: self._update_buttons())
        self.list_box.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        # On wxMSW the dialog's default-button navigation consumes Enter before
        # the ListBox EVT_KEY_DOWN handler ever sees it, so Enter must be
        # intercepted at the char-hook stage for the Play/Pause action to fire.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        outer.Add(self.list_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.play_btn = wx.Button(self, label=_("&Play"))
        self.play_btn.Bind(wx.EVT_BUTTON, self.on_play)
        btn_sizer.Add(self.play_btn, 0, wx.ALL, 4)

        self.up_btn = wx.Button(self, label=_("Move &Up"))
        self.up_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_move(-1))
        btn_sizer.Add(self.up_btn, 0, wx.ALL, 4)

        self.down_btn = wx.Button(self, label=_("Move &Down"))
        self.down_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_move(1))
        btn_sizer.Add(self.down_btn, 0, wx.ALL, 4)

        self.remove_btn = wx.Button(self, label=_("&Remove"))
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove)
        btn_sizer.Add(self.remove_btn, 0, wx.ALL, 4)

        self.clear_btn = wx.Button(self, label=_("&Clear All"))
        self.clear_btn.Bind(wx.EVT_BUTTON, self.on_clear)
        btn_sizer.Add(self.clear_btn, 0, wx.ALL, 4)

        outer.Add(btn_sizer, 0, wx.ALIGN_CENTER)

        close_sizer = self.CreateButtonSizer(wx.CLOSE)
        if close_sizer:
            outer.Add(close_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 8)
        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)

        self.SetSizer(outer)
        self.SetSize((460, 360))
        self.Centre()

        self._reload(select=0)

        # Keep the Play/Pause label live while the dialog is open: playback can
        # start, pause, or finish from elsewhere. The label is only rewritten
        # when it actually changes, so screen readers don't re-announce it.
        self._state_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._update_buttons(), self._state_timer)
        self._state_timer.Start(750)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _on_close(self, event) -> None:
        try:
            self._state_timer.Stop()
        except Exception:
            pass
        event.Skip()

    def _entry_is_playing(self, index: int) -> bool:
        try:
            fn = getattr(self.controller, "queue_entry_is_playing", None)
            return bool(fn(int(index))) if callable(fn) else False
        except Exception:
            return False

    def _entries(self):
        try:
            return list(self.controller.get_play_queue() or [])
        except Exception:
            return []

    def _entry_source(self, entry) -> str:
        try:
            fn = getattr(self.controller, "queue_entry_source", None)
            if callable(fn):
                return str(fn(entry) or "").strip()
        except Exception:
            pass
        return str((entry or {}).get("feed_title") or "").strip()

    def _entry_time_label(self, entry) -> str:
        try:
            fn = getattr(self.controller, "queue_entry_time_label", None)
            if callable(fn):
                return str(fn(entry) or "").strip()
        except Exception:
            pass
        return ""

    def _reload(self, select: int | None = None) -> None:
        entries = self._entries()
        self.list_box.Clear()
        for i, entry in enumerate(entries):
            title = str((entry or {}).get("title") or "").strip() or _("Untitled")
            source = self._entry_source(entry)
            if source:
                label = _("{index}. {title}, from {source}").format(
                    index=i + 1, title=title, source=source
                )
            else:
                label = _("{index}. {title}").format(index=i + 1, title=title)
            time_label = self._entry_time_label(entry)
            if time_label:
                label = f"{label}, {time_label}"
            self.list_box.Append(label)
        if entries:
            self.info_lbl.SetLabel(
                ngettext("{n} item in queue.", "{n} items in queue.", len(entries)).format(n=len(entries))
            )
            if select is None:
                select = 0
            select = max(0, min(int(select), len(entries) - 1))
            self.list_box.SetSelection(select)
        else:
            self.info_lbl.SetLabel(_("The play queue is empty."))
        self._update_buttons()

    def _update_buttons(self) -> None:
        count = self.list_box.GetCount()
        sel = self.list_box.GetSelection()
        has_sel = sel != wx.NOT_FOUND
        self.play_btn.Enable(has_sel)
        self.remove_btn.Enable(has_sel)
        self.up_btn.Enable(has_sel and sel > 0)
        self.down_btn.Enable(has_sel and 0 <= sel < count - 1)
        self.clear_btn.Enable(count > 0)
        # The Play button pauses the item that is currently playing.
        desired = _("&Pause") if (has_sel and self._entry_is_playing(sel)) else _("&Play")
        try:
            if self.play_btn.GetLabel() != desired:
                self.play_btn.SetLabel(desired)
        except Exception:
            pass

    def on_play(self, event) -> None:
        sel = self.list_box.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        try:
            toggle = getattr(self.controller, "toggle_queue_entry_play_pause", None)
            if callable(toggle):
                toggle(int(sel))
            else:
                self.controller.play_queue_index(int(sel))
        except Exception:
            log.exception("Failed to play/pause queue item from dialog")
        self._update_buttons()

    def on_remove(self, event) -> None:
        sel = self.list_box.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        try:
            self.controller.remove_queue_indices([int(sel)])
        except Exception:
            log.exception("Failed to remove queue item")
        self._reload(select=sel)

    def on_move(self, delta: int) -> None:
        sel = self.list_box.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        try:
            new_index = int(self.controller.move_queue_item(int(sel), int(delta)))
        except Exception:
            log.exception("Failed to move queue item")
            new_index = sel
        self._reload(select=new_index)
        self.list_box.SetFocus()

    def on_clear(self, event) -> None:
        if self.list_box.GetCount() == 0:
            return
        if (
            wx.MessageBox(
                _("Remove all items from the play queue?"),
                _("Clear Play Queue"),
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            != wx.YES
        ):
            return
        try:
            self.controller.clear_play_queue()
        except Exception:
            log.exception("Failed to clear queue")
        self._reload()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self.FindFocus() is self.list_box:
            self.on_play(event)
            return
        event.Skip()

    def on_list_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_play(event)
            return
        if key in (wx.WXK_DELETE, wx.WXK_BACK):
            self.on_remove(event)
            return
        if key in (wx.WXK_UP, wx.WXK_DOWN) and event.AltDown():
            self.on_move(-1 if key == wx.WXK_UP else 1)
            return
        event.Skip()


class ShortcutCaptureDialog(wx.Dialog):
    """Prompt the user to press a keystroke; returns its canonical accel string.

    Only combinations with at least one modifier are accepted so a bound
    shortcut can never shadow plain typing or list navigation. Escape cancels.
    """

    def __init__(self, parent, command_label: str):
        super().__init__(parent, title=_("Press Shortcut"))
        self.result = None

        outer = wx.BoxSizer(wx.VERTICAL)
        prompt = wx.StaticText(
            self,
            label=_("Press the new shortcut for “{command}”.\n"
                    "It must include Ctrl, Alt or Shift. Press Escape to cancel.").format(
                command=command_label
            ),
        )
        outer.Add(prompt, 0, wx.ALL, 12)

        self.captured_lbl = wx.StaticText(self, label=_("Waiting for a key…"))
        self.captured_lbl.SetName(_("Captured keyboard shortcut"))
        outer.Add(self.captured_lbl, 0, wx.ALL, 12)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            outer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 8)
        self.SetSizer(outer)
        self.Fit()
        self.Centre()

        self._ok_btn = self.FindWindowById(wx.ID_OK)
        if self._ok_btn is not None:
            self._ok_btn.Enable(False)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        try:
            key = int(event.GetKeyCode())
        except Exception:
            key = None
        # Escape cancels; Enter confirms an existing capture.
        if key == wx.WXK_ESCAPE and not (event.ControlDown() or event.AltDown() or event.ShiftDown()):
            self.EndModal(wx.ID_CANCEL)
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not (
            event.ControlDown() or event.AltDown() or event.ShiftDown()
        ):
            if self.result:
                self.EndModal(wx.ID_OK)
            return
        accel = None
        try:
            accel = event_to_accel(event, require_modifier=True)
        except Exception:
            accel = None
        if accel:
            self.result = accel
            self.captured_lbl.SetLabel(accel)
            if self._ok_btn is not None:
                self._ok_btn.Enable(True)
            return
        event.Skip()

    def _on_ok(self, event) -> None:
        if self.result:
            self.EndModal(wx.ID_OK)


class KeyboardShortcutsDialog(wx.Dialog):
    """View and customize keyboard shortcuts (NVDA input-gestures style).

    `controller` is the MainFrame; it exposes get_shortcut_overrides(),
    save_shortcut_overrides(dict). Command metadata + binding resolution come
    from core.shortcuts. Changes apply immediately.
    """

    def __init__(self, parent, controller):
        super().__init__(
            parent,
            title=_("Keyboard Shortcuts"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.controller = controller
        # Working copy of user overrides; applied to the app on every edit.
        self._overrides = dict(controller.get_shortcut_overrides() or {})
        self._row_commands = []  # row index -> command id

        outer = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(
            self,
            label=_("Select a command and choose Change to set its shortcut."),
        )
        outer.Add(info, 0, wx.ALL, 8)

        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.SetName(_("Keyboard shortcuts"))
        self.list_ctrl.InsertColumn(0, _("Category"), width=130)
        self.list_ctrl.InsertColumn(1, _("Command"), width=230)
        self.list_ctrl.InsertColumn(2, _("Shortcut"), width=150)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.on_change())
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._update_buttons())
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda e: self._update_buttons())
        outer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.change_btn = wx.Button(self, label=_("&Change Shortcut..."))
        self.change_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_change())
        btn_sizer.Add(self.change_btn, 0, wx.ALL, 4)

        self.remove_btn = wx.Button(self, label=_("&Remove Shortcut"))
        self.remove_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_remove())
        btn_sizer.Add(self.remove_btn, 0, wx.ALL, 4)

        self.reset_btn = wx.Button(self, label=_("Reset All to &Defaults"))
        self.reset_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_reset())
        btn_sizer.Add(self.reset_btn, 0, wx.ALL, 4)

        outer.Add(btn_sizer, 0, wx.ALIGN_CENTER)

        close_sizer = self.CreateButtonSizer(wx.CLOSE)
        if close_sizer:
            outer.Add(close_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 8)
        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)

        self.SetSizer(outer)
        self.SetSize((560, 420))
        self.Centre()

        self._reload(select=0)

    def _effective(self) -> dict:
        return shortcuts_mod.resolve_bindings(self._overrides)

    # Keys that are part of a control's own behavior (or a native accelerator)
    # rather than the editable registry. Listed read-only so the dialog is a
    # complete keyboard reference; Change/Remove are disabled on these rows.
    def _fixed_rows(self):
        return (
            (_("Enter"), _("Open or play the selected article")),
            (_("Del"), _("Delete the selected article")),
            (_("Shift+Del"), _("Delete the selected article without confirmation")),
            (_("Backspace"), _("Toggle read/unread in the article list")),
            ("Ctrl+R", _("Refresh feeds (fixed alias)")),
            (_("Ctrl+Left / Ctrl+Right"), _("Rewind / fast forward playback")),
            (_("Ctrl+Up / Ctrl+Down"), _("Volume up / volume down")),
            (_("Ctrl+Shift+Left / Ctrl+Shift+Right"), _("Previous / next chapter")),
            (_("Ctrl+F"), _("Find in the article reader")),
            (_("F3 / Shift+F3"), _("Next / previous match in the article reader")),
            (_("F6 / Shift+F6"), _("Move between panes in the rich view")),
            (_("Ctrl+X / Ctrl+C / Ctrl+V / Ctrl+A"), _("Cut / Copy / Paste / Select All in text fields")),
        )

    def _reload(self, select: int | None = None) -> None:
        eff = self._effective()
        self.list_ctrl.DeleteAllItems()
        self._row_commands = []
        for cmd in shortcuts_mod.iter_commands():
            accel = eff.get(cmd.id, "") or ""
            row = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), _(cmd.category))
            self.list_ctrl.SetItem(row, 1, _(cmd.label))
            self.list_ctrl.SetItem(row, 2, accel if accel else _("(none)"))
            self._row_commands.append(cmd.id)
        for keys, description in self._fixed_rows():
            row = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), _("Fixed keys"))
            self.list_ctrl.SetItem(row, 1, description)
            self.list_ctrl.SetItem(row, 2, keys)
            self._row_commands.append(None)
        if self._row_commands:
            if select is None:
                select = 0
            select = max(0, min(int(select), len(self._row_commands) - 1))
            self.list_ctrl.Select(select)
            self.list_ctrl.Focus(select)
        self._update_buttons()

    def _selected_row(self) -> int:
        return self.list_ctrl.GetNextItem(-1, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)

    def _selected_command(self):
        row = self._selected_row()
        if 0 <= row < len(self._row_commands):
            return self._row_commands[row]
        return None

    def _update_buttons(self) -> None:
        cmd_id = self._selected_command()
        has_sel = cmd_id is not None
        self.change_btn.Enable(has_sel)
        if has_sel:
            accel = self._effective().get(cmd_id, "")
            self.remove_btn.Enable(bool(accel))
        else:
            self.remove_btn.Enable(False)

    def _apply(self) -> None:
        try:
            self.controller.save_shortcut_overrides(dict(self._overrides))
        except Exception:
            log.exception("Failed to apply shortcut overrides")

    def on_change(self) -> None:
        cmd_id = self._selected_command()
        if cmd_id is None:
            return
        cmd = shortcuts_mod.command_by_id(cmd_id)
        label = _(cmd.label) if cmd else cmd_id
        row = self._selected_row()
        dlg = ShortcutCaptureDialog(self, label)
        try:
            if dlg.ShowModal() != wx.ID_OK or not dlg.result:
                return
            accel = dlg.result
        finally:
            dlg.Destroy()

        # Conflict: the accel is already bound to a different command.
        eff = self._effective()
        for other_id, other_accel in eff.items():
            if other_id != cmd_id and other_accel and other_accel == accel:
                other_cmd = shortcuts_mod.command_by_id(other_id)
                other_label = _(other_cmd.label) if other_cmd else other_id
                if (
                    wx.MessageBox(
                        _("{accel} is already assigned to “{other}”.\n"
                          "Reassign it to “{this}”?").format(
                            accel=accel, other=other_label, this=label
                        ),
                        _("Shortcut Conflict"),
                        wx.YES_NO | wx.ICON_QUESTION,
                        self,
                    )
                    != wx.YES
                ):
                    return
                self._overrides[other_id] = ""  # unbind the other command
                break

        self._overrides[cmd_id] = accel
        self._apply()
        self._reload(select=row)
        self.list_ctrl.SetFocus()

    def on_remove(self) -> None:
        cmd_id = self._selected_command()
        if cmd_id is None:
            return
        row = self._selected_row()
        self._overrides[cmd_id] = ""  # explicitly unbound
        self._apply()
        self._reload(select=row)
        self.list_ctrl.SetFocus()

    def on_reset(self) -> None:
        if (
            wx.MessageBox(
                _("Reset all keyboard shortcuts to their defaults?"),
                _("Reset Shortcuts"),
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            != wx.YES
        ):
            return
        row = self._selected_row()
        self._overrides = {}
        self._apply()
        self._reload(select=row if row >= 0 else 0)
        self.list_ctrl.SetFocus()


class _EqSliderAccessible(wx.Accessible):
    """Accessible object for an equalizer slider.

    Reports a stable, meaningful name (e.g. "60 Hz") and a value in the
    control's real units ("+3 dB") instead of NVDA's default percentage of
    the -20..20 range (which reads 0 dB as a confusing "50").
    """

    def __init__(self, slider: "wx.Slider", label_text: str):
        super().__init__(slider)
        self._slider = slider
        self._label = label_text

    def GetName(self, childId):
        return (wx.ACC_OK, self._label)

    def GetRole(self, childId):
        return (wx.ACC_OK, wx.ROLE_SYSTEM_SLIDER)

    def GetValue(self, childId):
        try:
            v = int(round(self._slider.GetValue()))
        except Exception:
            return (wx.ACC_NOT_IMPLEMENTED, "")
        sign = "+" if v > 0 else ""
        return (wx.ACC_OK, _("{sign}{v} dB").format(sign=sign, v=v))


class EqualizerDialog(wx.Dialog):
    """10-band graphic equalizer for the media player.

    `player` is the PlayerFrame; it exposes get_equalizer_config(),
    set_equalizer_config(cfg, persist, apply), and list_equalizer_presets().
    Changes apply live so the effect is audible while adjusting.
    """

    def __init__(self, parent, player):
        super().__init__(
            parent,
            title=_("Equalizer"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.player = player
        self._cfg = equalizer_mod.normalize_config(player.get_equalizer_config())
        self._updating = False
        try:
            self._builtin_presets = list(player.list_equalizer_presets() or [])
        except Exception:
            self._builtin_presets = []
        # Real libVLC band center frequencies so the sliders are labeled with
        # what the engine actually filters (falls back to the constants).
        try:
            freq_fn = getattr(player, "get_equalizer_band_frequencies", None)
            self._band_freqs = list(freq_fn() or []) if callable(freq_fn) else []
        except Exception:
            self._band_freqs = []
        if not self._band_freqs:
            self._band_freqs = list(equalizer_mod.BAND_FREQUENCIES)
        # Combined preset entries aligned to choice indices 1..N (0 == Custom):
        # each is (kind, name, preamp, bands) with kind in {"builtin", "user"}.
        self._preset_entries = []

        outer = wx.BoxSizer(wx.VERTICAL)

        self.enable_cb = wx.CheckBox(self, label=_("&Enable equalizer"))
        self.enable_cb.SetValue(bool(self._cfg.get("enabled")))
        self.enable_cb.Bind(wx.EVT_CHECKBOX, self.on_enable)
        outer.Add(self.enable_cb, 0, wx.ALL, 8)

        # Preset chooser.
        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        preset_row.Add(wx.StaticText(self, label=_("&Preset:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.preset_choice = wx.Choice(self)
        self.preset_choice.SetName(_("Preset"))
        self.preset_choice.Bind(wx.EVT_CHOICE, self.on_preset)
        preset_row.Add(self.preset_choice, 1, wx.EXPAND)
        outer.Add(preset_row, 0, wx.EXPAND | wx.ALL, 8)

        grid = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
        grid.AddGrowableCol(1, 1)

        # Preamp.
        self.preamp_slider = self._make_slider(grid, _("Preamp"), self._cfg.get("preamp", 0.0))

        # Bands. Labels come from the real libVLC band frequencies.
        self.band_sliders = []
        for i in range(equalizer_mod.BAND_COUNT):
            if i < len(self._band_freqs):
                freq = self._band_freqs[i]
            elif i < len(equalizer_mod.BAND_FREQUENCIES):
                freq = equalizer_mod.BAND_FREQUENCIES[i]
            else:
                freq = i + 1
            label = equalizer_mod.format_band_label(freq)
            val = self._cfg["bands"][i] if i < len(self._cfg["bands"]) else 0.0
            slider = self._make_slider(grid, label, val)
            self.band_sliders.append(slider)

        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.save_preset_btn = wx.Button(self, label=_("&Save as Preset..."))
        self.save_preset_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_save_preset())
        btn_sizer.Add(self.save_preset_btn, 0, wx.ALL, 4)
        self.delete_preset_btn = wx.Button(self, label=_("&Delete Preset"))
        self.delete_preset_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_delete_preset())
        btn_sizer.Add(self.delete_preset_btn, 0, wx.ALL, 4)
        self.reset_btn = wx.Button(self, label=_("&Reset (Flat)"))
        self.reset_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_reset())
        btn_sizer.Add(self.reset_btn, 0, wx.ALL, 4)
        outer.Add(btn_sizer, 0, wx.ALIGN_CENTER)

        # Populate the preset dropdown (built-in + user presets) and select the
        # last-applied preset if the persisted config named one.
        self._rebuild_preset_choice(select_name=self._cfg.get("preset"))

        close_sizer = self.CreateButtonSizer(wx.CLOSE)
        if close_sizer:
            outer.Add(close_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 8)
        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)

        self.SetSizer(outer)
        self.SetSize((460, 520))
        self.Centre()
        self._sync_enabled_state()

    def _make_slider(self, grid, label_text: str, value: float) -> wx.Slider:
        lbl = wx.StaticText(self, label=label_text)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        # NOTE: no wx.SL_LABELS. On Windows that style builds a composite
        # control with value-label children, and NVDA reads a child "0" label
        # as the slider's name instead of the name set below.
        slider = wx.Slider(
            self,
            value=int(round(float(value))),
            minValue=int(equalizer_mod.AMP_MIN),
            maxValue=int(equalizer_mod.AMP_MAX),
            style=wx.SL_HORIZONTAL,
        )
        # Fallback accessible name (used if SetAccessible is unavailable).
        slider.SetName(label_text)
        # Preferred: report a real name and a dB value to screen readers.
        try:
            slider._acc = _EqSliderAccessible(slider, label_text)
            slider.SetAccessible(slider._acc)
        except Exception:
            log.debug("SetAccessible unavailable for equalizer slider", exc_info=True)
        slider.Bind(wx.EVT_SLIDER, self.on_slider)
        grid.Add(slider, 1, wx.EXPAND)
        return slider

    def _rebuild_preset_choice(self, select_name=None, select_kind=None) -> None:
        """Repopulate the preset dropdown from built-in + user presets.

        Builds self._preset_entries as (kind, name, preamp, bands) aligned to
        choice indices 1..N (index 0 is "Custom"). User presets are suffixed so
        the user can tell which ones they can delete.
        """
        try:
            user_fn = getattr(self.player, "list_user_equalizer_presets", None)
            user_presets = list(user_fn() or []) if callable(user_fn) else []
        except Exception:
            user_presets = []

        entries = []
        labels = [_("Custom")]
        for (name, preamp, bands) in self._builtin_presets:
            entries.append(("builtin", name, preamp, list(bands)))
            labels.append(str(name))
        for (name, preamp, bands) in user_presets:
            entries.append(("user", name, preamp, list(bands)))
            labels.append(_("{name} (my preset)").format(name=name))
        self._preset_entries = entries

        self.preset_choice.Set(labels)
        target = 0
        if select_name:
            for i, (kind, name, _p, _b) in enumerate(entries, start=1):
                if name == select_name and (select_kind is None or kind == select_kind):
                    target = i
                    break
        self.preset_choice.SetSelection(target)
        self._update_preset_buttons()

    def _selected_preset_entry(self):
        sel = self.preset_choice.GetSelection()
        if sel <= 0 or (sel - 1) >= len(self._preset_entries):
            return None
        return self._preset_entries[sel - 1]

    def _update_preset_buttons(self) -> None:
        on = bool(self.enable_cb.GetValue())
        entry = self._selected_preset_entry()
        is_user = bool(entry and entry[0] == "user")
        try:
            self.save_preset_btn.Enable(on)
            self.delete_preset_btn.Enable(on and is_user)
        except Exception:
            pass

    def _sync_enabled_state(self) -> None:
        on = self.enable_cb.GetValue()
        self.preset_choice.Enable(on)
        self.preamp_slider.Enable(on)
        for s in self.band_sliders:
            s.Enable(on)
        self.reset_btn.Enable(on)
        self._update_preset_buttons()

    def _collect_and_apply(self, *, mark_custom: bool = True) -> None:
        if self._updating:
            return
        cfg = {
            "enabled": bool(self.enable_cb.GetValue()),
            "preamp": float(self.preamp_slider.GetValue()),
            "bands": [float(s.GetValue()) for s in self.band_sliders],
            "preset": None if mark_custom else self._cfg.get("preset"),
        }
        self._cfg = equalizer_mod.normalize_config(cfg)
        try:
            self.player.set_equalizer_config(self._cfg, persist=True, apply=True)
        except Exception:
            log.exception("Failed to apply equalizer config")

    def on_enable(self, event) -> None:
        self._sync_enabled_state()
        self._collect_and_apply(mark_custom=False)

    def on_slider(self, event) -> None:
        if not self._updating:
            self.preset_choice.SetSelection(0)  # editing => Custom
            self._update_preset_buttons()
        self._collect_and_apply()

    def on_preset(self, event) -> None:
        entry = self._selected_preset_entry()
        self._update_preset_buttons()
        if entry is None:
            return
        _kind, name, preamp, bands = entry
        self._updating = True
        try:
            self.preamp_slider.SetValue(int(round(preamp)))
            for i, s in enumerate(self.band_sliders):
                s.SetValue(int(round(bands[i])) if i < len(bands) else 0)
        finally:
            self._updating = False
        self._cfg["preset"] = name
        self._collect_and_apply(mark_custom=False)

    def on_save_preset(self) -> None:
        name = wx.GetTextFromUser(
            _("Name for this equalizer preset:"), _("Save Preset"), parent=self
        )
        name = (name or "").strip()
        if not name:
            return
        # Warn before overwriting an existing user preset of the same name.
        existing = {
            n.lower() for (k, n, _p, _b) in self._preset_entries if k == "user"
        }
        if name.lower() in existing:
            if wx.MessageBox(
                _("A preset named \"{name}\" already exists. Overwrite it?").format(name=name),
                _("Save Preset"),
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            ) != wx.YES:
                return
        preamp = float(self.preamp_slider.GetValue())
        bands = [float(s.GetValue()) for s in self.band_sliders]
        try:
            save_fn = getattr(self.player, "save_user_equalizer_preset", None)
            ok = bool(save_fn(name, preamp, bands)) if callable(save_fn) else False
        except Exception:
            log.exception("Failed to save equalizer preset")
            ok = False
        if not ok:
            wx.MessageBox(_("Could not save the preset."), _("Save Preset"), wx.ICON_ERROR, self)
            return
        self._cfg["preset"] = name
        self._rebuild_preset_choice(select_name=name, select_kind="user")

    def on_delete_preset(self) -> None:
        entry = self._selected_preset_entry()
        if entry is None or entry[0] != "user":
            return
        name = entry[1]
        if wx.MessageBox(
            _("Delete the preset \"{name}\"?").format(name=name),
            _("Delete Preset"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) != wx.YES:
            return
        try:
            del_fn = getattr(self.player, "delete_user_equalizer_preset", None)
            if callable(del_fn):
                del_fn(name)
        except Exception:
            log.exception("Failed to delete equalizer preset")
        if self._cfg.get("preset") == name:
            self._cfg["preset"] = None
        self._rebuild_preset_choice(select_name=None)

    def on_reset(self) -> None:
        self._updating = True
        try:
            self.preamp_slider.SetValue(0)
            for s in self.band_sliders:
                s.SetValue(0)
            self.preset_choice.SetSelection(0)
        finally:
            self._updating = False
        self._update_preset_buttons()
        self._collect_and_apply()
