import threading
from contextlib import closing
from types import SimpleNamespace

import pytest

from core import db, youtube_account
from core.models import Article, Feed
from gui import mainframe
from providers.local import LocalProvider
from providers.youtube_account import YouTubeAccountProvider


class Config(dict):
    def set(self, key, value):
        self[key] = value


class Remote:
    def __init__(self):
        self.calls = []
        self.articles = [Article("Remote", "https://example.com", "", "", "", "remote", id="remote-item")]

    def get_feeds(self):
        return [Feed("remote", "Remote", "https://example.com/feed", "Videos")]

    def get_categories(self):
        return ["Videos"]

    def get_articles_page(self, view, offset=0, limit=200):
        self.calls.append((view, offset, limit))
        return self.articles[offset:offset + limit], len(self.articles)

    def get_articles(self, view):
        return self.articles

    def get_name(self):
        return "Miniflux"

    def mark_all_read(self, view):
        self.calls.append(("read", view))
        return True

    def mark_read(self, article_id):
        self.calls.append(("read", article_id))
        return True


@pytest.fixture
def account(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    config = Config(youtube_account_refresh_token="private", youtube_account_category="Videos")
    remote = Remote()
    provider = YouTubeAccountProvider(remote, config)
    youtube_account.save_recommendations(config, [("dQw4w9WgXcQ", "One", "Channel"), ("abcdefghijk", "Two", "Other")])
    return config, provider, remote


def test_recommendations_are_a_private_feed_for_hosted_accounts(account):
    config, provider, remote = account
    feeds = provider.get_feeds()
    rec = feeds[-1]
    assert rec.title == "Recommendations" and rec.category == "Videos"
    assert rec.unread_count == 2
    assert provider.get_name() == "Miniflux"
    articles, total = provider.get_articles_page(rec.id)
    assert total == 2 and [a.title for a in articles] == ["One", "Two"]
    assert articles[0].media_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert remote.calls == []
    assert "private" not in repr(vars(articles[0]))


def test_paging_and_filters_include_recommendations_without_full_remote_load(account):
    config, provider, remote = account
    page, total = provider.get_articles_page("all", offset=1, limit=2)
    assert [a.title for a in page] == ["Two", "Remote"] and total == 3
    assert remote.calls[-1] == ("all", 0, 1)
    first = provider.get_articles(provider.get_feeds()[-1].id)[0]
    assert provider.mark_read(first.id)
    assert len(provider.get_articles("unread:" + first.feed_id)) == 1
    assert provider.set_favorite(first.id, True)
    assert [a.id for a in provider.get_articles("favorites:read:" + first.feed_id)] == [first.id]
    assert provider.get_article_by_id(first.id).is_favorite


def test_updates_preserve_read_favorite_and_deleted_states(account):
    config, provider, remote = account
    first, second = provider.get_articles(provider.get_feeds()[-1].id)
    provider.mark_read(first.id)
    provider.set_favorite(first.id, True)
    provider.delete_article(second.id)
    youtube_account.save_recommendations(config, [("dQw4w9WgXcQ", "Updated", "Channel"), ("abcdefghijk", "Two", "Other")])
    visible = provider.get_articles(first.feed_id)
    assert len(visible) == 1 and visible[0].title == "Updated"
    assert visible[0].is_read and visible[0].is_favorite
    assert provider.mark_unread(first.id)
    assert provider.toggle_favorite(first.id) is False
    assert remote.calls == []


def test_sign_out_and_account_switch_hide_private_cached_articles(account):
    config, provider, remote = account
    article = provider.get_articles(provider.get_feeds()[-1].id)[0]
    config["youtube_account_refresh_token"] = "other-account"
    assert len(provider.get_feeds()) == 1
    assert provider.get_article_by_id(article.id) is None
    config["youtube_account_refresh_token"] = ""
    assert len(provider.get_feeds()) == 1
    assert provider.get_articles_page("all")[1] == 1


def test_mark_all_read_and_managed_feed_actions_never_send_private_ids(account):
    config, provider, remote = account
    feed = provider.get_feeds()[-1]
    assert provider.mark_all_read(feed.id)
    assert provider.get_feeds()[-1].unread_count == 0
    assert remote.calls == []
    assert not provider.remove_feed(feed.id)
    assert not provider.update_feed(feed.id, url="https://example.com")
    assert provider.mark_all_read("category:Videos")
    assert remote.calls == [("read", "category:Videos")]


def test_favorites_remain_visible_when_no_longer_recommended(account):
    config, provider, remote = account
    first = provider.get_articles(provider.get_feeds()[-1].id)[0]
    provider.set_favorite(first.id, True)
    youtube_account.save_recommendations(config, [("abcdefghijk", "Two", "Other")])
    assert [a.title for a in provider.get_articles(first.feed_id)] == ["Two"]
    assert [a.title for a in provider.get_articles("favorites:" + first.feed_id)] == ["One"]


def test_full_local_page_never_requests_zero_remote_limit(account):
    config, provider, remote = account
    page, total = provider.get_articles_page("all", limit=2)
    assert len(page) == 2 and total == 3
    assert remote.calls[-1][2] > 0


def test_cache_reconciliation_preserves_remote_history_and_drops_signed_out_videos(account):
    config, provider, remote = account
    recs = provider.get_articles(provider.get_feeds()[-1].id)
    cached = remote.articles + recs
    assert provider.merge_recommendations("all", cached) is None
    config["youtube_account_refresh_token"] = ""
    assert provider.merge_recommendations("all", cached) == remote.articles
    assert provider.merge_recommendations("remote", remote.articles) is None


def test_chapters_are_stored_in_account_cache_without_remote_requests(account, monkeypatch):
    from core import utils
    config, provider, remote = account
    article = provider.get_articles(provider.get_feeds()[-1].id)[0]
    calls = []
    chapters = [{"start": 0, "title": "Introduction", "href": ""}]

    def fetch(article_id, media_url, media_type, *, cache_key):
        calls.append((article_id, media_url, cache_key))
        utils._replace_stored_chapters(article_id, chapters, cache_key=cache_key)
        return chapters

    monkeypatch.setattr(utils, "fetch_and_store_chapters", fetch)
    assert provider.get_article_chapters(article.id) == chapters
    assert provider.get_article_chapters(article.id) == chapters
    assert calls == [(article.id, article.media_url, article.id)]
    assert remote.calls == []


def test_category_rename_and_move_follow_account_folder_only_after_success(account):
    config, provider, remote = account
    remote.rename_category = lambda old, new: True
    remote.move_category = lambda title, parent: True
    config["youtube_account_category"] = "Videos / Channels"
    assert provider.rename_category("Videos", "Media")
    assert config["youtube_account_category"] == "Media / Channels"
    assert provider.move_category("Media", "Interests")
    assert config["youtube_account_category"] == "Interests / Media / Channels"
    remote.rename_category = lambda old, new: False
    assert not provider.rename_category("Interests", "Failed")
    assert config["youtube_account_category"] == "Interests / Media / Channels"


VIDEO_ONE, VIDEO_TWO, VIDEO_THREE = "abcDEF12345", "ghiJKL67890", "mnoPQR24680"


def _resync_after_earlier_sync(config, remote):
    """Recommend two videos, age them as if synced long ago, then sync again."""
    remote.articles = [Article("RSS item", "https://example.com/item", "", "2000-06-01T00:00:00+00:00", "", "remote", id="remote-item")]
    youtube_account.save_recommendations(config, [(VIDEO_ONE, "Video one", "Example channel"), (VIDEO_TWO, "Video two", "Example channel")])
    with closing(db.get_connection()) as conn, conn:
        conn.executemany("UPDATE youtube_recommendations SET date = ? WHERE video_id = ?",
                         [("2000-01-02T00:00:00+00:00", VIDEO_ONE), ("2000-01-01T00:00:00+00:00", VIDEO_TWO)])
    youtube_account.save_recommendations(config, [
        (VIDEO_THREE, "Video three", "Example channel"),
        (VIDEO_TWO, "Video two, renamed", "Example channel"),
        (VIDEO_ONE, "Video one", "Example channel"),
    ])


def _newest_first(articles):
    # The article list's default date sort.
    return [a.title for a in sorted(articles, key=lambda a: (a.timestamp, a.cache_id), reverse=True)]


def test_resync_keeps_first_seen_date_in_views_mixed_with_rss(account):
    config, provider, remote = account
    _resync_after_earlier_sync(config, remote)
    assert _newest_first(provider.get_articles("all")) == ["Video three", "RSS item", "Video one", "Video two, renamed"]


def test_recommendations_feed_keeps_youtube_order_after_resync(account):
    config, provider, remote = account
    _resync_after_earlier_sync(config, remote)
    order = ["Video three", "Video two, renamed", "Video one"]
    assert _newest_first(provider.get_articles(youtube_account.RECOMMENDATIONS_FEED_ID)) == order
    page, total = provider.get_articles_page("unread:" + youtube_account.RECOMMENDATIONS_FEED_ID)
    assert total == 3 and _newest_first(page) == order


def test_unchanged_sync_leaves_date_sorted_cached_views_alone(account):
    config, provider, remote = account
    _resync_after_earlier_sync(config, remote)
    feed_id = youtube_account.RECOMMENDATIONS_FEED_ID
    for view in ("all", "category:Videos", feed_id):
        cached = sorted(provider.get_articles(view), key=lambda a: (a.timestamp, a.cache_id), reverse=True)
        assert provider.merge_recommendations(view, cached) is None, view
    cached = provider.get_articles(feed_id)
    youtube_account.save_recommendations(config, [
        (VIDEO_ONE, "Video one", "Example channel"),
        (VIDEO_TWO, "Video two, renamed", "Example channel"),
        (VIDEO_THREE, "Video three", "Example channel"),
    ])
    assert _newest_first(provider.merge_recommendations(feed_id, cached)) == ["Video one", "Video two, renamed", "Video three"]


@pytest.fixture
def local_account(monkeypatch, tmp_path):
    """Local provider with one channel feed holding two not yet read videos."""
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "rss.db"))
    db.init_db()
    config = Config(youtube_account_refresh_token="private", youtube_account_category="Videos")
    provider = YouTubeAccountProvider(LocalProvider(config), config)
    with closing(db.get_connection()) as conn, conn:
        conn.execute("INSERT INTO feeds (id, url, title, category) VALUES ('channel', ?, 'Example channel', 'Videos')",
                     ("https://www.youtube.com/feeds/videos.xml?channel_id=UCexampleChannel000000",))
        conn.executemany(
            "INSERT INTO articles (id, feed_id, title, url, content, date, author, is_read) "
            "VALUES (?, 'channel', ?, ?, '', '2000-01-01 00:00:00', 'Example channel', 0)",
            [("yt:video:" + vid, title, "https://www.youtube.com/watch?v=" + vid)
             for vid, title in ((VIDEO_ONE, "Video one"), (VIDEO_TWO, "Video two"))],
        )
    return config, provider


