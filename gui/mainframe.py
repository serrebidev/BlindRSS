import wx
import wx.adv
import sys
# import wx.html2 # Removed as per request
import webbrowser
import threading
import time
import os
import re
import logging
from collections import deque
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
# from dateutil import parser as date_parser  # Removed unused import
from .dialogs import (
    AddFeedDialog,
    AddShortcutsDialog,
    SettingsDialog,
    FeedPropertiesDialog,
    AboutDialog,
    PersistentSearchDialog,
)
from .accessibility import AccessibleBrowserFrame, build_accessible_view_entries, voiceover_is_running
from .player import PlayerFrame
from .tray import BlindRSSTrayIcon
from .hotkeys import HoldRepeatHotkeys
from providers.base import RSSProvider
from core.config import APP_DIR
from core.models import Article
from core import utils
from core import article_extractor
from core import translation as translation_mod
from core import updater
from core import windows_integration
from core.version import APP_VERSION
from core import dependency_check
import core.discovery

log = logging.getLogger(__name__)

try:
    EVT_NOTIFICATION_MESSAGE_CLICK = wx.PyEventBinder(wx.adv.wxEVT_NOTIFICATION_MESSAGE_CLICK, 1)
    EVT_NOTIFICATION_MESSAGE_ACTION = wx.PyEventBinder(wx.adv.wxEVT_NOTIFICATION_MESSAGE_ACTION, 1)
    EVT_NOTIFICATION_MESSAGE_DISMISSED = wx.PyEventBinder(wx.adv.wxEVT_NOTIFICATION_MESSAGE_DISMISSED, 1)
except Exception:
    EVT_NOTIFICATION_MESSAGE_CLICK = None
    EVT_NOTIFICATION_MESSAGE_ACTION = None
    EVT_NOTIFICATION_MESSAGE_DISMISSED = None

# Use a long, finite timeout for actionable toasts.
# On some backends Timeout_Never can be treated as immediate-dismiss.
ACTIONABLE_NOTIFICATION_TIMEOUT_SECONDS = 25


