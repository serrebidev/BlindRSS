import abc
from typing import List, Dict, Any, Optional, Tuple
from core import utils
from core.models import Article, Feed

class RSSProvider(abc.ABC):
    """Abstract base class for RSS providers (Local, Feedly, etc.)"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abc.abstractmethod
    def get_name(self) -> str:
        pass

    @abc.abstractmethod
    def refresh(self, progress_cb=None, force: bool = False) -> bool:
        """
        Triggers a sync/refresh of feeds.
        progress_cb: optional callable accepting a feed-state dict per completed feed.
        force: if True, providers should ignore cache headers (ETag/Last-Modified) and force fetch.
        """
        pass

    def refresh_feed(self, feed_id: str, progress_cb=None) -> bool:
        """
        Triggers a sync/refresh of a single feed.
        """
        return False

    @abc.abstractmethod
    def get_feeds(self) -> List[Feed]:
        pass

    @abc.abstractmethod
    def get_articles(self, feed_id: str) -> List[Article]:
        pass

    # Favorites are optional and currently implemented for the Local provider.
    def supports_favorites(self) -> bool:
        return False

    def toggle_favorite(self, article_id: str):
        """Toggle an article's favorite state.

        Returns:
            bool: new favorite state
            None: unsupported or article not found
        """
        return None

    def set_favorite(self, article_id: str, is_favorite: bool) -> bool:
        """Set favorite state for an article (optional)."""
        return False

    def get_articles_page(self, feed_id: str, offset: int = 0, limit: int = 200) -> Tuple[List[Article], int]:
        """Optional pagination helper.

        Providers that can do server-side paging should override this for speed.
        Default implementation calls get_articles() and slices the result.
        """
        articles = self.get_articles(feed_id) or []
        total = len(articles)
        if offset < 0:
            offset = 0
        if limit is None or int(limit) <= 0:
            return [], total
        limit = int(limit)
        return articles[offset:offset + limit], total

    # Optional: providers can override for fast single-article lookup.
    def get_article_by_id(self, article_id: str) -> Optional[Article]:
        return None

    @abc.abstractmethod
    def mark_read(self, article_id: str) -> bool:
        pass

    @abc.abstractmethod
    def mark_unread(self, article_id: str) -> bool:
        pass

    def mark_read_batch(self, article_ids: List[str]) -> bool:
        """Default implementation: loop over single mark_read."""
        success = True
        for aid in article_ids:
            if not self.mark_read(aid):
                success = False
        return success

    # Optional: providers can override to mark all items in a view (feed/category/all).
    def mark_all_read(self, feed_id: str) -> bool:
        return False
    
    @abc.abstractmethod
    def add_feed(self, url: str, category: str = None) -> bool:
        pass
    
    @abc.abstractmethod
    def remove_feed(self, feed_id: str) -> bool:
        pass

    # Optional: providers that allow editing feed metadata can override.
    def supports_feed_edit(self) -> bool:
        return False

    def supports_feed_url_update(self) -> bool:
        return False

    def update_feed(self, feed_id: str, title: str = None, url: str = None, category: str = None) -> bool:
        return False

    # Optional: providers may support resetting a user-customized title back to provider-managed/default.
    def supports_feed_title_reset(self) -> bool:
        return False

    def reset_feed_title(self, feed_id: str) -> bool:
        return False
        
    def import_opml(self, path: str, target_category: str = None) -> bool:
        """Default implementation using utils.parse_opml and add_feed."""
        count = 0
        for title, url, category in utils.parse_opml(path):
            cat = target_category if target_category else category
            if self.add_feed(url, cat):
                count += 1
        return count > 0
        
    def export_opml(self, path: str) -> bool:
        """Default implementation using get_feeds and utils.write_opml."""
        feeds = self.get_feeds()
        return utils.write_opml(feeds, path)

    @abc.abstractmethod
    def get_categories(self) -> List[str]:
        """Returns a list of category names."""
        pass

    @abc.abstractmethod
    def add_category(self, title: str, parent_title: str = None) -> bool:
        pass

    @abc.abstractmethod
    def rename_category(self, old_title: str, new_title: str) -> bool:
        pass

    @abc.abstractmethod
    def delete_category(self, title: str) -> bool:
        pass

    def get_category_hierarchy(self) -> dict:
        """Return {category_title: parent_title} mapping. Uses local DB by default."""
        from core.db import get_category_hierarchy
        return get_category_hierarchy()

    # Optional: providers that offer server-side "fetch original content" can override this.
    def fetch_full_content(self, article_id: str, url: str = ""):
        return None

    # Optional: providers can implement chapter fetching for specific articles.
    def get_article_chapters(self, article_id: str) -> List[Dict]:
        return utils.get_chapters_from_db(article_id)

    # Optional: providers can implement article deletion.
    def supports_article_delete(self) -> bool:
        return False

    def delete_article(self, article_id: str) -> bool:
        return False
