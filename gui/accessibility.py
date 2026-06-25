import logging
import math
import subprocess
import threading
from collections import deque
from collections.abc import Mapping

import wx

from core import utils
from core import article_extractor
from .clipboard_utils import copy_textctrl_selection_to_clipboard

log = logging.getLogger(__name__)


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
        title = str(chapter.get("title", "") or "").strip() or "Untitled chapter"
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
    lines = [f"Chapters available: {len(chapter_list)}."]
    for index, chapter in enumerate(chapter_list, start=1):
        timestamp = format_accessible_chapter_timestamp(chapter["start"])
        line = f"Chapter {index}: {timestamp}, {chapter['title']}."
        if chapter["href"]:
            line += f" Link: {chapter['href']}"
        lines.append(line)
    return "\n".join(lines)


def extract_article_body(article, *, provider_fetch=None, timeout: int = 20, max_pages: int = 6):
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
    has_web_target = bool(url) and not article_extractor._looks_like_media_url(url)

    # Always ATTEMPT web extraction for a real URL (the generic ">2500 chars" prefer-feed
    # heuristic wrongly suppressed it for substantial feeds like Miniflux). But web
    # extraction sometimes returns LESS than the feed already provides (truncated/partial
    # page) — replacing a fuller feed body with that shorter result is exactly what reads
    # as "full text doesn't work". So we extract the feed too and keep whichever is more
    # complete (longer), never downgrading the user below the feed content.
    web_text = None
    if has_web_target:
        try:
            art = article_extractor.extract_full_article(url, max_pages=max_pages, timeout=timeout)
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
        {"label": "All Articles", "view_id": "all", "kind": "special", "parent_cats": []},
        {"label": "Unread Articles", "view_id": "unread:all", "kind": "special", "parent_cats": []},
        {"label": "Read Articles", "view_id": "read:all", "kind": "special", "parent_cats": []},
    ]
    if include_favorites:
        entries.append({"label": "Favorites", "view_id": "favorites:all", "kind": "special", "parent_cats": []})

    feeds = list(feeds or [])
    hierarchy = dict(hierarchy or {})

    cat_names = {str(c or "").strip() for c in (categories or []) if str(c or "").strip()}
    for feed in feeds:
        cat_names.add(str(getattr(feed, "category", "") or "Uncategorized").strip() or "Uncategorized")
    if not cat_names and feeds:
        cat_names.add("Uncategorized")

    feeds_by_cat = {cat: [] for cat in cat_names}
    for feed in feeds:
        cat = str(getattr(feed, "category", "") or "Uncategorized").strip() or "Uncategorized"
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
        path_label = " > ".join(category_display_leaf(c) for c in category_path)
        cat_id = f"category:{cat}"
        entries.append(
            {
                "label": f"Category: {path_label}",
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
            label = f"Feed: {title}"
            if unread > 0:
                label += f", {unread} unread"
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
    state = "expanded" if cat_name and cat_name in expanded else "collapsed"
    return f"{indent}{label}, {state}" if indent else f"{label}, {state}"


class AccessibleBrowserFrame(wx.Frame):
    def __init__(self, mainframe):
        super().__init__(mainframe, title="BlindRSS Accessible Browser", size=(1280, 820))
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
            label=(
                "VoiceOver-friendly browser for feeds, articles, and content. "
                "Use the lists below to choose a view and article."
            ),
        )
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 8)

        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(panel, label="Refresh Feeds")
        self.refresh_btn.SetName("Refresh Feeds")
        toolbar.Add(self.refresh_btn, 0, wx.RIGHT, 6)
        self.load_more_btn = wx.Button(panel, label="Load More Articles")
        self.load_more_btn.SetName("Load More Articles")
        toolbar.Add(self.load_more_btn, 0, wx.RIGHT, 6)
        self.expand_btn = wx.Button(panel, label="Expand Category")
        self.expand_btn.SetName("Expand Category")
        toolbar.Add(self.expand_btn, 0, wx.RIGHT, 6)
        self.collapse_btn = wx.Button(panel, label="Collapse Category")
        self.collapse_btn.SetName("Collapse Category")
        toolbar.Add(self.collapse_btn, 0, wx.RIGHT, 6)
        self.open_btn = wx.Button(panel, label="Open or Play Article")
        self.open_btn.SetName("Open or Play Article")
        toolbar.Add(self.open_btn, 0, wx.RIGHT, 6)
        self.mark_read_btn = wx.Button(panel, label="Mark Read")
        self.mark_read_btn.SetName("Mark Read")
        toolbar.Add(self.mark_read_btn, 0, wx.RIGHT, 6)
        self.mark_unread_btn = wx.Button(panel, label="Mark Unread")
        self.mark_unread_btn.SetName("Mark Unread")
        toolbar.Add(self.mark_unread_btn, 0, wx.RIGHT, 6)
        self.download_btn = wx.Button(panel, label="Download")
        self.download_btn.SetName("Download Article")
        self.download_btn.Enable(False)
        toolbar.Add(self.download_btn, 0)
        root.Add(toolbar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_lbl = wx.StaticText(panel, label="Filter Articles:")
        search_row.Add(search_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.search_ctrl = wx.TextCtrl(panel)
        self.search_ctrl.SetName("Accessible Article Filter")
        try:
            search_lbl.SetLabelFor(self.search_ctrl)
        except Exception:
            pass
        search_row.Add(self.search_ctrl, 1, wx.EXPAND)
        root.Add(search_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        content = wx.BoxSizer(wx.HORIZONTAL)

        left = wx.BoxSizer(wx.VERTICAL)
        views_lbl = wx.StaticText(panel, label="Views")
        left.Add(views_lbl, 0, wx.BOTTOM, 4)
        self.view_list = wx.ListBox(panel)
        self.view_list.SetName("Accessible Views")
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
            label=(
                "Categories can be expanded or collapsed. "
                "Use the buttons, or use Right Arrow to expand and Left Arrow to collapse."
            ),
        )
        left.Add(self.view_hint_lbl, 0, wx.TOP, 6)
        content.Add(left, 1, wx.ALL | wx.EXPAND, 8)

        middle = wx.BoxSizer(wx.VERTICAL)
        articles_lbl = wx.StaticText(panel, label="Articles")
        middle.Add(articles_lbl, 0, wx.BOTTOM, 4)
        self.article_list = wx.ListBox(panel)
        self.article_list.SetName("Accessible Articles")
        self.article_list.SetMinSize((260, 240))
        try:
            articles_lbl.SetLabelFor(self.article_list)
        except Exception:
            pass
        middle.Add(self.article_list, 1, wx.EXPAND)
        self.status_lbl = wx.StaticText(panel, label="Choose a view to load articles.")
        middle.Add(self.status_lbl, 0, wx.TOP, 6)
        content.Add(middle, 1, wx.ALL | wx.EXPAND, 8)

        right = wx.BoxSizer(wx.VERTICAL)
        article_lbl = wx.StaticText(panel, label="Article Content")
        right.Add(article_lbl, 0, wx.BOTTOM, 4)
        self.content_ctrl = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP
        )
        self.content_ctrl.SetName("Accessible Article Content")
        # Give the reader a generous minimum width so article text wraps as full lines,
        # not one word per line.
        self.content_ctrl.SetMinSize((620, 240))
        try:
            article_lbl.SetLabelFor(self.content_ctrl)
        except Exception:
            pass
        right.Add(self.content_ctrl, 1, wx.EXPAND)
        content.Add(right, 3, wx.ALL | wx.EXPAND, 8)

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
        self.article_list.Bind(wx.EVT_LISTBOX, self.on_article_selected)
        self.article_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open_article)
        self.article_list.Bind(wx.EVT_KEY_DOWN, self.on_article_list_key_down)
        self.content_ctrl.Bind(wx.EVT_TEXT_COPY, self.on_content_copy)
        self.content_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_content_focus)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search_changed)

        self.refresh_views()

    def on_content_copy(self, event):
        if copy_textctrl_selection_to_clipboard(self.content_ctrl):
            return
        event.Skip()

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
        event.Skip()

    def refresh_views(self, selected_view_id=None):
        selected_view_id = selected_view_id or self.current_view_id or getattr(self.mainframe, "current_feed_id", None) or "all"
        entries = list(getattr(self.mainframe, "_accessible_view_entries", []) or [])
        if not entries:
            entries = build_accessible_view_entries(
                list(getattr(self.mainframe, "feed_map", {}).values()),
                [],
                {},
                include_favorites=False,
            )
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
        self.status_lbl.SetLabel("Refreshing feeds...")

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
        event.Skip()

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
        self.status_lbl.SetLabel(
            f"{'Expanded' if expanded else 'Collapsed'} category: {entry['label'].replace('Category: ', '', 1)}"
        )
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
        self.article_list.Set(["Loading articles..."])
        self.content_ctrl.SetValue("")
        self.status_lbl.SetLabel("Loading articles...")
        threading.Thread(target=self._load_articles_page_thread, args=(self.current_view_id, 0), daemon=True).start()

    def _load_articles_page_thread(self, view_id, offset):
        page_size = int(getattr(self.mainframe, "article_page_size", 400) or 400)
        try:
            page, total = self.mainframe.provider.get_articles_page(view_id, offset=offset, limit=page_size)
            page = list(page or [])
            page.sort(key=lambda a: (getattr(a, "timestamp", 0.0), self.mainframe._article_cache_id(a)), reverse=True)
            wx.CallAfter(self._finish_load_articles_page, view_id, offset, page, total)
        except Exception as e:
            wx.CallAfter(self._load_articles_failed, view_id, str(e))

    def _load_articles_failed(self, view_id, error_msg):
        if view_id != self.current_view_id:
            return
        self._loading = False
        self.article_list.Set(["Failed to load articles."])
        self.status_lbl.SetLabel(f"Failed to load articles: {error_msg}")

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
            self.status_lbl.SetLabel(f"Loaded {loaded} article(s).")
        else:
            self.status_lbl.SetLabel(f"Loaded {loaded} of {int(total)} article(s).")
        self._update_load_more_enabled()

    def _apply_filter(self):
        query = str(self.search_ctrl.GetValue() or "").strip()
        filtered = self.mainframe._filter_articles(self._base_articles, query)
        self._current_articles = self.mainframe._sort_articles_for_display(filtered)
        if not self._current_articles:
            self.article_list.Set(["No articles found."])
            self.content_ctrl.SetValue("")
            self._update_download_button(None)
            return
        self.article_list.Set([self._article_label(article) for article in self._current_articles])
        self.article_list.SetSelection(0)
        self._show_article_at_index(0)

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
            f"Date: {utils.humanize_article_date(getattr(article, 'date', '') or '')}",
            f"Author: {str(getattr(article, 'author', '') or '')}",
            f"Link: {str(getattr(article, 'url', '') or '')}",
            "-" * 40,
            "",
        ]
        return "\n".join(header)

    def _chapter_text(self, art_id) -> str:
        chapter_cache = getattr(self, "_chapter_cache", {})
        if art_id in chapter_cache:
            return format_accessible_chapters(chapter_cache[art_id])
        if art_id in getattr(self, "_chapter_inflight", set()):
            return "Chapter availability: Loading."
        return ""

    def _compose_article_content(self, article, art_id, body) -> str:
        text = self._article_header(article) + str(body or "")
        chapter_text = self._chapter_text(art_id)
        if chapter_text:
            text = text.rstrip() + "\n\n" + chapter_text + "\n"
        return text

    def _set_article_content(self, article, art_id, body, *, preserve_position=False):
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
        self.content_ctrl.SetValue(self._compose_article_content(article, art_id, body))
        if preserve_position:
            try:
                if selection is not None:
                    self.content_ctrl.SetSelection(*selection)
                elif insertion_point is not None:
                    self.content_ctrl.SetInsertionPoint(insertion_point)
            except Exception:
                pass

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
        if self._current_body_art_id == art_id:
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
        if self._current_body_art_id == art_id:
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
            except Exception:
                body = str(getattr(article, "content", "") or "")
        self._set_article_content(article, art_id, body)
        self._update_download_button(article)
        self._start_chapters_load(article, art_id, token)
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
                    article, provider_fetch=self._provider_fetch_locked, max_pages=1
                )
            except Exception:
                body, cacheable = None, False
            wx.CallAfter(
                self._finish_prefetch,
                art_id,
                body if body and cacheable else None,
            )

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
            self._set_article_content(article, art_id, body, preserve_position=True)
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
                article, provider_fetch=self._provider_fetch_locked, max_pages=1
            )
        except Exception:
            log.exception("Full-text extraction failed for %s", art_id)
            body, cacheable = None, False
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
            self._set_article_content(article, art_id, body)
            self.content_ctrl.SetInsertionPoint(0)
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
        self.status_lbl.SetLabel("Loading more articles...")
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
