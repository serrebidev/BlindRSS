# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import wx
import wx.adv
import sys
# import wx.html2 # Removed as per request
import webbrowser
import threading
import time
import os
import re
import html as html_stdlib
import logging
import hashlib
import tempfile
from copy import deepcopy
from types import SimpleNamespace
from collections import OrderedDict, deque
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname
from bs4 import BeautifulSoup
# from dateutil import parser as date_parser  # Removed unused import
from .dialogs import (
    AddFeedDialog,
    AddShortcutsDialog,
    SettingsDialog,
    FeedPropertiesDialog,
    CategoryPropertiesDialog,
    AboutDialog,
    PersistentSearchDialog,
    TakeoutImportSelectionDialog,
)
from .accessibility import AccessibleBrowserFrame, build_accessible_view_entries, voiceover_is_running
from .player import PlayerFrame
from .tray import BlindRSSTrayIcon
from .hotkeys import HoldRepeatHotkeys
from .clipboard_utils import copy_textctrl_selection_to_clipboard, persist_owned_text_clipboard
from providers.base import RSSProvider
from core.config import APP_DIR, _default_download_dir
from core.models import Article
from core import utils
from core import article_columns
from core import article_extractor
from core import media_url as media_url_mod
from core import article_lang
from core import article_html
from core import smart_folders as smart_folders_mod
from core import filters as filters_mod
from core import translation as translation_mod
from core import updater
from core import windows_integration
from core import screen_reader_announce
from core import announcements as announcements_mod
from core.version import APP_VERSION
from core import dependency_check
from core import shortcuts as shortcuts_mod
from core.i18n import _, ngettext
from core.categories import (
    UNCATEGORIZED,
    category_display_name,
    is_uncategorized,
    normalize_category_input,
)
import core.discovery
from .shortcut_keys import event_to_accel
from .menu_mnemonics import apply_menu_mnemonics, apply_menubar_mnemonics
from .widgets import force_ltr_reading
from .reader_performance import (
    LARGE_READER_TEXT_CHARS,
    replace_text_control_value,
    set_accessible_webview_content,
)

log = logging.getLogger(__name__)


def _article_is_youtube_video(article) -> bool:
    try:
        from core import youtube_fulltext

        return youtube_fulltext.is_youtube_video_url(getattr(article, "url", "") or "")
    except Exception:
        return False

# Recovers an http(s) URL from the plain reader text so Enter can open the link
# under the caret. Matches to whitespace (URLs may contain parens, e.g.
# Wikipedia's "_(disambiguation)"); the wrapping paren of the "text (URL)"
# rendering and any trailing sentence punctuation are trimmed by
# _trim_recovered_url.
_CONTENT_URL_RE = re.compile(r'https?://\S+')


def _trim_recovered_url(url: str) -> str:
    """Trim wrapper/sentence punctuation a URL picked up from the reader text.

    A recovered token can carry the closing paren of the "text (URL)" rendering
    and trailing sentence punctuation (e.g. ``...report).``). Terminal
    punctuation is dropped first, then a trailing ``)`` only when it is
    unbalanced — so a URL that legitimately ends in ``)`` (Wikipedia's
    ``Mercury_(element)``) keeps its own paren. ``/`` is always preserved.
    """
    url = str(url or "")
    while url and url[-1] in ".,;:!?\"'>":
        url = url[:-1]
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url

# Default column indices, valid only for the built-in layout. Columns are now
# reorderable/hideable per feed (article list columns), so runtime code MUST resolve an
# index through MainFrame._col(key) instead of using these -- a hidden column has
# no index at all, and a reordered one does not sit where its constant says.
# These remain as the default layout's indices and for tests.
ARTICLE_COL_TITLE = 0
ARTICLE_COL_AUTHOR = 1
ARTICLE_COL_MEDIA = 2
ARTICLE_COL_DATE = 3
ARTICLE_COL_FEED = 4
ARTICLE_COL_DESCRIPTION = 5
ARTICLE_COL_STATUS = 6

# Labels shown in the media column (feature: "does this article contain media?").
# Keep stable English msgids here and translate at display time. MainFrame is
# imported before i18n.setup(), and these values participate in comparisons.
ARTICLE_MEDIA_YES = "Contains audio"
ARTICLE_MEDIA_NO = "No audio"


# Translation anchors -- SmartFolderDialog._FIELDS / ._OPS labels are translated
# at display time, which the AST-based POT extractor cannot follow. Keep in sync
# with those tables.
_RULE_LABEL_POT_ANCHORS = (
    _("(no condition)"),
    _("Title"),
    _("Content"),
    _("Description"),
    _("Author"),
    _("Feed / Publication"),
    _("Link (URL)"),
    _("Tag / Site category"),
    _("Is unread"),
    _("Is read"),
    _("Is favorite"),
    _("Is not favorite"),
    _("Has been opened"),
    _("Has not been opened"),
    _("Was updated since first fetch"),
    _("Was not updated"),
    _("contains"),
    _("does not contain"),
    _("equals"),
    _("starts with"),
)


def should_show_add_shortcuts(platform=None):
    """Whether to offer the "Add Shortcuts..." File-menu item.

    Desktop/Start Menu/Taskbar shortcuts are Windows-only concepts. On macOS the
    equivalent (start at login) lives in Settings, and the dialog is disabled off
    Windows, so the item is dead weight for VoiceOver users there. Linux keeps it
    for parity with the existing behavior.
    """
    plat = sys.platform if platform is None else platform
    return not plat.startswith("darwin")


def provider_configuration_changed(
    old_provider, old_provider_configs, new_provider, new_provider_configs
):
    """Return whether Settings changed provider identity or credentials.

    Settings always returns the providers mapping, so key presence alone
    cannot indicate a change. A no-op save must keep the visible articles.
    """
    return (
        new_provider != old_provider
        or new_provider_configs != old_provider_configs
    )


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
        # Push the article structure-marker toggles into core.utils so both
        # display conversion and full-text extraction honor them.
        utils.apply_article_structure_config(config_manager.get)
        # Stamp the configured browser identity onto utils.HEADERS before any
        # request goes out; every fetch path copies that dict per request.
        try:
            from core import user_agents

            user_agents.apply_to_headers(config_manager.get)
        except Exception:
            log.debug("Could not apply the configured User-Agent", exc_info=True)
        self._start_maximized = start_maximized
        self._start_in_system_tray = bool(config_manager.get("start_in_system_tray", False))
        if self._start_maximized and not self._start_in_system_tray:
            self.Maximize(True)
        self._refresh_guard = threading.Lock()
        # Critical background workers (e.g., destructive DB ops) we may want to wait for during shutdown.
        self._critical_workers_lock = threading.Lock()
        self._critical_workers = set()
        self.feed_map = {}
        self.feed_nodes = {}
        # Aggregated unread counts shown on category tree nodes (issue #34):
        # cat_nodes/category_base_labels mirror feed_nodes for category labels,
        # category_unread_totals is the recursive (direct feeds + nested
        # subcategories) sum kept in sync by the incremental mark-read/unread
        # path, and _category_hierarchy is the {category: parent_category} map
        # needed to walk a feed's ancestor chain without a full tree rebuild.
        self.cat_nodes = {}
        self.category_base_labels = {}
        self.category_unread_totals = {}
        self._category_hierarchy = {}
        # Per-feed image-alt overrides change rarely but are consulted while rendering
        # every settled article selection. Cache the nullable override so arrow-key
        # navigation does not perform a synchronous SQLite read for each article.
        self._feed_show_images_cache = {}
        # A full feed refresh can complete many feeds in parallel.  Keep its
        # progress visible in the tree, but defer the selected article-list
        # reload until the batch has settled: repeatedly rebuilding a 400-row
        # list while the user is trying to navigate it makes the whole app feel
        # unresponsive even though the HTTP work is off-thread.
        self._article_refresh_pending = False
        self._article_refresh_dirty = False
        self._article_refresh_debounce_ms = 250
        self._refresh_ui_batch_active = False
        self._refresh_ui_batch_ending = False
        self._refresh_ui_batch_refresh_tree = False
        self._refresh_ui_batch_end_activity = False
        self._refresh_ui_batch_token = 0
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
        self._load_more_label = _("Load more items (Enter)")
        self._loading_label = _("Loading more...")
        # Chunked article-list rendering keeps the UI thread (and NVDA) responsive
        # on large feeds. The first chunk renders synchronously for immediate
        # content; the rest is appended in bounded wx.CallAfter batches. Bumping
        # _render_generation invalidates any batch still queued from an older render.
        self._render_generation = 0
        # 30 rows fills the visible list area; it is rendered synchronously on
        # view switch, so keep it lean (60 rows measured ~60ms in one dispatch).
        self._render_first_chunk = 30
        # Keep append batches small and yield the event loop between them (see
        # _render_articles_batch): 60-row batches measured up to ~170ms per
        # dispatch during a big-category load, which reads as tree/list lag
        # under a screen reader.
        self._render_batch_size = 24
        self._article_render_inflight = False
        
        # Create player window lazily to keep startup fast.
        self.player_window = None

        # Custom hold-to-repeat for media keys (prevents multi-seek on quick tap)
        self._media_hotkeys = HoldRepeatHotkeys(self, hold_delay_s=2.0, repeat_interval_s=0.12, poll_interval_ms=15)

        # Editable keyboard-shortcut registry (play/pause, stop, queue, speed, ...).
        # accel-string -> command_id is rebuilt whenever bindings change.
        self._current_queue_index = None
        self._shortcut_cmd_map = {}
        self._rebuild_shortcut_map()

        self._updating_list = False # Flag to ignore selection events during background updates
        self._updating_tree = False # Flag to ignore tree selection events during rebuilds
        self._tree_selection_debounce_timer = None
        self._tree_selection_debounce_ms = 120
        self._tree_keyboard_nav_defer_until = 0.0
        self._tree_pending_feed_id = None
        self.selected_article_id = None
        self._update_check_inflight = False
        self._update_install_inflight = False

        # Batch refresh progress updates to avoid flooding the UI thread when many feeds refresh in parallel.
        self._refresh_progress_lock = threading.Lock()
        self._refresh_progress_pending = {}
        self._refresh_progress_flush_scheduled = False

        # Global read-status filter (issues #36/#40): "all", "unread", or "read".
        # Applies to every article view and prunes the category tree to matching
        # branches when not "all". _unread_filter_enabled is a compatibility
        # property over this.
        self._article_read_filter = "all"
        # Screen-reader announcements for key keyboard events (issue #67). The
        # announcer resolves each event's speech/Braille mode from live config,
        # so Settings changes take effect without rebuilding it.
        self.announcer = announcements_mod.Announcer(
            lambda: self.config_manager.get("announcements", {})
        )
        # Client-side media filter (independent of read status): "all", "with"
        # (only articles with playable media), or "without" (only non-media).
        # Applied at display time in _sort_articles_for_display, so it costs
        # nothing when "all" and needs no tree rebuild when changed.
        self._article_media_filter = "all"
        self._is_first_tree_load = True
        # Signatures of the last-applied tree content. A refresh tick that
        # changed nothing (the common case with many feeds) skips the full
        # rebuild entirely, and one that only changed unread counts patches
        # labels in place. Full rebuilds destroy and recreate every node, which
        # stalls the UI thread and yanks screen-reader focus, so with large
        # subscription lists they must only happen on structural changes.
        self._tree_structural_sig = None
        self._tree_counts_sig = None
        # Set by Stop Refresh so the end-of-refresh announcement says
        # "Refresh stopped" instead of "Refresh complete".
        self._refresh_stop_requested = False
        # Category-tree expansion memory (issue #33). The tree is fully rebuilt on
        # every refresh, so we track which category nodes the user explicitly
        # expanded/collapsed (keyed by category id/path) and re-apply that across
        # rebuilds. Categories the user never touched follow the configurable
        # default (category_tree_default_expanded). Both empty on first load, so
        # the whole tree follows the default until the user intervenes.
        self._expanded_categories = set()
        self._collapsed_categories = set()
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
        self._tray_activity_label = ""

        self.init_ui()
        self.init_menus()
        self.init_shortcuts()
        # Show the plain-text or rich reader per the (opt-in) setting. Deferred so
        # the frame is realized before any WebView2 control is created.
        wx.CallAfter(self._apply_reader_mode)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self._load_persistent_searches()
        
        self.tray_icon = BlindRSSTrayIcon(self)
        self._update_tray_status_label()
        
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ICONIZE, self.on_iconize)
        
        # Startup workers are deliberately deferred until the first event-loop
        # turn.  MainFrame is constructed before main.py calls Show(), and
        # starting a 16-worker refresh here can otherwise contend for the GIL
        # while Windows is trying to create/activate the first window.
        self.stop_event = threading.Event()
        self.refresh_thread = None
        self._startup_background_work_started = False
        # Timers do not dispatch until the main loop is running, by which time
        # main.py has shown the frame (or intentionally launched tray-only).
        # A tiny delay lets the show/activation and initial focus events run
        # first without materially delaying the immediate startup refresh.
        wx.CallLater(1, self._start_startup_background_work)
        wx.CallAfter(self._apply_startup_window_state)
        wx.CallAfter(self._focus_default_control)
        wx.CallLater(900, self._maybe_open_accessible_browser_for_voiceover)
        wx.CallLater(15000, self._maybe_auto_check_updates)
        wx.CallLater(4000, self._check_media_dependencies)
        # Later than the app-update check so a slow network cannot make the two
        # compete during the first seconds of a session.
        wx.CallLater(25000, self._maybe_auto_update_translations)

    def _start_startup_background_work(self) -> None:
        """Start initial tree loading and feed refresh after the window gets an
        event-loop turn.

        This remains valid for a tray-only launch: there is no ``IsShown``
        gate, because those launches must still refresh in the background.
        The guard also makes a queued timer harmless if shutdown begins before
        it fires.
        """
        if getattr(self, "_startup_background_work_started", False):
            return
        stop_event = getattr(self, "stop_event", None)
        try:
            if stop_event is not None and stop_event.is_set():
                return
        except Exception:
            return

        self._startup_background_work_started = True
        try:
            self.refresh_thread = threading.Thread(
                target=self.refresh_loop,
                daemon=True,
                name="BlindRSSRefreshLoop",
            )
            self.refresh_thread.start()
            log.info(
                "Refresh loop started refresh_on_startup=%s interval_s=%s provider=%s",
                bool(self.config_manager.get("refresh_on_startup", True)),
                self.config_manager.get("refresh_interval", 300),
                type(self.provider).__name__,
            )
        except Exception:
            # The tree can still load from the local cache even if a worker
            # cannot be created, so do not let this suppress the initial UI.
            log.exception("Failed to start refresh loop")

        try:
            log.info("Scheduling initial feed tree load")
            self.refresh_feeds()
        except Exception:
            log.exception("Failed to schedule initial feed tree load")

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
        """Startup dependency check. The status scan MUST stay off the UI
        thread: it walks PATH/Scoop/Chocolatey/portable layouts and may shell
        out to winget — measured ~0.8s warm and multiple seconds on a cold
        first launch, which froze the UI right when the user started
        navigating (this fires via CallLater 4s after startup)."""
        try:
            if not bool(self.config_manager.get("prompt_missing_dependencies_on_startup", True)):
                return
            threading.Thread(
                target=self._check_media_dependencies_worker,
                daemon=True,
                name="MediaDependencyCheck",
            ).start()
        except Exception as e:
            log.error(f"Dependency check failed: {e}")

    def _check_media_dependencies_worker(self):
        try:
            missing_vlc, missing_ffmpeg, missing_ytdlp = dependency_check.check_media_tools_status()
            if missing_vlc or missing_ffmpeg or missing_ytdlp:
                wx.CallAfter(
                    self._prompt_missing_dependencies, missing_vlc, missing_ffmpeg, missing_ytdlp
                )
        except Exception as e:
            log.error(f"Dependency check failed: {e}")

    def _prompt_missing_dependencies(self, missing_vlc, missing_ffmpeg, missing_ytdlp):
        try:
            if missing_vlc or missing_ffmpeg or missing_ytdlp:
                msg = _("Missing recommended tools:") + "\n"
                if missing_vlc:
                    msg += "- " + _("VLC Media Player (required for playback)") + "\n"
                if missing_ffmpeg:
                    msg += "- " + _("FFmpeg (required for some podcasts)") + "\n"
                if missing_ytdlp:
                    msg += "- " + _("yt-dlp (required for YouTube and many media sources)") + "\n"
                if sys.platform.startswith("win"):
                    msg += "\n" + _(
                        "Would you like to install them automatically (via winget/Ninite) and add them to PATH?"
                        "\n\nTip: You can disable this prompt in Settings > YouTube."
                    )

                    if wx.MessageBox(msg, _("Install Dependencies"), wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        self.SetStatusText(_("Installing dependencies..."))
                        # Run in thread to avoid freezing
                        threading.Thread(
                            target=self._install_dependencies_thread,
                            args=(missing_vlc, missing_ffmpeg, missing_ytdlp),
                            daemon=True,
                        ).start()
                elif sys.platform == "darwin" and dependency_check._has_brew():
                    msg += "\n" + _(
                        "Would you like to install them automatically via Homebrew?"
                        "\n\nTip: You can disable this prompt in Settings > YouTube."
                    )

                    if wx.MessageBox(msg, _("Install Dependencies"), wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        self.SetStatusText(_("Installing dependencies..."))
                        threading.Thread(
                            target=self._install_dependencies_thread,
                            args=(missing_vlc, missing_ffmpeg, missing_ytdlp),
                            daemon=True,
                        ).start()
                else:
                    log_path = dependency_check.get_dependency_log_path()
                    if sys.platform == "darwin":
                        # Homebrew is the macOS auto-install path; without it we can
                        # only point the user at a manual install.
                        msg += "\n\n" + _(
                            "Install Homebrew (https://brew.sh) to let BlindRSS install these "
                            "automatically, or install them yourself with:"
                            "\n    brew install --cask vlc"
                            "\n    brew install ffmpeg yt-dlp"
                            "\n\nIf this is a packaged build that should bundle them, see the log: {log_path}"
                            "\n\nTip: You can disable this prompt in Settings > YouTube."
                        ).format(log_path=log_path)
                    else:
                        msg += "\n\n" + _(
                            "This Linux build should already bundle these tools."
                            "\nIf they still appear missing, see the log: {log_path}"
                            "\n\nTip: You can disable this prompt in Settings > YouTube."
                        ).format(log_path=log_path)
                    wx.MessageBox(msg, _("Missing Dependencies"), wx.OK | wx.ICON_WARNING)
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
                    _("Some dependencies are still missing.\n\nSee log: {log_path}").format(log_path=log_path),
                    _("Install Incomplete"),
                    wx.ICON_WARNING,
                )
            else:
                wx.CallAfter(
                    wx.MessageBox,
                    _("Dependencies installed and PATH updated. A restart is recommended."),
                    _("Success"),
                    wx.ICON_INFORMATION,
                )
        except Exception as e:
            wx.CallAfter(wx.MessageBox, _("Installation failed: {error}").format(error=e), _("Error"), wx.ICON_ERROR)

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
            wx.MessageBox(
                _("Could not add shortcuts:\n{error}").format(error=e),
                _("Shortcuts"),
                wx.ICON_ERROR,
            )
            return

        lines = []
        for key, label in (
            ("desktop", _("Desktop")),
            ("start_menu", _("Start Menu")),
            ("taskbar", _("Taskbar")),
        ):
            if key not in results:
                continue
            ok, message = results.get(key, (False, _("Unknown error")))
            prefix = _("OK") if ok else _("Failed")
            detail = f": {message}" if message else ""
            lines.append(f"{label}: {prefix}{detail}")
        if not lines:
            lines.append(_("No shortcut actions were performed."))

        failed = any(not bool(results.get(k, (True, ""))[0]) for k in results.keys())
        wx.MessageBox("\n".join(lines), _("Shortcuts"), wx.ICON_WARNING if failed else wx.ICON_INFORMATION)

    def init_ui(self):
        # Field 0 keeps the existing user-facing transient messages (filter-match
        # counts, one-off install/translation notices). Field 1 is dedicated to
        # ambient background-activity status (feed refresh / downloads) so it
        # never clobbers field 0 while a screen-reader user is mid-search or
        # mid-read (issue: status bar shows nothing while work is happening).
        # Field 2 is dedicated to live playback status (now-playing title plus
        # elapsed/remaining time) so it never fights the refresh/filter fields.
        self.CreateStatusBar(3)
        self.SetStatusWidths([-2, -1, -1])
        self._playback_status_field = 2
        # Main Splitter: Tree vs Content Area
        splitter = wx.SplitterWindow(self)
        
        # Left: Tree (Feeds)
        self.tree = wx.TreeCtrl(splitter, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS)
        self.tree.SetName(_("Feeds and folders"))
        self.root = self.tree.AddRoot("Root")
        self.all_feeds_node = self.tree.AppendItem(self.root, _("All Feeds"))
        
        # Right: Search + Splitter (List + Content)
        right_panel = wx.Panel(splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.search_ctrl = wx.SearchCtrl(right_panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetName(_("Search articles"))
        try:
            self.search_ctrl.SetDescriptiveText(_("Filter current view (Enter)"))
        except Exception:
            try:
                self.search_ctrl.SetHint(_("Filter current view (Enter)"))
            except Exception:
                pass
        try:
            self.search_ctrl.ShowCancelButton(True)
        except Exception:
            pass
        right_sizer.Add(self.search_ctrl, 0, wx.EXPAND | wx.ALL, 4)

        right_splitter = wx.SplitterWindow(right_panel)
        
        # Top Right: List (Articles)
        # No LC_SINGLE_SEL: allow multiple articles to be selected (e.g. Shift+Up/Down
        # to extend a range) so bulk actions like Delete/Copy work on the whole selection.
        self.list_ctrl = wx.ListCtrl(right_splitter, style=wx.LC_REPORT)
        self.list_ctrl.SetName(_("Articles"))
        # Columns are built from the configured layout rather than hardcoded, so
        # they can be reordered/hidden globally or per feed (article list columns).
        self._column_keys = []
        self._column_index = {}
        self._applied_column_keys = None
        self._apply_column_layout(self._resolve_column_layout(None))
        
        # Bottom Right: Content. A container panel holds the plain-text reader
        # and (created on demand) the rich WebView reader, so the opt-in rich
        # mode can swap in place without disturbing the splitter.
        self.reader_panel = wx.Panel(right_splitter)
        self._reader_sizer = wx.BoxSizer(wx.VERTICAL)
        self.content_ctrl = self._create_article_text_control()
        self._reader_sizer.Add(self.content_ctrl, 1, wx.EXPAND)
        self.reader_panel.SetSizer(self._reader_sizer)
        self._rich_view = None            # AccessibleWebView, created on demand
        self._rich_view_unavailable = False
        self._fulltext_html_cache = {}    # cache_key -> rendered rich HTML
        self._rich_debounce = None

        right_splitter.SplitHorizontally(self.list_ctrl, self.reader_panel, 300)
        right_sizer.Add(right_splitter, 1, wx.EXPAND)
        right_panel.SetSizer(right_sizer)

        splitter.SplitVertically(self.tree, right_panel, 250)
        
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_select, self.tree)
        self.Bind(wx.EVT_CONTEXT_MENU, self.on_tree_context_menu, self.tree)
        self.tree.Bind(wx.EVT_KEY_DOWN, self.on_tree_key_down)
        # Remember manual category expand/collapse so it survives tree rebuilds (issue #33).
        self.Bind(wx.EVT_TREE_ITEM_EXPANDED, self.on_tree_item_expanded, self.tree)
        self.Bind(wx.EVT_TREE_ITEM_COLLAPSED, self.on_tree_item_collapsed, self.tree)
        
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_article_select, self.list_ctrl)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_article_activate, self.list_ctrl)
        self.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu, self.list_ctrl)
        self.list_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_article_list_key_down)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search_enter)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self.on_search_enter)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self.on_search_clear)

        # Full-text extraction cache (url -> rendered text)
        self._fulltext_cache = {}
        self._fulltext_cache_source = {}
        # Last search term used by find-in-article (reading pane).
        self._content_find_term = ""
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
        if not self.IsShown():
            return
        try:
            self.tree.SetFocus()
        except Exception:
            pass

    def _apply_startup_window_state(self):
        if bool(getattr(self, "_start_in_system_tray", False)):
            if self.IsIconized():
                self.Iconize(False)
            self.Hide()
            return
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
        # SetMenu transfers menu ownership to the wx.SearchCtrl: the control
        # frees the previous menu itself when a new one is set.  Only destroy
        # the old menu here if it was never attached (a second free of an
        # attached menu crashes the whole app — the saved-search dialog's OK
        # rebuilds this menu).
        old_menu = getattr(self, "_persistent_search_menu", None)
        old_attached = bool(getattr(self, "_persistent_search_menu_attached", False))
        menu = wx.Menu()
        self._persistent_search_items = {}

        if self._persistent_searches:
            for query in self._persistent_searches:
                item = menu.Append(wx.ID_ANY, query)
                self._persistent_search_items[int(item.GetId())] = query
                self.Bind(wx.EVT_MENU, self.on_persistent_search_select, item)
        else:
            empty_item = menu.Append(wx.ID_ANY, _("(No saved searches)"))
            empty_item.Enable(False)

        menu.AppendSeparator()
        manage_item = menu.Append(wx.ID_ANY, _("Configure Persistent Search..."))
        self.Bind(wx.EVT_MENU, self.on_configure_persistent_search, manage_item)

        attached = False
        try:
            self.search_ctrl.SetMenu(menu)
            attached = True
        except Exception:
            pass
        if old_menu is not None and not old_attached:
            try:
                old_menu.Destroy()
            except Exception:
                pass
        self._persistent_search_menu = menu
        self._persistent_search_menu_attached = attached

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

    def _raw_article_description(self, article) -> str:
        try:
            value = getattr(article, "description", None)
        except Exception:
            value = None
        if value is None:
            try:
                value = getattr(article, "content", "")
            except Exception:
                value = ""
        return str(value or "")

    def _article_description_text(self, article, *, include_images=None) -> str:
        raw = self._raw_article_description(article)
        if not raw:
            return ""
        if include_images is None:
            include_images = self._show_images_for_feed(getattr(article, "feed_id", None))
        try:
            text = self._strip_html(raw, include_images=bool(include_images)).strip()
        except Exception:
            text = raw.strip()
        return re.sub(r"\s+([,.;:!?])", r"\1", text)

    def _article_description_preview(self, article, max_len: int = 240) -> str:
        # Memoize only the default list-rendering path (max_len == 240), which is
        # the hot loop: rendering a large feed calls this once per row and each
        # call runs a full HTML->text parse plus two regex passes. The result is
        # stored on the Article object itself: a feed refresh builds NEW Article
        # objects (article.description/content are never mutated in place), so the
        # cache can never go stale, and it is freed with the article when its
        # cached view is evicted (no unbounded id-keyed dict to manage). Other
        # callers pass a different max_len (e.g. _article_description_for_sort uses
        # 4000) and must NOT receive a 240-char truncation, so they bypass the
        # cache and compute their own length.
        try:
            raw_description = self._raw_article_description(article)
        except Exception:
            try:
                raw_description = getattr(article, "description", None)
                if raw_description is None:
                    raw_description = getattr(article, "content", "")
            except Exception:
                raw_description = ""
            raw_description = str(raw_description or "")

        cache_on_article = (article is not None and max_len == 240)
        lru_key = None
        if cache_on_article:
            cached = getattr(article, "_desc_preview_240", None)
            if cached is not None:
                return cached
            # Second-level cache across Article object generations: every
            # refresh/reload builds NEW Article objects, so during a refresh
            # storm (each completing feed schedules a reload of the selected
            # view) the per-object memo misses every cycle and the loader
            # thread re-parses the whole page (~1.5s CPU per cycle — enough
            # sustained GIL pressure to make the whole app feel frozen right
            # after startup). Keyed by (article id, content hash) so identical
            # content is never parsed twice; bounded LRU so evicted views
            # don't pin memory.
            try:
                lru = self._desc_preview_lru
            except AttributeError:
                lru = self._desc_preview_lru = OrderedDict()
            try:
                lru_key = (self._article_cache_id(article), hash(raw_description))
                cached = lru.get(lru_key)
                if cached is not None:
                    lru.move_to_end(lru_key)
                    try:
                        article._desc_preview_240 = cached
                    except Exception:
                        pass
                    return cached
            except Exception:
                lru_key = None
        try:
            if max_len == 240:
                # A list row can only show a short preview.  Stop parsing once
                # enough visible text exists instead of building a full
                # BeautifulSoup tree for every article on a 400-row page.
                text = utils.html_to_text_preview(
                    raw_description,
                    max_chars=max_len + 64,
                )
            else:
                text = self._article_description_text(article, include_images=False)
        except Exception:
            text = raw_description
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if max_len > 3 and len(text) > max_len:
            result = text[: max_len - 3].rstrip() + "..."
        else:
            result = text
        if cache_on_article:
            try:
                article._desc_preview_240 = result
            except Exception:
                pass
            if lru_key is not None:
                try:
                    lru = self._desc_preview_lru
                    lru[lru_key] = result
                    lru.move_to_end(lru_key)
                    while len(lru) > 4096:
                        lru.popitem(last=False)
                except Exception:
                    pass
        return result

    def _article_description_for_sort(self, article) -> str:
        try:
            return self._article_description_preview(article, max_len=4000).lower()
        except Exception:
            return self._raw_article_description(article).lower()

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

    def _apply_media_filter(self, articles):
        """Drop articles that don't match the active media filter.

        "with" keeps only articles with playable media; "without" keeps only
        those without. Uses the same predicate as the Media column so the list
        and the column always agree. include_downloads=False skips the per-row
        disk lookup (a downloaded item already has a media/ytdlp URL).
        """
        mode = getattr(self, "_article_media_filter", "all")
        if mode not in ("with", "without"):
            return list(articles or [])
        want_media = (mode == "with")
        out = []
        for a in (articles or []):
            try:
                has = bool(self._should_play_in_player(a, include_downloads=False))
            except Exception:
                has = False
            if has == want_media:
                out.append(a)
        return out

    def _read_filter_mode_for_view(self, view_id=None):
        """The read-status filter the given view was fetched with, or None.

        The filter travels in the view id as an "unread:"/"read:" prefix (see
        _wrap_view_id_with_filter), so views the filter deliberately skips
        (Smart Folders, Deleted) are never filtered here either.
        """
        if view_id is None:
            view_id = getattr(self, "current_feed_id", None)
        view_id = str(view_id or "")
        if view_id.startswith("unread:"):
            return "unread"
        if view_id.startswith("read:"):
            return "read"
        return None

    def _apply_read_filter(self, articles, view_id=None):
        """Drop rows whose read status no longer matches the view's filter.

        The provider applies the filter when the page is fetched, but statuses
        change locally afterwards (the user reads an article, Mark All Read
        runs, a cached view is re-shown), so a merged or cached list can still
        hold rows that no longer belong (issue #96). This runs only when the
        list is (re)built -- never on the mark-read path itself -- so a row the
        user just read stays put under their focus until the next refresh,
        reload, or view switch.
        """
        mode = self._read_filter_mode_for_view(view_id)
        if mode is None:
            return list(articles or [])
        want_read = (mode == "read")
        out = []
        for a in (articles or []):
            try:
                is_read = bool(getattr(a, "is_read", False))
            except Exception:
                is_read = False
            if is_read == want_read:
                out.append(a)
        return out

    def _has_stale_read_filter_rows(self, articles=None, view_id=None) -> bool:
        """True when displayed rows no longer match the view's read filter."""
        mode = self._read_filter_mode_for_view(view_id)
        if mode is None:
            return False
        if articles is None:
            articles = getattr(self, "current_articles", None)
        want_read = (mode == "read")
        for a in (articles or []):
            try:
                is_read = bool(getattr(a, "is_read", False))
            except Exception:
                is_read = False
            if is_read != want_read:
                return True
        return False

    def _sort_articles_for_display(self, articles, view_id=None):
        # view_id defaults to the main window's current view; the accessible
        # browser passes its own so its list is filtered by the id it fetched.
        items = self._apply_read_filter(self._apply_media_filter(list(articles or [])), view_id)
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
                parts.append(self._raw_article_description(article))
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

    def _render_articles_list(self, articles, empty_label: str = _("No articles found.")) -> None:
        # Bump the render generation FIRST so any batch still queued from a
        # previous render detects that it is stale and stops (see
        # _render_articles_batch). This also supersedes prior batches when the
        # new render is empty or short (no batches of its own).
        generation = int(getattr(self, "_render_generation", 0)) + 1
        self._render_generation = generation
        feed_id = getattr(self, "current_feed_id", None)

        # Every list render funnels through here, so this is where a view's
        # column layout takes effect (a feed with an override, or back to the
        # global layout when leaving it). It no-ops unless the columns differ.
        self._apply_column_layout(self._resolve_column_layout(feed_id))

        # Refresh the played-media time annotations shown after each title.
        try:
            refresh_fn = getattr(self, "_refresh_playback_states_cache", None)
            if callable(refresh_fn):
                refresh_fn()
        except Exception:
            self._playback_states_cache = {}

        self.list_ctrl.DeleteAllItems()
        articles = list(articles or [])
        if not articles:
            self.list_ctrl.InsertItem(0, empty_label)
            self._article_render_inflight = False
            return

        # Render enough rows synchronously to fill the visible area and give NVDA
        # immediate content, then append the rest in bounded wx.CallAfter batches
        # so a large feed cannot block the UI thread parsing/inserting thousands
        # of rows in one go.
        first_chunk = max(1, int(getattr(self, "_render_first_chunk", 60)))
        first_count = min(len(articles), first_chunk)

        self.list_ctrl.Freeze()
        try:
            for i in range(first_count):
                self._insert_article_row(i, articles[i])
        finally:
            self.list_ctrl.Thaw()

        if first_count < len(articles):
            self._article_render_inflight = True
            # CallLater (not CallAfter): a CallAfter chain runs batch after
            # batch with nothing else dispatched in between, so keyboard/NVDA
            # events queue up behind the whole render. A short timer lets input,
            # paint, and screen-reader events interleave between batches.
            wx.CallLater(self._render_batch_delay_ms(), self._render_articles_batch, articles, first_count, generation, feed_id)
        else:
            self._article_render_inflight = False
            log.debug("Article list rendered rows=%d (single chunk)", len(articles))

    def _render_batch_delay_ms(self) -> int:
        # While a refresh batch is applying progress chunks the UI thread is
        # already contended; a slightly longer gap between render batches gives
        # keyboard/NVDA events real slices instead of back-to-back inserts.
        return 15 if getattr(self, "_refresh_ui_batch_active", False) else 1

    # --- Column layout (article list columns) -------------------------------------------

    def _global_column_layout(self):
        """The configured global layout (normalized; default when unset)."""
        try:
            stored = self.config_manager.get("article_columns", None)
        except Exception:
            stored = None
        if stored is None:
            return article_columns.default_layout()
        return article_columns.normalize_layout(stored)

    def _feed_column_override(self, view_id):
        """Per-feed column override for `view_id`, or None to use the global.

        Only a view that IS a single feed can carry an override: a category or
        "All Articles" view mixes feeds into one header row, so there is no one
        feed whose layout could apply. Those views always use the global layout.
        """
        if not view_id or view_id not in getattr(self, "feed_map", {}):
            return None
        try:
            from core import db as _db
            settings = _db.get_feed_settings(view_id)
        except Exception:
            return None
        return article_columns.feed_layout_from_settings(settings)

    def _resolve_column_layout(self, view_id):
        """Layout for `view_id`: its per-feed override when set, else global."""
        try:
            return article_columns.resolve_layout(
                self._global_column_layout(), self._feed_column_override(view_id)
            )
        except Exception:
            log.debug("Falling back to default column layout", exc_info=True)
            return article_columns.default_layout()

    def _apply_column_layout(self, layout) -> bool:
        """Rebuild the list's columns to match `layout`. Returns True if changed.

        Rebuilding drops every row's cell text, so callers must be about to
        (re)populate the list. No-ops when the visible columns already match,
        which is what keeps this off the hot path of throttled mid-refresh
        reloads.
        """
        keys = article_columns.visible_keys(layout)
        if keys == getattr(self, "_applied_column_keys", None):
            return False
        try:
            self.list_ctrl.DeleteAllItems()
            self.list_ctrl.DeleteAllColumns()
            for index, key in enumerate(keys):
                self.list_ctrl.InsertColumn(
                    index, article_columns.label_for(key), width=article_columns.width_for(key)
                )
        except Exception:
            log.exception("Failed to apply article column layout")
            return False
        self._column_keys = list(keys)
        self._column_index = {key: i for i, key in enumerate(keys)}
        self._applied_column_keys = list(keys)
        return True

    def _col(self, key):
        """Visible index of column `key`, or None when it is hidden."""
        return self._column_index.get(key)

    def _refresh_article_columns(self) -> None:
        """Re-render the list if the current view's column layout changed.

        Called after Settings or Feed Properties is accepted. Re-rendering is
        what rebuilds the columns (see _render_articles_list), so this is a
        no-op unless the visible columns actually differ.
        """
        layout = self._resolve_column_layout(getattr(self, "current_feed_id", None))
        if article_columns.visible_keys(layout) == getattr(self, "_applied_column_keys", None):
            return
        self._render_articles_list(list(getattr(self, "current_articles", []) or []))

    def _set_col(self, row: int, key: str, text: str) -> None:
        """Write a cell by column key, skipping columns the layout hides."""
        index = self._col(key)
        if index is None:
            return
        self.list_ctrl.SetItem(row, index, text)

    def _insert_article_row(self, index: int, article) -> None:
        """Insert one fully-populated article row at `index`.

        Only InsertItem/SetItem are used, so this never changes or steals
        selection/focus (critical for NVDA when appending rows asynchronously).
        """
        idx = self.list_ctrl.InsertItem(index, self._get_display_title(article))
        feed_title = ""
        if article.feed_id:
            feed = self.feed_map.get(article.feed_id)
            if feed:
                feed_title = feed.title or ""

        self._set_col(idx, article_columns.KEY_MEDIA, self._article_media_label(article))
        self._set_col(idx, article_columns.KEY_AUTHOR, article.author or "")
        self._set_col(idx, article_columns.KEY_DATE, utils.humanize_article_date(article.date))
        self._set_col(idx, article_columns.KEY_FEED, feed_title)
        self._set_col(idx, article_columns.KEY_DESCRIPTION, self._article_description_preview(article))
        self._set_col(idx, article_columns.KEY_STATUS, _("Read") if article.is_read else _("Unread"))

    def _render_articles_batch(self, articles, start, generation, feed_id) -> None:
        """Append one bounded batch of article rows, then queue the next batch."""
        # A newer _render_articles_list run has superseded us: stop and leave the
        # inflight flag to whichever render is now current.
        if int(generation) != int(getattr(self, "_render_generation", 0)):
            return
        # The view was switched out from under us via a path that clears the list
        # WITHOUT going through _render_articles_list (e.g. the empty cached-view
        # branch of _select_view, which does not bump the generation). Abandon and
        # clear our inflight flag so any deferred restore can proceed.
        if feed_id != getattr(self, "current_feed_id", None):
            self._article_render_inflight = False
            return

        total = len(articles)
        batch_size = max(1, int(getattr(self, "_render_batch_size", 60)))
        end = min(total, start + batch_size)

        self.list_ctrl.Freeze()
        try:
            for i in range(start, end):
                # Inserting at the growing article index preserves input order and
                # naturally keeps any load-more placeholder (added by the caller
                # right after the first chunk) as the trailing row: the placeholder
                # sits at the "next article" slot and each insert pushes it down.
                try:
                    self._insert_article_row(i, articles[i])
                except Exception:
                    log.exception("Error rendering article row %d", i)
        finally:
            self.list_ctrl.Thaw()

        if end < total:
            # Short timer, not CallAfter — see _render_articles_list: keeps the
            # event loop responsive between append batches.
            wx.CallLater(self._render_batch_delay_ms(), self._render_articles_batch, articles, end, generation, feed_id)
        else:
            self._article_render_inflight = False
            self._reassert_load_more_placeholder_last()
            log.debug("Article list rendered rows=%d (batched)", total)

    def _reassert_load_more_placeholder_last(self) -> None:
        """Ensure a load-more placeholder (if present) is the last row post-render."""
        if not getattr(self, "_loading_more_placeholder", False):
            return
        try:
            count = self.list_ctrl.GetItemCount()
        except Exception:
            return
        if count <= 0:
            return
        labels = (getattr(self, "_load_more_label", ""), getattr(self, "_loading_label", ""))
        try:
            if self.list_ctrl.GetItemText(count - 1) in labels:
                return  # already trailing (the expected case with in-order inserts)
        except Exception:
            return
        # Defensive: the placeholder somehow ended up buried; move it to the end,
        # preserving whether it was the "Loading..." variant.
        placeholder_idx = None
        loading_variant = False
        for idx in range(count):
            try:
                text = self.list_ctrl.GetItemText(idx)
            except Exception:
                continue
            if text in labels:
                placeholder_idx = idx
                loading_variant = (text == getattr(self, "_loading_label", ""))
                break
        if placeholder_idx is None:
            return
        try:
            self.list_ctrl.DeleteItem(placeholder_idx)
        except Exception:
            return
        self._loading_more_placeholder = False
        self._add_loading_more_placeholder(loading=loading_variant)

    def _defer_restore_during_render(self, fn) -> bool:
        """Re-queue `fn` behind pending render batches; return True if deferred.

        Focus/selection/scroll restoration addresses rows by absolute index, so it
        must run only after every row exists. While _render_articles_batch is still
        appending rows (inflight), re-queue the restore so it runs once the list is
        complete instead of acting on a partially rendered list.

        MUST re-queue via wx.CallLater, never wx.CallAfter: the render batches
        advance on wx.CallLater timers, and on wxMSW a CallAfter that re-posts
        itself keeps the posted-event queue permanently non-empty, which starves
        timer dispatch entirely. The result was a livelock — the batch timer
        never fired, _article_render_inflight never cleared, and this restore
        re-posted itself at 100% duty cycle until Windows flagged the app as
        Not Responding (the v1.90.4/5 startup freeze, caught live by py-spy:
        main thread forever inside _restore_list_view -> CallAfter).
        """
        if not getattr(self, "_article_render_inflight", False):
            return False
        try:
            wx.CallLater(15, fn)
        except Exception:
            return False
        return True

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
        empty_label = _("No matches.") if (self._is_search_active() and base_articles) else _("No articles found.")
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
                self._invalidate_reader_text_tracking()
            except Exception:
                pass

        if self._is_search_active():
            try:
                self.SetStatusText(_("Filter: {count} of {total}").format(count=len(self.current_articles), total=len(base_articles)))
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
        empty_label = _("No matches.") if base_articles else _("No articles found.")
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
                self._invalidate_reader_text_tracking()
            except Exception:
                pass

        try:
            self.SetStatusText(_("Filter: {count} of {total}").format(count=len(self.current_articles), total=len(base_articles)))
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
        self._render_articles_list(self.current_articles, empty_label=_("No articles found."))
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
                self._invalidate_reader_text_tracking()
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
                # "Not initialized yet" is normal while the shared libVLC
                # instance warms up in the background; only recreate the
                # window when it was shut down or VLC init actually failed.
                if getattr(pw, "_shutdown_done", False) or bool(getattr(pw, "_vlc_init_failed", False)):
                    try:
                        pw.Destroy()
                    except Exception:
                        pass
                    self.player_window = None
                    pw = None
            except Exception:
                pass
        if pw:
            self._wire_player_callbacks(pw)
            return pw
        try:
            pw = PlayerFrame(self, self.config_manager)
        except Exception:
            log.exception("Failed to create player window")
            return None
        self.player_window = pw
        self._wire_player_callbacks(pw)
        return pw

    def _wire_player_callbacks(self, pw) -> None:
        """Attach progress + queue-advance callbacks to the player window."""
        try:
            pw.playback_progress_listener = self._on_player_progress
        except Exception:
            pass
        try:
            pw.on_playback_finished = self._on_player_playback_finished
        except Exception:
            pass

    def _on_player_progress(self, info: dict) -> None:
        """Reflect live playback state on the main status bar (field 2).

        Runs on the wx main thread (called from the player's timer). Uses
        SetStatusText only, which never moves focus or forces speech, so the
        text is there for NVDA's "read status bar" command without chatter.
        """
        try:
            self._update_live_media_annotation(info)
            field = int(getattr(self, "_playback_status_field", 2))
            if not info or not info.get("has_media"):
                self.SetStatusText("", field)
                return
            title = str(info.get("title") or "").strip() or _("Media")
            state = str(info.get("state") or "").strip()
            pos = int(info.get("position_ms") or 0)
            dur = int(info.get("duration_ms") or 0)
            elapsed = self._format_media_time(pos)
            if dur > 0:
                remaining = self._format_media_time(max(0, dur - pos))
                total = self._format_media_time(dur)
                time_part = _("{elapsed} / {total} ({remaining} left)").format(
                    elapsed=elapsed, total=total, remaining=remaining
                )
            else:
                time_part = elapsed
            verb = state or (_("Playing") if info.get("playing") else _("Paused"))
            self.SetStatusText(f"{verb}: {title} — {time_part}", field)
        except Exception:
            log.debug("Failed to update playback status field", exc_info=True)

    def _update_live_media_annotation(self, info: dict) -> None:
        """Refresh the visible Media cell as soon as the player learns its length."""
        if not info or not info.get("has_media"):
            return
        article_id = info.get("article_id")
        media_url = str(info.get("media_url") or "")
        position_ms = int(info.get("position_ms") or 0)
        duration_ms = int(info.get("duration_ms") or 0)
        if article_id is None and not media_url:
            return

        states = getattr(self, "_playback_states_cache", None)
        if states is None:
            states = {}
            self._playback_states_cache = states

        matching_keys = []
        if article_id is not None:
            matching_keys.append(f"article:{article_id}")
        if media_url:
            matching_keys.append(media_url)
        existing = next((states.get(key) for key in matching_keys if states.get(key) is not None), None)
        completed = bool(getattr(existing, "completed", False)) if existing is not None else False
        state = SimpleNamespace(
            position_ms=position_ms,
            duration_ms=duration_ms or getattr(existing, "duration_ms", None),
            completed=completed,
        )
        for key in matching_keys:
            states[key] = state

        for index, article in enumerate(getattr(self, "current_articles", []) or []):
            same_id = article_id is not None and str(getattr(article, "id", "")) == str(article_id)
            same_url = bool(media_url) and media_url in (
                str(getattr(article, "media_url", "") or ""),
                str(getattr(article, "url", "") or ""),
            )
            if not (same_id or same_url):
                continue
            # The player is playing media for this exact article, so a cached
            # "No audio" label is provably stale (e.g. audio attached after the
            # row was first rendered, as NPR does). Correct it directly instead
            # of recomputing so this stays O(1) on the player-timer path.
            if not bool(getattr(article, "_has_media_cached", True)):
                article._media_label_cached = _(ARTICLE_MEDIA_YES)
                article._has_media_cached = True
            label = self._article_media_label(article)
            # The row may not exist yet: selecting/expanding a category rebuilds
            # the list (DeleteAllItems + a batched re-insert), so current_articles
            # can be longer than the number of rows rendered so far. This method
            # runs on the player's progress timer, so it can land mid-rebuild.
            # Reading or writing an out-of-range index makes wx emit
            # "Couldn't retrieve information about list control item N" via
            # wxLogError, which surfaces as a modal error dialog and CANNOT be
            # caught by the try/except below. Guard the index; the article's
            # cached label was already corrected above, so the pending render
            # paints the right value once the row exists.
            try:
                media_col = self._col(article_columns.KEY_MEDIA)
                if media_col is not None and 0 <= index < self.list_ctrl.GetItemCount():
                    if self.list_ctrl.GetItemText(index, media_col) != label:
                        self.list_ctrl.SetItem(index, media_col, label)
            except Exception:
                pass
            break

    def _on_player_playback_finished(self) -> None:
        """A media item finished naturally: advance the play queue if active."""
        try:
            self._advance_play_queue()
        except Exception:
            log.exception("Error advancing play queue after playback finished")

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
        self._invalidate_reader_text_tracking()
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
            empty_label = _("No matches.") if (self._is_search_active() and base_articles) else _("No articles found.")
            self._render_articles_list(self.current_articles, empty_label=empty_label)
            if self._is_search_active():
                try:
                    self.SetStatusText(_("Filter: {count} of {total}").format(count=len(self.current_articles), total=len(base_articles)))
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
            request_id = self._next_articles_request_id()
            threading.Thread(
                target=self._load_articles_thread,
                args=(feed_id, request_id, False),
                daemon=True,
            ).start()
            return

        # If we have cached empty state, show it immediately and still top-up.
        if st and isinstance(st.get("articles"), list) and not st.get("articles") and st.get("fully_loaded"):
            self._set_base_articles([], feed_id)
            self.current_articles = []
            self.list_ctrl.DeleteAllItems()
            self._remove_loading_more_placeholder()
            self.list_ctrl.InsertItem(0, _("No articles found."))
            try:
                self._reset_fulltext_prefetch([])
            except Exception:
                pass
            request_id = self._next_articles_request_id()
            threading.Thread(
                target=self._load_articles_thread,
                args=(feed_id, request_id, False),
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

    def _strip_html(self, html_content, include_images=None):
        if not html_content:
            return ""
        if include_images is None:
            include_images = self._images_enabled_global()
        try:
            # Blank lines between paragraphs are extra stops for a screen
            # reader and the full-text pane no longer has them, so the feed
            # content this shows before (and instead of) an extraction must
            # read the same way: one paragraph per line.
            return utils.collapse_blank_lines(
                utils.html_to_text(html_content, include_images=bool(include_images))
            )
        except Exception:
            return html_content

    def _images_enabled_global(self) -> bool:
        try:
            return bool(self.config_manager.get("show_image_alt", False))
        except Exception:
            return False

    def _show_images_for_feed(self, feed_id) -> bool:
        """Resolve image-alt display for a feed: per-feed override wins, else global."""
        if feed_id:
            cache = getattr(self, "_feed_show_images_cache", None)
            if cache is None:
                cache = {}
                self._feed_show_images_cache = cache
            try:
                if feed_id in cache:
                    override = cache[feed_id]
                else:
                    from core.db import get_feed_show_images
                    override = get_feed_show_images(feed_id)
                    cache[feed_id] = override
                if override is not None:
                    return bool(override)
            except Exception:
                pass
        return self._images_enabled_global()

    def _append_shortcut_menu_item(
        self, menu, command_id, base_label, help_text="", *, kind="normal", item_id=None
    ):
        """Append a menu item whose label carries its registry shortcut.

        The binding is rendered as a "(Ctrl+X)" text suffix, not a native
        '\\t' accelerator: registry shortcuts dispatch from the global
        char-hook (so they also work from the player window and can announce
        themselves), and a native accelerator would double-fire the handler.
        `self._shortcut_menu_items` lets reload_shortcuts() re-render each
        label after the user edits a binding.
        """
        label = self._shortcut_menu_label(base_label, command_id)
        wxid = wx.ID_ANY if item_id is None else item_id
        if kind == "check":
            item = menu.AppendCheckItem(wxid, label, help_text)
        elif kind == "radio":
            item = menu.AppendRadioItem(wxid, label, help_text)
        else:
            item = menu.Append(wxid, label, help_text)
        self._shortcut_menu_items.setdefault(command_id, []).append((item, base_label))
        return item

    def init_menus(self):
        menubar = wx.MenuBar()
        self._shortcut_menu_items = {}

        file_menu = wx.Menu()
        add_feed_item = self._append_shortcut_menu_item(
            file_menu, "feeds.add", _("&Add Feed"), _("Add a new RSS feed"))
        open_media_url_item = self._append_shortcut_menu_item(
            file_menu, "media.open_url", _("Open Media &URL..."),
            _("Stream or download media from any supported link"))
        detect_feeds_item = self._append_shortcut_menu_item(
            file_menu, "feeds.detect_page", _("Detect Feeds on &Page..."),
            _("Scan a webpage for RSS, Atom, or JSON feed links"))
        remove_feed_item = self._append_shortcut_menu_item(
            file_menu, "feeds.remove", _("&Remove Feed"), _("Remove selected feed"))
        refresh_item = self._append_shortcut_menu_item(
            file_menu, "feeds.refresh_all", _("&Refresh Feeds"), _("Refresh all feeds"),
            item_id=wx.ID_REFRESH)
        stop_refresh_item = self._append_shortcut_menu_item(
            file_menu, "feeds.stop_refresh", _("S&top Refresh"),
            _("Stop the feed refresh currently in progress"))
        mark_all_read_item = self._append_shortcut_menu_item(
            file_menu, "feeds.mark_all_read", _("Mark All Items as &Read"),
            _("Mark all items in all feeds as read"))
        view_errors_item = self._append_shortcut_menu_item(
            file_menu, "feeds.view_errors", _("View Feed &Errors..."),
            _("View feeds that failed to update"))
        file_menu.AppendSeparator()
        add_cat_item = self._append_shortcut_menu_item(
            file_menu, "feeds.add_category", _("Add &Category"), _("Add a new category"))
        remove_cat_item = self._append_shortcut_menu_item(
            file_menu, "feeds.remove_category", _("Remove C&ategory"), _("Remove selected category"))
        file_menu.AppendSeparator()
        import_opml_item = self._append_shortcut_menu_item(
            file_menu, "feeds.import_opml", _("&Import OPML..."), _("Import feeds from OPML"))
        import_youtube_takeout_item = self._append_shortcut_menu_item(
            file_menu, "feeds.import_youtube_takeout", _("Import &YouTube Takeout..."),
            _("Import YouTube subscriptions, playlists, channels, and watch-history channels"))
        export_opml_item = self._append_shortcut_menu_item(
            file_menu, "feeds.export_opml", _("E&xport OPML..."), _("Export feeds to OPML"))
        file_menu.AppendSeparator()
        persistent_search_item = self._append_shortcut_menu_item(
            file_menu, "tools.persistent_search", _("Configure &Persistent Search..."),
            _("Configure saved search queries"))
        # Desktop/Start Menu/Taskbar shortcuts are Windows-only; hide the dead item on macOS.
        add_shortcuts_item = None
        if should_show_add_shortcuts():
            add_shortcuts_item = file_menu.Append(wx.ID_ANY, _("Add &Shortcuts..."), _("Create desktop, taskbar, or Start Menu shortcuts"))
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, _("E&xit"), _("Exit application"))

        # Standard Edit menu. The standard IDs route to the focused text control
        # automatically (no custom handlers needed), giving the article reader pane
        # and other text fields native Cut/Copy/Paste/Select All. wx maps Ctrl->Cmd
        # on macOS, where VoiceOver relies on these shortcuts existing.
        edit_menu = wx.Menu()
        edit_menu.Append(wx.ID_CUT, _("Cu&t") + "\tCtrl+X", _("Cut the selection"))
        edit_menu.Append(wx.ID_COPY, _("&Copy") + "\tCtrl+C", _("Copy the selection"))
        edit_menu.Append(wx.ID_PASTE, _("&Paste") + "\tCtrl+V", _("Paste from the clipboard"))
        edit_menu.Append(wx.ID_SELECTALL, _("Select &All") + "\tCtrl+A", _("Select all"))

        view_menu = wx.Menu()
        show_search_item = self._append_shortcut_menu_item(
            view_menu, "view.toggle_search", _("Show &Search Field"),
            _("Show or hide the search field"), kind="check")
        show_search_item.Check(bool(getattr(self, "_search_visible", True)))
        self._show_search_item = show_search_item
        # Reader-surface toggle: checked = rich HTML view, unchecked = plain
        # full-text reader. Mirrors the Settings option so it can be flipped
        # quickly while reading (also editable in Settings).
        rich_view_item = self._append_shortcut_menu_item(
            view_menu, "view.rich_view", _("&Rich Full-Text View"),
            _("Switch the reader between plain full text and the rich HTML view"),
            kind="check")
        rich_view_item.Check(self._rich_view_enabled())
        self._rich_view_menu_item = rich_view_item
        self.Bind(wx.EVT_MENU, self.on_toggle_rich_view, rich_view_item)
        # Global read-status filter (issues #36/#40): lives here rather than in
        # the feed/category context menu because it applies to every view. When
        # not "All", the category tree hides branches with no matching articles.
        # Issue #60: the Ctrl+1..Ctrl+6 defaults live in the shortcut registry
        # (filter.*) and are shown in each label's "(...)" suffix.
        filter_menu = wx.Menu()
        self._article_filter_menu_items = {}
        for mode, command_id, label, help_text in (
            ("all", "filter.read_all", _("&All Articles"), _("Show read and unread articles in all views")),
            ("unread", "filter.read_unread", _("&Unread Only"), _("Show only unread articles in all views")),
            ("read", "filter.read_read", _("&Read Only"), _("Show only read articles in all views")),
        ):
            item = self._append_shortcut_menu_item(
                filter_menu, command_id, label, help_text, kind="radio")
            self._article_filter_menu_items[mode] = item
            if mode == getattr(self, "_article_read_filter", "all"):
                item.Check(True)
            self.Bind(wx.EVT_MENU, lambda e, m=mode: self.on_change_article_filter(m), item)
        # Second, independent radio group: filter by whether an article has
        # playable media. The separator breaks the wx radio group so this set is
        # tracked separately from the read-status set above.
        filter_menu.AppendSeparator()
        self._article_media_filter_menu_items = {}
        for mode, command_id, label, help_text in (
            ("all", "filter.media_all", _("Media and &Non-media"), _("Show articles whether or not they have media")),
            ("with", "filter.media_with", _("With &Media Only"), _("Show only articles that have playable media")),
            ("without", "filter.media_without", _("Wit&hout Media Only"), _("Show only articles that have no playable media")),
        ):
            item = self._append_shortcut_menu_item(
                filter_menu, command_id, label, help_text, kind="radio")
            self._article_media_filter_menu_items[mode] = item
            if mode == getattr(self, "_article_media_filter", "all"):
                item.Check(True)
            self.Bind(wx.EVT_MENU, lambda e, m=mode: self.on_change_media_filter(m), item)
        view_menu.AppendSubMenu(filter_menu, _("Article &Filter"), _("Filter all views by read status and media"))
        accessible_browser_item = self._append_shortcut_menu_item(
            view_menu, "view.accessible_browser", _("Open &Accessible Browser"),
            _("Open the VoiceOver-friendly browser window"))
        player_item = self._append_shortcut_menu_item(
            view_menu, "player.show_hide", _("Show/Hide &Player"),
            _("Show or hide the media player window"))
        view_menu.AppendSeparator()

        sort_menu = wx.Menu()
        self._sort_by_menu_items = {}
        self._sort_by_items_by_key = {}
        sort_choices = [
            ("date", "sort.date", _("&Date"), _("Sort articles by date")),
            ("name", "sort.name", _("&Name"), _("Sort articles by name")),
            ("author", "sort.author", _("A&uthor"), _("Sort articles by author")),
            ("description", "sort.description", _("De&scription"), _("Sort articles by description")),
            ("feed", "sort.feed", _("&Feed"), _("Sort articles by feed")),
            ("status", "sort.status", _("S&tatus"), _("Sort articles by status")),
        ]
        for key, command_id, label, sort_help in sort_choices:
            item = self._append_shortcut_menu_item(
                sort_menu, command_id, label, sort_help, kind="radio")
            self._sort_by_menu_items[int(item.GetId())] = key
            self._sort_by_items_by_key[key] = item
            if key == getattr(self, "_article_sort_by", "date"):
                item.Check(True)
            self.Bind(wx.EVT_MENU, self.on_change_sort_by, item)

        sort_menu.AppendSeparator()
        self._sort_ascending_item = self._append_shortcut_menu_item(
            sort_menu, "sort.ascending", _("&Ascending"),
            _("Sort in ascending order (default is descending by date)"),
            kind="check")
        self._sort_ascending_item.Check(bool(getattr(self, "_article_sort_ascending", False)))
        self.Bind(wx.EVT_MENU, self.on_toggle_sort_direction, self._sort_ascending_item)
        view_menu.AppendSubMenu(sort_menu, _("Sort &By"))

        # Player menu (media controls)
        # NOTE: shortcuts are shown in the label text only (not as '\t' menu
        # accelerators) because the registry-managed shortcuts are handled in the
        # global char-hook so they also work when the player window is focused.
        player_menu = wx.Menu()
        player_toggle_item = self._append_shortcut_menu_item(
            player_menu, "player.show_hide", _("Show/Hide Player"),
            _("Show or hide the media player window"),
        )
        player_menu.AppendSeparator()
        player_play_pause_item = self._append_shortcut_menu_item(
            player_menu, "player.play_pause", _("Play/Pause"), _("Toggle play/pause"),
        )
        player_stop_item = self._append_shortcut_menu_item(
            player_menu, "player.stop", _("Stop"), _("Stop playback"),
        )
        player_menu.AppendSeparator()
        player_queue_item = self._append_shortcut_menu_item(
            player_menu, "queue.open", _("Play &Queue..."),
            _("View and manage the media play queue"),
        )
        player_queue_next_item = self._append_shortcut_menu_item(
            player_menu, "queue.next", _("Play Next in Queue"),
            _("Play the next item in the play queue"),
        )
        player_queue_prev_item = self._append_shortcut_menu_item(
            player_menu, "queue.prev", _("Play Previous in Queue"),
            _("Play the previous item in the play queue"),
        )
        player_menu.AppendSeparator()
        # Playback speed submenu (feature: speed menu + shortcuts).
        speed_submenu = wx.Menu()
        speed_up_item = self._append_shortcut_menu_item(
            speed_submenu, "speed.up", _("Increase Speed"), _("Play faster"),
        )
        speed_down_item = self._append_shortcut_menu_item(
            speed_submenu, "speed.down", _("Decrease Speed"), _("Play slower"),
        )
        speed_reset_item = self._append_shortcut_menu_item(
            speed_submenu, "speed.reset", _("Normal Speed (1x)"), _("Reset to normal speed"),
        )
        # These action items were never bound, so choosing Increase/Decrease/
        # Normal Speed from the menu did nothing (the radio items below WERE
        # bound). Bind them to the same handlers the keyboard shortcuts use.
        self.Bind(wx.EVT_MENU, self.on_player_speed_up, speed_up_item)
        self.Bind(wx.EVT_MENU, self.on_player_speed_down, speed_down_item)
        self.Bind(wx.EVT_MENU, self.on_player_speed_reset, speed_reset_item)
        speed_submenu.AppendSeparator()
        self._speed_menu_items = {}
        for s in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
            it = speed_submenu.AppendRadioItem(wx.ID_ANY, _("{speed}x").format(speed=("%g" % s)))
            self._speed_menu_items[float(s)] = it
            self.Bind(wx.EVT_MENU, lambda e, sp=float(s): self._apply_playback_speed(sp), it)
        self._speed_submenu = speed_submenu
        player_menu.AppendSubMenu(speed_submenu, _("Playback &Speed"))
        # Equalizer (feature: equalizer).
        player_equalizer_item = self._append_shortcut_menu_item(
            player_menu, "player.equalizer", _("&Equalizer..."),
            _("Adjust the audio equalizer"),
        )
        player_menu.AppendSeparator()
        # NOTE: Do not use '\tCtrl+...' menu accelerators here.
        # We implement Ctrl+Arrow globally via an event filter + hold-to-repeat gate.
        # Leaving these as accelerators causes double-seeks (EVT_MENU + key handlers).
        player_rewind_item = player_menu.Append(wx.ID_ANY, _("Rewind (Ctrl+Left)"), _("Rewind"))
        player_forward_item = player_menu.Append(wx.ID_ANY, _("Fast Forward (Ctrl+Right)"), _("Fast forward"))
        player_menu.AppendSeparator()
        player_vol_up_item = player_menu.Append(wx.ID_ANY, _("Volume Up (Ctrl+Up)"), _("Increase volume"))
        player_vol_down_item = player_menu.Append(wx.ID_ANY, _("Volume Down (Ctrl+Down)"), _("Decrease volume"))
        player_menu.AppendSeparator()
        chapters_submenu = wx.Menu()
        player_menu.AppendSubMenu(chapters_submenu, _("Chapters"))

        self._player_menu = player_menu
        self._player_chapters_submenu = chapters_submenu
        self._player_chapter_dynamic_item_ids = []
        self._player_chapter_static_item_ids = []
        self._player_chapters_show_item = None
        self._player_chapters_prev_item = None
        self._player_chapters_next_item = None
        
        tools_menu = wx.Menu()
        find_feed_item = self._append_shortcut_menu_item(
            tools_menu, "feeds.find_podcast", _("Find a &Podcast or RSS Feed..."),
            _("Find and add a podcast or RSS feed"),
        )
        ytdlp_global_search_item = self._append_shortcut_menu_item(
            tools_menu, "feeds.video_search", _("&Video Search..."),
            _("Search all yt-dlp query-search sites"),
        )
        tools_menu.AppendSeparator()
        filter_rules_item = self._append_shortcut_menu_item(
            tools_menu, "tools.filter_rules", _("Filter &Rules..."),
            _("Create rules that categorize, label, or delete articles as they arrive"),
        )
        import_site_cookies_item = self._append_shortcut_menu_item(
            tools_menu, "tools.import_site_cookies", _("Import Site &Cookies..."),
            _("Import browser cookies so challenge-protected sites can be read"),
        )
        tools_menu.AppendSeparator()
        keyboard_shortcuts_item = self._append_shortcut_menu_item(
            tools_menu, "tools.keyboard_shortcuts", _("&Keyboard Shortcuts..."),
            _("View and customize keyboard shortcuts"),
        )
        settings_item = self._append_shortcut_menu_item(
            tools_menu, "tools.settings", _("&Settings..."), _("Configure application"),
            item_id=wx.ID_PREFERENCES,
        )

        help_menu = wx.Menu()
        check_updates_item = self._append_shortcut_menu_item(
            help_menu, "tools.check_updates", _("Check for &Updates..."),
            _("Check for new versions"),
        )
        about_item = help_menu.Append(wx.ID_ABOUT, _("&About"), _("About BlindRSS"))

        menubar.Append(file_menu, _("&File"))
        menubar.Append(edit_menu, _("&Edit"))
        menubar.Append(view_menu, _("&View"))
        menubar.Append(player_menu, _("&Player"))
        menubar.Append(tools_menu, _("&Tools"))
        menubar.Append(help_menu, _("&Help"))
        self.SetMenuBar(menubar)
        # Every menu item gets an access key, in every locale (task: menu
        # mnemonics). Runs after the bar is fully built so per-menu uniqueness
        # sees the final item set.
        apply_menubar_mnemonics(menubar)
        
        self.Bind(wx.EVT_MENU, self.on_add_feed, add_feed_item)
        self.Bind(wx.EVT_MENU, self.on_open_media_url, open_media_url_item)
        self.Bind(wx.EVT_MENU, self.on_detect_page_feeds, detect_feeds_item)
        self.Bind(wx.EVT_MENU, self.on_remove_feed, remove_feed_item)
        self.Bind(wx.EVT_MENU, self.on_refresh_feeds, refresh_item)
        self.Bind(wx.EVT_MENU, self.on_stop_refresh, stop_refresh_item)
        # Only one of Refresh Feeds / Stop Refresh is ever actionable, so grey
        # out the other one (this also disables its F5 / Shift+F5 accelerator).
        self.Bind(wx.EVT_UPDATE_UI, self.on_update_refresh_feeds_ui, refresh_item)
        self.Bind(wx.EVT_UPDATE_UI, self.on_update_stop_refresh_ui, stop_refresh_item)
        self.Bind(wx.EVT_MENU, self.on_mark_all_read, mark_all_read_item)
        self.Bind(wx.EVT_MENU, self.on_view_feed_errors, view_errors_item)
        self.Bind(wx.EVT_MENU, self.on_add_category, add_cat_item)
        self.Bind(wx.EVT_MENU, self.on_remove_category, remove_cat_item)
        self.Bind(wx.EVT_MENU, self.on_import_opml, import_opml_item)
        self.Bind(wx.EVT_MENU, self.on_import_youtube_takeout, import_youtube_takeout_item)
        self.Bind(wx.EVT_MENU, self.on_export_opml, export_opml_item)
        self.Bind(wx.EVT_MENU, self.on_configure_persistent_search, persistent_search_item)
        if add_shortcuts_item is not None:
            self.Bind(wx.EVT_MENU, self.on_add_shortcuts, add_shortcuts_item)
        self.Bind(wx.EVT_MENU, self.on_toggle_search_field, show_search_item)
        self.Bind(wx.EVT_MENU, self.on_open_accessible_browser, accessible_browser_item)
        self.Bind(wx.EVT_MENU, self.on_show_player, player_item)
        self.Bind(wx.EVT_MENU, self.on_show_player, player_toggle_item)
        self.Bind(wx.EVT_MENU, self.on_player_play_pause, player_play_pause_item)
        self.Bind(wx.EVT_MENU, self.on_player_stop, player_stop_item)
        self.Bind(wx.EVT_MENU, self.on_open_play_queue, player_queue_item)
        self.Bind(wx.EVT_MENU, self.on_play_queue_next, player_queue_next_item)
        self.Bind(wx.EVT_MENU, self.on_play_queue_prev, player_queue_prev_item)
        self.Bind(wx.EVT_MENU, self.on_open_equalizer, player_equalizer_item)
        self.Bind(wx.EVT_MENU, self.on_player_rewind, player_rewind_item)
        self.Bind(wx.EVT_MENU, self.on_player_forward, player_forward_item)
        self.Bind(wx.EVT_MENU, self.on_player_volume_up, player_vol_up_item)
        self.Bind(wx.EVT_MENU, self.on_player_volume_down, player_vol_down_item)
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_check_updates, check_updates_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        self.Bind(wx.EVT_MENU, self.on_find_feed, find_feed_item)
        self.Bind(wx.EVT_MENU, self.on_ytdlp_global_search, ytdlp_global_search_item)
        self.Bind(wx.EVT_MENU, self.on_manage_filter_rules, filter_rules_item)
        self.Bind(wx.EVT_MENU, self.on_import_site_cookies, import_site_cookies_item)
        self.Bind(wx.EVT_MENU, self.on_open_keyboard_shortcuts, keyboard_shortcuts_item)
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        self.Bind(wx.EVT_MENU_OPEN, self.on_menu_open)
        self._refresh_player_chapters_submenu()

    def init_shortcuts(self):
        # F5, Ctrl+F5, Ctrl+D, Ctrl+1..6 etc. are registry-managed now
        # (editable in Tools > Keyboard Shortcuts, dispatched from the global
        # char-hook). Only the legacy Ctrl+R refresh alias stays native — it is
        # not in the registry, so rebinding Refresh Feeds never orphans it.
        self._toggle_favorite_id = wx.NewIdRef()
        entries = [
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('R'), wx.ID_REFRESH),
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

    def _window_is_or_child(self, focus, window) -> bool:
        if focus is None or window is None:
            return False
        if focus == window:
            return True
        try:
            parent = focus.GetParent()
            while parent:
                if parent == window:
                    return True
                parent = parent.GetParent()
        except Exception:
            pass
        return False

    def _is_delete_key(self, key) -> bool:
        delete_keys = {
            getattr(wx, "WXK_DELETE", None),
            getattr(wx, "WXK_NUMPAD_DELETE", None),
            getattr(wx, "WXK_NUMPAD_DECIMAL", None),
        }
        delete_keys.discard(None)
        return key in delete_keys

    def _is_backspace_key(self, key) -> bool:
        return key == getattr(wx, "WXK_BACK", 8)

    def _is_plain_backspace_event(self, event: wx.KeyEvent, key) -> bool:
        if not MainFrame._is_backspace_key(self, key):
            return False
        try:
            return not (
                event.ControlDown()
                or event.ShiftDown()
                or event.AltDown()
                or event.MetaDown()
            )
        except Exception:
            return True

    def _is_shift_delete_event(self, event: wx.KeyEvent, key) -> bool:
        if not MainFrame._is_delete_key(self, key):
            return False
        try:
            return bool(event.ShiftDown()) and not (
                event.ControlDown()
                or event.AltDown()
                or event.MetaDown()
            )
        except Exception:
            return False

    def _is_rich_view_focused(self, focus) -> bool:
        """True when focus is inside the rich (WebView) reader surface.

        The WebView is a reading surface like the plain-text reader, so app-level
        Ctrl+arrow media shortcuts must not hijack it — the keys belong to the
        document (paragraph navigation, caret movement) and the screen reader.
        """
        rv = getattr(self, "_rich_view", None)
        if rv is None:
            return False
        try:
            return self._window_is_or_child(focus, rv.control)
        except Exception:
            return False

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

    def _is_editable_text_input_focused(self, focus) -> bool:
        """True when focus is in a text field the user can actually type into.

        The article view (`content_ctrl`) is a read-only TextCtrl, so the
        text-guarded media shortcuts (play/pause, stop, queue next/prev) must
        keep working while reading it — only editable fields (e.g. search)
        suppress them.
        """
        if not self._is_text_input_focused(focus):
            return False
        try:
            is_editable = getattr(focus, "IsEditable", None)
            if callable(is_editable) and not is_editable():
                return False
        except Exception:
            pass
        return True

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

    @staticmethod
    def _find_in_text(text, term, start, forward=True, wrap=True):
        """Find `term` in `text` case-insensitively. Returns (start, end) or None.
        forward=True: first match at index >= start, else wrap to top.
        forward=False: last match at index < start, else wrap to bottom."""
        if not text or not term:
            return None
        hay = text.lower()
        needle = term.lower()
        n = len(text)
        start = max(0, min(int(start), n))
        if forward:
            idx = hay.find(needle, start)
            if idx == -1 and wrap:
                idx = hay.find(needle, 0)
        else:
            idx = hay.rfind(needle, 0, start)
            if idx == -1 and wrap:
                idx = hay.rfind(needle)
        if idx == -1:
            return None
        return (idx, idx + len(needle))

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

        if MainFrame._is_plain_backspace_event(self, event, key):
            if MainFrame._window_is_or_child(self, focus, self.list_ctrl):
                try:
                    new_status = self.toggle_selected_article_read_status()
                    if new_status:
                        self._announce_event("status_toggle", new_status)
                    return
                except Exception:
                    log.exception("Error toggling article read status on Backspace")

        # Registry-managed shortcuts (refresh, filters, player, queue, speed,
        # and every other command in Tools > Keyboard Shortcuts). Dispatched
        # here — before menu accelerators — so they work window-wide and the
        # keyboard path can announce itself (issue #67) while menu clicks
        # stay silent.
        try:
            if self.dispatch_shortcut(event, focus):
                return
        except Exception:
            log.exception("Error dispatching registry shortcut")

        if focus == self.content_ctrl:
            if (
                key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and not event.ControlDown()
                and not event.ShiftDown()
                and not event.AltDown()
                and not event.MetaDown()
            ):
                try:
                    if self._open_link_at_content_cursor():
                        return
                except Exception:
                    log.exception("Error opening link from reader pane")
            if (
                event.ControlDown()
                and not event.ShiftDown()
                and not event.AltDown()
                and not event.MetaDown()
                and key in (ord("F"), ord("f"))
            ):
                try:
                    self.on_find_in_article()
                    return
                except Exception:
                    log.exception("Error opening find-in-article")
            if (
                key == wx.WXK_F3
                and not event.ControlDown()
                and not event.AltDown()
                and not event.MetaDown()
            ):
                try:
                    if event.ShiftDown():
                        self.on_find_prev_in_article()
                    else:
                        self.on_find_next_in_article()
                    return
                except Exception:
                    log.exception("Error navigating find-in-article")

        if MainFrame._is_delete_key(self, key):
            if MainFrame._window_is_or_child(self, focus, self.list_ctrl):
                try:
                    if MainFrame._is_shift_delete_event(self, event, key):
                        self.on_delete_article(confirm=False)
                    else:
                        self.on_delete_article()
                    return
                except Exception:
                    log.exception("Error handling article delete shortcut")
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
                    self._cmd_edit_selected(None)
                    return
                except Exception:
                    log.exception("Error opening properties editor on F2")

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
            chapters = list(getattr(pw, "current_chapters", []) or []) if pw else []
            if pw and chapters:
                try:
                    active_idx = int(pw.get_active_chapter_index())
                except Exception:
                    active_idx = -1
                if key == wx.WXK_LEFT and active_idx > 0:
                    try:
                        self.on_player_prev_chapter(None)
                        return
                    except Exception:
                        pass
                elif key == wx.WXK_RIGHT and active_idx < len(chapters) - 1:
                    try:
                        self.on_player_next_chapter(None)
                        return
                    except Exception:
                        pass
            if key in (wx.WXK_LEFT, wx.WXK_RIGHT):
                event.Skip()
                return

        if event.ControlDown() and not event.ShiftDown() and not event.AltDown() and not event.MetaDown():
            if key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN) and (
                self._is_text_input_focused(focus) or self._is_rich_view_focused(focus)
            ):
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

    def on_article_list_key_down(self, event: wx.KeyEvent) -> None:
        try:
            key = event.GetKeyCode()
        except Exception:
            key = None

        if MainFrame._is_plain_backspace_event(self, event, key):
            try:
                self.toggle_selected_article_read_status()
                return
            except Exception:
                log.exception("Error toggling article read status on Backspace")

        if MainFrame._is_delete_key(self, key):
            try:
                if MainFrame._is_shift_delete_event(self, event, key):
                    self.on_delete_article(confirm=False)
                else:
                    self.on_delete_article()
                return
            except Exception:
                log.exception("Error handling article list delete shortcut")

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

    # -----------------------------------------------------------------
    # Play-queue navigation (Play Next / Play Previous in queue)
    # -----------------------------------------------------------------

    def on_play_queue_next(self, event=None) -> None:
        self._play_queue_step(+1)

    def on_play_queue_prev(self, event=None) -> None:
        self._play_queue_step(-1)

    def _play_queue_step(self, delta: int) -> None:
        """Start playback of the queue item `delta` away from the current one.

        Works even when the queue dialog isn't focused. If nothing is marked as
        the current queue item yet, the first item (forward) or last item
        (backward) is used so the shortcut can kick off playback from idle.
        """
        queue = self._get_play_queue()
        if not queue:
            self._announce_event("media_navigation", _("Play queue is empty."))
            return
        cur = getattr(self, "_current_queue_index", None)
        if cur is None or not (0 <= int(cur) < len(queue)):
            target = 0 if delta >= 0 else len(queue) - 1
        else:
            target = int(cur) + int(delta)
        if not (0 <= target < len(queue)):
            self._announce_event(
                "media_navigation",
                _("End of play queue.") if delta >= 0 else _("Start of play queue."),
            )
            return
        if self.play_queue_index(target):
            try:
                title = str(queue[target].get("title") or "").strip()
            except Exception:
                title = ""
            self._announce_event(
                "media_navigation",
                _("Playing {position} of {total}: {title}").format(
                    position=target + 1, total=len(queue), title=title
                )
                if title
                else _("Playing {position} of {total}").format(
                    position=target + 1, total=len(queue)
                ),
            )

    # -----------------------------------------------------------------
    # Playback speed (menu + shortcuts)
    # -----------------------------------------------------------------

    def _player_for_speed(self):
        pw = getattr(self, "player_window", None)
        return pw

    def on_player_speed_up(self, event=None) -> None:
        self._nudge_playback_speed(+1)

    def on_player_speed_down(self, event=None) -> None:
        self._nudge_playback_speed(-1)

    def on_player_speed_reset(self, event=None) -> None:
        self._apply_playback_speed(1.0)

    def _nudge_playback_speed(self, direction: int) -> None:
        speeds = utils.build_playback_speeds()
        if not speeds:
            return
        try:
            current = float(self.config_manager.get("playback_speed", 1.0))
        except Exception:
            current = 1.0
        # Snap current to the nearest available speed, then step.
        idx = min(range(len(speeds)), key=lambda i: abs(speeds[i] - current))
        idx = max(0, min(len(speeds) - 1, idx + int(direction)))
        self._apply_playback_speed(speeds[idx])

    def _apply_playback_speed(self, speed: float) -> None:
        speed = float(speed)
        pw = self._player_for_speed()
        if pw is not None:
            try:
                pw.set_playback_speed(speed)
            except Exception:
                log.exception("Failed to set playback speed on player")
        else:
            # No player yet: persist so it applies when playback starts.
            try:
                self.config_manager.set("playback_speed", speed)
            except Exception:
                pass
        # Status bar only (no speech): the keyboard path announces the speed via
        # dispatch_shortcut so a menu-driven change stays quiet (issue #67).
        try:
            self.SetStatusText(
                _("Playback speed {speed}x").format(speed=("%g" % round(speed, 2))), 0
            )
        except Exception:
            pass
        try:
            self._sync_speed_menu_check()
        except Exception:
            pass

    def _sync_speed_menu_check(self) -> None:
        """Check the speed radio item nearest to the current playback speed."""
        items = getattr(self, "_speed_menu_items", None)
        if not items:
            return
        try:
            current = float(self.config_manager.get("playback_speed", 1.0))
        except Exception:
            current = 1.0
        nearest = min(items.keys(), key=lambda s: abs(s - current))
        for speed, item in items.items():
            try:
                item.Check(speed == nearest)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Editable keyboard-shortcut registry
    # -----------------------------------------------------------------

    # Commands suppressed while an *editable* text field is focused so they
    # never hijack typing. Read-only fields (the article view) do not suppress
    # them: a user reading an article while listening still needs play/pause,
    # stop, and queue next/prev. Speed up/down/reset are intentionally NOT
    # here: their combos (e.g. Ctrl+Shift+brackets or comma/period) are not
    # text-editing keys — guarding them there made the speed shortcuts appear
    # dead.
    _SHORTCUT_TEXT_GUARDED = frozenset({
        "player.play_pause", "player.stop",
        "queue.next", "queue.prev",
        # The Ctrl+digit filter shortcuts have always deferred to an editable
        # text field (parity with the pre-registry hard-coded handling).
        "filter.read_all", "filter.read_unread", "filter.read_read",
        "filter.media_all", "filter.media_with", "filter.media_without",
    })

    def _shortcut_handlers(self) -> dict:
        return {
            "feeds.add": self.on_add_feed,
            "feeds.detect_page": self.on_detect_page_feeds,
            "feeds.remove": self.on_remove_feed,
            "feeds.refresh_all": self._cmd_refresh_all,
            "feeds.stop_refresh": self._cmd_stop_refresh,
            "feeds.refresh_selected": self.on_refresh_single_feed,
            "feeds.edit_selected": self._cmd_edit_selected,
            "feeds.mark_all_read": self.on_mark_all_read,
            "feeds.view_errors": self.on_view_feed_errors,
            "feeds.copy_url": self.on_copy_feed_url,
            "feeds.add_category": self.on_add_category,
            "feeds.remove_category": self.on_remove_category,
            "feeds.import_opml": self.on_import_opml,
            "feeds.import_youtube_takeout": self.on_import_youtube_takeout,
            "feeds.export_opml": self.on_export_opml,
            "feeds.find_podcast": self.on_find_feed,
            "feeds.video_search": self.on_ytdlp_global_search,

            "media.open_url": self.on_open_media_url,

            "article.open_browser": self._cmd_open_in_browser,
            "article.copy_link": self._cmd_copy_link,
            "article.copy_media_link": self._cmd_copy_media_link,
            "article.copy_text": self._cmd_copy_text,
            "article.toggle_read": self._cmd_toggle_read,
            "article.toggle_favorite": self.on_toggle_favorite,
            "article.delete": self.on_delete_article,
            "article.download": self._cmd_download_article,
            "article.download_as": self._cmd_download_article_as,
            "article.toggle_queue": self._cmd_toggle_queue,
            "article.view_description": self._cmd_view_description,

            "view.focus_search": self._cmd_focus_search,
            "view.toggle_search": self._cmd_toggle_search_field,
            "view.rich_view": self.on_toggle_rich_view,
            "view.accessible_browser": self.on_open_accessible_browser,

            "filter.read_all": self._cmd_filter_read_all,
            "filter.read_unread": self._cmd_filter_read_unread,
            "filter.read_read": self._cmd_filter_read_read,
            "filter.media_all": self._cmd_filter_media_all,
            "filter.media_with": self._cmd_filter_media_with,
            "filter.media_without": self._cmd_filter_media_without,

            "sort.date": self._cmd_sort_date,
            "sort.name": self._cmd_sort_name,
            "sort.author": self._cmd_sort_author,
            "sort.description": self._cmd_sort_description,
            "sort.feed": self._cmd_sort_feed,
            "sort.status": self._cmd_sort_status,
            "sort.ascending": self._cmd_toggle_sort_ascending,

            "player.play_pause": self.on_player_play_pause,
            "player.stop": self.on_player_stop,
            "player.show_hide": self.on_show_player,
            "player.equalizer": self.on_open_equalizer,
            "player.chapters": self.on_player_show_chapters,
            "queue.open": self.on_open_play_queue,
            "queue.next": self.on_play_queue_next,
            "queue.prev": self.on_play_queue_prev,
            "speed.up": self.on_player_speed_up,
            "speed.down": self.on_player_speed_down,
            "speed.reset": self.on_player_speed_reset,

            "tools.filter_rules": self.on_manage_filter_rules,
            "tools.import_site_cookies": self.on_import_site_cookies,
            "tools.persistent_search": self.on_configure_persistent_search,
            "tools.keyboard_shortcuts": self.on_open_keyboard_shortcuts,
            "tools.settings": self.on_settings,
            "tools.check_updates": self.on_check_updates,
        }

    # --- Registry command wrappers ------------------------------------
    # Thin adapters between registry dispatch (handler(None)) and handlers
    # that need a selection index, a menu event, or the keyboard-only
    # announcement the equivalent menu click deliberately skips (issue #67).

    def _cmd_refresh_all(self, event=None):
        if self._is_feed_refresh_active():
            return
        self.on_refresh_feeds()
        self._announce_event("start_update", _("Refresh Feeds"))

    def _cmd_stop_refresh(self, event=None):
        if not self._is_feed_refresh_active():
            return
        self.on_stop_refresh()
        self._announce_event("stop_update", _("Stop Refresh"))

    def _cmd_selected_article_index(self):
        try:
            idx = self._get_selected_article_index()
        except Exception:
            return None
        if idx is None or idx < 0 or idx >= len(self.current_articles):
            return None
        return int(idx)

    def _cmd_open_in_browser(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is not None:
            self.on_open_in_browser(idx)

    def _cmd_copy_link(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is not None:
            self.on_copy_link(idx)

    def _cmd_copy_media_link(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is not None and self._has_direct_media_link(self.current_articles[idx]):
            self.on_copy_media_link(idx)

    def _cmd_copy_text(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is not None:
            self.on_copy_text(idx)

    def _cmd_toggle_read(self, event=None):
        # Same behavior (and announcement) as Backspace in the article list.
        new_status = self.toggle_selected_article_read_status()
        if new_status:
            self._announce_event("status_toggle", new_status)

    def _cmd_download_article(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is not None:
            article = self.current_articles[idx]
            if getattr(article, "media_url", None):
                self.on_download_article(article)

    def _cmd_download_article_as(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is not None:
            article = self.current_articles[idx]
            if getattr(article, "media_url", None):
                self.on_download_article_as(article)

    def _cmd_toggle_queue(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is None:
            return
        article = self.current_articles[idx]
        if not self._should_play_in_player(article):
            return
        if self._is_article_in_queue(article):
            self.remove_articles_from_queue([idx])
        else:
            self.add_articles_to_queue([idx])

    def _cmd_view_description(self, event=None):
        idx = self._cmd_selected_article_index()
        if idx is not None:
            self.on_view_feed_description(idx)

    def _cmd_focus_search(self, event=None):
        if not getattr(self, "_search_visible", True):
            self._cmd_set_search_visible(True)
        try:
            self.search_ctrl.SetFocus()
        except Exception:
            pass

    def _cmd_set_search_visible(self, visible: bool) -> None:
        self._set_search_visible(bool(visible))
        item = getattr(self, "_show_search_item", None)
        if item is not None:
            try:
                item.Check(bool(visible))
            except Exception:
                pass

    def _cmd_toggle_search_field(self, event=None):
        self._cmd_set_search_visible(not getattr(self, "_search_visible", True))

    def _cmd_set_filter(self, group: str, mode: str) -> None:
        """Apply an article filter and announce it (keyboard path, issue #67)."""
        if group == "read":
            items = getattr(self, "_article_filter_menu_items", None) or {}
            self.on_change_article_filter(mode)
        else:
            items = getattr(self, "_article_media_filter_menu_items", None) or {}
            self.on_change_media_filter(mode)
        # Announce the exact visible menu-item name (mnemonics/accelerator
        # stripped) so the spoken/Braille text matches what the menu shows.
        label = ""
        item = items.get(mode)
        if item is not None:
            try:
                label = item.GetItemLabelText()
            except Exception:
                label = ""
        if label:
            self._announce_event("filter_change", label)

    def _cmd_filter_read_all(self, event=None):
        self._cmd_set_filter("read", "all")

    def _cmd_filter_read_unread(self, event=None):
        self._cmd_set_filter("read", "unread")

    def _cmd_filter_read_read(self, event=None):
        self._cmd_set_filter("read", "read")

    def _cmd_filter_media_all(self, event=None):
        self._cmd_set_filter("media", "all")

    def _cmd_filter_media_with(self, event=None):
        self._cmd_set_filter("media", "with")

    def _cmd_filter_media_without(self, event=None):
        self._cmd_set_filter("media", "without")

    def _cmd_set_sort(self, key: str) -> None:
        key = self._normalize_article_sort_by(key)
        if key == getattr(self, "_article_sort_by", "date"):
            return
        self._article_sort_by = key
        try:
            self.config_manager.set("article_sort_by", key)
        except Exception:
            pass
        item = (getattr(self, "_sort_by_items_by_key", None) or {}).get(key)
        if item is not None:
            try:
                item.Check(True)
            except Exception:
                pass
        self._refresh_articles_for_sort_change()

    def _cmd_sort_date(self, event=None):
        self._cmd_set_sort("date")

    def _cmd_sort_name(self, event=None):
        self._cmd_set_sort("name")

    def _cmd_sort_author(self, event=None):
        self._cmd_set_sort("author")

    def _cmd_sort_description(self, event=None):
        self._cmd_set_sort("description")

    def _cmd_sort_feed(self, event=None):
        self._cmd_set_sort("feed")

    def _cmd_sort_status(self, event=None):
        self._cmd_set_sort("status")

    def _cmd_toggle_sort_ascending(self, event=None):
        new_val = not bool(getattr(self, "_article_sort_ascending", False))
        self._article_sort_ascending = new_val
        try:
            self.config_manager.set("article_sort_ascending", new_val)
        except Exception:
            pass
        item = getattr(self, "_sort_ascending_item", None)
        if item is not None:
            try:
                item.Check(new_val)
            except Exception:
                pass
        self._refresh_articles_for_sort_change()

    def get_shortcut_overrides(self) -> dict:
        try:
            raw = self.config_manager.get("keyboard_shortcuts", {})
        except Exception:
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def get_shortcut_bindings(self) -> dict:
        """Resolved {command_id: accel_string} with user overrides applied."""
        return shortcuts_mod.resolve_bindings(self.get_shortcut_overrides())

    def save_shortcut_overrides(self, overrides: dict) -> None:
        try:
            self.config_manager.set("keyboard_shortcuts", dict(overrides or {}))
        except Exception:
            log.exception("Failed to save keyboard shortcut overrides")
        self.reload_shortcuts()

    def _rebuild_shortcut_map(self) -> None:
        try:
            self._shortcut_cmd_map = shortcuts_mod.invert_bindings(self.get_shortcut_bindings())
        except Exception:
            log.exception("Failed to rebuild shortcut map")
            self._shortcut_cmd_map = {}

    def reload_shortcuts(self) -> None:
        self._rebuild_shortcut_map()
        try:
            self._refresh_shortcut_menu_labels()
        except Exception:
            log.exception("Failed to refresh shortcut menu labels")

    def binding_label(self, command_id: str) -> str:
        """Human accel string for a command's current binding, or '' if unbound."""
        try:
            return self.get_shortcut_bindings().get(command_id, "") or ""
        except Exception:
            return ""

    def dispatch_shortcut(self, event: "wx.KeyEvent", focus=None, apply_text_guard: bool = True) -> bool:
        """Handle a registry-managed shortcut for a key event. Returns True if handled.

        `apply_text_guard` should be False when dispatching from the player
        window, which has no editable text fields — its read-only time display
        must not suppress play/pause, stop, speed, or queue shortcuts.
        """
        try:
            accel = event_to_accel(event)
        except Exception:
            accel = None
        if not accel:
            return False
        cmd_id = self._shortcut_cmd_map.get(accel)
        if not cmd_id:
            return False
        if apply_text_guard and cmd_id in self._SHORTCUT_TEXT_GUARDED:
            try:
                if self._is_editable_text_input_focused(focus):
                    return False
            except Exception:
                pass
        handler = self._shortcut_handlers().get(cmd_id)
        if handler is None:
            return False
        try:
            handler(None)
        except Exception:
            log.exception("Error dispatching shortcut %s", cmd_id)
        # Keyboard-only announcement (issue #67): the speed handlers keep the
        # menu path silent (status bar only); announce the resulting speed here
        # so only the keyboard shortcut speaks/brailles it. Queue navigation
        # announces itself in _play_queue_step (shared by keyboard and menu).
        if cmd_id in ("speed.up", "speed.down", "speed.reset"):
            try:
                self._announce_event("playback_speed", self._current_playback_speed_message())
            except Exception:
                log.debug("Playback-speed announcement failed", exc_info=True)
        return True

    def _current_playback_speed_message(self) -> str:
        try:
            speed = float(self.config_manager.get("playback_speed", 1.0))
        except Exception:
            speed = 1.0
        return _("Playback speed {speed}x").format(speed=("%g" % round(speed, 2)))

    def _shortcut_menu_label(self, base_label: str, command_id: str) -> str:
        accel = self.binding_label(command_id)
        return "{base} ({accel})".format(base=base_label, accel=accel) if accel else str(base_label)

    def _refresh_shortcut_menu_labels(self) -> None:
        # A command can surface in several menus (e.g. Show/Hide Player lives
        # in both View and Player), so each id maps to a LIST of items.
        for command_id, entries in getattr(self, "_shortcut_menu_items", {}).items():
            for item, base_label in list(entries or []):
                try:
                    item.SetItemLabel(self._shortcut_menu_label(base_label, command_id))
                except Exception:
                    pass
        # Re-derive menu access keys: SetItemLabel above rebuilt each label
        # from its base text, wiping any auto-assigned mnemonic.
        try:
            menubar = self.GetMenuBar()
            if menubar is not None:
                apply_menubar_mnemonics(menubar)
        except Exception:
            pass

    def on_open_keyboard_shortcuts(self, event=None) -> None:
        try:
            from .dialogs import KeyboardShortcutsDialog
            dlg = KeyboardShortcutsDialog(self, self)
            dlg.ShowModal()
            dlg.Destroy()
        except Exception:
            log.exception("Failed to open keyboard shortcuts dialog")

    def on_import_site_cookies(self, event=None) -> None:
        """Import browser cookies for challenge-protected sites (issue #79)."""
        try:
            from .dialogs import ImportSiteCookiesDialog
            dlg = ImportSiteCookiesDialog(self)
            dlg.ShowModal()
            dlg.Destroy()
        except Exception:
            log.exception("Failed to open site cookies import dialog")

    def on_open_equalizer(self, event=None) -> None:
        pw = self._ensure_player_window()
        if not pw:
            return
        try:
            pw.open_equalizer_dialog()
        except Exception:
            log.exception("Failed to open equalizer dialog")

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
            speed_submenu = getattr(self, "_speed_submenu", None)
            if opened_menu is getattr(self, "_player_menu", None) or opened_menu is speed_submenu:
                self._sync_speed_menu_check()
        except Exception:
            pass
        try:
            event.Skip()
        except Exception:
            pass

    def _format_chapter_timestamp(self, start) -> str:
        try:
            seconds = float(start or 0)
        except Exception:
            seconds = 0.0
        if not (-float("inf") < seconds < float("inf")) or seconds < 0:
            seconds = 0.0
        total_seconds = int(seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _format_player_chapter_menu_label(self, chapter: dict) -> str:
        timestamp = self._format_chapter_timestamp(chapter.get("start", 0))
        title = str(chapter.get("title", "") or "").strip() or _("Untitled chapter")
        return f"{timestamp}, {title}"

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
        active_idx = -1

        if not has_chapters:
            try:
                empty_item = submenu.Append(wx.ID_ANY, _("No chapters available"))
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
                        label = _("Current chapter, {label}").format(label=label)
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
                self._shortcut_menu_label(_("Show Chapters..."), "player.chapters"),
                _("Show chapter list"),
            )
            self.Bind(wx.EVT_MENU, self.on_player_show_chapters, self._player_chapters_show_item)
            self._player_chapter_static_item_ids.append(int(self._player_chapters_show_item.GetId()))
        except Exception:
            self._player_chapters_show_item = None

        try:
            self._player_chapters_prev_item = submenu.Append(
                wx.ID_ANY,
                _("Previous Chapter (Ctrl+Shift+Left)"),
                _("Jump to previous chapter"),
            )
            self.Bind(wx.EVT_MENU, self.on_player_prev_chapter, self._player_chapters_prev_item)
            self._player_chapter_static_item_ids.append(int(self._player_chapters_prev_item.GetId()))
        except Exception:
            self._player_chapters_prev_item = None

        try:
            self._player_chapters_next_item = submenu.Append(
                wx.ID_ANY,
                _("Next Chapter (Ctrl+Shift+Right)"),
                _("Jump to next chapter"),
            )
            self.Bind(wx.EVT_MENU, self.on_player_next_chapter, self._player_chapters_next_item)
            self._player_chapter_static_item_ids.append(int(self._player_chapters_next_item.GetId()))
        except Exception:
            self._player_chapters_next_item = None

        try:
            if self._player_chapters_show_item is not None:
                self._player_chapters_show_item.Enable(bool(has_chapters))
            if self._player_chapters_prev_item is not None:
                self._player_chapters_prev_item.Enable(bool(has_chapters and active_idx > 0))
            if self._player_chapters_next_item is not None:
                self._player_chapters_next_item.Enable(bool(has_chapters and active_idx < len(chapters) - 1))
        except Exception:
            pass
        try:
            apply_menu_mnemonics(submenu)
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
        log.info("Manual full refresh requested")
        threading.Thread(target=self._manual_refresh_thread, daemon=True).start()

    def on_update_refresh_feeds_ui(self, event):
        event.Enable(not self._is_feed_refresh_active())

    def on_update_stop_refresh_ui(self, event):
        event.Enable(self._is_feed_refresh_active())

    def on_stop_refresh(self, event=None):
        """Stop the batch feed refresh currently in flight (cooperative:
        feeds already being fetched finish, queued ones are skipped)."""
        try:
            requested = bool(self.provider.cancel_refresh())
        except Exception:
            log.exception("Failed to request refresh cancellation")
            requested = False
        if requested:
            log.info("User requested refresh stop")
            self._refresh_stop_requested = True
            self._post_activity_status(_("Stopping refresh..."))
        else:
            self._post_activity_status(_("No refresh in progress"))

    def on_refresh_single_feed(self, event):
        item = self.tree.GetSelection()
        feed_id = self._get_feed_id_from_tree_item(item)
        if not feed_id:
            return
        threading.Thread(target=self._refresh_single_feed_thread, args=(feed_id,), daemon=True).start()

    def on_refresh_category(self, event=None, category_title: str | None = None):
        cat_title = str(category_title or "").strip()
        if not cat_title:
            item = self.tree.GetSelection()
            if item and item.IsOk():
                data = self.tree.GetItemData(item)
                if data and data.get("type") == "category":
                    cat_title = str(data.get("id") or "").strip()
        if not cat_title:
            return
        threading.Thread(target=self._refresh_category_thread, args=(cat_title,), daemon=True).start()

    def on_view_feed_errors(self, event=None):
        """Open the Feeds with Errors view (issue #32)."""
        from gui.dialogs import FeedErrorsDialog
        try:
            errors = self.provider.get_feed_errors() if self.provider else []
        except Exception:
            log.debug("Failed to fetch feed errors", exc_info=True)
            errors = []
        dlg = FeedErrorsDialog(self, errors, provider=self.provider)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

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

    def on_set_feed_images(self, feed_id: str, value):
        """Set a feed's image-alt override: None=inherit global, True=always, False=never."""
        try:
            from core.db import set_feed_show_images
            set_feed_show_images(feed_id, value)
        except Exception:
            log.debug("Failed to set per-feed image override", exc_info=True)
            return
        try:
            self._feed_show_images_cache[feed_id] = value
        except Exception:
            self._feed_show_images_cache = {feed_id: value}
        # Re-render the current article so the change takes effect immediately.
        try:
            idx = self.list_ctrl.GetFirstSelected()
            if idx is not None and idx >= 0:
                self._update_content_view(idx)
        except Exception:
            pass

    def _windows_notifications_enabled(self) -> bool:
        if not utils.platform_supports_notifications():
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

        title = str(payload.get("title") or _("New article")).strip() or _("New article")
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
            self._open_article_url(url)

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
        return _("New article available.")

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
            "title": str(item.get("title") or _("New article")).strip() or _("New article"),
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
            title = str(getattr(article, "title", "") or "").strip() or _("New article")
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
                title = str(item.get("title") or _("New article")).strip() or _("New article")
                preview = self._notification_preview_text(item.get("preview") or "")
                body = self._build_notification_body(preview, feed_title, include_feed)
                activation_payload = self._build_notification_activation_payload(item, feed_id=feed_id)
                wx.CallAfter(self._show_windows_notification, title, body, activation_payload)
                sent += 1
                if not unlimited:
                    remaining = max(0, remaining - 1)

            for _ in range(max(0, generic_count - sent)):
                body = feed_title if (include_feed and feed_title) else _("New article available.")
                wx.CallAfter(self._show_windows_notification, _("New article"), body)
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
            article_title = str(item.get("title") or _("New article")).strip() or _("New article")
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
        if not windows_integration.startup_supported():
            return True, ""
        return windows_integration.set_startup_enabled(bool(enabled))

    def _refresh_single_feed_thread(self, feed_id):
        log.info("Manual single-feed refresh requested feed_id=%s", feed_id)
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
            started_at = time.monotonic()
            # Hold the refresh guard so a manual single-feed refresh cannot run
            # concurrently with the background refresh loop (or another targeted
            # refresh), which would cause overlapping provider work / double-fetch.
            acquired = False
            try:
                acquired = self._refresh_guard.acquire(blocking=True)
            except Exception:
                acquired = False
            if not acquired:
                log.info("Single-feed refresh skipped; refresh guard unavailable feed_id=%s", feed_id)
                return
            feed_obj = self.feed_map.get(feed_id)
            feed_title = getattr(feed_obj, "title", None)
            # No total here: one feed's title says more than "1 out of 1".
            self._begin_refresh_activity(
                _("Refreshing feed: {title}...").format(title=feed_title)
                if feed_title
                else _("Refreshing feed...")
            )
            try:
                result = self.provider.refresh_feed(feed_id, progress_cb=progress_cb)
            finally:
                self._end_refresh_activity()
                try:
                    self._refresh_guard.release()
                except Exception:
                    pass
            log.info(
                "Manual single-feed refresh finished feed_id=%s provider_result=%s duration_s=%.2f new_items=%s",
                feed_id,
                result,
                time.monotonic() - started_at,
                new_items_total,
            )
            wx.CallAfter(self._flush_feed_refresh_progress) # Ensure it flushes immediately
            if (
                suppressed.get("count", 0) > 0
                and bool(self.config_manager.get("windows_notifications_show_summary_when_capped", True))
            ):
                hidden = int(suppressed.get("count", 0))
                wx.CallAfter(
                    self._show_windows_notification,
                    "BlindRSS",
                    _("{hidden} new article notification(s) were suppressed by your cap.").format(hidden=hidden),
                )
            # We don't need to call refresh_feeds() (full tree rebuild) if we just updated one feed.
            # The progress callback updates the tree item label.
            # Always play the completion sound (even with no new items) so a
            # targeted refresh gives audible feedback that it finished.
            self._play_sound("sound_refresh_complete")
        except Exception as e:
            print(f"Single feed refresh error: {e}")
            self._play_sound("sound_refresh_error")

    def _perform_retention_cleanup(self):
        """Perform retention cleanup based on config settings."""
        try:
            from core.db import cleanup_old_articles
            from core.retention import RETENTION_DEFAULT, retention_days
            days = retention_days(
                self.config_manager.get("article_retention", RETENTION_DEFAULT)
            )
            if days is not None:
                cleanup_old_articles(days)
        except Exception as e:
            log.error(f"Retention cleanup failed: {e}")

        # The hosted-provider chapter cache has its own time-based retention, so bound
        # its growth unconditionally (independent of the article-retention setting).
        try:
            from core.db import cleanup_hosted_chapter_cache
            cleanup_hosted_chapter_cache()
        except Exception as e:
            log.error(f"Hosted chapter cache cleanup failed: {e}")

    def _run_refresh(self, block: bool, force: bool = False, scheduled: bool = False) -> bool:
        """Run provider.refresh with optional blocking guard to avoid overlap.
        
        Performs retention cleanup BEFORE the refresh to avoid the following bug:
        1. User marks all as read
        2. Cleanup deletes those read articles
        3. RSS refresh re-inserts them as unread (because they were deleted)
        
        By running cleanup here (before RSS fetch), we ensure that only articles
        that existed BEFORE the refresh can be marked as read, and they won't be
        resurrected as unread.
        """
        started_at = time.monotonic()
        provider_name = type(self.provider).__name__
        log.info(
            "Refresh run requested provider=%s block=%s force=%s thread=%s",
            provider_name,
            block,
            force,
            threading.current_thread().name,
        )
        acquired = False
        try:
            acquired = self._refresh_guard.acquire(blocking=block)
        except Exception:
            acquired = False
        if not acquired:
            log.info(
                "Refresh run skipped because another refresh is active provider=%s block=%s force=%s",
                provider_name,
                block,
                force,
            )
            return False
        self._begin_refresh_activity(total=self._expected_refresh_feed_count())
        # Keep tree/count progress live, but do not repeatedly reload the
        # selected article list while many feeds finish in parallel.  The final
        # tree refresh below performs one coherent list update after the
        # progress queue has drained.
        refresh_ui_batch_token = self._begin_refresh_ui_batch()
        provider_result = False
        try:
            log.info("Refresh run acquired guard provider=%s force=%s", provider_name, force)
            # Maintenance is useful at startup/manual refresh, but running the
            # same SQLite cleanup every short scheduled interval creates
            # needless CPU and disk churn.  Hourly is sufficient for periodic
            # retention while preserving immediate manual/startup behavior.
            maintenance_now = time.monotonic()
            last_maintenance = float(
                getattr(self, "_last_retention_cleanup_monotonic", 0.0) or 0.0
            )
            if not scheduled or maintenance_now - last_maintenance >= 3600.0:
                self._perform_retention_cleanup()
                self._last_retention_cleanup_monotonic = maintenance_now
            
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
                # Hosted providers can report thousands of unchanged feed
                # states on every scheduled metadata poll.  They still pass
                # through notification accounting above, but do not need a
                # native ListView/TreeCtrl update (and accessibility event) if
                # the visible title/category/count is identical.
                queue_ui_state = True
                if scheduled:
                    feed_id = str((state or {}).get("id") or "")
                    cached_feed = (getattr(self, "feed_map", {}) or {}).get(feed_id)
                    if cached_feed is not None:
                        queue_ui_state = not (
                            (str((state or {}).get("title") or "") or str(getattr(cached_feed, "title", "") or ""))
                            == str(getattr(cached_feed, "title", "") or "")
                            and str((state or {}).get("category") or UNCATEGORIZED)
                            == str(getattr(cached_feed, "category", UNCATEGORIZED) or UNCATEGORIZED)
                            and int((state or {}).get("unread_count", 0) or 0)
                            == int(getattr(cached_feed, "unread_count", 0) or 0)
                        )
                if queue_ui_state:
                    self._on_feed_refresh_progress(state, batch_token=refresh_ui_batch_token)

            provider_result = self.provider.refresh(progress_cb, force=force, scheduled=scheduled)
            log.info(
                "Provider refresh returned provider=%s result=%s force=%s duration_s=%.2f new_items=%s",
                provider_name,
                provider_result,
                force,
                time.monotonic() - started_at,
                new_items_total,
            )
            if (
                suppressed.get("count", 0) > 0
                and bool(self.config_manager.get("windows_notifications_show_summary_when_capped", True))
            ):
                hidden = int(suppressed.get("count", 0))
                wx.CallAfter(
                    self._show_windows_notification,
                    "BlindRSS",
                    ngettext(
                        "{count} new article notification was suppressed by your cap.",
                        "{count} new article notifications were suppressed by your cap.",
                        hidden,
                    ).format(count=hidden),
                )
            if new_items_total > 0:
                self._play_sound("sound_refresh_complete")
            log.info(
                "Refresh run finished provider=%s force=%s duration_s=%.2f new_items=%s",
                provider_name,
                force,
                time.monotonic() - started_at,
                new_items_total,
            )
            return True
        except Exception as e:
            print(f"Refresh error: {e}")
            log.exception(
                "Refresh run failed provider=%s force=%s duration_s=%.2f",
                provider_name,
                force,
                time.monotonic() - started_at,
            )
            self._play_sound("sound_refresh_error")
            return False
        finally:
            try:
                # This must run on the wx thread.  It waits for the bounded
                # progress flushes already queued by worker threads, then runs
                # the one final tree/list refresh (or a single selected-view
                # reload when the provider did not request a tree refresh).
                wx.CallAfter(
                    self._finish_refresh_ui_batch,
                    bool(provider_result),
                    refresh_ui_batch_token,
                )
            except Exception:
                log.debug("Failed to finish refresh UI batch", exc_info=True)
            try:
                self._refresh_guard.release()
                log.info("Refresh run released guard provider=%s force=%s", provider_name, force)
            except Exception:
                pass

    def _manual_refresh_thread(self):
        # Manual refresh should wait for any in-flight refresh to finish.
        log.info("Manual full refresh thread started")
        ran = self._run_refresh(block=True, force=True)
        if not ran:
            print("Manual refresh skipped: another refresh is running.")
            log.info("Manual full refresh did not run because another refresh was active")
        else:
            log.info("Manual full refresh thread finished")

    def on_close(self, event):
        # If user prefers closing to tray and this is a real close event, just hide
        if event and self.config_manager.get("close_to_tray", False):
            event.Veto()
            self.Hide()
            return

        try:
            persist_owned_text_clipboard()
        except Exception:
            log.debug("Failed to persist clipboard during shutdown", exc_info=True)

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

            refresh_category_item = menu.Append(wx.ID_ANY, _("Refresh Category"))
            self.Bind(wx.EVT_MENU, lambda e, ct=cat_title: self.on_refresh_category(e, ct), refresh_category_item)

            mark_cat_read_item = menu.Append(wx.ID_ANY, _("Mark All Items as Read"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, ct=cat_title: self._confirm_and_mark_all_read(
                    f"category:{ct}",
                    _('Mark all items in category "{category}" as read?').format(category=ct),
                ),
                mark_cat_read_item,
            )

            if getattr(self.provider, "supports_subcategories", lambda: False)():
                add_sub_item = menu.Append(wx.ID_ANY, _("Add Subcategory"))
                self.Bind(wx.EVT_MENU, lambda e, ct=cat_title: self.on_add_subcategory(ct), add_sub_item)

            if not self._is_protected_uncategorized(cat_title):
                edit_item = menu.Append(wx.ID_ANY, _("Edit Category"))
                self.Bind(wx.EVT_MENU, lambda e: self.on_edit_category(cat_title), edit_item)

                remove_item = menu.Append(wx.ID_ANY, _("Remove Category"))
                self.Bind(wx.EVT_MENU, self.on_remove_category, remove_item)

                delete_with_feeds_item = menu.Append(wx.ID_ANY, _("Delete Category and Feeds"))
                self.Bind(wx.EVT_MENU, self.on_delete_category_with_feeds, delete_with_feeds_item)

            import_item = menu.Append(wx.ID_ANY, _("Import OPML Here..."))
            self.Bind(wx.EVT_MENU, lambda e: self.on_import_opml(e, target_category=cat_title), import_item)

            export_item = menu.Append(wx.ID_ANY, _("Export Category to OPML..."))
            self.Bind(wx.EVT_MENU, lambda e: self.on_export_category_opml(e, category_title=cat_title), export_item)
            
        elif data["type"] == "feed":
            feed_id = str(data.get("id") or "").strip()
            refresh_feed_item = menu.Append(
                wx.ID_ANY, self._shortcut_menu_label(_("Refresh Feed"), "feeds.refresh_selected"))
            self.Bind(wx.EVT_MENU, self.on_refresh_single_feed, refresh_feed_item)

            feed_title = str(getattr((getattr(self, "feed_map", {}) or {}).get(feed_id), "title", "") or "").strip()
            mark_feed_read_prompt = (
                _('Mark all items in "{feed}" as read?').format(feed=feed_title) if feed_title
                else _("Mark all items in this feed as read?")
            )
            mark_feed_read_item = menu.Append(wx.ID_ANY, _("Mark All Items as Read"))
            self.Bind(
                wx.EVT_MENU,
                lambda e, fid=feed_id, prompt=mark_feed_read_prompt: self._confirm_and_mark_all_read(fid, prompt),
                mark_feed_read_item,
            )

            edit_item = menu.Append(
                wx.ID_ANY, self._shortcut_menu_label(_("Edit Feed..."), "feeds.edit_selected"))
            self.Bind(wx.EVT_MENU, self.on_edit_feed, edit_item)

            try:
                if bool(getattr(self.provider, "supports_feed_title_reset", lambda: False)()):
                    reset_title_item = menu.Append(wx.ID_ANY, _("Reset Title to Feed Default"))
                    self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self.on_reset_feed_title(e, fid), reset_title_item)
            except Exception:
                pass

            copy_url_item = menu.Append(wx.ID_ANY, _("Copy Feed URL"))
            self.Bind(wx.EVT_MENU, self.on_copy_feed_url, copy_url_item)

            notifications_item = menu.AppendCheckItem(wx.ID_ANY, _("Notifications for This Feed"))
            notifications_item.Check(self._is_feed_notifications_enabled(feed_id))
            self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self.on_toggle_feed_notifications(e, fid), notifications_item)

            # Per-feed image alt-text override (inherit global / always / never).
            try:
                from core.db import get_feed_show_images
                current_override = get_feed_show_images(feed_id)
            except Exception:
                current_override = None
            images_menu = wx.Menu()
            inherit_item = images_menu.AppendRadioItem(wx.ID_ANY, _("Use default setting"))
            always_item = images_menu.AppendRadioItem(wx.ID_ANY, _("Always show image alt text"))
            never_item = images_menu.AppendRadioItem(wx.ID_ANY, _("Never show image alt text"))
            inherit_item.Check(current_override is None)
            always_item.Check(current_override is True)
            never_item.Check(current_override is False)
            self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self.on_set_feed_images(fid, None), inherit_item)
            self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self.on_set_feed_images(fid, True), always_item)
            self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self.on_set_feed_images(fid, False), never_item)
            menu.AppendSubMenu(images_menu, _("Image Alt Text"))

            remove_item = menu.Append(wx.ID_ANY, _("Remove Feed"))
            self.Bind(wx.EVT_MENU, self.on_remove_feed, remove_item)

        elif data["type"] == "smart_root":
            new_item = menu.Append(wx.ID_ANY, _("New Smart Folder..."))
            self.Bind(wx.EVT_MENU, lambda e: self.on_new_smart_folder(), new_item)

        elif data["type"] == "smart":
            smart_id = data.get("smart_id")
            edit_item = menu.Append(wx.ID_ANY, _("Edit Smart Folder..."))
            self.Bind(wx.EVT_MENU, lambda e, sid=smart_id: self.on_edit_smart_folder(sid), edit_item)
            delete_item = menu.Append(wx.ID_ANY, _("Delete Smart Folder"))
            self.Bind(wx.EVT_MENU, lambda e, sid=smart_id: self.on_delete_smart_folder(sid), delete_item)
            new_item = menu.Append(wx.ID_ANY, _("New Smart Folder..."))
            self.Bind(wx.EVT_MENU, lambda e: self.on_new_smart_folder(), new_item)

        # "Show Only Unread" is global, so it lives in the View menu instead of
        # here (issue #40) — a per-item context entry misled users into thinking
        # the filter was scoped to the clicked feed or category.

        if menu.GetMenuItemCount() > 0:
            apply_menu_mnemonics(menu)
            self.tree.PopupMenu(menu, menu_pos)
        menu.Destroy()

    @property
    def _unread_filter_enabled(self) -> bool:
        # Compatibility shim over the three-state filter (issue #36).
        return getattr(self, "_article_read_filter", "all") == "unread"

    @_unread_filter_enabled.setter
    def _unread_filter_enabled(self, value) -> None:
        self._article_read_filter = "unread" if value else "all"

    def on_change_article_filter(self, mode: str):
        mode = str(mode or "all").lower()
        if mode not in ("all", "unread", "read"):
            mode = "all"
        if mode == getattr(self, "_article_read_filter", "all"):
            return
        self._article_read_filter = mode
        self._sync_unread_filter_menu_check()
        # Rebuild the tree (hides branches with no matching articles when the
        # filter is active) and reload the current view with the new filter.
        # _update_tree ends by reloading the selected view's articles.
        self.refresh_feeds()

    def _sync_unread_filter_menu_check(self) -> None:
        items = getattr(self, "_article_filter_menu_items", None) or {}
        item = items.get(getattr(self, "_article_read_filter", "all"))
        if item is not None:
            try:
                item.Check(True)
            except Exception:
                pass

    def on_change_media_filter(self, mode: str):
        mode = str(mode or "all").lower()
        if mode not in ("all", "with", "without"):
            mode = "all"
        if mode == getattr(self, "_article_media_filter", "all"):
            return
        self._article_media_filter = mode
        self._sync_media_filter_menu_check()
        # Client-side filter over the already-loaded view: re-render the current
        # list with the new filter. No provider refetch or tree rebuild needed.
        try:
            self._refresh_articles_for_sort_change()
        except Exception:
            log.exception("Failed to re-render after media filter change")

    def _sync_media_filter_menu_check(self) -> None:
        items = getattr(self, "_article_media_filter_menu_items", None) or {}
        item = items.get(getattr(self, "_article_media_filter", "all"))
        if item is not None:
            try:
                item.Check(True)
            except Exception:
                pass

    def on_manage_filter_rules(self, event=None):
        if not getattr(self.provider, "supports_filter_rules", lambda: False)():
            wx.MessageBox(
                _("The current provider does not support filter rules."),
                _("Not Supported"),
                wx.ICON_INFORMATION,
            )
            return
        dlg = FilterRulesDialog(self, self.provider)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        # Rules may have moved/labeled/deleted articles; refresh the tree + list.
        try:
            self.refresh_feeds()
            self._reload_selected_articles()
        except Exception:
            log.debug("Failed to refresh views after managing filter rules", exc_info=True)

    def on_new_smart_folder(self):
        if not getattr(self.provider, "supports_smart_folders", lambda: False)():
            return
        dlg = SmartFolderDialog(self)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                name, rule = dlg.get_result()
                try:
                    self.provider.create_smart_folder(name, rule)
                except Exception:
                    log.exception("Error creating smart folder")
                    wx.MessageBox(_("Could not create the Smart Folder."), _("Error"), wx.ICON_ERROR)
                    return
                self.refresh_feeds()
        finally:
            dlg.Destroy()

    def on_edit_smart_folder(self, smart_id):
        if not smart_id:
            return
        try:
            from core.db import get_smart_folder
            folder = get_smart_folder(smart_id)
        except Exception:
            folder = None
        if not folder:
            return
        dlg = SmartFolderDialog(self, name=folder.get("name"), rule=folder.get("rule"))
        try:
            if dlg.ShowModal() == wx.ID_OK:
                name, rule = dlg.get_result()
                try:
                    self.provider.update_smart_folder(smart_id, name=name, rule=rule)
                except Exception:
                    log.exception("Error updating smart folder")
                    wx.MessageBox(_("Could not update the Smart Folder."), _("Error"), wx.ICON_ERROR)
                    return
                self.refresh_feeds()
        finally:
            dlg.Destroy()

    def on_delete_smart_folder(self, smart_id):
        if not smart_id:
            return
        try:
            from core.db import get_smart_folder
            folder = get_smart_folder(smart_id)
        except Exception:
            folder = None
        name = (folder or {}).get("name") or _("this Smart Folder")
        if wx.MessageBox(
            _('Delete Smart Folder "{name}"? Your articles are not affected.').format(name=name),
            _("Delete Smart Folder"),
            wx.YES_NO | wx.ICON_QUESTION,
        ) != wx.YES:
            return
        try:
            self.provider.delete_smart_folder(smart_id)
        except Exception:
            log.exception("Error deleting smart folder")
        if getattr(self, "current_feed_id", "") == f"smart:{smart_id}":
            try:
                self._select_view("all")
            except Exception:
                pass
        self.refresh_feeds()

    def on_list_context_menu(self, event):
        pos = event.GetPosition()
        idx = self._get_selected_article_index()
        
        menu_pos = wx.DefaultPosition
        
        if pos == wx.DefaultPosition: # Keyboard event
            if idx == wx.NOT_FOUND:
                idx = self.list_ctrl.GetFocusedItem()
            if idx != wx.NOT_FOUND:
                rect = self.list_ctrl.GetItemRect(idx)
                menu_pos = rect.GetPosition() # Use item's top-left corner relative to list control
            else:
                size = self.list_ctrl.GetSize()
                menu_pos = wx.Point(size.width // 2, size.height // 2)
        else: # Mouse event
            menu_pos = pos
            try:
                hit = self.list_ctrl.HitTest(pos)
                hit_idx = hit[0] if isinstance(hit, tuple) else hit
                if hit_idx != wx.NOT_FOUND:
                    idx = int(hit_idx)
                    # Right-clicking a row outside the current selection collapses to
                    # just that row; right-clicking inside a multi-selection keeps it.
                    if not self.list_ctrl.IsSelected(idx):
                        self._clear_list_selection()
                        self.list_ctrl.Select(idx)
                    self.list_ctrl.Focus(idx)
            except Exception:
                pass

        if idx == wx.NOT_FOUND and pos == wx.DefaultPosition:
            # If keyboard trigger and no item focused, don't show menu
            return

        valid_article_idx = idx != wx.NOT_FOUND and 0 <= idx < len(self.current_articles) and not self._is_load_more_row(idx)

        # When the clicked/focused row is part of a multi-selection, bulk actions
        # (delete, copy, mark read/unread) act on the whole selection. Otherwise
        # they act on just this row.
        sel_indices = self._get_selected_article_indices()
        if valid_article_idx and idx in sel_indices and len(sel_indices) > 1:
            menu_indices = list(sel_indices)
        elif valid_article_idx:
            menu_indices = [idx]
        else:
            menu_indices = []
        count = len(menu_indices)
        multi = count > 1
        in_deleted_view = self._is_deleted_view(getattr(self, "current_feed_id", "") or "")

        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("Open Article"))
        open_browser_item = menu.Append(
            wx.ID_ANY, self._shortcut_menu_label(_("Open in Default Browser"), "article.open_browser"))
        menu.AppendSeparator()
        if multi:
            mark_read_item = menu.Append(wx.ID_ANY, _("Mark {count} as &Read").format(count=count))
            mark_unread_item = menu.Append(wx.ID_ANY, _("Mark {count} as &Unread").format(count=count))
        else:
            mark_read_item = menu.Append(wx.ID_ANY, _("Mark as &Read"))
            mark_unread_item = menu.Append(wx.ID_ANY, _("Mark as &Unread"))
        delete_item = None
        if (
            valid_article_idx
            and not in_deleted_view
            and self._supports_article_delete()
        ):
            delete_label = (
                _("Delete {count} Articles\tDel").format(count=count)
                if multi
                else _("Delete Article\tDel")
            )
            delete_item = menu.Append(wx.ID_ANY, delete_label)
        elif valid_article_idx and in_deleted_view and self._supports_purge_deleted():
            delete_label = (
                _("Delete {count} Articles Permanently\tDel").format(count=count)
                if multi
                else _("Delete Article Permanently\tDel")
            )
            delete_item = menu.Append(wx.ID_ANY, delete_label)
        restore_item = None
        if valid_article_idx and in_deleted_view and self._supports_restore_deleted():
            restore_label = (
                _("Restore {count} Articles").format(count=count)
                if multi
                else _("Restore Article")
            )
            restore_item = menu.Append(wx.ID_ANY, restore_label)
        menu.AppendSeparator()
        copy_item = menu.Append(
            wx.ID_ANY,
            _("Copy Links") if multi
            else self._shortcut_menu_label(_("Copy Link"), "article.copy_link"))
        download_item = None
        if valid_article_idx:
            article_for_menu = self.current_articles[idx]
            copy_text_label = (
                _("Copy Text ({count} articles)").format(count=count)
                if multi
                else self._shortcut_menu_label(_("Copy Text"), "article.copy_text")
            )
            copy_text_item = menu.Append(wx.ID_ANY, copy_text_label)
            self.Bind(wx.EVT_MENU, lambda e, ii=list(menu_indices): self.on_copy_texts(ii), copy_text_item)
            view_description_item = menu.Append(wx.ID_ANY, _("View Feed Description..."))
            self.Bind(wx.EVT_MENU, lambda e, i=idx: self.on_view_feed_description(i), view_description_item)
            if article_for_menu.media_url:
                # Only offer "Copy Media Link" when media_url is a genuine direct
                # media file. yt-dlp page items (YouTube, etc.) store the
                # watch-page URL as media_url and have no single combined
                # audio+video direct link, so copying it would just duplicate
                # "Copy Link" or hand out a split/expiring stream.
                if self._has_direct_media_link(article_for_menu):
                    copy_audio_item = menu.Append(
                        wx.ID_ANY, self._shortcut_menu_label(_("Copy Media Link"), "article.copy_media_link"))
                    self.Bind(wx.EVT_MENU, lambda e, i=idx: self.on_copy_media_link(i), copy_audio_item)
                download_item = menu.Append(
                    wx.ID_ANY, self._shortcut_menu_label(_("Download"), "article.download"))
                self.Bind(wx.EVT_MENU, lambda e, a=article_for_menu: self.on_download_article(a), download_item)
                download_as_item = menu.Append(
                    wx.ID_ANY, self._shortcut_menu_label(_("Download As..."), "article.download_as"))
                self.Bind(wx.EVT_MENU, lambda e, a=article_for_menu: self.on_download_article_as(a), download_as_item)
            else:
                detect_audio_item = menu.Append(wx.ID_ANY, _("Detect Audio"))
                self.Bind(wx.EVT_MENU, lambda e, a=article_for_menu: self.on_detect_audio(a), detect_audio_item)
            try:
                if utils.content_has_images(getattr(article_for_menu, "content", "")):
                    copy_image_item = menu.Append(wx.ID_ANY, _("Copy Image Link"))
                    self.Bind(wx.EVT_MENU, lambda e, i=idx: self.on_copy_image_link(i), copy_image_item)
            except Exception:
                pass

            # Play queue: offer add/remove for playable media items.
            try:
                playable_targets = [
                    i for i in menu_indices
                    if 0 <= i < len(self.current_articles)
                    and self._should_play_in_player(self.current_articles[i])
                ]
            except Exception:
                playable_targets = []
            # Add/remove queue actions only make sense for playable media, but
            # "Open Play Queue..." must be reachable from any article's context
            # menu (not just media ones) so the queue can be opened from anywhere.
            menu.AppendSeparator()
            if playable_targets:
                if multi:
                    add_q_item = menu.Append(
                        wx.ID_ANY, _("Add {count} to Play Queue").format(count=len(playable_targets))
                    )
                    self.Bind(
                        wx.EVT_MENU,
                        lambda e, ii=list(playable_targets): self.add_articles_to_queue(ii),
                        add_q_item,
                    )
                    remove_q_item = menu.Append(
                        wx.ID_ANY, _("Remove {count} from Play Queue").format(count=len(playable_targets))
                    )
                    self.Bind(
                        wx.EVT_MENU,
                        lambda e, ii=list(playable_targets): self.remove_articles_from_queue(ii),
                        remove_q_item,
                    )
                else:
                    if self._is_article_in_queue(article_for_menu):
                        rm_q_item = menu.Append(wx.ID_ANY, _("Remove from Play Queue"))
                        self.Bind(
                            wx.EVT_MENU,
                            lambda e, i=idx: self.remove_articles_from_queue([i]),
                            rm_q_item,
                        )
                    else:
                        add_q_item = menu.Append(wx.ID_ANY, _("Add to Play Queue"))
                        self.Bind(
                            wx.EVT_MENU,
                            lambda e, i=idx: self.add_articles_to_queue([i]),
                            add_q_item,
                        )
            open_q_item = menu.Append(wx.ID_ANY, _("Open Play Queue..."))
            self.Bind(wx.EVT_MENU, self.on_open_play_queue, open_q_item)

            chapter_links = (
                self._article_chapter_links(article_for_menu)
                if getattr(article_for_menu, "chapters", None)
                else []
            )
            if chapter_links:
                chapter_links_menu = wx.Menu()
                for chapter, href in chapter_links:
                    label = _("Open {chapter}").format(
                        chapter=self._format_player_chapter_menu_label(chapter)
                    )
                    item = chapter_links_menu.Append(wx.ID_ANY, label)
                    self.Bind(
                        wx.EVT_MENU,
                        lambda e, chapter_href=href: self.on_open_chapter_link(chapter_href),
                        item,
                    )
                menu.AppendSubMenu(chapter_links_menu, _("Chapter Links"))

            try:
                if getattr(self.provider, "supports_favorites", lambda: False)() and hasattr(self, "_toggle_favorite_id"):
                    label = (
                        _("Remove from Favorites")
                        if getattr(article_for_menu, "is_favorite", False)
                        else _("Add to Favorites")
                    )
                    menu.Append(
                        int(self._toggle_favorite_id),
                        self._shortcut_menu_label(label, "article.toggle_favorite"),
                    )
            except Exception:
                pass

            try:
                if not in_deleted_view and self._article_has_history(article_for_menu):
                    history_item = menu.Append(wx.ID_ANY, _("View History..."))
                    self.Bind(
                        wx.EVT_MENU,
                        lambda e, a=article_for_menu: self.on_view_article_history(a),
                        history_item,
                    )
            except Exception:
                pass
        
        # Bindings for list menu items need to use the current idx or selected article
        # on_article_activate (event) needs an event object, but I can re-create one or just call its core logic
        # For simplicity, pass idx to lambda
        mark_targets = list(menu_indices) if menu_indices else ([idx] if valid_article_idx else [])
        self.Bind(wx.EVT_MENU, lambda e: self.on_article_activate(event=self._make_list_activate_event(idx)), open_item)
        self.Bind(wx.EVT_MENU, lambda e: self.on_open_in_browser(idx), open_browser_item)
        self.Bind(wx.EVT_MENU, lambda e, ii=list(mark_targets): self._mark_indices(ii, True), mark_read_item)
        self.Bind(wx.EVT_MENU, lambda e, ii=list(mark_targets): self._mark_indices(ii, False), mark_unread_item)
        if delete_item is not None:
            self.Bind(wx.EVT_MENU, lambda e: self.on_delete_article(), delete_item)
        if restore_item is not None:
            self.Bind(wx.EVT_MENU, lambda e, ii=list(menu_indices): self.on_restore_articles(ii), restore_item)
        self.Bind(wx.EVT_MENU, lambda e, ii=list(mark_targets): self.on_copy_links(ii), copy_item)

        if not valid_article_idx:
            # No target article (empty list or non-article row): keep the
            # article actions visible but grayed out so screen readers
            # announce them as unavailable instead of silently doing nothing.
            for article_item in (
                open_item,
                open_browser_item,
                mark_read_item,
                mark_unread_item,
                copy_item,
            ):
                article_item.Enable(False)

        apply_menu_mnemonics(menu)
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

    def _article_copy_url(self, article) -> str:
        """The URL "Copy Link" should hand out for an article.

        Normally the article's web link — but podcast feeds often point every
        episode's <link> at the show's homepage (e.g. Simplecast feeds where
        each item links to the site root). Copying that gives the same useless
        URL for every episode, so when the link is a bare homepage (or missing)
        and the item carries a direct media enclosure, copy the audio URL —
        the one the user can actually play elsewhere.
        """
        url = str(getattr(article, "url", "") or "").strip()
        if self._has_direct_media_link(article) and (not url or utils.is_bare_site_root(url)):
            return str(getattr(article, "media_url", "") or "").strip()
        return url

    def on_copy_link(self, idx):
        if 0 <= idx < len(self.current_articles):
            url = self._article_copy_url(self.current_articles[idx])
            if url:
                self._copy_to_clipboard(url)

    def on_copy_links(self, indices):
        """Copy the URLs of the given articles, one per line."""
        urls = []
        for idx in list(indices or []):
            if 0 <= idx < len(self.current_articles):
                url = self._article_copy_url(self.current_articles[idx])
                if url:
                    urls.append(url)
        if urls:
            self._copy_to_clipboard("\n".join(urls))

    def _has_direct_media_link(self, article) -> bool:
        """True only when the article's media_url is a direct, copyable media file.

        yt-dlp page items (YouTube, etc.) store the watch-page URL as media_url;
        those have no single combined audio+video direct link, so they are not
        treated as having a copyable media link (the menu hides "Copy Media Link"
        for them and downloads route through yt-dlp instead).
        """
        media_url = str(getattr(article, "media_url", "") or "").strip()
        if not media_url:
            return False
        article_link = str(getattr(article, "url", "") or "").strip()
        if media_url == article_link:
            return False
        try:
            if core.discovery.is_ytdlp_supported(media_url):
                return False
        except Exception:
            pass
        return True

    def on_copy_media_link(self, idx):
        if 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            media_url = getattr(article, "media_url", None)
            if media_url and wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(media_url))
                wx.TheClipboard.Flush()
                wx.TheClipboard.Close()

    def _copy_to_clipboard(self, text: str) -> None:
        text = str(text or "")
        if not text:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Flush()
            wx.TheClipboard.Close()

    def on_copy_text(self, idx):
        """Copy the article text shown in the reading pane.

        Prefers the already-extracted full text (the same text the article view
        shows once extraction or background prefetch has run) and includes the
        title/author header; falls back to the feed content with the same header
        the pane uses before extraction completes.
        """
        if 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            self._copy_to_clipboard(self._compose_article_copy_text(article, idx))

    def on_copy_texts(self, indices):
        """Copy the readable text of several articles, separated by a divider."""
        parts = []
        for idx in list(indices or []):
            if 0 <= idx < len(self.current_articles):
                article = self.current_articles[idx]
                parts.append(self._compose_article_copy_text(article, idx))
        if parts:
            separator = "\n\n" + ("=" * 40) + "\n\n"
            self._copy_to_clipboard(separator.join(parts))

    def on_view_feed_description(self, idx=None):
        if idx is None:
            idx = self._get_selected_article_index()
        if idx is None or idx < 0 or idx >= len(self.current_articles):
            return

        article = self.current_articles[idx]
        description = self._article_description_text(article)
        if not description:
            description = _("No feed description is available for this item.")

        dlg = wx.Dialog(self, title=_("Feed Description"), size=(720, 520))

        def _on_char_hook(event):
            try:
                if event.GetKeyCode() == wx.WXK_ESCAPE:
                    dlg.EndModal(wx.ID_CLOSE)
                    return
            except Exception:
                pass
            event.Skip()
        dlg.Bind(wx.EVT_CHAR_HOOK, _on_char_hook)

        try:
            sizer = wx.BoxSizer(wx.VERTICAL)
            title = str(getattr(article, "title", "") or _("Feed description"))
            title_lbl = wx.StaticText(dlg, label=title)
            sizer.Add(title_lbl, 0, wx.ALL | wx.EXPAND, 8)

            desc_ctrl = wx.TextCtrl(
                dlg,
                value=description,
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
            )
            desc_ctrl.SetName(_("Feed description"))
            sizer.Add(desc_ctrl, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

            btns = wx.BoxSizer(wx.HORIZONTAL)
            copy_btn = wx.Button(dlg, label=_("Copy"))
            close_btn = wx.Button(dlg, id=wx.ID_CLOSE, label=_("Close"))
            btns.Add(copy_btn, 0, wx.RIGHT, 8)
            btns.Add(close_btn, 0)
            sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            copy_btn.Bind(wx.EVT_BUTTON, lambda _event: self._copy_to_clipboard(description))
            close_btn.Bind(wx.EVT_BUTTON, lambda _event: dlg.EndModal(wx.ID_CLOSE))

            dlg.SetSizer(sizer)
            dlg.CentreOnParent()
            try:
                desc_ctrl.SetInsertionPoint(0)
                wx.CallAfter(desc_ctrl.SetFocus)
            except Exception:
                pass
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _compose_article_reader_text(self, base_text: str, article=None, chapters=None) -> str:
        """Compose the reader text without letting chapter sections get lost or duplicated."""
        text = str(base_text or "")
        chapter_list = list(
            chapters if chapters is not None else (getattr(article, "chapters", None) or [])
        )
        if not chapter_list:
            return text
        chapter_text = self._format_article_chapters_text(chapter_list)
        if text.rstrip().endswith(chapter_text.strip()):
            return text
        return text.rstrip() + chapter_text

    def _create_article_text_control(self):
        """Create the native reader with every accessibility/key binding."""
        ctrl = wx.TextCtrl(
            self.reader_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        ctrl.SetName(_("Article text"))
        ctrl.Bind(wx.EVT_SET_FOCUS, self.on_content_focus)
        ctrl.Bind(wx.EVT_TEXT_COPY, self.on_content_copy)
        ctrl.Bind(wx.EVT_CONTEXT_MENU, self.on_content_context_menu)
        ctrl.Bind(wx.EVT_KEY_DOWN, self.on_content_key_down)
        ctrl.Bind(wx.EVT_RIGHT_UP, self.on_content_right_up)
        return ctrl

    def _swap_focused_large_reader(self, displayed: str, reset_insertion: bool) -> bool:
        """Expose a fully populated RichEdit to NVDA in one focus transition."""
        if not sys.platform.startswith("win") or len(displayed) < LARGE_READER_TEXT_CHARS:
            return False
        # new.SetFocus() below delivers EVT_SET_FOCUS synchronously, and
        # on_content_focus re-enters _set_article_reader_text through the
        # full-text cache-hit path. Left unguarded that re-entry starts another
        # swap, and so on without bound, until the recursion unwinds through the
        # handlers here and strands a stale control on screen (issue #91).
        if getattr(self, "_reader_swap_active", False):
            return False
        old = self.content_ctrl
        new = None
        swapped = False
        self._reader_swap_active = True
        try:
            if wx.Window.FindFocus() is not old or not old.IsShown():
                return False
            selection = old.GetSelection()
            insertion = old.GetInsertionPoint()
            new = self._create_article_text_control()
            new.Hide()
            new.ChangeValue(displayed)
            end = len(displayed)
            if reset_insertion:
                new.SetInsertionPoint(0)
            elif selection is not None:
                new.SetSelection(min(selection[0], end), min(selection[1], end))
            else:
                new.SetInsertionPoint(min(insertion, end))
            if not self._reader_sizer.Replace(old, new):
                new.Destroy()
                return False
            swapped = True
            self.content_ctrl = new
            self._update_search_tab_order()
            new.Show()
            self.reader_panel.Layout()
            new.SetFocus()
            old.Hide()
            wx.CallAfter(old.Destroy)
            return True
        except Exception:
            log.debug("Large reader control swap failed", exc_info=True)
            # Undo a half-applied swap. Leaving it in place keeps the old
            # control visible and parented while content_ctrl points at the new
            # one, so every later write lands on a control the user cannot see
            # and the reader stays frozen on this article until the app is
            # restarted (issue #91).
            try:
                if swapped and new is not None and self._reader_sizer.Replace(new, old):
                    self.content_ctrl = old
                    old.Show()
                    self._update_search_tab_order()
                    self.reader_panel.Layout()
                if new is not None and new is not self.content_ctrl:
                    new.Destroy()
            except Exception:
                log.debug("Large reader swap rollback failed", exc_info=True)
            return False
        finally:
            self._reader_swap_active = False

    def _set_article_reader_text(self, article, base_text: str, *, reset_insertion: bool = False) -> str:
        """Set the main reader from chapter-free base text and return the displayed text."""
        displayed = self._compose_article_reader_text(base_text, article=article)
        try:
            same_tracked_text = getattr(self, "_reader_displayed_text", None) == displayed
            if same_tracked_text and self.content_ctrl.GetLastPosition() == len(displayed):
                if reset_insertion:
                    self.content_ctrl.SetInsertionPoint(0)
                return displayed
            # Record before swapping, not after: _swap_focused_large_reader
            # installs a control that already holds this text and then moves
            # focus to it, which re-enters this method synchronously. The
            # re-entrant call has to see the memo to stop here (issue #91).
            self._reader_displayed_text = displayed
            swapper = getattr(self, "_swap_focused_large_reader", None)
            if callable(swapper) and swapper(displayed, reset_insertion):
                return displayed
            changed = replace_text_control_value(self.content_ctrl, displayed)
            if changed:
                # An accidental right-Ctrl+Shift flips RichEdit to RTL reading
                # order and articles suddenly display right-to-left; re-render
                # always resets the reader to LTR.
                force_ltr_reading(self.content_ctrl)
            if reset_insertion and changed:
                self.content_ctrl.SetInsertionPoint(0)
        except Exception:
            # Never leave the memo asserting text the control may not hold; a
            # wrong "already displayed" answer skips the next write entirely.
            self._reader_displayed_text = None
            log.debug("Setting article reader text failed", exc_info=True)
        return displayed

    def _invalidate_reader_text_tracking(self) -> None:
        """Forget what the reader was last given, after a direct write to it.

        _set_article_reader_text skips the rewrite when asked for the text it
        last wrote. Anything that writes content_ctrl directly must clear that
        record, or the next request for the remembered text is skipped and the
        direct write stays on screen instead (issue #91).
        """
        self._reader_displayed_text = None

    # -- Rich (WebView) reader -------------------------------------------------

    def _rich_view_enabled(self) -> bool:
        """True when the user opted into the rich HTML reader in Settings."""
        try:
            return bool(self.config_manager.get("full_text_rich_view", False))
        except Exception:
            return False

    def _is_forum_thread_article(self, article) -> bool:
        """True when the article is a discussion thread whose feed carries only
        the opening post (audiogames / applevis), so the whole conversation is
        worth fetching on selection rather than waiting for reader focus."""
        url = str(getattr(article, "url", "") or "").strip()
        if not url:
            return False
        try:
            from core import article_extractor as ae

            return bool(ae._is_forum_thread_host(url))
        except Exception:
            return False

    def _is_youtube_video_article(self, article) -> bool:
        return _article_is_youtube_video(article)

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
            # The library defaults to lang="en", which is what made every
            # article claim to be English (issue #72). The skeleton is built
            # once and reused, so the root gets the UI language (rule 4, and the
            # right language for our own chrome); per-article content language
            # rides on the <article lang> that article_html emits.
            rv = AccessibleWebView(
                self.reader_panel,
                title=_("Article text"),
                lang=article_lang.app_ui_language(),
                live_region=False,
                open_links_externally=True,
                on_return=self._on_rich_view_return,
                on_message=self._on_rich_view_message,
            )
        except Exception:
            log.exception("Failed to create rich article view")
            self._rich_view_unavailable = True
            return None
        if not getattr(rv, "using_webview", False):
            # Degraded text fallback inside the library: prefer our own reader.
            self._rich_view_unavailable = True
            try:
                rv.control.Destroy()
            except Exception:
                pass
            return None
        self._rich_view = rv
        # Native WebView2 swallows ALT (and F6/Shift+F6/Shift+Tab) before wx sees
        # them, so the menu bar and pane navigation are unreachable while the rich
        # reader is focused. We bridge those keys out of the page through the
        # WebView library's own script-message channel (window.awv -> on_message)
        # and act on them here; ALT posts the native menu-bar signal
        # (WM_SYSCOMMAND / SC_KEYMENU). See _RICH_VIEW_KEYS_JS / _on_rich_view_message.
        self._reader_sizer.Add(rv.control, 1, wx.EXPAND)
        rv.control.Hide()
        try:
            rv.control.Bind(wx.EVT_SET_FOCUS, self._on_rich_view_focus)
        except Exception:
            pass
        # Inject the in-page key bridge now and on every (re)load; set_content
        # swaps innerHTML and keeps document-level listeners, so one install
        # persists, but re-injecting is idempotent (guarded in JS).
        try:
            import wx.html2 as _webview2
            rv.view.Bind(_webview2.EVT_WEBVIEW_LOADED, self._on_rich_view_loaded)
        except Exception:
            pass
        self._inject_rich_view_keys()
        self.reader_panel.Layout()
        return rv

    # In-page key bridge for the rich reader. WebView2 hides these keys from wx,
    # so a document-level listener catches them and posts to window.awv (the
    # WebView library's message channel), handled in _on_rich_view_message.
    #   * bare ALT / F10 -> open the native menu bar
    #   * Shift+F6       -> focus the category tree
    #   * Shift+Tab at the top of the article -> focus the article list
    # (Plain F6 / Escape are already bridged to the article list by the library.)
    # Registered on `window` in the CAPTURE phase so it runs before the WebView
    # library's own (bubble-phase) F6/Escape bridge. For the keys we fully own we
    # call stopPropagation() so that bridge never also fires — notably Shift+F6,
    # which it would otherwise treat as a plain F6 (it ignores modifiers) and send
    # to the article list. Plain F6 / Escape are deliberately left to propagate,
    # so the library still returns focus to the list even if this inject fails.
    _RICH_VIEW_KEYS_JS = r"""
(function(){
  if(window.__blindrssKeys) return;
  window.__blindrssKeys = true;
  function content(){ return document.getElementById('content'); }
  function post(t){ try{ if(window.awv&&window.awv.postMessage){ window.awv.postMessage(JSON.stringify({type:t})); } }catch(e){} }
  var altAlone = false;
  window.addEventListener('keyup', function(e){
    if(e.key==='Alt'){ if(altAlone){ e.stopPropagation(); e.preventDefault(); post('__menu'); } altAlone=false; }
  }, true);
  window.addEventListener('keydown', function(e){
    if(e.key==='Alt' && !e.ctrlKey && !e.shiftKey && !e.metaKey){ altAlone=true; return; }
    altAlone = false;
    if(e.key==='F10' && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey){ e.stopPropagation(); e.preventDefault(); post('__menu'); return; }
    if(e.key==='F6' && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey){ e.stopPropagation(); e.preventDefault(); post('__focus_tree'); return; }
    if((e.key==='H'||e.key==='h'||e.code==='KeyH') && (e.ctrlKey||e.metaKey) && !(e.ctrlKey&&e.metaKey) && e.shiftKey && !e.altKey){ e.stopPropagation(); e.preventDefault(); post('__toggle_rich'); return; }
    if(e.key==='Tab' && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey){
      var c = content(); var a = document.activeElement;
      if(!c || a===c || a===document.body || a===null || !c.contains(a)){
        e.stopPropagation(); e.preventDefault(); post('__focus_list');
      }
    }
  }, true);
})();
"""

    def _inject_rich_view_keys(self) -> None:
        rv = getattr(self, "_rich_view", None)
        if rv is None or getattr(rv, "view", None) is None:
            return
        try:
            rv.view.RunScript(self._RICH_VIEW_KEYS_JS)
        except Exception:
            pass

    def _on_rich_view_loaded(self, event) -> None:
        try:
            event.Skip()
        except Exception:
            pass
        self._inject_rich_view_keys()

    def _on_rich_view_message(self, data) -> None:
        """Handle keys bridged out of the rich reader's WebView (see JS above)."""
        try:
            kind = data.get("type") if isinstance(data, dict) else None
        except Exception:
            kind = None
        if kind == "__menu":
            self._open_menu_bar_from_rich_view()
        elif kind == "__toggle_rich":
            # Ctrl+Shift+H inside the WebView: wx never sees the key, so the
            # menu accelerator can't fire; toggle directly instead.
            self.on_toggle_rich_view()
        elif kind == "__focus_tree":
            try:
                self.tree.SetFocus()
            except Exception:
                pass
        elif kind == "__focus_list":
            try:
                self.list_ctrl.SetFocus()
            except Exception:
                pass

    def _open_menu_bar_from_rich_view(self) -> None:
        """Open the native menu bar from the focused WebView (ALT/F10).

        Posts the exact signal ALT sends (WM_SYSCOMMAND / SC_KEYMENU, lparam 0)
        to the frame, entering Windows' native menu-bar keyboard loop with the
        first menu highlighted. Windows restores focus to the WebView when the
        menu closes. No-op off Windows (other WebView backends route ALT natively).
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.PostMessageW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.PostMessageW(self.GetHandle(), 0x0112, 0xF100, 0)
        except Exception:
            pass

    def _rich_view_active(self) -> bool:
        """True when the rich reader is the surface currently shown to the user."""
        return bool(self._rich_view_enabled() and self._ensure_rich_view() is not None)

    def _apply_reader_mode(self) -> bool:
        """Show the plain-text or rich reader per the setting; return True if rich."""
        use_rich = self._rich_view_active()
        try:
            if self._rich_view is not None:
                self._rich_view.control.Show(use_rich)
            self.content_ctrl.Show(not use_rich)
            self.reader_panel.Layout()
        except Exception:
            log.exception("Failed to switch reader mode")
        return use_rich

    def _reader_surface_focused(self) -> bool:
        """True when the keyboard focus is inside either reader surface.

        The WebView's real focus lives in a native child window wx knows nothing
        about, so wx.Window.FindFocus() returns None while the rich reader is
        focused; ask Windows directly in that case.
        """
        focus = self._get_focused_window()
        if focus is not None:
            if self._window_is_or_child(focus, getattr(self, "content_ctrl", None)):
                return True
            if self._is_rich_view_focused(focus):
                return True
        # macOS: while the WKWebView has keyboard focus, wx.Window.FindFocus()
        # is None and there is no user32 fallback, so "reading in the rich
        # view" was undetectable and toggling stranded focus on the hidden
        # surface. When the rich reader is the shown surface and wx sees no
        # focused window, treat the reader as focused.
        if sys.platform == "darwin" and focus is None:
            rv = getattr(self, "_rich_view", None)
            try:
                if rv is not None and rv.control.IsShown():
                    return True
            except Exception:
                pass
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetFocus()
            panel = self.reader_panel.GetHandle()
            return bool(hwnd) and (hwnd == panel or bool(user32.IsChild(panel, hwnd)))
        except Exception:
            return False

    def _focus_reader_surface(self) -> None:
        """Put focus on whichever reader surface is currently shown."""
        try:
            if self._rich_view_active() and self._rich_view is not None:
                # focus() (not control.SetFocus()) also moves the in-page focus
                # onto the content node; on macOS WKWebView plain SetFocus()
                # leaves the document unfocused, so VoiceOver never lands in
                # the article after a toggle.
                self._rich_view.focus()
            else:
                self.content_ctrl.SetFocus()
        except Exception:
            log.exception("Failed to focus the reader after a rich-view toggle")

    def _sync_rich_view_menu_item(self) -> None:
        """Reflect the current rich-view setting in the View-menu check item."""
        item = getattr(self, "_rich_view_menu_item", None)
        if item is None:
            return
        try:
            item.Check(self._rich_view_enabled())
        except Exception:
            pass

    def on_toggle_rich_view(self, event=None) -> None:
        """View menu / Ctrl+Shift+H: switch between plain full text and the rich view.

        The new value is derived from the stored setting, not the check item:
        a menu click pre-flips the item but the accelerator and the WebView key
        bridge do not, so IsChecked() means different things per path.
        _sync_rich_view_menu_item() re-syncs the item below either way.
        """
        new_val = not self._rich_view_enabled()
        # Whether the user was reading when they flipped this decides where focus
        # belongs afterwards; sample it before the surfaces are swapped.
        reading = self._reader_surface_focused()
        try:
            self.config_manager.set("full_text_rich_view", new_val)
        except Exception:
            log.exception("Failed to save rich-view toggle")
        self._apply_reader_mode()
        self._sync_rich_view_menu_item()
        # Re-render the selected article so the change is visible immediately.
        try:
            idx = self.list_ctrl.GetFirstSelected()
        except Exception:
            idx = -1
        if idx is not None and idx >= 0:
            self._fulltext_token += 1
            try:
                self._update_content_view(int(idx))
            except Exception:
                log.exception("Failed to refresh reader after rich-view toggle")
        # Toggling from inside the reader leaves focus on the surface we just
        # hid -- Windows restores it to the old WebView/text control when the
        # menu closes -- so the screen reader keeps reading the stale view until
        # the user tabs away and back. Hand focus to the new surface once the
        # menu's own focus restore has run.
        if reading:
            wx.CallAfter(self._focus_reader_surface)

    def _on_rich_view_return(self) -> None:
        """Escape/F6 inside the web view hands focus back to the article list."""
        try:
            self.list_ctrl.SetFocus()
        except Exception:
            pass

    def _on_rich_view_focus(self, event) -> None:
        """Focusing the web view mirrors on_content_focus: mark read + load full text."""
        try:
            event.Skip()
        except Exception:
            pass
        try:
            idx = self.list_ctrl.GetFirstSelected()
        except Exception:
            idx = -1
        if idx is None or idx < 0 or idx >= len(self.current_articles):
            idx = self._index_of_selected_article()
            if idx is None:
                return
        self.mark_article_read(idx)
        try:
            self._mark_article_opened(self.current_articles[idx])
        except Exception:
            pass
        self._schedule_rich_load_for_index(idx, force=True)

    def _render_rich_html(self, html_body: str) -> None:
        rv = self._ensure_rich_view()
        if rv is None:
            return
        try:
            set_accessible_webview_content(rv, html_body)
        except Exception:
            log.exception("Failed to set rich reader content")

    def _rich_feed_content_html(self, article) -> str:
        """Cleaned feed-content HTML shown instantly on selection (no network)."""
        url = str(getattr(article, "url", "") or "")
        title = str(getattr(article, "title", "") or "")
        author = str(getattr(article, "author", "") or "")
        date = utils.humanize_article_date(getattr(article, "date", "") or "")
        body = ""
        try:
            body = article_html.clean_article_html(
                getattr(article, "content", "") or "", url, use_traf_prune=False
            )
        except Exception:
            body = ""
        header = f"<h1>{html_stdlib.escape(title or url)}</h1>"
        meta = " · ".join(p for p in (date, author) if p)
        if meta:
            header += f'<p class="awv-meta">{html_stdlib.escape(meta)}</p>'
        if url:
            safe = html_stdlib.escape(url, quote=True)
            header += f'<p class="awv-source"><a href="{safe}">{html_stdlib.escape(url)}</a></p>'
        if not body:
            body = f"<p>{html_stdlib.escape(_('Loading full text...'))}</p>"
        # Instant feed-content view: no page was fetched, so the only language
        # signal is whatever the feed declared for this article (issue #72).
        lang = article_lang.resolve_content_language(
            feed_item_lang=getattr(article, "language", None),
            feed_lang=self._feed_language_for(getattr(article, "feed_id", None)),
        )
        safe_lang = html_stdlib.escape(lang, quote=True)
        return f'<article lang="{safe_lang}">{header}<hr>{body}</article>'

    def _feed_language_for(self, feed_id):
        """The feed's declared language, or None when it isn't known.

        Providers that expose a feed language set Feed.language; those that do
        not (the Miniflux API has no such field) simply yield None, and the
        resolver falls through to the UI language.
        """
        if not feed_id:
            return None
        try:
            feed = self.feed_map.get(feed_id)
        except Exception:
            return None
        return getattr(feed, "language", None) if feed else None

    def _schedule_rich_load_for_index(self, idx: int, force: bool = False) -> None:
        """Debounced full-text fetch + render into the rich web view."""
        if idx is None or idx < 0 or idx >= len(self.current_articles):
            return
        article = self.current_articles[idx]
        cache_key, url, _aid = self._fulltext_cache_key_for_article(article, idx)
        cached = self._fulltext_html_cache.get(cache_key)
        if cached is not None:
            self._render_rich_html(cached)
            return
        if getattr(self, "_rich_debounce", None) is not None:
            try:
                self._rich_debounce.Stop()
            except Exception:
                pass
            self._rich_debounce = None
        delay = 0 if force else int(getattr(self, "_fulltext_debounce_ms", 350))
        token = int(getattr(self, "_fulltext_token", 0))
        self._rich_debounce = wx.CallLater(delay, self._start_rich_load, idx, token)

    def _start_rich_load(self, idx: int, token: int) -> None:
        if token != int(getattr(self, "_fulltext_token", 0)):
            return
        if getattr(self, "selected_article_id", None):
            resolved = self._index_of_selected_article()
            if resolved is None:
                return
            idx = resolved
        if idx is None or idx < 0 or idx >= len(self.current_articles):
            return
        article = self.current_articles[idx]
        cache_key, url, article_id = self._fulltext_cache_key_for_article(article, idx)
        cached = self._fulltext_html_cache.get(cache_key)
        if cached is not None:
            self._render_rich_html(cached)
            return
        req = {
            "cache_key": cache_key,
            "url": url,
            "article_id": article_id,
            "fallback_html": getattr(article, "content", "") or "",
            "fallback_title": getattr(article, "title", "") or "",
            "fallback_author": getattr(article, "author", "") or "",
            "date": utils.humanize_article_date(getattr(article, "date", "") or ""),
            # Language signals for the <article lang> the renderer emits (#72).
            "feed_item_lang": getattr(article, "language", "") or "",
            "feed_lang": self._feed_language_for(getattr(article, "feed_id", None)) or "",
            "token": token,
        }
        threading.Thread(target=self._rich_load_worker, args=(req,), daemon=True).start()

    def _rich_load_worker(self, req: dict) -> None:
        html_body = None
        try:
            html_body = article_html.render_full_article_html(
                req.get("url", ""),
                fallback_html=req.get("fallback_html", ""),
                fallback_title=req.get("fallback_title", ""),
                fallback_author=req.get("fallback_author", ""),
                date=req.get("date", ""),
                feed_item_lang=req.get("feed_item_lang", ""),
                feed_lang=req.get("feed_lang", ""),
            )
        except Exception:
            log.debug("Rich full-text render failed", exc_info=True)
            html_body = None
        try:
            wx.CallAfter(self._apply_rich_result, req.get("cache_key", ""), html_body, req.get("token"))
        except Exception:
            pass

    def _apply_rich_result(self, cache_key: str, html_body, token) -> None:
        if html_body:
            self._fulltext_html_cache[cache_key] = html_body
        if token is not None and int(token) != int(getattr(self, "_fulltext_token", 0)):
            return
        if not html_body:
            return
        try:
            idx_now = self.list_ctrl.GetFirstSelected()
        except Exception:
            idx_now = -1
        if idx_now is None or idx_now < 0 or idx_now >= len(self.current_articles):
            idx_now = self._index_of_selected_article()
            if idx_now is None:
                return
        article_now = self.current_articles[idx_now]
        cur_key, _u, _a = self._fulltext_cache_key_for_article(article_now, idx_now)
        if cur_key != cache_key:
            return
        self._render_rich_html(html_body)
        self._announce_fulltext_loaded_macos()

    def _announce_fulltext_loaded_macos(self, authoritative: bool = True) -> None:
        """macOS only: announce what the async reader update delivered.

        On macOS the load starts on selection and the extracted text replaces
        the feed snippet silently a few seconds later; VoiceOver gives no cue,
        so users who already read the snippet conclude full text never loaded.
        Windows keeps its focus-triggered flow where the screen reader re-reads
        the control anyway, so this stays quiet there. ``authoritative`` False
        (total extraction failure, feed fallback shown) must not claim success.
        """
        if not sys.platform.startswith("darwin"):
            return
        message = (
            _("Full text loaded.")
            if authoritative
            else _("Full text unavailable. Showing feed content.")
        )
        try:
            self._announce_event("general", message)
        except Exception:
            pass

    def _compose_article_copy_text(self, article, idx) -> str:
        """Build the readable article text for copying, mirroring the reading pane."""
        # If the full text has already been extracted (on focus or via prefetch),
        # copy exactly what the pane shows — render_full_article already prefixes
        # a "Title:"/"Author:" header ahead of the complete body.
        try:
            cache_key, _url, _aid = self._fulltext_cache_key_for_article(article, idx)
            cached = self._fulltext_cache.get(cache_key)
        except Exception:
            cache_key = None
            cached = None
        if cached and str(cached).strip():
            return self._compose_article_reader_text(str(cached), article=article)
        # Rich reader: no plain-text extraction runs, so derive copy text from the
        # rendered rich HTML when available.
        if cache_key and self._rich_view_enabled():
            rich_html = self._fulltext_html_cache.get(cache_key)
            if rich_html:
                text = utils.collapse_blank_lines(utils.html_to_text(rich_html))
                if text and text.strip():
                    return self._compose_article_reader_text(text, article=article)

        # Not extracted yet: mirror the pre-extraction pane (title, date, author,
        # link header + cleaned feed content).
        include_images = self._show_images_for_feed(getattr(article, "feed_id", None))
        header = f"{getattr(article, 'title', '') or ''}\n"
        header += _("Date:") + f" {utils.humanize_article_date(getattr(article, 'date', ''))}\n"
        header += _("Author:") + f" {getattr(article, 'author', '') or ''}\n"
        header += _("Link:") + f" {getattr(article, 'url', '') or ''}\n"
        header += "-" * 40 + "\n\n"
        body = self._strip_html(getattr(article, "content", ""), include_images=include_images)
        return self._compose_article_reader_text(header + body, article=article)

    def _article_chapter_links(self, article) -> list[tuple[dict, str]]:
        """Return actionable HTTP(S) chapter links, resolving relative hrefs."""
        article_url = str(getattr(article, "url", "") or "")
        links = []
        for chapter in list(getattr(article, "chapters", None) or []):
            href = str(chapter.get("href", "") or "")
            if not href:
                continue
            if "\\" in href or any(
                ch.isspace() or ord(ch) < 32 or 127 <= ord(ch) <= 159
                for ch in href
            ):
                continue
            try:
                if urlsplit(href).scheme:
                    safe_url = self._validated_chapter_web_url(href)
                    if safe_url is not None:
                        links.append((chapter, safe_url))
                    continue
                resolved = urljoin(article_url, href)
            except Exception:
                continue
            safe_url = self._validated_chapter_web_url(resolved)
            if safe_url is not None:
                links.append((chapter, safe_url))
        return links

    def _validated_chapter_web_url(self, href: str) -> str | None:
        """Return a strict HTTP(S) chapter URL, or None when it is unsafe."""
        value = str(href or "")
        if not value or "\\" in value:
            return None
        if any(ch.isspace() or ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in value):
            return None
        try:
            parsed = urlsplit(value)
            if parsed.scheme.lower() not in ("http", "https"):
                return None
            if not parsed.hostname:
                return None
            if parsed.username is not None or parsed.password is not None:
                return None
            parsed.port
        except (TypeError, ValueError):
            return None
        return value

    def on_open_chapter_link(self, href: str) -> None:
        safe_url = self._validated_chapter_web_url(href)
        if safe_url is None:
            return
        try:
            webbrowser.open(safe_url)
        except Exception:
            log.debug("Failed to open chapter link", exc_info=True)

    def _content_links_enabled(self) -> bool:
        """True when the opt-in reader-pane link handling is turned on."""
        try:
            return bool(self.config_manager.get("article_structure_links", False))
        except Exception:
            return False

    def _find_url_at_content_position(self, text: str, pos: int) -> str | None:
        """Return the http(s) URL the reader cursor sits on, or the one on its line.

        The reader is a plain text control, so the URL is recovered from the
        rendered text itself (it is written inline as ``text (URL)``): first the
        link whose span contains the caret, otherwise the first link on the same
        line. This survives translation, chapter composition, and caching
        because nothing depends on stored character offsets.
        """
        if not text:
            return None
        try:
            pos = max(0, min(int(pos), len(text)))
        except Exception:
            return None
        # A caret resting just past a URL (very common after arrowing onto it)
        # should still resolve, so accept start <= pos <= end.
        for m in _CONTENT_URL_RE.finditer(text):
            if m.start() <= pos <= m.end():
                return _trim_recovered_url(m.group(0))
        line_start = text.rfind("\n", 0, pos) + 1
        line_end = text.find("\n", pos)
        if line_end == -1:
            line_end = len(text)
        m = _CONTENT_URL_RE.search(text[line_start:line_end])
        if m:
            return _trim_recovered_url(m.group(0))
        return None

    def _open_link_at_content_cursor(self) -> bool:
        """Open the link under the reader caret. Returns True if one was opened."""
        if not self._content_links_enabled():
            return False
        try:
            text = self.content_ctrl.GetValue()
            pos = self.content_ctrl.GetInsertionPoint()
        except Exception:
            return False
        url = self._find_url_at_content_position(text, pos)
        if not url:
            return False
        safe_url = self._validated_chapter_web_url(url)
        if safe_url is None:
            return False
        try:
            webbrowser.open(safe_url)
        except Exception:
            log.debug("Failed to open link from reader pane", exc_info=True)
            return False
        try:
            self._announce(_("Opening link."))
        except Exception:
            pass
        return True

    def on_copy_image_link(self, idx):
        """Copy the first image URL found in the article content, if any."""
        if 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            img_url = utils.first_image_url(getattr(article, "content", ""))
            if img_url:
                self._copy_to_clipboard(img_url)

    def on_detect_audio(self, article):
        if not article or not article.url:
            return
            
        wx.MessageBox(_("Scanning for audio... This may take a few seconds."), _("Detect Audio"), wx.ICON_INFORMATION)
        
        def _worker():
            try:
                murl, mtype = core.discovery.detect_media(article.url)
                if murl:
                    if hasattr(self.provider, "update_article_media"):
                        self.provider.update_article_media(article.id, murl, mtype)
                        article.media_url = murl
                        article.media_type = mtype
                        self._invalidate_article_media_label(article)

                        # Refresh UI for this item
                        wx.CallAfter(self._refresh_article_in_list, self._article_cache_id(article))
                        wx.CallAfter(
                            wx.MessageBox,
                            _("Audio detected and added!"),
                            _("Success"),
                            wx.ICON_INFORMATION,
                        )
                    else:
                         wx.CallAfter(wx.MessageBox, _("Provider does not support updating media."), _("Error"), wx.ICON_ERROR)
                else:
                    wx.CallAfter(wx.MessageBox, _("No audio found."), _("Result"), wx.ICON_INFORMATION)
            except Exception as e:
                wx.CallAfter(wx.MessageBox, _("Error detecting audio: {error}").format(error=e), _("Error"), wx.ICON_ERROR)
                
        threading.Thread(target=_worker, daemon=True).start()

    @staticmethod
    def _invalidate_article_media_label(article) -> None:
        """Drop the memoized Media-column label so it recomputes from current data.

        Must be called whenever an article gains (or loses) media after the
        label was first rendered — e.g. Detect Audio attaching an enclosure —
        otherwise the column stays stuck on the stale "No audio" text.
        """
        try:
            for attr in ("_media_label_cached", "_has_media_cached"):
                if hasattr(article, attr):
                    delattr(article, attr)
        except Exception:
            pass

    def _refresh_article_in_list(self, article_id):
        # Find item index
        idx = -1
        for i, a in enumerate(self.current_articles):
            if self._article_cache_id(a) == article_id:
                idx = i
                break

        if idx != -1:
            article = self.current_articles[idx]
            # Recompute and repaint the Media column for this row.
            self._invalidate_article_media_label(article)
            try:
                self._set_col(idx, article_columns.KEY_MEDIA, self._article_media_label(article))
            except Exception:
                pass
            # Update the cached view so if the user navigates away and back, it's there.
            self._update_cached_views_for_article(article)

    def _update_cached_views_for_article(self, article):
        try:
            with getattr(self, "_view_cache_lock", threading.Lock()):
                for st in (self.view_cache or {}).values():
                    for a in (st.get("articles") or []):
                        if self._article_cache_id(a) == self._article_cache_id(article):
                            a.media_url = article.media_url
                            a.media_type = article.media_type
                            self._invalidate_article_media_label(a)
        except Exception:
            pass

    def _sync_read_flag_in_cached_views(self, article_id: str, is_read: bool) -> None:
        """Copy a new read state onto the article's copies in other views.

        Each view caches its own Article objects, so marking an item read in
        "All Articles" left the same item looking unread in a cached category
        or feed view -- where an Unread Only filter would then keep showing it
        (issue #96).
        """
        try:
            with getattr(self, "_view_cache_lock", threading.Lock()):
                for st in (self.view_cache or {}).values():
                    for a in (st.get("articles") or []):
                        if self._article_cache_id(a) == article_id:
                            a.is_read = bool(is_read)
        except Exception:
            log.exception("Error syncing read flag in cached views")

    def _supports_favorites(self) -> bool:
        try:
            return bool(getattr(self.provider, "supports_favorites", lambda: False)())
        except Exception:
            log.exception("Error checking provider support for favorites")
            return False

    def _supports_article_delete(self) -> bool:
        try:
            return bool(getattr(self.provider, "supports_article_delete", lambda: False)())
        except Exception:
            log.exception("Error checking provider support for article deletion")
            return False

    def _is_feed_refresh_active(self) -> bool:
        try:
            locked = getattr(getattr(self, "_refresh_guard", None), "locked", None)
            return bool(locked()) if callable(locked) else False
        except Exception:
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

    def _get_selected_indices_raw(self) -> list[int]:
        """All currently selected row indices, in list order."""
        indices: list[int] = []
        try:
            i = self.list_ctrl.GetFirstSelected()
            while i != wx.NOT_FOUND:
                indices.append(i)
                i = self.list_ctrl.GetNextSelected(i)
        except Exception:
            log.exception("Error enumerating selected list rows")
            indices = []
        return indices

    def _get_selected_article_indices(self) -> list[int]:
        """Selected rows that map to real articles (excludes the Load More row)."""
        result: list[int] = []
        for i in self._get_selected_indices_raw():
            if i is None or i < 0 or i >= len(self.current_articles):
                continue
            if self._is_load_more_row(i):
                continue
            result.append(i)
        return result

    def _clear_list_selection(self) -> None:
        """Deselect every currently selected row."""
        for i in self._get_selected_indices_raw():
            try:
                self.list_ctrl.SetItemState(i, 0, wx.LIST_STATE_SELECTED)
            except Exception:
                pass

    def _mark_indices(self, indices, read: bool) -> None:
        """Mark each of the given article rows read/unread."""
        for idx in list(indices or []):
            try:
                if read:
                    self.mark_article_read(idx)
                else:
                    self.mark_article_unread(idx)
            except Exception:
                log.exception("Error marking article read/unread at index %s", idx)

    def _is_favorites_view(self, view_id: str) -> bool:
        view_id = view_id or ""
        return view_id.startswith("favorites:") or view_id.startswith("fav:")

    def _is_deleted_view(self, view_id: str) -> bool:
        view_id = view_id or ""
        return view_id == "deleted:all" or view_id.startswith("deleted:")

    def _supports_restore_deleted(self) -> bool:
        try:
            return bool(getattr(self.provider, "supports_restore_deleted", lambda: False)())
        except Exception:
            return False

    def _supports_purge_deleted(self) -> bool:
        try:
            return bool(getattr(self.provider, "supports_purge_deleted", lambda: False)())
        except Exception:
            return False

    def _mark_article_opened(self, article) -> None:
        """Record that the user opened/looked at a local article.

        This backs the Smart Folders "opened" criterion. The DB write is queued
        off the UI thread so refresh contention cannot freeze article navigation.
        """
        aid = getattr(article, "id", None) if article is not None else None
        feed_id = getattr(article, "feed_id", None) if article is not None else None
        if not aid or not feed_id:
            return
        try:
            if not bool(getattr(self.provider, "supports_smart_folders", lambda: False)()):
                return
        except Exception:
            return
        threading.Thread(
            target=MainFrame._mark_article_opened_worker,
            args=(str(aid), str(feed_id)),
            daemon=True,
        ).start()

    @staticmethod
    def _mark_article_opened_worker(article_id: str, feed_id: str) -> None:
        try:
            from core.db import mark_article_opened
            mark_article_opened(article_id, feed_id=feed_id)
        except Exception:
            log.exception("Error recording article opened time")

    def _article_has_history(self, article) -> bool:
        """True when an article has more than one recorded version (i.e. the feed
        changed it after first fetch), so 'View History...' is worth offering."""
        aid = getattr(article, "id", None) if article is not None else None
        if not aid:
            return False
        try:
            from core.db import count_article_versions
            return count_article_versions(aid) > 1
        except Exception:
            return False

    def on_view_article_history(self, article) -> None:
        """Show the full change history (all captured versions) of an article."""
        aid = getattr(article, "id", None) if article is not None else None
        if not aid:
            return
        try:
            from core.db import get_article_versions
            versions = get_article_versions(aid)
        except Exception:
            versions = []
        if not versions:
            wx.MessageBox(_("No change history for this article."), _("Article History"),
                          wx.OK | wx.ICON_INFORMATION, self)
            return

        total = len(versions)  # newest-first
        dlg = wx.Dialog(self, title=_("Article History"),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dlg.SetSize((720, 520))
        sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(
            dlg, label=_("{total} versions of: {title}").format(title=getattr(article, 'title', '') or '')
        )
        sizer.Add(heading, 0, wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        listbox = wx.ListBox(dlg, style=wx.LB_SINGLE)
        listbox.SetName(_("Versions"))
        for i, v in enumerate(versions):
            num = total - i  # highest number is the current version
            ts = v.get("captured_at") or 0
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts))) if ts else _("unknown time")
            suffix = _(" (current)") if i == 0 else (_(" (original)") if num == 1 else "")
            listbox.Append(_("Version {num} - {when}{suffix}").format(num=num, when=when, suffix=suffix))
        row.Add(listbox, 1, wx.EXPAND | wx.ALL, 8)

        text = wx.TextCtrl(dlg, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        text.SetName(_("Version content"))
        row.Add(text, 2, wx.EXPAND | wx.ALL, 8)
        sizer.Add(row, 1, wx.EXPAND)

        close_btn = wx.Button(dlg, wx.ID_CLOSE, _("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        dlg.SetSizer(sizer)
        try:
            dlg.SetEscapeId(wx.ID_CLOSE)
        except Exception:
            pass

        def _show_version(i):
            if 0 <= i < len(versions):
                v = versions[i]
                title = v.get("title") or ""
                try:
                    body = utils.html_to_text(v.get("content") or "")
                except Exception:
                    body = v.get("content") or ""
                text.SetValue(f"{title}\n\n{body}")
                text.SetInsertionPoint(0)

        listbox.Bind(wx.EVT_LISTBOX, lambda e: _show_version(listbox.GetSelection()))
        listbox.SetSelection(0)
        _show_version(0)
        listbox.SetFocus()

        dlg.ShowModal()
        dlg.Destroy()

    def _get_display_title(self, article) -> str:
        """Return an accessible article-list title, including chapter availability
        and, for media that has been played before, listened/remaining time so a
        screen-reader user hears it right after the title without opening the item.
        """
        title = article.title or ""
        suffix = ""
        try:
            suffix_fn = getattr(self, "_media_time_suffix", None)
            if callable(suffix_fn):
                suffix = suffix_fn(article) or ""
        except Exception:
            suffix = ""
        if suffix:
            title = f"{title}{suffix}"
        if getattr(article, "chapters", None):
            return f"{title}, " + _("Chapters available")
        return title

    @staticmethod
    def _format_media_time(ms) -> str:
        """Format milliseconds as m:ss or h:mm:ss (screen-reader friendly)."""
        try:
            total = int(max(0, int(ms or 0)) // 1000)
        except (TypeError, ValueError):
            total = 0
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def _refresh_playback_states_cache(self) -> None:
        """Reload the article->playback-state map used to annotate the list.

        One indexed scan of the small local playback_state table; cheap enough to
        run on each full list render so the annotations stay reasonably fresh.
        """
        try:
            from core import playback_state
            self._playback_states_cache = playback_state.get_all_playback_states()
        except Exception:
            self._playback_states_cache = {}

    def _playback_state_for_article(self, article):
        states = getattr(self, "_playback_states_cache", None)
        if not states:
            return None
        try:
            aid = getattr(article, "id", None)
            if aid is not None:
                st = states.get(f"article:{aid}")
                if st is not None:
                    return st
            for key in (getattr(article, "media_url", None), getattr(article, "url", None)):
                if key and key in states:
                    return states[key]
        except Exception:
            return None
        return None

    def _media_time_suffix(self, article) -> str:
        """Return a short ', listened/remaining' suffix for a played media item."""
        st = self._playback_state_for_article(article)
        if st is None:
            return ""
        try:
            dur = int(st.duration_ms or 0)
            pos = int(st.position_ms or 0)
            if getattr(st, "completed", False):
                if dur > 0:
                    return _(", played, {total}").format(total=self._format_media_time(dur))
                return _(", played")
            if dur > 0 and pos > 0:
                return _(", {position} of {total}").format(
                    position=self._format_media_time(pos), total=self._format_media_time(dur)
                )
            if dur > 0:
                return _(", {total}").format(total=self._format_media_time(dur))
            if pos > 0:
                return _(", {position} played").format(position=self._format_media_time(pos))
        except Exception:
            return ""
        return ""

    def _playback_time_annotation(self, st) -> str:
        """Short 'length, played position' text from a PlaybackState (or None).

        Shared by the article list's Media column and the Play Queue dialog so
        both read the same way under a screen reader: total length first (when
        known), then how much has been played, or 'not played' for untouched
        items. Length is only known after an item has been loaded at least
        once, since feeds do not reliably carry durations.
        """
        try:
            dur = int(getattr(st, "duration_ms", 0) or 0) if st is not None else 0
            pos = int(getattr(st, "position_ms", 0) or 0) if st is not None else 0
            completed = bool(getattr(st, "completed", False)) if st is not None else False
        except Exception:
            dur, pos, completed = 0, 0, False
        parts = []
        if dur > 0:
            parts.append(self._format_media_time(dur))
        if completed:
            parts.append(_("played"))
        elif pos > 0:
            parts.append(_("played {position}").format(position=self._format_media_time(pos)))
        else:
            parts.append(_("not played"))
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # Play queue (config-backed ordered list of media items)
    # ------------------------------------------------------------------

    def _get_play_queue(self) -> list:
        try:
            raw = self.config_manager.get("play_queue", [])
        except Exception:
            raw = []
        if not isinstance(raw, list):
            return []
        out = []
        for entry in raw:
            if isinstance(entry, dict) and (entry.get("media_url") or entry.get("article_id")):
                out.append(entry)
        return out

    def _save_play_queue(self, queue: list) -> None:
        try:
            self.config_manager.set("play_queue", list(queue or []))
        except Exception:
            log.exception("Failed to save play queue")

    @staticmethod
    def _queue_entry_key(entry) -> str:
        try:
            aid = str(entry.get("article_id") or "").strip()
            if aid:
                return f"id:{aid}"
            return "url:" + str(entry.get("media_url") or "").strip()
        except Exception:
            return ""

    def _article_queue_entry(self, article) -> dict | None:
        """Build a serializable queue entry from an article, or None if unplayable."""
        try:
            media_url, use_ytdlp = self._playback_target_for_article(article)
        except Exception:
            media_url, use_ytdlp = None, False
        if not media_url:
            return None
        aid = getattr(article, "id", None)
        # Remember the source feed so a long queue stays readable — otherwise
        # only the item title shows and it's easy to forget which feed it's from.
        feed_id = getattr(article, "feed_id", None)
        feed_title = ""
        try:
            if feed_id:
                feed = self.feed_map.get(feed_id)
                if feed:
                    feed_title = feed.title or ""
        except Exception:
            feed_title = ""
        return {
            "article_id": (str(aid) if aid is not None else None),
            "media_url": str(media_url),
            "use_ytdlp": bool(use_ytdlp),
            "title": str(getattr(article, "title", "") or "") or str(media_url),
            "media_type": str(getattr(article, "media_type", "") or ""),
            "feed_id": (str(feed_id) if feed_id else ""),
            "feed_title": str(feed_title or ""),
        }

    def _is_article_in_queue(self, article) -> bool:
        return self._queue_index_for_article(article) is not None

    def _queue_index_for_article(self, article):
        if article is None:
            return None
        queue = self._get_play_queue()
        aid = getattr(article, "id", None)
        aid = str(aid) if aid is not None else None
        media_url = str(getattr(article, "media_url", "") or "") or None
        for i, entry in enumerate(queue):
            try:
                e_aid = str(entry.get("article_id") or "") or None
                if aid is not None and e_aid == aid:
                    return i
                if media_url and str(entry.get("media_url") or "") == media_url:
                    return i
            except Exception:
                continue
        return None

    def add_articles_to_queue(self, indices: list) -> None:
        queue = self._get_play_queue()
        existing = {self._queue_entry_key(e) for e in queue}
        added = 0
        for idx in indices or []:
            if not (0 <= idx < len(self.current_articles)):
                continue
            article = self.current_articles[idx]
            entry = self._article_queue_entry(article)
            if not entry:
                continue
            key = self._queue_entry_key(entry)
            if key and key in existing:
                continue
            queue.append(entry)
            existing.add(key)
            added += 1
        if added:
            self._save_play_queue(queue)
            self._announce(
                _("Added {count} to play queue ({total} queued).").format(count=added, total=len(queue))
            )
        else:
            self._announce(_("Already in play queue."))

    def remove_articles_from_queue(self, indices: list) -> None:
        queue = self._get_play_queue()
        remove_keys = set()
        for idx in indices or []:
            if 0 <= idx < len(self.current_articles):
                entry = self._article_queue_entry(self.current_articles[idx])
                if entry:
                    remove_keys.add(self._queue_entry_key(entry))
        if not remove_keys:
            return
        new_queue = [e for e in queue if self._queue_entry_key(e) not in remove_keys]
        removed = len(queue) - len(new_queue)
        if removed:
            self._save_play_queue(new_queue)
            self._current_queue_index = None
            self._announce(
                _("Removed {count} from play queue ({total} queued).").format(count=removed, total=len(new_queue))
            )

    # --- Queue controller interface (used by QueueDialog) ---

    def get_play_queue(self) -> list:
        return self._get_play_queue()

    def remove_queue_indices(self, indices: list) -> None:
        queue = self._get_play_queue()
        drop = {int(i) for i in indices or [] if 0 <= int(i) < len(queue)}
        if not drop:
            return
        self._save_play_queue([e for i, e in enumerate(queue) if i not in drop])
        self._current_queue_index = None

    def move_queue_item(self, index: int, delta: int) -> int:
        queue = self._get_play_queue()
        n = len(queue)
        if not (0 <= index < n):
            return index
        target = index + int(delta)
        if not (0 <= target < n):
            return index
        queue[index], queue[target] = queue[target], queue[index]
        self._save_play_queue(queue)
        return target

    def clear_play_queue(self) -> None:
        self._save_play_queue([])
        self._current_queue_index = None

    def play_queue_index(self, index: int) -> bool:
        queue = self._get_play_queue()
        if not (0 <= index < len(queue)):
            return False
        entry = queue[index]
        media_url = str(entry.get("media_url") or "").strip()
        if not media_url:
            return False
        pw = self._ensure_player_window()
        if not pw:
            return False
        try:
            pw.update_chapters([])
        except Exception:
            pass
        try:
            pw.load_media(
                media_url,
                bool(entry.get("use_ytdlp", False)),
                [],
                title=entry.get("title"),
                article_id=entry.get("article_id"),
            )
        except Exception:
            log.exception("Failed to play queue item")
            return False
        self._current_queue_index = int(index)
        try:
            if bool(self.config_manager.get("show_player_on_play", True)):
                self.toggle_player_visibility(force_show=True)
        except Exception:
            pass
        # Fetch chapters in the background (mirrors _open_article).
        try:
            threading.Thread(
                target=self._fetch_chapters_for_player,
                args=(entry.get("article_id"), media_url, entry.get("media_type")),
                daemon=True,
            ).start()
        except Exception:
            pass
        return True

    def queue_entry_source(self, entry) -> str:
        """Human-readable source feed for a queue entry, or '' if unknown."""
        if not isinstance(entry, dict):
            return ""
        title = str(entry.get("feed_title") or "").strip()
        if title:
            return title
        fid = str(entry.get("feed_id") or "").strip()
        if fid:
            try:
                feed = self.feed_map.get(fid)
                if feed:
                    return str(feed.title or "").strip()
            except Exception:
                pass
        return ""

    def queue_entry_time_label(self, entry) -> str:
        """Length/played annotation for a queue entry (e.g. '4:57, played 4:30').

        Looks the entry up in the playback_state table by article id first and
        media URL second (the two id forms the player writes). Items that have
        never been loaded have no stored duration and read as 'not played'.
        """
        if not isinstance(entry, dict):
            return ""
        st = None
        try:
            from core import playback_state
            aid = str(entry.get("article_id") or "").strip()
            if aid:
                st = playback_state.get_playback_state(f"article:{aid}")
            if st is None:
                murl = str(entry.get("media_url") or "").strip()
                if murl:
                    st = playback_state.get_playback_state(murl)
        except Exception:
            st = None
        return self._playback_time_annotation(st)

    def queue_entry_is_current(self, index: int) -> bool:
        """True when the queue item at `index` is the media loaded in the player."""
        queue = self._get_play_queue()
        if not (0 <= index < len(queue)):
            return False
        pw = getattr(self, "player_window", None)
        if not pw or not getattr(pw, "has_media_loaded", lambda: False)():
            return False
        entry = queue[index]
        try:
            return bool(pw.is_current_media(entry.get("article_id"), entry.get("media_url")))
        except Exception:
            return False

    def queue_entry_is_playing(self, index: int) -> bool:
        """True when the queue item at `index` is the current media AND playing."""
        if not self.queue_entry_is_current(index):
            return False
        pw = getattr(self, "player_window", None)
        try:
            return bool(pw.is_audio_playing())
        except Exception:
            return False

    def toggle_queue_entry_play_pause(self, index: int) -> None:
        """Play the queue item, or toggle play/pause if it is already current.

        This lets the Play Queue dialog's Play button double as a Pause button
        for the item that is currently loaded, instead of restarting it.
        """
        if self.queue_entry_is_current(index):
            self.on_player_play_pause(None)
        else:
            self.play_queue_index(index)

    def _advance_play_queue(self) -> None:
        idx = getattr(self, "_current_queue_index", None)
        if idx is None:
            return
        queue = self._get_play_queue()
        nxt = int(idx) + 1
        if 0 <= nxt < len(queue):
            self.play_queue_index(nxt)
        else:
            self._current_queue_index = None

    def on_open_play_queue(self, event=None) -> None:
        try:
            from .dialogs import QueueDialog
            dlg = QueueDialog(self, self)
            dlg.ShowModal()
            dlg.Destroy()
        except Exception:
            log.exception("Failed to open play queue dialog")

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

    def on_delete_article(self, event=None, *, confirm: bool | None = None):
        # Operate on the whole selection so several articles can be deleted at
        # once (e.g. Shift+Up/Down to select a range, then Delete). Fall back to
        # the focused row when nothing is explicitly selected.
        indices = self._get_selected_article_indices()
        if not indices:
            idx = self._get_selected_article_index()
            if (
                idx == wx.NOT_FOUND
                or self._is_load_more_row(idx)
                or idx < 0
                or idx >= len(self.current_articles)
            ):
                return
            indices = [idx]

        # In the Deleted Articles view the rows are tombstone snapshots, not
        # live articles, so Delete means "remove permanently" and goes through
        # the purge path instead of provider.delete_article.
        if self._is_deleted_view(getattr(self, "current_feed_id", "") or ""):
            self._purge_deleted_articles(indices, confirm=confirm)
            return

        if not self._supports_article_delete():
            wx.MessageBox(
                _("This provider does not support deleting articles."),
                _("Not Supported"),
                wx.ICON_INFORMATION,
            )
            return

        count = len(indices)
        if confirm is None:
            try:
                confirm = bool(self.config_manager.get("confirm_article_delete", True))
            except Exception:
                confirm = True
        if confirm:
            prompt = self._delete_confirm_prompt(indices, count)
            try:
                ok = wx.MessageBox(prompt, _("Confirm Delete"), wx.YES_NO | wx.ICON_WARNING)
            except Exception:
                ok = wx.NO
            if ok != wx.YES:
                return

        # Snapshot identifiers up front so shifting indices during removal can't
        # affect which articles get deleted.
        items = []
        for idx in indices:
            article = self.current_articles[idx]
            cache_key, _url, _aid = self._fulltext_cache_key_for_article(article, idx)
            items.append((article.id, self._article_cache_id(article), cache_key))
        anchor_idx = min(indices)

        threading.Thread(
            target=self._delete_articles_thread,
            args=(items, anchor_idx),
            daemon=True,
        ).start()

    def _delete_confirm_prompt(self, indices, count: int) -> str:
        """Describe what Delete will actually do (soft delete / purge / move),
        resolved from the first selected article's feed so the screen-reader
        user hears the real outcome instead of a generic warning."""
        behavior = "deleted"
        try:
            resolver = getattr(self.provider, "_resolve_delete_behavior", None)
            if callable(resolver) and indices:
                article = self.current_articles[indices[0]]
                behavior = resolver(getattr(article, "feed_id", None))
        except Exception:
            behavior = "deleted"
        kind, category = filters_mod.parse_delete_behavior(behavior)
        subject = ngettext("this article", "{n} articles", count).format(n=count)
        if "%d" in subject:
            subject = subject % count
        if kind == "category" and category:
            return _("Move {subject} to the '{category}' category?").format(subject=subject, category=category)
        if kind == "purge":
            return _("Permanently delete {subject}? This cannot be undone.").format(subject=subject)
        return _("Delete {subject}? Deleted articles can be restored from the Deleted Articles view.").format(subject=subject)

    def _purge_deleted_articles(self, indices, *, confirm: bool | None = None) -> None:
        """Permanently delete the given Deleted-view rows."""
        if not self._supports_purge_deleted():
            wx.MessageBox(
                _("This provider does not support permanently deleting articles."),
                _("Not Supported"),
                wx.ICON_INFORMATION,
            )
            return

        count = len(indices)
        if confirm is None:
            try:
                confirm = bool(self.config_manager.get("confirm_article_delete", True))
            except Exception:
                confirm = True
        if confirm:
            prompt = (
                _("Permanently delete this article? It cannot be restored.")
                if count == 1
                else _("Permanently delete {count} articles? They cannot be restored.").format(count=count)
            )
            try:
                ok = wx.MessageBox(prompt, _("Confirm Permanent Delete"), wx.YES_NO | wx.ICON_WARNING)
            except Exception:
                ok = wx.NO
            if ok != wx.YES:
                return

        items = []
        for idx in indices:
            article = self.current_articles[idx]
            cache_key, _url, _aid = self._fulltext_cache_key_for_article(article, idx)
            items.append(
                (article.id, getattr(article, "feed_id", None), self._article_cache_id(article), cache_key)
            )
        anchor_idx = min(indices)

        threading.Thread(
            target=self._purge_deleted_articles_thread,
            args=(items, anchor_idx),
            daemon=True,
        ).start()

    def _purge_deleted_articles_thread(self, items, anchor_idx: int) -> None:
        # No refresh guard needed: purging keeps the tombstone identity, so a
        # concurrent refresh can neither recreate the article nor race with it.
        results = []
        for article_id, feed_id, article_cache_id, cache_key in items:
            ok = False
            err = ""
            try:
                ok = bool(self.provider.purge_deleted_article(article_id, feed_id))
            except Exception as e:
                err = str(e) or _("Unknown error")
            results.append((article_id, article_cache_id, cache_key, ok, err))
        wx.CallAfter(self._post_delete_articles, results, anchor_idx)

    def _delete_articles_thread(self, items, anchor_idx: int) -> None:
        # No refresh guard needed: delete_article() tombstones the article (so a
        # concurrent refresh can't recreate it) and uses its own short busy-timeout
        # transaction, mirroring purge (_purge_deleted_articles_thread) which
        # already runs unguarded.
        results = []
        for article_id, article_cache_id, cache_key in items:
            ok = False
            err = ""
            try:
                ok = bool(self.provider.delete_article(article_id))
            except Exception as e:
                err = str(e) or _("Unknown error")
            results.append((article_id, article_cache_id, cache_key, ok, err))
        wx.CallAfter(self._post_delete_articles, results, anchor_idx)

    def _post_delete_articles(self, results, anchor_idx: int = 0) -> None:
        deleted_any = False
        failures = []
        for article_id, article_cache_id, cache_key, ok, err in results:
            if not ok:
                failures.append((article_id, err))
                continue
            deleted_any = True
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

        if failures:
            n = len(failures)
            first_err = next((e for _id, e in failures if e), "")
            msg = ngettext("Could not delete article.", "Could not delete {n} articles.", n).format(n=n)
            if "%d" in msg:
                msg = msg % n
            if first_err:
                msg += f"\n\n{first_err}"
            try:
                wx.MessageBox(msg, _("Error"), wx.ICON_ERROR)
            except Exception:
                pass

        if not self.current_articles:
            self._show_empty_articles_state()
            return

        if not deleted_any:
            return

        # Select the next closest item to keep navigation smooth.
        next_idx = min(max(0, int(anchor_idx)), len(self.current_articles) - 1)
        try:
            self._clear_list_selection()
            self.list_ctrl.Select(next_idx)
            self.list_ctrl.Focus(next_idx)
            self.list_ctrl.EnsureVisible(next_idx)
        except Exception:
            pass

    def on_restore_articles(self, indices) -> None:
        """Restore the given Deleted-view rows back into their feeds."""
        if not self._supports_restore_deleted():
            return
        items = []
        seen = set()
        for idx in list(indices or []):
            if idx is None or idx < 0 or idx >= len(self.current_articles):
                continue
            if self._is_load_more_row(idx):
                continue
            article = self.current_articles[idx]
            aid = getattr(article, "id", None)
            feed_id = getattr(article, "feed_id", None)
            item_key = (str(feed_id or ""), str(aid))
            if not aid or item_key in seen:
                continue
            seen.add(item_key)
            items.append((aid, feed_id, self._article_cache_id(article)))
        if not items:
            return
        threading.Thread(target=self._restore_articles_thread, args=(items,), daemon=True).start()

    def _restore_articles_thread(self, items) -> None:
        # No refresh guard needed (mirrors delete/purge): restore_deleted_article()
        # is a single short transaction under the DB's own busy-timeout, and a
        # failed restore already surfaces through _post_restore_articles.
        results = []
        for article_id, feed_id, cache_id in items:
            ok = False
            try:
                ok = bool(self.provider.restore_article(article_id, feed_id=feed_id))
            except Exception:
                log.exception("Error restoring article %s", article_id)
            results.append((article_id, cache_id, ok))
        wx.CallAfter(self._post_restore_articles, results)

    def _post_restore_articles(self, results) -> None:
        restored_any = any(ok for _aid, _cid, ok in results)
        failures = sum(1 for _aid, _cid, ok in results if not ok)

        if restored_any:
            # Restored items live in their feeds again. Drop every cached view
            # snapshot so the Deleted view (and All/Unread/Read/feed views) reload
            # fresh from the DB, then re-render the current view.
            try:
                with getattr(self, "_view_cache_lock", threading.Lock()):
                    self.view_cache.clear()
            except Exception:
                log.exception("Error clearing view cache after restore")
            try:
                self._select_view(getattr(self, "current_feed_id", "") or "deleted:all")
            except Exception:
                log.exception("Error reloading view after restore")

        if failures:
            try:
                wx.MessageBox(
                    _("Could not restore article.") if failures == 1
                    else _("Could not restore {count} articles.").format(count=failures),
                    _("Error"),
                    wx.ICON_ERROR,
                )
            except Exception:
                pass

    def _show_empty_articles_state(self) -> None:
        try:
            self._remove_loading_more_placeholder()
            self.list_ctrl.DeleteAllItems()
            label = _("No matches.") if (self._is_search_active() and getattr(self, "_base_articles", None)) else _("No articles found.")
            self.list_ctrl.InsertItem(0, label)
            self.content_ctrl.Clear()
            self._invalidate_reader_text_tracking()
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

        # Ctrl+D has no other feedback for a screen-reader user: the row's text
        # does not change, so without this the action is silent (issue #70).
        self._announce_event(
            "favorite_toggle",
            _("Added to favorites") if new_state else _("Removed from favorites"),
        )

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

    def _is_protected_uncategorized(self, title) -> bool:
        """True when ``title`` is the protected virtual Uncategorized bucket.

        Uncategorized is a system folder on most providers (nothing to rename or
        delete -- it just means "no category"). On Miniflux it is a real,
        deletable category, so the rename/remove guards must step aside there
        (issue #86). This is the single predicate all four guard sites consult.
        """
        if not is_uncategorized(title):
            return False
        try:
            return not bool(getattr(self.provider, "uncategorized_is_real_category", lambda: False)())
        except Exception:
            return True

    def _eligible_parent_categories(self, category_path: str) -> list:
        """Categories that ``category_path`` may be moved under (issue #86).

        Its own subtree is excluded: a category cannot become its own ancestor,
        and because identity is the full path, offering one would ask the
        provider to rewrite a path into a prefix of itself.
        """
        from core.db import CATEGORY_PATH_SEP
        path = str(category_path or "").strip()
        prefix = path + CATEGORY_PATH_SEP
        out = []
        try:
            categories = self.provider.get_categories() or []
        except Exception:
            categories = []
        for identity in categories:
            candidate = str(identity or "").strip()
            if not candidate or is_uncategorized(candidate):
                continue
            if candidate == path or candidate.startswith(prefix):
                continue
            out.append(candidate)
        return sorted(out, key=lambda s: category_display_name(s).lower())

    def on_edit_category(self, old_title):
        """Category Properties: rename the leaf and/or move it under another
        category (issue #86). The feed-side counterpart is edit_feed_by_id."""
        # Uncategorized is usually a sentinel for "no category", not a stored
        # one: it has no row to rename and no parent to move. Say so -- pressing
        # F2 on it and getting silence reads as a broken shortcut, especially
        # with a screen reader, where a dialog that never opens gives no signal
        # at all. On Miniflux it is a real category, so the guard steps aside.
        if self._is_protected_uncategorized(old_title):
            wx.MessageBox(
                _("The Uncategorized folder cannot be renamed or moved."),
                _("Info"),
            )
            return

        # old_title is the category's full path; the user edits only the leaf.
        from core.db import CATEGORY_PATH_SEP, category_display_leaf, make_category_path
        old_path = str(old_title or "").strip()
        leaf = category_display_leaf(old_path)
        old_parent = (
            old_path.rsplit(CATEGORY_PATH_SEP, 1)[0] if CATEGORY_PATH_SEP in old_path else None
        )

        # Moving is only offered where categories really nest; on a flat
        # provider the dialog is a rename with no parent picker.
        try:
            allow_parent_edit = bool(getattr(self.provider, "supports_subcategories", lambda: False)())
        except Exception:
            allow_parent_edit = False

        dlg = CategoryPropertiesDialog(
            self,
            old_path,
            self._eligible_parent_categories(old_path) if allow_parent_edit else [],
            current_parent=old_parent,
            allow_parent_edit=allow_parent_edit,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            new_leaf, new_parent = dlg.get_data()
        finally:
            dlg.Destroy()

        if not new_leaf:
            new_leaf = leaf
        if not allow_parent_edit:
            new_parent = old_parent
        parent_changed = (new_parent or None) != (old_parent or None)
        if new_leaf == leaf and not parent_changed:
            return

        # Move first, then rename. Both steps reject a name already taken under
        # the destination parent, and doing the move first means the only
        # collision that can block the edit is one at the destination -- renaming
        # first could fail on a clash under the parent being left behind.
        path = old_path
        if parent_changed:
            if not self.provider.move_category(path, new_parent):
                wx.MessageBox(_("Could not move category."), _("Error"), wx.ICON_ERROR)
                return
            path = make_category_path(new_parent, leaf)
        if new_leaf != leaf:
            if not self.provider.rename_category(path, new_leaf):
                wx.MessageBox(_("Could not rename category."), _("Error"), wx.ICON_ERROR)
                self.refresh_feeds()  # a completed move still needs to show
                return
        self.refresh_feeds()

    def on_add_category(self, event):
        # Only offer a parent picker for providers that support nested categories
        # (folders within folders). Flat providers get a plain top-level add.
        supports_sub = bool(getattr(self.provider, "supports_subcategories", lambda: False)())
        dlg = wx.Dialog(self, title=_("Add Category"), size=(400, 220 if supports_sub else 160))
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(dlg, label=_("Category name:")), 0, wx.ALL, 5)
        name_ctrl = wx.TextCtrl(dlg)
        name_ctrl.SetName(_("Category name"))
        sizer.Add(name_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        parent_ctrl = None
        if supports_sub:
            cats = self.provider.get_categories()
            category_ids = sorted(cats, key=lambda s: category_display_name(s).lower())
            choices = [_("(None - Top Level)")] + [
                category_display_name(category) for category in category_ids
            ]
            sizer.Add(wx.StaticText(dlg, label=_("Parent category:")), 0, wx.ALL, 5)
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
            parent_title = None
            if parent_ctrl is not None:
                parent_sel = parent_ctrl.GetSelection()
                parent_title = None if parent_sel <= 0 else category_ids[parent_sel - 1]
            if name:
                if self.provider.add_category(name, parent_title=parent_title):
                    self.refresh_feeds()
                else:
                    wx.MessageBox(_("Could not add category."), _("Error"), wx.ICON_ERROR)
        dlg.Destroy()

    def on_add_subcategory(self, parent_cat_title):
        # parent_cat_title is the parent's full path; show just its leaf to the user.
        from core.db import category_display_leaf
        parent_leaf = category_display_leaf(parent_cat_title)
        dlg = wx.TextEntryDialog(
            self,
            _("Enter subcategory name (under '{category}'):").format(category=parent_leaf),
            _("Add Subcategory"),
        )
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                if self.provider.add_category(name, parent_title=parent_cat_title):
                    self.refresh_feeds()
                else:
                    wx.MessageBox(_("Could not add subcategory."), _("Error"), wx.ICON_ERROR)
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
                if self._is_protected_uncategorized(data.get("id")):
                    wx.MessageBox(_("The Uncategorized folder cannot be removed."), _("Info"))
                    return
                if wx.MessageBox(
                    _("Remove category '{category}'? Feeds will be moved to Uncategorized.").format(
                        category=self.tree.GetItemText(item)
                    ),
                    _("Confirm"),
                    wx.YES_NO,
                ) == wx.YES:
                    self._selection_hint = self._get_parent_category_hint(data["id"])
                    if self.provider.delete_category(data["id"]):
                        self.refresh_feeds()
                    else:
                        wx.MessageBox(_("Could not remove category."), _("Error"), wx.ICON_ERROR)
            else:
                 wx.MessageBox(_("Please select a category to remove."), _("Info"))

    def on_delete_category_with_feeds(self, event):
        item = self.tree.GetSelection()
        if not item or not item.IsOk():
            return
        data = self.tree.GetItemData(item)
        if not data or data.get("type") != "category":
            wx.MessageBox(_("Please select a category to remove."), _("Info"))
            return

        cat_title = data.get("id")
        if not cat_title or self._is_protected_uncategorized(cat_title):
            wx.MessageBox(_("The Uncategorized folder cannot be removed."), _("Info"))
            return

        feed_ids = []
        sub_cats = []
        try:
            from core.db import get_subcategory_titles
            sub_cats = get_subcategory_titles(cat_title)
            all_cats_to_delete = {cat_title} | set(sub_cats)
            for fid, feed in (self.feed_map or {}).items():
                if (feed.category or UNCATEGORIZED) in all_cats_to_delete:
                    feed_ids.append(fid)
        except Exception:
            feed_ids = []
            sub_cats = []

        count = len(feed_ids)
        sub_note = _(" (including subcategories)") if len(sub_cats) > 0 else ""
        prompt = (
            ngettext("Delete category '{title}'{note} and its {count} feed?", "Delete category '{title}'{note} and its {count} feeds?", count).format(title=cat_title, note=sub_note, count=count)
            + "\n\n" +
            _("This will remove the feeds and their articles.")
        )
        if wx.MessageBox(prompt, _("Confirm"), wx.YES_NO | wx.ICON_WARNING) != wx.YES:
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
            warnings.append(_("Category '{title}' could not be deleted.").format(title=cat_title))
            if category_error:
                warnings.append(_("Error: {error}").format(error=category_error))
        if failed:
            warnings.append(
                ngettext("{n} feed could not be removed.", "{n} feeds could not be removed.", len(failed)).format(n=len(failed))
            )
        if warnings:
            wx.MessageBox("\n\n".join(warnings), _("Warning"), wx.ICON_WARNING)

    def _scheduled_refresh_tick_seconds(self) -> int:
        """Seconds between refresh-loop ticks: the global interval, shortened by
        any per-feed refresh interval overrides (local provider only)."""
        try:
            global_interval = int(self.config_manager.get("refresh_interval", 300))
        except (TypeError, ValueError):
            global_interval = 300
        try:
            return int(self.provider.scheduled_refresh_tick(global_interval))
        except Exception:
            return global_interval

    def refresh_loop(self):
        # If auto-refresh on startup is disabled, wait for one interval before the first check.
        startup_refresh_pending = bool(self.config_manager.get("refresh_on_startup", True))
        if not startup_refresh_pending:
             interval = self._scheduled_refresh_tick_seconds()
             log.info("Refresh loop startup refresh disabled; waiting interval_s=%s before first refresh", interval)
             if self.stop_event.wait(interval):
                 return

        while not self.stop_event.is_set():
            interval = self._scheduled_refresh_tick_seconds()
            is_startup_tick = startup_refresh_pending
            if interval <= 0 and not is_startup_tick:
                # "Never" setting: wait 5s then check config/stop event again
                if self.stop_event.wait(5):
                    return
                continue
                
            try:
                # The first refresh after launch should be immediate. By default it is
                # non-forced (conditional GET) so hosted providers such as Miniflux do
                # not fan out into per-feed refresh requests for every subscription.
                # Providers where forcing is cheap (the local provider: one full GET per
                # feed) opt in via should_force_startup_refresh() so a fresh launch is
                # not left stale by servers that return a spurious 304.
                startup_refresh_pending = False
                force_refresh = False
                if is_startup_tick:
                    try:
                        force_refresh = bool(self.provider.should_force_startup_refresh())
                    except Exception:
                        force_refresh = False
                log.info(
                    "Refresh loop tick interval_s=%s force=%s startup=%s",
                    interval, force_refresh, is_startup_tick,
                )
                # Periodic (non-startup) ticks are "scheduled": the provider may
                # skip feeds whose per-feed refresh interval has not elapsed yet.
                ran = self._run_refresh(block=False, force=force_refresh, scheduled=not is_startup_tick)
                log.info("Refresh loop tick complete ran=%s interval_s=%s force=%s", ran, interval, force_refresh)
            except Exception as e:
                print(f"Refresh error: {e}")
                log.exception("Refresh loop tick failed")
            # "Never" suppresses periodic ticks, but a separately enabled
            # startup refresh above still runs once before we enter this wait.
            sleep_seconds = interval if interval > 0 else 5
            # Sleep in one shot but wake early if closing
            if self.stop_event.wait(sleep_seconds):
                return

    def refresh_feeds(self):
        # Offload data fetching to background thread to prevent blocking UI
        log.info("Feed tree load requested")
        threading.Thread(target=self._refresh_feeds_worker, daemon=True).start()

    def _refresh_feeds_worker(self):
        try:
            started_at = time.monotonic()
            # Retention cleanup moved to _manual_refresh_thread to prevent
            # deletion of articles that were just marked as read.
            feeds = self.provider.get_feeds()
            all_cats = self.provider.get_categories()
            # Sync categories to local DB so hierarchy is available for all providers
            from core.db import sync_categories
            sync_categories(all_cats)
            hierarchy = self.provider.get_category_hierarchy()
            log.info(
                "Feed tree data loaded feeds=%s categories=%s duration_s=%.2f",
                len(feeds or []),
                len(all_cats or []),
                time.monotonic() - started_at,
            )
            wx.CallAfter(self._update_tree, feeds, all_cats, hierarchy)
        except Exception as e:
            log.exception("Feed tree load failed")
            # Runs in a background thread; marshal the dialog onto the UI thread.
            wx.CallAfter(wx.MessageBox, _("Error fetching feeds: {error}").format(error=e), _("Error"), wx.ICON_ERROR)

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
        # A tray-only launch must remain windowless until explicitly restored.
        if bool(getattr(self, "_start_in_system_tray", False)) and not self.IsShown():
            return
        self._voiceover_browser_attempted = True
        if not sys.platform.startswith("darwin"):
            return
        try:
            if voiceover_is_running():
                self.on_open_accessible_browser()
        except Exception:
            log.exception("Failed to auto-open accessible browser for VoiceOver")

    # --- Status bar activity field (field 1): ambient "what's happening now" ---
    # text for background work (feed refresh, downloads). Field 0 is left alone
    # (filter-match counts and other existing transient messages). Last-write-wins
    # if two background operations overlap; no queue/tracker is maintained.

    def _set_activity_status(self, text: str, *, update_tray: bool = True) -> None:
        """Set the activity-status field. UI-thread only.

        Background-thread callers must use _post_activity_status instead.
        ``update_tray=False`` is used while a progress flush is applying many
        feeds: updating a native tray icon walks every feed to recompute the
        unread total, so doing it for each state turns one refresh chunk into
        an avoidable O(feeds * completed-feeds) burst on the UI thread.
        """
        try:
            self.SetStatusText(text or "", 1)
        except Exception:
            log.debug("Failed to set activity status text", exc_info=True)
        if not update_tray:
            return
        update_tray = getattr(self, "_set_tray_activity_label", None)
        if callable(update_tray):
            try:
                update_tray(text)
            except Exception:
                log.debug("Failed to update tray activity label", exc_info=True)

    def _total_unread_count_for_tray(self) -> int:
        total = 0
        try:
            feeds = getattr(self, "feed_map", {}) or {}
            for feed in feeds.values():
                total += max(0, int(getattr(feed, "unread_count", 0) or 0))
        except Exception:
            return 0
        return total

    def _set_tray_activity_label(self, text: str | None, *, update: bool = True) -> None:
        activity = " ".join(str(text or "").split())
        if activity == _("Refresh complete"):
            activity = ""
        self._tray_activity_label = activity
        if update:
            self._update_tray_status_label()

    def _update_tray_status_label(self) -> None:
        tray = getattr(self, "tray_icon", None)
        update_label = getattr(tray, "update_status_label", None)
        if not callable(update_label):
            return
        try:
            update_label(
                self._total_unread_count_for_tray(),
                getattr(self, "_tray_activity_label", ""),
            )
        except Exception:
            log.debug("Failed to update tray status label", exc_info=True)

    def _post_activity_status(self, text: str) -> None:
        """Marshal an activity-status update from any (likely background) thread."""
        try:
            wx.CallAfter(self._set_activity_status, text)
        except Exception:
            # Likely during shutdown.
            log.debug("Failed to schedule activity status update, likely during shutdown.", exc_info=True)

    def _begin_refresh_activity(self, message: str | None = None, *, total: int | None = None) -> None:
        """Announce that a feed-refresh batch has started.

        message is the complete, already-localized wording for a targeted
        refresh ("Refreshing category: Tech..."); omit it for the main/periodic
        full-feed refresh. Shared by all four refresh entry points so the
        begin/end wording stays consistent instead of being copy-pasted.

        total is how many feeds this batch expects to check. When it is known
        the per-feed status becomes "Checked X out of Y" instead of the title
        of whichever feed happened to finish last, which is what tells a user
        how much of a long refresh is left (issue #85).
        """
        self._reset_refresh_progress_counter(total)
        self._post_activity_status(message or _("Refreshing feeds..."))

    def _reset_refresh_progress_counter(self, total: int | None = None) -> None:
        """Start a fresh "checked X out of Y" count for a refresh batch."""
        try:
            expected = max(0, int(total or 0))
        except (TypeError, ValueError):
            expected = 0
        self._refresh_progress_total = expected
        self._refresh_progress_seen = set()

    def _note_refresh_progress_feed(self, feed_id) -> None:
        """Count a feed as checked.

        Called for every progress state, on worker threads. Counting feed ids
        rather than callbacks keeps the number honest when a provider reports
        the same feed twice (a Miniflux per-feed retry, an error followed by a
        result), and counts feeds the UI later coalesces away.
        """
        seen = getattr(self, "_refresh_progress_seen", None)
        if seen is None:
            seen = set()
            self._refresh_progress_seen = seen
        seen.add(str(feed_id))

    def _refresh_progress_counts(self) -> tuple[int, int]:
        """(checked, total) for the running batch, or (0, 0) when no total is known."""
        try:
            total = int(getattr(self, "_refresh_progress_total", 0) or 0)
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            return (0, 0)
        done = len(getattr(self, "_refresh_progress_seen", None) or ())
        # A provider can report more feeds than the snapshot predicted (a feed
        # added mid-refresh, a retry pass over feeds outside the batch). Grow
        # the total rather than announcing "27 out of 25".
        return (done, max(total, done))

    def _expected_refresh_feed_count(self) -> int:
        """How many feeds a full refresh is expected to check (issue #85's Y).

        feed_map is the tree's own snapshot, which is what the user counts as
        "all my feeds"; fall back to the provider before the tree is built.
        """
        try:
            count = len(getattr(self, "feed_map", None) or {})
        except Exception:
            count = 0
        if count:
            return count
        try:
            return len(list(self.provider.get_feeds() or []))
        except Exception:
            return 0

    def _end_refresh_activity(self) -> None:
        """Announce that a feed-refresh batch has finished (success, error, or
        stopped by the user via Stop Refresh)."""
        if getattr(self, "_refresh_stop_requested", False):
            self._refresh_stop_requested = False
            self._post_activity_status(_("Refresh stopped"))
            return
        self._post_activity_status(_("Refresh complete"))

    def _set_feed_activity_status(self, state: dict) -> None:
        """Reflect a just-completed per-feed refresh (called on the UI thread
        from _apply_feed_refresh_progress, which already runs inside
        wx.CallAfter, so this touches the status bar directly).
        """
        if not state:
            return
        title = str(state.get("title") or "").strip() or "feed"
        failed = bool(state.get("error") or state.get("status") == "error")
        done, total = self._refresh_progress_counts()
        if total > 0:
            if failed:
                message = _("Error checking: {title} ({done} out of {total})").format(
                    title=title, done=done, total=total
                )
            else:
                message = _("Checked {done} out of {total}").format(done=done, total=total)
            # The tray gets the batch count, not the feed title: the count is
            # the part a user wants at a glance, and it changes once per UI
            # chunk instead of once per feed.  Store it only -- the flush that
            # is already recomputing the unread total paints it (below).
            set_tray_label = getattr(self, "_set_tray_activity_label", None)
            if callable(set_tray_label):
                set_tray_label(
                    _("Refreshing: {done} out of {total}").format(done=done, total=total),
                    update=False,
                )
        elif failed:
            message = _("Error checking: {title}").format(title=title)
        else:
            message = _("Checked: {title}").format(title=title)
        # Keep the tray's activity wording stable for the batch.  Replacing it
        # with every completed feed title makes Windows redraw the native tray
        # icon hundreds of times in a long refresh.  The status field remains
        # the detailed, screen-reader-friendly progress view.
        self._set_activity_status(message, update_tray=False)

    def _begin_refresh_ui_batch(self) -> int:
        """Mark a full refresh as active for selected-list coalescing.

        This is set by the worker before it can emit per-feed progress.  The
        values are simple flags guarded by the GIL; all UI work remains on the
        wx thread in ``_finish_refresh_ui_batch`` / the progress flusher.
        """
        # The provider guard prevents overlapping fetches, but it is released
        # before wx drains all posted progress.  Tokenize each run so a stale
        # completion callback can never finish a newer batch's UI state.
        self._refresh_ui_batch_token = int(getattr(self, "_refresh_ui_batch_token", 0) or 0) + 1
        self._refresh_ui_batch_active = True
        self._refresh_ui_batch_ending = False
        self._refresh_ui_batch_refresh_tree = False
        self._refresh_ui_batch_end_activity = False
        # A successful provider refresh can still be a complete no-op.  Keep
        # the final tree reload for real model/error changes only; otherwise a
        # large conditional refresh needlessly re-queries and rebuilds the UI.
        self._refresh_ui_batch_dirty = False
        return self._refresh_ui_batch_token

    def _finish_refresh_ui_batch(self, refresh_tree: bool, batch_token: int | None = None) -> None:
        """Finish a full refresh after its already-posted progress drains."""
        if batch_token is not None and int(batch_token) != int(getattr(self, "_refresh_ui_batch_token", 0) or 0):
            log.debug("Ignoring stale refresh UI completion token=%s", batch_token)
            return
        self._refresh_ui_batch_ending = True
        # Keep the caller's request, rather than snapshotting ``dirty`` here.
        # The worker can finish while a later 40-state wx progress chunk is
        # still queued, and that chunk may be the one that changes the model.
        self._refresh_ui_batch_refresh_tree = bool(refresh_tree)
        self._refresh_ui_batch_end_activity = True
        self._maybe_finish_refresh_ui_batch(batch_token=batch_token)

    def _maybe_finish_refresh_ui_batch(self, batch_token: int | None = None) -> None:
        """Complete the deferred final UI update once no progress callback is
        still queued.

        A full refresh can finish while `_flush_feed_refresh_progress` has
        scheduled its next 40-state timer batch.  Starting the final tree load
        before those batches complete would reintroduce list churn, so wait for
        the queue to become idle rather than polling it with ``wx.CallAfter``.
        """
        if batch_token is not None and int(batch_token) != int(getattr(self, "_refresh_ui_batch_token", 0) or 0):
            return
        if not getattr(self, "_refresh_ui_batch_ending", False):
            return
        try:
            with self._refresh_progress_lock:
                progress_pending = bool(self._refresh_progress_pending)
                flush_scheduled = bool(self._refresh_progress_flush_scheduled)
        except Exception:
            progress_pending = False
            flush_scheduled = False
        if progress_pending or flush_scheduled:
            return

        refresh_tree_requested = bool(getattr(self, "_refresh_ui_batch_refresh_tree", False))
        has_cached_tree = bool(getattr(self, "feed_map", None))
        refresh_tree = refresh_tree_requested and (
            bool(getattr(self, "_refresh_ui_batch_dirty", False)) or not has_cached_tree
        )
        end_activity = bool(getattr(self, "_refresh_ui_batch_end_activity", False))
        self._refresh_ui_batch_active = False
        self._refresh_ui_batch_ending = False
        self._refresh_ui_batch_refresh_tree = False
        self._refresh_ui_batch_end_activity = False
        self._refresh_ui_batch_dirty = False

        # Do this after the final per-feed status update, otherwise a timer
        # chunk can overwrite "Refresh complete" with a stale feed title.
        if end_activity:
            self._end_refresh_activity()

        if refresh_tree:
            # The tree update owns the final view reload: every _update_tree
            # branch now consults the still-set dirty marker (the unchanged
            # branch reloads only when dirty, fixing refreshes that change
            # articles without changing any tree signature). Cancel a queued
            # mid-batch debounce so it cannot race _update_tree's reload and
            # fetch the same page twice within a second.
            self._cancel_pending_article_reload()
            self.refresh_feeds()
        elif getattr(self, "_article_refresh_dirty", False):
            self._schedule_article_reload()
        elif self._has_stale_read_filter_rows():
            # Nothing in the model changed, so neither branch above runs -- but
            # rows the user read since the last load no longer belong in an
            # Unread Only / Read Only view, and a refresh is when they expect
            # them gone (issue #96). Re-render from the already-loaded
            # articles; no fetch, and focus/selection are restored.
            self._refresh_articles_for_sort_change()

    def _on_feed_refresh_progress(self, state, batch_token: int | None = None):
        # Called from worker threads inside provider.refresh; batch and marshal to UI thread.
        if not isinstance(state, dict):
            return
        feed_id = state.get("id")
        if not feed_id:
            return

        with self._refresh_progress_lock:
            # Count before coalescing: two feeds that finish between UI chunks
            # both count, even though only the later state survives the queue.
            self._note_refresh_progress_feed(feed_id)
            # Keep the latest state per feed per batch.  The token allows a
            # stale posted state from a just-finished refresh to be dropped if
            # the user starts another refresh before wx drains it.
            queue_key = (
                (int(batch_token), str(feed_id))
                if batch_token is not None
                else str(feed_id)
            )
            self._refresh_progress_pending[queue_key] = (
                int(batch_token), state
            ) if batch_token is not None else state
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
        # Drain in bounded chunks: with many feeds a refresh can complete
        # hundreds of feeds between flushes, and applying them all in one UI
        # callback stalls input and screen-reader events. A 1ms CallLater
        # between chunks lets keyboard/NVDA/paint events interleave (same
        # pattern as the article-list render batches).
        batch_limit = 40
        with self._refresh_progress_lock:
            keys = list(self._refresh_progress_pending.keys())[:batch_limit]
            pending = [self._refresh_progress_pending.pop(k) for k in keys]
            more = bool(self._refresh_progress_pending)
            self._refresh_progress_flush_scheduled = more

        applied_any = False
        latest_applied_state = None
        for pending_state in pending:
            state_token = None
            st = pending_state
            if (
                isinstance(pending_state, tuple)
                and len(pending_state) == 2
                and isinstance(pending_state[0], int)
                and isinstance(pending_state[1], dict)
            ):
                state_token, st = pending_state
            if state_token is not None and state_token != int(getattr(self, "_refresh_ui_batch_token", 0) or 0):
                continue
            try:
                # One status-bar update per UI chunk is enough: only the last
                # message is observable, while one per feed floods native and
                # accessibility events during a large refresh.
                self._apply_feed_refresh_progress(st, update_activity=False)
                applied_any = True
                latest_applied_state = st
            except Exception:
                log.debug("Failed to apply feed refresh progress update", exc_info=True)

        if latest_applied_state is not None:
            try:
                self._set_feed_activity_status(latest_applied_state)
            except Exception:
                log.debug("Failed to update refresh activity status", exc_info=True)

        # One tray/unread-total update per chunk, not per feed: the total walks
        # every feed, so doing it per progress state is quadratic in feed count.
        if applied_any:
            update_tray = getattr(self, "_update_tray_status_label", None)
            if callable(update_tray):
                try:
                    update_tray()
                except Exception:
                    log.debug("Failed to update tray status label", exc_info=True)

        if more:
            try:
                wx.CallLater(1, self._flush_feed_refresh_progress)
            except Exception:
                with self._refresh_progress_lock:
                    self._refresh_progress_pending.clear()
                    self._refresh_progress_flush_scheduled = False
                log.debug("Failed to reschedule feed refresh progress flush", exc_info=True)
                finish_ui_batch = getattr(self, "_maybe_finish_refresh_ui_batch", None)
                if callable(finish_ui_batch):
                    finish_ui_batch()
        else:
            # A full refresh may have already completed on its worker thread.
            # Let its final tree/list update run only after this last bounded
            # UI chunk, never in the middle of a progress storm.
            finish_ui_batch = getattr(self, "_maybe_finish_refresh_ui_batch", None)
            if callable(finish_ui_batch):
                finish_ui_batch()

    def _apply_feed_refresh_progress(self, state, *, update_activity: bool = True):
        if not state:
            return
        feed_id = state.get("id")
        if not feed_id:
            return

        if update_activity:
            self._set_feed_activity_status(state)

        title = state.get("title", "")
        unread = state.get("unread_count", 0)
        category = state.get("category", UNCATEGORIZED)
        try:
            has_new_items = int(state.get("new_items", 0) or 0) > 0
        except (TypeError, ValueError):
            has_new_items = bool(state.get("new_items"))
        model_changed = (
            has_new_items
            or bool(state.get("content_changed"))
            or bool(state.get("feed_metadata_changed"))
        )
        visible_feed_changed = False

        # Update cached feed objects
        feed_obj = self.feed_map.get(feed_id)
        if feed_obj:
            old_unread = int(getattr(feed_obj, "unread_count", 0) or 0)
            old_category = getattr(feed_obj, "category", None)
            old_title = getattr(feed_obj, "title", "")
            next_title = title or old_title
            visible_feed_changed = (
                next_title != old_title or unread != old_unread or category != old_category
            )
            model_changed = model_changed or visible_feed_changed
            feed_obj.title = next_title
            feed_obj.unread_count = unread
            feed_obj.category = category

            # Keep category aggregates live during a refresh instead of only
            # catching up once the full tree rebuild fires at the end (issue
            # #34). Handles a feed moving category mid-refresh by debiting the
            # old chain and crediting the new one; same-category updates net
            # out to the plain delta.
            if old_category == category and unread != old_unread:
                # The common case is an unchanged feed category.  Applying the
                # net delta once avoids two full ancestor-chain TreeCtrl writes
                # (and their screen-reader events) for every completed feed.
                self._update_category_unread_chain_ui(category, unread - old_unread)
            elif old_category != category:
                if old_category and old_unread:
                    self._update_category_unread_chain_ui(old_category, -old_unread)
                if category and unread:
                    self._update_category_unread_chain_ui(category, unread)
            # Tray/unread-total update happens once per flush chunk in
            # _flush_feed_refresh_progress; per-feed it is quadratic.
        else:
            # The initial cached-tree load can race the first refresh.  Ensure
            # the final rebuild incorporates this feed's current state.
            model_changed = True

        if model_changed and getattr(self, "_refresh_ui_batch_active", False):
            self._refresh_ui_batch_dirty = True

        # Update tree label if present
        node = self.feed_nodes.get(feed_id)
        if visible_feed_changed and node and node.IsOk():
            label = f"{title} ({unread})" if unread > 0 else title
            try:
                current_label = self.tree.GetItemText(node)
            except Exception:
                current_label = None
            if current_label != label:
                self.tree.SetItemText(node, label)

        # If the selected view is impacted, schedule article reload.  A true
        # no-op completion needs neither a list reload nor a final tree rebuild.
        if not model_changed:
            return
        sel = self.tree.GetSelection()
        if sel and sel.IsOk():
            data = self.tree.GetItemData(sel)
            if data:
                typ = data.get("type")
                if typ == "all":
                    self._request_article_reload()
                elif typ == "feed" and data.get("id") == feed_id:
                    self._request_article_reload()
                elif typ == "category":
                    # Category views aggregate nested subcategories (path-based
                    # identity, CATEGORY_PATH_SEP-joined), so a parent view must
                    # also reload when a feed in a subcategory gets new items.
                    from core.db import CATEGORY_PATH_SEP
                    sel_cat = str(data.get("id") or "")
                    feed_cat = str(category or "")
                    if sel_cat and (
                        feed_cat == sel_cat
                        or feed_cat.startswith(sel_cat + CATEGORY_PATH_SEP)
                    ):
                        self._request_article_reload()

    def _request_article_reload(self):
        """Remember that the selected view changed during a refresh.

        During a full refresh the reload runs on a slow throttle so new
        articles appear in the visible list as feeds complete, without the
        per-feed reload churn that starved full-text extraction.  Once the
        batch enters its ending drain the final tree/list update is imminent,
        so only the dirty marker is kept.  Targeted refreshes still use the
        normal short debounce, so a single-feed refresh remains visibly
        current without spawning one loader per feed completion.
        """
        self._article_refresh_dirty = True
        if getattr(self, "_refresh_ui_batch_ending", False):
            return
        if getattr(self, "_refresh_ui_batch_active", False):
            self._schedule_article_reload(
                delay_ms=int(getattr(self, "_article_refresh_batch_ms", 2500))
            )
            return
        self._schedule_article_reload()

    def _schedule_article_reload(self, delay_ms: int | None = None):
        self._article_refresh_dirty = True
        if self._article_refresh_pending:
            return
        self._article_refresh_pending = True
        if delay_ms is None:
            delay_ms = int(getattr(self, "_article_refresh_debounce_ms", 250))
        self._article_refresh_timer = wx.CallLater(max(1, int(delay_ms)), self._run_pending_article_reload)

    def _cancel_pending_article_reload(self):
        timer = getattr(self, "_article_refresh_timer", None)
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        self._article_refresh_timer = None
        self._article_refresh_pending = False

    def _run_pending_article_reload(self):
        self._article_refresh_pending = False
        self._article_refresh_timer = None
        if getattr(self, "_refresh_ui_batch_ending", False):
            # The batch's final update handles the still-set dirty marker.
            return
        if not getattr(self, "_article_refresh_dirty", False):
            return
        self._article_refresh_dirty = False
        log.debug("Article reload cycle start (debounced/throttled)")
        self._reload_selected_articles()

    def on_tree_item_expanded(self, event):
        """Remember that the user expanded a category (issue #33)."""
        self._record_tree_expansion(event.GetItem(), expanded=True)
        event.Skip()

    def on_tree_item_collapsed(self, event):
        """Remember that the user collapsed a category (issue #33)."""
        self._record_tree_expansion(event.GetItem(), expanded=False)
        event.Skip()

    def _record_tree_expansion(self, item, expanded: bool):
        # Ignore the expand/collapse events our own rebuild triggers; only real
        # user actions should update the remembered state.
        if getattr(self, "_updating_tree", False):
            return
        if not item or not item.IsOk():
            return
        data = self.tree.GetItemData(item)
        if not data or data.get("type") != "category":
            return
        cat_id = data.get("id")
        if cat_id is None:
            return
        if expanded:
            self._expanded_categories.add(cat_id)
            self._collapsed_categories.discard(cat_id)
        else:
            self._collapsed_categories.add(cat_id)
            self._expanded_categories.discard(cat_id)

    @staticmethod
    def _resolve_category_expanded(cat, expanded_set, collapsed_set, default_expanded: bool) -> bool:
        """Decide whether a category node should be expanded (issue #33).

        A category the user explicitly expanded or collapsed keeps that choice;
        one they never touched follows the configured default.
        """
        if cat in expanded_set:
            return True
        if cat in collapsed_set:
            return False
        return bool(default_expanded)

    @staticmethod
    def _compute_category_unread_totals(cat_feeds_map: dict, children_of: dict) -> dict:
        """Recursively sum unread counts per category (issue #34).

        total_unread(cat) = sum(unread_count of direct feeds) + sum(total_unread
        of child categories). Each category is summed once (memoized in
        ``totals``) regardless of how many ancestors pull it in, so this is
        O(categories + feeds) even for deep/wide hierarchies.
        """
        totals: dict = {}

        def _sum(cat):
            cached = totals.get(cat)
            if cached is not None:
                return cached
            total = sum(
                max(0, int(getattr(feed, "unread_count", 0) or 0))
                for feed in cat_feeds_map.get(cat, [])
            )
            for child in children_of.get(cat, []):
                total += _sum(child)
            totals[cat] = total
            return total

        for cat in cat_feeds_map.keys():
            _sum(cat)
        return totals

    def _apply_tree_expansion(self, cat_node_map):
        """Set each category's expansion state on a freshly rebuilt tree (issue #33).

        Categories the user explicitly expanded/collapsed keep that state across
        rebuilds; untouched categories follow the configured default
        (category_tree_default_expanded). This runs while ``_updating_tree`` is
        True, so the resulting expand/collapse events are ignored.
        """
        default_expanded = bool(self.config_manager.get("category_tree_default_expanded", True))
        for cat, node in cat_node_map.items():
            if not node or not node.IsOk():
                continue
            expand = self._resolve_category_expanded(
                cat, self._expanded_categories, self._collapsed_categories, default_expanded
            )
            try:
                if expand:
                    self.tree.Expand(node)
                else:
                    self.tree.Collapse(node)
            except Exception:
                log.debug("Failed to set expansion for category %r", cat, exc_info=True)

    def _tree_content_signatures(self, feeds, all_cats, hierarchy):
        """(structural, counts) signatures of what the tree would display.

        ``structural`` covers everything that changes the node set: feed
        ids/titles/categories, the category list and hierarchy, smart folders,
        and the read-status filter. ``counts`` covers per-feed unread counts,
        which only affect labels while the filter is "all".
        """
        smart_folders = ()
        try:
            if getattr(self.provider, "supports_smart_folders", lambda: False)():
                smart_folders = tuple(
                    (f.get("id"), f.get("name") or "")
                    for f in (self.provider.get_smart_folders() or [])
                )
        except Exception:
            smart_folders = ()
        # Provider identity/features decide the special nodes (Favorites,
        # Deleted Articles, Smart Folders), so a provider switch that happens
        # to expose an identical feed set still rebuilds.
        try:
            provider_features = (
                type(self.provider).__name__,
                bool(getattr(self.provider, "supports_favorites", lambda: False)()),
                bool(getattr(self.provider, "supports_restore_deleted", lambda: False)()),
            )
        except Exception:
            provider_features = ("?", False, False)
        structural = (
            provider_features,
            getattr(self, "_article_read_filter", "all"),
            tuple(sorted((str(f.id), f.title or "", f.category or "") for f in feeds)),
            tuple(sorted(str(c) for c in (all_cats or []))),
            tuple(sorted((str(k), str(v)) for k, v in (hierarchy or {}).items())),
            smart_folders,
        )
        counts = tuple(
            sorted((str(f.id), int(getattr(f, "unread_count", 0) or 0)) for f in feeds)
        )
        return structural, counts

    def _patch_tree_unread_labels(self, feeds, all_cats, hierarchy):
        """Update unread counts on the existing tree without rebuilding it.

        Only valid when the node set is unchanged (same structural signature)
        and the read filter is "all", where counts are purely cosmetic.
        """
        self.feed_map = {f.id: f for f in feeds}

        for feed in feeds:
            node = self.feed_nodes.get(feed.id)
            if not node or not node.IsOk():
                continue
            unread = int(getattr(feed, "unread_count", 0) or 0)
            label = f"{feed.title} ({unread})" if unread > 0 else (feed.title or "")
            try:
                if self.tree.GetItemText(node) != label:
                    self.tree.SetItemText(node, label)
            except Exception:
                log.debug("Failed to patch feed node label", exc_info=True)

        # Recompute category totals the same way the full rebuild does.
        cat_feeds_map = {c: [] for c in (all_cats or [])}
        for feed in feeds:
            cat_feeds_map.setdefault(feed.category or UNCATEGORIZED, []).append(feed)
        children_of = {}
        all_cat_set = set(cat_feeds_map.keys())
        for cat in all_cat_set:
            parent = (hierarchy or {}).get(cat)
            if parent and parent in all_cat_set:
                children_of.setdefault(parent, []).append(cat)
        totals = self._compute_category_unread_totals(cat_feeds_map, children_of)
        self.category_unread_totals = totals

        base_labels = getattr(self, "category_base_labels", {}) or {}
        for cat, node in (getattr(self, "cat_nodes", {}) or {}).items():
            if not node or not node.IsOk():
                continue
            base = base_labels.get(cat, cat)
            total = totals.get(cat, 0)
            label = f"{base} ({total})" if total > 0 else base
            try:
                if self.tree.GetItemText(node) != label:
                    self.tree.SetItemText(node, label)
            except Exception:
                log.debug("Failed to patch category node label", exc_info=True)

        update_tray = getattr(self, "_update_tray_status_label", None)
        if callable(update_tray):
            update_tray()

    def _update_tree(self, feeds, all_cats, hierarchy=None):
        # Fast paths for periodic refreshes: a full rebuild recreates every node,
        # stalling the UI thread and disturbing screen-reader focus in the tree,
        # so skip it when nothing (or only unread counts) changed. Structural
        # changes, the first load, pending selection hints, and non-"all" read
        # filters (where counts decide node visibility) always rebuild.
        structural_sig, counts_sig = self._tree_content_signatures(feeds, all_cats, hierarchy)
        if (
            not self._is_first_tree_load
            and not getattr(self, "_selection_hint", None)
            and getattr(self, "_article_read_filter", "all") == "all"
            and structural_sig == self._tree_structural_sig
        ):
            if counts_sig == self._tree_counts_sig:
                log.info("Feed tree unchanged; skipping rebuild feeds=%s", len(feeds or []))
                # A refresh can change articles without changing any tree
                # label or count (e.g. replaced content); the dirty marker is
                # the only record that the open view still needs a reload.
                if getattr(self, "_article_refresh_dirty", False):
                    self._article_refresh_dirty = False
                    self._reload_selected_articles()
                return
            log.info("Feed tree counts-only change; patching labels feeds=%s", len(feeds or []))
            try:
                self._patch_tree_unread_labels(feeds, all_cats, hierarchy)
                self._tree_counts_sig = counts_sig
                # New/removed unread articles may affect the open view; merge
                # them in without touching the tree.
                self._article_refresh_dirty = False
                self._reload_selected_articles()
                return
            except Exception:
                log.exception("Tree label patch failed; falling back to full rebuild")

        self._tree_structural_sig = structural_sig
        self._tree_counts_sig = counts_sig

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
                # A leading unread:/read: prefix restores the global filter
                # state (issue #36); the remainder identifies the view.
                rest = last_feed
                if rest.startswith("unread:"):
                    rest = rest[7:]
                    self._article_read_filter = "unread"
                    self._sync_unread_filter_menu_check()
                elif rest.startswith("read:"):
                    rest = rest[5:]
                    self._article_read_filter = "read"
                    self._sync_unread_filter_menu_check()

                if rest in ("all", ""):
                    selected_data = {"type": "all", "id": "all"}
                elif rest == "favorites:all":
                    selected_data = {"type": "all", "id": "favorites:all"}
                elif rest == "deleted:all":
                    selected_data = {"type": "all", "id": "deleted:all"}
                elif rest.startswith("smart:"):
                    selected_data = {"type": "smart", "id": rest, "smart_id": rest[len("smart:"):]}
                elif rest.startswith("category:"):
                    cat_name = rest[9:]  # Remove "category:" prefix
                    selected_data = {"type": "category", "id": cat_name}
                else:
                    selected_data = {"type": "feed", "id": rest}
        
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
            
            # Special Views. Dedicated "Unread Articles"/"Read Articles" nodes
            # were replaced by the global View > Article Filter (issue #36).
            self.all_feeds_node = self.tree.AppendItem(self.root, _("All Articles"))
            self.tree.SetItemData(self.all_feeds_node, {"type": "all", "id": "all"})

            self.unread_node = None
            self.read_node = None

            self.favorites_node = None
            try:
                if getattr(self.provider, "supports_favorites", lambda: False)():
                    self.favorites_node = self.tree.AppendItem(self.root, _("Favorites"))
                    self.tree.SetItemData(self.favorites_node, {"type": "all", "id": "favorites:all"})
            except Exception:
                self.favorites_node = None

            self.deleted_node = None
            try:
                if getattr(self.provider, "supports_restore_deleted", lambda: False)():
                    self.deleted_node = self.tree.AppendItem(self.root, _("Deleted Articles"))
                    self.tree.SetItemData(self.deleted_node, {"type": "all", "id": "deleted:all"})
            except Exception:
                self.deleted_node = None

            # Smart Folders: a container node plus one child per user-defined
            # rule-based folder. Always shown (even empty) so it is discoverable
            # for "New Smart Folder..." via its context menu.
            self.smart_root_node = None
            self.smart_folder_nodes = {}
            try:
                if getattr(self.provider, "supports_smart_folders", lambda: False)():
                    self.smart_root_node = self.tree.AppendItem(self.root, _("Smart Folders"))
                    self.tree.SetItemData(self.smart_root_node, {"type": "smart_root"})
                    for folder in (self.provider.get_smart_folders() or []):
                        sid = folder.get("id")
                        node = self.tree.AppendItem(
                            self.smart_root_node, folder.get("name") or _("Smart Folder")
                        )
                        self.tree.SetItemData(node, {"type": "smart", "id": f"smart:{sid}", "smart_id": sid})
                        self.smart_folder_nodes[sid] = node
                    if self.smart_folder_nodes:
                        self.tree.Expand(self.smart_root_node)
            except Exception:
                self.smart_root_node = None
                self.smart_folder_nodes = {}
            
            # Group feeds by category
            cat_feeds_map = {c: [] for c in all_cats}

            for feed in feeds:
                cat = feed.category or UNCATEGORIZED
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

            top_level_cats.sort(key=lambda s: category_display_name(s).lower())
            for k in children_of:
                children_of[k].sort(key=lambda s: s.lower())

            item_to_select = None
            cat_node_map = {}  # cat_title -> tree node
            cat_base_labels = {}  # cat_title -> displayed label without the count suffix

            from core.db import category_display_leaf

            # Recursive (direct feeds + nested subcategories) unread totals,
            # computed once up front so each category is summed exactly once
            # regardless of nesting depth (issue #34).
            category_unread_totals = self._compute_category_unread_totals(cat_feeds_map, children_of)

            # Global read-status filter (issue #36): when not "all", hide feeds
            # with no matching articles and categories whose whole subtree has
            # none. The tree only re-evaluates this on full rebuilds (filter
            # change / feed refresh), never mid-interaction, so nodes don't
            # vanish under the user's focus as they read articles.
            filter_mode = getattr(self, "_article_read_filter", "all")
            read_counts = None
            if filter_mode == "read":
                try:
                    getter = getattr(self.provider, "get_feed_read_counts", None)
                    read_counts = getter() if callable(getter) else None
                except Exception:
                    read_counts = None

            def _feed_matches_filter(feed):
                if filter_mode == "unread":
                    return int(getattr(feed, "unread_count", 0) or 0) > 0
                if filter_mode == "read" and read_counts is not None:
                    return int(read_counts.get(feed.id, 0) or 0) > 0
                # "all", or a provider that can't report read counts: show everything.
                return True

            _category_match_cache = {}

            def _category_matches_filter(cat):
                if filter_mode == "all":
                    return True
                cached = _category_match_cache.get(cat)
                if cached is not None:
                    return cached
                result = any(_feed_matches_filter(f) for f in cat_feeds_map.get(cat, [])) or any(
                    _category_matches_filter(child) for child in children_of.get(cat, [])
                )
                _category_match_cache[cat] = result
                return result

            def _add_category_node(cat, parent_node):
                nonlocal item_to_select
                cat_feeds = [f for f in cat_feeds_map.get(cat, []) if _feed_matches_filter(f)]
                cat_feeds.sort(key=lambda f: (f.title or "").lower())

                # The node identity is the full path; nested nodes display only
                # the leaf so the tree reads naturally for screen-reader users.
                label = (
                    category_display_name(cat)
                    if parent_node is self.root
                    else category_display_leaf(cat)
                )
                total_unread = category_unread_totals.get(cat, 0)
                display_label = f"{label} ({total_unread})" if total_unread > 0 else label
                cat_node = self.tree.AppendItem(parent_node, display_label)
                cat_data = {"type": "category", "id": cat}
                self.tree.SetItemData(cat_node, cat_data)
                cat_node_map[cat] = cat_node
                cat_base_labels[cat] = label

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
                    if _category_matches_filter(child_cat):
                        _add_category_node(child_cat, cat_node)

            for cat in top_level_cats:
                if _category_matches_filter(cat):
                    _add_category_node(cat, self.root)

            # Persist for the incremental mark-read/unread path, which patches a
            # single feed's ancestor chain without rebuilding the whole tree.
            self.cat_nodes = cat_node_map
            self.category_base_labels = cat_base_labels
            self.category_unread_totals = category_unread_totals
            self._category_hierarchy = hierarchy

            self._accessible_view_entries = build_accessible_view_entries(
                feeds,
                all_cats,
                hierarchy,
                include_favorites=bool(self.favorites_node),
            )

            self._apply_tree_expansion(cat_node_map)

            # Restore selection (default to All Feeds on first load so the list populates)
            # If "remember last feed" is enabled and this is the first load, use the saved feed
            selection_target = None

            if selected_data and selected_data.get("type") == "smart":
                smart_node = self.smart_folder_nodes.get(selected_data.get("smart_id"))
                if smart_node and smart_node.IsOk():
                    selection_target = smart_node

            if selection_target is not None:
                pass
            elif selected_data and selected_data["type"] == "all":
                if selected_data.get("id") == "favorites:all" and self.favorites_node and self.favorites_node.IsOk():
                    selection_target = self.favorites_node
                elif selected_data.get("id") == "deleted:all" and self.deleted_node and self.deleted_node.IsOk():
                    selection_target = self.deleted_node
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
            update_tray = getattr(self, "_update_tray_status_label", None)
            if callable(update_tray):
                update_tray()

        # Ensure article list refreshes after auto/remote refresh.
        # Re-selecting items on a rebuilt tree does not always emit EVT_TREE_SEL_CHANGED,
        # so explicitly trigger a load for the currently selected node.
        self._article_refresh_dirty = False
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
        if typ == "smart":
            return data.get("id")
        if typ == "category":
            return f"category:{data.get('id')}"
        return None

    def _wrap_view_id_with_filter(self, feed_id):
        """Apply the global read-status filter prefix to a view id (issue #36).

        Smart Folders and the Deleted view carry their own semantics; the
        filter must not wrap them (it would break their view id).
        """
        mode = getattr(self, "_article_read_filter", "all")
        if (
            mode in ("unread", "read")
            and feed_id
            and not feed_id.startswith(("smart:", "deleted:", "unread:", "read:"))
        ):
            return f"{mode}:{feed_id}"
        return feed_id

    def _tree_selection_feed_id(self, item):
        feed_id = self._get_feed_id_from_tree_item(item)
        if not feed_id:
            return None
        return self._wrap_view_id_with_filter(feed_id)

    def _is_tree_home_end_key(self, key) -> bool:
        keys = {
            getattr(wx, "WXK_HOME", None),
            getattr(wx, "WXK_END", None),
            getattr(wx, "WXK_NUMPAD_HOME", None),
            getattr(wx, "WXK_NUMPAD_END", None),
        }
        keys.discard(None)
        return key in keys

    def _is_tree_navigation_key(self, key) -> bool:
        # Any plain keyboard tree navigation (arrows/paging/home/end, incl. numpad)
        # defers the article-load commit so rapid arrowing keeps the UI thread free
        # for NVDA announcements. Mouse-click/programmatic selection never routes
        # through on_tree_key_down, so it sets no defer window and still commits now.
        if self._is_tree_home_end_key(key):
            return True
        keys = {
            getattr(wx, "WXK_UP", None),
            getattr(wx, "WXK_DOWN", None),
            getattr(wx, "WXK_LEFT", None),
            getattr(wx, "WXK_RIGHT", None),
            getattr(wx, "WXK_PAGEUP", None),
            getattr(wx, "WXK_PAGEDOWN", None),
            getattr(wx, "WXK_NUMPAD_UP", None),
            getattr(wx, "WXK_NUMPAD_DOWN", None),
            getattr(wx, "WXK_NUMPAD_LEFT", None),
            getattr(wx, "WXK_NUMPAD_RIGHT", None),
            getattr(wx, "WXK_NUMPAD_PAGEUP", None),
            getattr(wx, "WXK_NUMPAD_PAGEDOWN", None),
        }
        keys.discard(None)
        return key in keys

    def on_tree_key_down(self, event: wx.KeyEvent) -> None:
        try:
            key = event.GetKeyCode()
        except Exception:
            key = None

        try:
            plain = not (
                event.ControlDown()
                or event.ShiftDown()
                or event.AltDown()
                or event.MetaDown()
            )
        except Exception:
            plain = True

        if plain and self._is_tree_navigation_key(key):
            try:
                ms = int(getattr(self, "_tree_selection_debounce_ms", 120))
            except Exception:
                ms = 120
            self._tree_keyboard_nav_defer_until = time.monotonic() + max(0, ms) / 1000.0

        event.Skip()

    def _should_defer_tree_selection(self) -> bool:
        try:
            return time.monotonic() <= float(getattr(self, "_tree_keyboard_nav_defer_until", 0.0) or 0.0)
        except Exception:
            return False

    def _schedule_tree_selection_commit(self, feed_id: str) -> None:
        self._tree_pending_feed_id = feed_id
        timer = getattr(self, "_tree_selection_debounce_timer", None)
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        try:
            ms = int(getattr(self, "_tree_selection_debounce_ms", 120))
        except Exception:
            ms = 120
        self._tree_selection_debounce_timer = wx.CallLater(
            max(0, ms),
            self._commit_pending_tree_selection,
        )

    def _cancel_tree_selection_commit(self) -> None:
        self._tree_pending_feed_id = None
        timer = getattr(self, "_tree_selection_debounce_timer", None)
        self._tree_selection_debounce_timer = None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass

    def _commit_pending_tree_selection(self) -> None:
        feed_id = getattr(self, "_tree_pending_feed_id", None)
        self._tree_pending_feed_id = None
        self._tree_selection_debounce_timer = None
        if not feed_id:
            return
        try:
            current_feed_id = self._tree_selection_feed_id(self.tree.GetSelection())
        except Exception:
            current_feed_id = None
        if current_feed_id and current_feed_id != feed_id:
            return
        self._commit_tree_selection(feed_id)

    def _commit_tree_selection(self, feed_id: str) -> None:
        if not feed_id:
            return
        if feed_id == getattr(self, "current_feed_id", None):
            return

        # Save the last selected feed if the setting is enabled
        try:
            if self.config_manager.get("remember_last_feed", False):
                self.config_manager.set("last_selected_feed", feed_id)
        except Exception:
            pass

        self._select_view(feed_id)

    def _next_articles_request_id(self) -> int:
        """Return a collision-free generation for article page work."""
        generation = int(getattr(self, "_articles_request_generation", 0)) + 1
        self._articles_request_generation = generation
        self.current_request_id = generation
        return generation

    def _is_articles_load_current(self, feed_id, request_id) -> bool:
        return (
            request_id == getattr(self, "current_request_id", None)
            and feed_id == getattr(self, "current_feed_id", None)
        )

    def _begin_articles_load(self, feed_id: str, full_load: bool = True, clear_list: bool = True):
        # Track current view so auto-refresh can do a cheap "top-up" without reloading history.
        self.current_feed_id = feed_id

        if clear_list:
            self._set_base_articles([], feed_id)
            self._remove_loading_more_placeholder()
            self.list_ctrl.DeleteAllItems()
            self.list_ctrl.InsertItem(0, _("Loading..."))
            self.content_ctrl.Clear()
            self._invalidate_reader_text_tracking()

        # Use a request ID to handle race conditions (if user clicks fast / auto-refresh overlaps).
        request_id = self._next_articles_request_id()
        threading.Thread(
            target=self._load_articles_thread,
            args=(feed_id, request_id, full_load),
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

        feed_id = self._wrap_view_id_with_filter(feed_id)

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
        feed_id = self._tree_selection_feed_id(item)
        if not feed_id:
            return

        # If the feed hasn't changed (e.g. during a tree refresh where items are recreated),
        # don't reset the view. The update logic (_reload_selected_articles) handles merging new items.
        if feed_id == getattr(self, "current_feed_id", None):
            self._cancel_tree_selection_commit()
            return

        if self._should_defer_tree_selection():
            self._schedule_tree_selection_commit(feed_id)
            return

        self._cancel_tree_selection_commit()
        self._commit_tree_selection(feed_id)

    def _load_articles_thread(self, feed_id, request_id, full_load: bool = True):
        page_size = self.article_page_size
        load_started = time.perf_counter()
        try:
            # Fast-first page
            fetch_started = time.perf_counter()
            page, total = self.provider.get_articles_page(feed_id, offset=0, limit=page_size)
            fetch_ms = (time.perf_counter() - fetch_started) * 1000.0
            # Ensure stable order (newest first)
            page = page or []
            page.sort(key=lambda a: (a.timestamp, self._article_cache_id(a)), reverse=True)
            if not self._is_articles_load_current(feed_id, request_id):
                log.debug(
                    "Article page discarded as stale view=%s rows=%d stage=post-fetch fetch_ms=%.0f",
                    feed_id,
                    len(page),
                    fetch_ms,
                )
                return
            # Warm expensive per-row annotations here (loader thread), not in
            # the UI render loop.
            precompute_started = time.perf_counter()
            prepared = self._precompute_article_row_annotations(
                page,
                should_continue=lambda: self._is_articles_load_current(feed_id, request_id),
            )
            precompute_ms = (time.perf_counter() - precompute_started) * 1000.0
            if not prepared:
                log.debug(
                    "Article page preparation cancelled view=%s rows=%d fetch_ms=%.0f "
                    "precompute_ms=%.0f total_ms=%.0f",
                    feed_id,
                    len(page),
                    fetch_ms,
                    precompute_ms,
                    (time.perf_counter() - load_started) * 1000.0,
                )
                return
            log.debug(
                "Article page prepared view=%s rows=%d full=%s fetch_ms=%.0f "
                "precompute_ms=%.0f total_ms=%.0f",
                feed_id,
                len(page),
                bool(full_load),
                fetch_ms,
                precompute_ms,
                (time.perf_counter() - load_started) * 1000.0,
            )

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
            self.list_ctrl.InsertItem(0, _("No articles found."))
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
        empty_label = _("No matches.") if (self._is_search_active() and base_articles) else _("No articles found.")
        self._render_articles_list(self.current_articles, empty_label=empty_label)
        if self._is_search_active():
            try:
                self.SetStatusText(
                    _("Filter: {shown} of {total}").format(
                        shown=len(self.current_articles), total=len(base_articles)
                    )
                )
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

        empty_label = _("No matches.") if (self._is_search_active() and combined) else _("No articles found.")
        self._render_articles_list(self.current_articles, empty_label=empty_label)
        if self._is_search_active():
            try:
                self.SetStatusText(
                    _("Filter: {shown} of {total}").format(
                        shown=len(self.current_articles), total=len(combined)
                    )
                )
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
        if self._defer_restore_during_render(
            lambda: self._restore_list_view(focused_id, top_id, selected_id)
        ):
            return
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
                # Skip when the target already IS the top row: the double
                # scroll is two full-list native scrolls plus the redraw and
                # accessibility churn they trigger.
                count = self.list_ctrl.GetItemCount()
                try:
                    already_top = self.list_ctrl.GetTopItem() == target_idx
                except Exception:
                    already_top = False
                if count > 0 and not already_top:
                    self.list_ctrl.EnsureVisible(count - 1)
                    self.list_ctrl.EnsureVisible(target_idx)

    def _restore_load_more_focus(self):
        """Keep focus on the Load More row after paging for screen readers."""
        if self._defer_restore_during_render(self._restore_load_more_focus):
            return
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
        if self._defer_restore_during_render(
            lambda: self._restore_loaded_page_focus(article_id)
        ):
            return
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
        self._clear_non_title_cells(idx)
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
            # Column 0 is the item label whatever the layout, so the placeholder
            # text always goes there (see core.article_columns).
            self.list_ctrl.SetItem(count - 1, 0, label)
            self._clear_non_title_cells(count - 1)
        except Exception:
            pass

    def _clear_non_title_cells(self, row: int) -> None:
        """Blank every column except the item label, whatever the layout is.

        Placeholder rows ("Loading more...", "No articles found.") carry no
        article, so their non-title cells must be empty rather than stale.
        """
        for index in range(1, len(getattr(self, "_column_keys", []) or [])):
            self.list_ctrl.SetItem(row, index, "")

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
            if not self._is_articles_load_current(feed_id, request_id):
                wx.CallAfter(self._after_load_more, [], total, request_id, page_size)
                return
            # Warm expensive per-row annotations off the UI thread (see
            # _precompute_article_row_annotations).
            prepared = self._precompute_article_row_annotations(
                page,
                should_continue=lambda: self._is_articles_load_current(feed_id, request_id),
            )
            if not prepared:
                wx.CallAfter(self._after_load_more, [], total, request_id, page_size)
                return
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

    def _plan_incremental_list_update(self, old_display, new_display, new_ids):
        """Plan a cheap native-list update, or return ``None``.

        Returns ``(inserts, trim_count)`` when every retained old row keeps its
        relative order, every added row belongs to ``new_ids``, and any removed
        old rows form the oldest suffix. A reorder, middle removal, or
        unexpected id returns ``None`` so the caller uses the full rebuild.
        """
        inserts = []
        j = 0
        try:
            for i, art in enumerate(new_display):
                cid = self._article_cache_id(art)
                if j < len(old_display) and cid == self._article_cache_id(old_display[j]):
                    j += 1
                    continue
                if cid in new_ids:
                    inserts.append((i, art))
                    continue
                return None
        except Exception:
            return None
        # A capped top-up page removes only the oldest suffix.  Keeping this
        # count in the plan lets the caller avoid rebuilding all visible rows.
        return inserts, len(old_display) - j

    def _quick_merge_articles(self, latest_page, request_id, feed_id):
        # If a newer request was started, ignore
        if not hasattr(self, 'current_request_id') or request_id != self.current_request_id:
            return
        # Ensure we're still looking at the same view
        if feed_id != getattr(self, "current_feed_id", None):
            return
        # Rows the user has read (or unread) since the last load no longer match
        # an active unread:/read: view and must go, even when the top-up page
        # brought nothing new -- a refresh with no new entries is exactly the
        # case reported in issue #96.
        stale_rows = self._has_stale_read_filter_rows(view_id=feed_id)
        if not latest_page and not stale_rows:
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
        if not new_entries and not stale_rows:
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
        merge_path = "full"
        merge_started = time.perf_counter()
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

            # If no change in order or content after truncation, skip -- unless
            # stale rows still have to be filtered out of the displayed list.
            if not stale_rows and [self._article_cache_id(a) for a in combined] == [
                self._article_cache_id(a) for a in base_articles
            ]:
                return

            old_display = list(getattr(self, "current_articles", []) or [])
            self._set_base_articles(combined, feed_id)
            display_articles = combined
            if self._is_search_active():
                display_articles = self._filter_articles(combined, self._search_query)
            self.current_articles = self._sort_articles_for_display(display_articles)

            # Re-evaluate "Load More" placeholder (used by both merge paths).
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

            # Incremental fast path: during a refresh the overwhelmingly common
            # merge is "k new rows arrive and k oldest rows age out". A full
            # DeleteAllItems + ~400-row re-insert floods NVDA with thousands
            # of accessibility events every throttle cycle and the deferred
            # focus restore undoes any arrowing the user did meanwhile — the
            # "sluggish while feeds refresh" complaint. Inserting the new rows
            # and trimming only the oldest suffix keeps focus/selection/scroll
            # natively attached to existing items, so no full restore is needed.
            update_plan = None
            if (
                not self._is_search_active()
                and not getattr(self, "_article_render_inflight", False)
                and old_display
                # An emptied list must go through the full rebuild so the
                # "No articles found." row is announced instead of silence.
                and self.current_articles
            ):
                expected = len(old_display) + (1 if getattr(self, "_loading_more_placeholder", False) else 0)
                try:
                    count_ok = self.list_ctrl.GetItemCount() == expected
                except Exception:
                    count_ok = False
                if count_ok:
                    new_ids = {self._article_cache_id(a) for a in new_entries}
                    update_plan = self._plan_incremental_list_update(
                        old_display, self.current_articles, new_ids
                    )
                    if update_plan is not None:
                        _planned_inserts, trim_count = update_plan
                        trimmed_ids = {
                            self._article_cache_id(a)
                            for a in (old_display[-trim_count:] if trim_count else [])
                        }
                        if any(
                            anchor and anchor in trimmed_ids
                            for anchor in (focused_article_id, selected_id, top_article_id)
                        ):
                            update_plan = None

            if update_plan is not None:
                merge_path = "incremental"
                inserts, trim_count = update_plan
                if inserts or trim_count:
                    self.list_ctrl.Freeze()
                    try:
                        self._remove_loading_more_placeholder()
                        for idx in range(
                            len(old_display) - 1,
                            len(old_display) - trim_count - 1,
                            -1,
                        ):
                            self.list_ctrl.DeleteItem(idx)
                        for idx, art in inserts:
                            self._insert_article_row(idx, art)
                    finally:
                        self.list_ctrl.Thaw()
                if more:
                    self._add_loading_more_placeholder()
                else:
                    self._remove_loading_more_placeholder()
                if focused_on_load_more or selected_on_load_more:
                    wx.CallAfter(self._restore_load_more_focus)
            else:
                # Fallback: order changed, a non-suffix row disappeared, or a
                # render is still in flight — rebuild the whole list.
                self._remove_loading_more_placeholder()

                empty_label = _("No matches.") if (self._is_search_active() and combined) else _("No articles found.")
                self._render_articles_list(self.current_articles, empty_label=empty_label)
                if self._is_search_active():
                    try:
                        self.SetStatusText(
                    _("Filter: {shown} of {total}").format(
                        shown=len(self.current_articles), total=len(combined)
                    )
                )
                    except Exception:
                        pass

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

        log.debug(
            "Quick merge applied path=%s new=%d shown=%d ms=%.0f",
            merge_path,
            len(new_entries),
            len(self.current_articles or []),
            (time.perf_counter() - merge_started) * 1000.0,
        )

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
            # Incremental queue only (not _reset_fulltext_prefetch): a full reset here
            # would re-scan the whole list on every refresh top-up, starving on-demand
            # reads behind repeated slow prefetch re-attempts for the whole session.
            new_ids = {self._article_cache_id(a) for a in new_entries}
            visible_new = [a for a in self.current_articles if self._article_cache_id(a) in new_ids]
            self._queue_fulltext_prefetch(visible_new)
        except Exception:
            pass

    def on_article_select(self, event):
        if self._updating_list:
            return

        idx = event.GetIndex()
        # Focus moved to a new row: apply any Status-cell updates we deferred
        # while their rows were focused (see _set_or_defer_status_cell), now that
        # those rows are no longer the reader's focused item.
        self._flush_deferred_status_cells(except_idx=idx)
        if self._is_load_more_row(idx):
            # Keep focus on placeholder; do not try to load content
            self.selected_article_id = None
            self.content_ctrl.SetValue("")
            self._invalidate_reader_text_tracking()
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
            self.content_ctrl.SetValue(_("Loading..."))
            self._invalidate_reader_text_tracking()

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
        header += _("Date:") + f" {utils.humanize_article_date(article.date)}\n"
        header += _("Author:") + f" {article.author}\n"
        header += _("Link:") + f" {article.url}\n"
        header += "-" * 40 + "\n\n"
        
        use_rich = self._rich_view_active()
        try:
            include_images = self._show_images_for_feed(getattr(article, "feed_id", None))
            content = self._strip_html(article.content, include_images=include_images)
            full_text = header + content
            if not use_rich:
                self._set_article_reader_text(article, full_text)
        except Exception:
            pass

        # Rich reader: show cleaned feed content instantly (no network); the full
        # web extraction is fetched when the reader gains focus, mirroring the
        # plain-text reader's "feed content on select, full text on focus" flow.
        if use_rich:
            try:
                cache_key, _u, _a = self._fulltext_cache_key_for_article(article, idx)
                cached = self._fulltext_html_cache.get(cache_key)
                self._render_rich_html(cached if cached is not None else self._rich_feed_content_html(article))
            except Exception:
                log.debug("Rich feed-content render failed", exc_info=True)

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

        # macOS: VoiceOver cursor navigation never fires EVT_SET_FOCUS on the
        # reader, so the focus-triggered full-text load (on_content_focus /
        # _on_rich_view_focus) never runs and VoiceOver users only ever hear
        # the feed snippet. Mirror the accessible browser: start the load on
        # selection (debounced + token-guarded, so fast arrowing is safe).
        #
        # Forum threads get the same treatment on every platform: audiogames and
        # applevis syndicate only the opening post, so the feed-content view is a
        # single-post stub and the rest of the conversation appears only once the
        # reader is focused. Loading on selection means both the classic reader
        # and rich view show every post without a focus dance (issue: AppleVis
        # thread showed one comment).
        try:
            if (
                sys.platform == "darwin"
                or self._is_forum_thread_article(article)
                or self._is_youtube_video_article(article)
            ):
                if use_rich:
                    self._schedule_rich_load_for_index(idx, force=False)
                else:
                    self._schedule_fulltext_load_for_index(idx, force=False)
        except Exception:
            pass

    def on_content_copy(self, event):
        if copy_textctrl_selection_to_clipboard(self.content_ctrl):
            return
        event.Skip()

    def on_content_context_menu(self, event):
        """Show a localized context menu for the read-only reader (issue #73).

        The native menu wx hands a wx.TextCtrl comes from the OS and is labelled
        in the *system* language -- English on an English Windows install -- no
        matter what BlindRSS is set to. wx.Locale cannot reliably fix that
        either: it would need the wx translation catalog for that language
        present on the machine, which is not something we ship or control. So we
        build the menu ourselves from our own catalog, which always matches the
        app's language.

        Only Copy and Select All appear: the control is read-only, so Cut, Paste
        and Delete could only ever be greyed-out entries, and dead items are
        noise for a screen-reader user arrowing through the menu.

        Note this handler is not reached on MSW for the TE_RICH2 reader -- see
        on_content_key_down / on_content_right_up, which are what actually fire
        there. It is kept for the plain-control and non-MSW cases.
        """
        self._show_content_context_menu()

    @staticmethod
    def _is_context_menu_key(event):
        """True for the two keyboard ways to ask for a context menu."""
        code = event.GetKeyCode()
        if code == wx.WXK_WINDOWS_MENU:
            # Dedicated Menu/Application key.
            return True
        return (
            code == wx.WXK_F10
            and event.ShiftDown()
            and not event.ControlDown()
            and not event.AltDown()
        )

    def on_content_key_down(self, event):
        if self._is_context_menu_key(event):
            # Deliberately no event.Skip(): letting this through to the native
            # rich-edit is what raises the English menu we are replacing.
            self._show_content_context_menu()
            return
        event.Skip()

    def on_content_right_up(self, event):
        # Same reasoning as on_content_key_down: do not Skip.
        self._show_content_context_menu()

    def _show_content_context_menu(self):
        menu = wx.Menu()
        copy_item = menu.Append(wx.ID_COPY, _("&Copy") + "\tCtrl+C")
        menu.AppendSeparator()
        menu.Append(wx.ID_SELECTALL, _("Select &All") + "\tCtrl+A")

        # Copy is meaningless with nothing selected; Select All is meaningless
        # with no text. Reflect that instead of offering no-ops.
        try:
            start, end = self.content_ctrl.GetSelection()
            copy_item.Enable(start != end)
        except Exception:
            pass

        self.content_ctrl.Bind(wx.EVT_MENU, self._on_content_menu_copy, id=wx.ID_COPY)
        self.content_ctrl.Bind(wx.EVT_MENU, self._on_content_menu_select_all, id=wx.ID_SELECTALL)
        try:
            apply_menu_mnemonics(menu)
            self.content_ctrl.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _on_content_menu_copy(self, event):
        # Route through the same helper as Ctrl+C / EVT_TEXT_COPY so the menu
        # and the shortcut cannot drift apart.
        if not copy_textctrl_selection_to_clipboard(self.content_ctrl):
            try:
                self.content_ctrl.Copy()
            except Exception:
                pass

    def _on_content_menu_select_all(self, event):
        try:
            self.content_ctrl.SelectAll()
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
            # A refresh top-up merge may be mid-rebuild with the physical
            # selection transiently vacant; fall back to the logical selection
            # so focusing the reader still starts the full-text load.
            idx = self._index_of_selected_article()
            if idx is None:
                return

        self.mark_article_read(idx)
        try:
            self._mark_article_opened(self.current_articles[idx])
        except Exception:
            pass
        try:
            self._schedule_fulltext_load_for_index(idx, force=True)
        except Exception:
            pass

    def _select_content_match(self, match):
        start, end = match
        try:
            self.content_ctrl.SetSelection(start, end)
            self.content_ctrl.ShowPosition(start)
        except Exception:
            log.exception("Error selecting find match in article text")

    def _content_find_not_found(self, term):
        # Announce, don't interrupt: a modal dialog forces the screen-reader user
        # to dismiss an OK button just to keep reading. A live announcement is
        # spoken by NVDA/JAWS and leaves keyboard focus in the article text.
        self._announce(_('"{term}" was not found.').format(term=term))

    def _content_find_no_more(self, term, forward: bool):
        template = (
            _('No more occurrences of "{term}".')
            if forward
            else _('No previous occurrences of "{term}".')
        )
        self._announce(template.format(term=term))

    def _announce_event(self, event_id: str, message: str) -> None:
        """Announce a key-event message (issue #67) via the configured mode.

        Routes through the per-event announcer (speech and/or Braille through
        accessible-output2, falling back to the direct NVDA/JAWS adapters). The
        message is also mirrored to transient status field 0 for sighted users.
        Fully guarded and non-blocking; a disabled event ("none") is a no-op.
        """
        message = str(message or "").strip()
        if not message:
            return
        try:
            self.SetStatusText(message, 0)
        except Exception:
            pass
        try:
            self.announcer.announce(event_id, message)
        except Exception:
            log.debug("Announcement for %s failed", event_id, exc_info=True)

    def _announce(self, message: str) -> None:
        """Speak a short status message to the screen reader without stealing
        focus or popping a dialog.

        Best-effort and non-blocking: on Windows it first uses direct NVDA/JAWS
        speech APIs when available, then falls back to UI Automation and MSAA
        status-change events. On other platforms, or if no speech path succeeds,
        it falls back to the status bar plus a soft bell so the user still gets
        a cue. Keyboard focus never moves, so the user stays in the article text
        after Find.
        """
        message = str(message or "").strip()
        if not message:
            return
        # Reflect the message in transient status field 0 (see init_ui) as well:
        # harmless, and gives sighted users / a status query the same text.
        try:
            self.SetStatusText(message, 0)
        except Exception:
            pass
        try:
            self._announce_status_changed()
        except Exception:
            pass
        # Direct speech: NVDA/JAWS on Windows, `say` on macOS. Both give the
        # screen-reader user spoken confirmation the status bar alone does not.
        if (sys.platform.startswith("win") or sys.platform == "darwin") and \
                screen_reader_announce.speak_status(message, interrupt=True):
            return
        if sys.platform.startswith("win") and self._announce_via_uia(message):
            return
        try:
            wx.Bell()
        except Exception:
            pass

    def _announce_status_changed(self) -> None:
        """Tell MSAA clients the status-bar text changed.

        UIA notifications are the primary speech path on modern Windows, but
        NVDA/JAWS also listen to classic MSAA events in wx/Win32 apps. Raising
        this after SetStatusText gives them a queryable status object without
        moving keyboard focus.
        """
        try:
            status_bar = self.GetStatusBar()
        except Exception:
            status_bar = None
        if not status_bar:
            return
        try:
            notify = wx.Accessible.NotifyEvent
            objid = getattr(wx, "OBJID_CLIENT", -4)
            childid = getattr(wx, "ACC_SELF", 0)
            for event_type in (
                getattr(wx, "ACC_EVENT_OBJECT_VALUECHANGE", None),
                getattr(wx, "ACC_EVENT_OBJECT_NAMECHANGE", None),
                getattr(wx, "ACC_EVENT_SYSTEM_ALERT", None),
            ):
                if event_type is not None:
                    notify(event_type, status_bar, objid, childid)
        except Exception:
            pass

    def _announcement_hwnds(self):
        """Return native window handles to try as UIA notification sources."""
        hwnds = []

        def add_window(window):
            if not window:
                return
            try:
                hwnd = int(window.GetHandle())
            except Exception:
                hwnd = 0
            if hwnd and hwnd not in hwnds:
                hwnds.append(hwnd)

        try:
            add_window(self._get_focused_window())
        except Exception:
            pass
        try:
            add_window(self.content_ctrl)
        except Exception:
            pass
        try:
            add_window(self.GetStatusBar())
        except Exception:
            pass
        add_window(self)
        return hwnds

    def _announce_via_uia(self, message: str) -> bool:
        """Raise a Windows UI Automation notification so NVDA/JAWS speak `message`.

        Returns True if the notification was raised. Fully guarded: any failure
        (older Windows without the notification API, missing DLL, COM error)
        returns False so the caller can fall back.
        """
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return False
        hwnds = self._announcement_hwnds()
        if not hwnds:
            return False
        try:
            core = ctypes.oledll.UIAutomationCore
            oleaut32 = ctypes.windll.oleaut32
        except Exception:
            return False

        oleaut32.SysAllocString.restype = ctypes.c_void_p
        oleaut32.SysAllocString.argtypes = [ctypes.c_wchar_p]
        oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
        oleaut32.SysFreeString.restype = None

        core.UiaHostProviderFromHwnd.argtypes = [wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)]
        core.UiaHostProviderFromHwnd.restype = ctypes.HRESULT
        core.UiaRaiseNotificationEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ]
        core.UiaRaiseNotificationEvent.restype = ctypes.HRESULT

        bstr = None
        activity = None
        try:
            bstr = oleaut32.SysAllocString(message)
            activity = oleaut32.SysAllocString("blindrss.find")
            if not bstr or not activity:
                return False
            for hwnd in hwnds:
                provider = ctypes.c_void_p()
                try:
                    # HRESULT UiaHostProviderFromHwnd(HWND, IRawElementProviderSimple**)
                    hr = core.UiaHostProviderFromHwnd(wintypes.HWND(hwnd), ctypes.byref(provider))
                    if hr != 0 or not provider:
                        continue
                    # NotificationKind_ActionAborted = 3 (the find action produced nothing),
                    # NotificationProcessing_ImportantAll = 0 (never coalesced away).
                    hr = core.UiaRaiseNotificationEvent(provider, 3, 0, bstr, activity)
                    if hr == 0:
                        return True
                except Exception:
                    continue
                finally:
                    if provider:
                        # Release the host provider (IUnknown::Release is vtable slot 2).
                        try:
                            vtbl = ctypes.cast(provider, ctypes.POINTER(ctypes.c_void_p))[0]
                            release_ptr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[2]
                            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(release_ptr)
                            release(provider)
                        except Exception:
                            pass
            return False
        except Exception:
            return False
        finally:
            if bstr:
                try:
                    oleaut32.SysFreeString(bstr)
                except Exception:
                    pass
            if activity:
                try:
                    oleaut32.SysFreeString(activity)
                except Exception:
                    pass

    def on_find_in_article(self, event=None):
        text = ""
        try:
            text = self.content_ctrl.GetValue()
        except Exception:
            text = ""
        if not text.strip():
            return
        dlg = wx.TextEntryDialog(self, _("Find in article:"), _("Find"), self._content_find_term or "")
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            term = dlg.GetValue().strip()
        finally:
            dlg.Destroy()
        if not term:
            return
        self._content_find_term = term
        try:
            start = self.content_ctrl.GetInsertionPoint()
        except Exception:
            start = 0
        match = self._find_in_text(text, term, start, forward=True, wrap=True)
        if match:
            self._select_content_match(match)
        else:
            self._content_find_not_found(term)

    def on_find_next_in_article(self, event=None):
        if not self._content_find_term:
            return self.on_find_in_article()
        text = ""
        try:
            text = self.content_ctrl.GetValue()
        except Exception:
            text = ""
        if not text:
            return
        try:
            sel = self.content_ctrl.GetSelection()
            start = max(sel)
        except Exception:
            start = 0
        # F3 deliberately does not wrap: hitting the last match and pressing F3
        # again should say so, not silently jump back to the top (issue report).
        match = self._find_in_text(text, self._content_find_term, start, forward=True, wrap=False)
        if match:
            self._select_content_match(match)
        else:
            self._content_find_no_more(self._content_find_term, forward=True)

    def on_find_prev_in_article(self, event=None):
        if not self._content_find_term:
            return self.on_find_in_article()
        text = ""
        try:
            text = self.content_ctrl.GetValue()
        except Exception:
            text = ""
        if not text:
            return
        try:
            sel = self.content_ctrl.GetSelection()
            start = min(sel)
        except Exception:
            start = 0
        match = self._find_in_text(text, self._content_find_term, start, forward=False, wrap=False)
        if match:
            self._select_content_match(match)
        else:
            self._content_find_no_more(self._content_find_term, forward=False)

    def _fulltext_cache_key_for_article(self, article, idx: int):
        url = (getattr(article, "url", None) or "").strip()
        article_id = getattr(article, "id", None) or getattr(article, "article_id", None) or str(idx)
        cache_key = url if url else f"article:{article_id}"
        suffix = self._translation_fulltext_cache_suffix()
        if suffix:
            cache_key = f"{cache_key}{suffix}"
        return cache_key, url, str(article_id)

    def _index_of_selected_article(self) -> int | None:
        """Index of the logically selected article in current_articles.

        During a refresh top-up merge the list control is rebuilt in timer
        batches and the physical selection stays vacant until the deferred
        restore runs, so callers that need "the article the user is on" must
        fall back to selected_article_id rather than GetFirstSelected().
        """
        target_id = getattr(self, "selected_article_id", None)
        if not target_id:
            return None
        try:
            for i, article in enumerate(getattr(self, "current_articles", []) or []):
                if self._article_cache_id(article) == target_id:
                    return i
        except Exception:
            pass
        return None

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
                    self.SetStatusText(_("Translation failed: {error}").format(error=msg))
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
        # Compare against the translated notes as well: the notes below are
        # emitted through gettext, so an English-only check silently fails
        # for every non-English UI.
        notes = (
            "full-text extraction failed. showing feed content.",
            "no webpage url for this item. showing feed content.",
            _("Full-text extraction failed. Showing feed content.").lower(),
            _("No webpage URL for this item. Showing feed content.").lower(),
        )
        if any(note in low for note in notes):
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
            "feed_id": str(getattr(article, "feed_id", "") or ""),
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
                self._set_article_reader_text(article, cached, reset_insertion=True)
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

        # A refresh top-up merge can rebuild the list between scheduling and
        # now, shifting rows (the scheduled index would fetch the wrong
        # article) or leaving the physical selection vacant mid-rebuild.
        # Resolve the target by the logical selection id; fall back to the
        # positional checks only when no logical selection exists.
        if getattr(self, "selected_article_id", None):
            resolved = self._index_of_selected_article()
            if resolved is None:
                # Selected article is no longer in the (possibly truncated) view.
                return
            idx = resolved
        else:
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
                self._set_article_reader_text(article, cached, reset_insertion=True)
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

    def _fulltext_apply_result(self, cache_key, rendered, cacheable, cache_source, token_snapshot):
        """Deliver a finished on-demand extraction on the UI thread.

        Cache upkeep and the in-flight guard release must not depend on the
        list control's physical selection: refresh top-up merges rebuild the
        list every ~120ms and leave it selection-less while row batches are
        re-inserted. Discarding the result here (uncached, guard still set)
        used to lock the article out of full text until the refresh stopped
        churning, because the stale guard turned every retry into a silent
        no-op in _start_fulltext_load.
        """
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
        if getattr(self, "_fulltext_loading_url", None) == cache_key:
            self._fulltext_loading_url = None

        # Apply to the reader only if the user is still on this article.
        if token_snapshot is not None and token_snapshot != int(getattr(self, "_fulltext_token", 0)):
            return
        try:
            idx_now = self.list_ctrl.GetFirstSelected()
        except Exception:
            idx_now = -1
        if idx_now is None or idx_now < 0 or idx_now >= len(self.current_articles):
            # Mid-rebuild vacancy: resolve by the logical selection instead.
            idx_now = self._index_of_selected_article()
            if idx_now is None:
                return
        article_now = self.current_articles[idx_now]
        cur_key, _cur_url, _aid = self._fulltext_cache_key_for_article(article_now, idx_now)
        if cur_key != cache_key:
            return
        try:
            self._set_article_reader_text(article_now, rendered, reset_insertion=True)
            self._announce_fulltext_loaded_macos(authoritative=bool(cacheable))
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

            # Structured-metadata enrichment (core.metadata_enrich): harvest
            # author/tags from page HTML the extraction below already fetches,
            # so Filter Rules matching on author/tag work on feeds that omit
            # them. Local-provider articles only (no-op for hosted rows) and
            # strictly best-effort — never interferes with rendering.
            article_id_for_meta = str(req.get("article_id") or "").strip()

            def _metadata_sink(html, page_url, _aid=article_id_for_meta):
                if not _aid:
                    return

                def _enrich():
                    try:
                        from core import metadata_enrich
                        metadata_enrich.enrich_stored_article(_aid, html, page_url)
                    except Exception:
                        pass

                # Off the extraction worker: the enrichment UPDATE can wait on
                # SQLite's write lock while a refresh is saving feeds, and the
                # sink runs between page download and text extraction — doing
                # it inline stalled rendering for the duration of the refresh.
                try:
                    threading.Thread(target=_enrich, daemon=True).start()
                except Exception:
                    pass

            if is_prefetch:
                # Background prefetch uses provider-side fetch only (avoids hammering sites).
                provider_html = None
                try:
                    provider_html = self._provider_fetch_full_content(req.get("article_id"), url)
                except Exception as e:
                    if not err: err = str(e) or _("Unknown error")
                if provider_html:
                    _metadata_sink(provider_html, url)
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
                        if not err: err = str(e) or _("Unknown error")
                        rendered = None
            else:
                if is_web_eligible:
                    prefer_feed_first = self._should_prefer_feed_fulltext(url, fallback_html)

                # Try web extraction first (no fallback HTML so we can tell if it really worked).
                if not rendered and is_web_eligible:
                    # Per-feed full-text encoding override (issue #75). Passed as a
                    # kwarg only when set so test doubles without it keep working.
                    encoding_kwargs = {}
                    try:
                        _enc_fid = str(req.get("feed_id") or "").strip()
                        if _enc_fid:
                            from core import db as _enc_db
                            _enc = str((_enc_db.get_feed_settings(_enc_fid) or {}).get("fulltext_encoding") or "").strip()
                            if _enc:
                                encoding_kwargs["encoding"] = _enc
                    except Exception:
                        encoding_kwargs = {}
                    try:
                        rendered = article_extractor.render_full_article(
                            url,
                            fallback_html=fallback_html if prefer_feed_first else "",
                            fallback_title=fallback_title,
                            fallback_author=fallback_author,
                            prefer_feed_content=prefer_feed_first,
                            metadata_sink=_metadata_sink,
                            **encoding_kwargs,
                        )
                        render_source = "feed_preferred" if prefer_feed_first else "web"
                    except Exception as e:
                        err = str(e) or _("Unknown error")
                        rendered = None

                # If web extraction failed, try provider-side fetch.
                if not rendered:
                    provider_html = None
                    try:
                        provider_html = self._provider_fetch_full_content(req.get("article_id"), url)
                    except Exception as e:
                        if not err: err = str(e) or _("Unknown error")
                    if provider_html:
                        _metadata_sink(provider_html, url)
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
                            if not err: err = str(e) or _("Unknown error")
                            rendered = None

            if not rendered:
                if is_prefetch and is_web_eligible:
                    # Don't cache feed-content fallback during prefetch; let on-demand loads retry.
                    continue
                # Fallback: show feed content (cleaned) rather than a blank failure message.
                note_lines = []
                if not url:
                    note_lines.append(f'{_("No webpage URL for this item. Showing feed content.")}\n\n')
                else:
                    note_lines.append(f'{_("Full-text extraction failed. Showing feed content.")}\n\n')
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
                        stripped_fallback = (self._strip_html(fallback_html) or "").strip()
                    except Exception:
                        stripped_fallback = ""
                    final_text += stripped_fallback or _("No text available.\n")
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
                try:
                    wx.CallAfter(
                        self._fulltext_apply_result,
                        cache_key,
                        rendered,
                        cacheable,
                        cache_source,
                        token_snapshot,
                    )
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

    def _cache_article_chapters(self, article_cache_id, chapters) -> None:
        chapter_list = list(chapters or [])
        seen = set()
        collections = [
            getattr(self, "current_articles", []) or [],
            getattr(self, "_base_articles", []) or [],
        ]
        try:
            with self._view_cache_lock:
                collections.extend(
                    state.get("articles", []) or []
                    for state in (getattr(self, "view_cache", {}) or {}).values()
                )
        except Exception:
            pass

        for articles in collections:
            for article in articles:
                marker = id(article)
                if marker in seen:
                    continue
                seen.add(marker)
                if self._article_cache_id(article) == article_cache_id:
                    try:
                        article.chapters = chapter_list
                    except Exception:
                        pass

    def _update_article_chapter_indicator(self, article_cache_id) -> None:
        try:
            for idx, article in enumerate(getattr(self, "current_articles", []) or []):
                if self._article_cache_id(article) == article_cache_id:
                    self.list_ctrl.SetItem(idx, 0, self._get_display_title(article))
                    return
        except Exception:
            pass

    def _format_article_chapters_text(self, chapters) -> str:
        chapter_list = list(chapters or [])
        lines = [_("Chapters ({count}):").format(count=len(chapter_list))]
        for chapter in chapter_list:
            timestamp = self._format_chapter_timestamp(chapter.get("start", 0))
            title = str(chapter.get("title", "") or "").strip() or _("Untitled chapter")
            line = f"{timestamp}, {title}"
            href = str(chapter.get("href", "") or "").strip()
            if href:
                line += _(". Link: {url}").format(url=href)
            lines.append(line)
        return "\n\n" + "\n".join(lines) + "\n"

    def _remove_trailing_article_chapters_text(self, text: str, chapters) -> str:
        """Remove a previously rendered trailing chapter section from reader text."""
        value = str(text or "")
        chapter_list = list(chapters or [])
        if not chapter_list:
            return value
        chapter_text = self._format_article_chapters_text(chapter_list)
        if value.endswith(chapter_text):
            return value[:-len(chapter_text)]
        stripped_chapters = chapter_text.strip()
        if value.rstrip().endswith(stripped_chapters):
            return value.rstrip()[:-len(stripped_chapters)].rstrip()
        return value

    def _append_chapters(self, article_cache_id, chapters):
        chapter_list = list(chapters or [])
        if not chapter_list:
            return
        selected_article = None
        previous_chapters = []
        try:
            for article in getattr(self, "current_articles", []) or []:
                if self._article_cache_id(article) == article_cache_id:
                    selected_article = article
                    previous_chapters = list(getattr(article, "chapters", None) or [])
                    break
        except Exception:
            pass
        self._cache_article_chapters(article_cache_id, chapter_list)
        self._update_article_chapter_indicator(article_cache_id)

        # Complete YouTube full text already owns its chapter section.  Keep
        # chapter cache/player navigation, but do not rebuild the entire reader
        # a second time when this independent chapter request completes.
        if selected_article is not None and _article_is_youtube_video(selected_article):
            return

        # Verify selection hasn't changed
        if hasattr(self, 'selected_article_id') and self.selected_article_id == article_cache_id:
            try:
                current_text = self.content_ctrl.GetValue()
            except Exception:
                current_text = ""
            base_text = self._remove_trailing_article_chapters_text(current_text, previous_chapters)
            displayed = self._compose_article_reader_text(
                base_text,
                article=selected_article,
                chapters=chapter_list,
            )
            if displayed == current_text:
                return

            insertion_point = None
            selection = None
            try:
                insertion_point = self.content_ctrl.GetInsertionPoint()
                selection = self.content_ctrl.GetSelection()
            except Exception:
                pass
            self.content_ctrl.SetValue(displayed)
            # Writing the reader directly: keep the memo describing what the
            # control actually holds (issue #91).
            self._reader_displayed_text = displayed
            force_ltr_reading(self.content_ctrl)
            try:
                if selection is not None:
                    self.content_ctrl.SetSelection(*selection)
                elif insertion_point is not None:
                    self.content_ctrl.SetInsertionPoint(insertion_point)
            except Exception:
                pass

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

        # Propagate the actually-applied change (clamping above can make this
        # differ from the requested delta) up the category ancestor chain.
        self._update_category_unread_chain_ui(getattr(feed, "category", None), new_count - old_count)
        update_tray = getattr(self, "_update_tray_status_label", None)
        if callable(update_tray):
            update_tray()

    def _update_category_unread_chain_ui(self, category: str | None, delta: int) -> None:
        """Patch the aggregated unread total on a category and every ancestor (issue #34).

        Used by the single-feed mark-read/unread path so a click doesn't require
        rebuilding the whole tree just to keep parent category counts honest.
        Walks up via ``_category_hierarchy`` ({category: parent_category}, built
        by the last full ``_update_tree``); a ``seen`` guard makes this a no-op
        instead of an infinite loop if that map were ever inconsistent.
        """
        category = (category or "").strip() or UNCATEGORIZED
        if delta == 0:
            return

        seen = set()
        cat = category
        while cat and cat not in seen:
            seen.add(cat)
            old_total = int(self.category_unread_totals.get(cat, 0) or 0)
            new_total = max(0, old_total + delta)
            self.category_unread_totals[cat] = new_total

            node = self.cat_nodes.get(cat)
            if node and node.IsOk():
                base_label = self.category_base_labels.get(cat, cat)
                label = f"{base_label} ({new_total})" if new_total > 0 else base_label
                try:
                    self.tree.SetItemText(node, label)
                except Exception:
                    pass

            cat = self._category_hierarchy.get(cat)

    def _set_or_defer_status_cell(self, idx, article, label) -> None:
        """Update a row's Status cell — but never while that row is the focused item.

        Mutating a SysListView32 item in place (SetItem) while it is the live
        focused item leaves its MSAA column children inconsistent (childCount > 0
        but no reachable children). That breaks NVDA column-review add-ons, which
        read the focused item's cells and crash on the missing children. Since the
        first article in every view is auto-selected and auto-marked-read, its row
        was being mutated out from under the reader. Defer the cell update while
        the row is focused; _flush_deferred_status_cells applies it once focus
        moves elsewhere. The article model is already updated, so the correct
        status also re-materializes on any later full render.
        """
        deferred = getattr(self, "_deferred_status_cells", None)
        if deferred is None:
            deferred = self._deferred_status_cells = {}
        cache_id = self._article_cache_id(article)
        try:
            focused = self.list_ctrl.GetFocusedItem()
        except Exception:
            focused = -1
        if idx == focused:
            if cache_id is not None:
                deferred[cache_id] = label
            return
        try:
            if idx < self.list_ctrl.GetItemCount():
                self._set_col(idx, article_columns.KEY_STATUS, label)
        except Exception:
            pass
        if cache_id is not None:
            deferred.pop(cache_id, None)

    def _flush_deferred_status_cells(self, except_idx: int = -1) -> None:
        """Apply status-cell updates deferred while their rows were focused."""
        deferred = getattr(self, "_deferred_status_cells", None)
        if not deferred:
            return
        try:
            by_id = {
                self._article_cache_id(a): i
                for i, a in enumerate(getattr(self, "current_articles", []) or [])
            }
        except Exception:
            return
        for cache_id, label in list(deferred.items()):
            i = by_id.get(cache_id)
            if i is None or i == except_idx:
                continue
            try:
                if i < self.list_ctrl.GetItemCount():
                    self._set_col(i, article_columns.KEY_STATUS, label)
            except Exception:
                pass
            deferred.pop(cache_id, None)

    def mark_article_read(self, idx):
        if idx < 0 or idx >= len(self.current_articles):
            return
        article = self.current_articles[idx]
        if not article.is_read:
            threading.Thread(target=self.provider.mark_read, args=(article.id,), daemon=True).start()
            article.is_read = True
            # Mid-rebuild the row may not be inserted yet; the pending render
            # batch will pick the status up from the article model.
            self._set_or_defer_status_cell(idx, article, _("Read"))
            self._update_feed_unread_count_ui(article.feed_id, -1)
            self._sync_read_flag_in_cached_views(self._article_cache_id(article), True)

    def mark_article_unread(self, idx):
        if idx < 0 or idx >= len(self.current_articles):
            return
        article = self.current_articles[idx]
        if article.is_read:
            threading.Thread(target=self.provider.mark_unread, args=(article.id,), daemon=True).start()
            article.is_read = False
            self._set_or_defer_status_cell(idx, article, _("Unread"))
            self._update_feed_unread_count_ui(article.feed_id, 1)
            self._sync_read_flag_in_cached_views(self._article_cache_id(article), False)

    def toggle_selected_article_read_status(self):
        """Toggle read/unread on the selected article.

        Returns the new status label ("Read"/"Unread", matching the Status
        column) so keyboard callers can announce it (issue #67), or None when
        there was nothing to toggle.
        """
        idx = self._get_selected_article_index()
        if idx == wx.NOT_FOUND:
            return None
        if self._is_load_more_row(idx):
            return None
        if idx < 0 or idx >= len(self.current_articles):
            return None
        article = self.current_articles[idx]
        if bool(getattr(article, "is_read", False)):
            self.mark_article_unread(idx)
            return _("Unread")
        self.mark_article_read(idx)
        return _("Read")

    def on_mark_all_read(self, event=None):
        # File menu entry: global scope (issue #39). Per-feed/category marking
        # lives in the tree context menu via _confirm_and_mark_all_read.
        self._confirm_and_mark_all_read("all", _("Mark all items in all feeds as read?"))

    def _confirm_and_mark_all_read(self, view_id: str, prompt: str):
        view_id = str(view_id or "").strip()
        if not view_id:
            return
        try:
            if wx.MessageBox(prompt, _("Mark All as Read"), wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
                return
        except Exception:
            pass
        threading.Thread(target=self._mark_all_read_thread, args=(view_id,), daemon=True).start()

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
            err = str(e) or _("Unknown error")
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

    def _view_id_without_read_filter(self, view_id: str) -> str:
        view_id = str(view_id or "").strip()
        if view_id.startswith("unread:"):
            return view_id[7:]
        if view_id.startswith("read:"):
            return view_id[5:]
        return view_id

    def _mark_all_read_feed_ids_for_view(self, view_id: str) -> list[str]:
        """Feed ids whose unread counts should be zeroed after Mark All Read.

        This intentionally patches the existing tree instead of rebuilding it
        so Unread Only does not remove the focused feed under keyboard users.
        """
        raw_view_id = self._view_id_without_read_filter(view_id)
        feeds = getattr(self, "feed_map", {}) or {}
        if not raw_view_id:
            return []
        if raw_view_id == "all":
            return list(feeds.keys())
        if raw_view_id.startswith("category:"):
            category = raw_view_id.split(":", 1)[1]
            from core.db import CATEGORY_PATH_SEP
            result = []
            for fid, feed in feeds.items():
                feed_category = str(getattr(feed, "category", "") or UNCATEGORIZED)
                if feed_category == category or feed_category.startswith(category + CATEGORY_PATH_SEP):
                    result.append(fid)
            return result
        if raw_view_id.startswith(("favorites:", "fav:", "starred:", "smart:", "deleted:")):
            return []
        return [raw_view_id] if raw_view_id in feeds else []

    def _apply_mark_all_read_tree_updates(self, view_id: str) -> None:
        for fid in self._mark_all_read_feed_ids_for_view(view_id):
            feed = (getattr(self, "feed_map", {}) or {}).get(fid)
            try:
                unread = int(getattr(feed, "unread_count", 0) or 0)
            except Exception:
                unread = 0
            if unread > 0:
                self._update_feed_unread_count_ui(fid, -unread)

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
            msg = _("Failed to mark all items as read.")
            if err:
                msg += f"\n\n{err}"
            wx.MessageBox(msg, _("Error"), wx.ICON_ERROR)
            return

        if not unread_ids and not used_direct:
            try:
                wx.MessageBox(_("All items are already marked as read."), _("Mark All as Read"), wx.ICON_INFORMATION)
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
                            self._set_col(i, article_columns.KEY_STATUS, _("Read"))
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            self._apply_mark_all_read_tree_updates(feed_id)
        except Exception:
            pass

        # Clear cached views so filtered lists refresh correctly.
        try:
            with self._view_cache_lock:
                self.view_cache.clear()
        except Exception:
            pass

        try:
            # Reload the view the user is looking at, not the marked one: a
            # context-menu mark on another feed/category must not hijack the
            # current selection.
            self._begin_articles_load(
                getattr(self, "current_feed_id", None) or feed_id,
                full_load=True,
                clear_list=True,
            )
        except Exception:
            pass

    def on_article_activate(self, event):
        # Double click or Enter
        # wxMSW also synthesizes ITEM_ACTIVATED for plain Space in a
        # wx.ListCtrl; ignore it so Space stays the native selection toggle
        # instead of playing audio / opening the article in the browser.
        try:
            if wx.GetKeyState(wx.WXK_SPACE):
                return
        except Exception:
            pass
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

        try:
            self._mark_article_opened(article)
        except Exception:
            pass

        if self._should_play_in_player(article):
            media_url, use_ytdlp = self._playback_target_for_article(article)
            article_url = str(getattr(article, "url", "") or "").strip()

            if not media_url:
                if article_url:
                    self._open_article_url(article_url)
                return

            chapters = getattr(article, "chapters", None)

            pw = self._ensure_player_window()
            if not pw:
                return

            try:
                if pw.is_current_media(getattr(article, "id", None), media_url):
                    if chapters and list(getattr(pw, "current_chapters", []) or []) != list(chapters):
                        try:
                            pw.update_chapters(chapters)
                        except Exception:
                            log.exception("Error updating chapters for current article")
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

            if not chapters:
                try:
                    pw.update_chapters([])
                except Exception:
                    log.exception("Error clearing chapters before media load")

            pw.load_media(
                media_url,
                use_ytdlp,
                chapters,
                title=getattr(article, "title", None),
                article_id=getattr(article, "id", None),
            )

            # If this item is in the play queue, remember its position so that
            # finishing it auto-advances to the next queued item.
            try:
                self._current_queue_index = self._queue_index_for_article(article)
            except Exception:
                self._current_queue_index = None

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
            self._open_article_url(article_url)

    def _open_article_url(self, url) -> None:
        """Open an article link using the configured method (issue #31).

        With the "custom" method, runs the user's command template (``%1`` ->
        URL); on any failure it reports the error and falls back to the default
        browser so the user still gets their article. The "Open in Default
        Browser" action bypasses this and always uses the OS default.
        """
        url = str(url or "").strip()
        if not url:
            return
        method = str(self.config_manager.get("article_open_method", "default") or "default").lower()
        if method == "custom":
            template = str(self.config_manager.get("article_open_command", "") or "").strip()
            if template:
                ok, err = utils.launch_open_command(template, url)
                if ok:
                    return
                log.warning("Custom article-open command failed: %s", err)
                wx.MessageBox(
                    _(
                        "Could not open the article with your custom command:\n\n{err}\n\n"
                        "Opening in the default browser instead. You can change this in "
                        "Settings > General > Article opening method."
                    ).format(err=err),
                    _("Custom command failed"),
                    wx.ICON_WARNING,
                )
        webbrowser.open(url)

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
                wx.CallAfter(self._apply_chapters_for_player, article_id, chapters, media_url)
            except Exception:
                pass

    def _apply_chapters_for_player(
        self,
        article_id: str,
        chapters: list[dict],
        media_url: str | None = None,
    ) -> None:
        chapter_list = list(chapters or [])
        matching_cache_ids = []
        try:
            for a in getattr(self, "current_articles", []) or []:
                if getattr(a, "id", None) == article_id:
                    try:
                        a.chapters = chapter_list
                        matching_cache_ids.append(self._article_cache_id(a))
                    except Exception:
                        pass
        except Exception:
            pass
        for article_cache_id in matching_cache_ids:
            self._cache_article_chapters(article_cache_id, chapter_list)
            self._update_article_chapter_indicator(article_cache_id)

        try:
            pw = getattr(self, "player_window", None)
            if not pw:
                return
            current_article_id = getattr(pw, "current_article_id", None)
            if current_article_id is not None and article_id is not None:
                is_current = str(current_article_id) == str(article_id)
            else:
                is_current = bool(pw.is_current_media(article_id, media_url))
            if is_current:
                pw.update_chapters(chapter_list)
        except Exception:
            pass

    def _article_media_label(self, article) -> str:
        """Column text telling the user at a glance whether an article has media.

        The has-media base label is memoized on the Article object (same
        rationale/lifetime as _article_description_preview's cache): the first
        computation may run yt-dlp's extractor URL matching, which is too slow
        for the list-render loop, so _precompute_article_row_annotations warms
        it off the UI thread. The length/played annotation appended for media
        items is a cheap dict lookup and is recomputed each render so it stays
        fresh as playback progresses.
        """
        base = getattr(article, "_media_label_cached", None)
        if base is None:
            try:
                # Skip the download-index/disk lookup here: it runs once per rendered
                # row, and any downloadable article already has a media/ytdlp URL that
                # the cheaper checks below catch.
                has_media = bool(self._should_play_in_player(article, include_downloads=False))
            except Exception:
                has_media = False
            base = _(ARTICLE_MEDIA_YES) if has_media else _(ARTICLE_MEDIA_NO)
            try:
                article._media_label_cached = base
                article._has_media_cached = has_media
            except Exception:
                pass
        else:
            has_media = bool(getattr(article, "_has_media_cached", base != _(ARTICLE_MEDIA_NO)))
        if not has_media:
            return base
        annotation = ""
        try:
            st = self._playback_state_for_article(article)
            annotation = self._playback_time_annotation(st)
        except Exception:
            annotation = ""
        return f"{base}, {annotation}" if annotation else base

    def _precompute_article_row_annotations(self, articles, should_continue=None) -> bool:
        """Warm per-article row annotations OFF the UI thread.

        First-time computation of the description preview (full HTML->text
        parse) and the media label (yt-dlp extractor URL matching) measured
        ~2.6ms/article on real data — over 1s of UI-thread time for a 400-row
        page, spread across the wx.CallAfter render batches. That stall is
        exactly the lag felt when arrowing onto a large category or tabbing
        into the list while rows are still appending. Both helpers memoize on
        the Article object, so after this runs on the loader thread the render
        loop only reads precomputed strings. Safe off-thread: both paths are
        pure string/URL work (no wx, no DB writes).

        The brief sleep every few articles matters: this loop is seconds of
        CPU-bound Python, and without explicit yields it starves the wx main
        thread via the GIL (measured 60ms+ dispatch stalls during a load —
        felt as tree/list lag under a screen reader).
        """
        for i, article in enumerate(list(articles or [])):
            if should_continue is not None and not should_continue():
                return False
            try:
                self._article_description_preview(article)
                self._article_media_label(article)
            except Exception:
                continue
            if i % 16 == 15:
                time.sleep(0.001)
        return should_continue is None or bool(should_continue())

    def _should_play_in_player(self, article, include_downloads: bool = True):
        """Only treat bona-fide podcast/media items as playable; everything else opens in browser."""
        try:
            if include_downloads:
                local_resolver = getattr(self, "_downloaded_media_path_for_article", None)
                if callable(local_resolver) and local_resolver(article):
                    return True
        except Exception:
            pass
        
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

    def _playback_target_for_article(self, article):
        """Return (url_or_path, use_ytdlp), preferring a completed local download."""
        if not article:
            return None, False

        local_path = self._downloaded_media_path_for_article(article)
        if local_path:
            return local_path, False

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

        return media_url, use_ytdlp

    def _download_index(self) -> dict:
        try:
            raw = self.config_manager.get("downloaded_media", {})
        except Exception:
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def _download_provider_name(self) -> str:
        try:
            if getattr(self, "provider", None) and hasattr(self.provider, "get_name"):
                name = self.provider.get_name()
                if name:
                    return str(name)
        except Exception:
            pass
        try:
            name = self.config_manager.get("active_provider", "")
            if name:
                return str(name)
        except Exception:
            pass
        return ""

    def _download_index_key(self, kind: str, value: str) -> str | None:
        value = str(value or "").strip()
        if not value:
            return None
        digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()
        return f"{kind}:{digest}"

    def _download_index_keys(self, article) -> list[str]:
        if not article:
            return []
        provider_name = self._download_provider_name()
        feed_id = str(getattr(article, "feed_id", "") or "")
        values = []
        try:
            cache_id = self._article_cache_id(article)
        except Exception:
            cache_id = getattr(article, "cache_id", None) or getattr(article, "id", None)
        if cache_id:
            values.append(("article", f"{provider_name}|{cache_id}"))
        article_id = getattr(article, "id", None)
        if article_id:
            values.append(("article-id", f"{provider_name}|{feed_id}|{article_id}"))
        media_url = str(getattr(article, "media_url", "") or "").strip()
        if media_url:
            values.append(("media", media_url))
        article_url = str(getattr(article, "url", "") or "").strip()
        if article_url:
            values.append(("url", article_url))

        keys = []
        seen = set()
        for kind, value in values:
            key = self._download_index_key(kind, value)
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def _coerce_existing_local_media_path(self, value) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        path = raw
        try:
            drive, _tail = os.path.splitdrive(raw)
            if not drive and not raw.startswith(("\\\\", "//")):
                parts = urlsplit(raw)
                scheme = (parts.scheme or "").lower()
                if scheme == "file":
                    path = url2pathname(parts.path or "")
                    if parts.netloc:
                        path = os.path.join(f"//{parts.netloc}", path.lstrip("/\\"))
                elif scheme:
                    return None
        except Exception:
            path = raw
        try:
            path = os.path.abspath(os.path.expanduser(path))
        except Exception:
            path = raw
        try:
            if os.path.isfile(path):
                return path
        except Exception:
            pass
        return None

    def _download_entry_path(self, entry) -> str | None:
        if isinstance(entry, dict):
            entry = entry.get("path")
        return self._coerce_existing_local_media_path(entry)

    def _downloaded_media_path_for_article(self, article) -> str | None:
        """Return a completed local download for this article, if one exists."""
        if not article:
            return None

        for direct in (
            getattr(article, "local_media_path", None),
            getattr(article, "download_path", None),
            getattr(article, "media_url", None),
        ):
            path = self._coerce_existing_local_media_path(direct)
            if path:
                return path

        index = self._download_index()
        if index:
            stale_keys = []
            for key in self._download_index_keys(article):
                if key not in index:
                    continue
                path = self._download_entry_path(index.get(key))
                if path:
                    return path
                stale_keys.append(key)

            if stale_keys:
                cleaned = dict(index)
                changed = False
                for key in stale_keys:
                    if key in cleaned:
                        cleaned.pop(key, None)
                        changed = True
                if changed:
                    try:
                        self.config_manager.set("downloaded_media", cleaned)
                    except Exception:
                        pass

        legacy_path = self._find_legacy_downloaded_media_path(article)
        if legacy_path:
            self._record_article_download(article, legacy_path)
            return legacy_path
        return None

    def _record_article_download(self, article, local_path: str) -> str | None:
        path = self._coerce_existing_local_media_path(local_path)
        if not article or not path:
            return None

        entry = {
            "path": path,
            "title": str(getattr(article, "title", "") or ""),
            "feed_id": str(getattr(article, "feed_id", "") or ""),
            "article_id": str(getattr(article, "id", "") or ""),
            "media_url": str(getattr(article, "media_url", "") or ""),
            "url": str(getattr(article, "url", "") or ""),
            "updated_at": int(time.time()),
        }
        try:
            index = dict(self._download_index())
            for key in self._download_index_keys(article):
                index[key] = dict(entry)
            self.config_manager.set("downloaded_media", index)
        except Exception:
            log.exception("Failed to record downloaded media path")

        try:
            article.local_media_path = path
        except Exception:
            pass
        try:
            self._sync_download_path_in_cached_views(article, path)
        except Exception:
            pass
        return path

    def _sync_download_path_in_cached_views(self, article, local_path: str) -> None:
        article_id = self._article_cache_id(article)
        if not article_id:
            return
        try:
            with getattr(self, "_view_cache_lock", threading.Lock()):
                for st in (self.view_cache or {}).values():
                    for cached in (st.get("articles") or []):
                        if self._article_cache_id(cached) == article_id:
                            try:
                                cached.local_media_path = local_path
                            except Exception:
                                pass
        except Exception:
            log.exception("Error syncing download path in cached views")

    def on_download_article(self, article, download_format=None):
        if not article or not getattr(article, "media_url", None):
            wx.MessageBox(_("No downloadable media found for this item."), _("Download"), wx.ICON_INFORMATION)
            return
        if not self.config_manager.get("downloads_enabled", False):
            wx.MessageBox(_("Downloads are disabled. Enable them in Settings > Downloads."), _("Downloads disabled"), wx.ICON_INFORMATION)
            return
        threading.Thread(
            target=self._download_article_thread,
            args=(article, download_format),
            daemon=True,
        ).start()

    def on_download_article_as(self, article):
        """Download, but pick the format for this item instead of the default.

        Only yt-dlp items (YouTube and friends) have formats to choose from; a
        direct media file is downloaded byte-for-byte, so saying so beats
        showing a picker whose choices would all be ignored.
        """
        if not article or not getattr(article, "media_url", None):
            wx.MessageBox(_("No downloadable media found for this item."), _("Download"), wx.ICON_INFORMATION)
            return
        if not self.config_manager.get("downloads_enabled", False):
            wx.MessageBox(_("Downloads are disabled. Enable them in Settings > Downloads."), _("Downloads disabled"), wx.ICON_INFORMATION)
            return
        if not self._ytdlp_download_target(article):
            wx.MessageBox(
                _("This item is a direct media file, so it can only be downloaded in its original format."),
                _("Download As"),
                wx.ICON_INFORMATION,
            )
            return

        from core import download_formats

        choices = list(download_formats.DOWNLOAD_FORMAT_CHOICES)
        current = download_formats.normalize_download_format(
            self.config_manager.get("download_format", download_formats.DOWNLOAD_FORMAT_DEFAULT)
        )
        dlg = wx.SingleChoiceDialog(
            self,
            _("Choose the format to download this item in:"),
            _("Download As"),
            download_formats.download_format_labels(),
        )
        try:
            dlg.SetSelection(choices.index(current))
            if dlg.ShowModal() != wx.ID_OK:
                return
            idx = dlg.GetSelection()
        finally:
            dlg.Destroy()
        if not (0 <= idx < len(choices)):
            return
        self.on_download_article(article, download_format=choices[idx])

    def _ytdlp_download_target(self, article):
        """Return a yt-dlp-supported URL for this article, or None for a direct file.

        yt-dlp page items (YouTube, etc.) store the watch-page URL as media_url,
        which is not a direct media file: a plain GET would just save the HTML
        page, and even a resolved stream is split audio/video. Download those via
        yt-dlp instead so the streams are merged into one playable file.
        """
        if self._has_direct_media_link(article):
            return None
        for candidate in (getattr(article, "media_url", None), getattr(article, "url", None)):
            candidate = str(candidate or "").strip()
            if not candidate:
                continue
            try:
                if core.discovery.is_ytdlp_supported(candidate):
                    return candidate
            except Exception:
                pass
        return None

    def _download_dir_for_article(self, article, create: bool = True, allow_provider_lookup: bool = True):
        download_root = self.config_manager.get("download_path", _default_download_dir())
        if not download_root:
            download_root = _default_download_dir()
        # Items that came from a pasted link (File > Open Media URL) belong to no
        # feed, so they name their own subfolder instead of landing in "Feed".
        folder_override = str(getattr(article, "download_folder", "") or "").strip()
        if folder_override:
            target_dir = os.path.join(download_root, self._safe_name(folder_override))
            if create:
                os.makedirs(target_dir, exist_ok=True)
            return target_dir
        feed_title = None
        if allow_provider_lookup:
            feed_title = self._get_feed_title(article.feed_id)
        else:
            try:
                feed = self.feed_map.get(article.feed_id) if hasattr(self, "feed_map") else None
                feed_title = getattr(feed, "title", None)
            except Exception:
                feed_title = None
        feed_title = feed_title or "Feed"
        target_dir = os.path.join(download_root, self._safe_name(feed_title))
        if create:
            os.makedirs(target_dir, exist_ok=True)
        return target_dir

    def _find_legacy_downloaded_media_path(self, article) -> str | None:
        """Find downloads written before BlindRSS tracked local media paths."""
        if not article:
            return None
        try:
            target_dir = self._download_dir_for_article(
                article,
                create=False,
                allow_provider_lookup=False,
            )
        except Exception:
            return None
        if not target_dir or not os.path.isdir(target_dir):
            return None
        try:
            base_name = self._safe_name(getattr(article, "title", "") or "") or "episode"
            return self._find_downloaded_file(target_dir, base_name)
        except Exception:
            return None

    def _download_article_via_ytdlp(self, article, url, download_format=None):
        """Download a yt-dlp-supported item in the requested format preset.

        ``download_format`` is a core.download_formats identifier; None means
        the configured default. Video presets ask for the H.264 + AAC ladder so
        the result is a real MP4 rather than the MKV that AV1/Opus forces.

        Activity-status begin text was already posted by the caller
        (_download_article_thread, the only caller); this method pairs its own
        terminal outcomes (not-installed / success / failure) with status
        updates since it is where those outcomes are actually determined.
        """
        import subprocess
        import platform as _platform
        from core import download_formats

        fmt = download_formats.normalize_download_format(
            download_format
            if download_format is not None
            else self.config_manager.get("download_format", download_formats.DOWNLOAD_FORMAT_DEFAULT)
        )
        audio_only = download_formats.is_audio_only(fmt)

        title = self._download_activity_title(article)
        cli = core.discovery._resolve_ytdlp_cli_path()
        target_dir = self._download_dir_for_article(article)
        base_name = self._safe_name(article.title) or "video"
        out_template = os.path.join(target_dir, base_name + ".%(ext)s")

        base_cmd = [
            cli,
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "--no-color",
            "--geo-bypass",
            "--extractor-args", core.discovery.youtube_player_client_arg(),
            *download_formats.ytdlp_args(fmt),
            "-o", out_template,
        ]
        try:
            ffmpeg_path = dependency_check._find_executable_path("ffmpeg")
            if ffmpeg_path:
                base_cmd.extend(["--ffmpeg-location", str(ffmpeg_path)])
        except Exception:
            pass

        # Try anonymous first (works for most public videos and avoids Windows
        # DPAPI cookie failures), then a configured cookies.txt, then installed
        # browser cookies as a fallback for age-restricted/private videos.
        attempts = [[]]
        cookiefile = str(self.config_manager.get("ytdlp_cookies_file", "") or "").strip()
        if cookiefile and os.path.isfile(cookiefile):
            attempts.append(["--cookies", cookiefile])
        for src in core.discovery.get_ytdlp_cookie_sources(url) or []:
            arg = core.discovery.cookie_arg_for_ytdlp(src)
            if arg:
                attempts.append(["--cookies-from-browser", arg])

        creationflags = 0
        startupinfo = None
        if _platform.system().lower() == "windows":
            creationflags = 0x08000000  # CREATE_NO_WINDOW
            try:
                startupinfo = dependency_check._get_startup_info()
            except Exception:
                startupinfo = None

        last_err = _("yt-dlp download failed")
        timed_out = False
        for extra in attempts:
            # Audio presets never mux video, so the MKV rescue below does not
            # apply to them: one attempt per cookie source is the whole loop.
            merge_formats = ("mp4",) if audio_only else ("mp4", "mkv")
            for merge_format in merge_formats:
                cmd = list(base_cmd)
                if not audio_only:
                    cmd[cmd.index("--merge-output-format") + 1] = merge_format
                try:
                    res = subprocess.run(
                        cmd + extra + [url],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.DEVNULL,
                        creationflags=creationflags,
                        startupinfo=startupinfo,
                        timeout=1800,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                except FileNotFoundError:
                    wx.CallAfter(lambda: wx.MessageBox(
                        _("yt-dlp is not installed. Install it via Settings to download YouTube items."),
                        _("Download error"), wx.ICON_ERROR))
                    self._post_activity_status(_("Download failed: {title}").format(title=title))
                    return
                except subprocess.TimeoutExpired:
                    last_err = _("yt-dlp download timed out")
                    timed_out = True
                    break
                except Exception as e:
                    last_err = str(e)
                    break

                if int(getattr(res, "returncode", -1) or 0) == 0:
                    produced = self._find_downloaded_file(target_dir, base_name)
                    if produced:
                        self._record_article_download(article, produced)
                    self._apply_download_retention(target_dir)
                    dest = produced or target_dir
                    wx.CallAfter(
                        lambda d=dest: wx.MessageBox(
                            _("Downloaded to:\n{path}").format(path=d),
                            _("Download complete"),
                        )
                    )
                    self._post_activity_status(_("Download complete: {title}").format(title=title))
                    return

                last_err = (res.stderr or res.stdout or last_err).strip() or last_err
                if merge_format == "mp4" and "conversion failed" in last_err.lower():
                    log.info("yt-dlp MP4-preferred merge failed; retrying download as MKV")
                    continue
                break
            if timed_out:
                break

        wx.CallAfter(
            lambda e=last_err: wx.MessageBox(
                _("Download failed: {error}").format(error=e),
                _("Download error"),
                wx.ICON_ERROR,
            )
        )
        self._post_activity_status(_("Download failed: {title}").format(title=title))

    def _find_downloaded_file(self, target_dir, base_name):
        try:
            matches = [
                os.path.join(target_dir, n)
                for n in os.listdir(target_dir)
                if (
                    n.startswith(base_name)
                    and ".temp." not in n.lower()
                    and not n.endswith((".part", ".ytdl", ".tmp"))
                )
            ]
            if matches:
                return max(matches, key=os.path.getmtime)
        except Exception:
            pass
        return None

    def _download_activity_title(self, article) -> str:
        """Human-readable title for download activity-status text."""
        return str(getattr(article, "title", "") or "").strip() or "episode"

    def _download_article_thread(self, article, download_format=None):
        title = self._download_activity_title(article)
        self._post_activity_status(_("Downloading: {title}").format(title=title))
        try:
            ytdlp_url = self._ytdlp_download_target(article)
            if ytdlp_url:
                # _download_article_via_ytdlp pairs its own terminal outcomes
                # (success/failure) with activity-status updates.
                self._download_article_via_ytdlp(article, ytdlp_url, download_format)
                return

            url = article.media_url
            resp = utils.safe_requests_get(url, stream=True, timeout=30)
            resp.raise_for_status()

            ext = self._guess_extension(url, resp.headers.get("Content-Type"))
            # Same "<download path>/<feed>" layout as before, but via the shared
            # helper so a pasted link's own subfolder is honoured too.
            target_dir = self._download_dir_for_article(article)

            base_name = self._safe_name(article.title) or "episode"
            target_path = self._unique_path(os.path.join(target_dir, base_name + ext))

            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self._record_article_download(article, target_path)
            self._apply_download_retention(target_dir)
            wx.CallAfter(
                lambda: wx.MessageBox(
                    _("Downloaded to:\n{path}").format(path=target_path),
                    _("Download complete"),
                )
            )
            self._post_activity_status(_("Download complete: {title}").format(title=title))
        except Exception as e:
            error_message = str(e) or type(e).__name__
            wx.CallAfter(
                lambda message=error_message: wx.MessageBox(
                    _("Download failed: {error}").format(error=message),
                    _("Download error"),
                    wx.ICON_ERROR,
                )
            )
            self._post_activity_status(_("Download failed: {title}").format(title=title))

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
        from core.retention import RETENTION_DEFAULT
        value = self.config_manager.get("download_retention", RETENTION_DEFAULT)
        seconds = self._retention_seconds(value)
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

    def _retention_seconds(self, value):
        # Accepts stable identifiers ("1_week") and legacy English labels
        # ("1 week") from old configs; see core.retention (issue #63).
        from core.retention import retention_seconds
        return retention_seconds(value)

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
        self._show_add_feed_dialog()

    def _show_add_feed_dialog(self, initial_url: str = ""):
        cats = self.provider.get_categories()
        if not cats: cats = [UNCATEGORIZED]

        dlg = AddFeedDialog(self, cats, initial_url=initial_url)
        if dlg.ShowModal() == wx.ID_OK:
            url, cat = dlg.get_data()
            if url:
                self.SetTitle(_("BlindRSS - Adding feed {url}...").format(url=url))
                threading.Thread(target=self._add_feed_thread, args=(url, cat), daemon=True).start()
        dlg.Destroy()

    def on_detect_page_feeds(self, event):
        """File > Detect Feeds on Page... (issue #76)."""
        dlg = wx.TextEntryDialog(
            self,
            _("Enter the address of a webpage to scan for feeds:"),
            _("Detect Feeds on Page"),
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            url = (dlg.GetValue() or "").strip()
        finally:
            dlg.Destroy()
        if not url:
            return

        # Fetch/scan off the UI thread; results come back via CallAfter.
        def _scan():
            try:
                from core import discovery as _disc
                feeds = _disc.detect_page_feeds(
                    url,
                    browser_fallback_enabled=bool(
                        self.config_manager.get("browser_feed_fallback_enabled", True)
                    ),
                    browser_timeout=self.config_manager.get(
                        "browser_feed_fallback_timeout_seconds", 90
                    ),
                )
            except Exception as exc:
                if getattr(exc, "is_challenge", False):
                    # The automated browser could not complete this particular
                    # challenge. Cookie import remains a useful manual fallback.
                    message = _(
                        "BlindRSS could not complete this site's browser verification "
                        "page automatically.\n\nYou can still open the site in your web "
                        "browser, export its cookies with a cookies.txt extension, "
                        "then use Tools > Import Site Cookies."
                    )
                else:
                    message = _("Unable to retrieve the page.")
                wx.CallAfter(
                    wx.MessageBox,
                    message,
                    _("Detect Feeds on Page"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return
            wx.CallAfter(self._present_detected_page_feeds, feeds)

        threading.Thread(target=_scan, daemon=True).start()

    def _present_detected_page_feeds(self, feeds):
        """Show detection results: none -> message, one -> Add Feed, many -> picker."""
        feeds = [f for f in (feeds or []) if str((f or {}).get("url") or "").strip()]
        if not feeds:
            wx.MessageBox(
                _("No feeds detected on this page."),
                _("Detect Feeds on Page"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        if len(feeds) == 1:
            self._show_add_feed_dialog(initial_url=str(feeds[0].get("url") or ""))
            return
        labels = []
        for f in feeds:
            feed_url = str(f.get("url") or "")
            title = str(f.get("title") or "").strip()
            labels.append(f"{title} ({feed_url})" if title else feed_url)
        dlg = wx.SingleChoiceDialog(
            self,
            _("Select a feed to subscribe to:"),
            _("Detected Feeds"),
            labels,
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            idx = dlg.GetSelection()
        finally:
            dlg.Destroy()
        if 0 <= idx < len(feeds):
            self._show_add_feed_dialog(initial_url=str(feeds[idx].get("url") or ""))
        
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

        # Hold the refresh guard so this targeted post-add refresh cannot overlap
        # the background refresh loop.
        acquired = False
        try:
            acquired = self._refresh_guard.acquire(blocking=True)
        except Exception:
            acquired = False
        if not acquired:
            return False
        try:
            ok = bool(refresh_one(feed_id))
        except Exception:
            log.exception("Single-feed refresh after add failed for %s", feed_id)
            return False
        finally:
            try:
                self._refresh_guard.release()
            except Exception:
                pass

        if ok:
            wx.CallAfter(self.refresh_feeds)
        return ok

    def _post_add_feed(self, success, refresh_ran: bool = False):
        self.SetTitle("BlindRSS")
        if not refresh_ran:
            # Refresh regardless of success to be safe/consistent
            self.refresh_feeds()
        if not success:
             wx.MessageBox(_("Failed to add feed."), _("Error"), wx.ICON_ERROR)

    def on_remove_feed(self, event):
        item = self.tree.GetSelection()
        if item.IsOk():
            data = self.tree.GetItemData(item)
            if data and data["type"] == "feed":
                if wx.MessageBox(_("Are you sure you want to remove this feed?"), _("Confirm"), wx.YES_NO) == wx.YES:
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

                    self._begin_feed_removal(feed_id, feed_title)

    def _begin_feed_removal(self, feed_id: str, feed_title: str | None) -> None:
        if feed_title:
            self.SetTitle(_("BlindRSS - Removing feed {title}...").format(title=feed_title))
        else:
            self.SetTitle(_("BlindRSS - Removing feed..."))
        self._start_critical_worker(
            self._remove_feed_thread,
            args=(feed_id, feed_title),
            name="remove_feed",
        )

    def remove_feed_by_id(self, feed_id: str, feed_title: str | None = None) -> None:
        """Remove a feed without a tree selection (e.g. from the Feed Errors view).

        The caller is responsible for any confirmation prompt; this kicks off the
        same asynchronous removal + tree refresh used by the menu action.
        """
        if not feed_id:
            return
        if feed_title is None:
            feed_title = self._get_feed_title(feed_id)
        self._begin_feed_removal(feed_id, feed_title)

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
                parts.append(_("Could not remove feed '{title}'.").format(title=feed_title))
            else:
                parts.append(_("Could not remove feed."))

            if error_message:
                low = str(error_message).lower()
                if "locked" in low or "busy" in low:
                    parts.append(_("It may be busy due to another operation."))
                else:
                    parts.append(_("Error: {error}").format(error=error_message))

            parts.append(_("Please try again."))
            wx.MessageBox("\n\n".join(parts), _("Error"), wx.ICON_ERROR)
            return

        # Underlying DB rows changed significantly; drop view caches to avoid stale entries.
        try:
            with self._view_cache_lock:
                self.view_cache.clear()
        except Exception:
            log.exception("Failed to clear view cache after feed removal")

        self.refresh_feeds()

    def _cmd_edit_selected(self, event=None):
        """Edit whatever the tree has selected (the F2 command).

        Feed Properties for a feed, Category Properties for a category (issue
        #86). One command rather than two keeps a single "edit the thing I am
        on" key, the way F2 already behaves elsewhere in Windows.
        """
        item = self.tree.GetSelection()
        data = self.tree.GetItemData(item) if item and item.IsOk() else None
        if data and data.get("type") == "category":
            # A category's tree id is its full path (the category identity
            # model), which is what the provider calls take.
            self.on_edit_category(data.get("id"))
            return
        self.on_edit_feed(event)

    def on_edit_feed(self, event):
        item = self.tree.GetSelection()
        if not item or not item.IsOk():
            return
        data = self.tree.GetItemData(item)
        if not data or data.get("type") != "feed":
            return
        self.edit_feed_by_id(data.get("id"))

    def edit_feed_by_id(self, feed_id):
        """Open Feed Properties for a feed by id (e.g. from the Feed Errors view)."""
        if not feed_id:
            return
        feed = self.feed_map.get(feed_id)
        if not feed:
            return

        try:
            if not bool(getattr(self.provider, "supports_feed_edit", lambda: False)()):
                wx.MessageBox(_("This provider does not support editing feeds."), _("Not supported"), wx.ICON_INFORMATION)
                return
        except Exception:
            pass

        cats = self.provider.get_categories() if self.provider else []
        if not cats:
            cats = [UNCATEGORIZED]

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

        # The dialog has already persisted the per-feed settings (including any
        # column override). Apply the columns here, BEFORE the "nothing changed"
        # early return below -- editing only the columns leaves title/url/category
        # untouched, so that return would otherwise discard the change (article list columns).
        try:
            self._refresh_article_columns()
        except Exception:
            log.debug("Failed to re-render article columns after feed properties", exc_info=True)

        old_title = str(getattr(feed, "title", "") or "")
        old_url = str(getattr(feed, "url", "") or "")
        old_cat = str(getattr(feed, "category", "") or UNCATEGORIZED)

        if not new_title:
            new_title = old_title
        if not new_url:
            new_url = old_url
        if not new_cat:
            new_cat = old_cat

        url_changed = (new_url or "") != (old_url or "")
        if url_changed and not allow_url_edit:
            wx.MessageBox(
                _(
                    "This provider does not support changing the feed URL.\n"
                    "The title and category will be updated, but the URL will stay the same."
                ),
                _("Feed URL not supported"),
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
        msg = _("Could not update feed.")
        if err:
            msg = f"{msg}\n\n{err}"
        wx.MessageBox(msg, _("Error"), wx.ICON_ERROR)

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
                    _("This provider does not support resetting feed titles."),
                    _("Not supported"),
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
        msg = _("Could not reset feed title.")
        if err:
            msg = f"{msg}\n\n{err}"
        wx.MessageBox(msg, _("Error"), wx.ICON_ERROR)

    def on_import_opml(self, event, target_category=None):
        dlg = wx.FileDialog(self, _("Import OPML"), wildcard=f'{_("OPML files")} (*.opml)|*.opml', style=wx.FD_OPEN)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.SetTitle(_("BlindRSS - Importing OPML..."))
            threading.Thread(target=self._import_opml_thread, args=(path, target_category), daemon=True).start()
        dlg.Destroy()

    def on_import_youtube_takeout(self, event=None):
        """Import subscribable sources from a Google Takeout YouTube ZIP."""
        file_dlg = wx.FileDialog(
            self,
            _("Import YouTube Takeout"),
            wildcard=f'{_("ZIP archives")} (*.zip)|*.zip',
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if file_dlg.ShowModal() != wx.ID_OK:
                return
            path = file_dlg.GetPath()
        finally:
            file_dlg.Destroy()

        self.SetTitle(_("BlindRSS - Reading YouTube Takeout..."))
        threading.Thread(
            target=self._prepare_youtube_takeout_thread,
            args=(path,),
            daemon=True,
        ).start()

    def _prepare_youtube_takeout_thread(self, path: str) -> None:
        from core.youtube_takeout import parse_youtube_takeout

        try:
            result = parse_youtube_takeout(path)
            error = ""
        except Exception as exc:
            result = None
            error = str(exc) or exc.__class__.__name__
            log.exception("Could not inspect YouTube Takeout archive path=%s", path)
        wx.CallAfter(self._show_youtube_takeout_options, result, error)

    def _show_youtube_takeout_options(self, result, error="") -> None:
        self.SetTitle("BlindRSS")
        if result is None:
            message = _("YouTube Takeout import failed.")
            if error:
                message = f"{message}\n\n{error}"
            wx.MessageBox(message, _("Error"), wx.OK | wx.ICON_ERROR, self)
            return

        available_sources = [
            ("subscriptions", result.subscriptions, _("Subscribed channels ({count})")),
            ("history", result.history_channels, _("Channels from watch history ({count})")),
            ("owner", result.owner_channels, _("Owned channels ({count})")),
            ("playlists", result.playlists, _("Playlists ({count})")),
        ]
        source_options = [
            (source, label.format(count=count))
            for source, count, label in available_sources
            if count
        ]
        select_dlg = TakeoutImportSelectionDialog(
            self, [label for _source, label in source_options]
        )
        try:
            if select_dlg.ShowModal() != wx.ID_OK:
                return
            selected_indexes = list(select_dlg.GetSelections())
        finally:
            select_dlg.Destroy()
        if not selected_indexes:
            wx.MessageBox(_("Select at least one item type to import."), _("Import YouTube Takeout"), wx.OK | wx.ICON_INFORMATION, self)
            return

        sources = {source_options[index][0] for index in selected_indexes if 0 <= index < len(source_options)}
        selected_result = result.selected(sources)
        if not selected_result.feeds:
            wx.MessageBox(_("No subscribable items were selected."), _("Import YouTube Takeout"), wx.OK | wx.ICON_INFORMATION, self)
            return

        try:
            category_ids = list(self.provider.get_categories() or [])
        except Exception:
            category_ids = []
        if UNCATEGORIZED not in category_ids:
            category_ids.insert(0, UNCATEGORIZED)
        category_ids = list(dict.fromkeys(category_ids))
        category_dlg = wx.SingleChoiceDialog(
            self,
            _("Choose the category for imported YouTube subscriptions:"),
            _("Import YouTube Takeout"),
            [category_display_name(category) for category in category_ids],
        )
        try:
            if category_dlg.ShowModal() != wx.ID_OK:
                return
            selected_category = category_dlg.GetSelection()
            if selected_category < 0 or selected_category >= len(category_ids):
                return
            category = category_ids[selected_category]
        finally:
            category_dlg.Destroy()

        self.SetTitle(_("BlindRSS - Importing YouTube Takeout..."))
        threading.Thread(
            target=self._import_youtube_takeout_thread,
            args=(selected_result, category),
            daemon=True,
        ).start()

    def _import_youtube_takeout_thread(self, result, category: str) -> None:
        from core.youtube_takeout import write_takeout_opml

        success = False
        error = ""
        new_feed_ids: list[str] = []
        temp_path = ""
        try:
            before_ids = self._snapshot_feed_ids()
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".opml", prefix="blindrss-youtube-takeout-", delete=False
            ) as tmp:
                temp_path = tmp.name
            write_takeout_opml(result, temp_path)
            success = bool(self.provider.import_opml(temp_path, category))
            after_ids = self._snapshot_feed_ids()
            if success:
                new_feed_ids = sorted(fid for fid in after_ids if fid not in before_ids)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            log.exception("YouTube Takeout import failed")
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    log.warning("Could not remove temporary Takeout OPML file: %s", temp_path)
        wx.CallAfter(self._post_import_youtube_takeout, success, result, new_feed_ids, error)

    def _post_import_youtube_takeout(self, success, result, new_feed_ids, error="") -> None:
        self.SetTitle("BlindRSS")
        self.refresh_feeds()
        if not success or result is None:
            message = _("YouTube Takeout import failed.")
            if error:
                message = f"{message}\n\n{error}"
            wx.MessageBox(message, _("Error"), wx.OK | wx.ICON_ERROR, self)
            return

        normalized_new_ids = [str(feed_id).strip() for feed_id in new_feed_ids if str(feed_id).strip()]

        wx.MessageBox(
            _(
                "YouTube Takeout import complete.\n\n"
                "New subscriptions: {new}\n"
                "Subscription channels: {subscriptions}\n"
                "Watch-history channels: {history}\n"
                "Owned channels: {owned}\n"
                "Playlists: {playlists}\n\n"
                "The imported feeds will update during normal background refreshes."
            ).format(
                new=len(normalized_new_ids),
                subscriptions=result.subscriptions,
                history=result.history_channels,
                owned=result.owner_channels,
                playlists=result.playlists,
            ),
            _("Import YouTube Takeout"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

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

    def _collect_category_feed_ids_for_refresh(self, category_title: str | None) -> list[str]:
        feed_ids = []
        seen = set()
        try:
            feeds = self._collect_category_feeds_for_export(category_title)
        except Exception:
            feeds = []
        for feed in feeds or []:
            fid = str(getattr(feed, "id", "") or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            feed_ids.append(fid)
        return feed_ids

    def _refresh_category_thread(self, category_title: str) -> None:
        feed_ids = self._collect_category_feed_ids_for_refresh(category_title)
        if not feed_ids:
            wx.CallAfter(self.refresh_feeds)
            return

        refresh_many = getattr(self.provider, "refresh_feeds_by_ids", None)
        refresh_one = getattr(self.provider, "refresh_feed", None)
        if not callable(refresh_many) and not callable(refresh_one):
            threading.Thread(target=self._manual_refresh_thread, daemon=True).start()
            return

        acquired = False
        try:
            acquired = self._refresh_guard.acquire(blocking=True)
        except Exception:
            acquired = False
        if not acquired:
            return

        # The category's own feeds plus every subcategory's (issue #85): that
        # is exactly what _collect_category_feed_ids_for_refresh gathered.
        self._begin_refresh_activity(
            _("Refreshing category: {title}...").format(title=category_title),
            total=len(feed_ids),
        )
        try:
            def progress_cb(state):
                self._on_feed_refresh_progress(state)

            if callable(refresh_many):
                try:
                    refresh_many(feed_ids, progress_cb=progress_cb, force=True)
                except Exception:
                    log.exception("Failed category batch refresh for %s", category_title)
                    if callable(refresh_one):
                        for feed_id in feed_ids:
                            try:
                                refresh_one(feed_id, progress_cb=progress_cb)
                            except Exception:
                                log.exception("Failed category refresh for feed %s", feed_id)
            else:
                for feed_id in feed_ids:
                    try:
                        refresh_one(feed_id, progress_cb=progress_cb)
                    except Exception:
                        log.exception("Failed category refresh for feed %s", feed_id)
        finally:
            self._end_refresh_activity()
            try:
                self._refresh_guard.release()
            except Exception:
                pass

        wx.CallAfter(self._flush_feed_refresh_progress)
        wx.CallAfter(self.refresh_feeds)

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

        self._begin_refresh_activity(_("Refreshing imported feeds..."), total=len(ordered_ids))
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
            self._end_refresh_activity()
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
            wx.MessageBox(_("Import successful."))
        else:
            wx.MessageBox(_("Import failed. Please check the latest opml_debug_*.log in the temporary directory."))

    def on_export_opml(self, event):
        dlg = wx.FileDialog(self, _("Export OPML"), wildcard=f'{_("OPML files")} (*.opml)|*.opml', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            wx.BeginBusyCursor()
            try:
                if self.provider.export_opml(path):
                    wx.MessageBox(_("Export successful."))
                else:
                    wx.MessageBox(_("Export failed."))
            finally:
                wx.EndBusyCursor()
        dlg.Destroy()

    def _normalize_category_title_for_export(self, category_title: str | None) -> str:
        cat = str(category_title or "").strip()
        return cat or UNCATEGORIZED

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
            feed_cat = str(getattr(feed, "category", "") or "").strip() or UNCATEGORIZED
            if feed_cat.casefold() in all_keys:
                out.append(feed)
        return out

    def _export_category_opml_to_path(self, category_title: str | None, path: str):
        target_cat = self._normalize_category_title_for_export(category_title)
        feeds = self._collect_category_feeds_for_export(target_cat)
        if not feeds:
            return False, _('No feeds found in category "{category}".').format(category=target_cat)
        ok = bool(utils.write_opml(feeds, path))
        if ok:
            return True, None
        return False, _('Export failed for category "{category}".').format(category=target_cat)

    def on_export_category_opml(self, event, category_title=None):
        target_cat = self._normalize_category_title_for_export(category_title)
        safe_cat = re.sub(r'[\\/:*?"<>|]+', "_", target_cat).strip().rstrip(".") or "category"
        default_name = f"{safe_cat}.opml"
        dlg = wx.FileDialog(
            self,
            _('Export "{category}" Category OPML').format(category=target_cat),
            wildcard=f'{_("OPML files")} (*.opml)|*.opml',
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            defaultFile=default_name,
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            wx.BeginBusyCursor()
            try:
                ok, err = self._export_category_opml_to_path(target_cat, path)
                if ok:
                    wx.MessageBox(_("Export successful."))
                else:
                    wx.MessageBox(err or _("Export failed."))
            except Exception as e:
                wx.MessageBox(_("Export failed: {error}").format(error=e))
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
            old_provider_configs = deepcopy(self.config_manager.get("providers", {}) or {})
        except Exception:
            old_provider_configs = {}
        try:
            old_cache_full_text = bool(self.config_manager.get("cache_full_text", False))
        except Exception:
            old_cache_full_text = False
        try:
            old_rich_view = bool(self.config_manager.get("full_text_rich_view", False))
        except Exception:
            old_rich_view = False
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
        try:
            old_data_location = str(self.config_manager.get("data_location", "app_folder") or "app_folder")
        except Exception:
            old_data_location = "app_folder"

        accessible_browser_was_visible = False
        try:
            browser = getattr(self, "_accessible_browser", None)
            if browser is not None:
                accessible_browser_was_visible = bool(browser.IsShown())
        except Exception:
            accessible_browser_was_visible = False

        notification_feed_entries = self._collect_notification_feed_entries()
        dlg = SettingsDialog(self, self.config_manager.config, notification_feeds=notification_feed_entries)
        if dlg.ShowModal() == wx.ID_OK:
            data = dlg.get_data()

            # Apply data_location change first so subsequent config.set calls
            # write to the correct file.
            new_data_location = str(data.pop("data_location", old_data_location) or old_data_location)
            if new_data_location != old_data_location:
                ok, msg = self.config_manager.change_data_location(new_data_location)
                if not ok:
                    wx.MessageBox(
                        msg or _("Could not move config file."),
                        _("Storage Location"),
                        wx.ICON_WARNING,
                    )
                else:
                    wx.MessageBox(
                        _(
                            "Config has been moved. The feed database will be migrated "
                            "to the new location the next time BlindRSS starts."
                        ),
                        _("Storage Location Changed"),
                        wx.ICON_INFORMATION,
                    )

            # Apply settings
            try:
                for k, v in data.items():
                    self.config_manager.set(k, v)
            except Exception:
                pass

            # Structure-marker toggles take effect on the next article render.
            try:
                utils.apply_article_structure_config(self.config_manager.get)
            except Exception:
                pass

            # A changed browser identity applies to the next request made.
            try:
                from core import user_agents

                user_agents.apply_to_headers(self.config_manager.get)
            except Exception:
                log.debug("Could not apply the configured User-Agent", exc_info=True)

            # A changed global column layout only reaches the list on a render,
            # and the current view may well be one that just changed (article list columns).
            try:
                self._refresh_article_columns()
            except Exception:
                log.debug("Failed to re-render article columns after settings", exc_info=True)

            # Rich-reader toggle: swap the reader surface and re-render the
            # currently selected article so the change is visible immediately.
            try:
                new_rich_view = bool(self.config_manager.get("full_text_rich_view", False))
            except Exception:
                new_rich_view = old_rich_view
            if new_rich_view != old_rich_view:
                self._apply_reader_mode()
                self._sync_rich_view_menu_item()
                try:
                    idx = self.list_ctrl.GetFirstSelected()
                except Exception:
                    idx = -1
                if idx is not None and idx >= 0:
                    self._fulltext_token += 1
                    try:
                        self._update_content_view(int(idx))
                    except Exception:
                        pass

            # Re-register any custom media-tool path overrides so detection picks
            # them up immediately (without restarting the app).
            try:
                dependency_check.set_user_tool_paths({
                    "ffmpeg": self.config_manager.get("custom_ffmpeg_path", ""),
                    "ffprobe": self.config_manager.get("custom_ffprobe_path", ""),
                    "yt-dlp": self.config_manager.get("custom_ytdlp_path", ""),
                })
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
                    wx.MessageBox(
                        msg or _("Could not update startup registration."),
                        _("Settings"),
                        wx.ICON_WARNING,
                    )

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
                            msg or _("Windows notification prerequisites could not be fully configured."),
                            _("Notifications"),
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

            try:
                new_provider_configs = self.config_manager.get("providers", {}) or {}
            except Exception:
                new_provider_configs = {}

            if provider_configuration_changed(
                old_provider,
                old_provider_configs,
                new_provider,
                new_provider_configs,
            ):
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
                    self._invalidate_reader_text_tracking()
                except Exception:
                    pass
                try:
                    self.refresh_feeds()
                except Exception:
                    pass
        dlg.Destroy()

        if accessible_browser_was_visible:
            browser = getattr(self, "_accessible_browser", None)
            if browser is not None:
                try:
                    if not browser.IsShown():
                        browser.Show()
                    browser.Raise()
                    wx.CallAfter(browser.Raise)
                except Exception:
                    log.exception("Failed to restore accessible browser after settings")

    def on_check_updates(self, event):
        self._start_update_check(manual=True)

    def _maybe_auto_update_translations(self):
        """Refresh interface translations in the background, on the user's interval.

        Silent by design: the user asked for translations, not for a dialog. A
        downloaded catalog is applied on the next launch, so there is nothing
        actionable to report and nothing to interrupt a screen reader with.
        """
        try:
            from core import translation_updates as tu

            if not bool(self.config_manager.get(tu.CFG_ENABLED, tu.DEFAULT_ENABLED)):
                return
            frequency = str(
                self.config_manager.get(tu.CFG_FREQUENCY, tu.DEFAULT_FREQUENCY) or ""
            )
            if not tu.is_due(frequency):
                return
        except Exception:
            log.debug("Translation auto-update gate failed", exc_info=True)
            return

        def worker():
            try:
                from core import i18n, translation_updates as tu

                languages = [i18n.current_language().replace("-", "_")]
                languages.extend(tu.installed_languages())
                result = tu.check_and_update(list(dict.fromkeys(languages)))
                if result.updated:
                    log.info("Updated translations: %s", ", ".join(result.updated))
            except Exception:
                log.debug("Translation auto-update failed", exc_info=True)

        threading.Thread(target=worker, daemon=True).start()

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
            result = updater.UpdateCheckResult(
                "error", _("Update check failed: {error}").format(error=e)
            )
        wx.CallAfter(self._handle_update_check_result, result, manual)

    def _handle_update_check_result(self, result: updater.UpdateCheckResult, manual: bool):
        self._update_check_inflight = False

        if result.status == "error":
            if manual:
                wx.MessageBox(result.message, _("Update Check Failed"), wx.ICON_ERROR)
            return

        if result.status == "up_to_date":
            if manual:
                wx.MessageBox(result.message, _("No Updates"), wx.ICON_INFORMATION)
            return

        if result.status != "update_available" or not result.info:
            if manual:
                wx.MessageBox(_("Unable to determine update status."), _("Updates"), wx.ICON_ERROR)
            return

        info = result.info
        try:
            install_without_confirmation = bool(
                self.config_manager.get("install_updates_automatically", False)
            )
        except Exception:
            install_without_confirmation = False
        if install_without_confirmation:
            self._start_update_install(info)
            return

        summary = info.notes_summary or _("Release notes are available on GitHub.")
        prompt = (_(
            "A new version of BlindRSS is available ({version}).\n\n"
            "{summary}\n\n"
            "Download and install this update now?"
        ).format(version=info.tag, summary=summary))
        if wx.MessageBox(prompt, _("Update Available"), wx.YES_NO | wx.ICON_INFORMATION) == wx.YES:
            self._start_update_install(info)

    def _start_update_install(self, info: updater.UpdateInfo):
        if getattr(self, "_update_install_inflight", False):
            return
        if not updater.is_update_supported():
            wx.MessageBox(
                _(
                    "Auto-update is only available in the packaged app build.\n"
                    "Download the latest release from GitHub."
                ),
                _("Updates"),
                wx.ICON_INFORMATION,
            )
            return
        self._update_install_inflight = True
        self._update_cancel = threading.Event()
        # A real progress dialog (with a Cancel button) instead of just a busy
        # cursor, so the multi-megabyte download doesn't make the app look frozen.
        self._update_progress_dlg = wx.ProgressDialog(
            _("Updating BlindRSS"),
            _("Starting update..."),
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH | wx.PD_ELAPSED_TIME,
        )
        threading.Thread(target=self._update_install_thread, args=(info,), daemon=True).start()

    def _report_update_progress(self, phase: str, fraction) -> bool:
        # Called from the worker thread; marshal the UI update onto the main
        # thread and report back whether the user has asked to cancel.
        wx.CallAfter(self._apply_update_progress, phase, fraction)
        cancel = getattr(self, "_update_cancel", None)
        return not (cancel is not None and cancel.is_set())

    def _apply_update_progress(self, phase: str, fraction):
        dlg = getattr(self, "_update_progress_dlg", None)
        if not dlg:
            return
        try:
            if fraction is None:
                keep_going, _ignored = dlg.Pulse(phase)
            else:
                pct = int(max(0.0, min(1.0, fraction)) * 100)
                keep_going, _ignored = dlg.Update(pct, phase)
            if not keep_going:
                cancel = getattr(self, "_update_cancel", None)
                if cancel is not None:
                    cancel.set()
        except Exception:
            pass

    def _update_install_thread(self, info: updater.UpdateInfo):
        debug_mode = False
        try:
            debug_mode = bool(self.config_manager.get("debug_mode", False))
        except Exception:
            pass
        ok, msg = updater.download_and_apply_update(
            info, debug_mode=debug_mode, progress_cb=self._report_update_progress
        )
        wx.CallAfter(self._finish_update_install, ok, msg)

    def _finish_update_install(self, ok: bool, msg: str):
        self._update_install_inflight = False
        dlg = getattr(self, "_update_progress_dlg", None)
        if dlg is not None:
            try:
                dlg.Destroy()
            except Exception:
                pass
            self._update_progress_dlg = None
        if not ok:
            # A user-initiated cancel is not an error; just return quietly.
            if msg == updater.UPDATE_CANCELED_MESSAGE:
                return
            wx.MessageBox(msg, _("Update Failed"), wx.ICON_ERROR)
            return
        log.info("Update prepared; closing BlindRSS so the helper can apply it: %s", msg)
        try:
            wx.CallAfter(self.real_close)
        except Exception:
            self.real_close()

    def on_exit(self, event):
        self.real_close()

    def add_feed_from_url_prompt(self, url: str) -> None:
        url = str(url or "").strip()
        if not url:
            return

        cats = self.provider.get_categories()
        if not cats:
            cats = [UNCATEGORIZED]
        cat_dlg = wx.SingleChoiceDialog(self, _("Choose category:"), _("Add Feed"), cats)
        cat = UNCATEGORIZED
        if cat_dlg.ShowModal() == wx.ID_OK:
            cat = cat_dlg.GetStringSelection()
        cat_dlg.Destroy()

        self.SetTitle(_("BlindRSS - Adding feed {url}...").format(url=url))
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

    # --- Open Media URL (File menu) ------------------------------------
    # Any yt-dlp page or direct media link, streamed or downloaded, without it
    # having to be an article in a feed: feeds drop older items, so a video that
    # has scrolled out of a subscription is otherwise unreachable from the app.

    #: Subfolder (under the download path) for items downloaded from a pasted link.
    MEDIA_URL_DOWNLOAD_FOLDER = "Media Links"

    def _clipboard_media_url(self) -> str:
        """The clipboard's contents if they are a usable media URL, else ""."""
        text = ""
        try:
            clipboard = wx.TheClipboard
            if clipboard.Open():
                try:
                    data = wx.TextDataObject()
                    if clipboard.GetData(data):
                        text = data.GetText()
                finally:
                    clipboard.Close()
        except Exception:
            log.debug("Could not read the clipboard for Open Media URL", exc_info=True)
        return media_url_mod.normalize_media_url(text)

    def on_open_media_url(self, event=None):
        """File > Open Media URL: stream or download any supported link."""
        from gui.dialogs import OpenMediaUrlDialog
        from core import download_formats

        dlg = OpenMediaUrlDialog(
            self,
            initial_url=self._clipboard_media_url(),
            default_format=self.config_manager.get(
                "download_format", download_formats.DOWNLOAD_FORMAT_DEFAULT
            ),
            downloads_enabled=bool(self.config_manager.get("downloads_enabled", False)),
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            data = dlg.get_data()
            typed = dlg.url_ctrl.GetValue()
            download_action = data["action"] == OpenMediaUrlDialog.ACTION_DOWNLOAD
        finally:
            dlg.Destroy()

        url = data["url"]
        if not url:
            # Never fail silently: an empty or malformed box must say why.
            wx.MessageBox(
                _("That does not look like a media link. Enter a full web address, "
                  "for example https://www.youtube.com/watch?v=...")
                if str(typed or "").strip()
                else _("Enter the address of the media you want to open."),
                _("Open Media URL"),
                wx.ICON_INFORMATION,
            )
            return

        if download_action:
            self.download_media_url(url, data["download_format"])
        else:
            self.stream_media_url(url)

    def stream_media_url(self, url: str, title: str | None = None) -> None:
        """Play a pasted link in the BlindRSS player without saving anything."""
        url = media_url_mod.normalize_media_url(url)
        if not url:
            return
        try:
            use_ytdlp = bool(core.discovery.is_ytdlp_supported(url))
        except Exception:
            use_ytdlp = False

        pw = self._ensure_player_window()
        if not pw:
            wx.MessageBox(
                _("The media player could not be opened, so this link cannot be streamed."),
                _("Open Media URL"),
                wx.ICON_ERROR,
            )
            return

        # yt-dlp pages resolve their own real title during extraction; a direct
        # file has no metadata step, so name it from the URL rather than leaving
        # the player announcing "Loading media...".
        if not title and not use_ytdlp:
            title = media_url_mod.title_from_url(url)
        self._post_activity_status(_("Opening: {title}").format(title=title or url))
        pw.load_media(url, use_ytdlp=use_ytdlp, chapters=None, title=title, article_id=None)

        if bool(self.config_manager.get("show_player_on_play", True)):
            self.toggle_player_visibility(force_show=True)
        else:
            self.toggle_player_visibility(force_show=False)

    def download_media_url(self, url: str, download_format=None) -> None:
        """Save a pasted link to the downloads folder in the chosen format."""
        url = media_url_mod.normalize_media_url(url)
        if not url:
            return
        if not self.config_manager.get("downloads_enabled", False):
            wx.MessageBox(
                _("Downloads are disabled. Enable them in Settings > Downloads."),
                _("Downloads disabled"),
                wx.ICON_INFORMATION,
            )
            return
        threading.Thread(
            target=self._download_media_url_thread,
            args=(url, download_format),
            daemon=True,
        ).start()

    def _media_url_article(self, url: str, title: str = ""):
        """An article-shaped stand-in so a pasted link reuses the download path.

        It carries no id and no feed_id, which is what keeps it harmless: the
        download index then keys the saved file by media URL only, so if the
        same video later arrives in a feed the app still finds the local copy.
        `download_folder` sends it to its own subfolder instead of "Feed".
        """
        return SimpleNamespace(
            id="",
            feed_id="",
            title=str(title or media_url_mod.title_from_url(url)),
            url=url,
            media_url=url,
            local_media_path=None,
            download_folder=self.MEDIA_URL_DOWNLOAD_FOLDER,
        )

    def _download_media_url_thread(self, url: str, download_format=None) -> None:
        ytdlp_url = None
        try:
            ytdlp_url = url if core.discovery.is_ytdlp_supported(url) else None
        except Exception:
            ytdlp_url = None

        # Name the file from the site's own metadata when we can reach it; the
        # URL-derived fallback keeps a failed lookup from writing "watch.mp4".
        title = ""
        if ytdlp_url:
            self._post_activity_status(_("Opening: {title}").format(title=url))
            try:
                title = core.discovery.resolve_ytdlp_url_title(url, timeout=20) or ""
            except Exception:
                log.debug("Could not resolve a title for %s", url, exc_info=True)
        article = self._media_url_article(url, title)

        if ytdlp_url:
            self._post_activity_status(
                _("Downloading: {title}").format(title=article.title)
            )
            self._download_article_via_ytdlp(article, ytdlp_url, download_format)
            return

        # Not a yt-dlp page: save the bytes as they are. Format presets cannot
        # apply here, which the dialog says up front.
        self._download_article_thread(article, download_format)

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


class SmartFolderDialog(wx.Dialog):
    """Accessible builder for a Smart Folder rule.

    A flat list of condition rows plus a top-level ALL/ANY selector. Boolean
    criteria (read/favorite/opened/updated) are self-contained field choices so no
    per-row value widget juggling is needed; text criteria use an operator + value.
    The underlying rule engine (core.smart_folders) supports full nesting, but this
    v1 UI keeps to one accessible level.
    """

    MAX_ROWS = 6

    # (rule-key, label). "" = unused row; "__..." = a self-contained boolean.
    _FIELDS = [
        ("", "(no condition)"),
        ("title", "Title"),
        ("content", "Content"),
        ("description", "Description"),
        ("author", "Author"),
        ("feed", "Feed / Publication"),
        ("url", "Link (URL)"),
        ("tag", "Tag / Site category"),
        ("read_no", "Is unread"),
        ("read_yes", "Is read"),
        ("fav_yes", "Is favorite"),
        ("fav_no", "Is not favorite"),
        ("opened_yes", "Has been opened"),
        ("opened_no", "Has not been opened"),
        ("updated_yes", "Was updated since first fetch"),
        ("updated_no", "Was not updated"),
    ]
    _OPS = [
        ("contains", "contains"),
        ("not_contains", "does not contain"),
        ("equals", "equals"),
        ("starts_with", "starts with"),
    ]
    _TEXT_FIELDS = smart_folders_mod.TEXT_FIELDS
    _BOOL_MAP = smart_folders_mod.BOOL_ROW_KEYS

    def __init__(self, parent, name="", rule=None):
        super().__init__(parent, title=_("Smart Folder"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        outer = wx.BoxSizer(wx.VERTICAL)

        name_row = wx.BoxSizer(wx.HORIZONTAL)
        name_row.Add(wx.StaticText(self, label=_("Folder &name:")), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.name_ctrl = wx.TextCtrl(self, value=name or "")
        self.name_ctrl.SetName(_("Folder name"))
        name_row.Add(self.name_ctrl, 1)
        outer.Add(name_row, 0, wx.EXPAND | wx.ALL, 8)

        self.match_box = wx.RadioBox(
            self, label=_("Show articles that match"),
            choices=[_("All conditions (AND)"), _("Any condition (OR)")],
            majorDimension=1, style=wx.RA_SPECIFY_ROWS,
        )
        outer.Add(self.match_box, 0, wx.EXPAND | wx.ALL, 8)

        self.rows = []
        grid = wx.FlexGridSizer(cols=3, vgap=6, hgap=6)
        grid.AddGrowableCol(2, 1)
        grid.Add(wx.StaticText(self, label=_("Field")), 0)
        grid.Add(wx.StaticText(self, label=_("Condition")), 0)
        grid.Add(wx.StaticText(self, label=_("Value")), 0, wx.EXPAND)
        field_labels = [_(lbl) for _k, lbl in self._FIELDS]
        op_labels = [_(lbl) for _k, lbl in self._OPS]
        for i in range(self.MAX_ROWS):
            field_ctrl = wx.Choice(self, choices=field_labels)
            field_ctrl.SetName(_("Condition {n} field").format(n=i + 1))
            field_ctrl.SetSelection(0)
            op_ctrl = wx.Choice(self, choices=op_labels)
            op_ctrl.SetName(_("Condition {n} operator").format(n=i + 1))
            op_ctrl.SetSelection(0)
            val_ctrl = wx.TextCtrl(self)
            val_ctrl.SetName(_("Condition {n} value").format(n=i + 1))
            grid.Add(field_ctrl, 0)
            grid.Add(op_ctrl, 0)
            grid.Add(val_ctrl, 0, wx.EXPAND)
            row = {"field": field_ctrl, "op": op_ctrl, "val": val_ctrl}
            self.rows.append(row)
            field_ctrl.Bind(wx.EVT_CHOICE, lambda e, r=row: self._update_row_enabled(r))
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 8)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            outer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)
        self.SetSize((640, 480))

        if rule:
            self._load_rule(rule)
        for r in self.rows:
            self._update_row_enabled(r)

    def _field_key(self, row):
        idx = row["field"].GetSelection()
        return self._FIELDS[idx][0] if idx >= 0 else ""

    def _select_field(self, row, key):
        idx = next((i for i, (k, _l) in enumerate(self._FIELDS) if k == key), 0)
        row["field"].SetSelection(idx)

    def _update_row_enabled(self, row):
        is_text = self._field_key(row) in self._TEXT_FIELDS
        row["op"].Enable(is_text)
        row["val"].Enable(is_text)

    def _load_rule(self, rule):
        match = str((rule or {}).get("match") or "all").lower()
        self.match_box.SetSelection(1 if match == "any" else 0)
        conds = [c for c in (rule.get("conditions") or [])
                 if isinstance(c, dict) and "field" in c]
        for row, cond in zip(self.rows, conds[:self.MAX_ROWS]):
            field = str(cond.get("field") or "").lower()
            value = cond.get("value")
            if field in self._TEXT_FIELDS:
                self._select_field(row, field)
                op = str(cond.get("op") or "contains").lower()
                op_idx = next((i for i, (k, _l) in enumerate(self._OPS) if k == op), 0)
                row["op"].SetSelection(op_idx)
                row["val"].SetValue(str(value if value is not None else ""))
            else:
                want = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
                for pk, (bf, bv) in self._BOOL_MAP.items():
                    if bf == field and bool(bv) == bool(want):
                        self._select_field(row, pk)
                        break

    def get_result(self):
        name = self.name_ctrl.GetValue().strip() or _("Smart Folder")
        match = "any" if self.match_box.GetSelection() == 1 else "all"
        conditions = []
        for row in self.rows:
            key = self._field_key(row)
            if not key:
                continue
            if key in self._TEXT_FIELDS:
                op_idx = row["op"].GetSelection()
                op = self._OPS[op_idx][0] if op_idx >= 0 else "contains"
                value = row["val"].GetValue().strip()
                if not value and op != "equals":
                    continue  # skip empty text conditions
                conditions.append({"field": key, "op": op, "value": value})
            elif key in self._BOOL_MAP:
                bf, bv = self._BOOL_MAP[key]
                conditions.append({"field": bf, "op": "is", "value": bool(bv)})
        return name, {"match": match, "conditions": conditions}


class FilterRuleEditorDialog(wx.Dialog):
    """Accessible editor for a single Filter Rule: a condition builder (shared
    with Smart Folders) plus the action set the rule performs on matches."""

    MAX_ROWS = SmartFolderDialog.MAX_ROWS
    _FIELDS = SmartFolderDialog._FIELDS
    _OPS = SmartFolderDialog._OPS
    _TEXT_FIELDS = SmartFolderDialog._TEXT_FIELDS
    _BOOL_MAP = SmartFolderDialog._BOOL_MAP

    def __init__(self, parent, name="", rule=None, actions=None, enabled=True, stop=False):
        super().__init__(parent, title=_("Filter Rule"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        actions = filters_mod.normalize_actions(actions)
        move_category = actions.get("move") or ""
        label_category = actions.get("label") or ""
        self._move_category_identities = (
            [move_category] if move_category and move_category != UNCATEGORIZED else []
        )
        self._label_category_identities = (
            [label_category] if label_category and label_category != UNCATEGORIZED else []
        )
        outer = wx.BoxSizer(wx.VERTICAL)

        name_row = wx.BoxSizer(wx.HORIZONTAL)
        name_row.Add(wx.StaticText(self, label=_("Rule &name:")), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.name_ctrl = wx.TextCtrl(self, value=name or "")
        self.name_ctrl.SetName(_("Rule name"))
        name_row.Add(self.name_ctrl, 1)
        outer.Add(name_row, 0, wx.EXPAND | wx.ALL, 8)

        self.match_box = wx.RadioBox(
            self, label=_("Apply this rule to articles that match"),
            choices=[_("All conditions (AND)"), _("Any condition (OR)")],
            majorDimension=1, style=wx.RA_SPECIFY_ROWS,
        )
        outer.Add(self.match_box, 0, wx.EXPAND | wx.ALL, 8)

        cond_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Conditions")
        self.rows = []
        grid = wx.FlexGridSizer(cols=3, vgap=6, hgap=6)
        grid.AddGrowableCol(2, 1)
        grid.Add(wx.StaticText(self, label=_("Field")), 0)
        grid.Add(wx.StaticText(self, label=_("Condition")), 0)
        grid.Add(wx.StaticText(self, label=_("Value")), 0, wx.EXPAND)
        field_labels = [_(lbl) for _k, lbl in self._FIELDS]
        op_labels = [_(lbl) for _k, lbl in self._OPS]
        for i in range(self.MAX_ROWS):
            field_ctrl = wx.Choice(self, choices=field_labels)
            field_ctrl.SetName(_("Condition {n} field").format(n=i + 1))
            field_ctrl.SetSelection(0)
            op_ctrl = wx.Choice(self, choices=op_labels)
            op_ctrl.SetName(_("Condition {n} operator").format(n=i + 1))
            op_ctrl.SetSelection(0)
            val_ctrl = wx.TextCtrl(self)
            val_ctrl.SetName(_("Condition {n} value").format(n=i + 1))
            grid.Add(field_ctrl, 0)
            grid.Add(op_ctrl, 0)
            grid.Add(val_ctrl, 0, wx.EXPAND)
            row = {"field": field_ctrl, "op": op_ctrl, "val": val_ctrl}
            self.rows.append(row)
            field_ctrl.Bind(wx.EVT_CHOICE, lambda e, r=row: self._update_row_enabled(r))
        cond_box.Add(grid, 1, wx.EXPAND | wx.ALL, 4)
        outer.Add(cond_box, 1, wx.EXPAND | wx.ALL, 8)

        # Actions the rule performs on each matching article.
        act_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Then do this"))
        move_row = wx.BoxSizer(wx.HORIZONTAL)
        move_row.Add(wx.StaticText(self, label=_("&Move to category:")), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.move_ctrl = wx.TextCtrl(
            self,
            value=category_display_name(move_category) if move_category else "",
        )
        self.move_ctrl.SetName(_("Move to category (full path, blank for none)"))
        move_row.Add(self.move_ctrl, 1)
        act_box.Add(move_row, 0, wx.EXPAND | wx.ALL, 4)

        label_row = wx.BoxSizer(wx.HORIZONTAL)
        label_row.Add(wx.StaticText(self, label=_("Also &label with category:")), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.label_ctrl = wx.TextCtrl(
            self,
            value=category_display_name(label_category) if label_category else "",
        )
        self.label_ctrl.SetName(_("Also show under category (label, blank for none)"))
        label_row.Add(self.label_ctrl, 1)
        act_box.Add(label_row, 0, wx.EXPAND | wx.ALL, 4)

        self.mark_read_ctrl = wx.CheckBox(self, label=_("Mark as &read"))
        self.mark_read_ctrl.SetValue(bool(actions.get("mark_read")))
        self.mark_fav_ctrl = wx.CheckBox(self, label=_("Mark as &favorite"))
        self.mark_fav_ctrl.SetValue(bool(actions.get("mark_favorite")))
        self.delete_ctrl = wx.CheckBox(self, label=_("&Delete (uses the configured delete behavior)"))
        self.delete_ctrl.SetValue(bool(actions.get("delete")))
        self.skip_notify_ctrl = wx.CheckBox(self, label=_("Skip &notification"))
        self.skip_notify_ctrl.SetValue(bool(actions.get("skip_notification")))
        for ctrl in (self.mark_read_ctrl, self.mark_fav_ctrl, self.delete_ctrl, self.skip_notify_ctrl):
            act_box.Add(ctrl, 0, wx.ALL, 4)
        outer.Add(act_box, 0, wx.EXPAND | wx.ALL, 8)

        self.stop_ctrl = wx.CheckBox(self, label=_("&Stop processing later rules when this rule matches"))
        self.stop_ctrl.SetValue(bool(stop))
        outer.Add(self.stop_ctrl, 0, wx.ALL, 8)
        self.enabled_ctrl = wx.CheckBox(self, label=_("Rule &enabled"))
        self.enabled_ctrl.SetValue(bool(enabled))
        outer.Add(self.enabled_ctrl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        btns = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        if btns:
            outer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)
        self.SetSize((680, 640))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

        if rule:
            self._load_rule(rule)
        for r in self.rows:
            self._update_row_enabled(r)

    # Condition-row helpers mirror SmartFolderDialog (shared field/op constants).
    _field_key = SmartFolderDialog._field_key
    _select_field = SmartFolderDialog._select_field
    _update_row_enabled = SmartFolderDialog._update_row_enabled
    _load_rule = SmartFolderDialog._load_rule

    def _collect_rule(self):
        match = "any" if self.match_box.GetSelection() == 1 else "all"
        conditions = []
        for row in self.rows:
            key = self._field_key(row)
            if not key:
                continue
            if key in self._TEXT_FIELDS:
                op_idx = row["op"].GetSelection()
                op = self._OPS[op_idx][0] if op_idx >= 0 else "contains"
                value = row["val"].GetValue().strip()
                if not value and op != "equals":
                    continue
                conditions.append({"field": key, "op": op, "value": value})
            elif key in self._BOOL_MAP:
                bf, bv = self._BOOL_MAP[key]
                conditions.append({"field": bf, "op": "is", "value": bool(bv)})
        return {"match": match, "conditions": conditions}

    def _collect_actions(self):
        return filters_mod.normalize_actions({
            "move": normalize_category_input(
                self.move_ctrl.GetValue(), self._move_category_identities
            ),
            "label": normalize_category_input(
                self.label_ctrl.GetValue(), self._label_category_identities
            ),
            "mark_read": self.mark_read_ctrl.GetValue(),
            "mark_favorite": self.mark_fav_ctrl.GetValue(),
            "delete": self.delete_ctrl.GetValue(),
            "skip_notification": self.skip_notify_ctrl.GetValue(),
        })

    def _on_ok(self, event):
        if filters_mod.actions_are_empty(self._collect_actions()):
            wx.MessageBox(
                _("Choose at least one action for this rule (move, label, mark, delete, or skip notification)."),
                _("No Actions"),
                wx.ICON_WARNING,
                self,
            )
            return
        event.Skip()  # allow the dialog to close with wx.ID_OK

    def get_result(self):
        name = self.name_ctrl.GetValue().strip() or "Filter"
        return (
            name,
            self._collect_rule(),
            self._collect_actions(),
            bool(self.enabled_ctrl.GetValue()),
            bool(self.stop_ctrl.GetValue()),
        )


class FilterRulesDialog(wx.Dialog):
    """Accessible manager for the ordered Filter Rules pipeline."""

    def __init__(self, parent, provider):
        super().__init__(parent, title=_("Filter Rules"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.provider = provider
        self._rules = []

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(
            wx.StaticText(self, label=_("Rules run top to bottom for each incoming article, like email filters.")),
            0, wx.ALL, 8,
        )

        body = wx.BoxSizer(wx.HORIZONTAL)
        self.list_ctrl = wx.ListBox(self, style=wx.LB_SINGLE)
        self.list_ctrl.SetName(_("Filter rules"))
        self.list_ctrl.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._on_edit())
        body.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 8)

        btn_col = wx.BoxSizer(wx.VERTICAL)
        self._add_btn = wx.Button(self, label=_("&Add..."))
        self._edit_btn = wx.Button(self, label=_("&Edit..."))
        self._delete_btn = wx.Button(self, label=_("De&lete"))
        self._up_btn = wx.Button(self, label=_("Move &Up"))
        self._down_btn = wx.Button(self, label=_("Move &Down"))
        self._toggle_btn = wx.Button(self, label=_("En&able/Disable"))
        self._apply_btn = wx.Button(self, label=_("Apply to E&xisting Articles"))
        for b in (self._add_btn, self._edit_btn, self._delete_btn, self._up_btn,
                  self._down_btn, self._toggle_btn, self._apply_btn):
            btn_col.Add(b, 0, wx.EXPAND | wx.BOTTOM, 6)
        body.Add(btn_col, 0, wx.ALL, 8)
        outer.Add(body, 1, wx.EXPAND)

        close_btns = self.CreateStdDialogButtonSizer(wx.CLOSE)
        if close_btns:
            outer.Add(close_btns, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)
        self.SetSize((720, 480))

        self._add_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_add())
        self._edit_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_edit())
        self._delete_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_delete())
        self._up_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_move(-1))
        self._down_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_move(1))
        self._toggle_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_toggle())
        self._apply_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_apply_existing())
        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)

        self._reload()

    def _reload(self, select_index=None):
        try:
            self._rules = list(self.provider.get_filter_rules() or [])
        except Exception:
            log.exception("Failed to load filter rules")
            self._rules = []
        self.list_ctrl.Clear()
        for rule in self._rules:
            self.list_ctrl.Append(self._format_rule(rule))
        if self._rules:
            idx = 0 if select_index is None else max(0, min(select_index, len(self._rules) - 1))
            self.list_ctrl.SetSelection(idx)

    @staticmethod
    def _format_rule(rule):
        name = rule.get("name") or "Filter"
        cond = smart_folders_mod.describe_rule(rule.get("rule"))
        acts = filters_mod.describe_actions(rule.get("actions"))
        label = _("{name}: if {condition} then {actions}").format(
            name=name, condition=cond, actions=acts
        )
        if rule.get("stop"):
            label += _(" [stop]")
        if not rule.get("enabled", True):
            label += " (disabled)"
        return label

    def _selected_index(self):
        idx = self.list_ctrl.GetSelection()
        return idx if idx != wx.NOT_FOUND else None

    def _on_add(self):
        dlg = FilterRuleEditorDialog(self)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                name, rule, actions, enabled, stop = dlg.get_result()
                try:
                    self.provider.create_filter_rule(name, rule, actions, enabled=enabled, stop=stop)
                except Exception:
                    log.exception("Error creating filter rule")
                    wx.MessageBox(_("Could not create the rule."), _("Error"), wx.ICON_ERROR, self)
                    return
                self._reload(select_index=len(self._rules))
        finally:
            dlg.Destroy()

    def _on_edit(self):
        idx = self._selected_index()
        if idx is None:
            return
        rule = self._rules[idx]
        dlg = FilterRuleEditorDialog(
            self,
            name=rule.get("name"),
            rule=rule.get("rule"),
            actions=rule.get("actions"),
            enabled=rule.get("enabled", True),
            stop=rule.get("stop", False),
        )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                name, cond, actions, enabled, stop = dlg.get_result()
                try:
                    self.provider.update_filter_rule(
                        rule["id"], name=name, rule=cond, actions=actions,
                        enabled=enabled, stop=stop,
                    )
                except Exception:
                    log.exception("Error updating filter rule")
                    wx.MessageBox(_("Could not update the rule."), _("Error"), wx.ICON_ERROR, self)
                    return
                self._reload(select_index=idx)
        finally:
            dlg.Destroy()

    def _on_delete(self):
        idx = self._selected_index()
        if idx is None:
            return
        rule = self._rules[idx]
        name = rule.get("name") or _("this rule")
        if wx.MessageBox(
            _('Delete filter rule "{name}"? Articles it already filed are not changed.').format(name=name),
            _("Delete Rule"), wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        try:
            self.provider.delete_filter_rule(rule["id"])
        except Exception:
            log.exception("Error deleting filter rule")
        self._reload(select_index=idx)

    def _on_move(self, delta):
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self._rules):
            return
        order = [r["id"] for r in self._rules]
        order[idx], order[new_idx] = order[new_idx], order[idx]
        try:
            self.provider.reorder_filter_rules(order)
        except Exception:
            log.exception("Error reordering filter rules")
            return
        self._reload(select_index=new_idx)

    def _on_toggle(self):
        idx = self._selected_index()
        if idx is None:
            return
        rule = self._rules[idx]
        try:
            self.provider.update_filter_rule(rule["id"], enabled=not rule.get("enabled", True))
        except Exception:
            log.exception("Error toggling filter rule")
            return
        self._reload(select_index=idx)

    def _on_apply_existing(self):
        if wx.MessageBox(
            _(
                "Run all enabled rules against every existing article now? "
                "This may move, label, or delete articles."
            ),
            _("Apply to Existing Articles"), wx.YES_NO | wx.ICON_QUESTION, self,
        ) != wx.YES:
            return
        self._apply_btn.Disable()

        def _worker():
            try:
                result = self.provider.apply_filter_rules_to_existing()
            except Exception as e:
                result = {"error": str(e)}
            wx.CallAfter(_done, result)

        def _done(result):
            try:
                self._apply_btn.Enable()
            except Exception:
                pass
            if result.get("error"):
                wx.MessageBox(
                    _("Could not apply rules.\n\n{error}").format(error=result["error"]),
                    _("Error"),
                    wx.ICON_ERROR,
                    self,
                )
                return
            wx.MessageBox(
                _("Scanned {scanned} articles; {changed} matched a rule.").format(
                    scanned=result.get("scanned", 0), changed=result.get("changed", 0)
                ),
                _("Filter Rules Applied"), wx.ICON_INFORMATION, self,
            )
            self._reload(select_index=self._selected_index())

        threading.Thread(target=_worker, daemon=True).start()