def _recommend(config, provider):
    youtube_account.save_recommendations(config, [(VIDEO_ONE, "Video one", "Example channel"), (VIDEO_TWO, "Video two", "Example channel")])
    return provider.get_articles(youtube_account.RECOMMENDATIONS_FEED_ID)


def _read(provider, article_id):
    return provider.get_article_by_id(article_id).is_read


def test_recommending_a_video_read_in_its_channel_feed_shows_it_read(local_account):
    config, provider = local_account
    assert provider.mark_read("yt:video:" + VIDEO_ONE)
    one, two = _recommend(config, provider)
    assert one.is_read and not two.is_read
    assert provider.get_feeds()[-1].unread_count == 1
    assert [a.title for a in provider.get_articles("unread:" + youtube_account.RECOMMENDATIONS_FEED_ID)] == ["Video two"]
    assert sorted((a.feed_id, a.title) for a in provider.get_articles("read:category:Videos")) == [
        ("channel", "Video one"), (youtube_account.RECOMMENDATIONS_FEED_ID, "Video one")]


def test_read_state_follows_the_video_between_recommendation_and_channel_feed(local_account):
    config, provider = local_account
    one, two = _recommend(config, provider)
    feed_one, feed_two = "yt:video:" + VIDEO_ONE, "yt:video:" + VIDEO_TWO

    assert provider.mark_read(one.id) and _read(provider, feed_one)
    assert provider.mark_unread(feed_one) and not _read(provider, one.id)
    assert provider.mark_read(feed_one) and _read(provider, one.id)
    assert provider.mark_unread(one.id) and not _read(provider, feed_one)

    assert provider.mark_read_batch([one.id, feed_two])
    assert _read(provider, feed_one) and _read(provider, two.id)
    for article_id in (one.id, feed_two):
        provider.mark_unread(article_id)
    assert not any(_read(provider, aid) for aid in (one.id, two.id, feed_one, feed_two))

    assert provider.mark_all_read(youtube_account.RECOMMENDATIONS_FEED_ID)
    assert _read(provider, feed_one) and _read(provider, feed_two)
    for article_id in (one.id, two.id):
        provider.mark_unread(article_id)
    assert provider.mark_all_read("channel")
    assert _read(provider, one.id) and _read(provider, two.id)
    assert provider.get_feeds()[-1].unread_count == 0


