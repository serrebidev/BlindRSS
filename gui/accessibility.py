# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import html as html_stdlib
import logging
import math
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from collections.abc import Mapping

import wx

from core import utils
from core import article_extractor
from core import article_html
from core import article_lang
from core.i18n import _
from core.categories import UNCATEGORIZED, category_display_name
from .clipboard_utils import copy_text_to_clipboard, copy_textctrl_selection_to_clipboard
from .reader_performance import (
    notify_reader_content_changed,
    replace_text_control_value,
    set_accessible_webview_content,
)
from . import rich_view_links

log = logging.getLogger(__name__)


def _article_is_youtube_video(article) -> bool:
    try:
        from core import youtube_fulltext

        return youtube_fulltext.is_youtube_video_url(getattr(article, "url", "") or "")
    except Exception:
        return False


# A body shorter than this is probably a snippet/paywall stub, not a full article, so it's
# worth asking the provider's server-side fetcher for more.
_PROVIDER_FETCH_MIN_LEN = 1500


def normalize_accessible_chapters(chapters):
    """Return valid chapters sorted by their start time for reader presentation."""
    normalized = []
    for chapter in chapters or []:
        if not isinstance(chapter, Mapping):
            continue
        try:
            start = float(chapter.get("start", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            start = 0.0
        if not math.isfinite(start) or start < 0:
            start = 0.0
        title = str(chapter.get("title", "") or "").strip() or _("Untitled chapter")
        href = str(
            chapter.get("href", "")
            or chapter.get("url", "")
            or chapter.get("link", "")
            or ""
        ).strip()
        normalized.append({"start": start, "title": title, "href": href})
    normalized.sort(key=lambda chapter: chapter["start"])
    return normalized


def format_accessible_chapter_timestamp(start) -> str:
    try:
        seconds = float(start or 0)
    except (TypeError, ValueError, OverflowError):
        seconds = 0.0
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0.0
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_accessible_chapters(chapters) -> str:
    chapter_list = normalize_accessible_chapters(chapters)
    lines = [_("Chapters available: {count}.").format(count=len(chapter_list))]
    for index, chapter in enumerate(chapter_list, start=1):
        timestamp = format_accessible_chapter_timestamp(chapter["start"])
        line = _("Chapter {index}: {timestamp}, {title}.").format(index=index, timestamp=timestamp, title=chapter['title'])
        if chapter["href"]:
            line += _(" Link: {url}").format(url=chapter['href'])
        lines.append(line)
    return "\n".join(lines)


def extract_article_body(
    article,
    *,
    provider_fetch=None,
    timeout: int = 20,
    max_pages: int = 6,
    encoding: str = "",
    metadata_sink=None,
):
    """Extract the readable full-text body for an article.

    GUI-free and safe to call off the main thread (does network I/O). Tries, in order of
    preference by COMPLETENESS (longest wins): client-side web extraction, the feed
    content, and — when those don't beat the feed — the provider's own server-side
    full-text fetch (`provider_fetch(article_id, url) -> html`, e.g. Miniflux
    fetch-content, which has site-specific scraper rules for paywalled/anti-bot sites).

    Returns ``(body_text, cacheable)``:
    - ``body_text`` is the cleaned body, or ``None`` when nothing readable was produced.
    - ``cacheable`` is True when the body is authoritative — web/provider full text, or the
      feed for an item with no web target. A feed fallback for a *web* article after a total
      web+provider failure is NOT cached, so the next visit retries.
    """
    url = (getattr(article, "url", "") or "").strip()
    fallback_html = getattr(article, "content", "") or ""
    fallback_title = getattr(article, "title", "") or ""
    fallback_author = getattr(article, "author", "") or ""
    # MP3 enclosures are extractable only when the feed did not already supply
    # authored notes; then the bounded leading ID3 tag is the fallback source.
    # Other media types remain ineligible for webpage extraction.
    has_web_target = article_extractor.is_extractable_fulltext_url(url) and not (
        article_extractor._looks_like_id3_media_url(url) and fallback_html.strip()
    )

    # Always ATTEMPT web extraction for a real URL (the generic ">2500 chars" prefer-feed
    # heuristic wrongly suppressed it for substantial feeds like Miniflux). But web
    # extraction sometimes returns LESS than the feed already provides (truncated/partial
    # page) — replacing a fuller feed body with that shorter result is exactly what reads
    # as "full text doesn't work". So we extract the feed too and keep whichever is more
    # complete (longer), never downgrading the user below the feed content.
    web_text = None
    if has_web_target:
        try:
            # Per-feed full-text encoding override (issue #75) and structured-metadata
            # enrichment ride the same fetch the main window uses; both are optional
            # and passed only when provided so lean test doubles keep working.
            extra = {}
            if encoding:
                extra["encoding"] = encoding
            if metadata_sink is not None:
                extra["metadata_sink"] = metadata_sink
            art = article_extractor.extract_full_article(
                url, max_pages=max_pages, timeout=timeout, **extra
            )
            if art:
                web_text = (getattr(art, "text", "") or "").strip() or None
        except article_extractor.ExtractionError:
            web_text = None
        except Exception:
            web_text = None

    # The feed candidate is the LONGER of two views of the feed body: the boilerplate-cleaned
    # `extract_from_html`, and the plain `html_to_text` that the reader pane shows as the
    # initial snippet. Comparing only against the cleaned one let the "full text" come out
    # SHORTER than the snippet the user already heard (trafilatura sometimes drops the lead),
    # which reads as "full text makes it shorter / doesn't work". Never go below the snippet.
    feed_candidates = []
    try:
        fart = article_extractor.extract_from_html(
            fallback_html, url, title=fallback_title, author=fallback_author
        )
        if fart:
            t = (getattr(fart, "text", "") or "").strip()
            if t:
                feed_candidates.append(t)
    except Exception:
        pass
    try:
        raw = (utils.html_to_text(fallback_html) or "").strip()
        if raw:
            feed_candidates.append(raw)
    except Exception:
        pass
    # html_to_text is a RAW render of the feed body — it keeps leading toolbar/
    # ad/gallery chrome ("Share on Facebook", "Open this photo in gallery:",
    # "Advertisement / This advertisement has not loaded yet") that the
    # extractor's own output already strips. When a hosted provider (Miniflux)
    # serves full page HTML, this raw candidate is the LONGEST and wins the
    # comparison below, dragging that chrome back to the top of the reader.
    # Strip it here so a screen reader never opens on junk labels regardless of
    # which candidate wins.
    feed_candidates = [
        article_extractor._strip_leading_boilerplate(c) for c in feed_candidates
    ]
    feed_text = max(feed_candidates, key=len) if feed_candidates else None

    if web_text and feed_text:
        best, source = (web_text, "web") if len(web_text) > len(feed_text) else (feed_text, "feed")
    elif web_text:
        best, source = web_text, "web"
    elif feed_text:
        best, source = feed_text, "feed"
    else:
        best, source = None, None

    # When we don't yet have a clearly-full article (no result, or a short stub from a
    # paywalled/anti-bot page that blocks client-side scrapers), ask the provider's
    # server-side fetcher — for Miniflux this returns the full article its own scraper
    # rules pulled. Use it only if it's more complete. A length gate (rather than "web
    # lost") is needed because a 300-char paywall stub can still be longer than a tiny feed.
    need_more = best is None or len(best) < _PROVIDER_FETCH_MIN_LEN
    if provider_fetch is not None and has_web_target and need_more:
        article_id = str(getattr(article, "id", "") or getattr(article, "article_id", "") or "").strip()
        if article_id:
            provider_html = None
            try:
                provider_html = provider_fetch(article_id, url)
            except Exception:
                provider_html = None
            if provider_html:
                try:
                    part = article_extractor.extract_from_html(
                        provider_html, url, title=fallback_title, author=fallback_author
                    )
                    provider_text = (getattr(part, "text", "") or "").strip() if part else ""
                except Exception:
                    provider_text = ""
                if provider_text and (best is None or len(provider_text) > len(best)):
                    best, source = provider_text, "provider"

    if not best:
        return None, False

    # Cacheable (authoritative) when: web/provider full text; no web target (feed is all
    # there is); or the feed beat a working web extraction (stable). Only a TOTAL web (and
    # provider) failure for a web article stays uncached so it retries next time.
    if source in ("web", "provider"):
        cacheable = True
    else:
        cacheable = (not has_web_target) or (web_text is not None)
    return best, cacheable


def voiceover_is_running() -> bool:
    try:
        proc = subprocess.run(
            ["pgrep", "-x", "VoiceOver"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except Exception:
        return False


def build_accessible_view_entries(feeds, categories=None, hierarchy=None, include_favorites=False):
    entries = [
        {"label": _("All Articles"), "view_id": "all", "kind": "special", "parent_cats": []},
        {"label": _("Unread Articles"), "view_id": "unread:all", "kind": "special", "parent_cats": []},
        {"label": _("Read Articles"), "view_id": "read:all", "kind": "special", "parent_cats": []},
    ]
    if include_favorites:
        entries.append({"label": _("Favorites"), "view_id": "favorites:all", "kind": "special", "parent_cats": []})

    feeds = list(feeds or [])
    hierarchy = dict(hierarchy or {})

    cat_names = {str(c or "").strip() for c in (categories or []) if str(c or "").strip()}
    for feed in feeds:
        cat_names.add(str(getattr(feed, "category", "") or UNCATEGORIZED).strip() or UNCATEGORIZED)
    if not cat_names and feeds:
        cat_names.add(UNCATEGORIZED)

    feeds_by_cat = {cat: [] for cat in cat_names}
    for feed in feeds:
        cat = str(getattr(feed, "category", "") or UNCATEGORIZED).strip() or UNCATEGORIZED
        feeds_by_cat.setdefault(cat, []).append(feed)

    children_of = {}
    top_level = []
    for cat in sorted(cat_names, key=lambda s: s.lower()):
        parent = str(hierarchy.get(cat, "") or "").strip()
        if parent and parent in cat_names:
            children_of.setdefault(parent, []).append(cat)
        else:
            top_level.append(cat)
    for parent in list(children_of.keys()):
        children_of[parent].sort(key=lambda s: s.lower())

    from core.db import category_display_leaf

    def _walk(cat, path):
        # `path`/`cat` carry full category-path identities; show only the leaf of
        # each segment in the human-readable breadcrumb label.
        category_path = list(path) + [cat]
        path_label = " > ".join(
            category_display_name(c) if c == UNCATEGORIZED else category_display_leaf(c)
            for c in category_path
        )
        cat_id = f"category:{cat}"
        entries.append(
            {
                "label": f'{_("Category:")} {path_label}',
                "view_id": cat_id,
                "kind": "category",
                "parent_cats": list(path),
                "cat_name": cat,
            }
        )

        cat_feeds = sorted(
            feeds_by_cat.get(cat, []),
            key=lambda f: (str(getattr(f, "title", "") or "").lower(), str(getattr(f, "id", "") or "")),
        )
        for feed in cat_feeds:
            unread = 0
            try:
                unread = int(getattr(feed, "unread_count", 0) or 0)
            except Exception:
                unread = 0
            title = str(getattr(feed, "title", "") or "").strip() or str(getattr(feed, "id", "") or "")
            label = f'{_("Feed:")} {title}'
            if unread > 0:
                label += _(", unread: {unread}").format(unread=unread)
            if category_path:
                label += f" ({path_label})"
            entries.append(
                {
                    "label": label,
                    "view_id": str(getattr(feed, "id", "") or ""),
                    "kind": "feed",
                    "parent_cats": list(category_path),
                }
            )

        for child in children_of.get(cat, []):
            _walk(child, category_path)

    for cat in top_level:
        _walk(cat, [])

    return entries


def visible_accessible_view_entries(entries, expanded_categories=None):
    expanded = {str(cat or "").strip() for cat in (expanded_categories or []) if str(cat or "").strip()}
    visible = []
    for entry in list(entries or []):
        kind = str(entry.get("kind", "") or "")
        parent_cats = [
            str(cat or "").strip()
            for cat in (entry.get("parent_cats", []) or [])
            if str(cat or "").strip()
        ]
        if kind in {"category", "feed"} and any(parent not in expanded for parent in parent_cats):
            continue
        visible.append(entry)
    return visible


def format_accessible_view_label(entry, expanded_categories=None):
    entry = dict(entry or {})
    expanded = {str(cat or "").strip() for cat in (expanded_categories or []) if str(cat or "").strip()}
    kind = str(entry.get("kind", "") or "")
    parent_cats = [
        str(cat or "").strip()
        for cat in (entry.get("parent_cats", []) or [])
        if str(cat or "").strip()
    ]
    indent = "  " * len(parent_cats)
    label = str(entry.get("label", "") or "")
    if kind != "category":
        return f"{indent}{label}" if indent else label

    cat_name = str(entry.get("cat_name", "") or "").strip()
    state = _("expanded") if cat_name and cat_name in expanded else _("collapsed")
    return f"{indent}{label}, {state}" if indent else f"{label}, {state}"


class AccessibleBrowserFrame(wx.Frame):
    def __init__(self, mainframe):
        super().__init__(mainframe, title=_("BlindRSS Accessible Browser"), size=(1280, 820))
        self.mainframe = mainframe
        self.current_view_id = None
        self._view_entries = []
        self._visible_view_entries = []
        self._view_index_by_id = {}
        self._visible_view_index_by_id = {}
        self._known_categories = set()
        self._expanded_categories = set()
        self._base_articles = []
        self._current_articles = []
        self._paged_offset = 0
        self._total_articles = None
        self._loading = False
        # Full-text state: bump _content_token on every article switch so stale
        # background loads can't overwrite the pane; cache bodies by article id.
        self._content_token = 0
        self._fulltext_cache = {}
        self._fulltext_inflight = set()
        self._fulltext_timer = None
        self._fulltext_debounce_ms = 350
        self._chapter_cache = {}
        self._chapter_inflight = set()
        self._current_body_art_id = None
        self._current_body_text = ""
        # Optional rich (HTML) reader surface, mirroring MainFrame's opt-in
        # "Rich Full-Text View". Created lazily on first use; falls back to the
        # plain TextCtrl when the WebView backend is unavailable. Gated on the
        # SAME config key as the main window so the setting is shared.
        self._rich_view = None
        self._rich_view_unavailable = False
        self._rich_html_cache = {}
        self._rich_token = 0
        self._rich_debounce = None
        self._current_rich_art_id = None
        # Read-ahead prefetch: while the user reads one article, warm the full text of
        # the next few so VoiceOver reads the FULL article (not the feed snippet) the
        # moment they navigate to it. Web extraction is slow (2-7s); without this the
        # async result swaps in silently after the user has already heard the snippet.
        self._prefetch_ahead = 8
        self._prefetch_queue = deque()
        self._prefetch_inflight = set()
        self._prefetch_lock = threading.Lock()
        self._prefetch_event = threading.Event()
        self._prefetch_stop = False
        # The provider's session (e.g. Miniflux) isn't guaranteed thread-safe, so serialize
        # server-side fetch-content calls across the on-demand + prefetch workers.
        self._provider_lock = threading.Lock()
        self._prefetch_threads = [
            threading.Thread(target=self._prefetch_worker_loop, daemon=True) for _ in range(3)
        ]
        for t in self._prefetch_threads:
            t.start()

        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            panel,
            label=_(
                "VoiceOver-friendly browser for feeds, articles, and content. "
                "Use the lists below to choose a view and article."
            ),
        )
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 8)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(panel, label=_("Refresh Feeds"))
        self.refresh_btn.SetName(_("Refresh Feeds"))
        toolbar.Add(self.refresh_btn, 0, wx.RIGHT, 6)
        self.load_more_btn = wx.Button(panel, label=_("Load More Articles"))
        self.load_more_btn.SetName(_("Load More Articles"))
        toolbar.Add(self.load_more_btn, 0, wx.RIGHT, 6)
        self.expand_btn = wx.Button(panel, label=_("Expand Category"))
        self.expand_btn.SetName(_("Expand Category"))
        toolbar.Add(self.expand_btn, 0, wx.RIGHT, 6)
        self.collapse_btn = wx.Button(panel, label=_("Collapse Category"))
        self.collapse_btn.SetName(_("Collapse Category"))
        toolbar.Add(self.collapse_btn, 0, wx.RIGHT, 6)
        self.open_btn = wx.Button(panel, label=_("Open or Play Article"))
        self.open_btn.SetName(_("Open or Play Article"))
        toolbar.Add(self.open_btn, 0, wx.RIGHT, 6)
        self.mark_read_btn = wx.Button(panel, label=_("Mark Read"))
        self.mark_read_btn.SetName(_("Mark Read"))
        toolbar.Add(self.mark_read_btn, 0, wx.RIGHT, 6)
        self.mark_unread_btn = wx.Button(panel, label=_("Mark Unread"))
        self.mark_unread_btn.SetName(_("Mark Unread"))
        toolbar.Add(self.mark_unread_btn, 0, wx.RIGHT, 6)
        self.download_btn = wx.Button(panel, label=_("Download"))
        self.download_btn.SetName(_("Download Article"))
        self.download_btn.Enable(False)
        toolbar.Add(self.download_btn, 0, wx.RIGHT, 6)
        self.rich_view_chk = wx.CheckBox(panel, label=_("Rich View"))
        self.rich_view_chk.SetName(_("Rich Full-Text View"))
        self.rich_view_chk.SetValue(self._rich_view_enabled())
        toolbar.Add(self.rich_view_chk, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(toolbar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_lbl = wx.StaticText(panel, label=_("Filter Articles:"))
        search_row.Add(search_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.search_ctrl = wx.TextCtrl(panel)
        self.search_ctrl.SetName(_("Accessible Article Filter"))
        try:
            search_lbl.SetLabelFor(self.search_ctrl)
        except Exception:
            pass
        search_row.Add(self.search_ctrl, 1, wx.EXPAND)
        root.Add(search_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        content = wx.BoxSizer(wx.HORIZONTAL)

        left = wx.BoxSizer(wx.VERTICAL)
        views_lbl = wx.StaticText(panel, label=_("Views"))
        left.Add(views_lbl, 0, wx.BOTTOM, 4)
        self.view_list = wx.ListBox(panel)
        self.view_list.SetName(_("Accessible Views"))
        # Cap the list width so long feed labels don't starve the reader pane (which
        # otherwise gets squeezed to one word per line). Long labels truncate/scroll.
        self.view_list.SetMinSize((240, 240))
        try:
            views_lbl.SetLabelFor(self.view_list)
        except Exception:
            pass
        left.Add(self.view_list, 1, wx.EXPAND)
        self.view_hint_lbl = wx.StaticText(
            panel,
            label=_(
                "Categories can be expanded or collapsed. "
                "Use the buttons, or use Right Arrow to expand and Left Arrow to collapse."
            ),
        )
        left.Add(self.view_hint_lbl, 0, wx.TOP, 6)
        content.Add(left, 1, wx.ALL | wx.EXPAND, 8)

        middle = wx.BoxSizer(wx.VERTICAL)
        articles_lbl = wx.StaticText(panel, label=_("Articles"))
        middle.Add(articles_lbl, 0, wx.BOTTOM, 4)
        self.article_list = wx.ListBox(panel)
        self.article_list.SetName(_("Accessible Articles"))
        self.article_list.SetMinSize((260, 240))
        try:
            articles_lbl.SetLabelFor(self.article_list)
        except Exception:
            pass
        middle.Add(self.article_list, 1, wx.EXPAND)
        self.status_lbl = wx.StaticText(panel, label=_("Choose a view to load articles."))
        middle.Add(self.status_lbl, 0, wx.TOP, 6)
        content.Add(middle, 1, wx.ALL | wx.EXPAND, 8)

        right = wx.BoxSizer(wx.VERTICAL)
        article_lbl = wx.StaticText(panel, label=_("Article Content"))
        self._article_content_label = article_lbl
        right.Add(article_lbl, 0, wx.BOTTOM, 4)
        self.content_ctrl = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP
        )
        self.content_ctrl.SetName(_("Accessible Article Content"))
        # Give the reader a generous minimum width so article text wraps as full lines,
        # not one word per line.
        self.content_ctrl.SetMinSize((620, 240))
        try:
            article_lbl.SetLabelFor(self.content_ctrl)
        except Exception:
            pass
        right.Add(self.content_ctrl, 1, wx.EXPAND)
        content.Add(right, 3, wx.ALL | wx.EXPAND, 8)
        # Kept for lazy creation of the rich (WebView) reader surface.
        self._reader_panel = panel
        self._reader_right_sizer = right

        root.Add(content, 1, wx.EXPAND)
        panel.SetSizer(root)

        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh_feeds)
        self.load_more_btn.Bind(wx.EVT_BUTTON, self.on_load_more)
        self.expand_btn.Bind(wx.EVT_BUTTON, self.on_expand_category)
        self.collapse_btn.Bind(wx.EVT_BUTTON, self.on_collapse_category)
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open_article)
        self.mark_read_btn.Bind(wx.EVT_BUTTON, self.on_mark_read)
        self.mark_unread_btn.Bind(wx.EVT_BUTTON, self.on_mark_unread)
        self.download_btn.Bind(wx.EVT_BUTTON, self.on_download_article)
        self.view_list.Bind(wx.EVT_LISTBOX, self.on_view_selected)
        self.view_list.Bind(wx.EVT_KEY_DOWN, self.on_view_list_key_down)
        self.view_list.Bind(wx.EVT_CONTEXT_MENU, self.on_view_context_menu)
        self.article_list.Bind(wx.EVT_LISTBOX, self.on_article_selected)
        self.article_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open_article)
        self.article_list.Bind(wx.EVT_KEY_DOWN, self.on_article_list_key_down)
        self.article_list.Bind(wx.EVT_CONTEXT_MENU, self.on_article_context_menu)
        self.content_ctrl.Bind(wx.EVT_TEXT_COPY, self.on_content_copy)
        self.content_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_content_focus)
        self.rich_view_chk.Bind(wx.EVT_CHECKBOX, self.on_toggle_rich_view)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search_changed)

        self._build_menu_bar()

        # Build the rich reader now if the shared setting opted into it, so the
        # WebView is ready before the first article is shown.
        if self._rich_view_enabled():
            self._apply_reader_mode()

        self.refresh_views()

    def on_content_copy(self, event):
        if copy_textctrl_selection_to_clipboard(self.content_ctrl):
            return
        event.Skip()

    # ---- Menu bar ---------------------------------------------------------
    # The accessible browser had no menu bar, so a VoiceOver user who preferred
    # this window could not reach Settings, the player dialogs, or app-level
    # tools at all. Nearly every command delegates to the existing MainFrame
    # handler; article-scoped items act on THIS window's selected article.

    def _menu_item(self, menu, label, handler, help_text=""):
        item = menu.Append(wx.ID_ANY, label, help_text)
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def _delegate(self, method_name, *args):
        """Invoke a MainFrame handler, guarded. Event-based handlers accept None."""
        fn = getattr(self.mainframe, method_name, None)
        if not callable(fn):
            log.debug("Accessible browser: MainFrame has no %s to delegate to", method_name)
            return
        try:
            fn(*args) if args else fn(None)
        except Exception:
            log.exception("Accessible browser delegate to %s failed", method_name)

    def _build_menu_bar(self):
        mb = wx.MenuBar()

        file_menu = wx.Menu()
        self._menu_item(file_menu, _("&Add Feed...\tCtrl+N"), lambda e: self._delegate("on_add_feed"))
        self._menu_item(file_menu, _("Detect Feeds on &Page..."), lambda e: self._delegate("on_detect_page_feeds"))
        self._menu_item(file_menu, _("Add &Category..."), lambda e: self._delegate("on_add_category"))
        self._menu_item(file_menu, _("New Smart F&older..."), lambda e: self._ctx_new_smart_folder())
        self._menu_item(file_menu, _("&Import OPML..."), lambda e: self._delegate("on_import_opml"))
        self._menu_item(file_menu, _("Import &YouTube Takeout..."), lambda e: self._delegate("on_import_youtube_takeout"))
        self._menu_item(file_menu, _("&Export OPML..."), lambda e: self._delegate("on_export_opml"))
        file_menu.AppendSeparator()
        self._menu_item(file_menu, _("&Refresh Feeds\tCtrl+R"), self.on_refresh_feeds)
        self._menu_item(file_menu, _("&Stop Refresh"), lambda e: self._delegate("on_stop_refresh"))
        self._menu_item(file_menu, _("Mark All in Current View as R&ead"), self.on_menu_mark_view_read)
        file_menu.AppendSeparator()
        self._menu_item(file_menu, _("&Settings..."), lambda e: self._delegate("on_settings"))
        self._menu_item(file_menu, _("Close &Window\tCtrl+W"), lambda e: self.Close())
        mb.Append(file_menu, _("&File"))

        article_menu = wx.Menu()
        self._menu_item(article_menu, _("&Open or Play"), self.on_open_article)
        self._menu_item(article_menu, _("Open in &Browser"), self.on_menu_open_in_browser)
        article_menu.AppendSeparator()
        self._menu_item(article_menu, _("Copy &Link"), self.on_menu_copy_link)
        self._menu_item(article_menu, _("Copy &Text"), self.on_menu_copy_text)
        self._menu_item(article_menu, _("Copy &Media Link"), self.on_menu_copy_media_link)
        article_menu.AppendSeparator()
        self._menu_item(article_menu, _("Toggle &Favorite\tCtrl+D"), self.on_toggle_favorite)
        self._menu_item(article_menu, _("Mark &Read"), self.on_mark_read)
        self._menu_item(article_menu, _("Mark &Unread"), self.on_mark_unread)
        self._menu_item(article_menu, _("De&lete"), self.on_delete_selected_article)
        article_menu.AppendSeparator()
        self._menu_item(article_menu, _("&Download"), self.on_download_article)
        self._menu_item(article_menu, _("Detect &Audio"), self.on_menu_detect_audio)
        self._menu_item(article_menu, _("&Find in Article...\tCtrl+F"), self.on_find_in_article)
        self._menu_item(article_menu, _("View &History..."), self.on_view_history)
        self._menu_item(article_menu, _("View Feed De&scription..."), self.on_view_feed_description)
        mb.Append(article_menu, _("&Article"))

        player_menu = wx.Menu()
        self._menu_item(player_menu, _("&Show or Hide Player"), lambda e: self._delegate("toggle_player_visibility"))
        self._menu_item(player_menu, _("Open Play &Queue..."), lambda e: self._delegate("on_open_play_queue"))
        self._menu_item(player_menu, _("Play &Next in Queue"), lambda e: self._delegate("on_play_queue_next"))
        self._menu_item(player_menu, _("Play &Previous in Queue"), lambda e: self._delegate("on_play_queue_prev"))
        self._menu_item(player_menu, _("&Equalizer..."), lambda e: self._delegate("on_open_equalizer"))
        mb.Append(player_menu, _("&Player"))

        tools_menu = wx.Menu()
        self._menu_item(tools_menu, _("&Persistent Search..."), lambda e: self._delegate("on_configure_persistent_search"))
        self._menu_item(tools_menu, _("&Filter Rules..."), lambda e: self._delegate("on_manage_filter_rules"))
        self._menu_item(tools_menu, _("Find a Podcast or &RSS..."), lambda e: self._delegate("on_find_feed"))
        self._menu_item(tools_menu, _("&Video Search..."), lambda e: self._delegate("on_ytdlp_global_search"))
        self._menu_item(tools_menu, _("Import Site &Cookies..."), lambda e: self._delegate("on_import_site_cookies"))
        mb.Append(tools_menu, _("&Tools"))

        help_menu = wx.Menu()
        self._menu_item(help_menu, _("&Keyboard Shortcuts..."), lambda e: self._delegate("on_open_keyboard_shortcuts"))
        self._menu_item(help_menu, _("View Feed &Errors..."), lambda e: self._delegate("on_view_feed_errors"))
        self._menu_item(help_menu, _("Check for &Updates..."), lambda e: self._delegate("on_check_updates"))
        self._menu_item(help_menu, _("&About"), lambda e: self._delegate("on_about"))
        mb.Append(help_menu, _("&Help"))

        self.SetMenuBar(mb)
        return mb

    def on_menu_open_in_browser(self, _event):
        _idx, art = self._selected_article()
        url = str(getattr(art, "url", "") or "") if art is not None else ""
        if not url:
            return
        try:
            webbrowser.open(url)
        except Exception:
            log.exception("Failed to open article in browser")

    def on_menu_copy_link(self, _event):
        _idx, art = self._selected_article()
        url = str(getattr(art, "url", "") or "") if art is not None else ""
        if url:
            copy_text_to_clipboard(url)

    def on_menu_copy_text(self, _event):
        _idx, art = self._selected_article()
        if art is None:
            return
        # Prefer the extracted full text currently in the reader; fall back to feed.
        text = str(getattr(self, "_current_body_text", "") or "")
        if not text:
            try:
                text = self.mainframe._strip_html(getattr(art, "content", "") or "")
            except Exception:
                text = str(getattr(art, "content", "") or "")
        if text:
            copy_text_to_clipboard(text)

    def on_menu_copy_media_link(self, _event):
        _idx, art = self._selected_article()
        media = str(getattr(art, "media_url", "") or "") if art is not None else ""
        if media:
            copy_text_to_clipboard(media)

    def on_menu_detect_audio(self, _event):
        _idx, art = self._selected_article()
        if art is not None:
            self._delegate("on_detect_audio", art)

    def on_menu_mark_view_read(self, _event):
        view_id = str(getattr(self, "current_view_id", "") or "").strip() or "all"
        try:
            self.mainframe._confirm_and_mark_all_read(
                view_id, _("Mark all items in this view as read?")
            )
        except Exception:
            log.exception("Mark all in view failed")

    def on_toggle_favorite(self, _event=None):
        _idx, article = self._selected_article()
        if article is None:
            return
        try:
            if not self.mainframe._supports_favorites():
                return
        except Exception:
            return
        try:
            new_state = self.mainframe.provider.toggle_favorite(article.id)
        except Exception:
            log.exception("Toggle favorite failed")
            return
        if new_state is None:
            return
        article.is_favorite = bool(new_state)
        try:
            msg = _("Added to favorites.") if new_state else _("Removed from favorites.")
            self.mainframe._announce_event("favorite_toggle", msg)
        except Exception:
            pass
        self._apply_filter()

    def on_delete_selected_article(self, _event=None):
        _idx, article = self._selected_article()
        if article is None:
            return
        aid = getattr(article, "id", None)
        if not aid:
            return
        try:
            supports = self.mainframe._supports_article_delete()
        except Exception:
            supports = True
        if not supports:
            return
        # Respect the shared "confirm before delete" setting (default on).
        try:
            confirm = bool(self.mainframe.config_manager.get("confirm_article_delete", True))
        except Exception:
            confirm = True
        if confirm:
            try:
                if wx.MessageBox(
                    _("Delete this article?"), _("Delete Article"),
                    wx.YES_NO | wx.ICON_QUESTION, self,
                ) != wx.YES:
                    return
            except Exception:
                pass

        def _worker():
            try:
                self.mainframe.provider.delete_article(aid)
            except Exception:
                log.exception("Delete article failed")

        threading.Thread(target=_worker, daemon=True).start()
        # Drop it from the local lists and refresh so the row disappears at once.
        try:
            self._base_articles = [
                a for a in self._base_articles if getattr(a, "id", None) != aid
            ]
        except Exception:
            pass
        self._apply_filter()
        try:
            self.mainframe._announce_event("general", _("Article deleted."))
        except Exception:
            pass

    def on_view_history(self, _event=None):
        _idx, article = self._selected_article()
        if article is not None:
            self._delegate("on_view_article_history", article)

    def on_view_feed_description(self, _event=None):
        _idx, article = self._selected_article()
        if article is None:
            return
        try:
            desc = self.mainframe._article_description_text(article)
        except Exception:
            desc = ""
        if not desc:
            desc = _("No feed description is available for this item.")
        try:
            wx.MessageBox(desc, _("Feed Description"), wx.OK | wx.ICON_INFORMATION, self)
        except Exception:
            pass

    def on_find_in_article(self, _event=None):
        """Simple find within the reader text, with wrap-around and re-find."""
        try:
            haystack = self.content_ctrl.GetValue() or ""
        except Exception:
            haystack = ""
        if not haystack:
            return
        default = str(getattr(self, "_last_find_term", "") or "")
        dlg = wx.TextEntryDialog(self, _("Find in article:"), _("Find"), default)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            term = dlg.GetValue()
        finally:
            dlg.Destroy()
        term = str(term or "").strip()
        if not term:
            return
        self._last_find_term = term
        # Search AFTER the current caret first, then wrap to the top.
        try:
            start = self.content_ctrl.GetInsertionPoint()
        except Exception:
            start = 0
        low_hay = haystack.lower()
        low_term = term.lower()
        pos = low_hay.find(low_term, start)
        if pos < 0:
            pos = low_hay.find(low_term, 0)
        if pos < 0:
            try:
                self.mainframe._announce(_('"{term}" was not found.').format(term=term))
            except Exception:
                pass
            return
        try:
            self.content_ctrl.SetFocus()
            self.content_ctrl.SetSelection(pos, pos + len(term))
            self.content_ctrl.ShowPosition(pos)
        except Exception:
            pass

    def on_article_context_menu(self, _event):
        _idx, article = self._selected_article()
        menu = wx.Menu()
        self._menu_item(menu, _("&Open or Play"), self.on_open_article)
        self._menu_item(menu, _("Open in &Browser"), self.on_menu_open_in_browser)
        menu.AppendSeparator()
        self._menu_item(menu, _("Copy &Link"), self.on_menu_copy_link)
        self._menu_item(menu, _("Copy &Text"), self.on_menu_copy_text)
        self._menu_item(menu, _("Copy &Media Link"), self.on_menu_copy_media_link)
        menu.AppendSeparator()
        fav_label = _("Remove from &Favorites") if bool(getattr(article, "is_favorite", False)) else _("Add to &Favorites")
        self._menu_item(menu, fav_label, self.on_toggle_favorite)
        self._menu_item(menu, _("Mark &Read"), self.on_mark_read)
        self._menu_item(menu, _("Mark &Unread"), self.on_mark_unread)
        if self._in_deleted_view():
            self._menu_item(menu, _("&Restore"), self.on_restore_article)
        else:
            self._menu_item(menu, _("&Delete"), self.on_delete_selected_article)
        menu.AppendSeparator()
        self._menu_item(menu, _("&Download"), self.on_download_article)
        self._menu_item(menu, _("Detect &Audio"), self.on_menu_detect_audio)
        self._menu_item(menu, _("&Find in Article..."), self.on_find_in_article)
        self._menu_item(menu, _("View &History..."), self.on_view_history)
        self._menu_item(menu, _("View Feed De&scription..."), self.on_view_feed_description)
        try:
            self.article_list.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _in_deleted_view(self):
        try:
            return bool(self.mainframe._is_deleted_view(str(getattr(self, "current_view_id", "") or "")))
        except Exception:
            return False

    def on_restore_article(self, _event=None):
        _idx, article = self._selected_article()
        if article is None:
            return
        aid = getattr(article, "id", None)
        if not aid:
            return
        feed_id = getattr(article, "feed_id", None)

        def _worker():
            try:
                self.mainframe.provider.restore_article(aid, feed_id)
            except Exception:
                log.exception("Restore article failed")

        threading.Thread(target=_worker, daemon=True).start()
        try:
            self._base_articles = [
                a for a in self._base_articles if getattr(a, "id", None) != aid
            ]
        except Exception:
            pass
        self._apply_filter()
        try:
            self.mainframe._announce_event("general", _("Article restored."))
        except Exception:
            pass

    # ---- View-list (feed/category) context menu ---------------------------

    def on_view_context_menu(self, _event):
        entry = self._selected_view_entry()
        if not entry:
            return
        kind = str(entry.get("kind", "") or "")
        menu = wx.Menu()
        if kind == "feed":
            feed_id = str(entry.get("view_id", "") or "")
            self._menu_item(menu, _("&Refresh Feed"), lambda e: self._ctx_refresh_feed(feed_id))
            self._menu_item(menu, _("Mark All as &Read"), lambda e: self._ctx_mark_view_read(feed_id))
            self._menu_item(menu, _("&Copy Feed URL"), lambda e: self._ctx_copy_feed_url(feed_id))
            notif = menu.AppendCheckItem(wx.ID_ANY, _("&Notifications for This Feed"))
            try:
                notif.Check(bool(self.mainframe._is_feed_notifications_enabled(feed_id)))
            except Exception:
                pass
            self.Bind(wx.EVT_MENU, lambda e, fid=feed_id: self._ctx_toggle_notifications(fid), notif)
            img = wx.Menu()
            self._menu_item(img, _("Use default setting"), lambda e: self._delegate("on_set_feed_images", feed_id, None))
            self._menu_item(img, _("Always show image alt text"), lambda e: self._delegate("on_set_feed_images", feed_id, True))
            self._menu_item(img, _("Never show image alt text"), lambda e: self._delegate("on_set_feed_images", feed_id, False))
            menu.AppendSubMenu(img, _("Image Alt Text"))
            menu.AppendSeparator()
            self._menu_item(menu, _("Remove &Feed"), lambda e: self._ctx_remove_feed(feed_id))
        elif kind == "category":
            cat = str(entry.get("cat_name", "") or "")
            self._menu_item(menu, _("&Refresh Category"), lambda e: self._delegate("on_refresh_category", None, cat))
            self._menu_item(menu, _("Mark All as &Read"), lambda e: self._ctx_mark_view_read(str(entry.get("view_id", "") or "")))
            self._menu_item(menu, _("&Edit Category"), lambda e: self._delegate("on_edit_category", cat))
            self._menu_item(menu, _("Add &Subcategory"), lambda e: self._delegate("on_add_subcategory", cat))
            menu.AppendSeparator()
            self._menu_item(menu, _("Remove &Category"), lambda e: self._ctx_remove_category(cat))
        menu.AppendSeparator()
        self._menu_item(menu, _("&Add Feed..."), lambda e: self._delegate("on_add_feed"))
        self._menu_item(menu, _("Add Cate&gory..."), lambda e: self._delegate("on_add_category"))
        self._menu_item(menu, _("New Smart &Folder..."), lambda e: self._ctx_new_smart_folder())
        try:
            self.view_list.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _ctx_refresh_feed(self, feed_id):
        if not feed_id:
            return
        try:
            self.mainframe._refresh_single_feed_thread(feed_id)
        except Exception:
            log.exception("Refresh feed failed")

    def _ctx_mark_view_read(self, view_id):
        vid = str(view_id or "").strip()
        if not vid:
            return
        try:
            self.mainframe._confirm_and_mark_all_read(
                vid, _("Mark all items in this view as read?")
            )
        except Exception:
            log.exception("Mark all read failed")

    def _ctx_copy_feed_url(self, feed_id):
        try:
            feed = self.mainframe.feed_map.get(feed_id)
        except Exception:
            feed = None
        url = str(getattr(feed, "url", "") or "") if feed else ""
        if url:
            copy_text_to_clipboard(url)

    def _ctx_toggle_notifications(self, feed_id):
        try:
            enabled = bool(self.mainframe._is_feed_notifications_enabled(feed_id))
            self.mainframe._set_feed_notifications_enabled(feed_id, not enabled)
        except Exception:
            log.exception("Toggle feed notifications failed")

    def _ctx_remove_feed(self, feed_id):
        if not feed_id:
            return
        try:
            title = self.mainframe._get_feed_title(feed_id)
        except Exception:
            title = ""
        try:
            if wx.MessageBox(
                _("Remove this feed?"), _("Confirm"),
                wx.YES_NO | wx.ICON_QUESTION, self,
            ) != wx.YES:
                return
        except Exception:
            pass
        try:
            self.mainframe.remove_feed_by_id(feed_id, title or None)
        except Exception:
            log.exception("Remove feed failed")

    def _ctx_remove_category(self, cat):
        if not cat:
            return
        try:
            # Defer to the main window's provider-aware guard: on Miniflux
            # "Uncategorized" is a real, deletable category (issue #86).
            protected = self.mainframe._is_protected_uncategorized(cat)
        except Exception:
            from core.categories import is_uncategorized
            protected = is_uncategorized(cat)
        if protected:
            wx.MessageBox(
                _("The Uncategorized folder cannot be removed."), _("Info"),
                wx.OK | wx.ICON_INFORMATION, self,
            )
            return
        try:
            if wx.MessageBox(
                _("Remove this category? Feeds will be moved to Uncategorized."),
                _("Confirm"), wx.YES_NO | wx.ICON_QUESTION, self,
            ) != wx.YES:
                return
        except Exception:
            pass
        try:
            if self.mainframe.provider.delete_category(cat):
                self.mainframe.refresh_feeds()
            else:
                wx.MessageBox(
                    _("Could not remove category."), _("Error"),
                    wx.OK | wx.ICON_ERROR, self,
                )
        except Exception:
            log.exception("Remove category failed")

    def _ctx_new_smart_folder(self):
        try:
            self.mainframe.on_new_smart_folder()
        except Exception:
            log.exception("New smart folder failed")

    def on_article_list_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_open_article(event)
            return
        if key == getattr(wx, "WXK_BACK", 8) and not (
            event.ControlDown()
            or event.ShiftDown()
            or event.AltDown()
            or event.MetaDown()
        ):
            self.on_toggle_read_status(event)
            return
        event.Skip()

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == getattr(wx, "WXK_BACK", 8) and not (
            event.ControlDown()
            or event.ShiftDown()
            or event.AltDown()
            or event.MetaDown()
        ):
            if self.FindFocus() is self.article_list:
                self.on_toggle_read_status(event)
                return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focused = self.FindFocus()
            if focused is self.view_list:
                if self._toggle_selected_category_expansion():
                    return
                entry = self._selected_view_entry()
                if entry:
                    self._load_view(entry["view_id"])
                    return
            if focused is self.article_list:
                self.on_open_article(event)
                return
            if focused is self.content_ctrl and self._open_content_link_at_cursor():
                return
        focused = self.FindFocus()
        ctrl_or_cmd = event.ControlDown() or event.MetaDown()
        # Ctrl/Cmd+D: toggle favorite on the selected article (mirrors main window).
        if key in (ord("D"), ord("d")) and ctrl_or_cmd and not (event.AltDown() or event.ShiftDown()):
            self.on_toggle_favorite(event)
            return
        # Ctrl/Cmd+F: find within the reader (not while typing in the filter box).
        if key in (ord("F"), ord("f")) and ctrl_or_cmd and focused is not self.search_ctrl:
            self.on_find_in_article(event)
            return
        # Delete: delete the selected article.
        if (
            key == getattr(wx, "WXK_DELETE", 127)
            and focused is self.article_list
            and not (event.ControlDown() or event.ShiftDown() or event.AltDown() or event.MetaDown())
        ):
            self.on_delete_selected_article(event)
            return
        event.Skip()

    def _open_content_link_at_cursor(self) -> bool:
        """Open the link under the reader caret (opt-in). Mirrors the main frame."""
        mainframe = getattr(self, "mainframe", None)
        if mainframe is None or not mainframe._content_links_enabled():
            return False
        try:
            text = self.content_ctrl.GetValue()
            pos = self.content_ctrl.GetInsertionPoint()
        except Exception:
            return False
        url = mainframe._find_url_at_content_position(text, pos)
        if not url:
            return False
        safe_url = mainframe._validated_chapter_web_url(url)
        if safe_url is None:
            return False
        try:
            webbrowser.open(safe_url)
            return True
        except Exception:
            return False

    def refresh_views(self, selected_view_id=None):
        selected_view_id = selected_view_id or self.current_view_id or getattr(self.mainframe, "current_feed_id", None) or "all"
        entries = list(getattr(self.mainframe, "_accessible_view_entries", []) or [])
        if not entries:
            try:
                include_favorites = bool(self.mainframe._supports_favorites())
            except Exception:
                include_favorites = False
            entries = build_accessible_view_entries(
                list(getattr(self.mainframe, "feed_map", {}).values()),
                [],
                {},
                include_favorites=include_favorites,
            )
        # Offer a Deleted Articles view when the provider supports restoring.
        try:
            if self.mainframe._supports_restore_deleted() and not any(
                str(e.get("view_id", "")) == "deleted:all" for e in entries
            ):
                entries = list(entries) + [{
                    "label": _("Deleted Articles"),
                    "view_id": "deleted:all",
                    "kind": "special",
                    "parent_cats": [],
                }]
        except Exception:
            pass
        self._view_entries = entries
        self._view_index_by_id = {entry["view_id"]: idx for idx, entry in enumerate(entries)}
        self._sync_expanded_categories()
        self._ensure_view_visible(selected_view_id)
        self._refresh_view_list(selected_view_id=selected_view_id, load_view=True)

    def focus_view(self, view_id):
        if not view_id:
            return
        idx = self._view_index_by_id.get(view_id)
        if idx is None:
            self.refresh_views(selected_view_id=view_id)
            return
        self._ensure_view_visible(view_id)
        self._refresh_view_list(selected_view_id=view_id, load_view=False)
        visible_idx = self._visible_view_index_by_id.get(view_id)
        if visible_idx is None:
            self.refresh_views(selected_view_id=view_id)
            return
        self.view_list.SetSelection(visible_idx)
        self._load_view(view_id)
        try:
            self.view_list.SetFocus()
        except Exception:
            pass

    def on_refresh_feeds(self, _event):
        self.mainframe.refresh_feeds()
        self.status_lbl.SetLabel(_("Refreshing feeds..."))

    def on_view_selected(self, _event):
        entry = self._selected_view_entry()
        if not entry:
            return
        self._update_category_buttons()
        self._load_view(entry["view_id"])

    def on_view_list_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RIGHT, wx.WXK_ADD, ord("+")):
            if self._set_selected_category_expanded(True):
                return
        if key in (wx.WXK_LEFT, wx.WXK_SUBTRACT, ord("-")):
            if self._set_selected_category_expanded(False):
                return
        if key in (wx.WXK_SPACE,):
            if self._toggle_selected_category_expansion():
                return
        if key == wx.WXK_F2 and not event.HasAnyModifiers():
            if self._edit_selected_view_entry():
                return
        event.Skip()

    def _edit_selected_view_entry(self) -> bool:
        """F2: open Properties for the selected feed or category.

        The main window's tree has had this since the shortcut registry existed;
        this window had no F2 at all, so the key did nothing here (issue #86).
        """
        entry = self._selected_view_entry()
        if not entry:
            return False
        kind = str(entry.get("kind", "") or "")
        if kind == "category":
            self._delegate("on_edit_category", str(entry.get("cat_name", "") or ""))
            return True
        if kind == "feed":
            feed_id = str(entry.get("view_id", "") or "")
            if feed_id:
                self._delegate("edit_feed_by_id", feed_id)
                return True
        return False

    def _selected_view_entry(self):
        idx = self.view_list.GetSelection()
        if idx == wx.NOT_FOUND or idx < 0 or idx >= len(self._visible_view_entries):
            return None
        return self._visible_view_entries[idx]

    def _selected_category_entry(self):
        entry = self._selected_view_entry()
        if not entry or str(entry.get("kind", "") or "") != "category":
            return None
        return entry

    def _sync_expanded_categories(self):
        category_names = {
            str(entry.get("cat_name", "") or "").strip()
            for entry in self._view_entries
            if str(entry.get("kind", "") or "") == "category" and str(entry.get("cat_name", "") or "").strip()
        }
        if not self._known_categories:
            self._expanded_categories = set(category_names)
        else:
            self._expanded_categories &= category_names
            self._expanded_categories |= (category_names - self._known_categories)
        self._known_categories = set(category_names)

    def _ensure_view_visible(self, view_id):
        if not view_id:
            return
        entry = next((item for item in self._view_entries if item.get("view_id") == view_id), None)
        if not entry:
            return
        for cat in entry.get("parent_cats", []) or []:
            cat_name = str(cat or "").strip()
            if cat_name:
                self._expanded_categories.add(cat_name)
        if str(entry.get("kind", "") or "") == "category":
            cat_name = str(entry.get("cat_name", "") or "").strip()
            if cat_name:
                self._expanded_categories.add(cat_name)

    def _refresh_view_list(self, selected_view_id=None, load_view=False):
        selected_view_id = selected_view_id or self.current_view_id or "all"
        visible_entries = visible_accessible_view_entries(self._view_entries, self._expanded_categories)
        labels = [format_accessible_view_label(entry, self._expanded_categories) for entry in visible_entries]
        self._visible_view_entries = visible_entries
        self._visible_view_index_by_id = {
            entry["view_id"]: idx for idx, entry in enumerate(self._visible_view_entries)
        }
        self.view_list.Set(labels)
        self._update_category_buttons()
        idx = self._visible_view_index_by_id.get(selected_view_id, 0)
        if self.view_list.GetCount() <= 0:
            return
        self.view_list.SetSelection(idx)
        if load_view:
            self._load_view(self._visible_view_entries[idx]["view_id"])

    def _set_selected_category_expanded(self, expanded: bool) -> bool:
        entry = self._selected_category_entry()
        if not entry:
            return False
        cat_name = str(entry.get("cat_name", "") or "").strip()
        if not cat_name:
            return False
        changed = False
        if expanded:
            if cat_name not in self._expanded_categories:
                self._expanded_categories.add(cat_name)
                changed = True
        else:
            if cat_name in self._expanded_categories:
                self._expanded_categories.discard(cat_name)
                changed = True
        if not changed:
            self._update_category_buttons()
            return True
        self._refresh_view_list(selected_view_id=entry["view_id"], load_view=False)
        label = entry['label'].replace(f'{_("Category:")} ', '', 1)
        if expanded:
            text = _("Expanded category: {label}").format(label=label)
        else:
            text = _("Collapsed category: {label}").format(label=label)
        self.status_lbl.SetLabel(text)
        return True

    def _toggle_selected_category_expansion(self) -> bool:
        entry = self._selected_category_entry()
        if not entry:
            return False
        cat_name = str(entry.get("cat_name", "") or "").strip()
        return self._set_selected_category_expanded(cat_name not in self._expanded_categories)

    def _update_category_buttons(self):
        entry = self._selected_category_entry()
        if not entry:
            self.expand_btn.Enable(False)
            self.collapse_btn.Enable(False)
            return
        cat_name = str(entry.get("cat_name", "") or "").strip()
        is_expanded = bool(cat_name and cat_name in self._expanded_categories)
        self.expand_btn.Enable(not is_expanded)
        self.collapse_btn.Enable(is_expanded)

    def on_expand_category(self, _event):
        self._set_selected_category_expanded(True)

    def on_collapse_category(self, _event):
        self._set_selected_category_expanded(False)

    def _load_view(self, view_id):
        if not view_id or self._loading:
            return
        self.current_view_id = str(view_id)
        self._loading = True
        self._base_articles = []
        self._current_articles = []
        self._paged_offset = 0
        self._total_articles = None
        # Drop any read-ahead prefetch queued for the previous view.
        with self._prefetch_lock:
            self._prefetch_queue.clear()
        self.article_list.Set([_("Loading articles...")])
        self.content_ctrl.SetValue("")
        self.status_lbl.SetLabel(_("Loading articles..."))
        threading.Thread(target=self._load_articles_page_thread, args=(self.current_view_id, 0), daemon=True).start()

    def _load_articles_page_thread(self, view_id, offset):
        page_size = int(getattr(self.mainframe, "article_page_size", 400) or 400)
        try:
            page, total = self.mainframe.provider.get_articles_page(view_id, offset=offset, limit=page_size)
            page = list(page or [])
            page.sort(key=lambda a: (getattr(a, "timestamp", 0.0), self.mainframe._article_cache_id(a)), reverse=True)
        except Exception as e:
            try:
                wx.CallAfter(self._load_articles_failed, view_id, str(e))
            except (AssertionError, RuntimeError):
                # The accessible window can close while this daemon fetch is
                # finishing. There is then no live wx.App to receive an error
                # callback, and shutdown should remain silent.
                pass
            return
        try:
            wx.CallAfter(self._finish_load_articles_page, view_id, offset, page, total)
        except (AssertionError, RuntimeError):
            # Normal shutdown race: the wx.App/window was destroyed after the
            # provider returned but before this callback could be queued.
            pass

    def _load_articles_failed(self, view_id, error_msg):
        if view_id != self.current_view_id:
            return
        self._loading = False
        self.article_list.Set([_("Failed to load articles.")])
        self.status_lbl.SetLabel(_("Failed to load articles: {error}").format(error=error_msg))

    def _finish_load_articles_page(self, view_id, offset, page, total):
        if view_id != self.current_view_id:
            return
        self._loading = False
        if offset == 0:
            self._base_articles = list(page or [])
        else:
            existing = {self.mainframe._article_cache_id(a) for a in self._base_articles}
            self._base_articles.extend(a for a in (page or []) if self.mainframe._article_cache_id(a) not in existing)
            self._base_articles.sort(
                key=lambda a: (getattr(a, "timestamp", 0.0), self.mainframe._article_cache_id(a)),
                reverse=True,
            )

        self._paged_offset = len(self._base_articles)
        self._total_articles = total
        self._apply_filter()

        loaded = len(self._base_articles)
        if total is None:
            self.status_lbl.SetLabel(_("Articles loaded: {count}.").format(count=loaded))
        else:
            self.status_lbl.SetLabel(
                _("Articles loaded: {count} of {total}.").format(
                    count=loaded,
                    total=int(total),
                )
            )
        self._update_load_more_enabled()

    def _apply_filter(self):
        query = str(self.search_ctrl.GetValue() or "").strip()
        # Keep the reader's place: rebuilding the list (e.g. after Load More
        # appends a page) must not throw the selection back to the top.
        selected_id = None
        sel_idx = self._selected_article_index()
        if sel_idx is not None:
            selected_id = self.mainframe._article_cache_id(self._current_articles[sel_idx])
        filtered = self.mainframe._filter_articles(self._base_articles, query)
        self._current_articles = self.mainframe._sort_articles_for_display(
            filtered, view_id=self.current_view_id
        )
        if not self._current_articles:
            self.article_list.Set([_("No articles found.")])
            self.content_ctrl.SetValue("")
            self._update_download_button(None)
            return
        self.article_list.Set([self._article_label(article) for article in self._current_articles])
        new_idx = 0
        restored = False
        if selected_id is not None:
            for i, a in enumerate(self._current_articles):
                if self.mainframe._article_cache_id(a) == selected_id:
                    new_idx = i
                    restored = True
                    break
        self.article_list.SetSelection(new_idx)
        if not restored:
            self._show_article_at_index(new_idx)

    def _article_label(self, article) -> str:
        title = self.mainframe._get_display_title(article)
        feed_title = ""
        try:
            feed = self.mainframe.feed_map.get(getattr(article, "feed_id", None))
            if feed:
                feed_title = str(getattr(feed, "title", "") or "").strip()
        except Exception:
            feed_title = ""
        author = str(getattr(article, "author", "") or "").strip()
        date_text = utils.humanize_article_date(getattr(article, "date", "") or "")
        status = "Read" if bool(getattr(article, "is_read", False)) else "Unread"
        parts = [title]
        if feed_title:
            parts.append(feed_title)
        if author:
            parts.append(author)
        if date_text:
            parts.append(date_text)
        parts.append(status)
        return " | ".join(parts)

    def _selected_article_index(self):
        idx = self.article_list.GetSelection()
        if idx == wx.NOT_FOUND or idx < 0 or idx >= len(self._current_articles):
            return None
        return idx

    def _selected_article(self):
        idx = self._selected_article_index()
        if idx is None:
            return None, None
        return idx, self._current_articles[idx]

    def on_article_selected(self, _event):
        idx = self._selected_article_index()
        if idx is None:
            return
        self._show_article_at_index(idx)

    def _article_header(self, article) -> str:
        header = [
            str(getattr(article, "title", "") or ""),
            _("Date:") + f" {utils.humanize_article_date(getattr(article, 'date', '') or '')}",
            _("Author:") + f" {str(getattr(article, 'author', '') or '')}",
            _("Link:") + f" {str(getattr(article, 'url', '') or '')}",
            "-" * 40,
            "",
        ]
        return "\n".join(header)

    def _chapter_text(self, art_id) -> str:
        chapter_cache = getattr(self, "_chapter_cache", {})
        if art_id in chapter_cache:
            return format_accessible_chapters(chapter_cache[art_id])
        if art_id in getattr(self, "_chapter_inflight", set()):
            return _("Chapter availability: Loading.")
        return ""

    def _compose_article_content(self, article, art_id, body) -> str:
        text = self._article_header(article) + str(body or "")
        chapter_text = self._chapter_text(art_id)
        if chapter_text:
            text = text.rstrip() + "\n\n" + chapter_text + "\n"
        return text

    def _replace_macos_plain_reader(self, displayed, insertion_point, selection) -> bool:
        """Install a fresh TextCtrl so VoiceOver sees the completed article."""
        if sys.platform != "darwin":
            return False
        old = self.content_ctrl
        new = None
        swapped = False
        try:
            had_focus = wx.Window.FindFocus() is old
            was_shown = old.IsShown()
            new = wx.TextCtrl(
                old.GetParent(),
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
            )
            new.SetName(_("Accessible Article Content"))
            new.SetMinSize((620, 240))
            new.Bind(wx.EVT_TEXT_COPY, self.on_content_copy)
            new.Bind(wx.EVT_SET_FOCUS, self.on_content_focus)
            new.Hide()
            new.ChangeValue(displayed)
            try:
                new.MoveBeforeInTabOrder(old)
            except Exception:
                pass
            end = len(displayed)
            if selection is not None:
                new.SetSelection(min(selection[0], end), min(selection[1], end))
            elif insertion_point is not None:
                new.SetInsertionPoint(min(insertion_point, end))
            else:
                new.SetInsertionPoint(0)
            if not self._reader_right_sizer.Replace(old, new):
                new.Destroy()
                return False
            swapped = True
            self.content_ctrl = new
            try:
                self._article_content_label.SetLabelFor(new)
            except Exception:
                pass
            new.Show(was_shown)
            old.Hide()
            self._reader_panel.Layout()
            notify_reader_content_changed(new, tree_changed=True)
            if had_focus:
                wx.CallAfter(new.SetFocus)
            wx.CallAfter(old.Destroy)
            return True
        except Exception:
            log.debug("macOS reader control replacement failed", exc_info=True)
            try:
                if swapped and new is not None and self._reader_right_sizer.Replace(new, old):
                    self.content_ctrl = old
                    old.Show()
                    self._reader_panel.Layout()
                if new is not None and new is not self.content_ctrl:
                    new.Destroy()
            except Exception:
                log.debug("macOS reader control rollback failed", exc_info=True)
            return False

    def _set_article_content(
        self,
        article,
        art_id,
        body,
        *,
        preserve_position=False,
        refresh_accessibility=False,
    ):
        insertion_point = None
        selection = None
        if preserve_position:
            try:
                insertion_point = self.content_ctrl.GetInsertionPoint()
                selection = self.content_ctrl.GetSelection()
            except Exception:
                pass
        self._current_body_art_id = art_id
        self._current_body_text = str(body or "")
        displayed = self._compose_article_content(article, art_id, body)
        replaced = False
        if refresh_accessibility:
            replaced = self._replace_macos_plain_reader(
                displayed, insertion_point, selection
            )
        changed = replaced or replace_text_control_value(self.content_ctrl, displayed)
        if preserve_position:
            try:
                if selection is not None:
                    self.content_ctrl.SetSelection(*selection)
                elif insertion_point is not None:
                    self.content_ctrl.SetInsertionPoint(insertion_point)
            except Exception:
                pass
        if refresh_accessibility and changed and not replaced:
            notify_reader_content_changed(self.content_ctrl)

    # ---- Rich (HTML) reader surface ---------------------------------------
    # Mirrors MainFrame's opt-in "Rich Full-Text View": an AccessibleWebView
    # (WKWebView on macOS, read natively by VoiceOver) rendering the SAME HTML
    # that core.article_html produces for the main window. Falls back to the
    # plain TextCtrl whenever the WebView backend is missing.

    def _rich_view_enabled(self) -> bool:
        try:
            return bool(self.mainframe.config_manager.get("full_text_rich_view", False))
        except Exception:
            return False

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
                self._reader_panel,
                title=_("Article text"),
                lang=article_lang.app_ui_language(),
                live_region=False,
                # Ours, not the library's: its option diverts every navigation,
                # <iframe> loads included, which sent embeds to a browser window
                # instead of rendering them inline (issue #102).
                open_links_externally=False,
                on_return=self._on_rich_view_return,
            )
        except Exception:
            log.exception("Failed to create rich article view")
            self._rich_view_unavailable = True
            return None
        if not getattr(rv, "using_webview", False):
            # The library fell back to a degraded text control; prefer our own.
            self._rich_view_unavailable = True
            try:
                rv.control.Destroy()
            except Exception:
                pass
            return None
        self._rich_view = rv
        rich_view_links.attach(rv.view)
        self._reader_right_sizer.Add(rv.control, 1, wx.EXPAND)
        rv.control.Hide()
        try:
            self._reader_panel.Layout()
        except Exception:
            pass
        return rv

    def _rich_ready(self) -> bool:
        """True when the rich view is enabled AND a WebView backend exists."""
        return bool(self._rich_view_enabled() and self._ensure_rich_view() is not None)

    def _apply_reader_mode(self) -> bool:
        """Show either the plain text control or the rich WebView per the setting.

        Returns whether the rich surface is the one now shown.
        """
        want_rich = self._rich_view_enabled()
        rv = self._ensure_rich_view() if want_rich else self._rich_view
        use_rich = bool(want_rich and rv is not None)
        try:
            self.content_ctrl.Show(not use_rich)
        except Exception:
            pass
        if rv is not None:
            try:
                rv.control.Show(use_rich)
            except Exception:
                pass
        try:
            self._reader_panel.Layout()
        except Exception:
            pass
        return use_rich

    def _on_rich_view_return(self) -> None:
        """Escape/F6 inside the web view hands focus back to the article list."""
        try:
            self.article_list.SetFocus()
        except Exception:
            pass

    def _render_rich_html(self, html_body, *, refresh_accessibility=False) -> None:
        rv = self._ensure_rich_view()
        if rv is None:
            return
        try:
            if refresh_accessibility and sys.platform == "darwin":
                # A DOM mutation leaves VoiceOver on its cached pre-fetch AXWebArea.
                # Reloading the document publishes a new accessibility subtree.
                rv.clear()
                rv.set_content(html_body)
                rv.status(_("Full text loaded."))
                notify_reader_content_changed(rv.control, tree_changed=True)
            else:
                set_accessible_webview_content(rv, html_body)
                if refresh_accessibility:
                    notify_reader_content_changed(rv.control, tree_changed=True)
        except Exception:
            log.exception("Failed to set rich reader content")

    def _feed_language_for(self, feed_id):
        try:
            return self.mainframe._feed_language_for(feed_id)
        except Exception:
            return None

    def _rich_feed_content_html(self, article) -> str:
        """Instant no-network HTML view of the feed content shown on selection."""
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
        lang = article_lang.resolve_content_language(
            feed_item_lang=getattr(article, "language", None),
            feed_lang=self._feed_language_for(getattr(article, "feed_id", None)),
        )
        safe_lang = html_stdlib.escape(lang, quote=True)
        return f'<article lang="{safe_lang}">{header}<hr>{body}</article>'

    def _show_article_rich(self, article, art_id) -> None:
        """Render the rich surface: cached HTML, else instant feed HTML + async full text."""
        self._current_rich_art_id = art_id
        cached = self._rich_html_cache.get(art_id)
        if cached is not None:
            self._render_rich_html(cached)
            return
        try:
            self._render_rich_html(self._rich_feed_content_html(article))
        except Exception:
            pass
        self._schedule_rich_load(article, art_id)

    def _schedule_rich_load(self, article, art_id, force=False) -> None:
        if getattr(self, "_rich_debounce", None) is not None:
            try:
                self._rich_debounce.Stop()
            except Exception:
                pass
            self._rich_debounce = None
        self._rich_token += 1
        token = self._rich_token
        delay = 0 if force else int(getattr(self, "_fulltext_debounce_ms", 350))
        req = {
            "art_id": art_id,
            "url": getattr(article, "url", "") or "",
            "fallback_html": getattr(article, "content", "") or "",
            "fallback_title": getattr(article, "title", "") or "",
            "fallback_author": getattr(article, "author", "") or "",
            "date": utils.humanize_article_date(getattr(article, "date", "") or ""),
            "feed_item_lang": getattr(article, "language", "") or "",
            "feed_lang": self._feed_language_for(getattr(article, "feed_id", None)) or "",
            "token": token,
        }
        self._rich_debounce = wx.CallLater(delay, self._start_rich_load, req)

    def _start_rich_load(self, req) -> None:
        if req.get("token") != self._rich_token:
            return
        threading.Thread(target=self._rich_load_worker, args=(req,), daemon=True).start()

    def _rich_load_worker(self, req) -> None:
        html_body = None
        try:
            # max_pages=1: like the plain-text path, don't follow news-site "next"
            # links (they point to the NEXT STORY, not pagination).
            html_body = article_html.render_full_article_html(
                req.get("url", ""),
                fallback_html=req.get("fallback_html", ""),
                fallback_title=req.get("fallback_title", ""),
                fallback_author=req.get("fallback_author", ""),
                date=req.get("date", ""),
                feed_item_lang=req.get("feed_item_lang", ""),
                feed_lang=req.get("feed_lang", ""),
                max_pages=1,
            )
        except Exception:
            log.debug("Rich full-text render failed", exc_info=True)
            html_body = None
        try:
            wx.CallAfter(self._apply_rich_result, req.get("art_id"), html_body, req.get("token"))
        except Exception:
            pass

    def _apply_rich_result(self, art_id, html_body, token) -> None:
        if html_body:
            self._rich_html_cache[art_id] = html_body
        if token != self._rich_token:
            return
        if not html_body or self._current_rich_art_id != art_id:
            return
        self._render_rich_html(html_body, refresh_accessibility=True)
        log.debug(
            "Applied accessible rich full text for %s (%d characters)",
            art_id,
            len(html_body),
        )
        self._announce_fulltext_loaded()

    def on_toggle_rich_view(self, event=None) -> None:
        """Toolbar checkbox: switch between the plain text and rich HTML reader."""
        try:
            new_val = bool(self.rich_view_chk.GetValue())
        except Exception:
            new_val = not self._rich_view_enabled()
        try:
            self.mainframe.config_manager.set("full_text_rich_view", new_val)
        except Exception:
            log.exception("Failed to save rich-view toggle")
        use_rich = self._apply_reader_mode()
        # Reflect the EFFECTIVE state: the WebView backend may be unavailable, in
        # which case the checkbox snaps back so the user isn't misled.
        try:
            self.rich_view_chk.SetValue(use_rich if new_val else False)
        except Exception:
            pass
        idx = self._selected_article_index()
        if idx is not None:
            self._show_article_at_index(idx)

    def _cache_inline_chapters(self, article, art_id):
        chapters = normalize_accessible_chapters(getattr(article, "chapters", None))
        if not chapters:
            return
        self._chapter_cache[art_id] = chapters
        try:
            article.chapters = chapters
        except Exception:
            pass

    def _article_can_have_chapters(self, article) -> bool:
        return bool(
            getattr(article, "media_url", None)
            or getattr(article, "chapter_url", None)
            or getattr(article, "chapters", None)
        )

    def _start_chapters_load(self, article, art_id, token):
        if art_id in self._chapter_cache or art_id in self._chapter_inflight:
            return
        provider = getattr(self.mainframe, "provider", None)
        if not self._article_can_have_chapters(article) or not callable(
            getattr(provider, "get_article_chapters", None)
        ):
            return
        article_id = str(
            getattr(article, "id", "") or getattr(article, "article_id", "") or ""
        ).strip()
        if not article_id:
            return
        self._chapter_inflight.add(art_id)
        is_youtube = _article_is_youtube_video(article)
        if self._current_body_art_id == art_id and not is_youtube:
            self._set_article_content(
                article, art_id, self._current_body_text, preserve_position=True
            )
        threading.Thread(
            target=self._chapters_thread,
            args=(article_id, art_id, token),
            daemon=True,
        ).start()

    def _chapters_thread(self, article_id, art_id, token):
        chapters = None
        provider = getattr(self.mainframe, "provider", None)
        getter = getattr(provider, "get_article_chapters", None)
        if callable(getter):
            with self._provider_lock:
                try:
                    chapters = getter(article_id)
                except Exception:
                    chapters = None
        wx.CallAfter(self._finish_chapters, art_id, token, chapters)

    def _finish_chapters(self, art_id, token, chapters):
        self._chapter_inflight.discard(art_id)
        if chapters is not None:
            chapter_list = normalize_accessible_chapters(chapters)
            self._chapter_cache[art_id] = chapter_list
            for article in list(getattr(self, "_base_articles", []) or []) + list(
                getattr(self, "_current_articles", []) or []
            ):
                if self.mainframe._article_cache_id(article) == art_id:
                    try:
                        article.chapters = chapter_list
                    except Exception:
                        pass
        if token != self._content_token:
            return
        idx = self._selected_article_index()
        if idx is None:
            return
        article = self._current_articles[idx]
        if self.mainframe._article_cache_id(article) != art_id:
            return
        if (
            self._current_body_art_id == art_id
            and not _article_is_youtube_video(article)
        ):
            self._set_article_content(
                article, art_id, self._current_body_text, preserve_position=True
            )

    def _show_article_at_index(self, idx):
        if idx is None or idx < 0 or idx >= len(self._current_articles):
            self._update_download_button(None)
            return
        article = self._current_articles[idx]
        # New selection invalidates any in-flight background full-text load.
        self._content_token += 1
        token = self._content_token
        art_id = self.mainframe._article_cache_id(article)
        self._cache_inline_chapters(article, art_id)

        cached = self._fulltext_cache.get(art_id)
        if cached is not None:
            body = cached
        else:
            try:
                body = self.mainframe._strip_html(getattr(article, "content", "") or "")
                # Instant snippet is a raw feed render; drop leading toolbar/ad/
                # gallery chrome so the reader never opens on junk labels even
                # before the background full-text load lands.
                body = article_extractor._strip_leading_boilerplate(body)
            except Exception:
                body = str(getattr(article, "content", "") or "")
        self._set_article_content(article, art_id, body)
        self._update_download_button(article)
        self._start_chapters_load(article, art_id, token)
        if self._rich_ready():
            # The rich view runs its own HTML fetch; skip the parallel text
            # extraction and read-ahead prefetch so a site isn't hit twice.
            self._show_article_rich(article, art_id)
        else:
            if cached is None:
                self._schedule_fulltext(art_id, token)
            self._enqueue_prefetch_from(idx)

    def _enqueue_prefetch_from(self, idx):
        """Replace queued prefetch work with the bounded read-ahead window."""
        arts = self._current_articles
        pending = []
        for j in range(idx + 1, min(idx + 1 + self._prefetch_ahead, len(arts))):
            article = arts[j]
            art_id = self.mainframe._article_cache_id(article)
            if art_id in self._fulltext_cache:
                continue
            pending.append((art_id, article))
        with self._prefetch_lock:
            busy = set(self._prefetch_inflight)
            busy.update(self._fulltext_inflight)
            replacement = deque()
            for art_id, article in pending:
                if art_id in busy:
                    continue
                replacement.append((art_id, article))
                busy.add(art_id)
            self._prefetch_queue = replacement
            has_work = bool(replacement)
            if not has_work:
                self._prefetch_event.clear()
        if has_work:
            self._prefetch_event.set()

    def _prefetch_worker_loop(self):
        while True:
            self._prefetch_event.wait()
            if self._prefetch_stop:
                return
            item = None
            with self._prefetch_lock:
                if self._prefetch_queue:
                    item = self._prefetch_queue.popleft()
                if not self._prefetch_queue:
                    self._prefetch_event.clear()
            if not item:
                continue
            art_id, article = item
            with self._prefetch_lock:
                if (
                    art_id in self._fulltext_cache
                    or art_id in self._fulltext_inflight
                    or art_id in self._prefetch_inflight
                ):
                    continue
                self._prefetch_inflight.add(art_id)
            body = None
            cacheable = False
            try:
                body, cacheable = extract_article_body(
                    article,
                    provider_fetch=self._provider_fetch_locked,
                    max_pages=1,
                    encoding=self._feed_fulltext_encoding(getattr(article, "feed_id", None)),
                    metadata_sink=self._metadata_sink_for(article),
                )
            except Exception:
                body, cacheable = None, False
            if body and cacheable:
                body = self._maybe_translate(body)
            if self._prefetch_stop or wx.GetApp() is None:
                with self._prefetch_lock:
                    self._prefetch_inflight.discard(art_id)
                continue
            try:
                wx.CallAfter(
                    self._finish_prefetch,
                    art_id,
                    body if body and cacheable else None,
                )
            except AssertionError:
                with self._prefetch_lock:
                    self._prefetch_inflight.discard(art_id)

    def _finish_prefetch(self, art_id, body):
        with self._prefetch_lock:
            self._prefetch_inflight.discard(art_id)
        idx = self._selected_article_index()
        if idx is None:
            return
        article = self._current_articles[idx]
        if self.mainframe._article_cache_id(article) != art_id:
            return
        if not body:
            # The selected article's debounced on-demand load may have yielded to this
            # prefetch while it was in flight. If prefetch could not produce an
            # authoritative result, resume on-demand loading for the current selection.
            self._start_fulltext(art_id, self._content_token)
            return
        if art_id not in self._fulltext_cache:
            self._fulltext_cache[art_id] = body
        try:
            # A late prefetch completion must not move VoiceOver's reader cursor back
            # to the beginning after the user has started reading the snippet.
            changed = str(body or "") != str(getattr(self, "_current_body_text", "") or "")
            self._set_article_content(
                article,
                art_id,
                body,
                preserve_position=True,
                refresh_accessibility=changed,
            )
            if changed:
                self._announce_fulltext_loaded()
        except Exception:
            pass

    def _announce_fulltext_loaded(self, authoritative: bool = True):
        """Tell the screen reader what the async reader-pane update delivered.

        The extracted text replaces the feed snippet SILENTLY seconds after
        selection; a VoiceOver user who already read (or is reading) the
        snippet otherwise has no way to know the full article has arrived —
        which reads as "full text doesn't work" even when it loaded fine.

        ``authoritative`` False means every extraction route (web, fallback
        proxies, provider fetch) failed and the pane is showing feed content:
        say THAT, not "full text loaded" — a hard-paywalled article (e.g.
        Bloomberg) otherwise announces success while reading the summary.
        """
        message = (
            _("Full text loaded.")
            if authoritative
            else _("Full text unavailable. Showing feed content.")
        )
        try:
            self.mainframe._announce_event("general", message)
        except Exception:
            pass

    def _schedule_fulltext(self, art_id, token):
        """Debounce a background full-text load so rapid list navigation doesn't hammer sites."""
        timer = getattr(self, "_fulltext_timer", None)
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        self._fulltext_timer = wx.CallLater(
            int(getattr(self, "_fulltext_debounce_ms", 350)),
            self._start_fulltext,
            art_id,
            token,
        )

    def _start_fulltext(self, art_id, token):
        if token != self._content_token:
            return
        if art_id in self._fulltext_cache or art_id in self._fulltext_inflight:
            return
        with self._prefetch_lock:
            if art_id in self._prefetch_inflight:
                return
        article = next(
            (a for a in self._current_articles if self.mainframe._article_cache_id(a) == art_id),
            None,
        )
        if article is None:
            return
        self._fulltext_inflight.add(art_id)
        threading.Thread(
            target=self._fulltext_thread, args=(article, art_id, token), daemon=True
        ).start()

    def _feed_fulltext_encoding(self, feed_id) -> str:
        """Per-feed full-text decode override (issue #75), or "" when unset."""
        fid = str(feed_id or "").strip()
        if not fid:
            return ""
        try:
            from core import db
            return str((db.get_feed_settings(fid) or {}).get("fulltext_encoding") or "").strip()
        except Exception:
            return ""

    def _maybe_translate(self, body):
        """Translate the extracted body when translation is on; no-op otherwise.

        Runs on a background worker (network I/O). The MainFrame helper returns
        the input unchanged when translation is disabled or misconfigured.
        """
        text = str(body or "")
        if not text:
            return body
        try:
            return self.mainframe._translate_rendered_text_if_enabled(text)
        except Exception:
            return body

    def _metadata_sink_for(self, article):
        """Build a metadata-enrichment sink (author/tags for Filter Rules), or None.

        Mirrors MainFrame: enrichment runs off-thread so a slow SQLite write lock
        never stalls extraction, and any failure is swallowed.
        """
        aid = str(
            getattr(article, "id", "") or getattr(article, "article_id", "") or ""
        ).strip()
        if not aid:
            return None

        def _sink(html, page_url):
            def _enrich():
                try:
                    from core import metadata_enrich
                    metadata_enrich.enrich_stored_article(aid, html, page_url)
                except Exception:
                    pass
            try:
                threading.Thread(target=_enrich, daemon=True).start()
            except Exception:
                pass

        return _sink

    def _provider_fetch_locked(self, article_id, url):
        """Thread-safe wrapper over the provider's server-side full-text fetch."""
        prov = getattr(self.mainframe, "provider", None)
        fn = getattr(prov, "fetch_full_content", None)
        if not callable(fn):
            return None
        with self._provider_lock:
            try:
                return fn(article_id, url)
            except Exception:
                return None

    def _fulltext_thread(self, article, art_id, token):
        body = None
        cacheable = False
        try:
            # max_pages=1: don't follow "next" links — on news sites those point to the
            # NEXT STORY, not pagination, so following them merges unrelated articles.
            body, cacheable = extract_article_body(
                article,
                provider_fetch=self._provider_fetch_locked,
                max_pages=1,
                encoding=self._feed_fulltext_encoding(getattr(article, "feed_id", None)),
                metadata_sink=self._metadata_sink_for(article),
            )
        except Exception:
            log.exception("Full-text extraction failed for %s", art_id)
            body, cacheable = None, False
        if body:
            body = self._maybe_translate(body)
        wx.CallAfter(self._finish_fulltext, art_id, token, body, cacheable)

    def _finish_fulltext(self, art_id, token, body, cacheable):
        self._fulltext_inflight.discard(art_id)
        if body is None:
            return
        # Only cache authoritative results so a transient web failure (feed fallback)
        # retries on the next visit instead of being pinned to the snippet.
        if cacheable:
            self._fulltext_cache[art_id] = body
        if token != self._content_token:
            return
        idx = self._selected_article_index()
        if idx is None:
            return
        article = self._current_articles[idx]
        if self.mainframe._article_cache_id(article) != art_id:
            return
        try:
            # A late full-text completion must not move the reader cursor back
            # to the beginning after the user has started reading the snippet
            # (same rule as _finish_prefetch).
            changed = str(body or "") != str(getattr(self, "_current_body_text", "") or "")
            self._set_article_content(
                article,
                art_id,
                body,
                preserve_position=True,
                refresh_accessibility=changed,
            )
            log.debug(
                "Applied accessible plain full text for %s (%d characters)",
                art_id,
                len(body),
            )
            if changed or not cacheable:
                self._announce_fulltext_loaded(authoritative=bool(cacheable))
        except Exception:
            pass

    def on_content_focus(self, event):
        """Force an immediate full-text load (skip the debounce) when the reader pane is focused."""
        try:
            event.Skip()
        except Exception:
            pass
        idx = self._selected_article_index()
        if idx is None:
            return
        article = self._current_articles[idx]
        art_id = self.mainframe._article_cache_id(article)
        if art_id in self._fulltext_cache or art_id in self._fulltext_inflight:
            return
        self._start_fulltext(art_id, self._content_token)

    def Destroy(self):
        # Cancel any pending debounce so a one-shot timer can't fire after teardown.
        timer = getattr(self, "_fulltext_timer", None)
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
            self._fulltext_timer = None
        # Stop the prefetch worker.
        self._prefetch_stop = True
        try:
            self._prefetch_event.set()
        except Exception:
            pass
        return super().Destroy()

    def _update_download_button(self, article):
        has_media = bool(article and getattr(article, "media_url", None))
        try:
            self.download_btn.Enable(has_media)
        except Exception:
            pass

    def on_download_article(self, _event):
        _idx, article = self._selected_article()
        if article is None:
            return
        self.mainframe.on_download_article(article)

    def on_search_changed(self, _event):
        self._apply_filter()

    def _update_load_more_enabled(self):
        enabled = False
        try:
            if self._total_articles is None:
                enabled = bool(self._base_articles)
            else:
                enabled = int(self._paged_offset) < int(self._total_articles)
        except Exception:
            enabled = False
        self.load_more_btn.Enable(enabled)

    def on_load_more(self, _event):
        if self._loading or not self.current_view_id:
            return
        self._loading = True
        self.status_lbl.SetLabel(_("Loading more articles..."))
        threading.Thread(
            target=self._load_articles_page_thread,
            args=(self.current_view_id, int(self._paged_offset)),
            daemon=True,
        ).start()

    def _set_article_read_state(self, article, is_read):
        if article is None:
            return
        was_read = bool(getattr(article, "is_read", False))
        if was_read == bool(is_read):
            return
        article.is_read = bool(is_read)
        worker = self.mainframe.provider.mark_read if is_read else self.mainframe.provider.mark_unread
        threading.Thread(target=worker, args=(article.id,), daemon=True).start()
        delta = -1 if is_read else 1
        try:
            self.mainframe._update_feed_unread_count_ui(getattr(article, "feed_id", None), delta)
        except Exception:
            pass
        self._apply_filter()

    def on_mark_read(self, _event):
        idx, article = self._selected_article()
        if article is None:
            return
        self._set_article_read_state(article, True)
        if idx is not None and idx < self.article_list.GetCount():
            self.article_list.SetSelection(idx)
            self._show_article_at_index(idx)

    def on_mark_unread(self, _event):
        idx, article = self._selected_article()
        if article is None:
            return
        self._set_article_read_state(article, False)
        if idx is not None and idx < self.article_list.GetCount():
            self.article_list.SetSelection(idx)
            self._show_article_at_index(idx)

    def on_toggle_read_status(self, _event):
        idx, article = self._selected_article()
        if article is None:
            return
        self._set_article_read_state(article, not bool(getattr(article, "is_read", False)))
        if idx is not None and idx < self.article_list.GetCount():
            self.article_list.SetSelection(idx)
            self._show_article_at_index(idx)

    def on_open_article(self, _event):
        _idx, article = self._selected_article()
        if article is None:
            return
        self._set_article_read_state(article, True)
        self.mainframe._open_article(article)
