import wx
import wx.adv
import copy
import queue
import threading
import webbrowser
import time
import logging
import sys
from urllib.parse import urlparse
from core.discovery import discover_feed, is_ytdlp_supported, search_youtube_feeds
from core import utils
from core.casting import CastingManager
from core import inoreader_oauth
from core import translation as translation_mod

log = logging.getLogger(__name__)


class AddFeedDialog(wx.Dialog):
    def __init__(self, parent, categories=None):
        super().__init__(parent, title="Add Feed", size=(400, 250))
        
        self.categories = categories or ["Uncategorized"]
        self._check_timer = None
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # URL Input
        sizer.Add(wx.StaticText(self, label="Feed or Media URL:"), 0, wx.ALL, 5)
        self.url_ctrl = wx.TextCtrl(self)
        wx.CallAfter(self.url_ctrl.SetFocus)
        sizer.Add(self.url_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Compatibility Hint
        self.status_lbl = wx.StaticText(self, label="")
        self.status_lbl.SetForegroundColour(wx.Colour(0, 128, 0)) # Greenish
        sizer.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # Category Input
        sizer.Add(wx.StaticText(self, label="Category:"), 0, wx.ALL, 5)
        self.cat_ctrl = wx.ComboBox(self, choices=self.categories, style=wx.CB_DROPDOWN)
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
            self.status_lbl.SetLabel("OK: Recognized as YouTube source")
            # Auto-switch category to YouTube if available
            yt_idx = self.cat_ctrl.FindString("YouTube")
            if yt_idx != wx.NOT_FOUND:
                self.cat_ctrl.SetSelection(yt_idx)
            return

        self.status_lbl.SetLabel("Checking compatibility...")
        # Background thread for heavier yt-dlp check
        threading.Thread(target=self._heavy_check, args=(url,), daemon=True).start()

    def _heavy_check(self, url):
        if is_ytdlp_supported(url):
            wx.CallAfter(self.status_lbl.SetLabel, "OK: Supported by yt-dlp")
        else:
            wx.CallAfter(self.status_lbl.SetLabel, "")

    def get_data(self):
        return self.url_ctrl.GetValue(), self.cat_ctrl.GetValue()


class AddShortcutsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Add BlindRSS Shortcuts", size=(460, 280))

        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = (
            "Choose where to add BlindRSS shortcuts.\n"
            "Taskbar pinning may be limited by your Windows version/policies."
        )
        sizer.Add(wx.StaticText(self, label=intro), 0, wx.ALL, 10)

        self.desktop_chk = wx.CheckBox(self, label="Desktop")
        self.desktop_chk.SetValue(True)
        sizer.Add(self.desktop_chk, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.start_menu_chk = wx.CheckBox(self, label="Start Menu")
        self.start_menu_chk.SetValue(True)
        sizer.Add(self.start_menu_chk, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.taskbar_chk = wx.CheckBox(self, label="Taskbar")
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
        super().__init__(parent, title="Exclude Feeds from Notifications", size=(480, 420))
        self._feed_entries = list(feed_entries or [])
        self._excluded_ids = {str(x) for x in (excluded_ids or []) if str(x or "").strip()}
        self._feed_id_by_index = {}
        self._feed_base_labels = []

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            wx.StaticText(
                self,
                label=(
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

        self.feed_list = wx.CheckListBox(self, choices=labels)
        sizer.Add(self.feed_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        for idx, fid in self._feed_id_by_index.items():
            should_notify = fid not in self._excluded_ids
            try:
                self.feed_list.Check(idx, should_notify)
            except Exception:
                pass

        self._selection_status = wx.StaticText(self, label="")
        sizer.Add(self._selection_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._refresh_item_labels()
        self.feed_list.Bind(wx.EVT_LISTBOX, self.on_feed_selected)
        self.feed_list.Bind(wx.EVT_CHECKLISTBOX, self.on_feed_toggled)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        check_all_btn = wx.Button(self, label="Check All")
        uncheck_all_btn = wx.Button(self, label="Uncheck All")
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
            self._selection_status.SetLabel("No feeds available.")
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

    def _build_item_label(self, index):
        if index < 0 or index >= len(self._feed_base_labels):
            return ""
        checked = self._is_checked(index)
        check_state = "checked" if checked else "unchecked"
        return f"{self._feed_base_labels[index]} - {check_state}"

    def _refresh_item_labels(self):
        for i in range(self.feed_list.GetCount()):
            checked = self._is_checked(i)
            label = self._build_item_label(i)
            try:
                self.feed_list.SetString(i, label)
                self.feed_list.Check(i, checked)
            except Exception:
                pass

    def _update_selection_status(self, index=None):
        if index is None or index == wx.NOT_FOUND:
            try:
                index = self.feed_list.GetSelection()
            except Exception:
                index = wx.NOT_FOUND
        if index == wx.NOT_FOUND:
            self._selection_status.SetLabel("No feed selected.")
            return
        if index < 0 or index >= len(self._feed_base_labels):
            self._selection_status.SetLabel("")
            return
        checked = self._is_checked(index)
        check_state = "checked" if checked else "unchecked"
        self._selection_status.SetLabel(
            f"Selected feed: {self._feed_base_labels[index]}. {check_state}."
        )

    def on_feed_selected(self, event):
        self._update_selection_status(event.GetInt())
        event.Skip()

    def on_feed_toggled(self, event):
        index = event.GetInt()
        checked = self._is_checked(index)
        label = self._build_item_label(index)
        try:
            self.feed_list.SetString(index, label)
            self.feed_list.Check(index, checked)
        except Exception:
            pass
        self._update_selection_status(index)
        event.Skip()

    def on_check_all(self, event):
        try:
            for i in range(self.feed_list.GetCount()):
                self.feed_list.Check(i, True)
        except Exception:
            pass
        self._refresh_item_labels()
        self._update_selection_status()

    def on_uncheck_all(self, event):
        try:
            for i in range(self.feed_list.GetCount()):
                self.feed_list.Check(i, False)
        except Exception:
            pass
        self._refresh_item_labels()
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


class SettingsDialog(wx.Dialog):
    _TRANSLATION_LANGUAGE_PRESETS = [
        ("Abkhazian (ab)", "ab"),
        ("Afar (aa)", "aa"),
        ("Afrikaans (af)", "af"),
        ("Akan (ak)", "ak"),
        ("Albanian (sq)", "sq"),
        ("Amharic (am)", "am"),
        ("Arabic (ar)", "ar"),
        ("Aragonese (an)", "an"),
        ("Armenian (hy)", "hy"),
        ("Assamese (as)", "as"),
        ("Avaric (av)", "av"),
        ("Avestan (ae)", "ae"),
        ("Aymara (ay)", "ay"),
        ("Azerbaijani (az)", "az"),
        ("Bambara (bm)", "bm"),
        ("Bashkir (ba)", "ba"),
        ("Basque (eu)", "eu"),
        ("Belarusian (be)", "be"),
        ("Bengali (bn)", "bn"),
        ("Bislama (bi)", "bi"),
        ("Bosnian (bs)", "bs"),
        ("Breton (br)", "br"),
        ("Bulgarian (bg)", "bg"),
        ("Burmese (my)", "my"),
        ("Catalan (ca)", "ca"),
        ("Chamorro (ch)", "ch"),
        ("Chechen (ce)", "ce"),
        ("Chichewa (ny)", "ny"),
        ("Chinese (Simplified) (zh-CN)", "zh-CN"),
        ("Chinese (Traditional) (zh-TW)", "zh-TW"),
        ("Chinese (zh)", "zh"),
        ("Church Slavic (cu)", "cu"),
        ("Chuvash (cv)", "cv"),
        ("Cornish (kw)", "kw"),
        ("Corsican (co)", "co"),
        ("Cree (cr)", "cr"),
        ("Croatian (hr)", "hr"),
        ("Czech (cs)", "cs"),
        ("Danish (da)", "da"),
        ("Divehi (dv)", "dv"),
        ("Dutch (nl)", "nl"),
        ("Dzongkha (dz)", "dz"),
        ("English (en)", "en"),
        ("Esperanto (eo)", "eo"),
        ("Estonian (et)", "et"),
        ("Ewe (ee)", "ee"),
        ("Faroese (fo)", "fo"),
        ("Fijian (fj)", "fj"),
        ("Finnish (fi)", "fi"),
        ("French (fr)", "fr"),
        ("Fulah (ff)", "ff"),
        ("Galician (gl)", "gl"),
        ("Ganda (lg)", "lg"),
        ("Georgian (ka)", "ka"),
        ("German (de)", "de"),
        ("Guarani (gn)", "gn"),
        ("Gujarati (gu)", "gu"),
        ("Haitian (ht)", "ht"),
        ("Hausa (ha)", "ha"),
        ("Hebrew (he)", "he"),
        ("Herero (hz)", "hz"),
        ("Hindi (hi)", "hi"),
        ("Hiri Motu (ho)", "ho"),
        ("Hungarian (hu)", "hu"),
        ("Icelandic (is)", "is"),
        ("Ido (io)", "io"),
        ("Igbo (ig)", "ig"),
        ("Indonesian (id)", "id"),
        ("Interlingua (International Auxiliary Language Association) (ia)", "ia"),
        ("Interlingue (ie)", "ie"),
        ("Inuktitut (iu)", "iu"),
        ("Inupiaq (ik)", "ik"),
        ("Irish (ga)", "ga"),
        ("Italian (it)", "it"),
        ("Japanese (ja)", "ja"),
        ("Javanese (jv)", "jv"),
        ("Kalaallisut (kl)", "kl"),
        ("Kannada (kn)", "kn"),
        ("Kanuri (kr)", "kr"),
        ("Kashmiri (ks)", "ks"),
        ("Kazakh (kk)", "kk"),
        ("Khmer (km)", "km"),
        ("Kikuyu (ki)", "ki"),
        ("Kinyarwanda (rw)", "rw"),
        ("Kirghiz (ky)", "ky"),
        ("Komi (kv)", "kv"),
        ("Kongo (kg)", "kg"),
        ("Korean (ko)", "ko"),
        ("Kuanyama (kj)", "kj"),
        ("Kurdish (ku)", "ku"),
        ("Lao (lo)", "lo"),
        ("Latin (la)", "la"),
        ("Latvian (lv)", "lv"),
        ("Limburgan (li)", "li"),
        ("Lingala (ln)", "ln"),
        ("Lithuanian (lt)", "lt"),
        ("Luba-Katanga (lu)", "lu"),
        ("Luxembourgish (lb)", "lb"),
        ("Macedonian (mk)", "mk"),
        ("Malagasy (mg)", "mg"),
        ("Malay (macrolanguage) (ms)", "ms"),
        ("Malayalam (ml)", "ml"),
        ("Maltese (mt)", "mt"),
        ("Manx (gv)", "gv"),
        ("Maori (mi)", "mi"),
        ("Marathi (mr)", "mr"),
        ("Marshallese (mh)", "mh"),
        ("Modern Greek (1453-) (el)", "el"),
        ("Mongolian (mn)", "mn"),
        ("Nauru (na)", "na"),
        ("Navajo (nv)", "nv"),
        ("Ndonga (ng)", "ng"),
        ("Nepali (macrolanguage) (ne)", "ne"),
        ("North Ndebele (nd)", "nd"),
        ("Northern Sami (se)", "se"),
        ("Norwegian (no)", "no"),
        ("Norwegian Bokmal (nb)", "nb"),
        ("Norwegian Nynorsk (nn)", "nn"),
        ("Occitan (post 1500) (oc)", "oc"),
        ("Ojibwa (oj)", "oj"),
        ("Oriya (macrolanguage) (or)", "or"),
        ("Oromo (om)", "om"),
        ("Ossetian (os)", "os"),
        ("Pali (pi)", "pi"),
        ("Panjabi (pa)", "pa"),
        ("Persian (fa)", "fa"),
        ("Polish (pl)", "pl"),
        ("Portuguese (Brazil) (pt-BR)", "pt-BR"),
        ("Portuguese (Portugal) (pt-PT)", "pt-PT"),
        ("Portuguese (pt)", "pt"),
        ("Pushto (ps)", "ps"),
        ("Quechua (qu)", "qu"),
        ("Romanian (ro)", "ro"),
        ("Romansh (rm)", "rm"),
        ("Rundi (rn)", "rn"),
        ("Russian (ru)", "ru"),
        ("Samoan (sm)", "sm"),
        ("Sango (sg)", "sg"),
        ("Sanskrit (sa)", "sa"),
        ("Sardinian (sc)", "sc"),
        ("Scottish Gaelic (gd)", "gd"),
        ("Serbian (sr)", "sr"),
        ("Serbo-Croatian (sh)", "sh"),
        ("Shona (sn)", "sn"),
        ("Sichuan Yi (ii)", "ii"),
        ("Sindhi (sd)", "sd"),
        ("Sinhala (si)", "si"),
        ("Slovak (sk)", "sk"),
        ("Slovenian (sl)", "sl"),
        ("Somali (so)", "so"),
        ("South Ndebele (nr)", "nr"),
        ("Southern Sotho (st)", "st"),
        ("Spanish (es)", "es"),
        ("Sundanese (su)", "su"),
        ("Swahili (macrolanguage) (sw)", "sw"),
        ("Swati (ss)", "ss"),
        ("Swedish (sv)", "sv"),
        ("Tagalog (tl)", "tl"),
        ("Tahitian (ty)", "ty"),
        ("Tajik (tg)", "tg"),
        ("Tamil (ta)", "ta"),
        ("Tatar (tt)", "tt"),
        ("Telugu (te)", "te"),
        ("Thai (th)", "th"),
        ("Tibetan (bo)", "bo"),
        ("Tigrinya (ti)", "ti"),
        ("Tonga (Tonga Islands) (to)", "to"),
        ("Tsonga (ts)", "ts"),
        ("Tswana (tn)", "tn"),
        ("Turkish (tr)", "tr"),
        ("Turkmen (tk)", "tk"),
        ("Twi (tw)", "tw"),
        ("Uighur (ug)", "ug"),
        ("Ukrainian (uk)", "uk"),
        ("Urdu (ur)", "ur"),
        ("Uzbek (uz)", "uz"),
        ("Venda (ve)", "ve"),
        ("Vietnamese (vi)", "vi"),
        ("Volapuk (vo)", "vo"),
        ("Walloon (wa)", "wa"),
        ("Welsh (cy)", "cy"),
        ("Western Frisian (fy)", "fy"),
        ("Wolof (wo)", "wo"),
        ("Xhosa (xh)", "xh"),
        ("Yiddish (yi)", "yi"),
        ("Yoruba (yo)", "yo"),
        ("Zhuang (za)", "za"),
        ("Zulu (zu)", "zu"),
    ]

    def __init__(self, parent, config, notification_feeds=None):
        super().__init__(parent, title="Settings", size=(500, 450))
        
        self.config = config
        self._notification_feed_entries = list(notification_feeds or [])
        self._notification_excluded_feed_ids = {
            str(x) for x in (config.get("windows_notifications_excluded_feeds", []) or []) if str(x or "").strip()
        }
        
        notebook = wx.Notebook(self)
        
        # General Tab
        general_panel = wx.Panel(notebook)
        general_sizer = wx.BoxSizer(wx.VERTICAL)
        
        refresh_sizer = wx.BoxSizer(wx.HORIZONTAL)
        refresh_sizer.Add(wx.StaticText(general_panel, label="Refresh Interval:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.refresh_map = {
            "Never": 0,
            "30 seconds": 30,
            "1 minute": 60,
            "2 minutes": 120,
            "3 minutes": 180,
            "4 minutes": 240,
            "5 minutes": 300,
            "10 minutes": 600,
            "15 minutes": 900,
            "30 minutes": 1800,
            "60 minutes": 3600,
            "2 hours": 7200,
            "3 hours": 10800,
            "4 hours": 14400
        }
        self.refresh_choices = list(self.refresh_map.keys())
        self.refresh_ctrl = wx.Choice(general_panel, choices=self.refresh_choices)
        
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
        general_sizer.Add(refresh_sizer, 0, wx.EXPAND | wx.ALL, 5)

        search_mode_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_mode_sizer.Add(wx.StaticText(general_panel, label="Search Matches:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.search_mode_map = {
            "Titles only": "title_only",
            "Titles + article text": "title_content",
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
            selected_label = "Titles + article text"
        self.search_mode_ctrl.SetStringSelection(selected_label)
        search_mode_sizer.Add(self.search_mode_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(search_mode_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        concurrency_sizer = wx.BoxSizer(wx.HORIZONTAL)
        concurrency_sizer.Add(wx.StaticText(general_panel, label="Max Concurrent Refreshes:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.concurrent_ctrl = wx.SpinCtrl(general_panel, min=1, max=50, initial=int(config.get("max_concurrent_refreshes", 5)))
        concurrency_sizer.Add(self.concurrent_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(concurrency_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        per_host_sizer = wx.BoxSizer(wx.HORIZONTAL)
        per_host_sizer.Add(wx.StaticText(general_panel, label="Max Connections Per Host:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.per_host_ctrl = wx.SpinCtrl(general_panel, min=1, max=10, initial=int(config.get("per_host_max_connections", 3)))
        per_host_sizer.Add(self.per_host_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(per_host_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        timeout_sizer = wx.BoxSizer(wx.HORIZONTAL)
        timeout_sizer.Add(wx.StaticText(general_panel, label="Feed Timeout (seconds):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.timeout_ctrl = wx.SpinCtrl(general_panel, min=5, max=120, initial=int(config.get("feed_timeout_seconds", 15)))
        timeout_sizer.Add(self.timeout_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(timeout_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        retry_sizer = wx.BoxSizer(wx.HORIZONTAL)
        retry_sizer.Add(wx.StaticText(general_panel, label="Feed Retry Attempts:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.retry_ctrl = wx.SpinCtrl(general_panel, min=0, max=5, initial=int(config.get("feed_retry_attempts", 1)))
        retry_sizer.Add(self.retry_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(retry_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Cache views
        cache_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cache_sizer.Add(wx.StaticText(general_panel, label="Max Cached Views:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.cache_ctrl = wx.SpinCtrl(general_panel, min=5, max=100, initial=int(config.get("max_cached_views", 15)))
        cache_sizer.Add(self.cache_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(cache_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Full-text caching
        self.cache_full_text_chk = wx.CheckBox(general_panel, label="Cache full text in background")
        self.cache_full_text_chk.SetValue(bool(config.get("cache_full_text", False)))
        general_sizer.Add(self.cache_full_text_chk, 0, wx.ALL, 5)
        
        # Downloads
        self.downloads_chk = wx.CheckBox(general_panel, label="Enable Downloads")
        self.downloads_chk.SetValue(config.get("downloads_enabled", False))
        general_sizer.Add(self.downloads_chk, 0, wx.ALL, 5)
        
        dl_path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dl_path_sizer.Add(wx.StaticText(general_panel, label="Download Path:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.dl_path_ctrl = wx.TextCtrl(general_panel, value=config.get("download_path", ""))
        dl_path_sizer.Add(self.dl_path_ctrl, 1, wx.ALL, 5)
        browse_btn = wx.Button(general_panel, label="Browse...")
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_dl_path)
        dl_path_sizer.Add(browse_btn, 0, wx.ALL, 5)
        general_sizer.Add(dl_path_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        retention_sizer = wx.BoxSizer(wx.HORIZONTAL)
        retention_sizer.Add(wx.StaticText(general_panel, label="Retention Policy:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        retention_opts = ["1 day", "3 days", "1 week", "2 weeks", "3 weeks", "1 month", "2 months", "6 months", "1 year", "2 years", "5 years", "Unlimited"]
        self.retention_ctrl = wx.ComboBox(general_panel, choices=retention_opts, style=wx.CB_READONLY)
        self.retention_ctrl.SetValue(config.get("download_retention", "Unlimited"))
        retention_sizer.Add(self.retention_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(retention_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        art_retention_sizer = wx.BoxSizer(wx.HORIZONTAL)
        art_retention_sizer.Add(wx.StaticText(general_panel, label="Article Retention:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.art_retention_ctrl = wx.ComboBox(general_panel, choices=retention_opts, style=wx.CB_READONLY)
        self.art_retention_ctrl.SetValue(config.get("article_retention", "Unlimited"))
        art_retention_sizer.Add(self.art_retention_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(art_retention_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Tray settings
        self.close_tray_chk = wx.CheckBox(general_panel, label="Close to Tray")
        self.close_tray_chk.SetValue(config.get("close_to_tray", False))
        general_sizer.Add(self.close_tray_chk, 0, wx.ALL, 5)
        
        self.min_tray_chk = wx.CheckBox(general_panel, label="Minimize to Tray")
        self.min_tray_chk.SetValue(config.get("minimize_to_tray", True))        
        general_sizer.Add(self.min_tray_chk, 0, wx.ALL, 5)

        self.start_maximized_chk = wx.CheckBox(general_panel, label="Always start maximized")
        self.start_maximized_chk.SetValue(bool(config.get("start_maximized", False)))
        general_sizer.Add(self.start_maximized_chk, 0, wx.ALL, 5)

        self.debug_mode_chk = wx.CheckBox(general_panel, label="Debug mode (show console on startup)")
        self.debug_mode_chk.SetValue(bool(config.get("debug_mode", False)))     
        general_sizer.Add(self.debug_mode_chk, 0, wx.ALL, 5)

        self.auto_update_chk = wx.CheckBox(general_panel, label="Check for updates on startup")
        self.auto_update_chk.SetValue(bool(config.get("auto_check_updates", True)))
        general_sizer.Add(self.auto_update_chk, 0, wx.ALL, 5)

        self.refresh_startup_chk = wx.CheckBox(general_panel, label="Automatically refresh feeds upon start")
        self.refresh_startup_chk.SetValue(bool(config.get("refresh_on_startup", True)))
        general_sizer.Add(self.refresh_startup_chk, 0, wx.ALL, 5)

        self.prompt_missing_deps_chk = wx.CheckBox(
            general_panel,
            label="Ask to install missing media dependencies on startup",
        )
        self.prompt_missing_deps_chk.SetValue(
            bool(config.get("prompt_missing_dependencies_on_startup", True))
        )
        general_sizer.Add(self.prompt_missing_deps_chk, 0, wx.ALL, 5)

        self.start_on_login_chk = wx.CheckBox(general_panel, label="Start BlindRSS when Windows starts")
        self.start_on_login_chk.SetValue(bool(config.get("start_on_windows_login", False)))
        if not sys.platform.startswith("win"):
            self.start_on_login_chk.Disable()
        general_sizer.Add(self.start_on_login_chk, 0, wx.ALL, 5)

        self.remember_last_feed_chk = wx.CheckBox(general_panel, label="Remember last selected feed/folder on startup")
        self.remember_last_feed_chk.SetValue(bool(config.get("remember_last_feed", False)))
        general_sizer.Add(self.remember_last_feed_chk, 0, wx.ALL, 5)
        
        general_panel.SetSizer(general_sizer)
        notebook.AddPage(general_panel, "General")

        # Media Player Tab
        media_panel = wx.Panel(notebook)
        media_sizer = wx.BoxSizer(wx.VERTICAL)

        # Preferred soundcard
        soundcard_sizer = wx.BoxSizer(wx.HORIZONTAL)
        soundcard_sizer.Add(wx.StaticText(media_panel, label="Preferred Soundcard:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        current_soundcard = str(config.get("preferred_soundcard", "") or "")
        self._soundcard_choices = self._build_soundcard_choices(current_soundcard)
        self._soundcard_labels = [label for label, _device_id in self._soundcard_choices]
        self.soundcard_ctrl = wx.Choice(media_panel, choices=self._soundcard_labels)
        sel_idx = 0
        for i, (_label, device_id) in enumerate(self._soundcard_choices):
            if str(device_id or "") == current_soundcard:
                sel_idx = i
                break
        self.soundcard_ctrl.SetSelection(sel_idx)
        soundcard_sizer.Add(self.soundcard_ctrl, 1, wx.ALL, 5)
        media_sizer.Add(soundcard_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.skip_silence_chk = wx.CheckBox(media_panel, label="Skip Silence (Experimental)")
        self.skip_silence_chk.SetValue(config.get("skip_silence", False))
        media_sizer.Add(self.skip_silence_chk, 0, wx.ALL, 5)

        # Playback speed
        speed_sizer = wx.BoxSizer(wx.HORIZONTAL)
        speed_sizer.Add(wx.StaticText(media_panel, label="Default Playback Speed:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

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
        self.show_player_on_play_chk = wx.CheckBox(media_panel, label="Show player window when starting playback")
        self.show_player_on_play_chk.SetValue(bool(config.get("show_player_on_play", True)))
        media_sizer.Add(self.show_player_on_play_chk, 0, wx.ALL, 5)

        # VLC network caching (helps on high latency streams)
        cache_net_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cache_net_sizer.Add(wx.StaticText(media_panel, label="Network Cache (ms):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.vlc_cache_ctrl = wx.SpinCtrl(media_panel, min=500, max=60000, initial=int(config.get("vlc_network_caching_ms", 5000)))
        cache_net_sizer.Add(self.vlc_cache_ctrl, 0, wx.ALL, 5)
        media_sizer.Add(cache_net_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.range_cache_debug_chk = wx.CheckBox(media_panel, label="Verbose range-cache proxy debug logs")
        self.range_cache_debug_chk.SetValue(bool(config.get("range_cache_debug", False)))
        media_sizer.Add(self.range_cache_debug_chk, 0, wx.ALL, 5)

        media_panel.SetSizer(media_sizer)
        notebook.AddPage(media_panel, "Media Player")
        
        # Provider Tab
        provider_panel = wx.Panel(notebook)
        provider_sizer = wx.BoxSizer(wx.VERTICAL)

        provider_sizer.Add(wx.StaticText(provider_panel, label="Active Provider:"), 0, wx.ALL, 5)

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
            s.Add(wx.StaticText(pnl, label=info_text), 0, wx.ALL, 5)
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

            fg.Add(wx.StaticText(pnl, label="Inoreader App ID:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
            app_id_ctrl = wx.TextCtrl(pnl)
            app_id_ctrl.SetValue(str(p_cfg.get("app_id", "") or ""))
            fg.Add(app_id_ctrl, 1, wx.EXPAND | wx.ALL, 2)
            ctrls["app_id"] = app_id_ctrl

            fg.Add(wx.StaticText(pnl, label="Inoreader App Key:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
            app_key_ctrl = wx.TextCtrl(pnl, style=wx.TE_PASSWORD)
            app_key_ctrl.SetValue(str(p_cfg.get("app_key", "") or ""))
            fg.Add(app_key_ctrl, 1, wx.EXPAND | wx.ALL, 2)
            ctrls["app_key"] = app_key_ctrl

            default_redirect_uri = inoreader_oauth.get_redirect_uri(scheme="https")
            redirect_uri_ctrl = wx.TextCtrl(pnl)
            redirect_uri_ctrl.SetValue(str(p_cfg.get("redirect_uri", "") or "").strip() or default_redirect_uri)
            fg.Add(wx.StaticText(pnl, label="Redirect URI:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)
            fg.Add(redirect_uri_ctrl, 1, wx.EXPAND | wx.ALL, 2)
            ctrls["redirect_uri"] = redirect_uri_ctrl

            outer.Add(fg, 0, wx.EXPAND | wx.ALL, 2)

            help_lbl = wx.StaticText(
                pnl,
                label=(
                    "Note: If your Redirect URI uses HTTPS (common/required), your browser may fail to load\n"
                    "localhost after authorization. Copy the full redirected URL from the address bar and paste it\n"
                    "when prompted."
                ),
            )
            outer.Add(help_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)

            status_lbl = wx.StaticText(pnl, label="")
            outer.Add(status_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 2)

            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            auth_btn = wx.Button(pnl, label="Authorize Inoreader")
            clear_btn = wx.Button(pnl, label="Clear Authorization")
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

        _add_simple_info_panel("local", "Local provider uses the feeds you add inside the app (Add Feed / Import OPML).")
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
        notebook.AddPage(provider_panel, "Provider")
        
        # Sounds Tab
        sounds_panel = wx.Panel(notebook)
        sounds_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.sounds_enabled_chk = wx.CheckBox(sounds_panel, label="Enable Sound Notifications")
        self.sounds_enabled_chk.SetValue(config.get("sounds_enabled", True))
        sounds_sizer.Add(self.sounds_enabled_chk, 0, wx.ALL, 5)
        
        def _add_sound_field(label, key):
            s = wx.BoxSizer(wx.HORIZONTAL)
            s.Add(wx.StaticText(sounds_panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
            val = config.get(key, "")
            ctrl = wx.TextCtrl(sounds_panel, value=str(val))
            s.Add(ctrl, 1, wx.ALL, 5)
            browse_btn = wx.Button(sounds_panel, label="Browse...")
            
            def _on_browse(evt):
                dlg = wx.FileDialog(self, f"Choose {label}", defaultFile=ctrl.GetValue(), wildcard="WAV files (*.wav)|*.wav|All files (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
                if dlg.ShowModal() == wx.ID_OK:
                    ctrl.SetValue(dlg.GetPath())
                dlg.Destroy()
            
            browse_btn.Bind(wx.EVT_BUTTON, _on_browse)
            s.Add(browse_btn, 0, wx.ALL, 5)
            sounds_sizer.Add(s, 0, wx.EXPAND | wx.ALL, 5)
            return ctrl
            
        self.sound_complete_ctrl = _add_sound_field("Refresh Complete Sound:", "sound_refresh_complete")
        self.sound_error_ctrl = _add_sound_field("Refresh Error Sound:", "sound_refresh_error")
        
        sounds_panel.SetSizer(sounds_sizer)
        notebook.AddPage(sounds_panel, "Sounds")

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
            label="Enable notifications for new articles",
        )
        self.windows_notifications_chk.SetValue(bool(config.get("windows_notifications_enabled", False)))
        if not sys.platform.startswith("win"):
            self.windows_notifications_chk.Disable()
        notifications_sizer.Add(self.windows_notifications_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.windows_notifications_feed_chk = wx.CheckBox(
            notifications_panel,
            label="Include feed name in notification text",
        )
        self.windows_notifications_feed_chk.SetValue(
            bool(config.get("windows_notifications_include_feed_name", True))
        )
        notifications_sizer.Add(self.windows_notifications_feed_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        cap_row = wx.BoxSizer(wx.HORIZONTAL)
        cap_row.Add(
            wx.StaticText(notifications_panel, label="Max notifications per refresh (0 = no limit):"),
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
            label="Show a summary notification when notification cap is reached",
        )
        self.windows_notifications_summary_chk.SetValue(
            bool(config.get("windows_notifications_show_summary_when_capped", True))
        )
        notifications_sizer.Add(self.windows_notifications_summary_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.test_notification_btn = wx.Button(notifications_panel, label="Test Notification")
        self.test_notification_btn.Bind(wx.EVT_BUTTON, self.on_test_notification)
        notifications_sizer.Add(self.test_notification_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.exclude_feeds_btn = wx.Button(notifications_panel, label="Exclude Feeds...")
        self.exclude_feeds_btn.Bind(wx.EVT_BUTTON, self.on_exclude_notification_feeds)
        notifications_sizer.Add(self.exclude_feeds_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.exclude_feeds_lbl = wx.StaticText(notifications_panel, label="")
        notifications_sizer.Add(self.exclude_feeds_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._update_excluded_feeds_label()

        self.windows_notifications_chk.Bind(wx.EVT_CHECKBOX, self._on_toggle_windows_notifications)
        self._update_notification_controls()

        notifications_panel.SetSizer(notifications_sizer)
        notebook.AddPage(notifications_panel, "Notifications")

        # Translate Tab (automatic article translation via Grok/xAI)
        translate_panel = wx.Panel(notebook)
        translate_sizer = wx.BoxSizer(wx.VERTICAL)

        translate_note = (
            "Configure automatic article translation.\n"
            "Your API key is stored locally in config.json."
        )
        translate_sizer.Add(wx.StaticText(translate_panel, label=translate_note), 0, wx.ALL, 8)

        self.translation_enabled_chk = wx.CheckBox(
            translate_panel,
            label="Enable automatic translation for article content",
        )
        self.translation_enabled_chk.SetValue(bool(config.get("translation_enabled", False)))
        translate_sizer.Add(self.translation_enabled_chk, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        provider_row = wx.BoxSizer(wx.HORIZONTAL)
        provider_row.Add(wx.StaticText(translate_panel, label="Provider:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.translation_provider_ctrl = wx.Choice(translate_panel, choices=["grok"])
        if not self.translation_provider_ctrl.SetStringSelection(str(config.get("translation_provider", "grok") or "grok")):
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
            wx.StaticText(translate_panel, label="Target language:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_target_language_ctrl = wx.ComboBox(
            translate_panel,
            choices=[label for label, _code in self._TRANSLATION_LANGUAGE_PRESETS],
            style=wx.CB_DROPDOWN,
        )
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
                label="Choose a language or type a code (e.g. en, es, fr, pt-BR).",
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        model_row = wx.BoxSizer(wx.HORIZONTAL)
        model_row.Add(
            wx.StaticText(translate_panel, label="Grok model (optional):"),
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
        self.translation_grok_model_ctrl.SetValue(str(config.get("translation_grok_model", "") or ""))
        model_row.Add(self.translation_grok_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        translate_sizer.Add(
            wx.StaticText(
                translate_panel,
                label="Pick a common model or type a custom one. Leave blank for auto fallback order.",
            ),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        api_key_row.Add(wx.StaticText(translate_panel, label="Grok API key:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.translation_grok_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_grok_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        api_key_row.Add(self.translation_grok_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        translate_panel.SetSizer(translate_sizer)
        notebook.AddPage(translate_panel, "Translate")

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
        if not sys.platform.startswith("win"):
            wx.MessageBox("Windows notifications are only available on Windows.", "Notifications", wx.ICON_INFORMATION)
            return

        title = "BlindRSS notification test"
        body = "If you can read this, notifications are working."
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
            wx.MessageBox(
                "Notification APIs were unavailable. Check Windows notification permissions and Focus Assist.",
                "Notifications",
                wx.ICON_WARNING,
            )

    def _update_notification_controls(self):
        enabled = bool(getattr(self, "windows_notifications_chk", None) and self.windows_notifications_chk.GetValue())
        if not sys.platform.startswith("win"):
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
                test_btn.Enable(bool(sys.platform.startswith("win")))
        except Exception:
            pass
        try:
            exclude_btn = getattr(self, "exclude_feeds_btn", None)
            if exclude_btn:
                exclude_btn.Enable(bool(sys.platform.startswith("win")))
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
            wx.MessageBox("Enter your Inoreader App ID and App Key first.", "Inoreader", wx.ICON_INFORMATION)
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
            dlg = wx.Dialog(self, title="Inoreader Authorization", size=(580, 320))
            sizer = wx.BoxSizer(wx.VERTICAL)
            msg = (
                "After authorizing in your browser, it will redirect to your Redirect URI.\n"
                "If the redirected page fails to load (common for HTTPS localhost), copy the full URL from the\n"
                "browser address bar and paste it below.\n\n"
                f"Redirect URI:\n{redirect_uri}"
            )
            sizer.Add(wx.StaticText(dlg, label=msg), 0, wx.ALL, 10)
            tc = wx.TextCtrl(dlg, style=wx.TE_MULTILINE)
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
        wx.MessageBox(f"Inoreader authorization failed:\n{message}", "Inoreader", wx.ICON_ERROR)

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
            return "English (en)"
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

    def _build_soundcard_choices(self, selected_device_id: str) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = [("System Default", "")]
        seen_ids = {""}
        preferred = str(selected_device_id or "")
        devices_ptr = None
        try:
            import vlc

            instance = vlc.Instance("--no-video", "--aout=mmdevice")
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

    def on_browse_dl_path(self, event):
        dlg = wx.DirDialog(self, "Choose download directory", self.dl_path_ctrl.GetValue(), style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.dl_path_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

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
            "download_path": self.dl_path_ctrl.GetValue(),
            "download_retention": self.retention_ctrl.GetValue(),
            "article_retention": self.art_retention_ctrl.GetValue(),
            "close_to_tray": self.close_tray_chk.GetValue(),
            "minimize_to_tray": self.min_tray_chk.GetValue(),
            "start_maximized": self.start_maximized_chk.GetValue(),
            "debug_mode": self.debug_mode_chk.GetValue(),
            "refresh_on_startup": self.refresh_startup_chk.GetValue(),
            "prompt_missing_dependencies_on_startup": self.prompt_missing_deps_chk.GetValue(),
            "start_on_windows_login": self.start_on_login_chk.GetValue(),
            "remember_last_feed": self.remember_last_feed_chk.GetValue(),
            "auto_check_updates": self.auto_update_chk.GetValue(),
            "sounds_enabled": self.sounds_enabled_chk.GetValue(),
            "sound_refresh_complete": self.sound_complete_ctrl.GetValue(),
            "sound_refresh_error": self.sound_error_ctrl.GetValue(),
            "windows_notifications_enabled": self.windows_notifications_chk.GetValue(),
            "windows_notifications_include_feed_name": self.windows_notifications_feed_chk.GetValue(),
            "windows_notifications_max_per_refresh": self.windows_notifications_max_ctrl.GetValue(),
            "windows_notifications_show_summary_when_capped": self.windows_notifications_summary_chk.GetValue(),
            "windows_notifications_excluded_feeds": sorted(self._notification_excluded_feed_ids),
            "translation_enabled": self.translation_enabled_chk.GetValue(),
            "translation_provider": self.translation_provider_ctrl.GetStringSelection() or "grok",
            "translation_target_language": self._translation_language_code_from_ui(),
            "translation_grok_model": (self.translation_grok_model_ctrl.GetValue() or "").strip(),
            "translation_grok_api_key": (self.translation_grok_api_key_ctrl.GetValue() or "").strip(),
            "active_provider": self.provider_choice.GetStringSelection(),
            "providers": providers,
        }


class FeedPropertiesDialog(wx.Dialog):
    def __init__(self, parent, feed, categories, allow_url_edit: bool = True):
        super().__init__(parent, title="Feed Properties", size=(500, 260))

        self.feed = feed
        self.categories = categories

        sizer = wx.BoxSizer(wx.VERTICAL)

        title_sizer = wx.BoxSizer(wx.HORIZONTAL)
        title_sizer.Add(wx.StaticText(self, label="Title:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.title_ctrl = wx.TextCtrl(self, value=str(feed.title or ""))
        title_sizer.Add(self.title_ctrl, 1, wx.ALL, 5)
        sizer.Add(title_sizer, 0, wx.EXPAND)

        url_sizer = wx.BoxSizer(wx.HORIZONTAL)
        url_sizer.Add(wx.StaticText(self, label="URL:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.url_ctrl = wx.TextCtrl(self, value=str(feed.url or ""))
        if not bool(allow_url_edit):
            try:
                self.url_ctrl.SetEditable(False)
            except Exception:
                pass
        url_sizer.Add(self.url_ctrl, 1, wx.ALL, 5)
        sizer.Add(url_sizer, 0, wx.EXPAND)

        sizer.Add(wx.StaticText(self, label="Category:"), 0, wx.ALL, 5)
        self.cat_ctrl = wx.ComboBox(self, choices=self.categories, style=wx.CB_DROPDOWN)
        self.cat_ctrl.SetValue(feed.category or "Uncategorized")
        sizer.Add(self.cat_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        self.SetSizer(sizer)
        self.Centre()

        # Fix tab order: Title -> URL -> Category -> OK -> Cancel
        self.title_ctrl.SetFocus()
        if self.url_ctrl.AcceptsFocus():
            self.url_ctrl.MoveAfterInTabOrder(self.title_ctrl)
        
        self.cat_ctrl.MoveAfterInTabOrder(self.url_ctrl)
        
        ok_btn = self.FindWindow(wx.ID_OK)
        cancel_btn = self.FindWindow(wx.ID_CANCEL)
        
        if ok_btn:
            ok_btn.MoveAfterInTabOrder(self.cat_ctrl)
            ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        if cancel_btn and ok_btn:
            cancel_btn.MoveAfterInTabOrder(ok_btn)

    def on_ok(self, event):
        self.EndModal(wx.ID_OK)

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
            category = (self.cat_ctrl.GetValue() or "").strip()
        except Exception:
            category = ""
        return title, url, category


class FeedSearchDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Find a Podcast or RSS Feed", size=(800, 600))
        
        self.selected_url = None
        self._threads = []
        self._stop_event = threading.Event()
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Search Box
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        input_sizer.Add(wx.StaticText(self, label="Search:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.ShowCancelButton(True)
        wx.CallAfter(self.search_ctrl.SetFocus)
        input_sizer.Add(self.search_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        self.search_btn = wx.Button(self, label="Search")
        input_sizer.Add(self.search_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        
        sizer.Add(input_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Provider Status (optional, to show what's happening)
        self.status_lbl = wx.StaticText(self, label="Ready.")
        sizer.Add(self.status_lbl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # Results List
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.results_list.InsertColumn(0, "Title", width=350)
        self.results_list.InsertColumn(1, "Provider", width=120)
        self.results_list.InsertColumn(2, "Details", width=250)
        self.results_list.InsertColumn(3, "URL", width=0) # Hidden
        
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 5)

        # Attribution / Help
        help_sizer = wx.BoxSizer(wx.HORIZONTAL)
        help_sizer.Add(wx.StaticText(self, label="Sources: iTunes, gPodder, YouTube, Feedly, Feedsearch, NewsBlur, Reddit, Fediverse"), 0, wx.ALL, 5)
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

        self.results_data = [] # List of dicts: title, provider, detail, url

    def on_close(self, event):
        self._stop_event.set()
        event.Skip()

    def on_search(self, event):
        term = (self.search_ctrl.GetValue() or "").strip()
        if not term:
            return
            
        self.results_list.DeleteAllItems()
        self.results_data = []
        self._stop_event.clear()
        
        # Update UI
        self.search_ctrl.Disable()
        self.search_btn.Disable()
        self.status_lbl.SetLabel("Searching...")
        
        # Start unified search thread
        threading.Thread(target=self._unified_search_manager, args=(term,), daemon=True).start()

    def _unified_search_manager(self, term):
        import urllib.parse
        from queue import Queue

        results_queue = Queue()
        active_threads = []

        # Helper to launch a provider thread
        def launch(target, name):
            t = threading.Thread(target=target, args=(term, results_queue), name=name, daemon=True)
            t.start()
            active_threads.append(t)

        # 1. iTunes (Podcasts)
        launch(self._search_itunes, "iTunes")
        
        # 2. gPodder (Podcasts)
        launch(self._search_gpodder, "gPodder")
        
        # 3. Feedly (RSS/General)
        launch(self._search_feedly, "Feedly")

        # 3.5. YouTube channel/playlist search (returns native YouTube RSS feed URLs)
        launch(self._search_youtube_channels, "YouTube")
        
        # 4. NewsBlur (Autocomplete)
        launch(self._search_newsblur, "NewsBlur")

        # 5. Reddit (Subreddits)
        launch(self._search_reddit, "Reddit")

        # 6. Fediverse (Lemmy/Kbin)
        launch(self._search_fediverse, "Fediverse")

        # 7. Feedsearch.dev + BlindRSS (URL based)
        # Only run these if it looks like a URL or domain, OR if user wants broad search
        # Feedsearch.dev claims to search by URL. If we pass a keyword, it might fail, but let's try.
        # BlindRSS discovery is strictly URL based.
        if "." in term or "://" in term or term.lower().startswith("lbry:"):
            launch(self._search_feedsearch, "Feedsearch")
            launch(self._search_blindrss, "BlindRSS")
        
        # Wait for threads
        for t in active_threads:
            t.join(timeout=15) # Global timeout per provider

        # Process results
        all_results = []
        seen_urls = set()

        while not results_queue.empty():
            try:
                provider, items = results_queue.get_nowait()
                for item in items:
                    url = item.get("url", "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    all_results.append({
                        "title": item.get("title", url),
                        "provider": provider,
                        "detail": item.get("detail", ""),
                        "url": url
                    })
            except Exception:
                pass

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
            results = list(search_youtube_feeds(term, limit=12, timeout=15) or [])
            if results:
                queue.put(("YouTube", results))
        except Exception:
            pass

    def _search_newsblur(self, term, queue):
        try:
            import urllib.parse
            # Try autocomplete first
            url = f"https://newsblur.com/rss_feeds/feed_autocomplete?term={urllib.parse.quote(term)}"
            resp = utils.safe_requests_get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json() # usually a list of dicts
                results = []
                for it in data:
                    if not isinstance(it, dict): continue
                    # NewsBlur structure: {'value': 'url', 'label': 'Title', ...} or similar
                    # Check actual response structure. 
                    # Assuming standard list of dicts with 'value' (ID/URL) and 'label' (Title) 
                    # OR {'feeds': [...]}
                    # Actually standard NewsBlur autocomplete returns list of dicts: {value, label, tagline, num_subscribers}
                    
                    # Also checking /search_feed endpoint if autocomplete is sparse?
                    # sticking to autocomplete for now.
                    
                    feed_url = it.get("value")
                    if not feed_url: continue
                    
                    # Sometimes value is integer ID, sometimes URL.
                    # If it's an integer, we might not get the URL easily without auth.
                    # But for 'feed_autocomplete', it often returns the feed URL in 'address' or 'value' if looking up by address.
                    # Let's check keys carefully.
                    u = it.get("address") or it.get("value")
                    if str(u).isdigit(): continue # Skip internal IDs
                    
                    results.append({
                        "title": it.get("label") or u,
                        "detail": f"{it.get('tagline', '')} ({it.get('num_subscribers', 0)} subs)",
                        "url": u
                    })
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
        try:
            import urllib.parse
            # Query lemmy.world as a gateway to the Fediverse
            url = f"https://lemmy.world/api/v3/search?q={urllib.parse.quote(term)}&type_=Communities&sort=TopAll&limit=15"
            headers = {"User-Agent": "BlindRSS/1.0"}
            resp = utils.safe_requests_get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                # Structure: { "communities": [ { "community": { ... }, "counts": { ... } } ] }
                comms = data.get("communities", [])
                for c in comms:
                    comm = c.get("community", {})
                    counts = c.get("counts", {})
                    
                    title = comm.get("title")
                    name = comm.get("name")
                    actor_id = comm.get("actor_id")
                    
                    if not actor_id: continue
                    
                    # Distinguish Lemmy vs Kbin vs Mbin etc.
                    # Actor ID is usually the community URL: https://instance/c/name or https://instance/m/name
                    # RSS Construction:
                    # Lemmy: https://instance/feeds/c/name.xml
                    # Kbin: https://instance/m/name/rss (or .xml)
                    
                    rss_url = ""
                    provider_label = "Fediverse"
                    
                    if "/c/" in actor_id:
                        # Likely Lemmy
                        # Actor: https://lemmy.ml/c/linux
                        # RSS: https://lemmy.ml/feeds/c/linux.xml
                        base = actor_id.split("/c/")[0]
                        comm_name = actor_id.split("/c/")[1]
                        rss_url = f"{base}/feeds/c/{comm_name}.xml"
                        provider_label = "Lemmy"
                    elif "/m/" in actor_id:
                        # Likely Kbin
                        # Actor: https://kbin.social/m/gaming
                        # RSS: https://kbin.social/m/gaming/rss
                        rss_url = f"{actor_id}/rss"
                        provider_label = "Kbin"
                    else:
                        # Fallback/Unknown
                        continue

                    subs = counts.get("subscribers")
                    desc = f"{name} ({subs} subs)" if subs else name
                    
                    results.append({
                        "title": title or name,
                        "detail": f"{provider_label} - {desc}",
                        "url": rss_url
                    })
                queue.put(("Fediverse", results))
        except Exception:
            pass

    def _search_feedsearch(self, term, queue):
        try:
            import urllib.parse
            url = f"https://feedsearch.dev/api/v1/search?url={urllib.parse.quote(term)}"
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
        # Local discovery
        try:
            from core.discovery import discover_feeds, discover_feed
            
            candidates = []
            
            # 1. discover_feeds (list)
            try:
                c1 = discover_feeds(term)
                candidates.extend(c1)
            except: pass
            
            # 2. discover_feed (single, maybe different logic)
            if not candidates:
                 try:
                    c2 = discover_feed(term)
                    if c2: candidates.append(c2)
                 except: pass
                 
            # 3. Try with https:// if missing
            if not candidates and "://" not in term:
                 try:
                    c3 = discover_feeds("https://" + term)
                    candidates.extend(c3)
                 except: pass

            results = []
            seen = set()
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    results.append({
                        "title": c,
                        "detail": "Local Discovery",
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


class PersistentSearchDialog(wx.Dialog):
    def __init__(self, parent, searches=None):
        super().__init__(parent, title="Configure Persistent Search", size=(420, 320))

        self._searches = list(searches or [])

        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label="Saved searches:"), 0, wx.ALL, 5)

        self.list_ctrl = wx.ListBox(self, choices=self._searches)
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(self, label="Add...")
        remove_btn = wx.Button(self, label="Remove")
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
        dlg = wx.TextEntryDialog(self, "Search query:", "Add Search")
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
        super().__init__(parent, title="About BlindRSS", size=(400, 300))

        sizer = wx.BoxSizer(wx.VERTICAL)

        # Title / Version
        title_font = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title_txt = wx.StaticText(self, label=f"BlindRSS {version_str}")
        title_txt.SetFont(title_font)
        sizer.Add(title_txt, 0, wx.ALIGN_CENTER | wx.TOP, 15)

        # Copyright
        copy_txt = wx.StaticText(self, label="Copyright (c) 2024-2026 serrebi and contributors")
        sizer.Add(copy_txt, 0, wx.ALIGN_CENTER | wx.TOP, 10)

        sizer.AddSpacer(20)

        # Buttons
        github_btn = wx.Button(self, label="Follow me on GitHub (@serrebi)")
        repo_btn = wx.Button(self, label="Visit Repository")

        sizer.Add(github_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        sizer.Add(repo_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        sizer.AddSpacer(20)

        close_btn = wx.Button(self, wx.ID_CLOSE, "Close")
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)

        self.SetSizer(sizer)
        self.Centre()

        # Bindings
        github_btn.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://github.com/serrebi"))
        repo_btn.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://github.com/serrebi/BlindRSS"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

# Backwards-compatible name (menu item was historically called "Search Podcast").
PodcastSearchDialog = FeedSearchDialog
