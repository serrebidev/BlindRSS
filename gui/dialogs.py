import wx
import wx.adv
import concurrent.futures
import copy
import queue
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
    resolve_quick_url_title,
    resolve_ytdlp_url_enrichment,
    search_ytdlp_site,
    search_youtube_feeds,
    search_mastodon_feeds,
    search_bluesky_feeds,
    search_piefed_feeds,
)
from core import utils
from core import config as config_mod
from core.casting import CastingManager
from core import inoreader_oauth
from core import translation as translation_mod
from core.vlc_options import build_vlc_instance_args

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
        self.concurrent_ctrl = wx.SpinCtrl(general_panel, min=1, max=50, initial=int(config.get("max_concurrent_refreshes", 6)))
        concurrency_sizer.Add(self.concurrent_ctrl, 0, wx.ALL, 5)
        general_sizer.Add(concurrency_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        per_host_sizer = wx.BoxSizer(wx.HORIZONTAL)
        per_host_sizer.Add(wx.StaticText(general_panel, label="Max Connections Per Host:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.per_host_ctrl = wx.SpinCtrl(general_panel, min=1, max=10, initial=int(config.get("per_host_max_connections", 2)))
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

        # Preferred soundcard (enumerated in background to avoid blocking dialog open)
        soundcard_sizer = wx.BoxSizer(wx.HORIZONTAL)
        soundcard_sizer.Add(wx.StaticText(media_panel, label="Preferred Soundcard:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self._current_soundcard = str(config.get("preferred_soundcard", "") or "")
        self._soundcard_choices = [("System Default", "")]
        self._soundcard_labels = ["Loading soundcards..."]
        self.soundcard_ctrl = wx.Choice(media_panel, choices=self._soundcard_labels)
        self.soundcard_ctrl.SetSelection(0)
        soundcard_sizer.Add(self.soundcard_ctrl, 1, wx.ALL, 5)
        media_sizer.Add(soundcard_sizer, 0, wx.EXPAND | wx.ALL, 5)
        threading.Thread(target=self._load_soundcards_async, daemon=True).start()

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
            label="Enable automatic translation for article content",
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
        provider_row.Add(wx.StaticText(translate_panel, label="Provider:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
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
            wx.StaticText(translate_panel, label="Grok (xAI) model (optional):"),
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
        self.translation_grok_model_hint_lbl = wx.StaticText(
            translate_panel,
            label="Grok is by xAI. Get a key at console.x.ai. For Groq (LLaMA/Mistral), select 'Groq (LLaMA, Mistral)' instead.",
        )
        translate_sizer.Add(
            self.translation_grok_model_hint_lbl,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        api_key_row.Add(wx.StaticText(translate_panel, label="Grok (xAI) API key (starts with xai-):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.translation_grok_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_grok_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        api_key_row.Add(self.translation_grok_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        groq_model_row = wx.BoxSizer(wx.HORIZONTAL)
        groq_model_row.Add(
            wx.StaticText(translate_panel, label="Groq model (optional) - hosts LLaMA and Mistral:"),
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
        self.translation_groq_model_ctrl.SetValue(str(config.get("translation_groq_model", "") or ""))
        groq_model_row.Add(self.translation_groq_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(groq_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        groq_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        groq_api_key_row.Add(
            wx.StaticText(translate_panel, label="Groq API key (starts with gsk_):"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_groq_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_groq_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        groq_api_key_row.Add(self.translation_groq_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(groq_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.translation_groq_hint_lbl = wx.StaticText(
            translate_panel,
            label="Groq is NOT Grok. Get a free Groq key at console.groq.com/keys (runs LLaMA and Mistral models).",
        )
        translate_sizer.Add(
            self.translation_groq_hint_lbl,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            8,
        )

        openai_model_row = wx.BoxSizer(wx.HORIZONTAL)
        openai_model_row.Add(
            wx.StaticText(translate_panel, label="OpenAI model (optional):"),
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
        self.translation_openai_model_ctrl.SetValue(str(config.get("translation_openai_model", "") or ""))
        openai_model_row.Add(self.translation_openai_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openai_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openai_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        openai_api_key_row.Add(
            wx.StaticText(translate_panel, label="OpenAI API key:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_openai_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_openai_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        openai_api_key_row.Add(self.translation_openai_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openai_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openrouter_model_row = wx.BoxSizer(wx.HORIZONTAL)
        openrouter_model_row.Add(
            wx.StaticText(translate_panel, label="OpenRouter model (optional):"),
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
        self.translation_openrouter_model_ctrl.SetValue(str(config.get("translation_openrouter_model", "") or ""))
        openrouter_model_row.Add(self.translation_openrouter_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openrouter_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openrouter_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        openrouter_api_key_row.Add(
            wx.StaticText(translate_panel, label="OpenRouter API key:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_openrouter_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_openrouter_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        openrouter_api_key_row.Add(self.translation_openrouter_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openrouter_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        openrouter_tools_row = wx.BoxSizer(wx.HORIZONTAL)
        self.translation_openrouter_load_models_btn = wx.Button(translate_panel, label="Load OpenRouter Models")
        openrouter_tools_row.Add(self.translation_openrouter_load_models_btn, 0, wx.RIGHT, 8)
        self.translation_openrouter_models_status_lbl = wx.StaticText(
            translate_panel,
            label="Loads all available model IDs from OpenRouter.",
        )
        openrouter_tools_row.Add(self.translation_openrouter_models_status_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(openrouter_tools_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        gemini_model_row = wx.BoxSizer(wx.HORIZONTAL)
        gemini_model_row.Add(
            wx.StaticText(translate_panel, label="Gemini model (optional):"),
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
        self.translation_gemini_model_ctrl.SetValue(str(config.get("translation_gemini_model", "") or ""))
        gemini_model_row.Add(self.translation_gemini_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(gemini_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        gemini_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        gemini_api_key_row.Add(
            wx.StaticText(translate_panel, label="Gemini API key:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_gemini_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_gemini_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
        gemini_api_key_row.Add(self.translation_gemini_api_key_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(gemini_api_key_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        qwen_model_row = wx.BoxSizer(wx.HORIZONTAL)
        qwen_model_row.Add(
            wx.StaticText(translate_panel, label="Qwen model (optional):"),
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
        self.translation_qwen_model_ctrl.SetValue(str(config.get("translation_qwen_model", "") or ""))
        qwen_model_row.Add(self.translation_qwen_model_ctrl, 1, wx.ALIGN_CENTER_VERTICAL)
        translate_sizer.Add(qwen_model_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        qwen_api_key_row = wx.BoxSizer(wx.HORIZONTAL)
        qwen_api_key_row.Add(
            wx.StaticText(translate_panel, label="Qwen API key:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        self.translation_qwen_api_key_ctrl = wx.TextCtrl(
            translate_panel,
            value=str(config.get("translation_qwen_api_key", "") or ""),
            style=wx.TE_PASSWORD,
        )
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
        notebook.AddPage(translate_panel, "Translate")

        # Advanced Tab
        advanced_panel = wx.Panel(notebook)
        advanced_sizer = wx.BoxSizer(wx.VERTICAL)

        storage_group = wx.StaticBox(advanced_panel, label="Data Storage Location")
        storage_sizer = wx.StaticBoxSizer(storage_group, wx.VERTICAL)

        storage_help = wx.StaticText(
            advanced_panel,
            label=(
                "Where BlindRSS stores config.json and rss.db.\n"
                "User Data Folder keeps your settings and feeds across app upgrades,\n"
                "especially on macOS where the installed app bundle is replaced."
            ),
        )
        storage_sizer.Add(storage_help, 0, wx.ALL, 6)

        self._storage_location_map = {
            "User Data Folder": "user_data",
            "App Install Folder": "app_folder",
        }
        storage_choices = list(self._storage_location_map.keys())
        storage_row = wx.BoxSizer(wx.HORIZONTAL)
        storage_row.Add(
            wx.StaticText(advanced_panel, label="Storage Location:"),
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
                f"User Data Folder path:\n  {paths.get('user_data', '')}\n"
                f"App Install Folder path:\n  {paths.get('app_folder', '')}"
            ),
        )
        storage_sizer.Add(paths_lbl, 0, wx.ALL, 6)

        self._initial_storage_location = current_storage
        advanced_sizer.Add(storage_sizer, 0, wx.EXPAND | wx.ALL, 8)

        advanced_panel.SetSizer(advanced_sizer)
        notebook.AddPage(advanced_panel, "Advanced")

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
            self.translation_openrouter_models_status_lbl.SetLabel("Loading OpenRouter models...")
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

    def _load_soundcards_async(self):
        """Background thread: enumerate VLC soundcards, then update the UI."""
        choices = self._build_soundcard_choices(self._current_soundcard)
        wx.CallAfter(self._populate_soundcard_ctrl, choices)

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
        choices: list[tuple[str, str]] = [("System Default", "")]
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
            "active_provider": self.provider_choice.GetStringSelection(),
            "providers": providers,
            "data_location": self._storage_location_map.get(
                self.storage_location_ctrl.GetStringSelection(),
                self._initial_storage_location,
            ),
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
    _SEARCH_POLL_INTERVAL_S = 0.1
    _SEARCH_TOTAL_TIMEOUT_ALL_SOURCES_S = 60.0
    _SEARCH_TOTAL_TIMEOUT_SINGLE_SOURCE_S = 60.0
    _SOURCE_ALL = "__all__"
    _SOURCE_CHOICES = [
        ("All sources", _SOURCE_ALL),
        ("iTunes", "itunes"),
        ("gPodder", "gpodder"),
        ("Feedly", "feedly"),
        ("YouTube", "youtube"),
        ("NewsBlur", "newsblur"),
        ("Reddit", "reddit"),
        ("Fediverse (all)", "fediverse"),
        ("Mastodon", "mastodon"),
        ("Bluesky", "bluesky"),
        ("PieFed", "piefed"),
        ("Lemmy/Kbin", "lemmy"),
        ("Feedsearch (URL/domain)", "feedsearch"),
        ("BlindRSS discovery (URL/domain)", "blindrss"),
    ]

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

        input_sizer.Add(wx.StaticText(self, label="Source:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        source_labels = [label for label, _ in self._SOURCE_CHOICES]
        self.source_combo = wx.ComboBox(self, choices=source_labels, style=wx.CB_READONLY)
        self.source_combo.SetSelection(0)
        input_sizer.Add(self.source_combo, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)

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
        help_sizer.Add(wx.StaticText(self, label="Sources: iTunes, gPodder, YouTube, Feedly, Feedsearch, NewsBlur, Reddit, Fediverse (Lemmy/Kbin/Mastodon/Bluesky/PieFed)"), 0, wx.ALL, 5)
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
            ("iTunes", "itunes", self._search_itunes),
            ("gPodder", "gpodder", self._search_gpodder),
            ("Feedly", "feedly", self._search_feedly),
            ("YouTube", "youtube", self._search_youtube_channels),
            ("NewsBlur", "newsblur", self._search_newsblur),
            ("Reddit", "reddit", self._search_reddit),
            ("Fediverse", "fediverse", self._search_fediverse),
            ("Feedsearch", "feedsearch", self._search_feedsearch),
            ("BlindRSS", "blindrss", self._search_blindrss),
        ]
        specific_targets = {
            "mastodon": ("Mastodon", "mastodon", self._search_mastodon),
            "bluesky": ("Bluesky", "bluesky", self._search_bluesky),
            "piefed": ("PieFed", "piefed", self._search_piefed),
            "lemmy": ("Lemmy/Kbin", "lemmy", self._search_lemmy),
        }

        by_key = {key: (name, key, fn) for name, key, fn in all_targets}
        by_key.update(specific_targets)

        if source_key == self._SOURCE_ALL:
            target_keys = [key for _, key, _ in all_targets]
        elif source_key in by_key:
            target_keys = [source_key]
        else:
            target_keys = [key for _, key, _ in all_targets]

        url_like = self._is_url_like_term(term)
        filtered = []
        for key in target_keys:
            name, _, fn = by_key[key]
            if key in ("feedsearch", "blindrss") and not url_like:
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
            self.status_lbl.SetLabel("Searching all sources...")
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

        if source_key == self._SOURCE_ALL and all_results:
            # Keep YouTube results at the top of the merged list for easier discovery.
            all_results.sort(key=lambda item: 0 if str(item.get("provider") or "").strip().lower() == "youtube" else 1)

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
            results = list(search_youtube_feeds(term, limit=100, timeout=15) or [])
            if results:
                queue.put(("YouTube", results))
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
    _SEARCH_CONCURRENCY = 4
    _PER_SITE_LIMIT = 80
    _LOAD_MORE_STEP = 80
    _PER_SITE_TIMEOUT_S = 12
    _TITLE_ENRICH_CONCURRENCY = 2
    _TITLE_ENRICH_TIMEOUT_S = 10
    _QUICK_TITLE_ENRICH_CONCURRENCY = 4
    _QUICK_TITLE_ENRICH_TIMEOUT_S = 4
    _RESULTS_REFRESH_THROTTLE_MS = 200
    _RESULTS_REFRESH_THROTTLE_FOCUSED_MS = 500
    _RESULTS_REFRESH_NAV_COOLDOWN_MS = 1200
    _TITLE_ENRICH_WORKER_THREADS = 6
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
        super().__init__(parent, title="Video Search", size=(980, 680))

        self._stop_event = threading.Event()
        self._search_thread = None
        self._search_running = False
        self._site_rows = []
        self._scope_values = [self._ALL_SITES_TOKEN]
        self._filter_values = [self._ALL_SITES_TOKEN]
        self._all_results = []
        self._visible_results = []
        self._seen_result_keys = set()
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
        query_row.Add(wx.StaticText(self, label="Search:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.ShowCancelButton(True)
        query_row.Add(self.search_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.search_btn = wx.Button(self, label="Search")
        query_row.Add(self.search_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.load_more_btn = wx.Button(self, label="Load More Results (+80/site)")
        self.load_more_btn.Disable()
        query_row.Add(self.load_more_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        root.Add(query_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        opts_row = wx.BoxSizer(wx.HORIZONTAL)
        opts_row.Add(wx.StaticText(self, label="Search Sites:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.scope_choice = wx.Choice(self)
        opts_row.Add(self.scope_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        opts_row.Add(wx.StaticText(self, label="Filter Results:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.filter_choice = wx.Choice(self)
        opts_row.Add(self.filter_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        root.Add(opts_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        self.status_lbl = wx.StaticText(
            self,
            label="Ready.",
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
        self.results_list.InsertColumn(0, "Title", width=340)
        self.results_list.InsertColumn(1, "Site", width=140)
        self.results_list.InsertColumn(2, "Kind", width=90)
        self.results_list.InsertColumn(3, "Plays", width=100)
        self.results_list.InsertColumn(4, "Details", width=220)
        self.results_list.InsertColumn(5, "URL", width=0)  # Hidden storage column
        root.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 5)

        action_row = wx.BoxSizer(wx.HORIZONTAL)
        self.close_btn = wx.Button(self, wx.ID_CLOSE, "Close")
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
            sites = list(get_ytdlp_searchable_sites(include_adult=False) or [])
        except Exception:
            sites = []
        self._site_rows = sites

        self._scope_values = [self._ALL_SITES_TOKEN] + [str(s.get("id") or "") for s in sites]
        self._filter_values = [self._ALL_SITES_TOKEN] + [str(s.get("id") or "") for s in sites]
        scope_labels = ["All searchable sites"] + [str(s.get("label") or s.get("id") or "") for s in sites]
        filter_labels = ["All sites"] + [str(s.get("label") or s.get("id") or "") for s in sites]

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

    def _get_scope_sites(self) -> list[dict]:
        selected = self._get_choice_value(self.scope_choice, self._scope_values)
        if selected == self._ALL_SITES_TOKEN:
            return list(self._site_rows or [])
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

    def _sorted_results(self, items: list[dict]) -> list[dict]:
        rows = list(items or [])
        col = getattr(self, "_sort_column", self._DEFAULT_SORT_COLUMN)
        desc = bool(getattr(self, "_sort_desc", self._DEFAULT_SORT_DESC))

        if col is None:
            rows.sort(key=self._default_result_sort_key)
            return rows

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
            self.status_lbl.SetLabel("No searchable sites.")
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

        new_count = 0
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            site_id = str(item.get("site_id") or (site or {}).get("id") or "").strip()
            key = f"{site_id}|{url}" if site_id else url
            if not url or key in self._seen_result_keys:
                continue
            self._seen_result_keys.add(key)
            try:
                self._result_arrival_counter = int(self._result_arrival_counter or 0) + 1
            except Exception:
                self._result_arrival_counter = 1
            item["_arrival_order"] = int(self._result_arrival_counter or 0)
            self._all_results.append(item)
            new_count += 1
            self._queue_title_enrichment(item, self._search_generation)

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
        play_item = menu.Append(wx.ID_ANY, "Play")
        subscribe_item = menu.Append(wx.ID_ANY, "Subscribe")
        copy_item = menu.Append(wx.ID_ANY, "Copy URL")
        play_item.Enable(bool(play_ok))
        subscribe_item.Enable(bool(subscribe_ok))
        copy_item.Enable(bool(copy_ok))

        menu.Bind(wx.EVT_MENU, self.on_play_selected, play_item)
        menu.Bind(wx.EVT_MENU, self.on_subscribe_best, subscribe_item)
        menu.Bind(wx.EVT_MENU, self.on_copy_selected_url, copy_item)

        try:
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
                        lbl.SetLabel("Ready.")
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
                wx.MessageBox(f"Could not start playback: {e}", "Playback Error", wx.ICON_ERROR)
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
            wx.MessageBox("Parent window does not support subscribing from this dialog.", "Subscribe", wx.ICON_ERROR)
            return
        try:
            parent.add_feed_from_url_prompt(url)
            self.status_lbl.SetLabel(f"{label}: {url}")
        except Exception as e:
            wx.MessageBox(f"Could not subscribe: {e}", "Subscribe Error", wx.ICON_ERROR)

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
                self.status_lbl.SetLabel("Copied URL.")
        except Exception:
            pass


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
        copy_txt = wx.StaticText(self, label="Copyright (c) 2024-2026 serrebidev and contributors")
        sizer.Add(copy_txt, 0, wx.ALIGN_CENTER | wx.TOP, 10)

        sizer.AddSpacer(20)

        # Buttons
        github_btn = wx.Button(self, label="Follow me on GitHub (@serrebidev)")
        repo_btn = wx.Button(self, label="Visit Repository")

        sizer.Add(github_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        sizer.Add(repo_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        sizer.AddSpacer(20)

        close_btn = wx.Button(self, wx.ID_CLOSE, "Close")
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)

        self.SetSizer(sizer)
        self.Centre()

        # Bindings
        github_btn.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://github.com/serrebidev"))
        repo_btn.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open("https://github.com/serrebidev/BlindRSS"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))

# Backwards-compatible name (menu item was historically called "Search Podcast").
PodcastSearchDialog = FeedSearchDialog
