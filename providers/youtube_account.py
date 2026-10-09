"""Local YouTube recommendations alongside any RSS provider.

Delegate ordinary RSS operations unchanged; account video IDs never reach
the hosted provider. Cache lives in rss.db so the normal backup includes it.
"""

from contextlib import closing

from core.db import get_connection
from core.i18n import _
from core.models import Article, Feed
from core.youtube_account import RECOMMENDATIONS_FEED_ID, account_key


class YouTubeAccountProvider:
    def __init__(self, provider, config):
        self.provider = provider
        self.config = config

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def _category(self):
        return str(self.config.get("youtube_account_category", "YouTube") or "YouTube")

    def _view(self, view):
        read = favorite = None
        view = str(view or "")
        while ":" in view:
            prefix, remainder = view.split(":", 1)
            if prefix in ("read", "unread"):
                read = prefix == "read"
            elif prefix in ("favorites", "fav", "starred"):
                favorite = True
            else:
                break
            view = remainder
        category = view.removeprefix("category:") if view.startswith("category:") else None
        included = view in ("all", RECOMMENDATIONS_FEED_ID) or (
            category is not None and (self._category() == category or self._category().startswith(category + " / "))
        )
        return view, included, read, favorite

    def _articles(self, view):
        real, included, read, favorite = self._view(view)
        account = account_key(self.config)
        if not account or not included:
            return []
        where = "account = ? AND is_deleted = 0"
        args = [account]
        if favorite:
            where += " AND is_favorite = 1"
        else:
            where += " AND current = 1"
        if read is not None:
            where += " AND is_read = ?"
            args.append(int(read))
        with closing(get_connection()) as conn:
            rows = conn.execute(
                f"SELECT video_id, title, author, date, is_read, is_favorite FROM youtube_recommendations "
                f"WHERE {where} ORDER BY current DESC, position, date DESC", args
            ).fetchall()
        return [self._article(account, row) for row in rows]

    @staticmethod
    def _article(account, row):
        video_id, title, author, date, read, favorite = row
        url = "https://www.youtube.com/watch?v=" + video_id
        return Article(title, url, "", date, author, RECOMMENDATIONS_FEED_ID,
                       id=f"{RECOMMENDATIONS_FEED_ID}:{account}:{video_id}",
                       is_read=bool(read), is_favorite=bool(favorite), media_url=url, media_type="video/youtube")

    def get_feeds(self):
        feeds = list(self.provider.get_feeds() or [])
        if not feeds:
            diagnostic = getattr(self.provider, "get_connection_error", lambda: None)()
            if diagnostic:
                raise RuntimeError(diagnostic)
        articles = self._articles(RECOMMENDATIONS_FEED_ID)
        if self._has_snapshot():
            feed = Feed(RECOMMENDATIONS_FEED_ID, _("Recommendations"), "https://www.youtube.com/", self._category())
            feed.unread_count = sum(not a.is_read for a in articles)
            feeds.append(feed)
        return feeds

    def _has_snapshot(self):
        with closing(get_connection()) as conn:
            return conn.execute("SELECT 1 FROM youtube_recommendations WHERE account = ? AND current = 1 LIMIT 1",
                                (account_key(self.config),)).fetchone() is not None

    def get_categories(self):
        categories = list(self.provider.get_categories() or [])
        if self._has_snapshot() and self._category() not in categories:
            categories.append(self._category())
        return categories

    def _move_account_category(self, old, new):
        category = self._category()
        if category == old or category.startswith(old + " / "):
            self.config.set("youtube_account_category", new + category[len(old):])

    def rename_category(self, old_title, new_title):
        if not self.provider.rename_category(old_title, new_title):
            return False
        from core.db import make_category_path, sanitize_category_leaf
        parent = old_title.rsplit(" / ", 1)[0] if " / " in old_title else None
        self._move_account_category(old_title, make_category_path(parent, sanitize_category_leaf(new_title)))
        return True

    def move_category(self, title, parent_title=None):
        if not self.provider.move_category(title, parent_title):
            return False
        from core.db import category_display_leaf, make_category_path
        self._move_account_category(title, make_category_path(parent_title, category_display_leaf(title)))
        return True

    def get_articles(self, view):
        local = self._articles(view)
        return local if self._view(view)[0] == RECOMMENDATIONS_FEED_ID else local + list(self.provider.get_articles(view) or [])

    def merge_recommendations(self, view, articles):
        """Replace account rows in a cached view without refetching RSS history."""
        latest = self._articles(view)
        previous = [a for a in articles if a.feed_id == RECOMMENDATIONS_FEED_ID]
        def signature(rows):
            return [(a.id, a.title, a.author, a.is_read, a.is_favorite) for a in rows]
        if signature(previous) == signature(latest):
            return None
        return [a for a in articles if a.feed_id != RECOMMENDATIONS_FEED_ID] + latest

    def get_articles_page(self, view, offset=0, limit=200):
        local = self._articles(view)
        offset, limit = max(0, int(offset)), max(0, int(limit or 0))
        page = local[offset:offset + limit]
        if self._view(view)[0] == RECOMMENDATIONS_FEED_ID:
            return page, len(local)
        remaining = limit - len(page)
        remote, total = self.provider.get_articles_page(view, max(0, offset - len(local)), max(1, remaining))
        return page + list(remote or [])[:remaining], None if total is None else total + len(local)

    @staticmethod
    def _is_account_article(article_id):
        return str(article_id).startswith(RECOMMENDATIONS_FEED_ID + ":")

    def _video_id(self, article_id):
        account = account_key(self.config)
        prefix = f"{RECOMMENDATIONS_FEED_ID}:{account}:"
        return str(article_id)[len(prefix):] if account and str(article_id).startswith(prefix) else None

    def get_article_by_id(self, article_id):
        if not self._is_account_article(article_id):
            return self.provider.get_article_by_id(article_id)
        with closing(get_connection()) as conn:
            row = conn.execute(
                "SELECT video_id, title, author, date, is_read, is_favorite FROM youtube_recommendations "
                "WHERE account = ? AND video_id = ? AND is_deleted = 0",
                (account_key(self.config), self._video_id(article_id)),
            ).fetchone()
        return self._article(account_key(self.config), row) if row else None

    def _set_state(self, article_id, column, value):
        with closing(get_connection()) as conn, conn:
            return conn.execute(
                f"UPDATE youtube_recommendations SET {column} = ? WHERE account = ? AND video_id = ?",
                (int(value), account_key(self.config), self._video_id(article_id)),
            ).rowcount > 0

    def mark_read(self, article_id):
        return self._set_state(article_id, "is_read", True) if self._is_account_article(article_id) else self.provider.mark_read(article_id)

    def mark_unread(self, article_id):
        return self._set_state(article_id, "is_read", False) if self._is_account_article(article_id) else self.provider.mark_unread(article_id)

    def mark_read_batch(self, article_ids):
        local = [aid for aid in article_ids if self._is_account_article(aid)]
        remote = [aid for aid in article_ids if not self._is_account_article(aid)]
        local_ok = all([self.mark_read(aid) for aid in local])
        return (self.provider.mark_read_batch(remote) if remote else True) and local_ok

    def mark_all_read(self, view):
        local_ok = self.mark_read_batch([a.id for a in self._articles(view)])
        return local_ok if self._view(view)[0] == RECOMMENDATIONS_FEED_ID else self.provider.mark_all_read(view) and local_ok

    def set_favorite(self, article_id, value):
        return self._set_state(article_id, "is_favorite", value) if self._is_account_article(article_id) else self.provider.set_favorite(article_id, value)

    def toggle_favorite(self, article_id):
        if not self._is_account_article(article_id):
            return self.provider.toggle_favorite(article_id)
        article = self.get_article_by_id(article_id)
        if article and self.set_favorite(article_id, not article.is_favorite):
            return not article.is_favorite
        return None

    def delete_article(self, article_id, *args, **kwargs):
        return self._set_state(article_id, "is_deleted", True) if self._is_account_article(article_id) else self.provider.delete_article(article_id, *args, **kwargs)

    def remove_feed(self, feed_id):
        return False if feed_id == RECOMMENDATIONS_FEED_ID else self.provider.remove_feed(feed_id)

    def update_feed(self, feed_id, **kwargs):
        return False if feed_id == RECOMMENDATIONS_FEED_ID else self.provider.update_feed(feed_id, **kwargs)

    def reset_feed_title(self, feed_id):
        return False if feed_id == RECOMMENDATIONS_FEED_ID else self.provider.reset_feed_title(feed_id)

    def fetch_full_content(self, article_id, url=""):
        return None if self._is_account_article(article_id) else self.provider.fetch_full_content(article_id, url)

    def get_article_chapters(self, article_id):
        if self._is_account_article(article_id):
            from core.utils import fetch_and_store_chapters, get_chapters_from_db
            article = self.get_article_by_id(article_id)
            if article is None:
                return []
            cached = get_chapters_from_db(article_id, cache_key=article_id)
            return cached or fetch_and_store_chapters(article_id, article.media_url, article.media_type, cache_key=article_id)
        return self.provider.get_article_chapters(article_id)

    def refresh_feed(self, feed_id, progress_cb=None):
        if feed_id == RECOMMENDATIONS_FEED_ID:
            from core.youtube_account import list_recommendations, save_recommendations
            token = self.config.get("youtube_account_refresh_token", "")
            save_recommendations({"youtube_account_refresh_token": token}, list_recommendations(token))
            return True
        return self.provider.refresh_feed(feed_id, progress_cb=progress_cb)

    def refresh_feeds_by_ids(self, feed_ids, progress_cb=None, force=True):
        local_ok = self.refresh_feed(RECOMMENDATIONS_FEED_ID) if RECOMMENDATIONS_FEED_ID in feed_ids else True
        remote = [fid for fid in feed_ids if fid != RECOMMENDATIONS_FEED_ID]
        return (self.provider.refresh_feeds_by_ids(remote, progress_cb=progress_cb, force=force) if remote else True) and local_ok
