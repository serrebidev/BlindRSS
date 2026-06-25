from types import SimpleNamespace

from core import db
from gui import mainframe


class _Config:
    def __init__(self, show_image_alt=False):
        self.show_image_alt = show_image_alt

    def get(self, key, default=None):
        if key == "show_image_alt":
            return self.show_image_alt
        return default


class _Host:
    _images_enabled_global = mainframe.MainFrame._images_enabled_global
    _show_images_for_feed = mainframe.MainFrame._show_images_for_feed
    on_set_feed_images = mainframe.MainFrame.on_set_feed_images

    def __init__(self):
        self.config_manager = _Config()
        self._feed_show_images_cache = {}
        self.current_articles = []
        self.list_ctrl = SimpleNamespace(GetFirstSelected=lambda: -1)


def test_feed_image_override_is_cached_across_article_navigation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        db,
        "get_feed_show_images",
        lambda feed_id: calls.append(feed_id) or True,
    )
    host = _Host()

    assert host._show_images_for_feed("feed-1") is True
    assert host._show_images_for_feed("feed-1") is True
    assert calls == ["feed-1"]


def test_inherited_feed_image_setting_stays_dynamic_without_requery(monkeypatch):
    calls = []
    monkeypatch.setattr(
        db,
        "get_feed_show_images",
        lambda feed_id: calls.append(feed_id) or None,
    )
    host = _Host()

    assert host._show_images_for_feed("feed-1") is False
    host.config_manager.show_image_alt = True
    assert host._show_images_for_feed("feed-1") is True
    assert calls == ["feed-1"]


def test_setting_feed_image_override_refreshes_cached_value(monkeypatch):
    writes = []
    monkeypatch.setattr(
        db,
        "set_feed_show_images",
        lambda feed_id, value: writes.append((feed_id, value)) or True,
    )
    host = _Host()
    host._feed_show_images_cache["feed-1"] = False

    host.on_set_feed_images("feed-1", True)

    assert writes == [("feed-1", True)]
    assert host._feed_show_images_cache["feed-1"] is True