class MainFrame(wx.Frame):
    def __init__(self, provider: RSSProvider, config_manager):
        start_maximized = bool(config_manager.get("start_maximized", False))
        style = wx.DEFAULT_FRAME_STYLE
        super().__init__(None, title="BlindRSS", size=(1000, 700), style=style)
        self.provider = provider
        self.config_manager = config_manager
        self._start_maximized = start_maximized
        if self._start_maximized:
            self.Maximize(True)
        self._refresh_guard = threading.Lock()
        # Critical background workers (e.g., destructive DB ops) we may want to wait for during shutdown.
        self._critical_workers_lock = threading.Lock()
        self._critical_workers = set()
        self.feed_map = {}
        self.feed_nodes = {}
        self._article_refresh_pending = False
        # View/article cache so switching between nodes doesn't re-index history every time.
        # Keys are feed_id values like: "all", "<feed_id>", "category:<id>".
        self.view_cache = {}
        self._view_cache_lock = threading.Lock()
        self.max_cached_views = int(self.config_manager.get("max_cached_views", 15))

        self.current_feed_id = None
        self._loading_more_placeholder = False
        # Article paging
        self.article_page_size = 400
        self._load_more_inflight = False
        self._load_more_label = "Load more items (Enter)"
        self._loading_label = "Loading more..."
        
        # Create player window lazily to keep startup fast.
        self.player_window = None

        # Custom hold-to-repeat for media keys (prevents multi-seek on quick tap)
        self._media_hotkeys = HoldRepeatHotkeys(self, hold_delay_s=2.0, repeat_interval_s=0.12, poll_interval_ms=15)
        
        self._updating_list = False # Flag to ignore selection events during background updates
        self._updating_tree = False # Flag to ignore tree selection events during rebuilds
        self.selected_article_id = None
        self._update_check_inflight = False
        self._update_install_inflight = False

        # Batch refresh progress updates to avoid flooding the UI thread when many feeds refresh in parallel.
        self._refresh_progress_lock = threading.Lock()
        self._refresh_progress_pending = {}
        self._refresh_progress_flush_scheduled = False

        self._unread_filter_enabled = False
        self._is_first_tree_load = True
        self._search_query = ""
        self._search_active = False
        self._base_articles = []
        self._base_view_id = None
        self._search_base_articles = None
        self._search_base_view_id = None
        self._persistent_searches = []
        self._persistent_search_menu = None
        self._persistent_search_items = {}
        self._search_visible = bool(self.config_manager.get("show_search_field", True))
        self._search_mode = self._normalize_search_mode(self.config_manager.get("search_mode", "title_content"))
        self._article_sort_by = self._normalize_article_sort_by(self.config_manager.get("article_sort_by", "date"))
        self._article_sort_ascending = bool(self.config_manager.get("article_sort_ascending", False))
        self._sort_by_menu_items = {}
        self._sort_ascending_item = None
        # Keep more live notification objects so Windows can retain interactive
        # Action Center entries while refresh is processing many new items.
        self._active_notifications = deque(maxlen=500)
        self._notification_payloads = {}
        self._accessible_browser = None
        self._accessible_view_entries = []
        self._voiceover_browser_attempted = False

        self.init_ui()
        self.init_menus()
        self.init_shortcuts()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self._load_persistent_searches()
        
        self.tray_icon = BlindRSSTrayIcon(self)
        
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ICONIZE, self.on_iconize)
        
        # Start background refresh loop (daemon so it can't keep the app alive)
        self.stop_event = threading.Event()
        self.refresh_thread = threading.Thread(target=self.refresh_loop, daemon=True)
        self.refresh_thread.start()
        
        # Initial load
        self.refresh_feeds()
        wx.CallAfter(self._apply_startup_window_state)
        wx.CallAfter(self._focus_default_control)
        wx.CallLater(900, self._maybe_open_accessible_browser_for_voiceover)
        wx.CallLater(15000, self._maybe_auto_check_updates)
        wx.CallLater(4000, self._check_media_dependencies)

    def _start_critical_worker(self, target, args=(), *, name: str | None = None) -> None:
        """Start a tracked daemon thread for critical operations (e.g. destructive DB work).

        These threads are allowed to run in the background, but during shutdown we will try to
        join them briefly to reduce the chance of terminating mid-operation.
        """

        def _worker():
            try:
                target(*args)
            finally:
                with self._critical_workers_lock:
                    self._critical_workers.discard(threading.current_thread())

        t = threading.Thread(target=_worker, daemon=True, name=str(name) if name else None)

        with self._critical_workers_lock:
            self._critical_workers.add(t)

        try:
            t.start()
        except Exception:
            log.exception("Failed to start critical worker thread")
            with self._critical_workers_lock:
                self._critical_workers.discard(t)

    def _check_media_dependencies(self):
        try:
            if not bool(self.config_manager.get("prompt_missing_dependencies_on_startup", True)):
                return
            missing_vlc, missing_ffmpeg, missing_ytdlp = dependency_check.check_media_tools_status()
            if missing_vlc or missing_ffmpeg or missing_ytdlp:
                msg = "Missing recommended tools:\n"
                if missing_vlc:
                    msg += "- VLC Media Player (required for playback)\n"
                if missing_ffmpeg:
                    msg += "- FFmpeg (required for some podcasts)\n"
                if missing_ytdlp:
                    msg += "- yt-dlp (required for YouTube and many media sources)\n"
                if sys.platform.startswith("win"):
                    msg += "\nWould you like to install them automatically (via winget/Ninite) and add them to PATH?"
                    msg += "\n\nTip: You can disable this prompt in Settings > General."

                    if wx.MessageBox(msg, "Install Dependencies", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        self.SetStatusText("Installing dependencies...")
                        # Run in thread to avoid freezing
                        threading.Thread(
                            target=self._install_dependencies_thread,
                            args=(missing_vlc, missing_ffmpeg, missing_ytdlp),
                            daemon=True,
                        ).start()
                else:
                    log_path = dependency_check.get_dependency_log_path()
                    msg += "\n\nThis macOS/Linux build should already bundle these tools."
                    msg += f"\nIf they still appear missing, see the log: {log_path}"
                    msg += "\n\nTip: You can disable this prompt in Settings > General."
                    wx.MessageBox(msg, "Missing Dependencies", wx.OK | wx.ICON_WARNING)
        except Exception as e:
            log.error(f"Dependency check failed: {e}")

    def _install_dependencies_thread(self, vlc, ffmpeg, ytdlp):
        try:
            dependency_check.install_media_tools(vlc=vlc, ffmpeg=ffmpeg, ytdlp=ytdlp)
            missing_vlc, missing_ffmpeg, missing_ytdlp = dependency_check.check_media_tools_status()
            if missing_vlc or missing_ffmpeg or missing_ytdlp:
                log_path = dependency_check.get_dependency_log_path()
                wx.CallAfter(
                    wx.MessageBox,
                    f"Some dependencies are still missing.\n\nSee log: {log_path}",
                    "Install Incomplete",
                    wx.ICON_WARNING,
                )
            else:
                wx.CallAfter(
                    wx.MessageBox,
                    "Dependencies installed and PATH updated. A restart is recommended.",
                    "Success",
                    wx.ICON_INFORMATION,
                )
        except Exception as e:
            wx.CallAfter(wx.MessageBox, f"Installation failed: {e}", "Error", wx.ICON_ERROR)

    def on_about(self, event):
        dlg = AboutDialog(self, APP_VERSION)
        dlg.ShowModal()
        dlg.Destroy()

    def on_add_shortcuts(self, event):
        dlg = AddShortcutsDialog(self)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            data = dlg.get_data()
        finally:
            dlg.Destroy()

        if not any(bool(v) for v in (data or {}).values()):
            return

        try:
            results = windows_integration.create_shortcuts(
                desktop=bool(data.get("desktop")),
                start_menu=bool(data.get("start_menu")),
                taskbar=bool(data.get("taskbar")),
            )
        except Exception as e:
            wx.MessageBox(f"Could not add shortcuts:\n{e}", "Shortcuts", wx.ICON_ERROR)
            return

        lines = []
        for key, label in (("desktop", "Desktop"), ("start_menu", "Start Menu"), ("taskbar", "Taskbar")):
            if key not in results:
                continue
            ok, message = results.get(key, (False, "Unknown error"))
            prefix = "OK" if ok else "Failed"
            detail = f": {message}" if message else ""
            lines.append(f"{label}: {prefix}{detail}")
        if not lines:
            lines.append("No shortcut actions were performed.")

        failed = any(not bool(results.get(k, (True, ""))[0]) for k in results.keys())
        wx.MessageBox("\n".join(lines), "Shortcuts", wx.ICON_WARNING if failed else wx.ICON_INFORMATION)

    def init_ui(self):
        self.CreateStatusBar()
        # Main Splitter: Tree vs Content Area
        splitter = wx.SplitterWindow(self)
        
        # Left: Tree (Feeds)
        self.tree = wx.TreeCtrl(splitter, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS)
        self.tree.SetName("Feeds Tree")
        self.root = self.tree.AddRoot("Root")
        self.all_feeds_node = self.tree.AppendItem(self.root, "All Feeds")
        
        # Right: Search + Splitter (List + Content)
        right_panel = wx.Panel(splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.search_ctrl = wx.SearchCtrl(right_panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetName("Article Filter")
        try:
            self.search_ctrl.SetDescriptiveText("Filter current view (Enter)")
        except Exception:
            try:
                self.search_ctrl.SetHint("Filter current view (Enter)")
            except Exception:
                pass
        try:
            self.search_ctrl.ShowCancelButton(True)
        except Exception:
            pass
        right_sizer.Add(self.search_ctrl, 0, wx.EXPAND | wx.ALL, 4)

        right_splitter = wx.SplitterWindow(right_panel)
        
        # Top Right: List (Articles)
        self.list_ctrl = wx.ListCtrl(right_splitter, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.SetName("Articles List")
        self.list_ctrl.InsertColumn(0, "Title", width=350)
        self.list_ctrl.InsertColumn(1, "Author", width=120)
        self.list_ctrl.InsertColumn(2, "Date", width=120)
        self.list_ctrl.InsertColumn(3, "Feed", width=150)
        self.list_ctrl.InsertColumn(4, "Status", width=80)
        
        # Bottom Right: Content (No embedded player anymore)
        self.content_ctrl = wx.TextCtrl(right_splitter, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.content_ctrl.SetName("Article Content")
        
        right_splitter.SplitHorizontally(self.list_ctrl, self.content_ctrl, 300)
        right_sizer.Add(right_splitter, 1, wx.EXPAND)
        right_panel.SetSizer(right_sizer)

        splitter.SplitVertically(self.tree, right_panel, 250)
        
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_select, self.tree)
        self.Bind(wx.EVT_CONTEXT_MENU, self.on_tree_context_menu, self.tree)
        
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_article_select, self.list_ctrl)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_article_activate, self.list_ctrl)
        self.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu, self.list_ctrl)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search_enter)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self.on_search_enter)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self.on_search_clear)

        # When tabbing into the content field, load full article text.
        self.content_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_content_focus)

        # Full-text extraction cache (url -> rendered text)
        self._fulltext_cache = {}
        self._fulltext_cache_source = {}
        self._fulltext_token = 0
        self._fulltext_loading_url = None
        # Debounce full-text extraction when moving through the list quickly.
        self._fulltext_debounce = None
        self._fulltext_debounce_ms = 350

        # Single-worker background thread for full-text extraction (keeps CPU usage predictable).
        self._fulltext_worker_lock = threading.Lock()
        self._fulltext_worker_event = threading.Event()
        self._fulltext_worker_queue = deque()
        self._fulltext_prefetch_token = 0
        self._fulltext_prefetch_seen = set()
        self._fulltext_worker_stop = False
        self._fulltext_worker_thread = threading.Thread(target=self._fulltext_worker_loop, daemon=True)
        self._fulltext_worker_thread.start()

        # Debounce chapter loading too (selection changes can be rapid).
        self._chapters_debounce = None
        self._chapters_debounce_ms = 500

        # Store article objects for the list
        self.current_articles = []
        self._base_articles = []

        self._bind_search_tab_escape()
        self._set_search_visible(self._search_visible, update_menu=False, update_config=False)

    def _focus_default_control(self):
        """Ensure keyboard focus lands on the tree after the frame is visible."""
        try:
            self.tree.SetFocus()
        except Exception:
            pass

    def _apply_startup_window_state(self):
        start_maximized = bool(getattr(self, "_start_maximized", False))
        if start_maximized:
            self.Maximize(True)
        elif self.IsMaximized():
            self.Maximize(False)

    def _update_search_tab_order(self) -> None:
        try:
            if getattr(self, "_search_visible", True):
                self.search_ctrl.MoveAfterInTabOrder(self.tree)
                self.list_ctrl.MoveAfterInTabOrder(self.search_ctrl)
                self.content_ctrl.MoveAfterInTabOrder(self.list_ctrl)
            else:
                self.list_ctrl.MoveAfterInTabOrder(self.tree)
                self.content_ctrl.MoveAfterInTabOrder(self.list_ctrl)
        except Exception:
            pass

    def _set_search_visible(self, show: bool, *, update_menu: bool = True, update_config: bool = True) -> None:
        self._search_visible = bool(show)
        if update_config:
            try:
                self.config_manager.set("show_search_field", self._search_visible)
            except Exception:
                pass
        try:
            self.search_ctrl.Show(self._search_visible)
        except Exception:
            pass

        try:
            parent = self.search_ctrl.GetParent()
            if parent:
                parent.Layout()
                parent.Refresh()
        except Exception:
            pass

        if not self._search_visible:
            try:
                focus = self._get_focused_window()
            except Exception:
                focus = None
            try:
                if focus == self.search_ctrl or focus in self.search_ctrl.GetChildren():
                    self.list_ctrl.SetFocus()
            except Exception:
                pass

        self._update_search_tab_order()

        if update_menu and getattr(self, "_show_search_item", None):
            try:
                self._show_search_item.Check(self._search_visible)
            except Exception:
                pass

    def _is_search_active(self) -> bool:
        return bool(getattr(self, "_search_active", False) and (self._search_query or "").strip())

    def _normalize_persistent_searches(self, searches):
        cleaned = []
        seen = set()
        for item in (searches or []):
            try:
                value = str(item or "").strip()
            except Exception:
                value = ""
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(value)
        return cleaned

    def _load_persistent_searches(self):
        try:
            items = self.config_manager.get("persistent_searches", [])
        except Exception:
            items = []
        self._persistent_searches = self._normalize_persistent_searches(items)
        self._refresh_persistent_search_controls()

    def _save_persistent_searches(self, searches):
        cleaned = self._normalize_persistent_searches(searches)
        self._persistent_searches = cleaned
        try:
            self.config_manager.set("persistent_searches", cleaned)
        except Exception:
            pass
        self._refresh_persistent_search_controls()

    def _refresh_persistent_search_controls(self):
        try:
            self.search_ctrl.AutoComplete(self._persistent_searches)
        except Exception:
            pass
        self._apply_persistent_search_menu()

    def _apply_persistent_search_menu(self):
        try:
            if getattr(self, "_persistent_search_menu", None):
                try:
                    self._persistent_search_menu.Destroy()
                except Exception:
                    pass
        except Exception:
            pass
        menu = wx.Menu()
        self._persistent_search_items = {}

        if self._persistent_searches:
            for query in self._persistent_searches:
                item = menu.Append(wx.ID_ANY, query)
                self._persistent_search_items[int(item.GetId())] = query
                self.Bind(wx.EVT_MENU, self.on_persistent_search_select, item)
        else:
            empty_item = menu.Append(wx.ID_ANY, "(No saved searches)")
            empty_item.Enable(False)

        menu.AppendSeparator()
        manage_item = menu.Append(wx.ID_ANY, "Configure Persistent Search...")
        self.Bind(wx.EVT_MENU, self.on_configure_persistent_search, manage_item)

        try:
            self.search_ctrl.SetMenu(menu)
        except Exception:
            pass
        self._persistent_search_menu = menu

    def _set_base_articles(self, articles, view_id=None) -> None:
        self._base_articles = list(articles or [])
        if view_id is None:
            view_id = getattr(self, "current_feed_id", None)
        self._base_view_id = view_id

    def _get_base_articles_for_current_view(self):
        fid = getattr(self, "current_feed_id", None)
        if fid and fid == getattr(self, "_base_view_id", None) and self._base_articles is not None:
            return list(self._base_articles or [])
        try:
            st = (self.view_cache or {}).get(fid)
        except Exception:
            st = None
        if st:
            return list(st.get("articles") or [])
        return list(getattr(self, "current_articles", []) or [])

    def _normalize_search_mode(self, mode: str) -> str:
        mode = (mode or "").strip().lower()
        if mode in ("title_only", "titles_only", "title"):
            return "title_only"
        return "title_content"

    def _normalize_article_sort_by(self, sort_by: str) -> str:
        value = (sort_by or "").strip().lower()
        valid = {"date", "name", "author", "description", "feed", "status"}
        return value if value in valid else "date"

    def _article_description_for_sort(self, article) -> str:
        content = ""
        try:
            content = str(getattr(article, "content", "") or "")
        except Exception:
            content = ""
        if not content:
            return ""
        try:
            text = re.sub(r"<[^>]+>", " ", content)
            text = re.sub(r"\s+", " ", text).strip()
            return text.lower()
        except Exception:
            return content.lower()

    def _article_sort_primary_key(self, article):
        sort_by = getattr(self, "_article_sort_by", "date")
        if sort_by == "name":
            return (getattr(article, "title", "") or "").strip().lower()
        if sort_by == "author":
            return (getattr(article, "author", "") or "").strip().lower()
        if sort_by == "description":
            return self._article_description_for_sort(article)
        if sort_by == "feed":
            try:
                feed_id = getattr(article, "feed_id", None)
                if feed_id:
                    feed = self.feed_map.get(feed_id)
                    if feed:
                        return (getattr(feed, "title", "") or "").strip().lower()
            except Exception:
                pass
            return ""
        if sort_by == "status":
            try:
                return "read" if bool(getattr(article, "is_read", False)) else "unread"
            except Exception:
                return "unread"
        # date
        try:
            return float(getattr(article, "timestamp", 0.0) or 0.0)
        except Exception:
            return 0.0

    def _sort_articles_for_display(self, articles):
        items = list(articles or [])
        if len(items) <= 1:
            return items

        # Always stabilize by recency first, then apply user sort as a stable secondary sort.
        items.sort(
            key=lambda a: (
                float(getattr(a, "timestamp", 0.0) or 0.0),
                self._article_cache_id(a) or "",
            ),
            reverse=True,
        )

        sort_by = getattr(self, "_article_sort_by", "date")
        ascending = bool(getattr(self, "_article_sort_ascending", False))
        if sort_by == "date":
            items.sort(
                key=lambda a: (
                    float(getattr(a, "timestamp", 0.0) or 0.0),
                    self._article_cache_id(a) or "",
                ),
                reverse=(not ascending),
            )
            return items

        items.sort(key=self._article_sort_primary_key, reverse=(not ascending))
        return items

    def _capture_top_article_for_restore(self, focused_article_id=None, selected_article_id=None):
        top_article_id = None
        top_idx = self.list_ctrl.GetTopItem()
        if top_idx != wx.NOT_FOUND and 0 <= top_idx < len(self.current_articles):
            # Avoid "jumping" at the top of a feed: when the view is still at row 0
            # and the user has not anchored focus/selection, don't pin the old top row.
            should_anchor = (top_idx > 0) or bool(focused_article_id) or bool(selected_article_id)
            if should_anchor:
                top_article_id = self._article_cache_id(self.current_articles[top_idx])
        return top_article_id

    def _article_search_text(self, article) -> str:
        if not article:
            return ""
        parts = []
        mode = getattr(self, "_search_mode", "title_content")
        try:
            parts.append(getattr(article, "title", "") or "")
            if mode != "title_only":
                parts.append(getattr(article, "content", "") or "")
                parts.append(getattr(article, "author", "") or "")
                parts.append(getattr(article, "url", "") or "")
                parts.append(getattr(article, "media_url", "") or "")
        except Exception:
            pass
        if mode != "title_only":
            try:
                feed_title = ""
                feed_id = getattr(article, "feed_id", None)
                if feed_id:
                    feed = self.feed_map.get(feed_id)
                    if feed:
                        feed_title = feed.title or ""
                if feed_title:
                    parts.append(feed_title)
            except Exception:
                pass
        return " ".join([p for p in parts if p]).lower()

    def _filter_articles(self, articles, query: str):
        query = (query or "").strip().lower()
        if not query:
            return list(articles or [])
        terms = [t for t in re.split(r"\s+", query) if t]
        if not terms:
            return list(articles or [])
        filtered = []
        for article in (articles or []):
            text = self._article_search_text(article)
            if all(term in text for term in terms):
                filtered.append(article)
        return filtered

    def _capture_list_view_state(self):
        focused_idx = self.list_ctrl.GetFocusedItem()
        selected_idx = self.list_ctrl.GetFirstSelected()
        focused_on_load_more = self._is_load_more_row(focused_idx)
        selected_on_load_more = self._is_load_more_row(selected_idx)

        focused_article_id = None
        if (not focused_on_load_more) and focused_idx != wx.NOT_FOUND and 0 <= focused_idx < len(self.current_articles):
            focused_article_id = self._article_cache_id(self.current_articles[focused_idx])

        selected_article_id = None
        if (not selected_on_load_more) and selected_idx != wx.NOT_FOUND and 0 <= selected_idx < len(self.current_articles):
            selected_article_id = self._article_cache_id(self.current_articles[selected_idx])

        top_article_id = self._capture_top_article_for_restore(focused_article_id, selected_article_id)

        return focused_article_id, top_article_id, selected_article_id, (focused_on_load_more or selected_on_load_more)

    def _render_articles_list(self, articles, empty_label: str = "No articles found.") -> None:
        self.list_ctrl.DeleteAllItems()
        if not articles:
            self.list_ctrl.InsertItem(0, empty_label)
            return

        self.list_ctrl.Freeze()
        for i, article in enumerate(articles):
            idx = self.list_ctrl.InsertItem(i, self._get_display_title(article))
            feed_title = ""
            if article.feed_id:
                feed = self.feed_map.get(article.feed_id)
                if feed:
                    feed_title = feed.title or ""

            self.list_ctrl.SetItem(idx, 1, article.author or "")
            self.list_ctrl.SetItem(idx, 2, utils.humanize_article_date(article.date))
            self.list_ctrl.SetItem(idx, 3, feed_title)
            self.list_ctrl.SetItem(idx, 4, "Read" if article.is_read else "Unread")
        self.list_ctrl.Thaw()

    def _bind_search_tab_escape(self):
        def _handle_tab(event):
            try:
                key = event.GetKeyCode()
            except Exception:
                key = None
            if key == wx.WXK_TAB:
                flags = wx.NavigationKeyEvent.IsBackward if event.ShiftDown() else wx.NavigationKeyEvent.IsForward
                try:
                    self.search_ctrl.Navigate(flags)
                except Exception:
                    try:
                        self.Navigate(flags)
                    except Exception:
                        pass
                return
            event.Skip()

        try:
            self.search_ctrl.Bind(wx.EVT_CHAR_HOOK, _handle_tab)
        except Exception:
            pass
        try:
            for child in self.search_ctrl.GetChildren():
                try:
                    child.Bind(wx.EVT_CHAR_HOOK, _handle_tab)
                except Exception:
                    pass
        except Exception:
            pass

    def _should_show_load_more_placeholder(self, base_count: int | None = None) -> bool:
        fid = getattr(self, "current_feed_id", None)
        if not fid:
            return False
        try:
            st = (self.view_cache or {}).get(fid)
        except Exception:
            st = None
        if not st:
            return False
        if bool(st.get("fully_loaded", False)):
            return False
        total = st.get("total")
        if total is None:
            return True
        try:
            count = int(base_count) if base_count is not None else int(len(st.get("articles") or []))
            return int(total) > count
        except Exception:
            return True

    def on_search_enter(self, event):
        query = ""
        try:
            query = self.search_ctrl.GetValue()
        except Exception:
            query = ""
        query = (query or "").strip()
        if not query:
            self._clear_search_filter(force=True)
            return
        self._search_query = query
        self._search_active = True
        self._apply_search_filter()

    def on_search_clear(self, event):
        try:
            self.search_ctrl.SetValue("")
        except Exception:
            pass
        self._clear_search_filter(force=True)

    def on_persistent_search_select(self, event):
        try:
            query = self._persistent_search_items.get(int(event.GetId()))
        except Exception:
            query = None
        if not query:
            return
        try:
            self.search_ctrl.SetValue(query)
        except Exception:
            pass
        self.on_search_enter(None)

    def on_configure_persistent_search(self, event=None):
        dlg = PersistentSearchDialog(self, self._persistent_searches)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                searches = dlg.get_searches()
                self._save_persistent_searches(searches)
        finally:
            dlg.Destroy()

    def on_toggle_search_field(self, event):
        try:
            self._set_search_visible(event.IsChecked())
        except Exception:
            self._set_search_visible(True)

    def on_change_sort_by(self, event):
        sort_by = self._sort_by_menu_items.get(int(event.GetId()), "date")
        sort_by = self._normalize_article_sort_by(sort_by)
        if sort_by == getattr(self, "_article_sort_by", "date"):
            return
        self._article_sort_by = sort_by
        try:
            self.config_manager.set("article_sort_by", sort_by)
        except Exception:
            pass
        self._refresh_articles_for_sort_change()

    def on_toggle_sort_direction(self, event):
        self._article_sort_ascending = bool(event.IsChecked())
        try:
            self.config_manager.set("article_sort_ascending", self._article_sort_ascending)
        except Exception:
            pass
        self._refresh_articles_for_sort_change()

    def _refresh_articles_for_sort_change(self):
        focused_id, top_id, selected_id, load_more_selected = self._capture_list_view_state()
        base_articles = self._get_base_articles_for_current_view()
        display_articles = list(base_articles or [])
        if self._is_search_active():
            display_articles = self._filter_articles(base_articles, self._search_query)
        self.current_articles = self._sort_articles_for_display(display_articles)
        self._remove_loading_more_placeholder()
        empty_label = "No matches." if (self._is_search_active() and base_articles) else "No articles found."
        self._render_articles_list(self.current_articles, empty_label=empty_label)

        show_more = self._should_show_load_more_placeholder(len(base_articles))
        if show_more:
            self._add_loading_more_placeholder()

        if load_more_selected and show_more:
            wx.CallAfter(self._restore_load_more_focus)
        else:
            wx.CallAfter(self._restore_list_view, focused_id, top_id, selected_id)

        if selected_id and not any(self._article_cache_id(a) == selected_id for a in self.current_articles):
            self.selected_article_id = None
            try:
                self.content_ctrl.SetValue("")
            except Exception:
                pass

        if self._is_search_active():
            try:
                self.SetStatusText(f"Filter: {len(self.current_articles)} of {len(base_articles)}")
            except Exception:
                pass

    def _apply_search_filter(self):
        if not self._is_search_active():
            return
        base_articles = self._get_base_articles_for_current_view()
        self._set_base_articles(base_articles, getattr(self, "current_feed_id", None))
        try:
            self._search_base_articles = list(base_articles or [])
            self._search_base_view_id = getattr(self, "current_feed_id", None)
        except Exception:
            self._search_base_articles = None
            self._search_base_view_id = None

        focused_id, top_id, selected_id, load_more_selected = self._capture_list_view_state()

        filtered = self._filter_articles(base_articles, self._search_query)
        self.current_articles = self._sort_articles_for_display(filtered)

        self._remove_loading_more_placeholder()
        empty_label = "No matches." if base_articles else "No articles found."
        self._render_articles_list(self.current_articles, empty_label=empty_label)

        show_more = self._should_show_load_more_placeholder(len(base_articles))
        if show_more:
            self._add_loading_more_placeholder()

        if load_more_selected and show_more:
            wx.CallAfter(self._restore_load_more_focus)
        else:
            wx.CallAfter(self._restore_list_view, focused_id, top_id, selected_id)

        try:
            self._reset_fulltext_prefetch(self.current_articles)
        except Exception:
            pass

        if not self.current_articles or (selected_id and not any(self._article_cache_id(a) == selected_id for a in self.current_articles)):
            self.selected_article_id = None
            try:
                self.content_ctrl.SetValue("")
            except Exception:
                pass

        try:
            self.SetStatusText(f"Filter: {len(self.current_articles)} of {len(base_articles)}")
        except Exception:
            pass

    def _clear_search_filter(self, force: bool = False):
        if not force and not self._is_search_active():
            self._search_active = False
            self._search_query = ""
            try:
                self.SetStatusText("")
            except Exception:
                pass
            return

        self._search_active = False
        self._search_query = ""

        base_articles = None
        try:
            if (
                self._search_base_view_id == getattr(self, "current_feed_id", None)
                and self._search_base_articles is not None
            ):
                base_articles = list(self._search_base_articles or [])
        except Exception:
            base_articles = None
        if base_articles is None:
            base_articles = self._get_base_articles_for_current_view()
        self._set_base_articles(base_articles, getattr(self, "current_feed_id", None))

        focused_id, top_id, selected_id, load_more_selected = self._capture_list_view_state()

        self.current_articles = self._sort_articles_for_display(list(base_articles or []))
        self._remove_loading_more_placeholder()
        self._render_articles_list(self.current_articles, empty_label="No articles found.")
        show_more = self._should_show_load_more_placeholder(len(base_articles))
        if show_more:
            self._add_loading_more_placeholder()

        if load_more_selected and show_more:
            wx.CallAfter(self._restore_load_more_focus)
        else:
            wx.CallAfter(self._restore_list_view, focused_id, top_id, selected_id)

        try:
            self._reset_fulltext_prefetch(self.current_articles)
        except Exception:
            pass

        if selected_id and not any(self._article_cache_id(a) == selected_id for a in self.current_articles):
            self.selected_article_id = None
            try:
                self.content_ctrl.SetValue("")
            except Exception:
                pass

        try:
            self.SetStatusText("")
        except Exception:
            pass

        self._search_base_articles = None
        self._search_base_view_id = None

    def _ensure_player_window(self):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                if getattr(pw, "_shutdown_done", False) or not bool(getattr(pw, "initialized", True)):
                    try:
                        pw.Destroy()
                    except Exception:
                        pass
                    self.player_window = None
                    pw = None
            except Exception:
                pass
        if pw:
            return pw
        try:
            pw = PlayerFrame(self, self.config_manager)
        except Exception:
            log.exception("Failed to create player window")
            return None
        self.player_window = pw
        return pw

    def _capture_unread_snapshot(self):
        snapshot = {}
        try:
            for fid, feed in (self.feed_map or {}).items():
                try:
                    snapshot[str(fid)] = int(getattr(feed, "unread_count", 0) or 0)
                except Exception:
                    snapshot[str(fid)] = 0
        except Exception:
            pass
        return snapshot

    def _extract_new_items(self, state, unread_snapshot, seen_ids):
        if not isinstance(state, dict):
            return 0
        feed_id = state.get("id")
        if feed_id is None:
            return 0
        feed_id = str(feed_id)
        if seen_ids is not None:
            if feed_id in seen_ids:
                return 0
            seen_ids.add(feed_id)

        new_items = state.get("new_items")
        if new_items is not None:
            try:
                return max(0, int(new_items))
            except Exception:
                return 0

        try:
            unread_now = int(state.get("unread_count") or 0)
        except Exception:
            unread_now = 0
        if unread_snapshot:
            try:
                unread_before = int(unread_snapshot.get(feed_id, 0) or 0)
            except Exception:
                unread_before = 0
            delta = unread_now - unread_before
            if delta > 0:
                return delta
        return 0

    def _ensure_view_state(self, view_id: str):
        """Return a mutable cache dict for a view, creating it if needed.

        View ids are strings like:
        - "all"
        - "<feed_id>"
        - "category:<name>"
        """
        if not view_id:
            view_id = "all"

        with getattr(self, "_view_cache_lock", threading.Lock()):
            st = self.view_cache.get(view_id)
            if st is None:
                st = {
                    "articles": [],
                    "id_set": set(),
                    "total": None,
                    "page_size": self.article_page_size,
                    "paged_offset": 0,
                    "fully_loaded": False,
                    "last_access": time.time(),
                }
                self.view_cache[view_id] = st
            else:
                st["last_access"] = time.time()

            # LRU prune
            try:
                max_views = int(getattr(self, "max_cached_views", 15))
            except Exception:
                max_views = 15

            if max_views > 0 and len(self.view_cache) > max_views:
                # Evict least recently used views, but never evict the current view.
                current = getattr(self, "current_feed_id", None)
                items = []
                for k, v in list(self.view_cache.items()):
                    if k == current:
                        continue
                    ts = 0.0
                    try:
                        ts = float(v.get("last_access", 0.0))
                    except Exception:
                        ts = 0.0
                    items.append((ts, k))
                items.sort()
                while len(self.view_cache) > max_views and items:
                    _, victim = items.pop(0)
                    self.view_cache.pop(victim, None)

            return st

    def _select_view(self, feed_id: str):
        """Switch the UI to a view, using cached articles when available."""
        if not feed_id:
            return

        browser = getattr(self, "_accessible_browser", None)
        if browser and browser.IsShown() and feed_id != getattr(browser, "current_view_id", None):
            try:
                browser.focus_view(feed_id)
            except Exception:
                log.exception("Failed to sync accessible browser view")

        self.current_feed_id = feed_id
        self.content_ctrl.Clear()
        self.selected_article_id = None

        # If we have cached articles for this view, render them immediately.
        with getattr(self, "_view_cache_lock", threading.Lock()):
            st = self.view_cache.get(feed_id)
        if st and isinstance(st.get("articles"), list) and st.get("articles"):
            base_articles = list(st.get("articles") or [])
            self._set_base_articles(base_articles, feed_id)
            display_articles = base_articles
            if self._is_search_active():
                display_articles = self._filter_articles(base_articles, self._search_query)

            self.current_articles = self._sort_articles_for_display(display_articles)
            self._remove_loading_more_placeholder()
            empty_label = "No matches." if (self._is_search_active() and base_articles) else "No articles found."
            self._render_articles_list(self.current_articles, empty_label=empty_label)
            if self._is_search_active():
                try:
                    self.SetStatusText(f"Filter: {len(self.current_articles)} of {len(base_articles)}")
                except Exception:
                    pass

            if not bool(st.get("fully_loaded", False)):
                self._add_loading_more_placeholder()
            else:
                self._remove_loading_more_placeholder()

            try:
                self._reset_fulltext_prefetch(self.current_articles)
            except Exception:
                pass

            # Start a cheap top-up (latest page) in the background.
            self.current_request_id = time.time()
            threading.Thread(
                target=self._load_articles_thread,
                args=(feed_id, self.current_request_id, False),
                daemon=True,
            ).start()
            return

        # If we have cached empty state, show it immediately and still top-up.
        if st and isinstance(st.get("articles"), list) and not st.get("articles") and st.get("fully_loaded"):
            self._set_base_articles([], feed_id)
            self.current_articles = []
            self.list_ctrl.DeleteAllItems()
            self._remove_loading_more_placeholder()
            self.list_ctrl.InsertItem(0, "No articles found.")
            try:
                self._reset_fulltext_prefetch([])
            except Exception:
                pass
            self.current_request_id = time.time()
            threading.Thread(
                target=self._load_articles_thread,
                args=(feed_id, self.current_request_id, False),
                daemon=True,
            ).start()
            return

        # No cache yet: do fast-first + background history.
        self._begin_articles_load(feed_id, full_load=True, clear_list=True)

    def _resume_history_thread(self, feed_id: str, request_id):
        """Continue paging older entries from the last cached offset for this view."""
        page_size = self.article_page_size
        try:
            st = self._ensure_view_state(feed_id)
            try:
                offset = int(st.get("paged_offset", 0))
            except Exception:
                offset = 0

            # Fallback: if offset wasn't tracked, infer from cached articles length.
            if offset <= 0:
                try:
                    offset = int(len(st.get("articles") or []))
                except Exception:
                    offset = 0

            total = st.get("total")

            while True:
                if not hasattr(self, "current_request_id") or request_id != self.current_request_id:
                    break
                if feed_id != getattr(self, "current_feed_id", None):
                    break
                if st.get("fully_loaded", False):
                    break
                if total is not None:
                    try:
                        if int(offset) >= int(total):
                            break
                    except Exception:
                        pass

                page, page_total = self.provider.get_articles_page(feed_id, offset=offset, limit=page_size)
                if total is None and page_total is not None:
                    total = page_total
                if page is None:
                    page = []
                if not page:
                    break

                # Sort newest-first defensively.
                page.sort(key=lambda a: (a.timestamp, self._article_cache_id(a)), reverse=True)

                wx.CallAfter(self._append_articles, page, request_id, total, page_size)

                offset += len(page)
                try:
                    st["paged_offset"] = int(offset)
                except Exception:
                    st["paged_offset"] = offset
                if total is None and len(page) < page_size:
                    break

            wx.CallAfter(self._finish_loading_more, request_id)
        except Exception as e:
            print(f"Error resuming history: {e}")

    def _strip_html(self, html_content):
        if not html_content:
            return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Get text with basic formatting preservation
            text = soup.get_text(separator='\n\n')
            return text.strip()
        except Exception:
            return html_content

    def init_menus(self):
        menubar = wx.MenuBar()
        
        file_menu = wx.Menu()
        add_feed_item = file_menu.Append(wx.ID_ANY, "&Add Feed\tCtrl+N", "Add a new RSS feed")
        remove_feed_item = file_menu.Append(wx.ID_ANY, "&Remove Feed", "Remove selected feed")
        refresh_item = file_menu.Append(wx.ID_REFRESH, "&Refresh Feeds\tF5", "Refresh all feeds")
        mark_all_read_item = file_menu.Append(wx.ID_ANY, "Mark All Items as &Read", "Mark all items as read")
        file_menu.AppendSeparator()
        add_cat_item = file_menu.Append(wx.ID_ANY, "Add &Category", "Add a new category")
        remove_cat_item = file_menu.Append(wx.ID_ANY, "Remove C&ategory", "Remove selected category")
        file_menu.AppendSeparator()
        import_opml_item = file_menu.Append(wx.ID_ANY, "&Import OPML...", "Import feeds from OPML")
        export_opml_item = file_menu.Append(wx.ID_ANY, "E&xport OPML...", "Export feeds to OPML")
        file_menu.AppendSeparator()
        persistent_search_item = file_menu.Append(wx.ID_ANY, "Configure Persistent Search...", "Configure saved search queries")
        add_shortcuts_item = file_menu.Append(wx.ID_ANY, "Add &Shortcuts...", "Create desktop, taskbar, or Start Menu shortcuts")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit", "Exit application")
        
        view_menu = wx.Menu()
        show_search_item = view_menu.AppendCheckItem(wx.ID_ANY, "Show &Search Field", "Show or hide the search field")
        show_search_item.Check(bool(getattr(self, "_search_visible", True)))
        self._show_search_item = show_search_item
        accessible_browser_item = view_menu.Append(
            wx.ID_ANY,
            "Open &Accessible Browser",
            "Open the VoiceOver-friendly browser window",
        )
        # Ctrl+P is handled globally (see main.py GlobalMediaKeyFilter). Do not make it a menu accelerator.
        player_item = view_menu.Append(wx.ID_ANY, "Show/Hide &Player (Ctrl+P)", "Show or hide the media player window")
        view_menu.AppendSeparator()

        sort_menu = wx.Menu()
        self._sort_by_menu_items = {}
        sort_choices = [
            ("date", "Date"),
            ("name", "Name"),
            ("author", "Author"),
            ("description", "Description"),
            ("feed", "Feed"),
            ("status", "Status"),
        ]
        for key, label in sort_choices:
            item = sort_menu.AppendRadioItem(wx.ID_ANY, label, f"Sort articles by {label.lower()}")
            self._sort_by_menu_items[int(item.GetId())] = key
            if key == getattr(self, "_article_sort_by", "date"):
                item.Check(True)
            self.Bind(wx.EVT_MENU, self.on_change_sort_by, item)

        sort_menu.AppendSeparator()
        self._sort_ascending_item = sort_menu.AppendCheckItem(
            wx.ID_ANY,
            "Ascending",
            "Sort in ascending order (default is descending by date)",
        )
        self._sort_ascending_item.Check(bool(getattr(self, "_article_sort_ascending", False)))
        self.Bind(wx.EVT_MENU, self.on_toggle_sort_direction, self._sort_ascending_item)
        view_menu.AppendSubMenu(sort_menu, "Sort &By")

        # Player menu (media controls)
        player_menu = wx.Menu()
        player_toggle_item = player_menu.Append(wx.ID_ANY, "Show/Hide Player (Ctrl+P)", "Show or hide the media player window")
        player_menu.AppendSeparator()
        player_play_pause_item = player_menu.Append(wx.ID_ANY, "Play/Pause", "Toggle play/pause")
        player_stop_item = player_menu.Append(wx.ID_ANY, "Stop", "Stop playback")
        player_menu.AppendSeparator()
        # NOTE: Do not use '\tCtrl+...' menu accelerators here.
        # We implement Ctrl+Arrow globally via an event filter + hold-to-repeat gate.
        # Leaving these as accelerators causes double-seeks (EVT_MENU + key handlers).
        player_rewind_item = player_menu.Append(wx.ID_ANY, "Rewind (Ctrl+Left)", "Rewind")
        player_forward_item = player_menu.Append(wx.ID_ANY, "Fast Forward (Ctrl+Right)", "Fast forward")
        player_menu.AppendSeparator()
        player_vol_up_item = player_menu.Append(wx.ID_ANY, "Volume Up (Ctrl+Up)", "Increase volume")
        player_vol_down_item = player_menu.Append(wx.ID_ANY, "Volume Down (Ctrl+Down)", "Decrease volume")
        player_menu.AppendSeparator()
        chapters_submenu = wx.Menu()
        player_menu.AppendSubMenu(chapters_submenu, "Chapters")

        self._player_menu = player_menu
        self._player_chapters_submenu = chapters_submenu
        self._player_chapter_dynamic_item_ids = []
        self._player_chapter_static_item_ids = []
        self._player_chapters_show_item = None
        self._player_chapters_prev_item = None
        self._player_chapters_next_item = None
        
        tools_menu = wx.Menu()
        find_feed_item = tools_menu.Append(
            wx.ID_ANY,
            "Find a &Podcast or RSS Feed...\tCtrl+Shift+F",
            "Find and add a podcast or RSS feed",
        )
        ytdlp_global_search_item = tools_menu.Append(
            wx.ID_ANY,
            "&Video Search...",
            "Search all yt-dlp query-search sites",
        )
        tools_menu.AppendSeparator()
        settings_item = tools_menu.Append(wx.ID_PREFERENCES, "&Settings...", "Configure application")
        
        help_menu = wx.Menu()
        check_updates_item = help_menu.Append(wx.ID_ANY, "Check for &Updates...", "Check for new versions")
        about_item = help_menu.Append(wx.ID_ABOUT, "&About", "About BlindRSS")

        menubar.Append(file_menu, "&File")
        menubar.Append(view_menu, "&View")
        menubar.Append(player_menu, "&Player")
        menubar.Append(tools_menu, "&Tools")
        menubar.Append(help_menu, "&Help")
        self.SetMenuBar(menubar)
        
        self.Bind(wx.EVT_MENU, self.on_add_feed, add_feed_item)
        self.Bind(wx.EVT_MENU, self.on_remove_feed, remove_feed_item)
        self.Bind(wx.EVT_MENU, self.on_refresh_feeds, refresh_item)
        self.Bind(wx.EVT_MENU, self.on_mark_all_read, mark_all_read_item)
        self.Bind(wx.EVT_MENU, self.on_add_category, add_cat_item)
        self.Bind(wx.EVT_MENU, self.on_remove_category, remove_cat_item)
        self.Bind(wx.EVT_MENU, self.on_import_opml, import_opml_item)
        self.Bind(wx.EVT_MENU, self.on_export_opml, export_opml_item)
        self.Bind(wx.EVT_MENU, self.on_configure_persistent_search, persistent_search_item)
        self.Bind(wx.EVT_MENU, self.on_add_shortcuts, add_shortcuts_item)
        self.Bind(wx.EVT_MENU, self.on_toggle_search_field, show_search_item)
        self.Bind(wx.EVT_MENU, self.on_open_accessible_browser, accessible_browser_item)
        self.Bind(wx.EVT_MENU, self.on_show_player, player_item)
        self.Bind(wx.EVT_MENU, self.on_show_player, player_toggle_item)
        self.Bind(wx.EVT_MENU, self.on_player_play_pause, player_play_pause_item)
        self.Bind(wx.EVT_MENU, self.on_player_stop, player_stop_item)
        self.Bind(wx.EVT_MENU, self.on_player_rewind, player_rewind_item)
        self.Bind(wx.EVT_MENU, self.on_player_forward, player_forward_item)
        self.Bind(wx.EVT_MENU, self.on_player_volume_up, player_vol_up_item)
        self.Bind(wx.EVT_MENU, self.on_player_volume_down, player_vol_down_item)
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_check_updates, check_updates_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        self.Bind(wx.EVT_MENU, self.on_find_feed, find_feed_item)
        self.Bind(wx.EVT_MENU, self.on_ytdlp_global_search, ytdlp_global_search_item)
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        self.Bind(wx.EVT_MENU_OPEN, self.on_menu_open)
        self._refresh_player_chapters_submenu()

    def init_shortcuts(self):
        # Add accelerator for Ctrl+R (F5 is handled by menu item text usually, but being explicit helps)
        self._toggle_favorite_id = wx.NewIdRef()
        entries = [
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('R'), wx.ID_REFRESH),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F5, wx.ID_REFRESH),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('D'), int(self._toggle_favorite_id)),
        ]
        accel = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self.on_toggle_favorite, id=int(self._toggle_favorite_id))

    def _get_focused_window(self) -> "wx.Window | None":
        try:
            return wx.Window.FindFocus()
        except Exception as e:
            log.debug("Could not find focused window: %s", e)
            return None

    def _is_text_input_focused(self, focus) -> bool:
        try:
            if focus is None:
                return False
        except Exception:
            return False

        try:
            if focus == self.content_ctrl:
                return True
        except Exception:
            pass

        try:
            if focus == self.search_ctrl or focus in self.search_ctrl.GetChildren():
                return True
        except Exception:
            pass

        try:
            if isinstance(focus, wx.TextCtrl):
                return True
        except Exception:
            pass
        return False

    def _make_list_activate_event(self, idx: int) -> wx.ListEvent:
        evt = wx.ListEvent(wx.wxEVT_LIST_ITEM_ACTIVATED, self.list_ctrl.GetId())
        try:
            evt.SetEventObject(self.list_ctrl)
        except Exception:
            pass
        try:
            evt.SetIndex(int(idx))
        except Exception:
            pass
        return evt

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        """Global media shortcuts while the main window is focused."""
        try:
            key = event.GetKeyCode()
        except Exception:
            key = None
        try:
            focus = self._get_focused_window()
        except Exception:
            focus = None

        if key == wx.WXK_SPACE and not event.AltDown():
            if focus == self.list_ctrl:
                idx = self.list_ctrl.GetFirstSelected()
                if idx != wx.NOT_FOUND:
                    try:
                        self.on_article_activate(self._make_list_activate_event(idx))
                        return
                    except Exception:
                        log.exception("Error activating article on space press")

        delete_keys = {
            getattr(wx, "WXK_DELETE", None),
            getattr(wx, "WXK_NUMPAD_DELETE", None),
            getattr(wx, "WXK_NUMPAD_DECIMAL", None),
        }
        if key in delete_keys:
            if focus == self.tree:
                try:
                    item = self.tree.GetSelection()
                    if item and item.IsOk():
                        data = self.tree.GetItemData(item)
                        if data and data.get("type") == "category":
                            self.on_remove_category(None)
                            return
                        if data and data.get("type") == "feed":
                            self.on_remove_feed(None)
                            return
                except Exception:
                    log.exception("Error handling tree delete shortcut")

        if key == wx.WXK_F2 and not event.ControlDown() and not event.ShiftDown() and not event.AltDown() and not event.MetaDown():
            if focus == self.tree:
                try:
                    self.on_edit_feed(None)
                    return
                except Exception:
                    log.exception("Error opening feed editor on F2")

        if (
            event.ControlDown()
            and event.ShiftDown()
            and not event.AltDown()
            and not event.MetaDown()
            and key in (ord("F"), ord("f"))
        ):
            try:
                self.on_find_feed(None)
                return
            except Exception:
                log.exception("Error opening feed search on Ctrl+Shift+F")

        if (
            event.ControlDown()
            and event.ShiftDown()
            and not event.AltDown()
            and not event.MetaDown()
        ):
            if key in (wx.WXK_LEFT, wx.WXK_RIGHT) and self._is_text_input_focused(focus):
                event.Skip()
                return
            pw = getattr(self, "player_window", None)
            if pw:
                if key == wx.WXK_LEFT:
                    try:
                        self.on_player_prev_chapter(None)
                        return
                    except Exception:
                        pass
                elif key == wx.WXK_RIGHT:
                    try:
                        self.on_player_next_chapter(None)
                        return
                    except Exception:
                        pass

        if event.ControlDown() and not event.ShiftDown() and not event.AltDown() and not event.MetaDown():
            if key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN) and self._is_text_input_focused(focus):
                event.Skip()
                return
            pw = getattr(self, "player_window", None)
            if pw:
                actions = {
                    wx.WXK_UP: lambda: pw.adjust_volume(int(getattr(pw, "volume_step", 5))),
                    wx.WXK_DOWN: lambda: pw.adjust_volume(-int(getattr(pw, "volume_step", 5))),
                    wx.WXK_LEFT: lambda: pw.seek_relative_ms(-int(getattr(pw, "seek_back_ms", 10000))),
                    wx.WXK_RIGHT: lambda: pw.seek_relative_ms(int(getattr(pw, "seek_forward_ms", 10000))),
                }
                try:
                    if key in (wx.WXK_LEFT, wx.WXK_RIGHT):
                        has_media = bool(getattr(pw, "has_media_loaded", lambda: False)())
                        if not has_media:
                            event.Skip()
                            return
                except Exception:
                    pass

                handled = False
                try:
                    if getattr(self, "_media_hotkeys", None):
                        handled = bool(self._media_hotkeys.handle_ctrl_key(event, actions))
                except Exception:
                    handled = False
                if handled:
                    return

                action = actions.get(key)
                if action is not None:
                    try:
                        action()
                        return
                    except Exception:
                        pass
        event.Skip()

    # -----------------------------------------------------------------
    # Player menu handlers
    # -----------------------------------------------------------------

    def on_player_play_pause(self, event):
        pw = getattr(self, "player_window", None)
        if pw and getattr(pw, "has_media_loaded", lambda: False)():
            try:
                pw.toggle_play_pause()
            except Exception:
                pass

    def on_player_stop(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.stop()
            except Exception:
                pass

    def on_player_rewind(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.seek_relative_ms(-int(getattr(pw, "seek_back_ms", 10000)))
            except Exception:
                pass

    def on_player_forward(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.seek_relative_ms(int(getattr(pw, "seek_forward_ms", 10000)))
            except Exception:
                pass

    def on_player_volume_up(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.adjust_volume(int(getattr(pw, "volume_step", 5)))
            except Exception:
                pass

    def on_player_volume_down(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.adjust_volume(-int(getattr(pw, "volume_step", 5)))
            except Exception:
                pass

    def on_menu_open(self, event):
        try:
            opened_menu = event.GetMenu()
        except Exception:
            opened_menu = None
        try:
            player_menu = getattr(self, "_player_menu", None)
            chapters_submenu = getattr(self, "_player_chapters_submenu", None)
            if opened_menu is player_menu or opened_menu is chapters_submenu:
                self._refresh_player_chapters_submenu()
        except Exception:
            pass
        try:
            event.Skip()
        except Exception:
            pass

    def _format_player_chapter_menu_label(self, chapter: dict) -> str:
        try:
            start = float(chapter.get("start", 0) or 0)
        except Exception:
            start = 0.0
        if start < 0:
            start = 0.0
        mins = int(start // 60)
        secs = int(start % 60)
        title = str(chapter.get("title", "") or "").strip() or f"Chapter {mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}  {title}"

    def _clear_menu_items(self, menu: wx.Menu) -> None:
        try:
            items = list(menu.GetMenuItems() or [])
        except Exception:
            items = []
        for item in items:
            try:
                menu.Delete(int(item.GetId()))
            except Exception:
                pass

    def _refresh_player_chapters_submenu(self) -> None:
        submenu = getattr(self, "_player_chapters_submenu", None)
        if submenu is None:
            return

        self._clear_menu_items(submenu)
        self._player_chapter_dynamic_item_ids = []
        self._player_chapter_static_item_ids = []
        self._player_chapters_show_item = None
        self._player_chapters_prev_item = None
        self._player_chapters_next_item = None

        pw = getattr(self, "player_window", None)
        chapters = list(getattr(pw, "current_chapters", []) or []) if pw else []
        has_chapters = bool(chapters)

        if not has_chapters:
            try:
                empty_item = submenu.Append(wx.ID_ANY, "No chapters available")
                empty_item.Enable(False)
                self._player_chapter_dynamic_item_ids.append(int(empty_item.GetId()))
            except Exception:
                pass
        else:
            try:
                active_idx = int(pw.get_active_chapter_index())
            except Exception:
                active_idx = -1

            for i, ch in enumerate(chapters):
                try:
                    label = self._format_player_chapter_menu_label(ch)
                    if int(i) == int(active_idx):
                        label = f"[Current] {label}"
                    item = submenu.Append(wx.ID_ANY, label)
                    submenu.Bind(wx.EVT_MENU, lambda evt, idx=i: self.on_player_chapter_jump(evt, idx), item)
                    self._player_chapter_dynamic_item_ids.append(int(item.GetId()))
                except Exception:
                    pass

        try:
            sep = submenu.AppendSeparator()
            self._player_chapter_static_item_ids.append(int(sep.GetId()))
        except Exception:
            pass

        try:
            self._player_chapters_show_item = submenu.Append(
                wx.ID_ANY,
                "Show Chapters...",
                "Show chapter list",
            )
            self.Bind(wx.EVT_MENU, self.on_player_show_chapters, self._player_chapters_show_item)
            self._player_chapter_static_item_ids.append(int(self._player_chapters_show_item.GetId()))
        except Exception:
            self._player_chapters_show_item = None

        try:
            self._player_chapters_prev_item = submenu.Append(
                wx.ID_ANY,
                "Previous Chapter (Ctrl+Shift+Left)",
                "Jump to previous chapter",
            )
            self.Bind(wx.EVT_MENU, self.on_player_prev_chapter, self._player_chapters_prev_item)
            self._player_chapter_static_item_ids.append(int(self._player_chapters_prev_item.GetId()))
        except Exception:
            self._player_chapters_prev_item = None

        try:
            self._player_chapters_next_item = submenu.Append(
                wx.ID_ANY,
                "Next Chapter (Ctrl+Shift+Right)",
                "Jump to next chapter",
            )
            self.Bind(wx.EVT_MENU, self.on_player_next_chapter, self._player_chapters_next_item)
            self._player_chapter_static_item_ids.append(int(self._player_chapters_next_item.GetId()))
        except Exception:
            self._player_chapters_next_item = None

        for attr in ("_player_chapters_show_item", "_player_chapters_prev_item", "_player_chapters_next_item"):
            try:
                item = getattr(self, attr, None)
                if item is not None:
                    item.Enable(bool(has_chapters))
            except Exception:
                pass

    def on_player_show_chapters(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.show_chapters_menu()
            except Exception:
                pass

    def on_player_prev_chapter(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.prev_chapter()
            except Exception:
                pass

    def on_player_next_chapter(self, event):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.next_chapter()
            except Exception:
                pass

    def on_player_chapter_jump(self, event, idx: int):
        pw = getattr(self, "player_window", None)
        if pw:
            try:
                pw.jump_to_chapter(int(idx))
            except Exception:
                pass

    def on_refresh_feeds(self, event=None):
        # Visual feedback usually good, but console for now or title?
        # self.SetTitle("RSS Reader - Refreshing...") 
        threading.Thread(target=self._manual_refresh_thread, daemon=True).start()

    def on_refresh_single_feed(self, event):
        item = self.tree.GetSelection()
        feed_id = self._get_feed_id_from_tree_item(item)
        if not feed_id:
            return
        threading.Thread(target=self._refresh_single_feed_thread, args=(feed_id,), daemon=True).start()

    def _play_sound(self, key):
        if not self.config_manager.get("sounds_enabled", True):
            return
        path = self.config_manager.get(key)
        if not path:
            return
        
        # Resolve relative path
        if not os.path.isabs(path):
            # 1. Check user/custom path (APP_DIR/path)
            custom_path = os.path.join(APP_DIR, path)
            if os.path.exists(custom_path):
                path = custom_path
            # 2. Check PyInstaller bundle path (MEIPASS/path)
            elif getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                 bundled_path = os.path.join(sys._MEIPASS, path)
                 if os.path.exists(bundled_path):
                     path = bundled_path
                 else:
                     path = custom_path
            else:
                path = custom_path
            
        if os.path.exists(path):
            try:
                snd = wx.adv.Sound(path)
                if snd.IsOk():
                    snd.Play(wx.adv.SOUND_ASYNC)
            except Exception:
                log.exception(f"Failed to play sound: {path}")

    def _get_notification_excluded_feed_ids(self) -> set[str]:
        try:
            items = self.config_manager.get("windows_notifications_excluded_feeds", []) or []
        except Exception:
            items = []
        out = set()
        for item in items:
            fid = str(item or "").strip()
            if fid:
                out.add(fid)
        return out

    def _set_notification_excluded_feed_ids(self, feed_ids) -> None:
        cleaned = sorted({str(x or "").strip() for x in (feed_ids or []) if str(x or "").strip()})
        try:
            self.config_manager.set("windows_notifications_excluded_feeds", cleaned)
        except Exception:
            pass

    def _is_feed_notifications_enabled(self, feed_id: str | None) -> bool:
        fid = str(feed_id or "").strip()
        if not fid:
            return True
        return fid not in self._get_notification_excluded_feed_ids()

    def _set_feed_notifications_enabled(self, feed_id: str, enabled: bool) -> None:
        fid = str(feed_id or "").strip()
        if not fid:
            return
        excluded = self._get_notification_excluded_feed_ids()
        if enabled:
            excluded.discard(fid)
        else:
            excluded.add(fid)
        self._set_notification_excluded_feed_ids(excluded)

    def _collect_notification_feed_entries(self):
        entries = []
        seen = set()
        try:
            for feed in (self.feed_map or {}).values():
                fid = str(getattr(feed, "id", "") or "").strip()
                if not fid or fid in seen:
                    continue
                seen.add(fid)
                title = str(getattr(feed, "title", "") or "").strip() or fid
                entries.append((fid, title))
        except Exception:
            pass

        if not entries:
            try:
                for feed in (self.provider.get_feeds() or []):
                    fid = str(getattr(feed, "id", "") or "").strip()
                    if not fid or fid in seen:
                        continue
                    seen.add(fid)
                    title = str(getattr(feed, "title", "") or "").strip() or fid
                    entries.append((fid, title))
            except Exception:
                pass

        entries.sort(key=lambda x: (x[1] or "").lower())
        return entries

    def on_toggle_feed_notifications(self, event, feed_id: str):
        enabled = bool(event.IsChecked())
        self._set_feed_notifications_enabled(feed_id, enabled)

    def _windows_notifications_enabled(self) -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            return bool(self.config_manager.get("windows_notifications_enabled", False))
        except Exception:
            return False

    def _notification_note_key(self, event_or_note) -> int | None:
        if event_or_note is None:
            return None
        note_obj = event_or_note
        try:
            getter = getattr(event_or_note, "GetEventObject", None)
            if callable(getter):
                note_obj = getter()
        except Exception:
            note_obj = None
        if note_obj is None:
            return None
        return id(note_obj)

    def _bind_notification_payload(self, note, payload: dict) -> bool:
        if note is None or not isinstance(payload, dict):
            return False
        key = id(note)
        self._notification_payloads[key] = dict(payload)
        bound_click = False
        try:
            if EVT_NOTIFICATION_MESSAGE_CLICK:
                note.Bind(EVT_NOTIFICATION_MESSAGE_CLICK, self._on_windows_notification_click)
                bound_click = True
        except Exception:
            bound_click = False
        try:
            if EVT_NOTIFICATION_MESSAGE_ACTION:
                note.Bind(EVT_NOTIFICATION_MESSAGE_ACTION, self._on_windows_notification_click)
                bound_click = True
        except Exception:
            pass
        if not bound_click:
            self._notification_payloads.pop(key, None)
            return False
        return True

    def _consume_notification_payload(self, event_or_note, pop: bool = True) -> dict | None:
        key = self._notification_note_key(event_or_note)
        if key is None:
            return None
        if pop:
            return self._notification_payloads.pop(key, None)
        return self._notification_payloads.get(key)

    def _prune_notification_payloads(self) -> None:
        if not self._notification_payloads:
            return
        active_ids = {id(note) for note in (self._active_notifications or []) if note is not None}
        stale_ids = [k for k in list(self._notification_payloads.keys()) if k not in active_ids]
        for key in stale_ids:
            self._notification_payloads.pop(key, None)

    def _resolve_notification_article(self, payload: dict) -> Article | None:
        if not isinstance(payload, dict):
            return None

        article_id = str(payload.get("article_id") or payload.get("id") or "").strip()
        article_url = str(payload.get("url") or "").strip()

        try:
            for article in (self.current_articles or []):
                cur_id = str(getattr(article, "id", "") or "").strip()
                cur_cache_id = str(self._article_cache_id(article) or "").strip()
                cur_url = str(getattr(article, "url", "") or "").strip()
                if article_id and (article_id == cur_id or article_id == cur_cache_id):
                    return article
                if article_url and article_url == cur_url:
                    return article
        except Exception:
            pass

        if article_id:
            getter = getattr(self.provider, "get_article_by_id", None)
            if callable(getter):
                try:
                    resolved = getter(article_id)
                    if resolved is not None:
                        return resolved
                except Exception:
                    pass

        media_url = str(payload.get("media_url") or "").strip()
        media_type = str(payload.get("media_type") or "").strip()
        if not (article_url or media_url):
            return None

        title = str(payload.get("title") or "New article").strip() or "New article"
        feed_id = str(payload.get("feed_id") or "").strip()
        return Article(
            title=title,
            url=article_url,
            content="",
            date="",
            author="",
            feed_id=feed_id,
            is_read=False,
            id=article_id or article_url or media_url,
            media_url=media_url,
            media_type=media_type,
            chapters=[],
        )

    def _handle_notification_activation(self, payload: dict) -> None:
        article = self._resolve_notification_article(payload)
        if article is not None:
            self._open_article(article)
            return
        url = str((payload or {}).get("url") or "").strip()
        if url:
            webbrowser.open(url)

    def _on_windows_notification_click(self, event) -> None:
        payload = self._consume_notification_payload(event, pop=True)
        if payload:
            self._handle_notification_activation(payload)

    def _show_windows_notification(self, title: str, message: str, activation_payload: dict | None = None):
        if not self._windows_notifications_enabled():
            return
        shown = False
        if activation_payload is None:
            try:
                tray = getattr(self, "tray_icon", None)
                if tray and hasattr(tray, "show_notification"):
                    shown = bool(tray.show_notification(str(title or "BlindRSS"), str(message or "")))
            except Exception:
                shown = False

        if shown:
            return

        note = None
        note_key = None
        try:
            note = wx.adv.NotificationMessage(
                str(title or "BlindRSS"),
                str(message or ""),
                parent=self,
            )
            try:
                note.SetFlags(wx.ICON_INFORMATION)
            except Exception:
                pass
            if activation_payload:
                if self._bind_notification_payload(note, activation_payload):
                    note_key = id(note)
            timeout_value = (
                max(1, int(ACTIONABLE_NOTIFICATION_TIMEOUT_SECONDS))
                if activation_payload
                else wx.adv.NotificationMessage.Timeout_Auto
            )
            shown = note.Show(timeout=timeout_value)
            if shown:
                try:
                    self._active_notifications.append(note)
                    self._prune_notification_payloads()
                except Exception:
                    pass
            elif note_key is not None:
                self._notification_payloads.pop(note_key, None)
        except Exception:
            log.debug("Failed to show Windows notification", exc_info=True)

    def _notification_preview_text(self, raw_text: str, max_len: int = 180) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return ""
        try:
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_len:
            text = text[: max_len - 3].rstrip() + "..."
        return text

    def _build_notification_body(self, preview: str, feed_title: str, include_feed: bool) -> str:
        preview_text = str(preview or "").strip()
        feed_text = str(feed_title or "").strip()
        if include_feed and feed_text and preview_text:
            return f"{feed_text} - {preview_text}"
        if include_feed and feed_text:
            return feed_text
        if preview_text:
            return preview_text
        return "New article available."

    def _build_notification_activation_payload(self, item: dict, feed_id: str = "") -> dict | None:
        if not isinstance(item, dict):
            return None
        article_id = str(item.get("id") or item.get("article_id") or "").strip()
        url = str(item.get("url") or "").strip()
        media_url = str(item.get("media_url") or "").strip()
        media_type = str(item.get("media_type") or "").strip()
        if not (article_id or url or media_url):
            return None
        return {
            "article_id": article_id,
            "title": str(item.get("title") or "New article").strip() or "New article",
            "url": url,
            "feed_id": str(feed_id or item.get("feed_id") or "").strip(),
            "media_url": media_url,
            "media_type": media_type,
        }

    def _load_recent_notification_items(self, feed_id: str, count: int, notified_ids: set[str]):
        desired = max(0, int(count or 0))
        if desired <= 0:
            return []
        fid = str(feed_id or "").strip()
        if not fid:
            return []

        view_id = f"unread:{fid}"
        fetch_limit = min(80, max(desired * 3, desired + 8))
        articles = []
        try:
            page, _total = self.provider.get_articles_page(view_id, offset=0, limit=fetch_limit)
            articles = list(page or [])
        except Exception:
            try:
                articles = list((self.provider.get_articles(view_id) or [])[:fetch_limit])
            except Exception:
                articles = []

        out = []
        seen = set()
        for article in articles:
            article_id = str(getattr(article, "id", "") or self._article_cache_id(article) or "").strip()
            if article_id and (article_id in notified_ids or article_id in seen):
                continue
            seen.add(article_id)
            title = str(getattr(article, "title", "") or "").strip() or "New article"
            preview = self._notification_preview_text(getattr(article, "content", "") or "")
            article_url = str(getattr(article, "url", "") or "").strip()
            media_url = str(getattr(article, "media_url", "") or "").strip()
            media_type = str(getattr(article, "media_type", "") or "").strip()
            out.append(
                {
                    "id": article_id,
                    "title": title,
                    "preview": preview,
                    "url": article_url,
                    "media_url": media_url,
                    "media_type": media_type,
                }
            )
            if len(out) >= desired:
                break
        return out

    def _queue_new_article_notifications_from_state(
        self,
        state: dict,
        notified_ids: set[str],
        notify_budget: dict[str, int | None],
        suppressed_counter: dict[str, int],
        fallback_new_count: int = 0,
    ):
        if not self._windows_notifications_enabled():
            return
        if not isinstance(state, dict):
            return

        feed_id = str(state.get("id") or "").strip()
        if feed_id and not self._is_feed_notifications_enabled(feed_id):
            return

        feed_title = str(state.get("title", "") or "").strip()
        include_feed = bool(self.config_manager.get("windows_notifications_include_feed_name", True))
        remaining_raw = notify_budget.get("remaining", None)
        unlimited = remaining_raw is None
        remaining = 0 if unlimited else max(0, int(remaining_raw or 0))
        if (not unlimited) and remaining <= 0:
            return

        items = state.get("new_articles") or []
        if not isinstance(items, list):
            items = []

        if not items:
            generic_count = 0
            try:
                generic_count = max(0, int(state.get("new_items") or 0))
            except Exception:
                generic_count = 0
            if generic_count <= 0:
                try:
                    generic_count = max(0, int(fallback_new_count or 0))
                except Exception:
                    generic_count = 0
            if generic_count <= 0:
                return
            if (not unlimited) and generic_count > remaining:
                suppressed_counter["count"] = int(suppressed_counter.get("count", 0)) + (generic_count - remaining)
                generic_count = remaining

            resolved_items = self._load_recent_notification_items(feed_id, generic_count, notified_ids)
            sent = 0
            for item in resolved_items:
                if not isinstance(item, dict):
                    continue
                article_id = str(item.get("id") or "").strip()
                if article_id:
                    if article_id in notified_ids:
                        continue
                    notified_ids.add(article_id)
                title = str(item.get("title") or "New article").strip() or "New article"
                preview = self._notification_preview_text(item.get("preview") or "")
                body = self._build_notification_body(preview, feed_title, include_feed)
                activation_payload = self._build_notification_activation_payload(item, feed_id=feed_id)
                wx.CallAfter(self._show_windows_notification, title, body, activation_payload)
                sent += 1
                if not unlimited:
                    remaining = max(0, remaining - 1)

            for _ in range(max(0, generic_count - sent)):
                body = feed_title if (include_feed and feed_title) else "New article available."
                wx.CallAfter(self._show_windows_notification, "New article", body)
                if not unlimited:
                    remaining = max(0, remaining - 1)
            if not unlimited:
                notify_budget["remaining"] = remaining
            return

        for item in items:
            if (not unlimited) and remaining <= 0:
                suppressed_counter["count"] = int(suppressed_counter.get("count", 0)) + 1
                continue
            if not isinstance(item, dict):
                continue
            article_id = str(item.get("id") or "").strip()
            if article_id:
                if article_id in notified_ids:
                    continue
                notified_ids.add(article_id)
            article_title = str(item.get("title") or "New article").strip() or "New article"
            preview = self._notification_preview_text(
                item.get("preview") or item.get("content") or item.get("summary") or ""
            )
            body = self._build_notification_body(preview, feed_title, include_feed)
            activation_payload = self._build_notification_activation_payload(item, feed_id=feed_id)
            wx.CallAfter(self._show_windows_notification, article_title, body, activation_payload)
            if not unlimited:
                remaining -= 1

        if not unlimited:
            notify_budget["remaining"] = remaining

    def _sync_windows_startup_setting(self, enabled: bool) -> tuple[bool, str]:
        if not sys.platform.startswith("win"):
            return True, ""
        return windows_integration.set_startup_enabled(bool(enabled))

    def _refresh_single_feed_thread(self, feed_id):
        try:
            unread_snapshot = self._capture_unread_snapshot()
            new_items_total = 0
            seen_ids = set()
            notified_ids = set()
            max_notifications = max(0, int(self.config_manager.get("windows_notifications_max_per_refresh", 0) or 0))
            notify_budget = {
                "remaining": None if max_notifications <= 0 else max_notifications
            }
            suppressed = {"count": 0}
            progress_lock = threading.Lock()

            def progress_cb(state):
                nonlocal new_items_total
                with progress_lock:
                    detected_new_items = self._extract_new_items(state, unread_snapshot, seen_ids)
                    new_items_total += detected_new_items
                    self._queue_new_article_notifications_from_state(
                        state,
                        notified_ids,
                        notify_budget,
                        suppressed,
                        fallback_new_count=detected_new_items,
                    )
                self._on_feed_refresh_progress(state)

            # Re-use the existing progress callback mechanism
            self.provider.refresh_feed(feed_id, progress_cb=progress_cb)
            wx.CallAfter(self._flush_feed_refresh_progress) # Ensure it flushes immediately
            if (
                suppressed.get("count", 0) > 0
                and bool(self.config_manager.get("windows_notifications_show_summary_when_capped", True))
            ):
                hidden = int(suppressed.get("count", 0))
                wx.CallAfter(
                    self._show_windows_notification,
                    "BlindRSS",
                    f"{hidden} new article notification(s) were suppressed by your cap.",
                )
            # We don't need to call refresh_feeds() (full tree rebuild) if we just updated one feed.
            # The progress callback updates the tree item label.
            if new_items_total > 0:
                self._play_sound("sound_refresh_complete")
        except Exception as e:
            print(f"Single feed refresh error: {e}")
            self._play_sound("sound_refresh_error")

    def _perform_retention_cleanup(self):
        """Perform retention cleanup based on config settings."""
        try:
            from core.db import cleanup_old_articles
            retention_str = self.config_manager.get("article_retention", "Unlimited")
            days = None
            if retention_str == "1 day": days = 1
            elif retention_str == "2 days": days = 2
            elif retention_str == "3 days": days = 3
            elif retention_str == "1 week": days = 7
            elif retention_str == "2 weeks": days = 14
            elif retention_str == "3 weeks": days = 21
            elif retention_str == "1 month": days = 30
            elif retention_str == "2 months": days = 60
            elif retention_str == "3 months": days = 90
            elif retention_str == "6 months": days = 180
            elif retention_str == "1 year": days = 365
            elif retention_str == "2 years": days = 730
            elif retention_str == "5 years": days = 1825
            
            if days is not None:
                cleanup_old_articles(days)
        except Exception as e:
            log.error(f"Retention cleanup failed: {e}")

    def _run_refresh(self, block: bool, force: bool = False) -> bool:
        """Run provider.refresh with optional blocking guard to avoid overlap.
        
        Performs retention cleanup BEFORE the refresh to avoid the following bug:
        1. User marks all as read
        2. Cleanup deletes those read articles
        3. RSS refresh re-inserts them as unread (because they were deleted)
        
        By running cleanup here (before RSS fetch), we ensure that only articles
        that existed BEFORE the refresh can be marked as read, and they won't be
        resurrected as unread.
        """
        acquired = False
        try:
            acquired = self._refresh_guard.acquire(blocking=block)
        except Exception:
            acquired = False
        if not acquired:
            return False
        try:
            # Perform retention cleanup before refresh to avoid resurrecting old articles
            self._perform_retention_cleanup()
            
            unread_snapshot = self._capture_unread_snapshot()
            new_items_total = 0
            seen_ids = set()
            notified_ids = set()
            max_notifications = max(0, int(self.config_manager.get("windows_notifications_max_per_refresh", 0) or 0))
            notify_budget = {
                "remaining": None if max_notifications <= 0 else max_notifications
            }
            suppressed = {"count": 0}
            progress_lock = threading.Lock()

            def progress_cb(state):
                nonlocal new_items_total
                with progress_lock:
                    detected_new_items = self._extract_new_items(state, unread_snapshot, seen_ids)
                    new_items_total += detected_new_items
                    self._queue_new_article_notifications_from_state(
                        state,
                        notified_ids,
                        notify_budget,
                        suppressed,
                        fallback_new_count=detected_new_items,
                    )
                self._on_feed_refresh_progress(state)

            if self.provider.refresh(progress_cb, force=force):
                wx.CallAfter(self.refresh_feeds)
            if (
                suppressed.get("count", 0) > 0
                and bool(self.config_manager.get("windows_notifications_show_summary_when_capped", True))
            ):
                hidden = int(suppressed.get("count", 0))
                wx.CallAfter(
                    self._show_windows_notification,
                    "BlindRSS",
                    f"{hidden} new article notification(s) were suppressed by your cap.",
                )
            if new_items_total > 0:
                self._play_sound("sound_refresh_complete")
            return True
        except Exception as e:
            print(f"Refresh error: {e}")
            self._play_sound("sound_refresh_error")
            return False
        finally:
            try:
                self._refresh_guard.release()
            except Exception:
                pass

    def _manual_refresh_thread(self):
        # Manual refresh should wait for any in-flight refresh to finish.
        ran = self._run_refresh(block=True, force=True)
        if not ran:
            print("Manual refresh skipped: another refresh is running.")

    def on_close(self, event):
        # If user prefers closing to tray and this is a real close event, just hide
        if event and self.config_manager.get("close_to_tray", False):
            event.Veto()
            self.Hide()
            return

        # Close player window cleanly
        if self.player_window:
            try:
                if hasattr(self.player_window, "shutdown"):
                    self.player_window.shutdown()
            except Exception:
                log.exception("Error during player window shutdown")
            self.player_window.Destroy()
        try:
            if getattr(self, "_media_hotkeys", None):
                self._media_hotkeys.stop()
        except Exception:
            pass
        try:
            browser = getattr(self, "_accessible_browser", None)
            if browser:
                browser.Destroy()
        except Exception:
            pass
        if self.tray_icon:
            self.tray_icon.Destroy()
        try:
            self._fulltext_worker_stop = True
            self._fulltext_worker_event.set()
        except Exception:
            pass

        self.stop_event.set()
        
        # Force immediate shutdown as requested, ignoring background threads
        try:
            self.Destroy()
        except Exception:
            pass
        os._exit(0)

    def on_iconize(self, event):
        if event.IsIconized() and self.config_manager.get("minimize_to_tray", True):
            self.Hide()
            return
        event.Skip()

    def on_tree_context_menu(self, event):
        # Determine position for the menu
        pos = event.GetPosition() # Mouse position if mouse event, (-1,-1) if keyboard event
        item = self.tree.GetSelection() # Get currently selected item (important for keyboard trigger)
        
        menu_pos = wx.DefaultPosition # Default to mouse if available
        
        if pos == wx.DefaultPosition: # Keyboard event
            if item.IsOk():
                rect = self.tree.GetBoundingRect(item)
                menu_pos = rect.GetPosition() # Use item's top-left corner relative to tree control
            else:
                # Fallback: display menu at center of the tree control if no item selected
                size = self.tree.GetSize()
                menu_pos = wx.Point(size.width // 2, size.height // 2)
        else: # Mouse event, pos is relative to the tree control itself
            menu_pos = pos

        if not item.IsOk() and pos == wx.DefaultPosition:
            # If keyboard trigger and no item selected, don't show menu.
            # Or show a generic one if that makes sense. For now, skip.
            return
            
        data = self.tree.GetItemData(item) # Data of the selected item
        if not data:
            # If no data, it means no valid item is selected, so no menu
            return
            
        menu = wx.Menu()
        
        if data["type"] == "category":
            cat_title = data["id"]

            add_sub_item = menu.Append(wx.ID_ANY, "Add Subcategory")
            self.Bind(wx.EVT_MENU, lambda e, ct=cat_title: self.on_add_subcategory(ct), add_sub_item)

            if cat_title != "Uncategorized":
                rename_item = menu.Append(wx.ID_ANY, "Rename Category")
                self.Bind(wx.EVT_MENU, lambda e: self.on_rename_category(cat_title), rename_item)

                remove_item = menu.Append(wx.ID_ANY, "Remove Category")
                self.Bind(wx.EVT_MENU, self.on_remove_category, remove_item)

                delete_with_feeds_item = menu.Append(wx.ID_ANY, "Delete Category and Feeds")
                self.Bind(wx.EVT_MENU, self.on_delete_category_with_feeds, delete_with_feeds_item)

            import_item = menu.Append(wx.ID_ANY, "Import OPML Here...")
            self.Bind(wx.EVT_MENU, lambda e: self.on_import_opml(e, target_category=cat_title), import_item)

            export_item = menu.Append(wx.ID_ANY, "Export Category to OPML...")
            self.Bind(wx.EVT_MENU, lambda e: self.on_export_category_opml(e, category_title=cat_title), export_item)
            
        elif data["type"] == "feed":
            feed_id = str(data.get("id") or "").strip()
            refresh_feed_item = menu.Append(wx.ID_ANY, "Refresh Feed")
            self.Bind(wx.EVT_MENU, self.on_refresh_single_feed, refresh_feed_item)

            edit_item = menu.Append(wx.ID_ANY, "Edit Feed...\tF2")
            self.Bind(wx.EVT_MENU, self.on_edit_feed, edit_item)

            try:
                if bool(getattr(self.provider, "supports_feed_title_reset", lambda: False)()):
                    reset_title_item = menu.Append(wx.ID_ANY, "Reset Title to Feed Default")
                    self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self.on_reset_feed_title(e, fid), reset_title_item)
            except Exception:
                pass

            copy_url_item = menu.Append(wx.ID_ANY, "Copy Feed URL")
            self.Bind(wx.EVT_MENU, self.on_copy_feed_url, copy_url_item)

            notifications_item = menu.AppendCheckItem(wx.ID_ANY, "Notifications for This Feed")
            notifications_item.Check(self._is_feed_notifications_enabled(feed_id))
            self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self.on_toggle_feed_notifications(e, fid), notifications_item)

            remove_item = menu.Append(wx.ID_ANY, "Remove Feed")
            self.Bind(wx.EVT_MENU, self.on_remove_feed, remove_item)
            
        # View options common to all viewable items
        menu.AppendSeparator()
        unread_only_item = menu.AppendCheckItem(wx.ID_ANY, "Show Only Unread")
        unread_only_item.Check(self._unread_filter_enabled)
        self.Bind(wx.EVT_MENU, self.on_toggle_unread_filter, unread_only_item)

        if menu.GetMenuItemCount() > 0:
            self.tree.PopupMenu(menu, menu_pos)
        menu.Destroy()

    def on_toggle_unread_filter(self, event):
        self._unread_filter_enabled = event.IsChecked()
        # Force reload of the current view with the new filter setting
        self._reload_selected_articles()

    def on_list_context_menu(self, event):
        pos = event.GetPosition()
        idx = self.list_ctrl.GetFocusedItem() # Get currently focused item
        
        menu_pos = wx.DefaultPosition
        
        if pos == wx.DefaultPosition: # Keyboard event
            if idx != wx.NOT_FOUND:
                rect = self.list_ctrl.GetItemRect(idx)
                menu_pos = rect.GetPosition() # Use item's top-left corner relative to list control
            else:
                size = self.list_ctrl.GetSize()
                menu_pos = wx.Point(size.width // 2, size.height // 2)
        else: # Mouse event
            menu_pos = pos

        if idx == wx.NOT_FOUND and pos == wx.DefaultPosition:
            # If keyboard trigger and no item focused, don't show menu
            return

        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, "Open Article")
        open_browser_item = menu.Append(wx.ID_ANY, "Open in Browser")
        menu.AppendSeparator()
        mark_read_item = menu.Append(wx.ID_ANY, "Mark as Read")
        mark_unread_item = menu.Append(wx.ID_ANY, "Mark as Unread")
        menu.AppendSeparator()
        copy_item = menu.Append(wx.ID_ANY, "Copy Link")
        delete_item = None
        download_item = None
        if idx != wx.NOT_FOUND and 0 <= idx < len(self.current_articles):
            if not self._is_load_more_row(idx):
                delete_item = menu.Append(wx.ID_ANY, "Delete Article\tDelete")
            article_for_menu = self.current_articles[idx]
            if article_for_menu.media_url:
                download_item = menu.Append(wx.ID_ANY, "Download")
                self.Bind(wx.EVT_MENU, lambda e, a=article_for_menu: self.on_download_article(a), download_item)
            else:
                detect_audio_item = menu.Append(wx.ID_ANY, "Detect Audio")
                self.Bind(wx.EVT_MENU, lambda e, a=article_for_menu: self.on_detect_audio(a), detect_audio_item)

            try:
                if getattr(self.provider, "supports_favorites", lambda: False)() and hasattr(self, "_toggle_favorite_id"):
                    label = "Remove from Favorites" if getattr(article_for_menu, "is_favorite", False) else "Add to Favorites"
                    menu.Append(int(self._toggle_favorite_id), f"{label}\tCtrl+D")
            except Exception:
                pass
        
        # Bindings for list menu items need to use the current idx or selected article
        # on_article_activate (event) needs an event object, but I can re-create one or just call its core logic
        # For simplicity, pass idx to lambda
        self.Bind(wx.EVT_MENU, lambda e: self.on_article_activate(event=self._make_list_activate_event(idx)), open_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_open_in_browser(idx), open_browser_item)
        self.Bind(wx.EVT_MENU, lambda e: self.mark_article_read(idx), mark_read_item)
        self.Bind(wx.EVT_MENU, lambda e: self.mark_article_unread(idx), mark_unread_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_copy_link(idx), copy_item)
        if delete_item:
            self.Bind(wx.EVT_MENU, lambda e: self.on_delete_article(), delete_item)

        self.list_ctrl.PopupMenu(menu, menu_pos)
        menu.Destroy()

    def on_open_in_browser(self, idx):
        if idx != wx.NOT_FOUND and 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            if article.url:
                webbrowser.open(article.url)

    def on_copy_feed_url(self, event):
        item = self.tree.GetSelection()
        if item.IsOk():
            data = self.tree.GetItemData(item)
            if data and data["type"] == "feed":
                feed_id = data["id"]
                feed = self.feed_map.get(feed_id)
                if feed and feed.url:
                    if wx.TheClipboard.Open():
                        wx.TheClipboard.SetData(wx.TextDataObject(feed.url))
                        wx.TheClipboard.Flush()
                        wx.TheClipboard.Close()

    def on_copy_link(self, idx):
        if 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(article.url))
                wx.TheClipboard.Flush()
                wx.TheClipboard.Close()

    def on_detect_audio(self, article):
        if not article or not article.url:
            return
            
        wx.MessageBox("Scanning for audio... This may take a few seconds.", "Detect Audio", wx.ICON_INFORMATION)
        
        def _worker():
            try:
                murl, mtype = core.discovery.detect_media(article.url)
                if murl:
                    if hasattr(self.provider, "update_article_media"):
                        self.provider.update_article_media(article.id, murl, mtype)
                        article.media_url = murl
                        article.media_type = mtype
                        
                        # Refresh UI for this item
                        wx.CallAfter(self._refresh_article_in_list, self._article_cache_id(article))
                        wx.CallAfter(wx.MessageBox, "Audio detected and added!", "Success", wx.ICON_INFORMATION)
                    else:
                         wx.CallAfter(wx.MessageBox, "Provider does not support updating media.", "Error", wx.ICON_ERROR)
                else:
                    wx.CallAfter(wx.MessageBox, "No audio found.", "Result", wx.ICON_INFORMATION)
            except Exception as e:
                wx.CallAfter(wx.MessageBox, f"Error detecting audio: {e}", "Error", wx.ICON_ERROR)
                
        threading.Thread(target=_worker, daemon=True).start()

    def _refresh_article_in_list(self, article_id):
        # Find item index
        idx = -1
        for i, a in enumerate(self.current_articles):
            if self._article_cache_id(a) == article_id:
                idx = i
                break
        
        if idx != -1:
            # We don't have a column for 'Has Audio', but if we did we'd update it.
            # However, we should update the cached view so if the user navigates away and back, it's there.
            self._update_cached_views_for_article(self.current_articles[idx])
            
            # If this is the selected article, update the content view (though content view doesn't show audio controls directly, 
            # the player logic might need to know).
            if self.selected_article_id == article_id:
                 # maybe refresh content?
                 pass

    def _update_cached_views_for_article(self, article):
        try:
            with getattr(self, "_view_cache_lock", threading.Lock()):
                for st in (self.view_cache or {}).values():
                    for a in (st.get("articles") or []):
                        if self._article_cache_id(a) == self._article_cache_id(article):
                            a.media_url = article.media_url
                            a.media_type = article.media_type
        except Exception:
            pass

    def _supports_favorites(self) -> bool:
        try:
            return bool(getattr(self.provider, "supports_favorites", lambda: False)())
        except Exception:
            log.exception("Error checking provider support for favorites")
            return False

    def _get_selected_article_index(self) -> int:
        idx = wx.NOT_FOUND
        try:
            idx = self.list_ctrl.GetFirstSelected()
        except Exception:
            idx = wx.NOT_FOUND
        if idx == wx.NOT_FOUND:
            try:
                idx = self.list_ctrl.GetFocusedItem()
            except Exception:
                idx = wx.NOT_FOUND
        return idx

    def _is_favorites_view(self, view_id: str) -> bool:
        view_id = view_id or ""
        return view_id.startswith("favorites:") or view_id.startswith("fav:")

    def _get_display_title(self, article) -> str:
        """Return title to display in list. Now that we have a Feed column, just return the title."""
        title = article.title or ""
        # Removed appending feed title since it now has a column
        return title

    def _article_cache_id(self, article) -> str | None:
        if not article:
            return None
        return getattr(article, "cache_id", getattr(article, "id", None))

    def _sync_favorite_flag_in_cached_views(self, article_id: str, is_favorite: bool) -> None:
        try:
            with getattr(self, "_view_cache_lock", threading.Lock()):
                for st in (self.view_cache or {}).values():
                    for a in (st.get("articles") or []):
                        if self._article_cache_id(a) == article_id:
                            a.is_favorite = bool(is_favorite)
        except Exception:
            log.exception("Error syncing favorite flag in cached views")

    def _update_cached_favorites_view(self, article, is_favorite: bool) -> None:
        try:
            fav_view_id = "favorites:all"
            with getattr(self, "_view_cache_lock", threading.Lock()):
                fav_st = (self.view_cache or {}).get(fav_view_id)
                if fav_st is None:
                    return

                fav_articles = list(fav_st.get("articles") or [])
                fav_id_set = set(fav_st.get("id_set") or set())
                article_cache_id = self._article_cache_id(article)

                if bool(is_favorite):
                    if article_cache_id not in fav_id_set:
                        fav_articles.append(article)
                        fav_id_set.add(article_cache_id)
                        fav_articles.sort(key=lambda a: (a.timestamp, self._article_cache_id(a)), reverse=True)
                else:
                    if article_cache_id in fav_id_set:
                        fav_id_set.discard(article_cache_id)
                        fav_articles = [a for a in fav_articles if self._article_cache_id(a) != article_cache_id]

                fav_st["articles"] = fav_articles
                fav_st["id_set"] = fav_id_set
                fav_st["last_access"] = time.time()
        except Exception:
            log.exception("Error updating cached favorites view")

    def _decrement_view_total_if_present(self, view_id: str) -> None:
        try:
            st = self._ensure_view_state(view_id)
            total = st.get("total")
            if total is None:
                return
            st["total"] = max(0, int(total) - 1)
        except Exception:
            log.exception("Error decrementing view total for view_id '%s'", view_id)

    def _remove_article_from_current_list(self, idx: int) -> None:
        froze = False
        article_id = None
        try:
            if 0 <= idx < len(self.current_articles):
                article_id = self._article_cache_id(self.current_articles[idx])
        except Exception:
            article_id = None
        try:
            self.list_ctrl.Freeze()
            froze = True
        except Exception:
            log.exception("Error freezing list_ctrl")

        try:
            try:
                self.current_articles.pop(idx)
            except Exception:
                log.exception("Error popping article from current_articles at index %s", idx)
            if article_id and self._base_view_id == getattr(self, "current_feed_id", None):
                try:
                    self._base_articles = [a for a in (self._base_articles or []) if self._article_cache_id(a) != article_id]
                except Exception:
                    pass
            try:
                self.list_ctrl.DeleteItem(idx)
            except Exception:
                log.exception("Error deleting item from list_ctrl at index %s", idx)
        finally:
            if froze:
                try:
                    self.list_ctrl.Thaw()
                except Exception:
                    log.exception("Error thawing list_ctrl")

    def _remove_article_from_cached_views(self, article_id: str) -> None:
        try:
            with getattr(self, "_view_cache_lock", threading.Lock()):
                for st in (self.view_cache or {}).values():
                    articles = list(st.get("articles") or [])
                    if not articles:
                        continue
                    new_articles = [a for a in articles if self._article_cache_id(a) != article_id]
                    if len(new_articles) == len(articles):
                        continue
                    st["articles"] = new_articles
                    st["id_set"] = {self._article_cache_id(a) for a in new_articles}
                    if st.get("total") is not None:
                        try:
                            st["total"] = max(0, int(st.get("total") or 0) - 1)
                        except Exception:
                            st["total"] = max(0, len(new_articles))
        except Exception:
            log.exception("Error removing article from cached views")

    def on_delete_article(self, event=None):
        idx = self._get_selected_article_index()
        if idx == wx.NOT_FOUND:
            return
        if self._is_load_more_row(idx):
            return
        if idx < 0 or idx >= len(self.current_articles):
            return

        article = self.current_articles[idx]
        try:
            ok = wx.MessageBox(
                "Delete this article? This cannot be undone.",
                "Confirm Delete",
                wx.YES_NO | wx.ICON_WARNING,
            )
        except Exception:
            ok = wx.NO
        if ok != wx.YES:
            return

        if not bool(getattr(self.provider, "supports_article_delete", lambda: False)()):
            wx.MessageBox(
                "This provider does not support deleting articles.",
                "Not Supported",
                wx.ICON_INFORMATION,
            )
            return

        cache_key, _url, _aid = self._fulltext_cache_key_for_article(article, idx)
        threading.Thread(
            target=self._delete_article_thread,
            args=(article.id, self._article_cache_id(article), cache_key),
            daemon=True,
        ).start()

    def _delete_article_thread(self, article_id: str, article_cache_id: str, cache_key: str) -> None:
        ok = False
        err = ""
        try:
            ok = bool(self.provider.delete_article(article_id))
        except Exception as e:
            err = str(e) or "Unknown error"
        wx.CallAfter(self._post_delete_article, article_id, article_cache_id, cache_key, ok, err)

    def _post_delete_article(self, article_id: str, article_cache_id: str, cache_key: str, ok: bool, err: str) -> None:
        if not ok:
            msg = "Could not delete article."
            if err:
                msg += f"\n\n{err}"
            wx.MessageBox(msg, "Error", wx.ICON_ERROR)
            return

        try:
            self._fulltext_cache.pop(cache_key, None)
        except Exception:
            pass
        try:
            self._fulltext_cache_source.pop(cache_key, None)
        except Exception:
            pass

        idx = None
        for i, a in enumerate(self.current_articles):
            if self._article_cache_id(a) == article_cache_id:
                idx = i
                break

        if idx is not None:
            self._remove_article_from_current_list(idx)

        self._remove_article_from_cached_views(article_cache_id)

        if not self.current_articles:
            self._show_empty_articles_state()
            return

        # Select the next closest item to keep navigation smooth.
        next_idx = 0
        if idx is not None:
            next_idx = min(idx, len(self.current_articles) - 1)
        try:
            self.list_ctrl.Select(next_idx)
            self.list_ctrl.Focus(next_idx)
        except Exception:
            pass

    def _show_empty_articles_state(self) -> None:
        try:
            self._remove_loading_more_placeholder()
            self.list_ctrl.DeleteAllItems()
            label = "No matches." if (self._is_search_active() and getattr(self, "_base_articles", None)) else "No articles found."
            self.list_ctrl.InsertItem(0, label)
            self.content_ctrl.Clear()
            self.selected_article_id = None
        except Exception:
            log.exception("Error showing empty articles state")

    def _update_current_view_cache(self, view_id: str) -> None:
        try:
            st = self._ensure_view_state(view_id)
            if self._is_search_active() and self._base_view_id == view_id:
                base_articles = list(getattr(self, "_base_articles", []) or [])
                st["articles"] = base_articles
                st["id_set"] = {self._article_cache_id(a) for a in base_articles}
            else:
                st["articles"] = self.current_articles
                st["id_set"] = {self._article_cache_id(a) for a in (self.current_articles or [])}
            st["last_access"] = time.time()
        except Exception:
            log.exception("Error updating current view cache for view_id '%s'", view_id)

    def on_toggle_favorite(self, event=None):
        if not self._supports_favorites():
            return

        idx = self._get_selected_article_index()
        if idx == wx.NOT_FOUND:
            return
        if self._is_load_more_row(idx):
            return
        if idx < 0 or idx >= len(self.current_articles):
            return

        article = self.current_articles[idx]
        try:
            new_state = self.provider.toggle_favorite(article.id)
        except Exception:
            return
        if new_state is None:
            return

        article.is_favorite = bool(new_state)

        self._sync_favorite_flag_in_cached_views(self._article_cache_id(article), bool(new_state))
        self._update_cached_favorites_view(article, bool(new_state))

        # If we're in the Favorites view and the item was removed from favorites, drop it from the list.
        fid = getattr(self, "current_feed_id", "") or ""
        if self._is_favorites_view(fid) and not bool(new_state):
            self._remove_article_from_current_list(idx)

            # If the list is now empty, show an empty-state row.
            if not self.current_articles:
                self._show_empty_articles_state()

            # Keep cache for the current view consistent.
            self._update_current_view_cache(fid)
            self._decrement_view_total_if_present(fid)

    def on_rename_category(self, old_title):
        dlg = wx.TextEntryDialog(self, f"Rename category '{old_title}' to:", "Rename Category", value=old_title)
        if dlg.ShowModal() == wx.ID_OK:
            new_title = dlg.GetValue()
            if new_title and new_title != old_title:
                if self.provider.rename_category(old_title, new_title):
                    self.refresh_feeds()
                else:
                    wx.MessageBox("Could not rename category.", "Error", wx.ICON_ERROR)
        dlg.Destroy()

    def on_add_category(self, event):
        cats = self.provider.get_categories()
        choices = ["(None - Top Level)"] + sorted(cats)
        dlg = wx.Dialog(self, title="Add Category", size=(400, 220))
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(dlg, label="Category name:"), 0, wx.ALL, 5)
        name_ctrl = wx.TextCtrl(dlg)
        sizer.Add(name_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        sizer.Add(wx.StaticText(dlg, label="Parent category:"), 0, wx.ALL, 5)
        parent_ctrl = wx.ComboBox(dlg, choices=choices, style=wx.CB_READONLY)
        parent_ctrl.SetSelection(0)
        sizer.Add(parent_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        btn_sizer = dlg.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        dlg.SetSizer(sizer)
        dlg.Centre()
        wx.CallAfter(name_ctrl.SetFocus)

        if dlg.ShowModal() == wx.ID_OK:
            name = name_ctrl.GetValue().strip()
            parent_sel = parent_ctrl.GetSelection()
            parent_title = None if parent_sel <= 0 else parent_ctrl.GetString(parent_sel)
            if name:
                if self.provider.add_category(name, parent_title=parent_title):
                    self.refresh_feeds()
                else:
                    wx.MessageBox("Could not add category.", "Error", wx.ICON_ERROR)
        dlg.Destroy()

    def on_add_subcategory(self, parent_cat_title):
        dlg = wx.TextEntryDialog(self, f"Enter subcategory name (under '{parent_cat_title}'):", "Add Subcategory")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                if self.provider.add_category(name, parent_title=parent_cat_title):
                    self.refresh_feeds()
                else:
                    wx.MessageBox("Could not add subcategory.", "Error", wx.ICON_ERROR)
        dlg.Destroy()

    def _get_parent_category_hint(self, cat_title):
        """Return a selection hint pointing to the parent category, or All Articles if top-level."""
        from core.db import get_category_hierarchy
        hierarchy = get_category_hierarchy()
        parent = hierarchy.get(cat_title)
        if parent:
            return {"type": "category", "id": parent}
        return {"type": "all", "id": "all"}

    def on_remove_category(self, event):
        item = self.tree.GetSelection()
        if item.IsOk():
            data = self.tree.GetItemData(item)
            if data and data["type"] == "category":
                if wx.MessageBox(f"Remove category '{self.tree.GetItemText(item)}'? Feeds will be moved to Uncategorized.", "Confirm", wx.YES_NO) == wx.YES:
                    self._selection_hint = self._get_parent_category_hint(data["id"])
                    if self.provider.delete_category(data["id"]):
                        self.refresh_feeds()
                    else:
                        wx.MessageBox("Could not remove category.", "Error", wx.ICON_ERROR)
            else:
                 wx.MessageBox("Please select a category to remove.", "Info")

    def on_delete_category_with_feeds(self, event):
        item = self.tree.GetSelection()
        if not item or not item.IsOk():
            return
        data = self.tree.GetItemData(item)
        if not data or data.get("type") != "category":
            wx.MessageBox("Please select a category to remove.", "Info")
            return

        cat_title = data.get("id")
        if not cat_title or str(cat_title).lower() == "uncategorized":
            wx.MessageBox("The Uncategorized folder cannot be removed.", "Info")
            return

        feed_ids = []
        try:
            from core.db import get_subcategory_titles
            sub_cats = get_subcategory_titles(cat_title)
            all_cats_to_delete = {cat_title} | set(sub_cats)
            for fid, feed in (self.feed_map or {}).items():
                if (feed.category or "Uncategorized") in all_cats_to_delete:
                    feed_ids.append(fid)
        except Exception:
            feed_ids = []

        count = len(feed_ids)
        sub_note = f" (including subcategories)" if len(sub_cats) > 0 else ""
        prompt = (
            f"Delete category '{cat_title}'{sub_note} and its {count} feed(s)?\n\n"
            "This will remove the feeds and their articles."
        )
        if wx.MessageBox(prompt, "Confirm", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return

        self._selection_hint = self._get_parent_category_hint(cat_title)
        self._start_critical_worker(
            self._delete_category_with_feeds_thread,
            args=(cat_title, feed_ids),
            name="delete_category_with_feeds",
        )

    def _delete_category_with_feeds_thread(self, cat_title: str, feed_ids: list[str]):
        failed = []
        category_deleted = True
        category_error = None
        try:
            for fid in (feed_ids or []):
                try:
                    if not self.provider.remove_feed(fid):
                        failed.append(fid)
                except Exception:
                    # The provider logs the detailed error.
                    failed.append(fid)
            try:
                # Delete subcategories first (leaves before parent)
                from core.db import get_subcategory_titles
                sub_cats = get_subcategory_titles(cat_title)
                for sub in reversed(sub_cats):
                    try:
                        self.provider.delete_category(sub)
                    except Exception:
                        log.exception("Failed to delete subcategory '%s'", sub)
                category_deleted = bool(self.provider.delete_category(cat_title))
            except Exception as e:
                category_deleted = False
                category_error = str(e) or type(e).__name__
                log.exception("Failed to delete category '%s'", cat_title)
        finally:
            wx.CallAfter(
                self._post_delete_category_with_feeds,
                cat_title,
                failed,
                category_deleted,
                category_error,
            )

    def _post_delete_category_with_feeds(
        self,
        cat_title: str,
        failed: list[str],
        category_deleted: bool,
        category_error: str | None = None,
    ):
        # Underlying DB rows changed significantly; drop view caches to avoid stale entries.
        try:
            with self._view_cache_lock:
                self.view_cache.clear()
        except Exception:
            log.exception("Failed to clear view cache after category removal")

        self.refresh_feeds()
        warnings = []
        if not category_deleted:
            warnings.append(f"Category '{cat_title}' could not be deleted.")
            if category_error:
                warnings.append(f"Error: {category_error}")
        if failed:
            warnings.append(f"{len(failed)} feed(s) could not be removed.")
        if warnings:
            wx.MessageBox("\n\n".join(warnings), "Warning", wx.ICON_WARNING)

    def refresh_loop(self):
        # If auto-refresh on startup is disabled, wait for one interval before the first check.
        if not self.config_manager.get("refresh_on_startup", True):
             interval = int(self.config_manager.get("refresh_interval", 300))
             if self.stop_event.wait(interval):
                 return

        while not self.stop_event.is_set():
            interval = int(self.config_manager.get("refresh_interval", 300))
            if interval <= 0:
                # "Never" setting: wait 5s then check config/stop event again
                if self.stop_event.wait(5):
                    return
                continue
                
            try:
                self._run_refresh(block=False)
            except Exception as e:
                print(f"Refresh error: {e}")
            # Sleep in one shot but wake early if closing
            if self.stop_event.wait(interval):
                return

    def refresh_feeds(self):
        # Offload data fetching to background thread to prevent blocking UI
        threading.Thread(target=self._refresh_feeds_worker, daemon=True).start()

    def _refresh_feeds_worker(self):
        try:
            # Retention cleanup moved to _manual_refresh_thread to prevent
            # deletion of articles that were just marked as read.
            feeds = self.provider.get_feeds()
            all_cats = self.provider.get_categories()
            # Sync categories to local DB so hierarchy is available for all providers
            from core.db import sync_categories
            sync_categories(all_cats)
            hierarchy = self.provider.get_category_hierarchy()
            wx.CallAfter(self._update_tree, feeds, all_cats, hierarchy)
        except Exception as e:
            wx.MessageBox(f"Error fetching feeds: {e}", "Error", wx.ICON_ERROR)

    def _ensure_accessible_browser(self):
        browser = getattr(self, "_accessible_browser", None)
        if browser:
            try:
                if not browser.IsBeingDeleted():
                    return browser
            except Exception:
                pass

        browser = AccessibleBrowserFrame(self)
        self._accessible_browser = browser
        browser.Bind(wx.EVT_CLOSE, self._on_accessible_browser_close)
        return browser

    def _on_accessible_browser_close(self, event):
        browser = getattr(self, "_accessible_browser", None)
        if browser:
            try:
                browser.Hide()
                event.Veto()
                return
            except Exception:
                pass
        event.Skip()

    def on_open_accessible_browser(self, event=None):
        browser = self._ensure_accessible_browser()
        selected_view_id = getattr(browser, "current_view_id", None) or getattr(self, "current_feed_id", None) or "all"
        try:
            browser.refresh_views(selected_view_id=selected_view_id)
        except Exception:
            log.exception("Failed to refresh accessible browser")
        browser.Show()
        browser.Raise()
        try:
            browser.focus_view(selected_view_id)
        except Exception:
            pass

    def _maybe_open_accessible_browser_for_voiceover(self):
        if self._voiceover_browser_attempted:
            return
        self._voiceover_browser_attempted = True
        if not sys.platform.startswith("darwin"):
            return
        try:
            if voiceover_is_running():
                self.on_open_accessible_browser()
        except Exception:
            log.exception("Failed to auto-open accessible browser for VoiceOver")

    def _on_feed_refresh_progress(self, state):
        # Called from worker threads inside provider.refresh; batch and marshal to UI thread.
        if not isinstance(state, dict):
            return
        feed_id = state.get("id")
        if not feed_id:
            return

        with self._refresh_progress_lock:
            self._refresh_progress_pending[str(feed_id)] = state
            if self._refresh_progress_flush_scheduled:
                return
            self._refresh_progress_flush_scheduled = True

        try:
            wx.CallAfter(self._flush_feed_refresh_progress)
        except Exception:
            # Likely during shutdown. We failed to schedule a flush.
            with self._refresh_progress_lock:
                self._refresh_progress_pending.clear()
                self._refresh_progress_flush_scheduled = False
            log.debug("Failed to schedule feed refresh progress flush, likely during shutdown.", exc_info=True)

    def _flush_feed_refresh_progress(self):
        with self._refresh_progress_lock:
            pending = list(self._refresh_progress_pending.values())
            self._refresh_progress_pending.clear()
            self._refresh_progress_flush_scheduled = False

        for st in pending:
            try:
                self._apply_feed_refresh_progress(st)
            except Exception:
                log.debug("Failed to apply feed refresh progress update", exc_info=True)

    def _apply_feed_refresh_progress(self, state):
        if not state:
            return
        feed_id = state.get("id")
        if not feed_id:
            return

        title = state.get("title", "")
        unread = state.get("unread_count", 0)
        category = state.get("category", "Uncategorized")

        # Update cached feed objects
        feed_obj = self.feed_map.get(feed_id)
        if feed_obj:
            feed_obj.title = title or feed_obj.title
            feed_obj.unread_count = unread
            feed_obj.category = category

        # Update tree label if present
        node = self.feed_nodes.get(feed_id)
        if node and node.IsOk():
            label = f"{title} ({unread})" if unread > 0 else title
            self.tree.SetItemText(node, label)

        # If the selected view is impacted, schedule article reload
        sel = self.tree.GetSelection()
        if sel and sel.IsOk():
            data = self.tree.GetItemData(sel)
            if data:
                typ = data.get("type")
                if typ == "all":
                    self._schedule_article_reload()
                elif typ == "feed" and data.get("id") == feed_id:
                    self._schedule_article_reload()
                elif typ == "category" and data.get("id") == category:
                    self._schedule_article_reload()

    def _schedule_article_reload(self):
        if self._article_refresh_pending:
            return
        self._article_refresh_pending = True
        wx.CallLater(120, self._run_pending_article_reload)

    def _run_pending_article_reload(self):
        self._article_refresh_pending = False
        self._reload_selected_articles()

    def _update_tree(self, feeds, all_cats, hierarchy=None):
        # Save selection to restore it later
        selected_item = self.tree.GetSelection()
        selected_data = None
        if selected_item.IsOk():
            selected_data = self.tree.GetItemData(selected_item)

        # Use selection hint if present (e.g. after deletion)
        hint = getattr(self, "_selection_hint", None)
        if hint:
            selected_data = hint
            self._selection_hint = None

        # Check if we should restore the last selected feed
        # On first load, always check the setting if enabled
        # On subsequent loads, only restore if there was no previous selection
        should_restore_saved = False
        if self.config_manager.get("remember_last_feed", False):
            if self._is_first_tree_load:
                should_restore_saved = True
            elif not selected_data:
                should_restore_saved = True
        
        if should_restore_saved:
            last_feed = self.config_manager.get("last_selected_feed")
            if last_feed:
                # Parse the saved feed_id to create matching selected_data
                if last_feed == "all":
                    selected_data = {"type": "all", "id": "all"}
                elif last_feed == "unread:all":
                    selected_data = {"type": "all", "id": "unread:all"}
                elif last_feed == "read:all":
                    selected_data = {"type": "all", "id": "read:all"}
                elif last_feed == "favorites:all":
                    selected_data = {"type": "all", "id": "favorites:all"}
                elif last_feed.startswith("unread:category:"):
                    cat_name = last_feed[16:]  # Remove "unread:category:" prefix
                    selected_data = {"type": "category", "id": cat_name}
                    self._unread_filter_enabled = True
                elif last_feed.startswith("category:"):
                    cat_name = last_feed[9:]  # Remove "category:" prefix
                    selected_data = {"type": "category", "id": cat_name}
                elif last_feed.startswith("unread:"):
                    feed_id = last_feed[7:]  # Remove "unread:" prefix
                    selected_data = {"type": "feed", "id": feed_id}
                    self._unread_filter_enabled = True
                else:
                    selected_data = {"type": "feed", "id": last_feed}
        
        # Mark that we've completed the first tree load
        self._is_first_tree_load = False

        frozen = False
        self._updating_tree = True
        try:
            self.tree.Freeze() # Stop updates while rebuilding
            frozen = True
            self.tree.DeleteChildren(self.all_feeds_node)
            self.tree.DeleteChildren(self.root)

            # Map feed id -> Feed and Tree items for quick lookup (downloads, labeling)
            self.feed_map = {f.id: f for f in feeds}
            self.feed_nodes = {}
            
            # Special Views
            self.all_feeds_node = self.tree.AppendItem(self.root, "All Articles")
            self.tree.SetItemData(self.all_feeds_node, {"type": "all", "id": "all"})

            self.unread_node = self.tree.AppendItem(self.root, "Unread Articles")
            self.tree.SetItemData(self.unread_node, {"type": "all", "id": "unread:all"})
            
            self.read_node = self.tree.AppendItem(self.root, "Read Articles")
            self.tree.SetItemData(self.read_node, {"type": "all", "id": "read:all"})

            self.favorites_node = None
            try:
                if getattr(self.provider, "supports_favorites", lambda: False)():
                    self.favorites_node = self.tree.AppendItem(self.root, "Favorites")
                    self.tree.SetItemData(self.favorites_node, {"type": "all", "id": "favorites:all"})
            except Exception:
                self.favorites_node = None
            
            # Group feeds by category
            cat_feeds_map = {c: [] for c in all_cats}

            for feed in feeds:
                cat = feed.category or "Uncategorized"
                if cat not in cat_feeds_map:
                    cat_feeds_map[cat] = []
                cat_feeds_map[cat].append(feed)

            # Build hierarchy: determine which categories are top-level vs children
            hierarchy = hierarchy if hierarchy else {}
            # children_of[parent_title] = [child_titles...]
            children_of = {}
            top_level_cats = []
            all_cat_set = set(cat_feeds_map.keys())
            for cat in all_cat_set:
                parent = hierarchy.get(cat)
                if parent and parent in all_cat_set:
                    children_of.setdefault(parent, []).append(cat)
                else:
                    top_level_cats.append(cat)

            top_level_cats.sort(key=lambda s: s.lower())
            for k in children_of:
                children_of[k].sort(key=lambda s: s.lower())

            item_to_select = None
            cat_node_map = {}  # cat_title -> tree node

            def _add_category_node(cat, parent_node):
                nonlocal item_to_select
                cat_feeds = cat_feeds_map.get(cat, [])
                cat_feeds.sort(key=lambda f: (f.title or "").lower())

                cat_node = self.tree.AppendItem(parent_node, cat)
                cat_data = {"type": "category", "id": cat}
                self.tree.SetItemData(cat_node, cat_data)
                cat_node_map[cat] = cat_node

                if selected_data and selected_data["type"] == "category" and selected_data["id"] == cat:
                    item_to_select = cat_node

                for feed in cat_feeds:
                    title = f"{feed.title} ({feed.unread_count})" if feed.unread_count > 0 else feed.title
                    node = self.tree.AppendItem(cat_node, title)
                    feed_data = {"type": "feed", "id": feed.id}
                    self.tree.SetItemData(node, feed_data)
                    self.feed_nodes[feed.id] = node

                    if selected_data and selected_data["type"] == "feed" and selected_data["id"] == feed.id:
                        item_to_select = node

                # Recursively add subcategories
                for child_cat in children_of.get(cat, []):
                    _add_category_node(child_cat, cat_node)

            for cat in top_level_cats:
                _add_category_node(cat, self.root)

            self._accessible_view_entries = build_accessible_view_entries(
                feeds,
                all_cats,
                hierarchy,
                include_favorites=bool(self.favorites_node),
            )

            self.tree.ExpandAll()

            # Restore selection (default to All Feeds on first load so the list populates)
            # If "remember last feed" is enabled and this is the first load, use the saved feed
            selection_target = None
            
            if selected_data and selected_data["type"] == "all":
                if selected_data.get("id") == "unread:all":
                    selection_target = self.unread_node
                elif selected_data.get("id") == "read:all":
                    selection_target = self.read_node
                elif selected_data.get("id") == "favorites:all" and self.favorites_node and self.favorites_node.IsOk():
                    selection_target = self.favorites_node
                else:
                    selection_target = self.all_feeds_node
            elif item_to_select and item_to_select.IsOk():
                selection_target = item_to_select
            else:
                selection_target = self.all_feeds_node

            if selection_target and selection_target.IsOk():
                # Ignore transient EVT_TREE_SEL_CHANGED during rebuild; we refresh explicitly below.
                self.tree.SelectItem(selection_target)
            browser = getattr(self, "_accessible_browser", None)
            if browser:
                try:
                    browser.refresh_views(
                        selected_view_id=getattr(browser, "current_view_id", None)
                        or getattr(self, "current_feed_id", None)
                        or "all"
                    )
                except Exception:
                    log.exception("Failed to refresh accessible browser views")
        finally:
            if frozen:
                try:
                    self.tree.Thaw() # Resume updates
                except Exception:
                    pass
            self._updating_tree = False

        # Ensure article list refreshes after auto/remote refresh.
        # Re-selecting items on a rebuilt tree does not always emit EVT_TREE_SEL_CHANGED,
        # so explicitly trigger a load for the currently selected node.
        self._reload_selected_articles()

    def _get_feed_id_from_tree_item(self, item):
        if not item or not item.IsOk():
            return None
        data = self.tree.GetItemData(item)
        if not data:
            return None
        typ = data.get("type")
        if typ == "all":
            return data.get("id")
        if typ == "feed":
            return data.get("id")
        if typ == "category":
            return f"category:{data.get('id')}"
        return None

    def _begin_articles_load(self, feed_id: str, full_load: bool = True, clear_list: bool = True):
        # Track current view so auto-refresh can do a cheap "top-up" without reloading history.
        self.current_feed_id = feed_id

        if clear_list:
            self._set_base_articles([], feed_id)
            self._remove_loading_more_placeholder()
            self.list_ctrl.DeleteAllItems()
            self.list_ctrl.InsertItem(0, "Loading...")
            self.content_ctrl.Clear()

        # Use a request ID to handle race conditions (if user clicks fast / auto-refresh overlaps).
        self.current_request_id = time.time()
        threading.Thread(
            target=self._load_articles_thread,
            args=(feed_id, self.current_request_id, full_load),
            daemon=True
        ).start()

    def _reload_selected_articles(self):
        """Refresh the currently selected view after a feed refresh/tree rebuild.

        If the view is already loaded, only fetch the newest page and merge it in.
        If the view isn't loaded yet (or selection changed), do a full load.
        """
        item = self.tree.GetSelection()
        feed_id = self._get_feed_id_from_tree_item(item)
        if not feed_id:
            return

        if self._unread_filter_enabled:
            feed_id = f"unread:{feed_id}"

        base_articles = None
        if self._base_view_id == feed_id:
            base_articles = getattr(self, "_base_articles", None)
        if self._is_search_active():
            have_articles = bool(base_articles)
        else:
            have_articles = bool(getattr(self, "current_articles", None))
        same_view = (feed_id == getattr(self, "current_feed_id", None))

        if have_articles and same_view:
            # Fast: fetch latest page and merge, do not page through history.
            self._begin_articles_load(feed_id, full_load=False, clear_list=False)
        else:
            # First load (or selection changed): fast-first + background history.
            self._begin_articles_load(feed_id, full_load=True, clear_list=True)

    def on_tree_select(self, event):
        if getattr(self, "_updating_tree", False):
            try:
                event.Skip()
            except Exception:
                pass
            return
        item = event.GetItem()
        feed_id = self._get_feed_id_from_tree_item(item)
        if not feed_id:
            return
        
        if self._unread_filter_enabled:
            feed_id = f"unread:{feed_id}"
        
        # If the feed hasn't changed (e.g. during a tree refresh where items are recreated),
        # don't reset the view. The update logic (_reload_selected_articles) handles merging new items.
        if feed_id == getattr(self, "current_feed_id", None):
            return

        # Save the last selected feed if the setting is enabled
        try:
            if self.config_manager.get("remember_last_feed", False):
                self.config_manager.set("last_selected_feed", feed_id)
        except Exception:
            pass

        self._select_view(feed_id)

    def _load_articles_thread(self, feed_id, request_id, full_load: bool = True):
        page_size = self.article_page_size
        try:
            # Fast-first page
            page, total = self.provider.get_articles_page(feed_id, offset=0, limit=page_size)
            # Ensure stable order (newest first)
            page = page or []
            page.sort(key=lambda a: (a.timestamp, self._article_cache_id(a)), reverse=True)

            if not full_load:
                wx.CallAfter(self._quick_merge_articles, page, request_id, feed_id)
                return

            wx.CallAfter(self._populate_articles, page, request_id, total, page_size)

        except Exception as e:
            print(f"Error loading articles: {e}")
            if full_load:
                wx.CallAfter(self._populate_articles, [], request_id, 0, page_size)
            # For quick mode, just do nothing on failure.

    def _populate_articles(self, articles, request_id, total=None, page_size: int | None = None):
        # If a newer request was started, ignore this result
        if not hasattr(self, 'current_request_id') or request_id != self.current_request_id:
            return
        if page_size is None:
            page_size = self.article_page_size

        self._remove_loading_more_placeholder()

        fid = getattr(self, 'current_feed_id', None)
        base_articles = list(articles or [])
        self._set_base_articles(base_articles, fid)

        if not base_articles:
            self.current_articles = []
            self.list_ctrl.DeleteAllItems()
            self.list_ctrl.InsertItem(0, 'No articles found.')
            # Cache empty state
            if fid:
                st = self._ensure_view_state(fid)
                st['articles'] = []
                st['id_set'] = set()
                st['total'] = total
                st['page_size'] = int(page_size)
                st['paged_offset'] = 0
                st['fully_loaded'] = True
                st['last_access'] = time.time()
            try:
                self._reset_fulltext_prefetch([])
            except Exception:
                pass
            return

        display_articles = base_articles
        if self._is_search_active():
            display_articles = self._filter_articles(base_articles, self._search_query)

        self.current_articles = self._sort_articles_for_display(display_articles)
        self.list_ctrl.DeleteAllItems()
        empty_label = "No matches." if (self._is_search_active() and base_articles) else "No articles found."
        self._render_articles_list(self.current_articles, empty_label=empty_label)
        if self._is_search_active():
            try:
                self.SetStatusText(f"Filter: {len(self.current_articles)} of {len(base_articles)}")
            except Exception:
                pass

        # Add a placeholder row if we know/strongly suspect there is more history coming.
        more = False
        if total is None:
            more = (len(base_articles) >= page_size)
        else:
            try:
                more = int(total) > len(base_articles)
            except Exception:
                more = False

        if more:
            self._add_loading_more_placeholder()
        else:
            self._remove_loading_more_placeholder()

        # Update cache for this view (fresh first page).
        if fid:
            st = self._ensure_view_state(fid)
            st['articles'] = base_articles
            st['id_set'] = {self._article_cache_id(a) for a in base_articles}
            st['total'] = total
            st['page_size'] = int(page_size)
            st['paged_offset'] = len(articles or [])
            # Determine completion based on paging + total/short page.
            fully = False
            if total is not None:
                try:
                    fully = int(st['paged_offset']) >= int(total)
                except Exception:
                    fully = False
            else:
                try:
                    fully = len(articles or []) < int(page_size)
                except Exception:
                    fully = False
            st['fully_loaded'] = bool(fully)
            st['last_access'] = time.time()

        try:
            self._reset_fulltext_prefetch(self.current_articles)
        except Exception:
            pass

    def _append_articles(self, articles, request_id, total=None, page_size: int | None = None):
        if not hasattr(self, 'current_request_id') or request_id != self.current_request_id:
            return
        if not articles:
            return
        if page_size is None:
            page_size = self.article_page_size

        fid = getattr(self, 'current_feed_id', None)
        base_articles = None
        if self._base_view_id == fid:
            base_articles = list(getattr(self, '_base_articles', []) or [])
        else:
            base_articles = list(getattr(self, 'current_articles', []) or [])

        # Deduplicate to avoid duplicates when the underlying feed shifts due to new entries.
        existing_ids = {self._article_cache_id(a) for a in base_articles}
        new_articles = [a for a in articles if self._article_cache_id(a) not in existing_ids]

        # Even if everything was a duplicate, persist paging progress for resume logic.
        st = None
        if fid:
            st = self._ensure_view_state(fid)
            try:
                st['paged_offset'] = int(st.get('paged_offset', 0)) + len(articles)
            except Exception:
                st['paged_offset'] = len(articles)
            if total is not None:
                st['total'] = total
            st['page_size'] = int(page_size)
            st['last_access'] = time.time()

        if not new_articles:
            return

        # Capture state before update to restore position
        focused_idx = self.list_ctrl.GetFocusedItem()
        selected_idx = self.list_ctrl.GetFirstSelected()
        focused_on_load_more = self._is_load_more_row(focused_idx)
        selected_on_load_more = self._is_load_more_row(selected_idx)

        load_more_requested = focused_on_load_more or selected_on_load_more
        first_new_article_id = None
        if load_more_requested:
            try:
                first_new_article_id = self._article_cache_id(new_articles[0])
            except Exception:
                first_new_article_id = None

        focused_article_id = None
        if (not focused_on_load_more) and focused_idx != wx.NOT_FOUND and 0 <= focused_idx < len(self.current_articles):
             focused_article_id = self._article_cache_id(self.current_articles[focused_idx])

        selected_article_id = None
        if (not selected_on_load_more) and selected_idx != wx.NOT_FOUND and 0 <= selected_idx < len(self.current_articles):
            selected_article_id = self._article_cache_id(self.current_articles[selected_idx])
        if selected_article_id is None and not selected_on_load_more:
            selected_article_id = getattr(self, "selected_article_id", None)

        # Capture top item when appropriate; avoid anchoring row 0 to prevent top-of-feed jumping.
        top_article_id = self._capture_top_article_for_restore(focused_article_id, selected_article_id)

        self._remove_loading_more_placeholder()

        # Combine and sort to ensure chronological order even if paging overlapped/shifted
        combined = base_articles + new_articles
        combined.sort(key=lambda a: (a.timestamp, self._article_cache_id(a)), reverse=True)
        self._set_base_articles(combined, fid)

        display_articles = combined
        if self._is_search_active():
            display_articles = self._filter_articles(combined, self._search_query)
        self.current_articles = self._sort_articles_for_display(display_articles)

        empty_label = "No matches." if (self._is_search_active() and combined) else "No articles found."
        self._render_articles_list(self.current_articles, empty_label=empty_label)
        if self._is_search_active():
            try:
                self.SetStatusText(f"Filter: {len(self.current_articles)} of {len(combined)}")
            except Exception:
                pass

        # Update cache for this view
        if fid:
            st = self._ensure_view_state(fid)
            st['articles'] = combined
            st['id_set'] = {self._article_cache_id(a) for a in combined}
            if total is not None:
                st['total'] = total
            st['page_size'] = int(page_size)
            # paged_offset already updated above
            try:
                if st.get('total') is not None and int(st['paged_offset']) >= int(st['total']):
                    st['fully_loaded'] = True
            except Exception:
                pass
            if st.get('total') is None and len(articles) < int(page_size):
                st['fully_loaded'] = True
            st['last_access'] = time.time()

        try:
            self._queue_fulltext_prefetch(new_articles)
        except Exception:
            pass

        more = False
        if total is None:
            more = (len(articles) >= page_size)
        else:
            try:
                # Prefer paging progress when available
                if fid and st is not None and st.get('paged_offset') is not None:
                    more = int(st.get('paged_offset', 0)) < int(total)
                else:
                    more = int(total) > len(combined)
            except Exception:
                more = False

        if more:
            self._add_loading_more_placeholder()
        else:
            self._remove_loading_more_placeholder()

        if load_more_requested and first_new_article_id:
            wx.CallAfter(self._restore_loaded_page_focus, first_new_article_id)
        else:
            # Restore view state AFTER Thaw to ensure layout is updated
            wx.CallAfter(self._restore_list_view, focused_article_id, top_article_id, selected_article_id)

    def _restore_list_view(self, focused_id, top_id, selected_id=None):
        """Restore focus, selection, and scroll position after list rebuild."""
        if not self.current_articles:
            return

        # 1. Restore Selection
        selected_idx = None
        if selected_id:
            for i, a in enumerate(self.current_articles):
                if self._article_cache_id(a) == selected_id:
                    selected_idx = i
                    self.list_ctrl.SetItemState(i, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
                    break

        # 2. Restore Focus
        focused_idx = None
        if focused_id:
            for i, a in enumerate(self.current_articles):
                if self._article_cache_id(a) == focused_id:
                    focused_idx = i
                    self.list_ctrl.SetItemState(i, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)
                    # If we don't have a specific scroll target, ensure focused is visible
                    if not top_id:
                        self.list_ctrl.EnsureVisible(i)
                    break
        elif selected_idx is not None:
            try:
                focused_idx = selected_idx
                self.list_ctrl.SetItemState(selected_idx, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)
                if not top_id:
                    self.list_ctrl.EnsureVisible(selected_idx)
            except Exception:
                pass

        # 3. Restore Scroll Position (Top Item)
        if top_id:
            target_idx = -1
            for i, a in enumerate(self.current_articles):
                if self._article_cache_id(a) == top_id:
                    target_idx = i
                    break
            
            if target_idx != -1:
                # Trick to force the item to the TOP of the view:
                # EnsureVisible(target) usually brings it to the bottom if scrolling down.
                # EnsureVisible(last) -> Scrolls to bottom.
                # EnsureVisible(target) -> Scrolls up until target is at top.
                count = self.list_ctrl.GetItemCount()
                if count > 0:
                    self.list_ctrl.EnsureVisible(count - 1)
                    self.list_ctrl.EnsureVisible(target_idx)

    def _restore_load_more_focus(self):
        """Keep focus on the Load More row after paging for screen readers."""
        try:
            count = self.list_ctrl.GetItemCount()
        except Exception:
            return
        if count <= 0:
            return

        target_idx = count - 1
        try:
            self.list_ctrl.SetItemState(target_idx, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
            self.list_ctrl.SetItemState(target_idx, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)
            self.list_ctrl.EnsureVisible(target_idx)
        except Exception:
            pass

    def _restore_loaded_page_focus(self, article_id: str | None):
        """Focus the first newly loaded article after paging."""
        if not article_id:
            return
        target_idx = -1
        try:
            for i, a in enumerate(self.current_articles):
                if self._article_cache_id(a) == article_id:
                    target_idx = i
                    break
        except Exception:
            target_idx = -1
        if target_idx < 0:
            return
        try:
            self.list_ctrl.SetItemState(target_idx, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
            self.list_ctrl.SetItemState(target_idx, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)
            self.list_ctrl.EnsureVisible(target_idx)
        except Exception:
            pass

    def _finish_loading_more(self, request_id):
        if not hasattr(self, 'current_request_id') or request_id != self.current_request_id:
            return
        self._remove_loading_more_placeholder()
        fid = getattr(self, 'current_feed_id', None)
        if fid:
            st = self._ensure_view_state(fid)
            if self._base_view_id == fid:
                base_articles = list(getattr(self, "_base_articles", []) or [])
            else:
                base_articles = list(getattr(self, "current_articles", []) or [])
            st['articles'] = base_articles
            st['id_set'] = {self._article_cache_id(a) for a in base_articles}
            st['fully_loaded'] = True
            st['last_access'] = time.time()

    def _add_loading_more_placeholder(self, loading: bool = False):
        if getattr(self, "_loading_more_placeholder", False):
            # If it already exists, just update the label if needed
            self._update_loading_placeholder(self._loading_label if loading else self._load_more_label)
            return
        label = self._loading_label if loading else self._load_more_label
        idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), label)
        self.list_ctrl.SetItem(idx, 1, "")
        self.list_ctrl.SetItem(idx, 2, "")
        self.list_ctrl.SetItem(idx, 3, "")
        self.list_ctrl.SetItem(idx, 4, "")
        self._loading_more_placeholder = True

    def _remove_loading_more_placeholder(self):
        if not getattr(self, "_loading_more_placeholder", False):
            return
        count = self.list_ctrl.GetItemCount()
        if count > 0:
            self.list_ctrl.DeleteItem(count - 1)
        self._loading_more_placeholder = False

    def _update_loading_placeholder(self, text: str | None = None):
        if not getattr(self, "_loading_more_placeholder", False):
            return
        count = self.list_ctrl.GetItemCount()
        if count <= 0:
            return
        label = text or self._load_more_label
        try:
            self.list_ctrl.SetItem(count - 1, 0, label)
            self.list_ctrl.SetItem(count - 1, 1, "")
            self.list_ctrl.SetItem(count - 1, 2, "")
            self.list_ctrl.SetItem(count - 1, 3, "")
            self.list_ctrl.SetItem(count - 1, 4, "")
        except Exception:
            pass
    def _is_load_more_row(self, idx: int) -> bool:
        if idx is None or idx < 0:
            return False
        if not getattr(self, "_loading_more_placeholder", False):
            return False
        count = self.list_ctrl.GetItemCount()
        if idx != count - 1:
            return False
        title = self.list_ctrl.GetItemText(idx)
        return title in (self._load_more_label, self._loading_label)

    def _load_more_articles(self):
        if self._load_more_inflight:
            return
        if not getattr(self, "_loading_more_placeholder", False):
            return
        feed_id = getattr(self, "current_feed_id", None)
        if not feed_id:
            return
        st = self._ensure_view_state(feed_id)
        
        # Robust offset calculation:
        # 1. Use current article count as authoritative source if available.
        # 2. Fall back to cached paged_offset.
        # This fixes bugs where cache eviction resets paged_offset to 0, causing Page 0 duplicates.
        if self._base_view_id == feed_id:
            current_count = len(getattr(self, "_base_articles", []) or [])
        else:
            current_count = len(getattr(self, "current_articles", []) or [])
        cached_offset = int(st.get("paged_offset", 0))
        offset = current_count if current_count > 0 else cached_offset

        self._load_more_inflight = True
        self._update_loading_placeholder(self._loading_label)
        request_id = getattr(self, "current_request_id", None)
        page_size = self.article_page_size
        threading.Thread(
            target=self._load_more_thread,
            args=(feed_id, request_id, offset, page_size),
            daemon=True,
        ).start()

    def _load_more_thread(self, feed_id, request_id, offset, page_size):
        try:
            page, total = self.provider.get_articles_page(feed_id, offset=offset, limit=page_size)
            page = page or []
            page.sort(key=lambda a: (a.timestamp, self._article_cache_id(a)), reverse=True)
            wx.CallAfter(self._after_load_more, page, total, request_id, page_size)
        except Exception as e:
            wx.CallAfter(self._load_more_failed, request_id, str(e))

    def _after_load_more(self, page, total, request_id, page_size):
        self._load_more_inflight = False
        if not hasattr(self, "current_request_id") or request_id != self.current_request_id:
            return
        if not page:
            self._finish_loading_more(request_id)
            return
        self._append_articles(page, request_id, total, page_size)

    def _load_more_failed(self, request_id, error_msg: str):
        self._load_more_inflight = False
        if not hasattr(self, "current_request_id") or request_id != self.current_request_id:
            return
        try:
            self._update_loading_placeholder(self._load_more_label)
        except Exception:
            pass

    def _quick_merge_articles(self, latest_page, request_id, feed_id):
        # If a newer request was started, ignore
        if not hasattr(self, 'current_request_id') or request_id != self.current_request_id:
            return
        # Ensure we're still looking at the same view
        if feed_id != getattr(self, "current_feed_id", None):
            return
        if not latest_page:
            return

        page_size = self.article_page_size

        base_articles = None
        if self._base_view_id == feed_id:
            base_articles = list(getattr(self, "_base_articles", []) or [])
        else:
            base_articles = list(getattr(self, "current_articles", []) or [])

        # No prior content: behave like a normal populate
        if not base_articles:
            self._populate_articles(latest_page, request_id, None, page_size)
            return

        existing_ids = {self._article_cache_id(a) for a in base_articles}
        new_entries = [a for a in latest_page if self._article_cache_id(a) not in existing_ids]
        if not new_entries:
            return

        # Remember selection and focus by article id
        selected_id = getattr(self, "selected_article_id", None)

        focused_idx = self.list_ctrl.GetFocusedItem()
        selected_idx = self.list_ctrl.GetFirstSelected()
        focused_on_load_more = self._is_load_more_row(focused_idx)
        selected_on_load_more = self._is_load_more_row(selected_idx)

        if selected_on_load_more:
            selected_id = None

        focused_article_id = None
        if (not focused_on_load_more) and focused_idx != wx.NOT_FOUND and 0 <= focused_idx < len(self.current_articles):
             focused_article_id = self._article_cache_id(self.current_articles[focused_idx])

        # Capture top item when appropriate; avoid anchoring row 0 to prevent top-of-feed jumping.
        top_article_id = self._capture_top_article_for_restore(focused_article_id, selected_id)

        self._updating_list = True
        try:
            # Combine, deduplicate, and sort
            combined = new_entries + base_articles
            combined.sort(key=lambda a: (a.timestamp, self._article_cache_id(a)), reverse=True)
            
            # Enforce page-limited view based on how many history pages the user loaded.
            truncated = False
            try:
                fid = getattr(self, "current_feed_id", None)
                if fid:
                    st = self._ensure_view_state(fid)
                    paged = int(st.get("paged_offset", page_size))
                    allowed_pages = max(1, (paged + page_size - 1) // page_size)
                    allowed = allowed_pages * page_size
                    if len(combined) > allowed:
                        combined = combined[:allowed]
                        truncated = True
            except Exception:
                pass

            # If no change in order or content after truncation, skip
            if [self._article_cache_id(a) for a in combined] == [self._article_cache_id(a) for a in base_articles]:
                return

            self._set_base_articles(combined, feed_id)
            display_articles = combined
            if self._is_search_active():
                display_articles = self._filter_articles(combined, self._search_query)
            self.current_articles = self._sort_articles_for_display(display_articles)
            
            # Reset placeholder state since we are doing a full rebuild
            self._remove_loading_more_placeholder()

            empty_label = "No matches." if (self._is_search_active() and combined) else "No articles found."
            self._render_articles_list(self.current_articles, empty_label=empty_label)
            if self._is_search_active():
                try:
                    self.SetStatusText(f"Filter: {len(self.current_articles)} of {len(combined)}")
                except Exception:
                    pass

            # Re-evaluate "Load More" placeholder
            more = False
            fid = getattr(self, "current_feed_id", None)
            if fid:
                st = self._ensure_view_state(fid)
                total = st.get("total")
                if total is None:
                    # If we truncated, we definitely have more.
                    # Otherwise fallback to page check
                    more = truncated or (len(combined) >= page_size)
                else:
                    try:
                        # If we have a total, checks if we've shown everything.
                        # Note: paged_offset tracks what we FETCHED, not what we show.
                        # But typically they align unless we truncated.
                        more = int(total) > len(combined)
                    except Exception:
                        more = False
            
            if more:
                self._add_loading_more_placeholder()
            else:
                self._remove_loading_more_placeholder()

            restore_load_more = focused_on_load_more or selected_on_load_more
            if restore_load_more:
                wx.CallAfter(self._restore_load_more_focus)
            else:
                # Restore View State
                wx.CallAfter(self._restore_list_view, focused_article_id, top_article_id, selected_id)

        finally:
            self._updating_list = False

        # Update cache for this view (do not reset paging offset)
        fid = getattr(self, 'current_feed_id', None)
        if fid:
            st = self._ensure_view_state(fid)
            st['articles'] = combined
            st['id_set'] = {self._article_cache_id(a) for a in combined}
            # Do NOT advance paged_offset here; quick top-ups shouldn't change history offset.
            st['page_size'] = page_size
            st['last_access'] = time.time()

        try:
            self._reset_fulltext_prefetch(self.current_articles)
        except Exception:
            pass

    def on_article_select(self, event):
        if self._updating_list:
            return
            
        idx = event.GetIndex()
        if self._is_load_more_row(idx):
            # Keep focus on placeholder; do not try to load content
            self.selected_article_id = None
            self.content_ctrl.SetValue("")
            return
        if 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            
            # Prevent flashing/resetting if the selection hasn't semantically changed
            # (e.g. during background refresh when list indices shift).
            if getattr(self, "selected_article_id", None) == self._article_cache_id(article):
                return

            self.selected_article_id = self._article_cache_id(article) # Track selection
            # Reset full-text state for new selection
            self._fulltext_loading_url = None
            self._fulltext_token += 1
            
            # Immediate feedback (fast)
            self.content_ctrl.SetValue("Loading...")

            # Debounce heavy operations (HTML parsing, marking read, etc.)
            if getattr(self, "_content_debounce", None):
                self._content_debounce.Stop()
            self._content_debounce = wx.CallLater(150, self._update_content_view, idx)

    def _update_content_view(self, idx):
        if idx < 0 or idx >= len(self.current_articles):
            return
        article = self.current_articles[idx]
        
        # Verify selection hasn't changed
        if getattr(self, "selected_article_id", None) != self._article_cache_id(article):
            return

        # Prepare content (Heavy: BeautifulSoup)
        header = f"{article.title}\n"
        header += f"Date: {utils.humanize_article_date(article.date)}\n"
        header += f"Author: {article.author}\n"
        header += f"Link: {article.url}\n"
        header += "-" * 40 + "\n\n"
        
        try:
            content = self._strip_html(article.content)
            full_text = header + content
            self.content_ctrl.SetValue(full_text)
        except Exception:
            pass
        
        # Fetch chapters
        try:
            self._schedule_chapters_load(article)
        except Exception:
            pass

        # When translation is enabled, automatically queue the async full-text pipeline so the
        # content pane is replaced with translated text without requiring an extra focus action.
        try:
            if self._translation_enabled_for_content_view():
                self._schedule_fulltext_load_for_index(idx, force=False)
        except Exception:
            pass


    def on_content_focus(self, event):
        """When the content field receives focus, force an immediate full-text load for the selected article."""
        try:
            event.Skip()
        except Exception:
            pass

        try:
            idx = self.list_ctrl.GetFirstSelected()
        except Exception:
            idx = -1

        if idx is None or idx < 0 or idx >= len(self.current_articles):
            return

        self.mark_article_read(idx)
        try:
            self._schedule_fulltext_load_for_index(idx, force=True)
        except Exception:
            pass

    def _fulltext_cache_key_for_article(self, article, idx: int):
        url = (getattr(article, "url", None) or "").strip()
        article_id = getattr(article, "id", None) or getattr(article, "article_id", None) or str(idx)
        cache_key = url if url else f"article:{article_id}"
        suffix = self._translation_fulltext_cache_suffix()
        if suffix:
            cache_key = f"{cache_key}{suffix}"
        return cache_key, url, str(article_id)

    def _translation_enabled_for_content_view(self) -> bool:
        cfg = self._translation_runtime_config()
        return bool(cfg)

    def _translation_runtime_config(self) -> dict | None:
        try:
            enabled = bool(self.config_manager.get("translation_enabled", False))
        except Exception:
            enabled = False
        if not enabled:
            return None

        try:
            provider = str(self.config_manager.get("translation_provider", "grok") or "grok").strip().lower()
        except Exception:
            provider = "grok"
        if provider not in ("grok", "groq", "openai", "openrouter", "gemini", "qwen"):
            provider = "grok"

        api_key = ""
        if provider == "groq":
            try:
                api_key = str(self.config_manager.get("translation_groq_api_key", "") or "").strip()
            except Exception:
                api_key = ""
        elif provider == "openai":
            try:
                api_key = str(self.config_manager.get("translation_openai_api_key", "") or "").strip()
            except Exception:
                api_key = ""
        elif provider == "openrouter":
            try:
                api_key = str(self.config_manager.get("translation_openrouter_api_key", "") or "").strip()
            except Exception:
                api_key = ""
        elif provider == "gemini":
            try:
                api_key = str(self.config_manager.get("translation_gemini_api_key", "") or "").strip()
            except Exception:
                api_key = ""
        elif provider == "qwen":
            try:
                api_key = str(self.config_manager.get("translation_qwen_api_key", "") or "").strip()
            except Exception:
                api_key = ""
        else:
            try:
                api_key = str(self.config_manager.get("translation_grok_api_key", "") or "").strip()
            except Exception:
                api_key = ""
        if not api_key:
            return None

        try:
            target_language = str(self.config_manager.get("translation_target_language", "en") or "en").strip()
        except Exception:
            target_language = "en"
        if not target_language:
            target_language = "en"

        try:
            grok_model = str(self.config_manager.get("translation_grok_model", "") or "").strip()
        except Exception:
            grok_model = ""
        try:
            groq_model = str(self.config_manager.get("translation_groq_model", "") or "").strip()
        except Exception:
            groq_model = ""
        try:
            openai_model = str(self.config_manager.get("translation_openai_model", "") or "").strip()
        except Exception:
            openai_model = ""
        try:
            openrouter_model = str(self.config_manager.get("translation_openrouter_model", "") or "").strip()
        except Exception:
            openrouter_model = ""
        try:
            gemini_model = str(self.config_manager.get("translation_gemini_model", "") or "").strip()
        except Exception:
            gemini_model = ""
        try:
            qwen_model = str(self.config_manager.get("translation_qwen_model", "") or "").strip()
        except Exception:
            qwen_model = ""

        model = ""
        if provider == "groq":
            model = groq_model
        elif provider == "openai":
            model = openai_model
        elif provider == "openrouter":
            model = openrouter_model
        elif provider == "gemini":
            model = gemini_model
        elif provider == "qwen":
            model = qwen_model
        else:
            model = grok_model

        try:
            timeout_s = int(self.config_manager.get("translation_timeout_seconds", 45) or 45)
        except Exception:
            timeout_s = 45
        timeout_s = max(5, min(180, timeout_s))

        try:
            chunk_chars = int(self.config_manager.get("translation_chunk_chars", 3500) or 3500)
        except Exception:
            chunk_chars = 3500
        chunk_chars = max(500, min(8000, chunk_chars))

        return {
            "provider": provider,
            "api_key": api_key,
            "target_language": target_language,
            "model": model,
            "grok_model": grok_model,
            "groq_model": groq_model,
            "openai_model": openai_model,
            "openrouter_model": openrouter_model,
            "gemini_model": gemini_model,
            "qwen_model": qwen_model,
            "timeout_s": timeout_s,
            "chunk_chars": chunk_chars,
        }

    def _translation_fulltext_cache_suffix(self) -> str:
        cfg = self._translation_runtime_config()
        if not cfg:
            return ""
        provider = str(cfg.get("provider") or "grok").strip().lower() or "grok"
        lang = str(cfg.get("target_language") or "en").strip().lower() or "en"
        model = str(cfg.get("model") or "").strip().lower()
        if model:
            return f"::tr[{provider}:{lang}:{model}]"
        return f"::tr[{provider}:{lang}]"

    def _translate_rendered_text_if_enabled(self, rendered: str) -> str:
        cfg = self._translation_runtime_config()
        if not cfg:
            return rendered
        text = str(rendered or "")
        if not text.strip():
            return text
        try:
            return translation_mod.translate_text(
                text,
                provider=str(cfg.get("provider") or "grok"),
                api_key=str(cfg.get("api_key") or ""),
                target_language=str(cfg.get("target_language") or "en"),
                grok_model=str(cfg.get("grok_model") or ""),
                groq_model=str(cfg.get("groq_model") or ""),
                openai_model=str(cfg.get("openai_model") or ""),
                openrouter_model=str(cfg.get("openrouter_model") or ""),
                gemini_model=str(cfg.get("gemini_model") or ""),
                qwen_model=str(cfg.get("qwen_model") or ""),
                timeout_s=int(cfg.get("timeout_s") or 45),
                chunk_chars=int(cfg.get("chunk_chars") or 3500),
            )
        except Exception as e:
            log.warning("Translation failed; showing original text: %s", e)
            try:
                msg = " ".join(str(e or "").split()).strip()
                if msg:
                    if len(msg) > 180:
                        msg = msg[:177].rstrip() + "..."
                    self.SetStatusText(f"Translation failed: {msg}")
            except Exception:
                pass
            return text

    def _fulltext_prefetch_enabled(self) -> bool:
        try:
            # Background prefetching can poison full-text extraction on some sites.
            # Keep caching after on-demand loads, but avoid background fetches.
            return False
        except Exception:
            return False

    def _fulltext_cache_enabled(self) -> bool:
        try:
            return bool(self.config_manager.get("cache_full_text", False))
        except Exception:
            return False

    def _provider_supports_fulltext_fetch(self) -> bool:
        prov = getattr(self, "provider", None)
        if not prov:
            return False
        try:
            fn = getattr(type(prov), "fetch_full_content", None)
        except Exception:
            fn = None
        if fn is None:
            return False
        try:
            return fn is not RSSProvider.fetch_full_content
        except Exception:
            return False

    def _should_prefer_feed_fulltext(self, url: str, fallback_html: str) -> bool:
        if not url or not fallback_html:
            return False
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            path = (parts.path or "").lower()
            query = (parts.query or "").lower()
        except Exception:
            return False
        if not host or not (host == "ning.com" or host.endswith(".ning.com")):
            return False

        # Ning member/profile activity entries often have no meaningful article page.
        # Keep the feed fragment for these, but allow full web extraction for real topics/posts.
        if "/members/" in path or path.startswith("/profile/"):
            return True

        if "xg_source=activity" in query:
            if not any(
                marker in path
                for marker in (
                    "/forum/topics/",
                    "/xn/detail/",
                    "/profiles/blog/show",
                    "/blog/",
                )
            ):
                return True

        return False

    def _cached_fulltext_is_fallback(self, text: str) -> bool:
        if not text:
            return False
        low = text.lower()
        if "full-text extraction failed. showing feed content." in low:
            return True
        if "no webpage url for this item. showing feed content." in low:
            return True
        return False

    def _cached_fulltext_is_authoritative(self, cache_key: str, url: str, looks_like_media: bool, cached_text: str) -> bool:
        if not cached_text:
            return False
        if self._cached_fulltext_is_fallback(cached_text):
            return False
        if not url or looks_like_media:
            return True
        if not self._fulltext_cache_enabled():
            return True
        try:
            # For URL-backed articles, only web extraction is authoritative.
            return self._fulltext_cache_source.get(cache_key) == "web"
        except Exception:
            return False

    def _clear_fulltext_prefetch_queue(self) -> None:
        try:
            with self._fulltext_worker_lock:
                if self._fulltext_worker_queue:
                    keep = deque([req for req in self._fulltext_worker_queue if not req.get("prefetch")])
                    self._fulltext_worker_queue = keep
                else:
                    self._fulltext_worker_queue = deque()
                self._fulltext_prefetch_seen = set()
            try:
                if not self._fulltext_worker_queue:
                    self._fulltext_worker_event.clear()
            except Exception:
                pass
        except Exception:
            pass

    def _build_fulltext_request(
        self,
        article,
        idx: int,
        *,
        token: int | None = None,
        prefetch: bool = False,
        prefetch_token: int | None = None,
        apply: bool = True,
    ) -> dict:
        cache_key, url, article_id = self._fulltext_cache_key_for_article(article, idx)
        return {
            "idx": idx,
            "cache_key": cache_key,
            "url": url,
            "fallback_html": getattr(article, "content", "") or "",
            "fallback_title": getattr(article, "title", "") or "",
            "fallback_author": getattr(article, "author", "") or "",
            "article_id": article_id,
            "token": token,
            "prefetch": bool(prefetch),
            "prefetch_token": prefetch_token,
            "apply": bool(apply),
        }

    def _reset_fulltext_prefetch(self, articles) -> None:
        if not self._fulltext_prefetch_enabled():
            self._clear_fulltext_prefetch_queue()
            return
        try:
            self._fulltext_prefetch_token = int(getattr(self, "_fulltext_prefetch_token", 0)) + 1
        except Exception:
            self._fulltext_prefetch_token = 1

        queued = 0
        token = int(getattr(self, "_fulltext_prefetch_token", 0))
        try:
            with self._fulltext_worker_lock:
                if self._fulltext_worker_queue:
                    keep = deque([req for req in self._fulltext_worker_queue if not req.get("prefetch")])
                    self._fulltext_worker_queue = keep
                else:
                    self._fulltext_worker_queue = deque()
                self._fulltext_prefetch_seen = set()
                for idx, article in enumerate(articles or []):
                    cache_key, _url, _aid = self._fulltext_cache_key_for_article(article, idx)
                    cached = self._fulltext_cache.get(cache_key)
                    if cached:
                        try:
                            looks_like_media = bool(getattr(article_extractor, "_looks_like_media_url", lambda _u: False)(_url))
                        except Exception:
                            looks_like_media = False
                        if self._cached_fulltext_is_authoritative(cache_key, _url, looks_like_media, cached):
                            continue
                    if cache_key in self._fulltext_prefetch_seen:
                        continue
                    self._fulltext_prefetch_seen.add(cache_key)
                    req = self._build_fulltext_request(
                        article,
                        idx,
                        prefetch=True,
                        prefetch_token=token,
                        apply=False,
                    )
                    self._fulltext_worker_queue.append(req)
                    queued += 1
                if queued:
                    self._fulltext_worker_event.set()
                else:
                    try:
                        self._fulltext_worker_event.clear()
                    except Exception:
                        pass
        except Exception:
            pass

    def _queue_fulltext_prefetch(self, articles) -> None:
        if not self._fulltext_prefetch_enabled():
            return
        if not articles:
            return
        token = int(getattr(self, "_fulltext_prefetch_token", 0))
        queued = 0
        try:
            with self._fulltext_worker_lock:
                for idx, article in enumerate(articles or []):
                    cache_key, _url, _aid = self._fulltext_cache_key_for_article(article, idx)
                    cached = self._fulltext_cache.get(cache_key)
                    if cached:
                        try:
                            looks_like_media = bool(getattr(article_extractor, "_looks_like_media_url", lambda _u: False)(_url))
                        except Exception:
                            looks_like_media = False
                        if self._cached_fulltext_is_authoritative(cache_key, _url, looks_like_media, cached):
                            continue
                    if cache_key in self._fulltext_prefetch_seen:
                        continue
                    self._fulltext_prefetch_seen.add(cache_key)
                    req = self._build_fulltext_request(
                        article,
                        idx,
                        prefetch=True,
                        prefetch_token=token,
                        apply=False,
                    )
                    self._fulltext_worker_queue.append(req)
                    queued += 1
                if queued:
                    self._fulltext_worker_event.set()
        except Exception:
            pass

    def _schedule_fulltext_load_for_index(self, idx: int, force: bool = False):
        if idx is None or idx < 0 or idx >= len(self.current_articles):
            return

        article = self.current_articles[idx]
        cache_key, url, _article_id = self._fulltext_cache_key_for_article(article, idx)

        cached = self._fulltext_cache.get(cache_key)
        if cached:
            try:
                looks_like_media = bool(getattr(article_extractor, "_looks_like_media_url", lambda _u: False)(url))
            except Exception:
                looks_like_media = False
            if not self._cached_fulltext_is_authoritative(cache_key, url, looks_like_media, cached):
                cached = None
        if cached:
            try:
                self._fulltext_loading_url = None
                # Fix: Don't reset text if it's already displayed (preserves cursor position)
                if self.content_ctrl.GetValue() != cached:
                    self.content_ctrl.SetValue(cached)
                    self.content_ctrl.SetInsertionPoint(0)
            except Exception:
                pass
            return
        if getattr(self, "_fulltext_debounce", None) is not None:
            try:
                self._fulltext_debounce.Stop()
            except Exception:
                pass
            self._fulltext_debounce = None

        delay = 0 if force else int(getattr(self, "_fulltext_debounce_ms", 350))
        token_snapshot = int(getattr(self, "_fulltext_token", 0))

        self._fulltext_debounce = wx.CallLater(delay, self._start_fulltext_load, idx, token_snapshot)

    def _start_fulltext_load(self, idx: int, token_snapshot: int):
        # Only proceed if selection hasn't changed since scheduling.
        if token_snapshot != int(getattr(self, "_fulltext_token", 0)):
            return

        if idx is None or idx < 0 or idx >= len(self.current_articles):
            return

        try:
            sel = self.list_ctrl.GetFirstSelected()
        except Exception:
            sel = idx
        if sel is not None and sel >= 0 and sel != idx:
            # User selection moved; don't start a load for the old index.
            return

        article = self.current_articles[idx]
        cache_key, url, _article_id = self._fulltext_cache_key_for_article(article, idx)

        # If already cached, render immediately.
        cached = self._fulltext_cache.get(cache_key)
        if cached:
            try:
                looks_like_media = bool(getattr(article_extractor, "_looks_like_media_url", lambda _u: False)(url))
            except Exception:
                looks_like_media = False
            if not self._cached_fulltext_is_authoritative(cache_key, url, looks_like_media, cached):
                cached = None
        if cached:
            try:
                self._fulltext_loading_url = None
                self.content_ctrl.SetValue(cached)
                self.content_ctrl.SetInsertionPoint(0)
            except Exception:
                pass
            return

        # Avoid duplicate in-flight loads.
        if getattr(self, "_fulltext_loading_url", None) == cache_key:
            return
        self._fulltext_loading_url = cache_key

        fallback_html = getattr(article, "content", "") or ""
        fallback_title = getattr(article, "title", "") or ""
        fallback_author = getattr(article, "author", "") or ""
        req = self._build_fulltext_request(
            article,
            idx,
            token=token_snapshot,
            prefetch=False,
            prefetch_token=None,
            apply=True,
        )
        # Preserve exact cache key computed above.
        req["cache_key"] = cache_key
        req["url"] = url
        req["article_id"] = _article_id
        req["fallback_html"] = fallback_html
        req["fallback_title"] = fallback_title
        req["fallback_author"] = fallback_author
        self._fulltext_submit_request(req, priority=True)

    def _fulltext_submit_request(self, req: dict, priority: bool = False):
        try:
            with self._fulltext_worker_lock:
                if priority:
                    self._fulltext_worker_queue.appendleft(req)
                else:
                    self._fulltext_worker_queue.append(req)
                self._fulltext_worker_event.set()
        except Exception:
            pass

    def _provider_fetch_full_content(self, article_id: str, url: str = ""):
        prov = getattr(self, "provider", None)
        if not prov or not hasattr(prov, "fetch_full_content"):
            return None
        try:
            return prov.fetch_full_content(article_id, url)
        except Exception as e:
            print(f"Provider full-content fetch failed for {article_id}: {e}")
            return None

    def _fulltext_worker_loop(self):
        while True:
            try:
                self._fulltext_worker_event.wait()
            except Exception:
                time.sleep(0.05)
                continue

            if getattr(self, "_fulltext_worker_stop", False):
                break

            req = None
            try:
                with self._fulltext_worker_lock:
                    if self._fulltext_worker_queue:
                        req = self._fulltext_worker_queue.popleft()
                    if not self._fulltext_worker_queue:
                        self._fulltext_worker_event.clear()
            except Exception:
                req = None
                try:
                    self._fulltext_worker_event.clear()
                except Exception:
                    pass

            if not req:
                continue

            token_snapshot = req.get("token", None)
            try:
                token_snapshot = int(token_snapshot) if token_snapshot is not None else None
            except Exception:
                token_snapshot = None
            is_prefetch = bool(req.get("prefetch", False))
            prefetch_token = req.get("prefetch_token", None)
            try:
                prefetch_token = int(prefetch_token) if prefetch_token is not None else None
            except Exception:
                prefetch_token = None
            apply_to_ui = bool(req.get("apply", True))
            cache_key = (req.get("cache_key") or "").strip()
            url = (req.get("url") or "").strip()
            fallback_html = req.get("fallback_html") or ""
            fallback_title = req.get("fallback_title") or ""
            fallback_author = req.get("fallback_author") or ""

            if is_prefetch:
                if not self._fulltext_prefetch_enabled():
                    continue
                if prefetch_token is not None and prefetch_token != int(getattr(self, "_fulltext_prefetch_token", 0)):
                    continue
                if cache_key and cache_key in self._fulltext_cache:
                    cached = self._fulltext_cache.get(cache_key)
                    try:
                        looks_like_media = bool(getattr(article_extractor, "_looks_like_media_url", lambda _u: False)(url))
                    except Exception:
                        looks_like_media = False
                    if cached and self._cached_fulltext_is_authoritative(cache_key, url, looks_like_media, cached):
                        continue
            else:
                # If selection already changed before we start, skip the expensive work.
                if token_snapshot is not None and token_snapshot != int(getattr(self, "_fulltext_token", 0)):
                    continue

            err = None
            rendered = None
            cacheable = True
            looks_like_media = False
            try:
                looks_like_media = bool(getattr(article_extractor, "_looks_like_media_url", lambda _u: False)(url))
            except Exception:
                looks_like_media = False

            is_web_eligible = bool(url) and not looks_like_media
            render_source = None
            prefer_feed_first = False

            if is_prefetch:
                # Background prefetch uses provider-side fetch only (avoids hammering sites).
                provider_html = None
                try:
                    provider_html = self._provider_fetch_full_content(req.get("article_id"), url)
                except Exception as e:
                    if not err: err = str(e) or "Unknown error"
                if provider_html:
                    try:
                        rendered = article_extractor.render_full_article(
                            "",
                            fallback_html=provider_html,
                            fallback_title=fallback_title,
                            fallback_author=fallback_author,
                            prefer_feed_content=False,
                        )
                        render_source = "provider"
                    except Exception as e:
                        if not err: err = str(e) or "Unknown error"
                        rendered = None
            else:
                if is_web_eligible:
                    prefer_feed_first = self._should_prefer_feed_fulltext(url, fallback_html)

                # Try web extraction first (no fallback HTML so we can tell if it really worked).
                if not rendered and is_web_eligible:
                    try:
                        rendered = article_extractor.render_full_article(
                            url,
                            fallback_html=fallback_html if prefer_feed_first else "",
                            fallback_title=fallback_title,
                            fallback_author=fallback_author,
                            prefer_feed_content=prefer_feed_first,
                        )
                        render_source = "feed_preferred" if prefer_feed_first else "web"
                    except Exception as e:
                        err = str(e) or "Unknown error"
                        rendered = None

                # If web extraction failed, try provider-side fetch.
                if not rendered:
                    provider_html = None
                    try:
                        provider_html = self._provider_fetch_full_content(req.get("article_id"), url)
                    except Exception as e:
                        if not err: err = str(e) or "Unknown error"
                    if provider_html:
                        try:
                            rendered = article_extractor.render_full_article(
                                "",
                                fallback_html=provider_html,
                                fallback_title=fallback_title,
                                fallback_author=fallback_author,
                                prefer_feed_content=False,
                            )
                            render_source = "provider"
                        except Exception as e:
                            if not err: err = str(e) or "Unknown error"
                            rendered = None

            if not rendered:
                if is_prefetch and is_web_eligible:
                    # Don't cache feed-content fallback during prefetch; let on-demand loads retry.
                    continue
                # Fallback: show feed content (cleaned) rather than a blank failure message.
                note_lines = []
                if not url:
                    note_lines.append("No webpage URL for this item. Showing feed content.\n\n")
                else:
                    note_lines.append("Full-text extraction failed. Showing feed content.\n\n")
                if err:
                    note_lines.append(err + "\n\n")

                feed_render = None
                try:
                    feed_render = article_extractor.render_full_article(
                        "",
                        fallback_html=fallback_html,
                        fallback_title=fallback_title,
                        fallback_author=fallback_author,
                    )
                except Exception:
                    feed_render = None

                final_text = "".join(note_lines)
                if feed_render:
                    final_text += feed_render
                else:
                    # last resort: strip HTML to visible text
                    try:
                        final_text += (self._strip_html(fallback_html) or "").strip()
                    except Exception:
                        final_text += "No text available.\n"
                rendered = final_text
                render_source = "fallback"

            if is_web_eligible:
                cacheable = render_source in ("web", "provider")
            cache_source = render_source or ("feed" if not is_web_eligible else "unknown")

            # Optional automatic translation (runs inside the background full-text worker).
            try:
                rendered = self._translate_rendered_text_if_enabled(rendered)
            except Exception:
                pass

            if apply_to_ui:
                def apply():
                    # Only apply if selection still matches.
                    if token_snapshot is not None and token_snapshot != int(getattr(self, "_fulltext_token", 0)):
                        return
                    try:
                        idx_now = self.list_ctrl.GetFirstSelected()
                    except Exception:
                        idx_now = -1
                    if idx_now is None or idx_now < 0 or idx_now >= len(self.current_articles):
                        return
                    article_now = self.current_articles[idx_now]
                    cur_key, _cur_url, _aid = self._fulltext_cache_key_for_article(article_now, idx_now)
                    if cur_key != cache_key:
                        return

                    if cacheable:
                        try:
                            self._fulltext_cache[cache_key] = rendered
                            self._fulltext_cache_source[cache_key] = cache_source
                        except Exception:
                            pass
                    else:
                        try:
                            self._fulltext_cache.pop(cache_key, None)
                            self._fulltext_cache_source.pop(cache_key, None)
                        except Exception:
                            pass

                    try:
                        self._fulltext_loading_url = None
                        self.content_ctrl.SetValue(rendered)
                        self.content_ctrl.SetInsertionPoint(0)
                    except Exception:
                        pass

                try:
                    wx.CallAfter(apply)
                except Exception:
                    pass
            else:
                def cache_only():
                    if not self._fulltext_prefetch_enabled():
                        return
                    if prefetch_token is not None and prefetch_token != int(getattr(self, "_fulltext_prefetch_token", 0)):
                        return
                    if not cacheable:
                        return
                    try:
                        self._fulltext_cache[cache_key] = rendered
                        self._fulltext_cache_source[cache_key] = cache_source
                    except Exception:
                        pass

                try:
                    wx.CallAfter(cache_only)
                except Exception:
                    pass


    def _schedule_chapters_load(self, article):
        # Cancel previous debounce timer.
        if getattr(self, "_chapters_debounce", None) is not None:
            try:
                self._chapters_debounce.Stop()
            except Exception:
                pass
            self._chapters_debounce = None

        delay = int(getattr(self, "_chapters_debounce_ms", 500))
        article_cache_id = self._article_cache_id(article)

        self._chapters_debounce = wx.CallLater(delay, self._start_chapters_load, article_cache_id)

    def _start_chapters_load(self, article_cache_id):
        try:
            if hasattr(self, 'selected_article_id') and self.selected_article_id != article_cache_id:
                return
        except Exception:
            pass

        # Find the article object in current list.
        article = None
        try:
            for a in self.current_articles:
                if self._article_cache_id(a) == article_cache_id:
                    article = a
                    break
        except Exception:
            article = None

        if not article:
            return

        try:
            threading.Thread(target=self._load_chapters_thread, args=(article,), daemon=True).start()
        except Exception:
            pass
    def _load_chapters_thread(self, article):
        chapters = getattr(article, "chapters", None)
        if not chapters and hasattr(self.provider, "get_article_chapters"):
            try:
                chapters = self.provider.get_article_chapters(article.id)
            except Exception:
                chapters = None
        
        if chapters:
            wx.CallAfter(self._append_chapters, self._article_cache_id(article), chapters)

    def _append_chapters(self, article_cache_id, chapters):
        # Verify selection hasn't changed
        if hasattr(self, 'selected_article_id') and self.selected_article_id == article_cache_id:
            text = "\n\nChapters:\n"
            for ch in chapters:
                start = ch.get("start", 0)
                mins = int(start // 60)
                secs = int(start % 60)
                start_str = f"{mins:02d}:{secs:02d}"
                title = ch.get("title", "")
                href = ch.get("href", "")
                if href:
                    text += f"- {start_str}  {title} ({href})\n"
                else:
                    text += f"- {start_str}  {title}\n"
            self.content_ctrl.AppendText(text)

    def on_show_player(self, event):
        self.toggle_player_visibility()

    def toggle_player_visibility(self, force_show: bool | None = None):
        """Show/hide the player window.

        force_show:
          - True: show
          - False: hide
          - None: toggle
        """
        pw = self._ensure_player_window()
        if not pw:
            return
        try:
            if force_show is None:
                show = not pw.IsShown()
            else:
                show = bool(force_show)
            if show:
                if hasattr(pw, "show_and_focus"):
                    pw.show_and_focus()
                else:
                    pw.Show()
                    pw.Raise()
            else:
                pw.Hide()
                try:
                    self.list_ctrl.SetFocus()
                except Exception:
                    pass
        except Exception:
            pass

    def show_and_focus_main(self, flash: bool = True):
        """Restore window from tray/minimized state and focus the tree."""
        try:
            if self.IsIconized():
                self.Iconize(False)
            if not self.IsShown():
                self.Show()
            self.Raise()
            if flash:
                try:
                    self.RequestUserAttention(wx.NOTIFY_WINDOW_REQUEST)
                except Exception:
                    pass
            wx.CallAfter(self._focus_default_control)
        except Exception:
            pass

    def _update_feed_unread_count_ui(self, feed_id: str, delta: int) -> None:
        if not feed_id or delta == 0:
            return
        
        # Update feed object
        feed = self.feed_map.get(feed_id)
        if not feed:
            return
        
        try:
            old_count = int(feed.unread_count or 0)
        except Exception:
            old_count = 0
            
        new_count = max(0, old_count + delta)
        feed.unread_count = new_count
        
        # Update tree node
        node = self.feed_nodes.get(feed_id)
        if node and node.IsOk():
            title = feed.title or ""
            label = f"{title} ({new_count})" if new_count > 0 else title
            try:
                self.tree.SetItemText(node, label)
            except Exception:
                pass

    def mark_article_read(self, idx):
        if idx < 0 or idx >= len(self.current_articles):
            return
        article = self.current_articles[idx]
        if not article.is_read:
            threading.Thread(target=self.provider.mark_read, args=(article.id,), daemon=True).start()
            article.is_read = True
            self.list_ctrl.SetItem(idx, 4, "Read")
            self._update_feed_unread_count_ui(article.feed_id, -1)

    def mark_article_unread(self, idx):
        if idx < 0 or idx >= len(self.current_articles):
            return
        article = self.current_articles[idx]
        if article.is_read:
            threading.Thread(target=self.provider.mark_unread, args=(article.id,), daemon=True).start()
            article.is_read = False
            self.list_ctrl.SetItem(idx, 4, "Unread")
            self._update_feed_unread_count_ui(article.feed_id, 1)

    def on_mark_all_read(self, event=None):
        feed_id = getattr(self, "current_feed_id", None)
        if not feed_id:
            return
        try:
            prompt = "Mark all items as read?"
            if wx.MessageBox(prompt, "Mark All as Read", wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
                return
        except Exception:
            pass
        threading.Thread(target=self._mark_all_read_thread, args=(feed_id,), daemon=True).start()

    def _mark_all_read_thread(self, feed_id: str):
        ok = False
        err = ""
        unread_ids: list[str] = []
        used_direct = False
        try:
            provider_mark_all = getattr(self.provider, "mark_all_read", None)
            if callable(provider_mark_all) and self._should_mark_all_view(feed_id):
                try:
                    ok = bool(provider_mark_all(feed_id))
                except Exception:
                    ok = False
                if ok:
                    used_direct = True
                    unread_ids = self._collect_unread_ids_current_view(feed_id)
            if not ok:
                unread_ids = self._collect_unread_ids(feed_id)
                if not unread_ids:
                    ok = True
                else:
                    ok = bool(self.provider.mark_read_batch(unread_ids))
        except Exception as e:
            err = str(e) or "Unknown error"
        wx.CallAfter(self._post_mark_all_read, feed_id, ok, unread_ids, err, used_direct)

    def _is_global_mark_all_view(self, feed_id: str) -> bool:
        if not feed_id:
            return False
        if feed_id == "all":
            return True
        if feed_id.startswith("unread:") and feed_id[7:] == "all":
            return True
        return False

    def _should_mark_all_view(self, feed_id: str) -> bool:
        if not feed_id:
            return False
        if feed_id.startswith(("favorites:", "fav:", "starred:")):
            return False
        if feed_id.startswith("read:"):
            return False
        return True

    def _collect_unread_ids_current_view(self, feed_id: str) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        # Always include currently loaded items for this view so the UI
        # list can be fully marked even if a provider doesn't page all history.
        try:
            if feed_id == getattr(self, "current_feed_id", None):
                for article in (self.current_articles or []):
                    aid = getattr(article, "id", None)
                    if not aid or aid in seen:
                        continue
                    seen.add(aid)
                    if not getattr(article, "is_read", False):
                        ids.append(aid)
        except Exception:
            pass
        return ids

    def _collect_unread_ids(self, feed_id: str) -> list[str]:
        ids = self._collect_unread_ids_current_view(feed_id)
        seen: set[str] = set(ids)
        page_size = 500
        offset = 0
        last_offset = -1
        while True:
            if offset <= last_offset:
                break
            last_offset = offset
            try:
                page, total = self.provider.get_articles_page(feed_id, offset=offset, limit=page_size)
            except Exception:
                break
            page = page or []
            if not page:
                break
            for article in page:
                aid = getattr(article, "id", None)
                if not aid or aid in seen:
                    continue
                seen.add(aid)
                if not getattr(article, "is_read", False):
                    ids.append(aid)
            offset += len(page)
            if total is not None:
                try:
                    if offset >= int(total):
                        break
                except Exception:
                    pass
            if total is None and len(page) < page_size:
                break
        return ids

    def _post_mark_all_read(self, feed_id: str, ok: bool, unread_ids: list[str], err: str = "", used_direct: bool = False):
        if not ok:
            msg = "Failed to mark all items as read."
            if err:
                msg += f"\n\n{err}"
            wx.MessageBox(msg, "Error", wx.ICON_ERROR)
            return

        if not unread_ids and not used_direct:
            try:
                wx.MessageBox("All items are already marked as read.", "Mark All as Read", wx.ICON_INFORMATION)
            except Exception:
                pass
            return

        id_set = set(unread_ids or [])
        try:
            for i, article in enumerate(self.current_articles or []):
                if getattr(article, "id", None) in id_set and not article.is_read:
                    article.is_read = True
                    if not self._is_load_more_row(i):
                        try:
                            self.list_ctrl.SetItem(i, 4, "Read")
                        except Exception:
                            pass
        except Exception:
            pass

        # Clear cached views so filtered lists refresh correctly.
        try:
            with self._view_cache_lock:
                self.view_cache.clear()
        except Exception:
            pass

        try:
            self._begin_articles_load(feed_id, full_load=True, clear_list=True)
        except Exception:
            pass

        try:
            self.refresh_feeds()
        except Exception:
            pass

    def on_article_activate(self, event):
        # Double click or Enter
        idx = event.GetIndex()
        if self._is_load_more_row(idx):
            self._load_more_articles()
            return
        if 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            self.mark_article_read(idx)
            self._open_article(article)

    def _open_article(self, article) -> None:
        if article is None:
            return

        if self._should_play_in_player(article):
            # Decision logic for which URL to play
            media_url = getattr(article, "media_url", None)
            media_type = (getattr(article, "media_type", None) or "").lower()
            use_ytdlp = media_type == "video/youtube"

            is_direct_media = False
            try:
                if media_url:
                    if utils.media_type_is_audio_video_or_podcast(media_type):
                        is_direct_media = True
                    else:
                        media_path = urlsplit(str(media_url)).path.lower()
                        if media_path.endswith(
                            (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac", ".mp4", ".m4v", ".webm", ".mkv", ".mov")
                        ):
                            is_direct_media = True
            except Exception:
                is_direct_media = False

            article_url = str(getattr(article, "url", "") or "").strip()
            if article_url and core.discovery.is_ytdlp_supported(article_url):
                if use_ytdlp or (not media_url) or (not is_direct_media):
                    media_url = article_url
                    use_ytdlp = True
            elif not media_url and article_url:
                media_url = article_url

            if not media_url:
                if article_url:
                    webbrowser.open(article_url)
                return

            chapters = getattr(article, "chapters", None)

            pw = self._ensure_player_window()
            if not pw:
                return

            try:
                if pw.is_current_media(getattr(article, "id", None), media_url):
                    try:
                        if pw.is_audio_playing():
                            pw.pause()
                        else:
                            pw.resume_or_reload_current()
                    except Exception:
                        log.exception("Error toggling play/pause for current article")
                    return
            except Exception:
                log.exception("Error checking if article is currently playing")

            pw.load_media(
                media_url,
                use_ytdlp,
                chapters,
                title=getattr(article, "title", None),
                article_id=getattr(article, "id", None),
            )

            if bool(self.config_manager.get("show_player_on_play", True)):
                self.toggle_player_visibility(force_show=True)
            else:
                self.toggle_player_visibility(force_show=False)

            if not chapters:
                chapter_media_url = getattr(article, "media_url", None)
                chapter_media_type = getattr(article, "media_type", None)
                threading.Thread(
                    target=self._fetch_chapters_for_player,
                    args=(getattr(article, "id", None), chapter_media_url, chapter_media_type),
                    daemon=True,
                ).start()
            return

        article_url = str(getattr(article, "url", "") or "").strip()
        if article_url:
            webbrowser.open(article_url)

    def _fetch_chapters_for_player(self, article_id, media_url: str | None = None, media_type: str | None = None):
        chapters = []
        try:
            if hasattr(self.provider, "get_article_chapters"):
                chapters = self.provider.get_article_chapters(article_id) or []
        except Exception as e:
            print(f"Background chapter fetch (provider) failed: {e}")
            chapters = []

        # Fallback: if the provider doesn't resolve chapters itself, try extracting them directly
        # from the playable audio URL (ID3 CHAP frames / Podcasting 2.0 chapters JSON).
        if not chapters and media_url:
            try:
                chapters = utils.fetch_and_store_chapters(article_id, media_url, media_type) or []
            except Exception as e:
                print(f"Background chapter fetch (media) failed: {e}")

        if chapters:
            try:
                wx.CallAfter(self._apply_chapters_for_player, article_id, chapters)
            except Exception:
                pass

    def _apply_chapters_for_player(self, article_id: str, chapters: list[dict]) -> None:
        try:
            for a in getattr(self, "current_articles", []) or []:
                if getattr(a, "id", None) == article_id:
                    try:
                        a.chapters = chapters
                    except Exception:
                        pass
                    break
        except Exception:
            pass

        try:
            pw = getattr(self, "player_window", None)
            if pw:
                pw.update_chapters(chapters)
        except Exception:
            pass

    def _should_play_in_player(self, article):
        """Only treat bona-fide podcast/media items as playable; everything else opens in browser."""
        
        # 1. Check main URL for yt-dlp compatibility first (high priority)
        # This covers YouTube, Twitch, etc. even if they have thumbnail enclosures.
        if article.url and core.discovery.is_ytdlp_supported(article.url):
            # Safe-reject if the main URL is explicitly an image
            url_low = article.url.lower()
            if any(url_low.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]):
                return False
            return True

        # 2. Check direct media attachments
        if article.media_url:
            media_type = utils.canonical_media_type(article.media_type)
            url = article.media_url.lower()
            audio_exts = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac")
            
            # Reject common image extensions unless yt-dlp explicitly supports them (unlikely for enclosures)
            if any(url.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]):
                if not core.discovery.is_ytdlp_supported(article.media_url):
                    return False

            if utils.media_type_is_audio_video_or_podcast(media_type):
                return True
            if media_type == "video/youtube":
                return True
            if url.endswith(audio_exts):
                return True

        return False

    def on_download_article(self, article):
        if not article or not getattr(article, "media_url", None):
            wx.MessageBox("No downloadable media found for this item.", "Download", wx.ICON_INFORMATION)
            return
        if not self.config_manager.get("downloads_enabled", False):
            wx.MessageBox("Downloads are disabled. Enable them in Settings > Downloads.", "Downloads disabled", wx.ICON_INFORMATION)
            return
        threading.Thread(target=self._download_article_thread, args=(article,), daemon=True).start()

    def _download_article_thread(self, article):
        try:
            url = article.media_url
            resp = utils.safe_requests_get(url, stream=True, timeout=30)
            resp.raise_for_status()

            ext = self._guess_extension(url, resp.headers.get("Content-Type"))
            download_root = self.config_manager.get("download_path", os.path.join(APP_DIR, "podcasts"))
            if not download_root:
                download_root = os.path.join(APP_DIR, "podcasts")

            feed_title = self._get_feed_title(article.feed_id) or "Feed"
            feed_folder = self._safe_name(feed_title)
            target_dir = os.path.join(download_root, feed_folder)
            os.makedirs(target_dir, exist_ok=True)

            base_name = self._safe_name(article.title) or "episode"
            target_path = self._unique_path(os.path.join(target_dir, base_name + ext))

            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self._apply_download_retention(target_dir)
            wx.CallAfter(lambda: wx.MessageBox(f"Downloaded to:\n{target_path}", "Download complete"))
        except Exception as e:
            wx.CallAfter(lambda: wx.MessageBox(f"Download failed: {e}", "Download error", wx.ICON_ERROR))

    def _guess_extension(self, url, content_type=None):
        path = urlsplit(url).path if url else ""
        ext = os.path.splitext(path)[1]
        if ext and len(ext) <= 5:
            return ext

        mapping = {
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/mp4": ".m4a",
            "audio/aac": ".aac",
            "audio/ogg": ".ogg",
            "audio/opus": ".opus",
            "audio/x-wav": ".wav",
            "audio/wav": ".wav",
            "audio/flac": ".flac",
            "audio/x-flac": ".flac",
            "application/flac": ".flac",
            "application/x-flac": ".flac",
        }
        if content_type:
            ctype = utils.canonical_media_type(content_type)
            if ctype in mapping:
                return mapping[ctype]
            for prefix, mapped in mapping.items():
                if ctype.startswith(prefix):
                    return mapped
        return ".mp3"

    def _safe_name(self, text):
        if not text:
            return "untitled"
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", text)
        cleaned = cleaned.strip().rstrip(".")
        return cleaned[:120] or "untitled"

    def _unique_path(self, path):
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        counter = 1
        while True:
            candidate = f"{base}-{counter}{ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _apply_download_retention(self, folder):
        label = self.config_manager.get("download_retention", "Unlimited")
        seconds = self._retention_seconds(label)
        if seconds is None:
            return
        cutoff = time.time() - seconds
        try:
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
        except Exception as e:
            print(f"Retention cleanup failed for {folder}: {e}")

    def _retention_seconds(self, label):
        table = {
            "1 day": 86400,
            "3 days": 3 * 86400,
            "1 week": 7 * 86400,
            "2 weeks": 14 * 86400,
            "3 weeks": 21 * 86400,
            "1 month": 30 * 86400,
            "2 months": 60 * 86400,
            "6 months": 180 * 86400,
            "1 year": 365 * 86400,
            "2 years": 730 * 86400,
            "5 years": 1825 * 86400,
            "Unlimited": None
        }
        return table.get(label, None)

    def _get_feed_title(self, feed_id):
        feed = self.feed_map.get(feed_id) if hasattr(self, "feed_map") else None
        if feed:
            return feed.title
        try:
            feeds = self.provider.get_feeds()
            for f in feeds:
                if f.id == feed_id:
                    return f.title
        except Exception:
            pass
        return None

    def on_add_feed(self, event):
        cats = self.provider.get_categories()
        if not cats: cats = ["Uncategorized"]
        
        dlg = AddFeedDialog(self, cats)
        if dlg.ShowModal() == wx.ID_OK:
            url, cat = dlg.get_data()
            if url:
                self.SetTitle(f"BlindRSS - Adding feed {url}...")
                threading.Thread(target=self._add_feed_thread, args=(url, cat), daemon=True).start()
        dlg.Destroy()
        
    def _add_feed_thread(self, url, cat):
        success = False
        refresh_ran = False
        pre_feed_ids = set()
        try:
            feeds_before = self.provider.get_feeds() if self.provider else []
            for f in (feeds_before or []):
                fid = str(getattr(f, "id", "") or "").strip()
                if fid:
                    pre_feed_ids.add(fid)
        except Exception:
            pre_feed_ids = set()
        try:
            success = self.provider.add_feed(url, cat)
            if success:
                # NOTE: Do NOT call refresh_feeds() here before _run_refresh completes.
                # If the tree updates before articles are fetched, users may click on
                # the new feed and see an empty list. The empty result gets cached
                # with fully_loaded=True, causing the feed to appear permanently empty.
                # _run_refresh() calls refresh_feeds() after articles are fetched.
                try:
                    # Prefer a targeted single-feed refresh so adding one feed does not
                    # block on a full refresh of every feed in the library.
                    refresh_ran = bool(self._refresh_newly_added_feed_after_add(url, pre_feed_ids))
                    if not refresh_ran:
                        # Fallback: force a full refresh so the newly added feed has content immediately.
                        refresh_ran = bool(self._run_refresh(block=True, force=True))
                except Exception:
                    log.exception("Failed to refresh feeds after add")
                    refresh_ran = False
        except Exception:
            log.exception("Error adding feed")
            success = False
            refresh_ran = False
        wx.CallAfter(self._post_add_feed, success, refresh_ran)

    def _refresh_newly_added_feed_after_add(self, requested_url: str, pre_feed_ids: set[str] | None = None) -> bool:
        """Refresh only the newly added feed when the provider supports it."""
        refresh_one = getattr(self.provider, "refresh_feed", None)
        if not callable(refresh_one):
            return False

        before_ids = set(pre_feed_ids or set())
        try:
            feeds_after = list(self.provider.get_feeds() or [])
        except Exception:
            return False

        new_feeds = []
        for feed in feeds_after:
            fid = str(getattr(feed, "id", "") or "").strip()
            if not fid or fid in before_ids:
                continue
            new_feeds.append(feed)
        if not new_feeds:
            # Some providers (e.g., Miniflux) return "already exists" for duplicate adds.
            # In that case there may be no new feed row, but the add should still be treated
            # as success and should not trigger a full refresh fallback.
            add_result = getattr(self.provider, "_last_add_feed_result", None)
            if isinstance(add_result, dict) and bool(add_result.get("duplicate")):
                # The feed is already present; don't trigger another refresh request here.
                # Some providers (e.g., Miniflux) may have flaky targeted refresh endpoints,
                # and a duplicate add should still return quickly as success.
                wx.CallAfter(self.refresh_feeds)
                return True
            return False

        # Prefer the feed whose stored URL matches the requested URL (or its YouTube RSS conversion).
        candidate_urls = set()
        try:
            req = str(requested_url or "").strip()
            if req:
                candidate_urls.add(req)
                yt_feed = core.discovery.get_ytdlp_feed_url(req)
                if yt_feed:
                    candidate_urls.add(str(yt_feed).strip())
        except Exception:
            pass

        selected = None
        if candidate_urls:
            for feed in new_feeds:
                furl = str(getattr(feed, "url", "") or "").strip()
                if furl in candidate_urls:
                    selected = feed
                    break
        if selected is None and len(new_feeds) == 1:
            selected = new_feeds[0]
        if selected is None:
            return False

        feed_id = str(getattr(selected, "id", "") or "").strip()
        if not feed_id:
            return False

        try:
            ok = bool(refresh_one(feed_id))
        except Exception:
            log.exception("Single-feed refresh after add failed for %s", feed_id)
            return False

        if ok:
            wx.CallAfter(self.refresh_feeds)
        return ok

    def _post_add_feed(self, success, refresh_ran: bool = False):
        self.SetTitle("BlindRSS")
        if not refresh_ran:
            # Refresh regardless of success to be safe/consistent
            self.refresh_feeds()
        if not success:
             wx.MessageBox("Failed to add feed.", "Error", wx.ICON_ERROR)

    def on_remove_feed(self, event):
        item = self.tree.GetSelection()
        if item.IsOk():
            data = self.tree.GetItemData(item)
            if data and data["type"] == "feed":
                if wx.MessageBox("Are you sure you want to remove this feed?", "Confirm", wx.YES_NO) == wx.YES:
                    feed_id = data.get("id")
                    feed_title = self._get_feed_title(feed_id) if feed_id else None
                    # Logic to find the "next" best item to focus (alphabetical neighbor)
                    # Try next sibling first, then previous sibling
                    next_item = self.tree.GetNextSibling(item)
                    if not next_item or not next_item.IsOk():
                        next_item = self.tree.GetPrevSibling(item)
                    
                    if next_item and next_item.IsOk():
                        self._selection_hint = self.tree.GetItemData(next_item)
                    else:
                        # Fallback to category if it was the only feed
                        parent = self.tree.GetItemParent(item)
                        if parent.IsOk():
                            self._selection_hint = self.tree.GetItemData(parent)

                    if feed_title:
                        self.SetTitle(f"BlindRSS - Removing feed {feed_title}...")
                    else:
                        self.SetTitle("BlindRSS - Removing feed...")
                    self._start_critical_worker(
                        self._remove_feed_thread,
                        args=(feed_id, feed_title),
                        name="remove_feed",
                    )

    def _remove_feed_thread(self, feed_id: str, feed_title: str | None = None) -> None:
        success = False
        error_message = None
        try:
            success = bool(self.provider.remove_feed(feed_id))
        except Exception as e:
            # The provider is responsible for logging the detailed exception.
            error_message = str(e) or type(e).__name__
        wx.CallAfter(self._post_remove_feed, feed_id, feed_title, success, error_message)

    def _post_remove_feed(self, feed_id: str, feed_title: str | None, success: bool, error_message: str | None = None) -> None:
        self.SetTitle("BlindRSS")

        if not success:
            # Deletion did not happen - don't force-selection to a neighbor.
            self._selection_hint = None
            parts = []
            if feed_title:
                parts.append(f"Could not remove feed '{feed_title}'.")
            else:
                parts.append("Could not remove feed.")

            if error_message:
                low = str(error_message).lower()
                if "locked" in low or "busy" in low:
                    parts.append("It may be busy due to another operation.")
                else:
                    parts.append(f"Error: {error_message}")

            parts.append("Please try again.")
            wx.MessageBox("\n\n".join(parts), "Error", wx.ICON_ERROR)
            return

        # Underlying DB rows changed significantly; drop view caches to avoid stale entries.
        try:
            with self._view_cache_lock:
                self.view_cache.clear()
        except Exception:
            log.exception("Failed to clear view cache after feed removal")

        self.refresh_feeds()

    def on_edit_feed(self, event):
        item = self.tree.GetSelection()
        if not item or not item.IsOk():
            return
        data = self.tree.GetItemData(item)
        if not data or data.get("type") != "feed":
            return
        feed_id = data.get("id")
        feed = self.feed_map.get(feed_id)
        if not feed:
            return

        try:
            if not bool(getattr(self.provider, "supports_feed_edit", lambda: False)()):
                wx.MessageBox("This provider does not support editing feeds.", "Not supported", wx.ICON_INFORMATION)
                return
        except Exception:
            pass

        cats = self.provider.get_categories() if self.provider else []
        if not cats:
            cats = ["Uncategorized"]

        allow_url_edit = False
        try:
            allow_url_edit = bool(getattr(self.provider, "supports_feed_url_update", lambda: False)())
        except Exception:
            allow_url_edit = False

        dlg = FeedPropertiesDialog(self, feed, cats, allow_url_edit=allow_url_edit)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_title, new_url, new_cat = dlg.get_data()
        finally:
            dlg.Destroy()

        old_title = str(getattr(feed, "title", "") or "")
        old_url = str(getattr(feed, "url", "") or "")
        old_cat = str(getattr(feed, "category", "") or "Uncategorized")

        if not new_title:
            new_title = old_title
        if not new_url:
            new_url = old_url
        if not new_cat:
            new_cat = old_cat

        url_changed = (new_url or "") != (old_url or "")
        if url_changed and not allow_url_edit:
            wx.MessageBox(
                "This provider does not support changing the feed URL.\n"
                "The title and category will be updated, but the URL will stay the same.",
                "Feed URL not supported",
                wx.ICON_INFORMATION,
            )
            new_url = old_url

        if new_title == old_title and new_url == old_url and new_cat == old_cat:
            return

        threading.Thread(
            target=self._update_feed_thread,
            args=(feed_id, new_title, new_url, new_cat),
            daemon=True,
        ).start()

    def _update_feed_thread(self, feed_id: str, title: str, url: str, category: str):
        ok = False
        err = None
        try:
            updater = getattr(self.provider, "update_feed", None)
            if callable(updater):
                ok = bool(updater(feed_id, title=title, url=url, category=category))
        except Exception as e:
            err = str(e)
            ok = False
        wx.CallAfter(self._post_update_feed, ok, err)

    def _post_update_feed(self, ok: bool, err: str | None):
        if ok:
            self.refresh_feeds()
            return
        msg = "Could not update feed."
        if err:
            msg = f"{msg}\n\n{err}"
        wx.MessageBox(msg, "Error", wx.ICON_ERROR)

    def on_reset_feed_title(self, event=None, feed_id: str | None = None):
        fid = str(feed_id or "").strip()
        if not fid:
            item = self.tree.GetSelection()
            if item and item.IsOk():
                data = self.tree.GetItemData(item)
                if data and data.get("type") == "feed":
                    fid = str(data.get("id") or "").strip()
        if not fid:
            return

        try:
            if not bool(getattr(self.provider, "supports_feed_title_reset", lambda: False)()):
                wx.MessageBox(
                    "This provider does not support resetting feed titles.",
                    "Not supported",
                    wx.ICON_INFORMATION,
                )
                return
        except Exception:
            return

        threading.Thread(target=self._reset_feed_title_thread, args=(fid,), daemon=True).start()

    def _reset_feed_title_thread(self, feed_id: str):
        ok = False
        err = None
        try:
            resetter = getattr(self.provider, "reset_feed_title", None)
            if callable(resetter):
                ok = bool(resetter(feed_id))
            if ok and callable(getattr(self.provider, "refresh_feed", None)):
                try:
                    self.provider.refresh_feed(feed_id)
                except Exception as refresh_exc:
                    err = str(refresh_exc) or type(refresh_exc).__name__
                    ok = False
        except Exception as e:
            err = str(e) or type(e).__name__
            ok = False
        wx.CallAfter(self._post_reset_feed_title, ok, err)

    def _post_reset_feed_title(self, ok: bool, err: str | None = None):
        if ok:
            self.refresh_feeds()
            return
        msg = "Could not reset feed title."
        if err:
            msg = f"{msg}\n\n{err}"
        wx.MessageBox(msg, "Error", wx.ICON_ERROR)

    def on_import_opml(self, event, target_category=None):
        dlg = wx.FileDialog(self, "Import OPML", wildcard="OPML files (*.opml)|*.opml", style=wx.FD_OPEN)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.SetTitle("BlindRSS - Importing OPML...")
            threading.Thread(target=self._import_opml_thread, args=(path, target_category), daemon=True).start()
        dlg.Destroy()

    def _snapshot_feed_ids(self) -> set[str]:
        try:
            feeds = list(self.provider.get_feeds() or [])
        except Exception:
            return set()
        out = set()
        for feed in feeds:
            fid = str(getattr(feed, "id", "") or "").strip()
            if fid:
                out.add(fid)
        return out

    def _import_opml_thread(self, path, target_category):
        success = False
        new_feed_ids: list[str] = []
        try:
            before_ids = self._snapshot_feed_ids()
            success = bool(self.provider.import_opml(path, target_category))
            after_ids = self._snapshot_feed_ids()
            if success and after_ids:
                new_feed_ids = sorted(fid for fid in after_ids if fid not in before_ids)
        except Exception as e:
            import traceback
            traceback.print_exc()
            log.exception("OPML import failed for path=%s: %s", path, e)
            success = False
            new_feed_ids = []
        wx.CallAfter(self._post_import_opml, success, new_feed_ids)

    def _refresh_imported_feed_ids_thread(self, feed_ids: list[str]) -> None:
        if not feed_ids:
            return
        refresh_many = getattr(self.provider, "refresh_feeds_by_ids", None)
        refresh_one = getattr(self.provider, "refresh_feed", None)
        if not callable(refresh_many) and not callable(refresh_one):
            return

        ordered_ids: list[str] = []
        seen = set()
        for raw_id in feed_ids:
            fid = str(raw_id or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            ordered_ids.append(fid)
        if not ordered_ids:
            return

        acquired = False
        try:
            acquired = self._refresh_guard.acquire(blocking=True)
        except Exception:
            acquired = False
        if not acquired:
            return

        try:
            def progress_cb(state):
                self._on_feed_refresh_progress(state)

            if callable(refresh_many):
                try:
                    refresh_many(ordered_ids, progress_cb=progress_cb, force=True)
                except Exception:
                    log.exception("Failed OPML batch post-import refresh")
                    if callable(refresh_one):
                        for feed_id in ordered_ids:
                            try:
                                refresh_one(feed_id, progress_cb=progress_cb)
                            except Exception:
                                log.exception("Failed OPML post-import refresh for feed %s", feed_id)
            else:
                for feed_id in ordered_ids:
                    try:
                        refresh_one(feed_id, progress_cb=progress_cb)
                    except Exception:
                        log.exception("Failed OPML post-import refresh for feed %s", feed_id)
        finally:
            try:
                self._refresh_guard.release()
            except Exception:
                pass

        wx.CallAfter(self._flush_feed_refresh_progress)
        wx.CallAfter(self.refresh_feeds)

    def _post_import_opml(self, success, new_feed_ids=None):
        self.SetTitle("BlindRSS")
        self.refresh_feeds()
        normalized_new_ids = []
        for raw_id in list(new_feed_ids or []):
            fid = str(raw_id or "").strip()
            if fid:
                normalized_new_ids.append(fid)

        if success and normalized_new_ids:
            refresh_many = getattr(self.provider, "refresh_feeds_by_ids", None)
            refresh_one = getattr(self.provider, "refresh_feed", None)
            if callable(refresh_many) or callable(refresh_one):
                threading.Thread(
                    target=self._refresh_imported_feed_ids_thread,
                    args=(normalized_new_ids,),
                    daemon=True,
                ).start()
            else:
                threading.Thread(target=self._manual_refresh_thread, daemon=True).start()
        if success:
            wx.MessageBox("Import successful.")
        else:
            wx.MessageBox("Import failed. Please check the latest opml_debug_*.log in the temporary directory.")

    def on_export_opml(self, event):
        dlg = wx.FileDialog(self, "Export OPML", wildcard="OPML files (*.opml)|*.opml", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            wx.BeginBusyCursor()
            try:
                if self.provider.export_opml(path):
                    wx.MessageBox("Export successful.")
                else:
                    wx.MessageBox("Export failed.")
            finally:
                wx.EndBusyCursor()
        dlg.Destroy()

    def _normalize_category_title_for_export(self, category_title: str | None) -> str:
        cat = str(category_title or "").strip()
        return cat or "Uncategorized"

    def _collect_category_feeds_for_export(self, category_title: str | None):
        target_cat = self._normalize_category_title_for_export(category_title)
        target_key = target_cat.casefold()
        # Include subcategory feeds
        from core.db import get_subcategory_titles
        sub_cats = get_subcategory_titles(target_cat)
        all_keys = {target_key} | {s.casefold() for s in sub_cats}
        feeds = list((self.provider.get_feeds() if self.provider else []) or [])
        out = []
        for feed in feeds:
            feed_cat = str(getattr(feed, "category", "") or "").strip() or "Uncategorized"
            if feed_cat.casefold() in all_keys:
                out.append(feed)
        return out

    def _export_category_opml_to_path(self, category_title: str | None, path: str):
        target_cat = self._normalize_category_title_for_export(category_title)
        feeds = self._collect_category_feeds_for_export(target_cat)
        if not feeds:
            return False, f'No feeds found in category "{target_cat}".'
        ok = bool(utils.write_opml(feeds, path))
        if ok:
            return True, None
        return False, f'Export failed for category "{target_cat}".'

    def on_export_category_opml(self, event, category_title=None):
        target_cat = self._normalize_category_title_for_export(category_title)
        safe_cat = re.sub(r'[\\/:*?"<>|]+', "_", target_cat).strip().rstrip(".") or "category"
        default_name = f"{safe_cat}.opml"
        dlg = wx.FileDialog(
            self,
            f'Export "{target_cat}" Category OPML',
            wildcard="OPML files (*.opml)|*.opml",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            wx.BeginBusyCursor()
            try:
                ok, err = self._export_category_opml_to_path(target_cat, path)
                if ok:
                    wx.MessageBox("Export successful.")
                else:
                    wx.MessageBox(err or "Export failed.")
            except Exception as e:
                wx.MessageBox(f"Export failed: {e}")
            finally:
                wx.EndBusyCursor()
        dlg.Destroy()

    def on_settings(self, event):
        old_provider = None
        try:
            old_provider = self.config_manager.get("active_provider", "local")
        except Exception:
            old_provider = "local"
        try:
            old_cache_full_text = bool(self.config_manager.get("cache_full_text", False))
        except Exception:
            old_cache_full_text = False
        try:
            old_search_mode = self._normalize_search_mode(self.config_manager.get("search_mode", "title_content"))
        except Exception:
            old_search_mode = "title_content"
        try:
            old_start_on_login = bool(self.config_manager.get("start_on_windows_login", False))
        except Exception:
            old_start_on_login = False
        try:
            old_translation_suffix = self._translation_fulltext_cache_suffix()
        except Exception:
            old_translation_suffix = ""

        notification_feed_entries = self._collect_notification_feed_entries()
        dlg = SettingsDialog(self, self.config_manager.config, notification_feeds=notification_feed_entries)
        if dlg.ShowModal() == wx.ID_OK:
            data = dlg.get_data()

            # Apply settings
            try:
                for k, v in data.items():
                    self.config_manager.set(k, v)
            except Exception:
                pass

            try:
                new_start_on_login = bool(self.config_manager.get("start_on_windows_login", False))
            except Exception:
                new_start_on_login = old_start_on_login
            if new_start_on_login != old_start_on_login:
                ok, msg = self._sync_windows_startup_setting(new_start_on_login)
                if not ok:
                    try:
                        self.config_manager.set("start_on_windows_login", old_start_on_login)
                    except Exception:
                        pass
                    wx.MessageBox(msg or "Could not update startup registration.", "Settings", wx.ICON_WARNING)

            if sys.platform.startswith("win"):
                try:
                    notifications_enabled = bool(self.config_manager.get("windows_notifications_enabled", False))
                except Exception:
                    notifications_enabled = False
                if notifications_enabled:
                    ok, msg = windows_integration.ensure_notification_prerequisites(
                        ensure_start_menu_shortcut=True
                    )
                    if not ok:
                        wx.MessageBox(
                            msg or "Windows notification prerequisites could not be fully configured.",
                            "Notifications",
                            wx.ICON_WARNING,
                        )

            try:
                new_cache_full_text = bool(self.config_manager.get("cache_full_text", False))
            except Exception:
                new_cache_full_text = False
            if new_cache_full_text != old_cache_full_text:
                try:
                    if new_cache_full_text:
                        self._reset_fulltext_prefetch(getattr(self, "current_articles", []) or [])
                    else:
                        self._clear_fulltext_prefetch_queue()
                except Exception:
                    pass

            try:
                new_translation_suffix = self._translation_fulltext_cache_suffix()
            except Exception:
                new_translation_suffix = old_translation_suffix
            if new_translation_suffix != old_translation_suffix:
                try:
                    self._fulltext_cache.clear()
                    self._fulltext_cache_source.clear()
                    self._fulltext_loading_url = None
                except Exception:
                    pass
                try:
                    idx = self.list_ctrl.GetFirstSelected()
                except Exception:
                    idx = -1
                if idx is not None and idx >= 0:
                    try:
                        self._fulltext_token += 1
                        self._schedule_fulltext_load_for_index(int(idx), force=True)
                    except Exception:
                        pass

            try:
                self._search_mode = self._normalize_search_mode(self.config_manager.get("search_mode", "title_content"))
            except Exception:
                self._search_mode = "title_content"
            if self._is_search_active() and self._search_mode != old_search_mode:
                try:
                    self._apply_search_filter()
                except Exception:
                    pass

            # Apply playback speed immediately if the player exists
            if "playback_speed" in data:
                try:
                    pw = getattr(self, "player_window", None)
                    if pw:
                        pw.set_playback_speed(data["playback_speed"])
                except Exception:
                    pass

            if "preferred_soundcard" in data:
                try:
                    pw = getattr(self, "player_window", None)
                    if pw:
                        pw.apply_preferred_soundcard()
                except Exception:
                    pass

            if "range_cache_debug" in data:
                try:
                    from core.range_cache_proxy import get_range_cache_proxy
                    get_range_cache_proxy(debug_logs=bool(data.get("range_cache_debug", False)))
                except Exception:
                    pass

            # If provider credentials/provider selection changed, recreate provider and refresh tree/articles
            try:
                new_provider = self.config_manager.get("active_provider", "local")
            except Exception:
                new_provider = old_provider or "local"

            if new_provider != old_provider or "providers" in data:
                try:
                    from core.factory import get_provider
                    self.provider = get_provider(self.config_manager)
                except Exception as e:
                    try:
                        print(f"Error switching provider: {e}")
                    except Exception:
                        pass
                try:
                    # Clear list/content immediately to avoid stale selection against new provider.
                    self.current_articles = []
                    self._set_base_articles([], None)
                    self.list_ctrl.DeleteAllItems()
                    self.content_ctrl.SetValue("")
                except Exception:
                    pass
                try:
                    self.refresh_feeds()
                except Exception:
                    pass
        dlg.Destroy()

    def on_check_updates(self, event):
        self._start_update_check(manual=True)

    def _maybe_auto_check_updates(self):
        try:
            if not bool(self.config_manager.get("auto_check_updates", True)):
                return
        except Exception:
            return
        wx.CallLater(2500, lambda: self._start_update_check(manual=False))

    def _start_update_check(self, manual: bool):
        if getattr(self, "_update_check_inflight", False):
            return
        self._update_check_inflight = True
        threading.Thread(target=self._update_check_thread, args=(manual,), daemon=True).start()

    def _update_check_thread(self, manual: bool):
        try:
            result = updater.check_for_updates()
        except Exception as e:
            result = updater.UpdateCheckResult("error", f"Update check failed: {e}")
        wx.CallAfter(self._handle_update_check_result, result, manual)

    def _handle_update_check_result(self, result: updater.UpdateCheckResult, manual: bool):
        self._update_check_inflight = False

        if result.status == "error":
            if manual:
                wx.MessageBox(result.message, "Update Check Failed", wx.ICON_ERROR)
            return

        if result.status == "up_to_date":
            if manual:
                wx.MessageBox(result.message, "No Updates", wx.ICON_INFORMATION)
            return

        if result.status != "update_available" or not result.info:
            if manual:
                wx.MessageBox("Unable to determine update status.", "Updates", wx.ICON_ERROR)
            return

        info = result.info
        summary = info.notes_summary or "Release notes are available on GitHub."
        prompt = (
            f"A new version of BlindRSS is available ({info.tag}).\n\n"
            f"{summary}\n\n"
            "Download and install this update now?"
        )
        if wx.MessageBox(prompt, "Update Available", wx.YES_NO | wx.ICON_INFORMATION) == wx.YES:
            self._start_update_install(info)

    def _start_update_install(self, info: updater.UpdateInfo):
        if getattr(self, "_update_install_inflight", False):
            return
        if not updater.is_update_supported():
            wx.MessageBox(
                "Auto-update is only available in the packaged Windows build.\n"
                "Download the latest release from GitHub.",
                "Updates",
                wx.ICON_INFORMATION,
            )
            return
        self._update_install_inflight = True
        wx.BeginBusyCursor()
        threading.Thread(target=self._update_install_thread, args=(info,), daemon=True).start()

    def _update_install_thread(self, info: updater.UpdateInfo):
        debug_mode = False
        try:
            debug_mode = bool(self.config_manager.get("debug_mode", False))
        except Exception:
            pass
        ok, msg = updater.download_and_apply_update(info, debug_mode=debug_mode)
        wx.CallAfter(self._finish_update_install, ok, msg)

    def _finish_update_install(self, ok: bool, msg: str):
        self._update_install_inflight = False
        try:
            wx.EndBusyCursor()
        except Exception:
            pass
        if not ok:
            wx.MessageBox(msg, "Update Failed", wx.ICON_ERROR)
            return
        wx.MessageBox(msg, "Update Ready", wx.ICON_INFORMATION)
        self.real_close()

    def on_exit(self, event):
        self.real_close()

    def add_feed_from_url_prompt(self, url: str) -> None:
        url = str(url or "").strip()
        if not url:
            return

        cats = self.provider.get_categories()
        if not cats:
            cats = ["Uncategorized"]
        cat_dlg = wx.SingleChoiceDialog(self, "Choose category:", "Add Feed", cats)
        cat = "Uncategorized"
        if cat_dlg.ShowModal() == wx.ID_OK:
            cat = cat_dlg.GetStringSelection()
        cat_dlg.Destroy()

        self.SetTitle(f"BlindRSS - Adding feed {url}...")
        threading.Thread(target=self._add_feed_thread, args=(url, cat), daemon=True).start()

    def play_ytdlp_search_result(self, url: str, title: str | None = None) -> None:
        url = str(url or "").strip()
        if not url:
            return

        pw = self._ensure_player_window()
        if not pw:
            return

        pw.load_media(
            url,
            use_ytdlp=True,
            chapters=None,
            title=(str(title or "").strip() or None),
            article_id=None,
        )

        if bool(self.config_manager.get("show_player_on_play", True)):
            self.toggle_player_visibility(force_show=True)
        else:
            self.toggle_player_visibility(force_show=False)

    def on_find_feed(self, event):
        from gui.dialogs import FeedSearchDialog
        dlg = FeedSearchDialog(self)
        url = None
        try:
            if dlg.ShowModal() == wx.ID_OK:
                url = dlg.get_selected_url()
        finally:
            dlg.Destroy()

        if url:
            self.add_feed_from_url_prompt(url)

    def on_ytdlp_global_search(self, event):
        from gui.dialogs import YtdlpGlobalSearchDialog

        dlg = YtdlpGlobalSearchDialog(self)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def real_close(self):
        # Standardize shutdown path
        self.on_close(event=None)