def test_hosted_accounts_keep_recommendation_read_state_apart(account):
    config, provider, remote = account
    with closing(db.get_connection()) as conn, conn:
        # Left behind in rss.db by an earlier local profile.
        conn.execute("INSERT INTO articles (id, title, is_read) VALUES (?, 'Video one', 1)", ("yt:video:" + VIDEO_ONE,))
    youtube_account.save_recommendations(config, [(VIDEO_ONE, "Video one", "Example channel")])
    one = provider.get_articles(youtube_account.RECOMMENDATIONS_FEED_ID)[0]
    assert not one.is_read
    assert provider.mark_read(one.id) and provider.mark_unread(one.id)
    with closing(db.get_connection()) as conn:
        assert conn.execute("SELECT is_read FROM articles WHERE id = ?", ("yt:video:" + VIDEO_ONE,)).fetchone() == (1,)
    assert remote.calls == []


class _RunNow:
    """Runs the provider call mark_article_read starts, before returning."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class _ListHost:
    """The main window's mark-read path without a window (no wx.App)."""

    mark_article_read = mainframe.MainFrame.mark_article_read
    mark_article_unread = mainframe.MainFrame.mark_article_unread
    _sync_read_flag_in_cached_views = mainframe.MainFrame._sync_read_flag_in_cached_views
    _sync_read_twin = mainframe.MainFrame._sync_read_twin
    _article_cache_id = mainframe.MainFrame._article_cache_id

    def __init__(self, provider, articles, view_cache):
        self.provider = provider
        self.current_articles = articles
        self.view_cache = view_cache
        self._view_cache_lock = threading.Lock()
        self.status = {}
        self.count_changes = []

    def _set_or_defer_status_cell(self, idx, article, label):
        self.status[idx] = label

    def _update_feed_unread_count_ui(self, feed_id, delta):
        self.count_changes.append((feed_id, delta))


