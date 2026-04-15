import logging
import subprocess
import threading

import wx

from core import utils

log = logging.getLogger(__name__)


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
        {"label": "All Articles", "view_id": "all", "kind": "special"},
        {"label": "Unread Articles", "view_id": "unread:all", "kind": "special"},
        {"label": "Read Articles", "view_id": "read:all", "kind": "special"},
    ]
    if include_favorites:
        entries.append({"label": "Favorites", "view_id": "favorites:all", "kind": "special"})

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

    def _walk(cat, path):
        category_path = list(path) + [cat]
        path_label = " > ".join(category_path)
        entries.append(
            {
                "label": f"Category: {path_label}",
                "view_id": f"category:{cat}",
                "kind": "category",
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
                }
            )

        for child in children_of.get(cat, []):
            _walk(child, category_path)

    for cat in top_level:
        _walk(cat, [])

    return entries


class AccessibleBrowserFrame(wx.Frame):
    def __init__(self, mainframe):
        super().__init__(mainframe, title="BlindRSS Accessible Browser", size=(980, 760))
        self.mainframe = mainframe
        self.current_view_id = None
        self._view_entries = []
        self._view_index_by_id = {}
        self._base_articles = []
        self._current_articles = []
        self._paged_offset = 0
        self._total_articles = None
        self._loading = False

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
        self.open_btn = wx.Button(panel, label="Open or Play Article")
        self.open_btn.SetName("Open or Play Article")
        toolbar.Add(self.open_btn, 0, wx.RIGHT, 6)
        self.mark_read_btn = wx.Button(panel, label="Mark Read")
        self.mark_read_btn.SetName("Mark Read")
        toolbar.Add(self.mark_read_btn, 0, wx.RIGHT, 6)
        self.mark_unread_btn = wx.Button(panel, label="Mark Unread")
        self.mark_unread_btn.SetName("Mark Unread")
        toolbar.Add(self.mark_unread_btn, 0)
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
        try:
            views_lbl.SetLabelFor(self.view_list)
        except Exception:
            pass
        left.Add(self.view_list, 1, wx.EXPAND)
        content.Add(left, 1, wx.ALL | wx.EXPAND, 8)

        middle = wx.BoxSizer(wx.VERTICAL)
        articles_lbl = wx.StaticText(panel, label="Articles")
        middle.Add(articles_lbl, 0, wx.BOTTOM, 4)
        self.article_list = wx.ListBox(panel)
        self.article_list.SetName("Accessible Articles")
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
        self.content_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.content_ctrl.SetName("Accessible Article Content")
        try:
            article_lbl.SetLabelFor(self.content_ctrl)
        except Exception:
            pass
        right.Add(self.content_ctrl, 1, wx.EXPAND)
        content.Add(right, 2, wx.ALL | wx.EXPAND, 8)

        root.Add(content, 1, wx.EXPAND)
        panel.SetSizer(root)

        self.refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh_feeds)
        self.load_more_btn.Bind(wx.EVT_BUTTON, self.on_load_more)
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open_article)
        self.mark_read_btn.Bind(wx.EVT_BUTTON, self.on_mark_read)
        self.mark_unread_btn.Bind(wx.EVT_BUTTON, self.on_mark_unread)
        self.view_list.Bind(wx.EVT_LISTBOX, self.on_view_selected)
        self.article_list.Bind(wx.EVT_LISTBOX, self.on_article_selected)
        self.article_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_open_article)
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search_changed)

        self.refresh_views()

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
        self.view_list.Set([entry["label"] for entry in entries])
        idx = self._view_index_by_id.get(selected_view_id, 0)
        if self.view_list.GetCount() > 0:
            self.view_list.SetSelection(idx)
            self._load_view(entries[idx]["view_id"])

    def focus_view(self, view_id):
        if not view_id:
            return
        idx = self._view_index_by_id.get(view_id)
        if idx is None:
            self.refresh_views(selected_view_id=view_id)
            return
        self.view_list.SetSelection(idx)
        self._load_view(view_id)
        try:
            self.view_list.SetFocus()
        except Exception:
            pass

    def on_refresh_feeds(self, _event):
        self.mainframe.refresh_feeds()
        self.status_lbl.SetLabel("Refreshing feeds...")

    def on_view_selected(self, _event):
        idx = self.view_list.GetSelection()
        if idx == wx.NOT_FOUND or idx < 0 or idx >= len(self._view_entries):
            return
        self._load_view(self._view_entries[idx]["view_id"])

    def _load_view(self, view_id):
        if not view_id or self._loading:
            return
        self.current_view_id = str(view_id)
        self._loading = True
        self._base_articles = []
        self._current_articles = []
        self._paged_offset = 0
        self._total_articles = None
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

    def _show_article_at_index(self, idx):
        if idx is None or idx < 0 or idx >= len(self._current_articles):
            return
        article = self._current_articles[idx]
        header = [
            str(getattr(article, "title", "") or ""),
            f"Date: {utils.humanize_article_date(getattr(article, 'date', '') or '')}",
            f"Author: {str(getattr(article, 'author', '') or '')}",
            f"Link: {str(getattr(article, 'url', '') or '')}",
            "-" * 40,
            "",
        ]
        try:
            body = self.mainframe._strip_html(getattr(article, "content", "") or "")
        except Exception:
            body = str(getattr(article, "content", "") or "")
        self.content_ctrl.SetValue("\n".join(header) + body)

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

    def on_open_article(self, _event):
        _idx, article = self._selected_article()
        if article is None:
            return
        self._set_article_read_state(article, True)
        self.mainframe._open_article(article)