def test_open_lists_show_the_new_state_on_both_copies_of_a_video(local_account, monkeypatch):
    monkeypatch.setattr(mainframe, "threading", SimpleNamespace(Thread=_RunNow, Lock=threading.Lock))
    config, provider = local_account
    _recommend(config, provider)
    feed_id = youtube_account.RECOMMENDATIONS_FEED_ID
    shown = provider.get_articles("category:Videos")
    cached_feed = provider.get_articles(feed_id)
    cached_channel = provider.get_articles("channel")
    host = _ListHost(provider, shown, {feed_id: {"articles": cached_feed}, "channel": {"articles": cached_channel}})
    feed_copy = next(i for i, a in enumerate(shown) if a.id == "yt:video:" + VIDEO_ONE)
    recommended = next(i for i, a in enumerate(shown) if a.feed_id == feed_id and a.title == "Video one")

    host.mark_article_read(feed_copy)
    assert shown[recommended].is_read and host.status == {feed_copy: mainframe._("Read"), recommended: mainframe._("Read")}
    assert sorted(host.count_changes) == [("channel", -1), (feed_id, -1)]
    assert [a.is_read for a in cached_feed] == [True, False]
    assert _read(provider, shown[recommended].id)

    host.mark_article_unread(recommended)
    assert not shown[feed_copy].is_read and host.status[feed_copy] == mainframe._("Unread")
    assert not next(a for a in cached_channel if a.id == "yt:video:" + VIDEO_ONE).is_read
    assert not _read(provider, "yt:video:" + VIDEO_ONE)
